"""Central configuration, reference mappings, and canonical normalization helpers."""
import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECTION_ROOT = REPO_ROOT / "collection"
RAW_DATA_ROOT = COLLECTION_ROOT / "data"
CATALOG_DIR = REPO_ROOT / "catalog"
SILVER_DIR = REPO_ROOT / "silver"
GOLD_DIR = REPO_ROOT / "gold"

STATE_NAME_TO_ABBR = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "WASHINGTON DC": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "HAWAI'I": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
    "PUERTO RICO": "PR",
    "U.S. VIRGIN ISLANDS": "VI",
    "US VIRGIN ISLANDS": "VI",
    "VIRGIN ISLANDS": "VI",
    "GUAM": "GU",
    "AMERICAN SAMOA": "AS",
    "NORTHERN MARIANA ISLANDS": "MP",
}

ABBR_TO_STATE_NAME = {v: k.title() for k, v in STATE_NAME_TO_ABBR.items() if len(v) == 2}
ABBR_TO_STATE_NAME["DC"] = "District of Columbia"
ABBR_TO_STATE_NAME["HI"] = "Hawaii"
ABBR_TO_STATE_NAME["VI"] = "U.S. Virgin Islands"

STATE_PREFIX_TO_ABBR = {
    "alabama_": "AL",
    "alaska_": "AK",
    "arizona_": "AZ",
    "arkansas_": "AR",
    "california_": "CA",
    "colorado_": "CO",
    "connecticut_": "CT",
    "delaware_": "DE",
    "dc_": "DC",
    "florida_": "FL",
    "georgia_": "GA",
    "hawaii_": "HI",
    "idaho_": "ID",
    "illinois_": "IL",
    "indiana_": "IN",
    "iowa_": "IA",
    "kansas_": "KS",
    "kentucky_": "KY",
    "louisiana_": "LA",
    "maine_": "ME",
    "maryland_": "MD",
    "massachusetts_": "MA",
    "michigan_": "MI",
    "minnesota_": "MN",
    "mississippi_": "MS",
    "missouri_": "MO",
    "montana_": "MT",
    "nebraska_": "NE",
    "nevada_": "NV",
    "new_hampshire_": "NH",
    "new_jersey_": "NJ",
    "new_mexico_": "NM",
    "new_york_": "NY",
    "north_carolina_": "NC",
    "north_dakota_": "ND",
    "ohio_": "OH",
    "oklahoma_": "OK",
    "oregon_": "OR",
    "pennsylvania_": "PA",
    "puerto_rico_": "PR",
    "rhode_island_": "RI",
    "south_carolina_": "SC",
    "south_dakota_": "SD",
    "tennessee_": "TN",
    "texas_": "TX",
    "usvi_": "VI",
    "utah_": "UT",
    "vermont_": "VT",
    "virginia_": "VA",
    "washington_": "WA",
    "west_virginia_": "WV",
    "wisconsin_": "WI",
    "wyoming_": "WY",
}

LEGAL_STOPWORDS = {
    "INC",
    "INCORPORATED",
    "LLC",
    "L L C",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LTD",
    "LIMITED",
    "LP",
    "LLP",
    "PLC",
    "THE",
    "OF",
    "AND",
    "FOR",
}

UTILITY_BOILERPLATE_TOKENS = {
    "ELECTRIC",
    "ELECTRICAL",
    "POWER",
    "LIGHT",
    "LIGHTING",
    "ENERGY",
    "GAS",
    "NATURAL",
    "WATER",
    "WASTEWATER",
    "SEWER",
    "SEWERAGE",
    "SANITARY",
    "SANITATION",
    "UTILITY",
    "UTILITIES",
    "PUBLIC",
    "SERVICE",
    "SERVICES",
    "SYSTEM",
    "SYSTEMS",
    "DEPARTMENT",
    "DEPT",
    "DIVISION",
    "DIV",
    "BOARD",
    "COMMISSION",
    "COMMISSIONERS",
    "AUTHORITY",
    "DISTRICT",
    "DIST",
    "COOPERATIVE",
    "COOP",
    "REC",
    "RECC",
    "EMC",
    "RWD",
    "PWSD",
    "PUD",
    "MUD",
    "WCID",
    "SUD",
    "WSC",
    "CPW",
    "ASSOCIATION",
    "ASSN",
    "ASSOC",
    "MUNICIPAL",
    "MUNI",
    "RURAL",
    "WORKS",
}


