"""Scoring logic: converts enriched API data into a 0–100 score, tier, reasoning, and SDR insights.

Scoring is tiered within each signal (not binary) to create meaningful spread
between mid-market and top-market leads.

Base signal weights (sum to 90, leaving room for size bonus):
    housing_units (25) + renter_pct (20) + median_income (10)
    + fmr_2br (20) + company_news (10) + city_news (5) = 90

ICP size bonus (from icp_classifier):
    LARGE=10, MEDIUM=6, SMALL=2, UNKNOWN=0

Total is capped at 100.

ICP gate:
    If icp_match == "NO", skip all signals and return score=15, tier="Cold".

Tier cutoffs (from config):
    Hot:  70–100
    Warm: 40–69
    Cold:   0–39
"""

from typing import Optional
from urllib.parse import quote_plus
import config


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_lead(enrichment: dict, icp_result: dict = None) -> dict:
    """Score an enriched lead and return score, tier, reasoning, and SDR insights.

    Args:
        enrichment:  Combined output from all API clients. Expected shape::

            {
                "census": {
                    "housing_units": 449452,
                    "renter_percentage": 55.6,
                    "median_income": 86556,
                    "success": True
                },
                "hud": {
                    "fmr_2br": 1852,
                    "metro_name": "Austin-Round Rock, TX MSA",
                    "success": True
                },
                "news": {
                    "company_news": {"article_count": 3, "articles": [...], "success": True},
                    "city_news":    {"article_count": 2, "articles": [...], "success": True}
                },
                "icp": {
                    "icp_match": "YES",
                    "company_size": "LARGE",
                    "size_score_bonus": 10,
                    "success": True
                }
            }

        icp_result: Optional explicit icp dict. If None, falls back to
                    enrichment.get("icp"). Pass explicitly when calling from
                    main.py to keep the caller in control.

    Returns:
        {
            "score": 85,
            "tier": "Hot",
            "reasoning": "...",
            "breakdown": {
                "housing_units": 25, "renter_pct": 20, "median_income": 10,
                "fmr_2br": 20, "company_news": 10, "city_news": 5,
                "company_size_bonus": 10
            },
            "sales_insights": ["...", "...", "..."]
        }
    """
    icp = icp_result if icp_result is not None else (enrichment.get("icp") or {})

    # --- ICP gate: hard-exclude non-ICP companies ---
    if icp.get("icp_match") == "NO":
        icp_desc = icp.get("description", "")
        return {
            "score": 15,
            "tier": "Cold",
            "reasoning": (
                f"Company classified as outside EliseAI's ICP. {icp_desc} "
                "Recommend deprioritising this lead."
            ),
            "breakdown": {
                "housing_units": 0, "renter_pct": 0, "median_income": 0,
                "fmr_2br": 0, "company_news": 0, "city_news": 0,
                "company_size_bonus": 0,
            },
            "sales_insights": [
                "This company does not appear to be a multifamily property manager. "
                "Confirm business model before any outreach."
            ],
        }

    census = enrichment.get("census") or {}
    hud = enrichment.get("hud") or {}
    news = enrichment.get("news") or {}
    company_news = news.get("company_news") or {}
    city_news = news.get("city_news") or {}

    housing_units: Optional[int] = census.get("housing_units")
    renter_pct: Optional[float] = census.get("renter_percentage")
    median_income: Optional[int] = census.get("median_income")
    fmr_2br: Optional[int] = hud.get("fmr_2br")

    size_bonus = icp.get("size_score_bonus", 0) if icp.get("success") else 0

    breakdown = {
        "housing_units":      _score_housing_units(housing_units),
        "renter_pct":         _score_renter_pct(renter_pct),
        "median_income":      _score_median_income(median_income),
        "fmr_2br":            _score_fmr(fmr_2br),
        "company_news":       _score_company_news(company_news),
        "city_news":          _score_city_news(city_news),
        "company_size_bonus": size_bonus,
    }

    score = min(sum(breakdown.values()), 100)
    tier = _assign_tier(score)
    reasoning = _build_reasoning(enrichment, icp)
    sales_insights = _build_sales_insights(enrichment, breakdown, icp)

    return {
        "score": score,
        "tier": tier,
        "reasoning": reasoning,
        "breakdown": breakdown,
        "sales_insights": sales_insights,
    }


# ---------------------------------------------------------------------------
# Per-signal scorers
# ---------------------------------------------------------------------------

def _score_housing_units(units: Optional[int]) -> int:
    """Award 4 / 10 / 18 / 25 pts based on total housing units in the city."""
    if units is None:
        return 0
    if units >= 300_000:
        return 25
    if units >= 100_000:
        return 18
    if units >= 50_000:
        return 10
    return 4


