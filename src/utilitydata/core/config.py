"""Policy values for the drinking-water core.

DEFAULT_QUARTER and DEFAULT_RELEASE_ID are the only copies of the current
quarter and release id. Command defaults read them from here.


Thresholds, identifier width, status maps, and the authority order live here.
Do not copy a threshold into another module. The name and overlap cutoffs are
starting values. Leave them in place unless a 200-pair sample shows
auto-accepted precision below 98 percent, and record that change as uncalibrated.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_QUARTER = "2026-Q4"
DEFAULT_RELEASE_ID = "2026Q4.1"

NAME_AUTO_ACCEPT = 95
NAME_WITH_OVERLAP = 80
IOU_AUTO_ACCEPT = 0.5
# A county, place, or tract is served when its population share or its
# population inside the best area reaches these values.
IS_SERVED_POP_SHARE = 0.01
IS_SERVED_MIN_POP = 100
# Absolute relative difference between block population and population_served.
POPULATION_AGREEMENT = 0.25
DISPLAY_SIMPLIFY_DEGREES = (0.001, 0.01)
COMPLIANCE_WINDOW_YEARS = (3, 10)
SHAREABLE_LICENCES = frozenset({
    "public_domain",
    "public_unrestricted",
    "attribution_required",
    "cc-by-4.0",
})
RESTRICTED_LICENCES = frozenset({
    "unknown",
    "internal_or_no_redistribution",
    "attribution_no_commercial_sale",
})
# A recorded restriction can only be replaced by one at least as strict. Not
# finding the terms again is not evidence that the restriction ended.
RESTRICTION_RANK = {
    "internal_or_no_redistribution": 2,
    "attribution_no_commercial_sale": 1,
}
REVIEW_QUEUE_LIMIT = 3
MATCH_SAMPLE_SIZE = 200
MATCH_SAMPLE_SEED = 2026
FEDERAL_ID_SCORE = 100.0
LOCAL_ID_HEX_LENGTH = 10
THRESHOLDS_CALIBRATED = False

# Electric zone matching. These are starting values, not a calibrated measurement.
ELECTRIC_HIFLD_OVERLAP = 0.5
ELECTRIC_NAME_SIMILARITY = 70
# A utility above this bundled-plus-delivery MWh per customer in every measured
# year of the last ELECTRIC_DIRECT_SERVICE_YEARS report years serves a few direct
# customers or sells wholesale. One measured year is enough to be listed. Its
# polygon is not a retail footprint, so it is never a best area. A utility with
# very few customers on a very large polygon is not caught by this ratio.
ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER = 2500.0
ELECTRIC_DIRECT_SERVICE_YEARS = 3
ELECTRIC_THRESHOLDS_CALIBRATED = False

# Wastewater federal linking. These are starting values, not a calibrated measurement.
WASTEWATER_SEWERSHED_OVERLAP = 0.5
WASTEWATER_THRESHOLDS_CALIBRATED = False
WASTEWATER_SAMPLE_SIZE = 50
WASTEWATER_SAMPLE_SEED = 2026

# Utility-name keys used when a zone has no identifier. Two names in one state
# are compared three ways, strictest first: exact normalized text, text without
# legal-form words, and text without legal-form or generic service words. A key
# links only when exactly one system in that state has it. These lists are
# starting values and the links they produce are not a calibrated measurement.
NAME_LEGAL_FORM_TOKENS = frozenset({
    "inc", "incorporated", "co", "company", "corp", "corporation",
    "llc", "lp", "ltd", "the", "l", "p", "c", "o",
})
NAME_GENERIC_SERVICE_TOKENS = frozenset({
    "city", "town", "village", "county", "of", "and", "for", "fo",
    "gas", "natural", "dept", "department", "system", "systems", "sys",
    "municipal", "mun", "muni", "utility", "utilities", "util", "utils",
    "board", "commission", "comm", "authority", "auth", "district", "dist",
    "division", "div", "service", "services", "svc", "public", "works", "wks",
})
GAS_NAME_KEYS_CALIBRATED = False

# Facility matching across identifier types. These are starting values, not a calibrated measurement.
FACILITY_MATCH_DISTANCE_M = 500
FACILITY_NAME_SIMILARITY = 85
FACILITY_THRESHOLDS_CALIBRATED = False
# A same-name group larger than this is queued as a group instead of a pairwise product.
FACILITY_NAME_GROUP_LIMIT = 500
UNIT_CAPACITY_KW_PER_MW = 1000
PARENT_REVIEW_ROWS = 100
# Graph export. Entity and predicate IRIs use this one base. The query language is SPARQL.
GRAPH_BASE_IRI = "http://utilities.local/"
GRAPH_QUERY_TIMEOUT_S = 20
GRAPH_QUERY_HOST = "127.0.0.1"
GRAPH_QUERY_PORT = 3030
# QLever is not the default query engine. The port is loopback-only.
GRAPH_QLEVER_PORT = 7019

# Quarterly refresh. A source fails when feature count or total area moves by more
# than this share of the last good snapshot.
REFRESH_COUNT_DRIFT = 0.10
REFRESH_AREA_DRIFT = 0.10
# ArcGIS feature pages start at this size. One timeout retries that page at half size.
ARCGIS_PAGE_SIZE = 1000
ARCGIS_TIMEOUT_SECONDS = 180
HTTP_TIMEOUT_SECONDS = 180
DISCOVER_TIMEOUT_SECONDS = 60

# Relationship confidence labels source quality. These are not calibrated probabilities.
SEC_PARENT_CONFIDENCE = 0.5
HIFLD_HOLDING_CONFIDENCE = 0.5
GOVID_LINK_CONFIDENCE = 1.0
GOVERNMENT_NAME_OWNER_TYPES = frozenset({
    "local",
    "public",
    "municipal",
    "political_subdivision",
})
NETWORK_CLASS_FIELDS = (
    "pipe_class",
    "line_type",
    "structure_type",
    "unit_type",
    "asset_type",
    "flow_type",
)
NETWORK_OWNER_FIELDS = ("owner", "ownership", "operator", "utility_name")
NETWORK_OWNER_NAME_COLUMNS = frozenset({"OWNER", "Owner", "Operator", "Opername", "OpShortNm"})
NETWORK_STATUS_FIELDS = (
    "line_status",
    "operating_status",
    "operational_status",
    "operation",
    "service_status",
    "lifecycle",
    "approval_status",
    "unit_status",
)

# Saved CWNS FLOW.FLOW_TYPE value for the total row. The dictionary names this
# "Total Flow"; the other saved types are component rows and are not a fallback.
CWNS_TOTAL_FLOW_TYPE = "Total Flow"
CWNS_POPULATION_TYPES = frozenset({"Receiving Collection", "Total Receiving Treatment"})
CWNS_PREFERRED_POPULATION_TYPE = "Total Receiving Treatment"
CWNS_TREATMENT_PLANT = "Treatment Plant"
CWNS_RESPONSIBLE_ENTITY = "Y"
# A code outside this map raises. outside_sector rows are rejected and counted.
CWNS_INFRASTRUCTURE_SECTOR = {
    "Wastewater": "wastewater",
    "Decentralized Wastewater Treatment": "wastewater",
    "Stormwater": "outside_sector",
    "Nonpoint Source": "outside_sector",
}
# Saved REVIEW_STATUS codes. FA is Federal Accepted. UNC is Confirmed.
CWNS_REVIEW_STATUS = {
    "FA": "active",
    "UNC": "unknown",
}
CWNS_OWNER_TYPE = {
    "Public": "public",
    "Private": "private",
    "Federal": "federal",
}
ELECTRIC_BEST_AREA_LAND_RATIO = 1.3
EIA_RETAIL_SERVICE_TYPES = frozenset({"bundled", "delivery"})
EIA_ENERGY_ONLY_SERVICE_TYPE = "energy"
EIA_NONUTILITY_IDS = frozenset({88888, 99999})
EIA_ADJUSTMENT_NAME_PREFIX = "adjustment"
EIA_WITHHELD_NAME = "withheld"
EIA_ENTITY_TYPE = {
    "C": "cooperative",
    "I": "investor_owned",
    "M": "municipal",
    "P": "political_subdivision",
    "F": "federal",
    "S": "state",
    "Q": "independent_power_producer",
    "IND": "industrial",
    "COM": "commercial",
}

AUTHORITY_RANK = (
    "utility_direct",
    "state_regulator",
    "federal_submitted",
    "federal_modeled",
    "admin_proxy",
)
BEST_ROLES = frozenset({"active_retail_service", "certified_franchise_territory"})
NONSERVING_ROLES = frozenset({
    "planned_or_future_service",
    "regional_wholesale_or_district",
    "source_watershed_or_basin",
    "not_serviced_or_excluded",
    "onsite_noncommunity",
    "review_required",
    "unassigned_area",
    "administrative_unit_proxy",
})

# SDWA PWS_ACTIVITY_CODE. Null uses the missing value. Any other code raises.
ACTIVITY_STATUS = {
    "A": "active",
    "I": "inactive",
    "N": "unknown",
    "P": "unknown",
    "M": "unknown",
}
MISSING_ACTIVITY_STATUS = "unknown"

# SDWA OWNER_TYPE_CODE. A code outside this map is kept raw and not given a type.
OWNER_TYPE = {
    "F": "federal",
    "L": "local",
    "M": "public/private",
    "N": "tribal",
    "P": "private",
    "S": "state",
}

# SDWA IS_WHOLESALER_IND. The stored evidence keeps the raw code; unknown codes raise.
WHOLESALER_CODES = {"Y": "yes", "N": "no"}

SDWA_SYSTEMS_LAYER = "SDWA_PUB_WATER_SYSTEMS.csv"
GOVERNMENT_UNITS_LAYER = "government_units"


@dataclass(frozen=True)
class BlockedCase:
    """An acceptance case that stays unproven while its sources are unreviewed."""

    case_id: str
    reason: str
    required_source_ids: tuple[str, ...]


def load_blocked_cases(path: Path) -> tuple[BlockedCase, ...]:
    """Read the snapshot acceptance file. The cases are not embedded in the check code."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = []
    for item in payload["cases"]:
        cases.append(BlockedCase(
            case_id=str(item["case_id"]),
            reason=" ".join(str(item["reason"]).split()),
            required_source_ids=tuple(item["required_source_ids"]),
        ))
    if not cases:
        raise ValueError(f"Acceptance file has no cases: {path.as_posix()}")
    return tuple(cases)


BLOCKED_CASES = load_blocked_cases(
    Path(__file__).resolve().parents[3] / "registry" / "acceptance" / f"{DEFAULT_QUARTER}.yaml"
)
