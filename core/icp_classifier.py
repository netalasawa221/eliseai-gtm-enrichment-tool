"""ICP (Ideal Customer Profile) classification via Claude.

Determines whether a company is in EliseAI's ICP — a multifamily property
manager or operator who would benefit from AI-powered leasing and tenant
communication — and estimates company size from news context.

EliseAI's ICP:
  - Multifamily property managers or operators
  - Manages apartment communities (not single-family, commercial, or retail)
  - Mid-market to enterprise scale (hundreds to tens of thousands of units)
  - US-based

Company size tiers:
  LARGE  — Major national/regional operator (10,000+ units or top-20 NMHC ranking)
  MEDIUM — Mid-market operator (500–9,999 units or regional footprint)
  SMALL  — Smaller local/regional operator (<500 units or very limited footprint)
  UNKNOWN — Insufficient information to determine size
"""

import json

from clients.llm_client import complete

_SYSTEM_PROMPT = """\
You are an expert B2B sales analyst helping EliseAI, an AI company that sells \
AI leasing agents and tenant communication tools to multifamily residential \
property managers.

EliseAI's Ideal Customer Profile (ICP):
- Companies that own, operate, or manage multifamily residential apartment communities
- US-based operations
- Mid-market to enterprise scale preferred (hundreds to tens of thousands of units)
- NOT a fit: single-family rentals, commercial real estate, retail, hospitality, \
  student housing only, government housing authorities

Your task: classify a given company as ICP or not, estimate size, and describe \
what you know.

Respond with ONLY a valid JSON object — no markdown fences, no prose, no \
explanation outside the JSON. Use exactly these keys:

{
  "icp_match": "YES" | "NO" | "UNCERTAIN",
  "company_size": "LARGE" | "MEDIUM" | "SMALL" | "UNKNOWN",
  "description": "<one sentence about the company and why it is or isn't ICP>"
}

icp_match rules:
  YES       — Clearly a multifamily PM/operator (apartments, communities, units)
  NO        — Clearly not (commercial, single-family only, wrong industry)
  UNCERTAIN — Not enough info, or mixed portfolio

company_size rules:
  LARGE   — National/major regional operator, 10,000+ units, or NMHC top 50
  MEDIUM  — Regional mid-market operator, 500–9,999 units
  SMALL   — Local or small operator, <500 units or very limited footprint
  UNKNOWN — Cannot determine from the information provided
"""


def classify_icp(company: str, news_headlines: list[str]) -> dict:
    """Classify whether a company is in EliseAI's ICP using Claude.

    Args:
        company:        Company name (e.g. "Greystar").
        news_headlines: List of recent article titles mentioning the company.
                        May be empty if no news was found.

    Returns:
        {
            "company":         str,
            "icp_match":       "YES" | "NO" | "UNCERTAIN",
            "company_size":    "LARGE" | "MEDIUM" | "SMALL" | "UNKNOWN",
            "description":     str,
            "size_score_bonus": int,   # 10 / 6 / 2 / 0
            "success":         bool,
            "error":           str | None
        }
    """
    headlines_block = (
        "\n".join(f"- {h}" for h in news_headlines)
        if news_headlines
        else "(no recent news headlines available)"
    )

    user_prompt = (
        f"Company: {company}\n\n"
        f"Recent news headlines:\n{headlines_block}\n\n"
        "Classify this company."
    )

    response = complete(system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=256)

    if not response.get("success"):
        return _failed_result(company, response.get("error", "LLM call failed"))

    raw = response.get("text", "").strip()
    # Strip markdown code fences if Claude wraps the JSON anyway
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _failed_result(company, f"JSON parse error: {exc} — raw: {raw[:120]}")

    icp_match = parsed.get("icp_match", "UNCERTAIN")
    company_size = parsed.get("company_size", "UNKNOWN")
    description = parsed.get("description", "")

    size_bonus_map = {"LARGE": 10, "MEDIUM": 6, "SMALL": 2, "UNKNOWN": 0}
    size_score_bonus = size_bonus_map.get(company_size, 0)

    return {
        "company": company,
        "icp_match": icp_match,
        "company_size": company_size,
        "description": description,
        "size_score_bonus": size_score_bonus,
        "success": True,
        "error": None,
    }


def _failed_result(company: str, error: str) -> dict:
    return {
        "company": company,
        "icp_match": "UNCERTAIN",
        "company_size": "UNKNOWN",
        "description": "",
        "size_score_bonus": 0,
        "success": False,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    test_cases = [
        {
            "company": "Greystar",
            "headlines": [
                "Greystar expands Austin portfolio with 500-unit acquisition",
                "Greystar Real Estate Partners closes $1.5B fund for multifamily",
            ],
        },
        {
            "company": "AvalonBay Communities",
            "headlines": [
                "AvalonBay reports strong Q1 occupancy across 85,000+ units",
            ],
        },
        {
            "company": "High Desert Property Management",
            "headlines": [],
        },
        {
            "company": "Prologis",
            "headlines": [
                "Prologis acquires industrial warehouse portfolio in midwest",
            ],
        },
        {
            "company": "Heritage Acres",
            "headlines": [],
        },
    ]

    for tc in test_cases:
        result = classify_icp(tc["company"], tc["headlines"])
        print(f"\n{'=' * 55}")
        print(f"  {tc['company']}")
        print(f"{'=' * 55}")
        print(f"  ICP Match:    {result['icp_match']}")
        print(f"  Size:         {result['company_size']} (bonus: +{result['size_score_bonus']})")
        print(f"  Description:  {result['description']}")
        print(f"  Success:      {result['success']}")
        if not result["success"]:
            print(f"  Error:        {result['error']}")
