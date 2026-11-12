"""Classes, links, and column roles for the utility graph.

Sector class names are hand-written. A sector added to the vocabulary has no
class until it is named here.
"""

from __future__ import annotations

EXCLUDED_EXPORT_COLUMNS = frozenset({"geometry", "geometry_wkb"})
FORBIDDEN_OUTPUT_MARKERS = ("geometry", "geometry_wkb", "block_geoid", "block_coverage", "wkb", "violation")

SECTOR_CLASSES = {
    "water": "WaterSystem",
    "electric": "ElectricSystem",
    "wastewater": "WastewaterSystem",
    "natural_gas": "NaturalGasSystem",
    "multi_utility": "MultiUtilitySystem",
    "reference": "ReferenceSystem",
    "stormwater": "StormwaterSystem",
    "telecommunications": "TelecommunicationsSystem",
    "petroleum_liquids": "PetroleumLiquidsSystem",
}

CLASS_LABELS = {
    "Organization": "Organization",
    "UtilitySystem": "Utility system",
    "WaterSystem": "Water system",
    "ElectricSystem": "Electric system",
    "WastewaterSystem": "Wastewater system",
    "NaturalGasSystem": "Natural gas system",
    "MultiUtilitySystem": "Multi-utility system",
    "ReferenceSystem": "Reference system",
    "StormwaterSystem": "Stormwater system",
    "TelecommunicationsSystem": "Telecommunications system",
    "PetroleumLiquidsSystem": "Petroleum liquids system",
    "ServiceArea": "Service area",
    "Facility": "Facility",
    "County": "County",
    "State": "State",
    "Place": "Place",
    "Source": "Source",
    "CountyCoverage": "County coverage",
}

CLASS_COMMENTS = {
    "Organization": "An organization that owns or operates utility systems, or that appears in a parent relationship.",
    "UtilitySystem": "A utility system. Each sector is a subclass.",
    "WaterSystem": "A drinking-water system.",
    "ElectricSystem": "An electric utility system.",
    "WastewaterSystem": "A wastewater system.",
    "NaturalGasSystem": "A natural-gas system.",
    "MultiUtilitySystem": "A system that serves more than one sector.",
    "ReferenceSystem": "A reference-sector system.",
    "StormwaterSystem": "A stormwater system.",
    "TelecommunicationsSystem": "A telecommunications system.",
    "PetroleumLiquidsSystem": "A petroleum or liquids system.",
    "ServiceArea": "A service-area assertion. Geometry stays in the service-area table.",
    "Facility": "A facility. The geometry blob stays in the facility table.",
    "County": "A county or county-equivalent, including Connecticut planning regions.",
    "State": "A state, the District of Columbia, or an island area from the Census state list.",
    "Place": "A census place.",
    "Source": "A reviewed source. Draft sources are not in the graph.",
    "CountyCoverage": (
        "One system in one county, with population share, evidence, and authority. "
        "Block coverage is not this class."
    ),
}

LINKS = (
    "operatesSystem",
    "ownsSystem",
    "parentOf",
    "hasServiceArea",
    "assertedBy",
    "inState",
    "locatedInCounty",
    "servesCounty",
)

LINK_LABELS = {
    "operatesSystem": "operates system",
    "ownsSystem": "owns system",
    "parentOf": "parent of",
    "hasServiceArea": "has service area",
    "assertedBy": "asserted by",
    "inState": "in state",
    "locatedInCounty": "located in county",
    "servesCounty": "serves county",
}

