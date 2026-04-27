"""API keys (loaded from .env) and scoring thresholds."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
CENSUS_API_KEY: str = os.environ.get("CENSUS_API_KEY", "")
NEWS_API_KEY: str = os.environ.get("NEWS_API_KEY", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# HUD API — Bearer token from https://www.huduser.gov/hudapi/public/register
HUD_API_TOKEN: str = os.environ.get("HUD_API_TOKEN", "")

# --- Scoring Thresholds ---
HOUSING_UNITS_THRESHOLD: int = 100_000       # 25 pts if city has 100k+ housing units
RENTER_PCT_THRESHOLD: float = 40.0            # 20 pts if renter % > 40
MEDIAN_INCOME_THRESHOLD: int = 60_000         # 15 pts if median household income > $60k
FMR_2BR_THRESHOLD: int = 1_500               # 20 pts if 2BR fair market rent > $1500

# --- Scoring Weights ---
SCORE_WEIGHTS: dict[str, int] = {
    "housing_units": 30,
    "renter_pct": 20,
    "median_income": 15,
    "fmr_2br": 20,
    "company_news": 10,
    "city_news": 5,
}

# --- Tier Cutoffs ---
TIER_HOT_MIN: int = 70
TIER_WARM_MIN: int = 40

# --- Claude Model ---
CLAUDE_MODEL: str = "claude-sonnet-4-6"

# --- Gmail SMTP (demo email sending) ---
GMAIL_USER: str | None = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD: str | None = os.environ.get("GMAIL_APP_PASSWORD")
DEMO_RECIPIENT_EMAIL: str | None = os.environ.get("DEMO_RECIPIENT_EMAIL")


def validate_email_config() -> tuple[bool, str]:
    """Check that all Gmail-related env vars are configured.

    Returns:
        (True, "")                  if all three vars are set.
        (False, "error message")    if any var is missing.
    """
    if not GMAIL_USER:
        return False, "GMAIL_USER not set in .env"
    if not GMAIL_APP_PASSWORD:
        return False, "GMAIL_APP_PASSWORD not set in .env"
    if not DEMO_RECIPIENT_EMAIL:
        return False, "DEMO_RECIPIENT_EMAIL not set in .env"
    return True, ""
