"""Orchestrates all API calls for a single lead and returns a unified enrichment dict.

Calls four data sources sequentially:
  1. US Census ACS  — city demographics (housing units, renter %, income)
  2. HUD FMR        — metro-level Fair Market Rents
  3. NewsAPI        — recent articles about the company
  4. NewsAPI        — recent real estate news in the city

Each client is called defensively: if one fails (API down, bad key, city not
found), enrichment continues with the remaining clients and the failure is
recorded in `error_summary`. The scorer and email generator both treat missing
data gracefully, so a partial enrichment is always better than a crash.
"""

from clients.census_client import get_city_demographics
from clients.hud_client import get_fair_market_rent
from clients.news_client import get_company_news, get_city_real_estate_news
from core.icp_classifier import classify_icp


def enrich_lead(lead: dict) -> dict:
    """Fetch all external data for a lead and return a unified enrichment dict.

    Prints a progress line per API call so failures are visible immediately
    during batch runs.

    Args:
        lead: Lead row dict. Expected keys: name, email, company,
              property_address, city, state, country.

    Returns:
        {
            "census": {
                "housing_units": int | None,
                "renter_percentage": float | None,
                "median_income": int | None,
                "success": bool,
                "error": str | None
            },
            "hud": {
                "fmr_1br": int | None,
                "fmr_2br": int | None,
                "fmr_3br": int | None,
                "metro_name": str | None,
                "success": bool,
                "error": str | None
            },
            "news": {
                "company_news": {
                    "article_count": int,
                    "articles": list[dict],
                    "success": bool,
                    "error": str | None
                },
                "city_news": {
                    "article_count": int,
                    "articles": list[dict],
                    "success": bool,
                    "error": str | None
                }
            },
            "any_errors": bool,
            "error_summary": list[str]
        }
    """
    name = lead.get("name", "Unknown")
    company = lead.get("company", "Unknown")
    city = lead.get("city", "")
    state = lead.get("state", "")
    country = (lead.get("country") or "US").strip().upper()
    is_us = country in {"US", "USA", "UNITED STATES"}

    print(f"\n[{name} / {company} / {city}, {state}]")
    if not is_us:
        print(f"  ⚠ Non-US lead (country={country}) — Census and HUD are US-only; skipping.")

    error_summary: list[str] = []

    # ------------------------------------------------------------------
    # 1. Census demographics (US only)
    # ------------------------------------------------------------------
    if not is_us:
        census = _failed_census(f"Census API is US-only; lead country is '{country}'")
        print(f"  – Census:       SKIPPED (non-US)")
    else:
        try:
            census = get_city_demographics(city, state)
        except Exception as exc:
            census = _failed_census(f"Unexpected error: {exc}")

        if census.get("success"):
            units = census.get("housing_units")
            renter = census.get("renter_percentage")
            units_str = f"{units // 1000}K units" if units else "? units"
            renter_str = f"{renter}% renters" if renter is not None else "? renters"
            print(f"  ✓ Census:       OK ({units_str}, {renter_str})")
        else:
            error_summary.append("Census")
            print(f"  ✗ Census:       FAILED ({census.get('error')})")

    # ------------------------------------------------------------------
    # 2. HUD Fair Market Rents (US only)
    # ------------------------------------------------------------------
    if not is_us:
        hud = _failed_hud(f"HUD API is US-only; lead country is '{country}'")
        print(f"  – HUD:          SKIPPED (non-US)")
    else:
        try:
            hud = get_fair_market_rent(city, state)
        except Exception as exc:
            hud = _failed_hud(f"Unexpected error: {exc}")

        if hud.get("success"):
            fmr = hud.get("fmr_2br")
            fmr_str = f"${fmr:,} 2BR FMR" if fmr else "no 2BR FMR"
            print(f"  ✓ HUD:          OK ({fmr_str})")
        else:
            error_summary.append("HUD")
            print(f"  ✗ HUD:          FAILED ({hud.get('error')})")

    # ------------------------------------------------------------------
    # 3. Company news
    # ------------------------------------------------------------------
    try:
        company_news = get_company_news(company)
    except Exception as exc:
        company_news = _failed_news(company=company, error=f"Unexpected error: {exc}")

    if company_news.get("success"):
        count = company_news.get("article_count", 0)
        print(f"  ✓ Company news: OK ({count} article{'s' if count != 1 else ''})")
    else:
        error_summary.append("Company News")
        print(f"  ✗ Company news: FAILED ({company_news.get('error')})")

    # ------------------------------------------------------------------
    # 4. City real estate news
    # ------------------------------------------------------------------
    try:
        city_news = get_city_real_estate_news(city, state)
    except Exception as exc:
        city_news = _failed_news(city=city, state=state, error=f"Unexpected error: {exc}")

    if city_news.get("success"):
        count = city_news.get("article_count", 0)
        print(f"  ✓ City news:    OK ({count} article{'s' if count != 1 else ''})")
    else:
        error_summary.append("City News")
        print(f"  ✗ City news:    FAILED ({city_news.get('error')})")

    # ------------------------------------------------------------------
    # 5. ICP classification (uses company name + news headlines)
    # ------------------------------------------------------------------
    headlines = [
        a.get("title", "")
        for a in (company_news.get("articles") or [])
        if a.get("title")
    ]

    try:
        icp = classify_icp(company, headlines)
    except Exception as exc:
        icp = {
            "company": company,
            "icp_match": "UNCERTAIN",
            "company_size": "UNKNOWN",
            "description": "",
            "size_score_bonus": 0,
            "success": False,
            "error": f"Unexpected error: {exc}",
        }

    if icp.get("success"):
        match = icp.get("icp_match", "UNCERTAIN")
        size = icp.get("company_size", "UNKNOWN")
        desc = icp.get("description", "")
        icon = "✓" if match == "YES" else ("⚠" if match == "UNCERTAIN" else "✗")
        print(
            f"  {icon} ICP check:   {match} | Size: {size} | "
            f"{desc[:55]}{'…' if len(desc) > 55 else ''}"
        )
    else:
        error_summary.append("icp_classifier")
        print(f"  ✗ ICP check:   FAILED ({icp.get('error')})")

    # ------------------------------------------------------------------
    # Assemble and return
    # ------------------------------------------------------------------
    return {
        "census": census,
        "hud": hud,
        "news": {
            "company_news": company_news,
            "city_news": city_news,
        },
        "icp": icp,
        "any_errors": len(error_summary) > 0,
        "error_summary": error_summary,
    }


