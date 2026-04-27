"""HUD Fair Market Rents API wrapper.

HUD publishes annual Fair Market Rents (FMRs) by metro area (Core-Based
Statistical Area / CBSA).  Auth is a Bearer token from:
  https://www.huduser.gov/hudapi/public/register

Single-call design: GET /statedata/{state} returns every metro area for that
state with FMR values already inline — no second lookup needed.

Metro name matching uses three passes (most → least strict):
  1. Exact leading-token: "Austin-Round Rock, TX MSA" → leading = "Austin" ✓
  2. City-suffix strip:   "Boise City, ID" → strip " City" → "Boise" ✓
  3. Substring fallback:  city appears anywhere in metro_name

Typical usage:
    from clients.hud_client import get_fair_market_rent
    result = get_fair_market_rent("Austin", "TX")
    # {
    #   "city": "Austin", "state": "TX",
    #   "metro_name": "Austin-Round Rock-San Marcos, TX MSA",
    #   "fmr_1br": 1562, "fmr_2br": 1852, "fmr_3br": 2347,
    #   "success": True, "error": None
    # }
"""

from typing import Optional
import requests
import config


BASE_URL = "https://www.huduser.gov/hudapi/public/fmr"

_EMPTY_RESULT = {
    "metro_name": None,
    "fmr_1br": None,
    "fmr_2br": None,
    "fmr_3br": None,
}


def get_fair_market_rent(city: str, state: str, debug: bool = False) -> dict:
    """Fetch Fair Market Rent data for the metro area that contains a given city.

    Calls GET /statedata/{state} once to retrieve all metro areas for the state,
    matches the city by name, and returns the inline FMR values.

    Args:
        city:  City name, e.g. "Austin"
        state: Two-letter abbreviation, e.g. "TX"
        debug: If True, prints raw API response and match details to stdout.

    Returns:
        Always returns a dict — never raises. On failure, rent fields are None.

        {
            "city": "Austin",
            "state": "TX",
            "metro_name": "Austin-Round Rock-San Marcos, TX MSA",
            "fmr_1br": 1562,
            "fmr_2br": 1852,
            "fmr_3br": 2347,
            "success": True,
            "error": None
        }
    """
    base = {"city": city, "state": state, **_EMPTY_RESULT}
    url = f"{BASE_URL}/statedata/{state.upper()}"

    if debug:
        print(f"  [debug] GET {url}")

    try:
        response = _get(url)
    except requests.HTTPError as exc:
        return {**base, "success": False, "error": f"HUD API HTTP error: {exc}"}
    except requests.RequestException as exc:
        return {**base, "success": False, "error": f"HUD API request failed: {exc}"}

    metros: list[dict] = response.get("data", {}).get("metroareas", [])

    if debug:
        print(f"  [debug] {len(metros)} metros returned for {state}")
        print(f"  [debug] First 3 metro names: {[m.get('metro_name') for m in metros[:3]]}")
        print(f"  [debug] Searching for city='{city}'")

    matched = _match_metro(city, metros, debug=debug)
    if matched is None:
        return {
            **base,
            "success": False,
            "error": (
                f"No HUD metro area found for '{city}, {state}'. "
                "City may be in a rural (non-MSA) area."
            ),
        }

    metro_name, fmr_1br, fmr_2br, fmr_3br = matched
    return {
        **base,
        "metro_name": metro_name,
        "fmr_1br": fmr_1br,
        "fmr_2br": fmr_2br,
        "fmr_3br": fmr_3br,
        "success": True,
        "error": None,
    }


def _match_metro(
    city: str,
    metros: list[dict],
    debug: bool = False,
) -> Optional[tuple[str, Optional[int], Optional[int], Optional[int]]]:
    """Find the best-matching metro for a city and return its name + FMR values.

    Three passes, stopping at the first hit:
      Pass 1 — exact leading-token match:
        "Austin-Round Rock-San Marcos, TX MSA" → leading = "Austin"
        "Austin County, TX HUD Metro FMR Area" → leading = "Austin County"  ← skipped
      Pass 2 — leading-token with " City" suffix stripped:
        "Boise City, ID HUD Metro FMR Area" → leading = "Boise City" → stripped = "Boise"
      Pass 3 — substring fallback for any remaining edge cases.

    Args:
        city:   City name to search for.
        metros: List of metro dicts from the /statedata response.
        debug:  Print pass/match details when True.

    Returns:
        (metro_name, fmr_1br, fmr_2br, fmr_3br) on match, else None.
    """
    city_lower = city.lower().strip()

    def leading_token(metro_name: str) -> str:
        """Extract the primary city portion before the first '-' or ','."""
        return metro_name.split("-")[0].split(",")[0].lower().strip()

    # Pass 1: exact leading-token match
    for metro in metros:
        name = metro.get("metro_name", "")
        if leading_token(name) == city_lower:
            if debug:
                print(f"  [debug] Pass 1 match: '{name}'")
            return _extract_fmr(metro)

    # Pass 2: strip " City" suffix (e.g. "Boise City" → "Boise")
    for metro in metros:
        name = metro.get("metro_name", "")
        stripped = leading_token(name).removesuffix(" city")
        if stripped == city_lower:
            if debug:
                print(f"  [debug] Pass 2 match (City suffix stripped): '{name}'")
            return _extract_fmr(metro)

    # Pass 3: substring fallback
    for metro in metros:
        name = metro.get("metro_name", "")
        if city_lower in name.lower():
            if debug:
                print(f"  [debug] Pass 3 match (substring): '{name}'")
            return _extract_fmr(metro)

    if debug:
        print(f"  [debug] No match found for '{city}' in any pass")
    return None


def _extract_fmr(
    metro: dict,
) -> tuple[str, Optional[int], Optional[int], Optional[int]]:
    """Pull metro_name and bedroom FMR values from a /statedata metro entry.

    HUD uses plain English keys: "One-Bedroom", "Two-Bedroom", "Three-Bedroom".
    """
    return (
        metro.get("metro_name", ""),
        _parse_int(metro.get("One-Bedroom")),
        _parse_int(metro.get("Two-Bedroom")),
        _parse_int(metro.get("Three-Bedroom")),
    )


def _parse_int(value: object) -> Optional[int]:
    """Convert a HUD API value to int, returning None on missing/invalid data."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _get(url: str) -> dict:
    """GET request with Bearer auth; raises requests.HTTPError on non-2xx."""
    headers = {"Authorization": f"Bearer {config.HUD_API_TOKEN}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    import sys

    debug_mode = "--debug" in sys.argv

    test_cases = [
        ("Austin", "TX"),    # large MSA — expect high rents, Austin-Round Rock match
        ("Newark", "NJ"),    # NYC-adjacent — expect very high rents
        ("Miami", "FL"),     # major coastal MSA
        ("Boise", "ID"),     # mid-size; HUD calls it "Boise City" — tests pass-2 match
        ("Liberal", "KS"),   # rural, no MSA — expect graceful failure
    ]

    for city, state in test_cases:
        print(f"\n{'='*50}")
        print(f"  {city}, {state}")
        print(f"{'='*50}")
        result = get_fair_market_rent(city, state, debug=debug_mode)
        print(f"  URL called:   {BASE_URL}/statedata/{state}")
        if result["success"]:
            print(f"  Metro matched: {result['metro_name']}")
            print(f"  FMR 1BR:  ${result['fmr_1br']:,}")
            print(f"  FMR 2BR:  ${result['fmr_2br']:,}")
            print(f"  FMR 3BR:  ${result['fmr_3br']:,}")
        else:
            print(f"  FAILED:   {result['error']}")
