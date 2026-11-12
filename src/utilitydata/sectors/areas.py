"""Read reviewed local service areas from a frozen snapshot."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from utilitydata.registry import Layer, Source
from utilitydata.sectors.tables import snapshot_path
from utilitydata.silver.boundaries import (
    _known_states,
    _load_state_regions,
    build_layer_rows,
    required_columns,
)
from utilitydata.silver.geometry import read_arcgis_features, read_vector_features


def read_source_features(home: Path, quarter: str, source: Source, layer: Layer):
    """Read features from an ArcGIS snapshot, an archived vector layer, or a standalone vector file."""
    path = snapshot_path(home, quarter, source.paths[0])
    if source.driver == "arcgis":
        return read_arcgis_features(path)
    if layer.archive_member:
        member = layer.archive_member.replace("\\", "/")
        vsi = f"/vsizip/{path.resolve().as_posix()}/{member}"
        target_layer = None if Path(member).suffix.lower() in {".geojson", ".json", ".shp"} else layer.layer
        frame, geoms, crs = read_vector_features(vsi, target_layer, feature_id_field=layer.id_fields.get("feature_id"))
    elif path.suffix.lower() in {".gpkg", ".geojson", ".json", ".shp"}:
        target_layer = None if path.suffix.lower() in {".geojson", ".json", ".shp"} else layer.layer
        frame, geoms, crs = read_vector_features(str(path), target_layer, feature_id_field=layer.id_fields.get("feature_id"))
    else:
        raise ValueError(f"{source.source_id} is not a supported spatial service area")
    missing = sorted(required_columns(layer) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing columns in {source.source_id}: {', '.join(missing)}")
    return frame.to_dict("records"), geoms, crs


def read_local_zones(
    home: Path,
    quarter: str,
    jobs: list[tuple[Source, object, str]],
    sources: list[Source],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Read the selected local zones. Jobs must already exclude draft sources."""
    if not jobs:
        empty = gpd.GeoDataFrame(columns=["assertion_id", "geometry"], geometry="geometry", crs="EPSG:4326")
        return empty, pd.DataFrame(columns=["source_id", "source_layer", "source_feature_id", "reason", "raw_name"])
    known_states = _known_states(home / "silver" / quarter / "ref_state.parquet")
    state_geometries, state_codes = _load_state_regions(home, sources, home / "silver" / quarter / "ref_state.parquet")
    frames: list[pd.DataFrame] = []
    geometries: list[object] = []
    rejects: list[pd.DataFrame] = []
    for source, layer, _status in jobs:
        attributes, geoms, crs = read_source_features(home, quarter, source, layer)
        rows = build_layer_rows(
            source_id=source.source_id,
            licence=source.licence,
            layer=layer,
            attributes=attributes,
            geometries=geoms,
            source_crs=crs,
            sdwis_counts={},
            known_states=known_states,
            state_geometries=state_geometries,
            state_codes=state_codes,
            spatial=True,
        )
        if len(rows.assertions) + len(rows.rejects) != len(attributes):
            raise ValueError(f"{source.source_id} feature count does not reconcile")
        if rows.assertions:
            frames.append(pd.DataFrame(rows.assertions))
            geometries.extend(rows.geometries)
        if rows.rejects:
            rejects.append(pd.DataFrame(rows.rejects))
    if not frames:
        zones = gpd.GeoDataFrame(columns=["assertion_id", "geometry"], geometry="geometry", crs="EPSG:4326")
    else:
        zones = pd.concat(frames, ignore_index=True)
        if len(zones) != len(geometries):
            raise ValueError("Local zone geometries do not match assertions")
        zones["geometry"] = geometries
        zones = gpd.GeoDataFrame(zones, geometry="geometry", crs="EPSG:4326")
    reject_frame = pd.concat(rejects, ignore_index=True) if rejects else pd.DataFrame(
        columns=["source_id", "source_layer", "source_feature_id", "reason", "raw_name"]
    )
    return zones, reject_frame
