"""Download an ArcGIS layer into a staging folder and commit it only when the counts match."""

import gzip
import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime

import numpy as np
import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from utilitydata.bronze.blobs import sha256_bytes
from utilitydata.bronze.drivers.local import fetch_local
from utilitydata.bronze.drivers.protocol import (
    CandidateFile,
    FetchRequest,
    FetchResult,
    Transport,
)
from utilitydata.bronze.gate import Measurement, count_outside_state
from utilitydata.core.geometry import polygonal_area_km2
from utilitydata.core.spatial_io import (
    get_esri_crs,
    parse_esri_geometry,
    reproject_geoms,
)
from utilitydata.registry import mapped_field_names

_DESTINATION = CRS.from_epsg(4326)


def fetch_arcgis(request: FetchRequest) -> FetchResult:
    """Read the saved layer, or download it when this is not a dry run."""
    if request.dry_run or request.transport is None:
        return fetch_local(request)
    if len(request.source.paths) != 1:
        raise ValueError(f"ArcGIS source needs exactly one path: {request.source.source_id}")
    if not request.source.url:
        raise ValueError(f"ArcGIS source needs a URL: {request.source.source_id}")
    if request.page_size < 2:
        raise ValueError("ArcGIS page size must be at least 2 so a timeout can halve it")
    return _download(request)


def measure_arcgis(
    files: Mapping[str, bytes],
    *,
    mapped_fields: frozenset[str],
    expected_state: BaseGeometry | None,
) -> Measurement:
    """Count features, area, and fields in a saved ArcGIS layer."""
    metadata_name = _one_name(files, "layer_metadata.json")
    metadata = json.loads(files[metadata_name])
    layer_type = metadata.get("type")
    geometry_type = metadata.get("geometryType")
    if layer_type == "Feature Layer" and not geometry_type:
        raise ValueError("Feature layer is missing geometryType")
    if layer_type == "Table" and geometry_type:
        raise ValueError("Table layer declares geometry")
    if layer_type not in {"Feature Layer", "Table"}:
        raise ValueError("ArcGIS layer type is not a feature layer or a table")
    spatial = layer_type == "Feature Layer"
    attributes, geometries = _features(files, geometry_type, spatial)
    fields = _common_fields(attributes)
    missing = mapped_fields - fields
    if missing and attributes:
        fields = fields - missing
    area = _area(geometries, metadata) if spatial else None
    outside = 0
    if spatial and expected_state is not None:
        outside = count_outside_state(_reproject(geometries, metadata), expected_state)
    return Measurement(len(attributes), area, fields, outside, spatial)


def recount_features(files: Mapping[str, bytes]) -> int | None:
    """Count saved features without projecting them. A page without features raises."""
    pages = [name for name in files if name.endswith(".json.gz")]
    if not pages:
        return None
    total = 0
    for name in sorted(pages):
        payload = json.loads(gzip.decompress(files[name]))
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise TypeError(f"ArcGIS page is missing features: {name}")
        total += len(features)
    return total


