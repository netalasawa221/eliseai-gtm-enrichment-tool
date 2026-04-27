"""NewsAPI wrapper.

Searches for:
  1. Recent news about a specific company (for lead scoring + email hooks)
  2. Recent real estate / rental market news in a city (for scoring signal)

Free-tier limits: 100 requests/day, articles up to 1 month old.
Each lead uses 2 requests (one per function). At 100 req/day that's 50 leads/day
on the free plan before hitting the cap.

Docs: https://newsapi.org/docs/endpoints/everything

Typical usage:
    from clients.news_client import get_company_news, get_city_real_estate_news

    result = get_company_news("Greystar")
    # {
    #   "company": "Greystar",
    #   "article_count": 2,
    #   "articles": [{"title": "...", "description": "...",
    #                 "url": "...", "published_at": "...", "source": "..."}],
    #   "success": True, "error": None
    # }
"""

import requests
import config


NEWSAPI_URL = "https://newsapi.org/v2/everything"


def get_company_news(company: str, max_results: int = 3) -> dict:
    """Search for recent news articles about a company.

    Uses an exact-phrase query (company name in quotes) sorted by publication
    date so the most recent coverage surfaces first.

    Args:
        company:     Company name, e.g. "Greystar" or "AvalonBay Communities".
        max_results: Maximum articles to return (default 3).

    Returns:
        Always returns a dict — never raises.

        {
            "company": "Greystar",
            "article_count": 2,
            "articles": [
                {
                    "title": "Greystar acquires ...",
                    "description": "...",
                    "url": "https://...",
                    "published_at": "2024-03-15T10:00:00Z",
                    "source": "Multifamily Executive"
                }
            ],
            "success": True,
            "error": None
        }

        On failure: success=False, article_count=0, articles=[], error=message.
        On 0 results: success=True, article_count=0, articles=[].
    """
    base = {"company": company, "article_count": 0, "articles": []}

    # Exact-phrase match reduces false positives for common company names
    query = f'"{company}"'
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max_results,
        "apiKey": config.NEWS_API_KEY,
    }

    articles, error = _call_newsapi(params)
    if error:
        return {**base, "success": False, "error": error}

    return {
        **base,
        "article_count": len(articles),
        "articles": articles,
        "success": True,
        "error": None,
    }


def get_city_real_estate_news(city: str, state: str, max_results: int = 3) -> dict:
    """Search for recent real estate and rental market news in a city.

    Builds a query that anchors on the city name and requires at least one
    real estate keyword, keeping results relevant to multifamily / housing.

    Args:
        city:        City name, e.g. "Austin".
        state:       Two-letter abbreviation, e.g. "TX".
        max_results: Maximum articles to return (default 3).

    Returns:
        Always returns a dict — never raises.

        {
            "city": "Austin",
            "state": "TX",
            "article_count": 1,
            "articles": [...],
            "success": True,
            "error": None
        }

        On failure: success=False, article_count=0, articles=[], error=message.
    """
    base = {"city": city, "state": state, "article_count": 0, "articles": []}

    # AND semantics: city must appear, plus at least one housing keyword.
    # Quoting the city name reduces results about unrelated uses (e.g. "Austin"
    # the person vs "Austin" the city).
    query = f'"{city}" AND (rental OR "real estate" OR housing OR multifamily OR apartments)'
    params = {
        "q": query,
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": max_results,
        "apiKey": config.NEWS_API_KEY,
    }

    articles, error = _call_newsapi(params)
    if error:
        return {**base, "success": False, "error": error}

    return {
        **base,
        "article_count": len(articles),
        "articles": articles,
        "success": True,
        "error": None,
    }


def _call_newsapi(params: dict) -> tuple[list[dict], str | None]:
    """Execute a NewsAPI /everything request and return (articles, error).

    Args:
        params: Full query parameter dict (including apiKey).

    Returns:
        (articles, None)        on success — articles is a list of normalized dicts.
        ([], error_message)     on any failure — caller decides how to surface it.
    """
    try:
        response = requests.get(NEWSAPI_URL, params=params, timeout=10)
    except requests.RequestException as exc:
        return [], f"NewsAPI request failed: {exc}"

    if response.status_code == 401:
        return [], "NewsAPI authentication failed — check NEWS_API_KEY in .env"
    if response.status_code == 429:
        return [], "NewsAPI rate limit reached (100 req/day on free tier)"
    if not response.ok:
        return [], f"NewsAPI returned HTTP {response.status_code}"

    body = response.json()
    if body.get("status") != "ok":
        message = body.get("message", "Unknown NewsAPI error")
        return [], f"NewsAPI error: {message}"

    raw_articles: list[dict] = body.get("articles", [])
    normalized = [_normalize_article(a) for a in raw_articles]
    return normalized, None


def _normalize_article(raw: dict) -> dict:
    """Flatten a raw NewsAPI article into a compact, consistently-keyed dict."""
    return {
        "title": raw.get("title") or "",
        "description": raw.get("description") or "",
        "url": raw.get("url") or "",
        "published_at": raw.get("publishedAt") or "",
        "source": (raw.get("source") or {}).get("name") or "",
    }


if __name__ == "__main__":
    print("=" * 55)
    print("COMPANY NEWS TESTS")
    print("=" * 55)

    company_tests = [
        "Greystar",
        "AvalonBay Communities",
        "RandomFakeCompanyXYZ",
    ]

    for company in company_tests:
        result = get_company_news(company)
        print(f"\n  Company: {company}")
        print(f"  Success: {result['success']}")
        if not result["success"]:
            print(f"  Error:   {result['error']}")
        else:
            print(f"  Articles found: {result['article_count']}")
            if result["articles"]:
                top = result["articles"][0]
                print(f"  Top article: [{top['source']}] {top['title'][:80]}")
                print(f"  Published:   {top['published_at'][:10]}")

    print()
    print("=" * 55)
    print("CITY REAL ESTATE NEWS TESTS")
    print("=" * 55)

    city_tests = [
        ("Austin", "TX"),
        ("Newark", "NJ"),
        ("Liberal", "KS"),
    ]

    for city, state in city_tests:
        result = get_city_real_estate_news(city, state)
        print(f"\n  City: {city}, {state}")
        print(f"  Success: {result['success']}")
        if not result["success"]:
            print(f"  Error:   {result['error']}")
        else:
            print(f"  Articles found: {result['article_count']}")
            if result["articles"]:
                top = result["articles"][0]
                print(f"  Top article: [{top['source']}] {top['title'][:80]}")