def normalize_state_code(val: object) -> str | None:
    """Normalize a state code or full state name to a 2-letter USPS code."""
    if val is None:
        return None
    s = str(val).strip().upper()
    if not s or s in {"NAN", "NONE", "NULL", "NA", "<NA>"}:
        return None
    if len(s) == 2 and s in ABBR_TO_STATE_NAME:
        return s
    cleaned = re.sub(r"[^A-Z\s']", "", s).strip()
    return STATE_NAME_TO_ABBR.get(cleaned)


def infer_state_from_source_id(source_id: str) -> str | None:
    """Infer 2-letter state code from a layer or source identifier prefix."""
    lower = source_id.lower()
    for prefix, abbr in STATE_PREFIX_TO_ABBR.items():
        if lower.startswith(prefix):
            return abbr
    return None


def normalize_entity_name(raw_name: object, strip_utility_terms: bool = False) -> str:
    """Produce a normalized uppercase entity key for deterministic & fuzzy matching."""
    if raw_name is None:
        return ""
    s = str(raw_name).strip().upper()
    if not s or s in {"NAN", "NONE", "NULL", "N/A", "UNKNOWN", "TBD"}:
        return ""
    # Remove trailing state tags like " - (SC)" or "(TX)"
    s = re.sub(r"\s*-?\s*\([A-Z]{2}\)\s*$", "", s)
    # Handle inverted "JACKSON, CITY OF" or "ABBEVILLE CITY OF"
    m = re.match(r"^([A-Z0-9\s\.\-']+?),?\s+(CITY|TOWN|VILLAGE|BOROUGH|COUNTY|TOWNSHIP)\s+OF\b(.*)$", s)
    if m:
        s = f"{m.group(2)} OF {m.group(1)} {m.group(3)}"
    s = s.replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in LEGAL_STOPWORDS]
    # Standardize common abbreviations
    std_map = {
        "COOP": "COOPERATIVE",
        "ASSN": "ASSOCIATION",
        "ASSOC": "ASSOCIATION",
        "DEPT": "DEPARTMENT",
        "DIST": "DISTRICT",
        "MUNI": "MUNICIPAL",
        "UTIL": "UTILITY",
        "UTILS": "UTILITIES",
        "ELEC": "ELECTRIC",
        "PWR": "POWER",
        "LT": "LIGHT",
        "WTR": "WATER",
        "SWR": "SEWER",
        "SAN": "SANITARY",
        "AUTH": "AUTHORITY",
        "COMM": "COMMISSION",
        "PUB": "PUBLIC",
        "SVC": "SERVICE",
        "SVCS": "SERVICES",
        "SYS": "SYSTEM",
        "SYST": "SYSTEM",
        "ST": "SAINT",
        "MT": "MOUNT",
    }
    tokens = [std_map.get(t, t) for t in tokens]
    if strip_utility_terms:
        core = [t for t in tokens if t not in UTILITY_BOILERPLATE_TOKENS]
        if core:
            tokens = core
    return " ".join(tokens)


def normalize_county_name(raw_county: object) -> str:
    """Normalize county/parish/borough name for matching to US Census counties."""
    if raw_county is None:
        return ""
    s = str(raw_county).strip().upper()
    if not s or s in {"NAN", "NONE", "NULL"}:
        return ""
    s = re.sub(r"\b(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY|CITY AND BOROUGH)\b", "", s)
    s = re.sub(r"^ST\.?\s+", "SAINT ", s)
    s = re.sub(r"^STE\.?\s+", "SAINTE ", s)
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return " ".join(s.split())


def normalize_pwsid(raw_pwsid: object, fallback_state: str | None = None) -> str | None:
    """Normalize a Public Water System ID to standard 9-character SDWIS PWSID (SSDDDDDDD)."""
    if raw_pwsid is None:
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(raw_pwsid).strip().upper())
    if not s or s in {"NAN", "NONE", "NULL", "0", "UNKNOWN"}:
        return None
    m = re.match(r"^([A-Z]{2})(\d{5,7})$", s)
    if m:
        return f"{m.group(1)}{int(m.group(2)):07d}"
    if s.isdigit() and fallback_state and len(fallback_state) == 2:
        return f"{fallback_state.upper()}{int(s):07d}"
    return s if len(s) >= 7 else None


def deterministic_id(prefix: str, *parts: object) -> str:
    """Generate a stable, readable deterministic ID from prefix and key components."""
    joined = "|".join(str(p).strip().upper() for p in parts if p is not None and str(p).strip())
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"
