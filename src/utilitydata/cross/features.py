"""Turn reviewed source rows into facilities, units, and network segments."""

from __future__ import annotations

import numpy as np
import pandas as pd
import shapely
from pyproj import Geod

from utilitydata.core.config import (
    NETWORK_CLASS_FIELDS,
    NETWORK_OWNER_FIELDS,
    NETWORK_OWNER_NAME_COLUMNS,
    NETWORK_STATUS_FIELDS,
)
from utilitydata.core.text import as_string, normalize_name
from utilitydata.cross.capacity import kilowatts_to_megawatts, resolve_plant_capacity
from utilitydata.cross.schema import (
    FACILITY_COLUMNS,
    NETWORK_COLUMNS,
    UNIT_COLUMNS,
    stable_id,
)
from utilitydata.cross.vocab import (
    FacilityVocabulary,
    map_facility_type,
    require_known_facility_type,
)
from utilitydata.registry import Layer, Source

_GEOD = Geod(ellps="WGS84")
_LINE_TYPES = frozenset({"LineString", "MultiLineString"})


def one_declared(layer: Layer, names: tuple[str, ...], label: str) -> str | None:
    """Return the one logical field declared for a role, or none."""
    found = [name for name in names if name in layer.attribute_fields]
    if len(found) > 1:
        raise ValueError(f"{layer.layer} declares more than one {label}: {', '.join(found)}")
    return found[0] if found else None


