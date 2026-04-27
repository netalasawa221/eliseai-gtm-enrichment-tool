"""Generates personalized cold outreach emails via Claude.

Flow:
  1. _build_prompt() assembles a structured USER prompt from lead + enrichment + scoring data
  2. complete() sends it to Claude with a fixed SYSTEM prompt
  3. _parse_response() extracts the SUBJECT and BODY from Claude's structured reply
  4. generate_outreach_email() wraps all of this and returns a consistent dict

Prompt format contract with Claude:
  The user prompt instructs Claude to return exactly:
      SUBJECT: <one line>
      BODY:
      <email body>

  _parse_response() splits on those markers. If Claude ignores the format,
  the whole raw text is returned as the body with a fallback subject.
"""

from clients.llm_client import complete


_SYSTEM_PROMPT = """You are an expert B2B SDR writing outreach emails for EliseAI, an AI \
platform that helps property managers automate leasing conversations, tenant communication, \
and maintenance requests. Your emails are short, specific, and avoid generic sales language. \
You use real market data to demonstrate you've done your research.

Constraints:
- Under 120 words total (subject + body)
- Professional but conversational — never pushy or salesy
- Open with the most compelling hook available (company news if present, else a market data point)
- Mention exactly ONE market data point inline (e.g. "55% of Austin households rent")
- Close with this exact soft CTA: "Worth a 15-min chat next week?"
- No fluff, no filler sentences, no em-dashes as decoration"""


def generate_outreach_email(lead: dict, enrichment: dict, scoring: dict) -> dict:
    """Generate a personalized cold outreach email for a lead.

    Args:
        lead:       Original lead row — expects at minimum: name, company, city, state.
        enrichment: Combined API data (keys: census, hud, news).
        scoring:    Scorer output (keys: score, tier, reasoning, sales_insights).

    Returns:
        Always returns a dict — never raises.

        On success:
            {
                "subject": "Quick question about Greystar's Austin portfolio",
                "body": "Hi Jordan, ...",
                "success": True,
                "error": None
            }

        On failure (Claude API down, bad key, etc.):
            {"subject": None, "body": None, "success": False, "error": "..."}
    """
    user_prompt = _build_prompt(lead, enrichment, scoring)
    result = complete(system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=300)

    if not result["success"]:
        return {"subject": None, "body": None, "success": False, "error": result["error"]}

    subject, body = _parse_response(result["text"])
    return {"subject": subject, "body": body, "success": True, "error": None}


def _build_prompt(lead: dict, enrichment: dict, scoring: dict) -> str:
    """Assemble the USER portion of the Claude prompt.

    Pulls data from three sources and formats each section so Claude receives
    clean, labelled context rather than raw nested dicts.

    Missing values are replaced with explicit "Not available" strings so Claude
    never sees Python's "None" or empty strings in the prompt.

    Args:
        lead:       Lead row dict.
        enrichment: Enricher output dict.
        scoring:    Scorer output dict.

    Returns:
        A multi-section prompt string.
    """
    census = enrichment.get("census") or {}
    hud = enrichment.get("hud") or {}
    news = enrichment.get("news") or {}
    company_news = news.get("company_news") or {}
    city_news = news.get("city_news") or {}

    # --- Lead identity ---
    name = lead.get("name") or "there"
    first_name = name.split()[0] if name != "there" else "there"
    company = lead.get("company") or "your company"
    city = lead.get("city") or "your city"
    state = lead.get("state") or ""
    location = f"{city}, {state}".strip(", ")

    # --- Market data ---
    housing_units = census.get("housing_units")
    renter_pct = census.get("renter_percentage")
    median_income = census.get("median_income")
    fmr_2br = hud.get("fmr_2br")
    metro_name = hud.get("metro_name")

    units_str = f"{housing_units:,}" if housing_units else "Not available"
    renter_str = f"{renter_pct}%" if renter_pct is not None else "Not available"
    income_str = f"${median_income:,}" if median_income else "Not available"
    fmr_str = f"${fmr_2br:,}" if fmr_2br else "Not available (likely rural/non-MSA area)"
    metro_str = metro_name or location

    # --- News headlines (top 1 each, clean text only) ---
    company_articles = company_news.get("articles") or []
    city_articles = city_news.get("articles") or []

    def _headline(articles: list[dict]) -> str:
        if not articles:
            return "No recent news found"
        a = articles[0]
        title = (a.get("title") or "").strip()
        source = (a.get("source") or "").strip()
        date = (a.get("published_at") or "")[:10]
        if not title:
            return "No recent news found"
        parts = [f'"{title}"']
        if source:
            parts.append(f"({source})")
        if date:
            parts.append(date)
        return " ".join(parts)

    company_news_str = _headline(company_articles)
    city_news_str = _headline(city_articles)

    # --- Tier context (guides Claude's tone) ---
    tier = scoring.get("tier", "Unknown")
    score = scoring.get("score", 0)

    return f"""Write a cold outreach email to the following lead.

LEAD:
  First name: {first_name}
  Company: {company}
  Location: {location}

MARKET DATA ({metro_str}):
  Total housing units: {units_str}
  Renter population: {renter_str}
  Median household income: {income_str}
  Fair Market Rent (2BR): {fmr_str}
  Lead tier: {tier} (score {score}/100)

RECENT NEWS ABOUT {company.upper()}:
  {company_news_str}

RECENT LOCAL REAL ESTATE NEWS ({city}):
  {city_news_str}

INSTRUCTIONS:
  - Address {first_name} by first name
  - If company news is available (not "No recent news found"), open by referencing it
  - Otherwise open with the most relevant market data point
  - Mention exactly one specific number from the market data above
  - Keep the full email under 120 words
  - Close with: "Worth a 15-min chat next week?"

Return your response in EXACTLY this format (no extra text before or after):
SUBJECT: <one-line subject>
BODY:
<email body>"""


