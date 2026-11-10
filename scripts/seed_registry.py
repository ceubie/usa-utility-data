"""Seed unreviewed declarations from the legacy catalog and collection evidence."""

import argparse
import ast
import json
from pathlib import Path

import yaml

from utilitydata.paths import DataPaths


def read_layer_urls(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LAYERS" for t in node.targets):
            values = ast.literal_eval(node.value)
            if not isinstance(values, dict):
                break
            return values
    raise ValueError("No literal LAYERS mapping in collection script")


def seed(catalog_path: Path, collection_script: Path, raw_root: Path, output: Path, evidence_path: Path) -> None:
    if output.exists() or evidence_path.exists():
        raise FileExistsError("Refusing to overwrite existing seed files")
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))["sources"]
    layer_urls = read_layer_urls(collection_script)
    category_grains = {
        "service_boundary": "service_area", "facility_point": "facility",
        "network_line": "network", "network_node": "network",
        "county_or_community_association": "admin_association",
        "entity_registry": "registry_table", "reference_geography": "registry_table",
    }
    sources = []
    evidence = {"manifests": {}, "layers": {}}
    for entry in catalog:
        source_id = entry["source_id"]
        raw_path = entry.get("relative_path", "").removeprefix("collection/data/")
        if not raw_path or raw_path.startswith(("/", "\\")) or ".." in Path(raw_path).parts:
            raise ValueError(f"Invalid catalog path for {source_id}: {raw_path}")
        metadata_path = raw_root / raw_path / "layer_metadata.json"
        snapshot_path = raw_root / raw_path / "snapshot.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
        if metadata or snapshot:
            evidence["layers"][source_id] = {"metadata": str(metadata_path.relative_to(raw_root)).replace("\\", "/"), "snapshot": str(snapshot_path.relative_to(raw_root)).replace("\\", "/"), "field_names": [f["name"] for f in metadata.get("fields", [])], "feature_count": snapshot.get("downloaded_count"), "layer_url_from_script": layer_urls.get(source_id)}
        layer = {"layer": str(metadata.get("id", entry.get("source_type", "unresolved"))), "sector": entry.get("sector"), "grain": category_grains.get(entry.get("entity_category")), "role": entry.get("zone_role") if entry.get("entity_category") == "service_boundary" else None, "metadata_path": str(metadata_path.relative_to(raw_root)).replace("\\", "/") if metadata else None}
        source = {"source_id": source_id, "publisher": None, "driver": "arcgis" if entry.get("source_type") == "arcgis_layer" else "http", "url": entry.get("source_url") or layer_urls.get(source_id), "cadence": None, "licence": None, "out_of_scope": entry.get("sector") in {"stormwater", "telecommunications", "petroleum_liquids"}, "superseded_by": entry.get("superseded_by"), "reviewed": False, "paths": [raw_path], "layers": [{k: v for k, v in layer.items() if v is not None}], "notes": "Draft seeded from the old catalog; mappings, publisher and licence require review."}
        sources.append(source)
    for path in sorted(raw_root.glob("manifest*.json")):
        evidence["manifests"][path.name] = json.loads(path.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump({"sources": sources}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/sources_catalog.yaml"))
    parser.add_argument("--collection-script", type=Path, default=Path("collection/collect_gis.py"))
    parser.add_argument("--output", type=Path, default=Path("registry/sources/unreviewed.yaml"))
    parser.add_argument("--evidence", type=Path, default=Path("registry/seed_evidence.json"))
    args = parser.parse_args()
    seed(args.catalog, args.collection_script, DataPaths.from_environment().raw, args.output, args.evidence)


if __name__ == "__main__":
    main()
