"""Column lists for electric tables."""

SALES_COLUMNS = (
    "utility_id_eia",
    "utility_name_eia",
    "state",
    "report_date",
    "customer_class",
    "business_model",
    "service_type",
    "customers",
    "sales_mwh",
)
TERRITORY_COLUMNS = (
    "utility_id_eia",
    "state",
    "county_id_fips",
    "report_date",
)
ENTITY_COLUMNS = ("utility_id_eia", "utility_name_eia")
CODE_COLUMNS = ("utility_id_eia", "entity_type", "report_date")
RELIABILITY_COLUMNS = (
    "utility_id_eia",
    "state",
    "report_date",
    "saidi_wo_major_event_days_minutes",
    "saifi_wo_major_event_days_customers",
)
SYSTEM_STATE_COLUMNS = (
    "system_id",
    "utility_id_eia",
    "state",
    "customers",
    "sales_mwh",
    "report_date",
)
REJECT_COLUMNS = (
    "table_name",
    "utility_id_eia",
    "state",
    "reason",
    "raw_name",
)
DECISION_COLUMNS = (
    "assertion_id",
    "system_id",
    "method",
    "score",
    "evidence",
    "decided_by",
    "release",
)
QUEUE_COLUMNS = (
    "assertion_id",
    "source_id",
    "candidate_system_id",
    "name_score",
    "overlap",
    "geom_state",
    "name_norm",
    "reason",
)