# ---------------------------------------------------------------------------
# Safe fallback constructors (used when a client raises unexpectedly)
# ---------------------------------------------------------------------------

def _failed_census(error: str) -> dict:
    return {
        "housing_units": None,
        "renter_percentage": None,
        "median_income": None,
        "success": False,
        "error": error,
    }


def _failed_hud(error: str) -> dict:
    return {
        "fmr_1br": None,
        "fmr_2br": None,
        "fmr_3br": None,
        "metro_name": None,
        "success": False,
        "error": error,
    }


def _failed_news(**kwargs) -> dict:
    """kwargs may include company=, city=, state= for context, plus error=."""
    base = {
        "article_count": 0,
        "articles": [],
        "success": False,
        "error": kwargs.get("error", "Unknown error"),
    }
    if "company" in kwargs:
        base["company"] = kwargs["company"]
    if "city" in kwargs:
        base["city"] = kwargs["city"]
    if "state" in kwargs:
        base["state"] = kwargs["state"]
    return base


if __name__ == "__main__":
    import json

    test_lead = {
        "name": "Jordan Smith",
        "email": "jordan@greystar.com",
        "company": "Greystar",
        "property_address": "123 Congress Ave",
        "city": "Austin",
        "state": "TX",
        "country": "US",
    }

    enrichment = enrich_lead(test_lead)

    print("\n" + "=" * 55)
    print("  Full enrichment dict")
    print("=" * 55)

    # Print a clean summary without dumping all article text
    summary = {
        "census": enrichment["census"],
        "hud": enrichment["hud"],
        "news": {
            "company_news": {
                k: v for k, v in enrichment["news"]["company_news"].items()
                if k != "articles"
            },
            "city_news": {
                k: v for k, v in enrichment["news"]["city_news"].items()
                if k != "articles"
            },
        },
        "any_errors": enrichment["any_errors"],
        "error_summary": enrichment["error_summary"],
    }
    print(json.dumps(summary, indent=2))

    # Show article titles separately if any were returned
    for source, key in [("Company", "company_news"), ("City", "city_news")]:
        articles = enrichment["news"][key].get("articles", [])
        if articles:
            print(f"\n  {source} news headlines:")
            for a in articles:
                print(f"    [{a.get('source', '?')}] {a.get('title', '?')[:80]}")