def _score_renter_pct(pct: Optional[float]) -> int:
    """Award 5 / 12 / 20 pts based on renter-occupied percentage."""
    if pct is None:
        return 0
    if pct > 50.0:
        return 20
    if pct >= 40.0:
        return 12
    return 5


def _score_median_income(income: Optional[int]) -> int:
    """Award 3 / 7 / 10 pts based on median household income."""
    if income is None:
        return 0
    if income > 75_000:
        return 10
    if income >= 60_000:
        return 7
    return 3


def _score_fmr(fmr: Optional[int]) -> int:
    """Award 0 / 5 / 12 / 20 pts based on 2-bedroom Fair Market Rent.

    Missing FMR (rural areas with no MSA data) scores 0, not 5, because absence
    of HUD metro coverage is itself a negative market signal.
    """
    if fmr is None:
        return 0
    if fmr > 1_800:
        return 20
    if fmr >= 1_400:
        return 12
    return 5


def _score_company_news(company_news: dict) -> int:
    """Award -5 / 5 / 10 pts based on recent article count for the company."""
    if not company_news.get("success"):
        return 0
    count = company_news.get("article_count", 0)
    if count >= 3:
        return 10
    if count >= 1:
        return 5
    return -5


def _score_city_news(city_news: dict) -> int:
    """Award 5 pts if 1+ recent real estate articles exist for the city."""
    if city_news.get("success") and city_news.get("article_count", 0) >= 1:
        return 5
    return 0


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------

def _assign_tier(score: int) -> str:
    """Return 'Hot', 'Warm', or 'Cold' based on thresholds in config."""
    if score >= config.TIER_HOT_MIN:
        return "Hot"
    if score >= config.TIER_WARM_MIN:
        return "Warm"
    return "Cold"


# ---------------------------------------------------------------------------
# Reasoning string
# ---------------------------------------------------------------------------

def _build_reasoning(enrichment: dict, icp: dict) -> str:
    """Produce a 3-sentence explanation of the score, always covering all signals.

    Structure (fixed, regardless of missing data):
      Sentence 1: ICP classification + market size + renter percentage
      Sentence 2: FMR rental price + median income (or explicit "no data" message)
      Sentence 3: News coverage (or explicit "no coverage" message)
    """
    census = enrichment.get("census") or {}
    hud = enrichment.get("hud") or {}
    news = enrichment.get("news") or {}

    # --- Sentence 1: ICP + market size label + units + renter % ---
    units = census.get("housing_units")
    renter_pct = census.get("renter_percentage")

    icp_match = icp.get("icp_match", "UNCERTAIN") if icp.get("success") else "UNCERTAIN"
    company_size = icp.get("company_size", "UNKNOWN") if icp.get("success") else "UNKNOWN"

    if icp_match == "YES":
        icp_prefix = f"ICP match ({company_size.lower()} operator)."
    elif icp_match == "UNCERTAIN":
        icp_prefix = "ICP classification uncertain."
    else:
        icp_prefix = "Not in ICP."

    if units is not None and units >= 300_000:
        size_label = "Major market"
    elif units is not None and units >= 100_000:
        size_label = "Large market"
    elif units is not None and units >= 50_000:
        size_label = "Mid-size market"
    elif units is not None:
        size_label = "Small market"
    else:
        size_label = "Market"

    units_str = f"{units:,} housing units" if units is not None else "unknown housing units"

    if renter_pct is not None:
        renter_label = "majority-renter" if renter_pct > 50 else "renter"
        renter_str = f"{renter_label} population ({renter_pct}% renters)"
        s1 = f"{icp_prefix} {size_label} with {units_str} and a {renter_str}."
    else:
        s1 = f"{icp_prefix} {size_label} with {units_str}."

    # --- Sentence 2: FMR + income ---
    fmr = hud.get("fmr_2br")
    metro = hud.get("metro_name")
    income = census.get("median_income")

    if fmr:
        metro_tag = f" in {metro}" if metro else ""
        fmr_part = f"2BR FMR of ${fmr:,}{metro_tag}"
    else:
        fmr_part = "No HUD Fair Market Rent data available — likely rural/non-MSA area"

    if income:
        s2 = f"{fmr_part}; median income of ${income:,}."
    else:
        s2 = f"{fmr_part}."

    # --- Sentence 3: news coverage ---
    company_n = (news.get("company_news") or {}).get("article_count", 0)
    city_n = (news.get("city_news") or {}).get("article_count", 0)

    def _art(n: int) -> str:
        return f"{n} article{'s' if n != 1 else ''}"

    if company_n and city_n:
        s3 = f"{_art(company_n)} of company news and {_art(city_n)} of local real estate news signal active market presence."
    elif company_n:
        s3 = f"{_art(company_n)} of recent company news found; limited local real estate news."
    elif city_n:
        s3 = f"No recent company news found; {_art(city_n)} of local real estate news available."
    else:
        s3 = "No recent company or city real estate news found."

    return f"{s1} {s2} {s3}"