LINK_COMMENTS = {
    "operatesSystem": "The organization operates the utility system. The edge exists only when operator_org_id is present.",
    "ownsSystem": "The organization owns the utility system. The edge exists only when owner_org_id is present.",
    "parentOf": (
        "The subject organization is a parent of the object organization. "
        "SEC parent rows are experimental and incomplete and are not verified. "
        "Each exported row keeps its coverage note on a statement node."
    ),
    "hasServiceArea": "The utility system has this service area.",
    "assertedBy": "The subject is asserted by this reviewed source.",
    "inState": "The subject is in this state. The state IRI uses the USPS code.",
    "locatedInCounty": (
        "A facility or place located in a county. A facility uses the county that contains its "
        "coordinates; a coordinate on a boundary uses the lowest county GEOID. A place that spans "
        "counties uses the county with the largest block population inside the place, and the lowest "
        "county GEOID breaks a tie. Facilities without coordinates have no edge. County service uses "
        "the county coverage node and servesCounty, not this link."
    ),
    "servesCounty": (
        "Shortcut from a utility system to a county. Written only when county coverage is_served is true. "
        "Population share, evidence, and authority stay on the county coverage node."
    ),
}

LINK_RANGE = {
    "operatesSystem": "UtilitySystem",
    "ownsSystem": "UtilitySystem",
    "parentOf": "Organization",
    "hasServiceArea": "ServiceArea",
    "assertedBy": "Source",
    "inState": "State",
    "locatedInCounty": "County",
    "servesCounty": "County",
}

LINK_DOMAIN = {
    "operatesSystem": "Organization",
    "ownsSystem": "Organization",
    "parentOf": "Organization",
    "hasServiceArea": "UtilitySystem",
    "servesCounty": "UtilitySystem",
}

COVERAGE_OBJECT_PROPERTIES = {
    "system": ("UtilitySystem", "The utility system this county coverage describes."),
    "county": ("County", "The county this county coverage describes."),
}

EDGE_FILES = {
    "operatesSystem": "operates_system",
    "ownsSystem": "owns_system",
    "parentOf": "parent_of",
    "hasServiceArea": "has_service_area",
    "assertedBy": "asserted_by",
    "inState": "in_state",
    "locatedInCounty": "located_in_county",
    "servesCounty": "serves_county",
}

SOURCE_FIELDS = (
    "source_id",
    "publisher",
    "driver",
    "url",
    "licence",
    "cadence",
    "redistribution",
    "out_of_scope",
    "notes",
    "reviewed",
)

XSD = {
    "string": "xsd:string",
    "integer": "xsd:integer",
    "float": "xsd:double",
    "boolean": "xsd:boolean",
    "date": "xsd:date",
}