def _parse_response(raw: str) -> tuple[str, str]:
    """Extract subject and body from Claude's structured response.

    Expects:
        SUBJECT: Quick question about Greystar's Austin portfolio
        BODY:
        Hi Jordan, ...

    Falls back to a generic subject + full raw text as body if the markers
    are missing (Claude occasionally ignores format instructions).

    Args:
        raw: Raw text from Claude.

    Returns:
        (subject, body) as a tuple of stripped strings.
    """
    subject = "Following up on EliseAI"
    body = raw.strip()

    lines = raw.strip().splitlines()
    subject_line = next((l for l in lines if l.upper().startswith("SUBJECT:")), None)
    body_marker = next((i for i, l in enumerate(lines) if l.strip().upper() == "BODY:"), None)

    if subject_line:
        subject = subject_line.split(":", 1)[1].strip()

    if body_marker is not None:
        body = "\n".join(lines[body_marker + 1:]).strip()

    return subject, body


if __name__ == "__main__":
    # Reuse the same mock data as scorer.py tests
    test_cases = [
        {
            "label": "Hot lead — Austin TX (Greystar, company news available)",
            "lead": {
                "name": "Jordan Marsh",
                "company": "Greystar Real Estate Partners",
                "email": "jordan.marsh@greystarpm.com",
                "city": "Austin",
                "state": "TX",
                "property_address": "2400 Barton Creek Blvd",
            },
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
                        "articles": [{
                            "title": "Greystar expands Austin portfolio with 500-unit acquisition",
                            "source": "Multifamily Executive",
                            "published_at": "2024-03-10T09:00:00Z",
                            "url": "", "description": "",
                        }],
                        "success": True,
                    },
                    "city_news": {
                        "article_count": 2,
                        "articles": [{
                            "title": "Austin rental market tightens as demand surges",
                            "source": "Austin Business Journal",
                            "published_at": "2024-03-08T00:00:00Z",
                            "url": "", "description": "",
                        }],
                        "success": True,
                    },
                },
            },
            "scoring": {
                "score": 100, "tier": "Hot",
                "reasoning": "Major market with 449,452 housing units.",
                "sales_insights": [],
            },
        },
        {
            "label": "Warm lead — Boise ID (High Desert PM, no company news)",
            "lead": {
                "name": "Ashley Nguyen",
                "company": "High Desert Property Management",
                "email": "a.nguyen@highdesertpm.com",
                "city": "Boise",
                "state": "ID",
                "property_address": "3150 N Cole Rd",
            },
            "enrichment": {
                "census": {
                    "housing_units": 105_000,
                    "renter_percentage": 43.2,
                    "median_income": 67_500,
                    "success": True,
                },
                "hud": {
                    "fmr_2br": 1655,
                    "metro_name": "Boise City, ID HUD Metro FMR Area",
                    "success": True,
                },
                "news": {
                    "company_news": {"article_count": 0, "articles": [], "success": True},
                    "city_news": {
                        "article_count": 1,
                        "articles": [{
                            "title": "Boise multifamily construction hits 10-year high",
                            "source": "Idaho Statesman",
                            "published_at": "2024-03-01T00:00:00Z",
                            "url": "", "description": "",
                        }],
                        "success": True,
                    },
                },
            },
            "scoring": {
                "score": 59, "tier": "Warm",
                "reasoning": "Large market with 105,000 housing units.",
                "sales_insights": [],
            },
        },
        {
            "label": "Cold lead — Liberal KS (Heritage Acres, rural, no data)",
            "lead": {
                "name": "Tom Burgess",
                "company": "Heritage Acres Property Management",
                "email": "tom@heritageacrespm.com",
                "city": "Liberal",
                "state": "KS",
                "property_address": "412 S Main St",
            },
            "enrichment": {
                "census": {
                    "housing_units": 9_800,
                    "renter_percentage": 35.0,
                    "median_income": 51_000,
                    "success": True,
                },
                "hud": {
                    "fmr_2br": None,
                    "metro_name": None,
                    "success": False,
                },
                "news": {
                    "company_news": {"article_count": 0, "articles": [], "success": True},
                    "city_news": {"article_count": 0, "articles": [], "success": True},
                },
            },
            "scoring": {
                "score": 15, "tier": "Cold",
                "reasoning": "Small market with 9,800 housing units.",
                "sales_insights": [],
            },
        },
    ]

    for case in test_cases:
        print(f"\n{'=' * 65}")
        print(f"  {case['label']}")
        print(f"{'=' * 65}")
        result = generate_outreach_email(case["lead"], case["enrichment"], case["scoring"])
        if result["success"]:
            print(f"  SUBJECT: {result['subject']}")
            print(f"\n  BODY:")
            for line in result["body"].splitlines():
                print(f"    {line}")
        else:
            print(f"  FAILED: {result['error']}")