# ---------------------------------------------------------------------------
# Sales insights
# ---------------------------------------------------------------------------

def _build_sales_insights(enrichment: dict, breakdown: dict, icp: dict) -> list[str]:
    """Generate 3–4 concrete, EliseAI-specific bullet points for the SDR."""
    census = enrichment.get("census") or {}
    hud = enrichment.get("hud") or {}
    news = enrichment.get("news") or {}
    company_news = news.get("company_news") or {}
    city_news = news.get("city_news") or {}

    insights: list[str] = []

    # ICP uncertainty warning (prepended first)
    if icp.get("success") and icp.get("icp_match") == "UNCERTAIN":
        insights.append(
            "ICP status is uncertain — confirm this company manages multifamily "
            "residential properties before investing in heavy outreach."
        )

    # Housing units → scale opportunity
    units = census.get("housing_units")
    if units and units > 0:
        if units > 100_000:
            insights.append(
                f"With {units:,} housing units, this is a major multifamily market — "
                "high unit count means high ROI on automating leasing and tenant comms."
            )
        elif units >= 50_000:
            insights.append(
                f"{units:,} housing units is a substantial portfolio opportunity for "
                "EliseAI's leasing automation platform."
            )
        else:
            insights.append(
                f"Smaller market ({units:,} units) — EliseAI can help this PM "
                "punch above their weight with AI-driven tenant communication."
            )

    # Renter % → tenant communication volume
    renter_pct = census.get("renter_percentage")
    if renter_pct is not None:
        if renter_pct > 50:
            insights.append(
                f"{renter_pct}% of households rent — majority-renter cities have the "
                "highest leasing velocity and tenant turnover, exactly where EliseAI's "
                "24/7 AI leasing agent delivers the most time savings."
            )
        elif renter_pct >= 40:
            insights.append(
                f"{renter_pct}% renter-occupied households indicates solid multifamily "
                "demand and consistent tenant communication volume."
            )

    # FMR → premium market signal
    fmr = hud.get("fmr_2br")
    metro = hud.get("metro_name", "this metro")
    if fmr and fmr > 0:
        if fmr > 1_800:
            insights.append(
                f"Premium rental market: 2BR FMR is ${fmr:,} in {metro}. "
                "High-rent properties attract tenants who expect responsive, "
                "professional management — a strong fit for EliseAI."
            )
        elif fmr >= 1_400:
            insights.append(
                f"Mid-to-high 2BR FMR (${fmr:,} in {metro}) signals a competitive "
                "rental market where automation gives PMs an edge in responsiveness."
            )
        else:
            insights.append(
                f"2BR FMR of ${fmr:,} in {metro} — even in moderate-rent markets, "
                "EliseAI reduces leasing overhead and improves tenant retention."
            )
    elif breakdown.get("fmr_2br", 0) == 0:
        insights.append(
            "No MSA rental data found — this may be a rural market. "
            "Confirm property type before prioritizing outreach."
        )

    # Company news → warm opener for email
    if company_news.get("article_count", 0) >= 1:
        articles = company_news.get("articles") or []
        first_title = articles[0].get("title", "") if articles else ""
        source = articles[0].get("source", "") if articles else ""
        if first_title:
            source_tag = f" ({source})" if source else ""
            insights.append(
                f"Recent press hook: \"{first_title[:90]}\"{source_tag} — "
                "use this to open the outreach email with a timely, specific reference."
            )
        else:
            insights.append(
                f"Company has {company_news['article_count']} recent news mention(s) — "
                "research for a specific hook before sending outreach."
            )
    elif city_news.get("article_count", 0) >= 1:
        articles = city_news.get("articles") or []
        first_title = articles[0].get("title", "") if articles else ""
        if first_title:
            insights.append(
                f"Local market news angle: \"{first_title[:90]}\" — "
                "reference the local market context even without company-specific news."
            )

    return insights[:4]


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# LinkedIn URL builder
# ---------------------------------------------------------------------------