SYSTEM_FIELDS = (
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
ORGANIZATION_FIELDS = (
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
SERVICE_AREA_FIELDS = (
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
    "boundary_representation",
)
FACILITY_FIELDS = (
    "facility_id",
    "sector",
    "facility_type",
    "name",
    "name_norm",
    "state",
    "owner_name",
    "status",
    "capacity_mw",
    "unit_count",
    "source_id",
    "source_layer",
    "source_feature_id",
    "licence",
    "longitude",
    "latitude",
)
COUNTY_FIELDS = ("county_geoid", "state", "countyfp", "name", "namelsad", "pop20")
STATE_FIELDS = ("state", "geoid", "usps", "name", "pop20")
PLACE_FIELDS = ("place_geoid", "state", "placefp", "name", "namelsad", "pop20")
COVERAGE_FIELDS = (
    "system_id",
    "county_geoid",
    "state",
    "sector",
    "pop_in_area",
    "housing_in_area",
    "pop_share_of_county",
    "pop_share_of_system",
    "area_share",
    "evidence",
    "authority",
    "is_served",
    "licence",
    "source_id",
    "in_federal_registry",
)

NODE_FIELDS = {
    "organization": ("iri", "rdf_types", *ORGANIZATION_FIELDS),
    "utility_system": ("iri", "rdf_types", *SYSTEM_FIELDS),
    "service_area": ("iri", "rdf_types", *SERVICE_AREA_FIELDS),
    "facility": ("iri", "rdf_types", *FACILITY_FIELDS),
    "county": ("iri", "rdf_types", *COUNTY_FIELDS),
    "state": ("iri", "rdf_types", *STATE_FIELDS),
    "place": ("iri", "rdf_types", *PLACE_FIELDS),
    "source": ("iri", "rdf_types", *SOURCE_FIELDS),
    "county_coverage": ("iri", "rdf_types", "system_iri", "county_iri", *COVERAGE_FIELDS),
}

NODE_OBJECT_COLUMNS = {
    "county_coverage": {"system_iri": "system", "county_iri": "county"},
}

EDGE_FIELDS = {
    "operates_system": ("subject_iri", "object_iri", "predicate", "org_id", "system_id"),
    "owns_system": ("subject_iri", "object_iri", "predicate", "org_id", "system_id"),
    "parent_of": (
        "subject_iri",
        "object_iri",
        "predicate",
        "relationship_iri",
        "parent_org_id",
        "child_org_id",
        "relationship_id",
        "experimental",
        "coverage_note",
        "confidence",
        "as_of",
        "source_id",
    ),
    "has_service_area": ("subject_iri", "object_iri", "predicate", "system_id", "service_area_id"),
    "asserted_by": ("subject_iri", "object_iri", "predicate", "subject_id", "source_id", "subject_class"),
    "in_state": ("subject_iri", "object_iri", "predicate", "subject_id", "state_usps", "subject_class"),
    "located_in_county": ("subject_iri", "object_iri", "predicate", "subject_id", "county_geoid", "subject_class"),
    "serves_county": ("subject_iri", "object_iri", "predicate", "system_id", "county_geoid", "sector"),
}

PARENT_STATEMENT_FIELDS = (
    "experimental",
    "coverage_note",
    "confidence",
    "as_of",
    "relationship_id",
    "source_id",
    "parent_org_id",
    "child_org_id",
)

SQL_TYPES = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "boolean": "BOOLEAN",
    "date": "DATE",
}

FIELD_SQL = {
    **{name: "VARCHAR" for name in (
        "system_id", "sector", "name", "status", "system_type", "primary_state", "owner_org_id",
        "operator_org_id", "first_seen_release", "last_seen_release", "org_id", "name_norm", "state",
        "owner_type", "owner_type_code", "government_unit_id", "source_id", "service_area_id",
        "zone_role", "authority", "grain", "licence", "boundary_representation", "facility_id",
        "facility_type", "owner_name", "source_layer", "source_feature_id", "county_geoid",
        "countyfp", "namelsad", "geoid", "usps", "place_geoid", "placefp", "evidence",
        "relationship_id", "relationship_type", "subject_org_id", "related_org_id", "subject_name",
        "related_name", "subject_sector", "related_sector", "subject_utility_id", "related_utility_id",
        "govid", "coverage_note", "parent_org_id", "child_org_id", "subject_id",
        "subject_class", "state_usps", "predicate",
    )},
    **{name: "BIGINT" for name in (
        "population_served", "service_connections", "part_count", "unit_count", "pop20",
        "pop_in_area", "housing_in_area",
    )},
    **{name: "DOUBLE" for name in (
        "customers", "sales_mwh", "area_km2", "capacity_mw", "longitude", "latitude",
        "pop_share_of_county", "pop_share_of_system", "area_share", "confidence",
    )},
    **{name: "BOOLEAN" for name in (
        "in_federal_registry", "is_best", "footprint_verified", "is_served", "experimental",
        "out_of_scope", "reviewed",
    )},
    **{name: "DATE" for name in ("source_vintage_date", "as_of")},
}

NOT_EXPORTED = (
    "geometry",
    "block coverage",
    "monthly series",
    "individual violations",
    "network segments",
    "facility units",
    "SDWA water facility inventory",
    "place coverage",
    "tract coverage",
)


def sector_class_name(sector: str) -> str:
    """Return the utility-system subclass for one vocabulary sector."""
    try:
        return SECTOR_CLASSES[sector]
    except KeyError as exc:
        raise ValueError(f"Unknown sector: {sector}") from exc