def _download(request: FetchRequest) -> FetchResult:
    transport = request.transport
    if transport is None:
        raise ValueError(f"ArcGIS download needs a transport: {request.source.source_id}")
    url = request.source.url.rstrip("/")
    metadata_bytes = _get(transport, url, {"f": "json"}, request.timeout_seconds)
    metadata = json.loads(metadata_bytes)
    count_payload = json.loads(_get(transport, f"{url}/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"}, request.timeout_seconds))
    id_payload = json.loads(_get(transport, f"{url}/query", {"where": "1=1", "returnIdsOnly": "true", "f": "json"}, request.timeout_seconds))
    expected = _integer(count_payload.get("count"), "ArcGIS count")
    ids = _identifiers(id_payload)
    if len(ids) != expected:
        raise ValueError(f"ArcGIS id count does not match the feature count for {request.source.source_id}")
    object_field = _object_field(metadata, id_payload)
    maximum = metadata.get("maxRecordCount")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        raise ValueError(f"ArcGIS maxRecordCount is missing for {request.source.source_id}")
    size = min(request.page_size, maximum)
    if request.staging.exists():
        shutil.rmtree(request.staging)
    request.staging.mkdir(parents=True)
    (request.staging / "layer_metadata.json").write_bytes(metadata_bytes)
    try:
        pages = _pages(transport, url, ids, size, object_field, metadata, request.timeout_seconds, request.staging)
        downloaded = sum(page["features"] for page in pages)
        if downloaded != expected or downloaded != len(ids):
            raise ValueError(f"ArcGIS feature count does not match for {request.source.source_id}")
        snapshot = {
            "source_layer": request.source.url,
            "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expected_count_at_start": expected,
            "id_count": len(ids),
            "downloaded_count": downloaded,
            "pages": pages,
        }
        snapshot_bytes = json.dumps(snapshot, indent=2).encode("utf-8")
        (request.staging / "snapshot.json").write_bytes(snapshot_bytes)
        prefix = request.source.paths[0].rstrip("/")
        files = [
            CandidateFile(f"{prefix}/layer_metadata.json", metadata_bytes),
            CandidateFile(f"{prefix}/snapshot.json", snapshot_bytes),
        ]
        for page in pages:
            content = (request.staging / page["file"]).read_bytes()
            if sha256_bytes(content) != page["sha256"]:
                raise ValueError(f"Staged ArcGIS page hash does not match for {page['file']}")
            files.append(CandidateFile(f"{prefix}/{page['file']}", content))
        return _with_differences(request, tuple(files))
    except Exception:
        shutil.rmtree(request.staging, ignore_errors=True)
        raise


def _pages(transport: Transport, url: str, ids: list[int], size: int, object_field: str, metadata: dict, timeout: float, staging) -> list[dict]:
    pages: list[dict] = []
    halved = False
    index = 0
    geometry_type = metadata.get("geometryType")
    spatial = metadata.get("type") == "Feature Layer"
    while index < len(ids):
        batch = ids[index:index + size]
        try:
            body = _query_features(transport, url, batch, object_field, metadata, timeout)
        except TimeoutError:
            if halved:
                raise
            halved_size = size // 2
            if halved_size < 1:
                raise
            size = halved_size
            halved = True
            continue
        payload = json.loads(body)
        if payload.get("exceededTransferLimit"):
            raise ValueError("ArcGIS page exceeded the transfer limit")
        features = payload.get("features")
        if not isinstance(features, list) or len(features) != len(batch):
            raise ValueError("ArcGIS page count does not match the requested ids")
        received = [_feature_id(feature, object_field) for feature in features]
        if set(received) != set(batch):
            raise ValueError("ArcGIS page does not contain the requested ids")
        for feature in features:
            _require_feature(feature, geometry_type, spatial)
        name = f"page_{index:06d}.json.gz"
        destination = staging / name
        with gzip.open(destination, "wb") as stream:
            stream.write(body)
        pages.append({"file": name, "features": len(features), "sha256": sha256_bytes(destination.read_bytes())})
        index += len(batch)
    return pages


def _query_features(transport: Transport, url: str, batch: list[int], object_field: str, metadata: dict, timeout: float) -> bytes:
    params = {
        "objectIds": ",".join(str(value) for value in batch),
        "outFields": "*",
        "returnGeometry": "true",
        "orderByFields": object_field,
        "returnZ": str(bool(metadata.get("hasZ"))).lower(),
        "returnM": str(bool(metadata.get("hasM"))).lower(),
        "f": "json",
    }
    response = transport.request("POST", f"{url}/query", params=params, headers=None, data=None, timeout=timeout)
    if response.status_code != 200:
        raise ValueError(f"ArcGIS feature query returned HTTP {response.status_code}")
    return response.content