def normalize_frame(
    frame: pd.DataFrame,
    layer: Layer,
    source: Source,
    vocabulary: FacilityVocabulary,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Return kept rows, id rejects, and the keep mask. Every input row is in one side."""
    frame = frame.reset_index(drop=True)
    if not source.licence:
        raise ValueError(f"{source.source_id} has no licence")
    if not layer.sector:
        raise ValueError(f"{source.source_id} {layer.layer} has no sector")
    feature_id, missing = _feature_ids(frame, layer, source)
    name, owner = _name_and_owner(frame, layer, source)
    kept_mask = ~missing
    if bool(feature_id.loc[kept_mask].duplicated().any()):
        example = feature_id.loc[kept_mask].loc[feature_id.loc[kept_mask].duplicated()].iloc[0]
        raise ValueError(f"Duplicate feature id {example} in {source.source_id} {layer.layer}")
    kept = pd.DataFrame({
        "feature_id": feature_id.loc[kept_mask].to_numpy(),
        "name": name.loc[kept_mask].to_numpy(),
        "name_norm": name.loc[kept_mask].map(normalize_name).to_numpy(),
        "facility_type": _facility_types(frame.loc[kept_mask], layer, vocabulary).to_numpy(),
        "owner_name": owner.loc[kept_mask].to_numpy(),
        "status": _optional_text(frame, layer, NETWORK_STATUS_FIELDS, "status").loc[kept_mask].to_numpy(),
        "segment_class": _optional_text(frame, layer, NETWORK_CLASS_FIELDS, "class").loc[kept_mask].to_numpy(),
        "state": _state(frame, layer).loc[kept_mask].to_numpy(),
        "unit_capacity_kw": _numeric(frame, layer, "unit_capacity_kw").loc[kept_mask].to_numpy(),
        "unit_capacity_mw": _numeric(frame, layer, "unit_capacity_mw").loc[kept_mask].to_numpy(),
        "plant_capacity_mw": _numeric(frame, layer, "plant_capacity_mw").loc[kept_mask].to_numpy(),
        "turbine_count": _numeric(frame, layer, "turbine_count").loc[kept_mask].to_numpy(),
        "eia_plant_id": _text_attribute(frame, layer, "eia_plant_id").loc[kept_mask].to_numpy(),
    })
    rejects = pd.DataFrame({
        "source_id": source.source_id,
        "source_layer": layer.layer,
        "source_feature_id": frame.index.astype("string"),
        "reason": "missing_feature_id",
        "raw_name": name,
    }).loc[missing]
    if len(kept) + len(rejects) != len(frame):
        raise ValueError(f"{source.source_id} {layer.layer} rows do not reconcile")
    return kept.reset_index(drop=True), rejects.reset_index(drop=True), kept_mask.to_numpy()


def facilities_from_frame(
    frame: pd.DataFrame,
    geometries: list | None,
    layer: Layer,
    source: Source,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return facilities, units, and rejected plant totals."""
    if geometries is not None and len(geometries) != len(frame):
        raise ValueError(f"{source.source_id} {layer.layer} geometries do not match its rows")
    if layer.facility_level == "unit":
        return _unit_facilities(frame, geometries, layer, source)
    if layer.facility_level != "plant":
        raise ValueError(f"Unknown facility level {layer.facility_level}")
    return _plant_facilities(frame, geometries, layer, source), _empty_units(), _empty_capacity_rejects()


def network_frame(frame: pd.DataFrame, geometries: list, layer: Layer, source: Source) -> pd.DataFrame:
    """Return one segment per row, including rows whose geometry is empty."""
    if len(geometries) != len(frame):
        raise ValueError(f"{source.source_id} {layer.layer} geometries do not match its rows")
    output = pd.DataFrame({
        "segment_id": [stable_id("SEG", source.source_id, layer.layer, feature) for feature in frame["feature_id"]],
        "sector": layer.sector,
        "source_id": source.source_id,
        "source_layer": layer.layer,
        "source_feature_id": frame["feature_id"].to_numpy(),
        "segment_class": frame["segment_class"].to_numpy(),
        "owner_name": frame["owner_name"].to_numpy(),
        "status": frame["status"].to_numpy(),
        "length_m": [length_meters(geometry) for geometry in geometries],
        "has_geometry": [geometry is not None and not shapely.is_empty(geometry) for geometry in geometries],
        "licence": source.licence,
    })
    empty = shapely.from_wkt("POINT EMPTY")
    output["geometry"] = [empty if geometry is None else geometry for geometry in geometries]
    return output.loc[:, list(NETWORK_COLUMNS) + ["geometry"]]


def length_meters(geometry: object) -> float | None:
    """Return geodesic length for a line. Empty geometry and points have no length."""
    if geometry is None or shapely.is_empty(geometry):
        return None
    kind = geometry.geom_type
    if kind == "GeometryCollection":
        parts = [length_meters(part) for part in geometry.geoms]
        known = [part for part in parts if part is not None]
        return float(sum(known)) if known else None
    if kind not in _LINE_TYPES:
        return None
    return float(_GEOD.geometry_length(geometry))


def _plant_facilities(frame: pd.DataFrame, geometries: list | None, layer: Layer, source: Source) -> pd.DataFrame:
    longitude, latitude, geometry_wkb = _locations(frame, geometries)
    return pd.DataFrame({
        "facility_id": [stable_id("FAC", source.source_id, layer.layer, feature) for feature in frame["feature_id"]],
        "sector": layer.sector,
        "facility_type": frame["facility_type"].to_numpy(),
        "name": frame["name"].to_numpy(),
        "name_norm": frame["name_norm"].to_numpy(),
        "state": frame["state"].to_numpy(),
        "owner_name": frame["owner_name"].to_numpy(),
        "status": frame["status"].to_numpy(),
        # A plant-level layer states its own total. It is null unless the
        # registry names a plant_capacity_mw column.
        "capacity_mw": frame["plant_capacity_mw"].astype("Float64"),
        "unit_count": pd.Series(pd.NA, index=frame.index, dtype="Int64"),
        "source_id": source.source_id,
        "source_layer": layer.layer,
        "source_feature_id": frame["feature_id"].to_numpy(),
        "licence": source.licence,
        "longitude": longitude,
        "latitude": latitude,
        "geometry_wkb": geometry_wkb,
    }).loc[:, list(FACILITY_COLUMNS)]


def _unit_facilities(
    frame: pd.DataFrame,
    geometries: list | None,
    layer: Layer,
    source: Source,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    longitude, latitude, _wkb = _locations(frame, geometries)
    work = frame.copy()
    work["longitude"] = longitude
    work["latitude"] = latitude
    named = work["name_norm"].notna()
    # A declared EIA plant id is part of the key, so two plants that share a
    # name in one state stay apart. A missing id does not join a numbered plant.
    group_key = (
        source.source_id
        + "|"
        + layer.layer
        + "|"
        + work["state"].fillna("").astype(str)
        + "|"
        + work["name_norm"].fillna("")
        + "|"
        + work["eia_plant_id"].fillna("").astype(str)
    )
    group_key = group_key.mask(~named, source.source_id + "|" + layer.layer + "|" + work["feature_id"].astype(str))
    work["facility_id"] = group_key.map(lambda value: stable_id("FAC", value))
    work["unit_capacity_mw"] = _unit_megawatts(work)
    capacity, rejects = resolve_plant_capacity(work.rename(columns={"feature_id": "source_feature_id"}).assign(
        source_feature_id=work["feature_id"],
        facility_id=work["facility_id"],
        unit_capacity_mw=work["unit_capacity_mw"],
        plant_capacity_mw=work["plant_capacity_mw"],
    ))
    capacity_lookup = capacity.set_index("facility_id")["capacity_mw"]
    facilities = []
    for facility_id, group in work.groupby("facility_id", sort=False, dropna=False):
        facilities.append(_grouped_facility(facility_id, group, capacity_lookup, layer, source))
    facility_frame = pd.DataFrame(facilities, columns=list(FACILITY_COLUMNS)) if facilities else pd.DataFrame(columns=list(FACILITY_COLUMNS))
    units = pd.DataFrame({
        "unit_id": [stable_id("UNIT", source.source_id, layer.layer, feature) for feature in work["feature_id"]],
        "facility_id": work["facility_id"].to_numpy(),
        "sector": layer.sector,
        "facility_type": work["facility_type"].to_numpy(),
        "name": work["name"].to_numpy(),
        "status": work["status"].to_numpy(),
        "capacity_mw": work["unit_capacity_mw"].to_numpy(),
        "turbine_count": work["turbine_count"].to_numpy(),
        "source_id": source.source_id,
        "source_layer": layer.layer,
        "source_feature_id": work["feature_id"].to_numpy(),
        "licence": source.licence,
        "longitude": work["longitude"].to_numpy(),
        "latitude": work["latitude"].to_numpy(),
    }).loc[:, list(UNIT_COLUMNS)]
    rejects = rejects.copy()
    rejects["source_id"] = source.source_id
    rejects["source_layer"] = layer.layer
    if len(units) != len(frame):
        raise ValueError(f"{source.source_id} {layer.layer} unit rows do not reconcile")
    return facility_frame, units, rejects


def _grouped_facility(facility_id: object, group: pd.DataFrame, capacity_lookup: pd.Series, layer: Layer, source: Source) -> dict[str, object]:
    return {
        "facility_id": facility_id,
        "sector": layer.sector,
        "facility_type": _one_value(group["facility_type"], f"{source.source_id} facility type"),
        "name": _first_text(group["name"]),
        "name_norm": _one_value(group["name_norm"], f"{source.source_id} facility name"),
        "state": _one_value(group["state"], f"{source.source_id} facility state"),
        "owner_name": _unique_or_null(group["owner_name"]),
        "status": _unique_or_null(group["status"]),
        "capacity_mw": capacity_lookup.get(facility_id, pd.NA),
        "unit_count": len(group),
        "source_id": source.source_id,
        "source_layer": layer.layer,
        "source_feature_id": pd.NA,
        "licence": source.licence,
        "longitude": _mean(group["longitude"]),
        "latitude": _mean(group["latitude"]),
        "geometry_wkb": _mean_wkb(group["longitude"], group["latitude"]),
    }


def _unit_megawatts(frame: pd.DataFrame) -> pd.Series:
    kilowatts = frame["unit_capacity_kw"].notna().any()
    megawatts = frame["unit_capacity_mw"].notna().any()
    if bool(kilowatts and megawatts):
        raise ValueError("Unit capacity is declared in both kilowatts and megawatts")
    if bool(kilowatts):
        return kilowatts_to_megawatts(frame["unit_capacity_kw"])
    return frame["unit_capacity_mw"]


def _feature_ids(frame: pd.DataFrame, layer: Layer, source: Source) -> tuple[pd.Series, pd.Series]:
    if not layer.id_fields:
        raise ValueError(f"{source.source_id} {layer.layer} has no id field")
    missing = pd.Series(False, index=frame.index)
    pieces: list[pd.Series] = []
    for logical, column in layer.id_fields.items():
        if column not in frame.columns:
            raise ValueError(f"{source.source_id} {layer.layer} is missing columns: {column}")
        text = as_string(frame[column])
        missing = missing | text.isna()
        pieces.append((logical + "=") + text.fillna(""))
    feature_id = pieces[0]
    for piece in pieces[1:]:
        feature_id = feature_id.str.cat(piece, sep="|")
    return feature_id.mask(missing), missing


def _name_and_owner(frame: pd.DataFrame, layer: Layer, source: Source) -> tuple[pd.Series, pd.Series]:
    name_is_owner = bool(layer.name_field and layer.name_field in NETWORK_OWNER_NAME_COLUMNS)
    owner_logical = one_declared(layer, NETWORK_OWNER_FIELDS, "owner")
    if name_is_owner and owner_logical:
        raise ValueError(f"{source.source_id} {layer.layer} declares two owners")
    empty = pd.Series(pd.NA, index=frame.index, dtype="string")
    if layer.name_field and not name_is_owner:
        _require_source_column(frame, layer.name_field, source, layer)
        name = as_string(frame[layer.name_field])
    else:
        name = empty.copy()
    if owner_logical:
        column = layer.attribute_fields[owner_logical]
        _require_source_column(frame, column, source, layer)
        owner = as_string(frame[column])
    elif name_is_owner and layer.name_field:
        _require_source_column(frame, layer.name_field, source, layer)
        owner = as_string(frame[layer.name_field])
    else:
        owner = empty
    return name, owner


def _optional_text(frame: pd.DataFrame, layer: Layer, names: tuple[str, ...], label: str) -> pd.Series:
    logical = one_declared(layer, names, label)
    if logical is None:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    column = layer.attribute_fields[logical]
    _require_source_column(frame, column, None, layer)
    return as_string(frame[column])


def _state(frame: pd.DataFrame, layer: Layer) -> pd.Series:
    if layer.state_fixed:
        return pd.Series(layer.state_fixed, index=frame.index, dtype="string")
    if layer.state_field:
        _require_source_column(frame, layer.state_field, None, layer)
        return as_string(frame[layer.state_field]).str.upper()
    return pd.Series(pd.NA, index=frame.index, dtype="string")


def covered_unit_states(sources: list[Source]) -> dict[str, set[str]]:
    """Return states where a reviewed state inventory already lists one facility type.

    A national unit file is not a second copy of those turbines. The caller
    rejects the overlapping rows with a reason instead of dropping them.
    """
    covered: dict[str, set[str]] = {}
    for source in sources:
        if not source.reviewed:
            continue
        for layer in source.layers:
            if layer.grain != "facility" or layer.facility_level != "unit" or not layer.state_fixed or not layer.facility_type_fixed:
                continue
            covered.setdefault(layer.facility_type_fixed, set()).add(layer.state_fixed)
    return covered


def _text_attribute(frame: pd.DataFrame, layer: Layer, logical: str) -> pd.Series:
    if logical not in layer.attribute_fields:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    column = layer.attribute_fields[logical]
    _require_source_column(frame, column, None, layer)
    return as_string(frame[column])


def _numeric(frame: pd.DataFrame, layer: Layer, logical: str) -> pd.Series:
    if logical not in layer.attribute_fields:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    column = layer.attribute_fields[logical]
    _require_source_column(frame, column, None, layer)
    numeric = pd.to_numeric(frame[column], errors="coerce")
    if bool((frame[column].notna() & frame[column].astype("string").str.strip().ne("") & numeric.isna()).any()):
        raise ValueError(f"{layer.layer} {column} is not numeric")
    return numeric.astype("Float64")


def _facility_types(frame: pd.DataFrame, layer: Layer, vocabulary: FacilityVocabulary) -> pd.Series:
    if layer.facility_type_fixed:
        require_known_facility_type(vocabulary, layer.facility_type_fixed)
        return pd.Series(layer.facility_type_fixed, index=frame.index, dtype="string")
    if "facility_type" not in layer.attribute_fields:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    column = layer.attribute_fields["facility_type"]
    _require_source_column(frame, column, None, layer)
    output: list[object] = []
    for value in frame[column]:
        if value is None or (not isinstance(value, str) and pd.isna(value)) or (isinstance(value, str) and not value):
            output.append(pd.NA)
            continue
        if not isinstance(value, str):
            raise ValueError(f"Unmapped facility type: {value!r}")
        output.append(map_facility_type(vocabulary, value))
    return pd.Series(output, index=frame.index, dtype="string")


def _locations(frame: pd.DataFrame, geometries: list | None) -> tuple[pd.Series, pd.Series, list]:
    if geometries is None:
        empty = pd.Series(pd.NA, index=frame.index, dtype="Float64")
        return empty, empty.copy(), [None] * len(frame)
    longitude: list[object] = []
    latitude: list[object] = []
    geometry_wkb: list[bytes | None] = []
    for geometry in geometries:
        if geometry is None or shapely.is_empty(geometry):
            longitude.append(pd.NA)
            latitude.append(pd.NA)
            geometry_wkb.append(None)
            continue
        point = shapely.point_on_surface(geometry)
        longitude.append(float(point.x))
        latitude.append(float(point.y))
        geometry_wkb.append(shapely.to_wkb(geometry))
    return (
        pd.Series(longitude, index=frame.index, dtype="Float64"),
        pd.Series(latitude, index=frame.index, dtype="Float64"),
        geometry_wkb,
    )


def _require_source_column(frame: pd.DataFrame, column: str, source: Source | None, layer: Layer) -> None:
    if column not in frame.columns:
        label = layer.layer if source is None else f"{source.source_id} {layer.layer}"
        raise ValueError(f"{label} is missing columns: {column}")


def _unique_or_null(series: pd.Series) -> object:
    """Return the only non-null value. Differing values stay null instead of being chosen."""
    values = series.dropna().unique()
    if len(values) == 1:
        return values[0]
    return pd.NA


def _one_value(series: pd.Series, label: str) -> object:
    values = series.dropna().unique()
    if len(values) > 1:
        raise ValueError(f"{label} has more than one value")
    if len(values) == 0:
        return pd.NA
    return values[0]


def _first_text(series: pd.Series) -> object:
    values = sorted(str(value) for value in series.dropna().unique())
    return values[0] if values else pd.NA


def _mean(series: pd.Series) -> object:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return pd.NA
    return float(numeric.mean())


def _mean_wkb(longitude: pd.Series, latitude: pd.Series) -> bytes | None:
    lon = _mean(longitude)
    lat = _mean(latitude)
    if pd.isna(lon) or pd.isna(lat):
        return None
    return shapely.to_wkb(shapely.Point(float(lon), float(lat)))


def _empty_units() -> pd.DataFrame:
    return pd.DataFrame(columns=list(UNIT_COLUMNS))


def _empty_capacity_rejects() -> pd.DataFrame:
    return pd.DataFrame(columns=["facility_id", "source_feature_id", "plant_capacity_mw", "reason", "source_id", "source_layer"])