def build_linkedin_urls(name: str, company: str) -> dict:
    """Generate LinkedIn search URLs for a lead — saves SDRs manual lookup time.

    Args:
        name:    Full name of the contact (e.g. "Jordan Smith").
        company: Company name (e.g. "Greystar").

    Returns:
        {
            "person_search": "https://www.linkedin.com/search/results/people/?keywords=Jordan+Smith+Greystar",
            "company_page":  "https://www.linkedin.com/search/results/companies/?keywords=Greystar",
            "sales_nav":     "https://www.linkedin.com/sales/search/people?firstName=Jordan&lastName=Smith&companyName=Greystar"
        }

        All values are empty strings if name or company is missing.
    """
    if not name or not company:
        return {"person_search": "", "company_page": "", "sales_nav": ""}

    combined         = quote_plus(f"{name.strip()} {company.strip()}")
    company_encoded  = quote_plus(company.strip())

    name_parts = name.strip().split(maxsplit=1)
    first_name = quote_plus(name_parts[0]) if len(name_parts) > 0 else ""
    last_name  = quote_plus(name_parts[1]) if len(name_parts) > 1 else ""

    return {
        "person_search": f"https://www.linkedin.com/search/results/people/?keywords={combined}",
        "company_page":  f"https://www.linkedin.com/search/results/companies/?keywords={company_encoded}",
        "sales_nav":     f"https://www.linkedin.com/sales/search/people?firstName={first_name}&lastName={last_name}&companyName={company_encoded}",
    }


if __name__ == "__main__":
    test_cases = [
        {
            "label": "Hot — Austin TX (ICP YES, LARGE, premium rents, news)",
            "enrichment": {
                "census": {
                    "housing_units": 449452,
                    "renter_percentage": 55.6,
                    "median_income": 86556,
                    "success": True,
                },
                "hud": {
                    "fmr_2br": 1852,
                    "metro_name": "Austin-Round Rock-San Marcos, TX MSA",
                    "success": True,
                },
                "news": {
                    "company_news": {
                        "article_count": 3,
                        "articles": [{"title": "Greystar expands Austin portfolio", "source": "Multifamily Executive", "published_at": "", "url": "", "description": ""}],
                        "success": True,
                    },
                    "city_news": {
                        "article_count": 2,
                        "articles": [{"title": "Austin rental market tightens", "source": "Austin BJ", "published_at": "", "url": "", "description": ""}],
                        "success": True,
                    },
                },
            },
            "icp_result": {
                "icp_match": "YES",
                "company_size": "LARGE",
                "description": "Greystar is the world's largest apartment operator.",
                "size_score_bonus": 10,
                "success": True,
            },
        },
        {
            "label": "Cold ICP gate — Prologis (ICP NO, industrial REIT)",
            "enrichment": {
                "census": {"housing_units": 449452, "renter_percentage": 55.6, "median_income": 86556, "success": True},
                "hud": {"fmr_2br": 1852, "metro_name": "Austin MSA", "success": True},
                "news": {"company_news": {"article_count": 5, "articles": [], "success": True}, "city_news": {"article_count": 2, "articles": [], "success": True}},
            },
            "icp_result": {
                "icp_match": "NO",
                "company_size": "LARGE",
                "description": "Prologis manages industrial/logistics properties, not residential apartments.",
                "size_score_bonus": 10,
                "success": True,
            },
        },
        {
            "label": "Cold rural — Liberal KS (ICP UNCERTAIN, SMALL, no HUD data)",
            "enrichment": {
                "census": {"housing_units": 9_800, "renter_percentage": 35.0, "median_income": 51_000, "success": True},
                "hud": {"fmr_2br": None, "metro_name": None, "success": False},
                "news": {"company_news": {"article_count": 0, "articles": [], "success": True}, "city_news": {"article_count": 0, "articles": [], "success": True}},
            },
            "icp_result": {
                "icp_match": "UNCERTAIN",
                "company_size": "SMALL",
                "description": "Heritage Acres — insufficient information to confirm multifamily focus.",
                "size_score_bonus": 2,
                "success": True,
            },
        },
    ]

    for case in test_cases:
        result = score_lead(case["enrichment"], icp_result=case["icp_result"])
        print(f"\n{'=' * 60}")
        print(f"  {case['label']}")
        print(f"{'=' * 60}")
        print(f"  Score:     {result['score']} / 100")
        print(f"  Tier:      {result['tier']}")
        print(f"  Breakdown: {result['breakdown']}")
        print(f"\n  Reasoning:")
        print(f"    {result['reasoning']}")
        print(f"\n  Sales insights:")
        for bullet in result["sales_insights"]:
            print(f"    • {bullet}")

    # LinkedIn URL builder test
    print(f"\n{'=' * 60}")
    print("  LinkedIn URL builder")
    print(f"{'=' * 60}")
    test_urls = build_linkedin_urls("Jordan Smith", "Greystar")
    print("  Jordan Smith @ Greystar:")
    for url_type, url in test_urls.items():
        print(f"    {url_type}: {url}")
    print()
    empty_urls = build_linkedin_urls("", "")
    print(f"  Empty name/company → {empty_urls}")
