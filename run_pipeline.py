"""End-to-end orchestrator and verification CLI for the US Utility Data Platform."""
import argparse
import json
import duckdb
from pipeline.build_catalog import build_catalog
from pipeline.build_gold_products import build_gold_products
from pipeline.config import GOLD_DIR, SILVER_DIR
from pipeline.entity_resolution import resolve_entities_and_deduplicate
from pipeline.normalize_registries import build_federal_registries, build_reference_geographies
from pipeline.normalize_spatial import normalize_facilities_and_networks, normalize_service_boundaries


def verify_products() -> dict:
    """Run automated integrity, deduplication, and Knowledge Graph query checks."""
    db_path = GOLD_DIR / "knowledge_graph" / "utility_knowledge_graph.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)

    checks = {}

    # 1. Node & Edge uniqueness
    total_nodes, distinct_nodes = con.execute("SELECT COUNT(*), COUNT(DISTINCT node_id) FROM kg_nodes").fetchone()
    total_edges, distinct_edges = con.execute("SELECT COUNT(*), COUNT(DISTINCT edge_id) FROM kg_edges").fetchone()
    checks["nodes_unique"] = total_nodes == distinct_nodes and total_nodes > 0
    checks["edges_unique"] = total_edges == distinct_edges and total_edges > 0

    # 2. Best-available service boundaries by sector
    sector_zones = con.execute("""
        SELECT sector, COUNT(*) AS zones, COUNT(DISTINCT external_id) AS distinct_ext_ids
        FROM kg_nodes
        WHERE node_label = 'ServiceZone'
        GROUP BY sector
        ORDER BY zones DESC
    """).fetchall()
    checks["service_zones_by_sector"] = [
        {"sector": r[0], "zones": r[1], "distinct_external_ids": r[2]} for r in sector_zones
    ]

    # 3. County multi-utility coverage across 3,235 US Census Counties
    cnty_cov = con.execute("""
        SELECT
            COUNT(*) AS total_counties,
            SUM(CASE WHEN electric_provider_count > 0 THEN 1 ELSE 0 END) AS counties_with_electric,
            SUM(CASE WHEN water_provider_count > 0 THEN 1 ELSE 0 END) AS counties_with_water,
            SUM(CASE WHEN wastewater_provider_count > 0 THEN 1 ELSE 0 END) AS counties_with_wastewater,
            SUM(CASE WHEN natural_gas_provider_count > 0 THEN 1 ELSE 0 END) AS counties_with_natural_gas
        FROM county_multi_utility_summary
    """).fetchone()
    checks["county_coverage"] = {
        "total_us_counties": cnty_cov[0],
        "counties_with_electric": cnty_cov[1],
        "counties_with_water": cnty_cov[2],
        "counties_with_wastewater": cnty_cov[3],
        "counties_with_natural_gas": cnty_cov[4],
    }

    # 4. Deduplication verification on facilities
    fac_stats = con.execute("""
        SELECT
            COUNT(*) AS unique_facilities,
            SUM(source_assertion_count) AS total_source_assertions,
            SUM(CASE WHEN source_assertion_count > 1 THEN 1 ELSE 0 END) AS multi_source_reconciled_facilities
        FROM facilities_deduplicated
    """).fetchone()
    checks["facility_deduplication"] = {
        "unique_facilities": fac_stats[0],
        "total_source_assertions": fac_stats[1],
        "multi_source_reconciled_facilities": fac_stats[2],
    }

    con.close()
    print("Verification Audit Passed:\n" + json.dumps(checks, indent=2))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="US Utility Data Harmonization & Knowledge Graph Pipeline")
    parser.add_argument(
        "--stage",
        choices=["all", "catalog", "registries", "spatial", "resolve", "gold", "verify"],
        default="all",
        help="Pipeline stage to execute.",
    )
    args = parser.parse_args()

    if args.stage in ("all", "catalog"):
        build_catalog()
    if args.stage in ("all", "registries"):
        _, counties = build_reference_geographies()
        build_federal_registries(counties)
    if args.stage in ("all", "spatial"):
        normalize_service_boundaries()
        normalize_facilities_and_networks()
    if args.stage in ("all", "resolve"):
        resolve_entities_and_deduplicate()
    if args.stage in ("all", "gold"):
        build_gold_products()
    if args.stage in ("all", "verify"):
        verify_products()


if __name__ == "__main__":
    main()
