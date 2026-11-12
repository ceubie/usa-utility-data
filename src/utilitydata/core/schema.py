"""Column lists for core tables. Writers and readers share these names."""

SYSTEM_COLUMNS = (
    "system_id",
    "sector",
    "name",
    "status",
    "system_type",
    "primary_state",
    "population_served",
    "service_connections",
    "customers",
    "sales_mwh",
    "owner_org_id",
    "operator_org_id",
    "in_federal_registry",
    "first_seen_release",
    "last_seen_release",
)
SYSTEM_HELPER_COLUMNS = ("pwsid", "name_norm", "owner_type", "owner_type_code")
WORKING_SYSTEM_COLUMNS = SYSTEM_COLUMNS + SYSTEM_HELPER_COLUMNS

IDENTIFIER_COLUMNS = ("system_id", "scheme", "value", "source_id")
EVIDENCE_COLUMNS = ("system_id", "activity_code", "wholesaler_indicator", "owner_type_code")
DECISION_COLUMNS = (
    "assertion_id",
    "system_id",
    "method",
    "score",
    "evidence",
    "decided_by",
    "release",
)
SERVICE_AREA_COLUMNS = (
    "service_area_id",
    "system_id",
    "sector",
    "zone_role",
    "source_id",
    "authority",
    "grain",
    "source_vintage_date",
    "is_best",
    "part_count",
    "area_km2",
    "footprint_verified",
    "licence",
    "geometry",
)
ORGANIZATION_COLUMNS = (
    "org_id",
    "name",
    "name_norm",
    "state",
    "owner_type",
    "owner_type_code",
    "government_unit_id",
    "sector",
    "source_id",
)
QUEUE_COLUMNS = (
    "assertion_id",
    "source_id",
    "rank",
    "candidate_system_id",
    "name_score",
    "iou",
    "geom_state",
    "name_norm",
    "queued_system_id",
    "reason",
)
SAMPLE_COLUMNS = (
    "assertion_id",
    "source_id",
    "geom_state",
    "assertion_name",
    "candidate_system_id",
    "candidate_name",
    "name_score",
    "iou",
    "decision",
    "method",
    "result_system_id",
)
REGISTRY_COLUMNS = ("sector", "state", "name_norm", "system_id", "release")
OVERRIDE_COLUMNS = ("assertion_id", "system_id", "decided_by", "notes")
PWSID_CANDIDATE_COLUMNS = ("assertion_id", "candidate", "federal_id")

ASSERTION_COLUMNS = (
    "assertion_id",
    "source_id",
    "sector",
    "zone_role",
    "authority",
    "raw_name",
    "name_norm",
    "pwsid",
    "pwsid_raw",
    "geom_state",
    "source_vintage_date",
    "licence",
    "grain",
    "area_km2",
    "footprint_verified",
    "activity_status",
    "review_reason",
)
SDWA_COLUMNS = (
    "PWSID",
    "PWS_NAME",
    "PWS_ACTIVITY_CODE",
    "PWS_TYPE_CODE",
    "OWNER_TYPE_CODE",
    "STATE_CODE",
    "POPULATION_SERVED_COUNT",
    "SERVICE_CONNECTIONS_COUNT",
    "IS_WHOLESALER_IND",
)
GOVERNMENT_COLUMNS = ("CENSUS_ID_PID6", "UNIT_NAME", "STATE")
ATTRIBUTE_COLUMNS = ("record_id", "pwsid")
MANIFEST_COLUMNS = ("source_id", "status")