def _get(transport: Transport, url: str, params: dict[str, str], timeout: float) -> bytes:
    response = transport.request("GET", url, params=params, headers=None, data=None, timeout=timeout)
    if response.status_code != 200:
        raise ValueError(f"ArcGIS request returned HTTP {response.status_code}")
    return response.content


def _with_differences(request: FetchRequest, files: tuple[CandidateFile, ...]) -> FetchResult:
    previous = {item.relative_path: item.sha256 for item in request.previous}
    current = {item.relative_path: sha256_bytes(item.content) for item in files}
    differences = []
    for path in sorted(set(previous) | set(current)):
        old = previous.get(path)
        new = current.get(path)
        if old is None:
            differences.append(f"new refreshed file {path}")
        elif new is None:
            differences.append(f"missing refreshed file {path}")
        elif old != new:
            differences.append(f"{path} snapshot {old} current {new}")
    return FetchResult(not differences, files, tuple(differences))


def _features(files: Mapping[str, bytes], geometry_type: str | None, spatial: bool) -> tuple[list[dict], list]:
    attributes: list[dict] = []
    geometries: list = []
    for name in sorted(path for path in files if path.endswith(".json.gz")):
        payload = json.loads(gzip.decompress(files[name]))
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise TypeError(f"ArcGIS page is missing features: {name}")
        for feature in features:
            _require_feature(feature, geometry_type, spatial)
            attributes.append(feature["attributes"])
            if spatial:
                geometries.append(parse_esri_geometry(feature.get("geometry"), geometry_type))
    return attributes, geometries


def _require_feature(feature: object, geometry_type: str | None, spatial: bool) -> None:
    if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
        raise TypeError("ArcGIS feature is missing attributes")
    if not spatial:
        return
    geometry = parse_esri_geometry(feature.get("geometry"), geometry_type)
    if geometry is None or geometry.is_empty:
        raise ValueError("Feature layer feature is missing geometry")


def _area(geometries: list, metadata: dict) -> float:
    projected = _reproject(geometries, metadata)
    return float(sum(polygonal_area_km2(geometry) for geometry in projected))


def _reproject(geometries: list, metadata: dict) -> list:
    source = get_esri_crs(metadata)
    if source is None:
        raise ValueError("ArcGIS table has no geometry to reproject")
    projected = shapely.make_valid(reproject_geoms(np.array(geometries, dtype=object), source, _DESTINATION))
    return list(projected)


def _common_fields(attributes: list[dict]) -> frozenset[str]:
    if not attributes:
        return frozenset()
    fields = set(attributes[0])
    for record in attributes[1:]:
        fields &= set(record)
    return frozenset(fields)


def _one_name(files: Mapping[str, bytes], suffix: str) -> str:
    matches = [name for name in files if name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"ArcGIS files need exactly one {suffix}")
    return matches[0]


def _identifiers(payload: dict) -> list[int]:
    values = payload.get("objectIds")
    if not isinstance(values, list):
        raise TypeError("ArcGIS id response is missing objectIds")
    identifiers: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("ArcGIS object id is not an integer")
        identifiers.append(value)
    return sorted(identifiers)


def _object_field(metadata: dict, payload: dict) -> str:
    named = metadata.get("objectIdField") or payload.get("objectIdFieldName")
    if isinstance(named, str) and named:
        return named
    matches = [field.get("name") for field in metadata.get("fields", []) if isinstance(field, dict) and field.get("type") == "esriFieldTypeOID"]
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise ValueError("ArcGIS object id field is missing")
    return matches[0]


def _feature_id(feature: dict, field: str) -> int:
    attributes = feature["attributes"]
    if field not in attributes:
        raise ValueError(f"ArcGIS feature is missing {field}")
    value = attributes[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"ArcGIS feature {field} is not an integer")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} is not an integer")
    return value


def source_mapped_fields(source) -> frozenset[str]:
    """Return every mapped column declared on the source."""
    fields: set[str] = set()
    for layer in source.layers:
        fields.update(mapped_field_names(layer))
    return frozenset(fields)
