"""US Census Bureau API wrapper.

Fetches city-level demographic data via the ACS 5-Year Detailed Tables:
  - Total housing units          (B25001_001E)
  - Owner-occupied units         (B25003_002E)
  - Renter-occupied units        (B25003_003E)  → renter %
  - Median household income      (B19013_001E)

Typical usage:
    from clients.census_client import get_city_demographics
    result = get_city_demographics("Austin", "TX")
    # {
    #   "city": "Austin", "state": "TX",
    #   "housing_units": 450231,
    #   "renter_percentage": 55.2,
    #   "median_income": 75400,
    #   "success": True, "error": None
    # }
"""

from typing import Optional
import requests
import config


ACS_BASE_URL = "https://api.census.gov/data/2022/acs/acs5"

# Detailed-table variable codes (B-series)
VAR_HOUSING_UNITS = "B25001_001E"   # total housing units
VAR_OWNER_OCCUPIED = "B25003_002E"  # owner-occupied units
VAR_RENTER_OCCUPIED = "B25003_003E" # renter-occupied units
VAR_MEDIAN_INCOME = "B19013_001E"   # median household income

# Sentinel the Census API returns when a value is suppressed / unavailable
CENSUS_NULL_SENTINEL = -666666666

# Maps two-letter state abbreviations → 2-digit FIPS codes
STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
    "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56",
}

_EMPTY_RESULT = {
    "housing_units": None,
    "renter_percentage": None,
    "median_income": None,
}


def get_city_demographics(city: str, state: str) -> dict:
    """Fetch demographic and housing data for a US city from the ACS 5-Year API.

    Resolution flow:
      1. Convert state abbreviation → 2-digit FIPS
      2. Query all Census places in that state to find the city's place FIPS
      3. Fetch housing + income variables for that specific place

    Args:
        city: City name, e.g. "Austin"
        state: Two-letter abbreviation, e.g. "TX"

    Returns:
        Always returns a dict — never raises. On failure, numeric fields are None.

        {
            "city": "Austin",
            "state": "TX",
            "housing_units": 450231,
            "renter_percentage": 55.2,   # 0.0–100.0
            "median_income": 75400,
            "success": True,
            "error": None
        }
    """
    base = {"city": city, "state": state, **_EMPTY_RESULT}

    # Step 1: state abbreviation → FIPS
    state_fips = STATE_FIPS.get(state.upper())
    if not state_fips:
        return {**base, "success": False, "error": f"Unknown state abbreviation: '{state}'"}

    # Step 2: city name → place FIPS
    place_fips = _find_place_fips(city, state_fips)
    if not place_fips:
        return {**base, "success": False, "error": f"City '{city}' not found in Census places for state '{state}'"}

    # Step 3: fetch demographic variables
    variables = ",".join([VAR_HOUSING_UNITS, VAR_OWNER_OCCUPIED, VAR_RENTER_OCCUPIED, VAR_MEDIAN_INCOME])
    params = {
        "get": f"NAME,{variables}",
        "for": f"place:{place_fips}",
        "in": f"state:{state_fips}",
        "key": config.CENSUS_API_KEY,
    }

    try:
        response = requests.get(ACS_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {**base, "success": False, "error": f"Census API request failed: {exc}"}

    data = response.json()
    if len(data) < 2:
        return {**base, "success": False, "error": "Census API returned no data rows"}

    # Row 0 is the header; row 1 is the data
    headers = data[0]
    values = data[1]
    row = dict(zip(headers, values))

    housing_units = _parse_int(row.get(VAR_HOUSING_UNITS))
    owner_occupied = _parse_int(row.get(VAR_OWNER_OCCUPIED))
    renter_occupied = _parse_int(row.get(VAR_RENTER_OCCUPIED))
    median_income = _parse_int(row.get(VAR_MEDIAN_INCOME))

    renter_percentage: Optional[float] = None
    if renter_occupied is not None and owner_occupied is not None:
        total_occupied = owner_occupied + renter_occupied
        if total_occupied > 0:
            renter_percentage = round(renter_occupied / total_occupied * 100, 1)

    return {
        **base,
        "housing_units": housing_units,
        "renter_percentage": renter_percentage,
        "median_income": median_income,
        "success": True,
        "error": None,
    }


def _find_place_fips(city: str, state_fips: str) -> Optional[str]:
    """Query all Census places in a state and return the place FIPS for a city.

    The Census API returns place names like "Austin city, Texas". We match
    case-insensitively against the part before the first comma — e.g. "austin city"
    must start with the target city name "austin".

    Args:
        city: City name to search for, e.g. "Austin"
        state_fips: 2-digit state FIPS, e.g. "48"

    Returns:
        5-digit place FIPS string, or None if not found or on request error.
    """
    params = {
        "get": "NAME",
        "for": "place:*",
        "in": f"state:{state_fips}",
        "key": config.CENSUS_API_KEY,
    }

    try:
        response = requests.get(ACS_BASE_URL, params=params, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return None

    rows = response.json()
    city_lower = city.lower().strip()

    # Each row is [NAME, state, place] after the header row
    for row in rows[1:]:
        name, _state, place_code = row
        # "Austin city, Texas" → local_name = "austin city"
        local_name = name.split(",")[0].lower().strip()
        # Match: local_name is "{city} city", "{city} town", "{city} CDP", etc.
        if local_name.startswith(city_lower):
            return place_code

    return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Convert a Census API string value to int, returning None for nulls/sentinels."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        return None
    return None if parsed == CENSUS_NULL_SENTINEL else parsed


if __name__ == "__main__":
    test_cases = [
        ("Austin", "TX"),
        ("Newark", "NJ"),
        ("Miami", "FL"),
        ("Boise", "ID"),
        ("Liberal", "KS"),
    ]

    for city, state in test_cases:
        print(f"\n--- {city}, {state} ---")
        result = get_city_demographics(city, state)
        if result["success"]:
            print(f"  Housing units:     {result['housing_units']:,}")
            print(f"  Renter %:          {result['renter_percentage']}%")
            print(f"  Median income:     ${result['median_income']:,}")
        else:
            print(f"  ERROR: {result['error']}")
