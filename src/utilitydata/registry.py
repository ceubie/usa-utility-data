"""Hand-declared source registry and strict review-state validation."""

import csv
import gzip
import hashlib
import io
import json
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

import pandas as pd
import pyarrow.parquet as pq
import pyogrio
import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from utilitydata.bronze.archive import materialize_archive_member
from utilitydata.core.config import RESTRICTION_RANK

Sector = Literal["water", "electric", "wastewater", "natural_gas", "multi_utility", "reference", "stormwater", "telecommunications", "petroleum_liquids"]
Grain = Literal["service_area", "facility", "network", "admin_association", "registry_table"]
Authority = Literal["utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy"]
BoundaryRepresentation = Literal["unmodeled", "modeled", "mixed", "unknown"]
AUTHORITIES = {"utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy"}
BOUNDARY_REPRESENTATIONS = {"unmodeled", "modeled", "mixed", "unknown"}
VECTOR_SUFFIXES = {".gpkg", ".geojson", ".json", ".shp"}
ZONE_ROLES = {"active_retail_service", "certified_franchise_territory", "planned_or_future_service", "administrative_unit_proxy", "source_watershed_or_basin", "regional_wholesale_or_district", "not_serviced_or_excluded", "unassigned_area", "onsite_noncommunity", "review_required"}
STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "AS", "GU", "MP", "PR", "VI"}


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FieldMap(RegistryModel):
    field: str = Field(min_length=1)
    values: dict[str, str] = Field(min_length=1)
    on_null: Literal["reject", "unknown", "review_required"]


class RoleCase(RegistryModel):
    values: list[str | None]
    role: str


class RoleMatrix(RegistryModel):
    fields: list[str] = Field(min_length=1)
    cases: list[RoleCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self):
        if len(self.fields) != len(set(self.fields)) or any(not field for field in self.fields):
            raise ValueError("Role matrix fields must be nonempty and unique")
        combinations = [tuple(case.values) for case in self.cases]
        if len(combinations) != len(set(combinations)) or any(len(case.values) != len(self.fields) for case in self.cases):
            raise ValueError("Role matrix cases must be unique and match field count")
        if any(case.role not in ZONE_ROLES for case in self.cases):
            raise ValueError("Unknown role in matrix")
        return self


class Layer(RegistryModel):
    layer: str = Field(min_length=1)
    archive_member: str | None = None
    sector: Sector | None = None
    grain: Grain | None = None
    role: str | None = None
    role_field: FieldMap | None = None
    role_matrix: RoleMatrix | None = None
    authority: Authority | FieldMap | None = None
    boundary_representation: BoundaryRepresentation | FieldMap = "unknown"
    name_field: str | None = None
    on_missing_name: Literal["preserve_and_review"] | None = None
    id_fields: dict[str, str] = Field(default_factory=dict)
    attribute_fields: dict[str, str] = Field(default_factory=dict)
    pwsid_rule: Literal["state_prefix_7"] | None = None
    on_invalid_pwsid: Literal["preserve_raw_without_federal_id"] | None = None
    state_field: str | None = None
    state_fixed: str | None = None
    state_from_geometry: StrictBool = False
    mailing_state_field: str | None = None
    status_field: FieldMap | None = None
    wholesaler_field: FieldMap | None = None
    vintage_field: str | None = None
    vintage_fixed: str | None = None
    dissolve: StrictBool = False
    metadata_path: str | None = None
    notes: str | None = None
    facility_level: Literal["plant", "unit"] = "plant"
    facility_type_fixed: str | None = None

    @model_validator(mode="after")
    def exclusive_fields(self):
        if sum(bool(value) for value in (self.role, self.role_field, self.role_matrix)) > 1:
            raise ValueError("Choose only one role mapping")
        if sum(bool(x) for x in (self.state_field, self.state_fixed, self.state_from_geometry)) > 1:
            raise ValueError("Choose only one state source")
        if self.vintage_field and self.vintage_fixed:
            raise ValueError("Choose vintage_field or vintage_fixed, not both")
        if self.role and self.role not in ZONE_ROLES:
            raise ValueError("Unknown zone role")
        if self.role_field and set(self.role_field.values.values()) - ZONE_ROLES:
            raise ValueError("Unknown zone role mapping")
        if self.role_field and self.role_field.on_null not in {"reject", "review_required"}:
            raise ValueError("Null role values must be rejected or routed to review")
        if isinstance(self.authority, FieldMap) and set(self.authority.values.values()) - AUTHORITIES:
            raise ValueError("Unknown authority mapping")
        if isinstance(self.authority, FieldMap) and self.authority.on_null != "reject":
            raise ValueError("Null authority values must be rejected and reconciled")
        if isinstance(self.boundary_representation, FieldMap) and set(self.boundary_representation.values.values()) - BOUNDARY_REPRESENTATIONS:
            raise ValueError("Unknown boundary representation mapping")
        if isinstance(self.boundary_representation, FieldMap) and self.boundary_representation.on_null not in {"reject", "unknown"}:
            raise ValueError("Null boundary representation values must be rejected or marked unknown")
        if self.status_field and set(self.status_field.values.values()) - {"active", "inactive", "unknown"}:
            raise ValueError("Unknown status mapping")
        if self.status_field and self.status_field.on_null not in {"reject", "unknown"}:
            raise ValueError("Null status values must be rejected or marked unknown")
        if self.wholesaler_field and set(self.wholesaler_field.values.values()) - {"yes", "no", "unknown"}:
            raise ValueError("Unknown wholesaler mapping")
        if self.wholesaler_field and self.wholesaler_field.on_null not in {"reject", "unknown"}:
            raise ValueError("Null wholesaler values must be rejected or marked unknown")
        if self.state_fixed and self.state_fixed not in STATES:
            raise ValueError("Invalid fixed state")
        if self.pwsid_rule and ("pwsid" not in self.id_fields or not self.state_fixed):
            raise ValueError("A PWSID rule requires a PWSID field and fixed state")
        if self.facility_level == "unit" and self.grain not in {None, "facility"}:
            raise ValueError("Unit features require facility grain")
        if self.facility_type_fixed and "facility_type" in self.attribute_fields:
            raise ValueError("Choose a fixed facility type or a facility_type field, not both")
        return self


class Source(RegistryModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    publisher: str | None = None
    driver: Literal["arcgis", "http", "discover", "custom"] | None = None
    url: str | None = None
    cadence: Literal["monthly", "quarterly", "annual", "irregular", "frozen"] | None = None
    licence: Literal["unknown", "public_domain", "public_unrestricted", "attribution_required", "cc-by-4.0", "internal_or_no_redistribution", "attribution_no_commercial_sale"] | None = None
    redistribution: Literal["shareable", "internal_only"] = "internal_only"
    out_of_scope: StrictBool = False
    superseded_by: str | None = None
    pruned_reason: str | None = None
    reviewed: StrictBool = False
    storage: Literal["collection", "home"] = "collection"
    paths: list[str] = Field(default_factory=list)
    layers: list[Layer] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_reviewed(self):
        if self.redistribution == "shareable" and self.licence not in {"public_domain", "public_unrestricted", "attribution_required", "cc-by-4.0"}:
            raise ValueError("Unknown or restricted licence cannot be marked shareable")
        if not self.reviewed:
            return self
        if self.superseded_by and not self.pruned_reason:
            raise ValueError("Reviewed superseded sources require a reason")
        if any(not x for x in (self.publisher, self.driver, self.url, self.cadence, self.licence)):
            raise ValueError("Reviewed sources require publisher, driver, url, cadence and licence")
        if not self.paths:
            raise ValueError("Reviewed sources require explicit paths")
        if not self.out_of_scope and not self.layers:
            raise ValueError("Reviewed in-scope sources require layer declarations")
        for layer in self.layers:
            if not layer.sector or not layer.grain:
                raise ValueError("Reviewed layers require sector and grain")
            if layer.grain == "service_area" and (not (layer.role or layer.role_field or layer.role_matrix) or not layer.authority):
                raise ValueError("Reviewed service areas require role and authority")
            if layer.grain == "service_area" and not layer.name_field:
                raise ValueError("Reviewed service areas require a name field")
            if layer.grain == "service_area" and layer.on_missing_name != "preserve_and_review":
                raise ValueError("Reviewed service areas must preserve and review missing names")
            if "pwsid" in layer.id_fields and layer.on_invalid_pwsid != "preserve_raw_without_federal_id":
                raise ValueError("Reviewed PWSID mappings require a policy for invalid or missing values")
        return self


class SourceFile(RegistryModel):
    sources: list[Source]


def _is_null(value) -> bool:
    if value is None or isinstance(value, str):
        return value is None
    return bool(pd.isna(value))


def _exact_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _value_maps(layer: Layer) -> list[FieldMap]:
    candidates: list[FieldMap | None] = [layer.role_field, layer.status_field, layer.wholesaler_field]
    if isinstance(layer.authority, FieldMap):
        candidates.append(layer.authority)
    if isinstance(layer.boundary_representation, FieldMap):
        candidates.append(layer.boundary_representation)
    return [item for item in candidates if item is not None]


def mapped_field_names(layer: Layer) -> frozenset[str]:
    """Return the source columns a layer maps. The names are exact."""
    return frozenset(_declared_fields(layer))


def _declared_fields(layer: Layer) -> set[str]:
    declared = set(layer.id_fields.values())
    declared.update(layer.attribute_fields.values())
    declared.update(
        name for name in (layer.name_field, layer.state_field, layer.vintage_field, layer.mailing_state_field) if name
    )
    declared.update(item.field for item in _value_maps(layer))
    if layer.role_matrix is not None:
        declared.update(layer.role_matrix.fields)
    return declared


def _folded_names(names: set) -> dict[str, str]:
    folded: dict[str, str] = {}
    for name in names:
        if isinstance(name, str):
            folded.setdefault(name.casefold(), name)
    return folded


def _require_declared_names(source_id: str, declared: set[str], available: set, *, feature: bool) -> None:
    missing = {name for name in declared if name not in available}
    if not missing:
        return
    folded = _folded_names(available)
    mismatches = [f"{name} != {folded[name.casefold()]}" for name in sorted(missing) if name.casefold() in folded]
    if mismatches:
        raise ValueError(f"Attribute case mismatch in {source_id}: {', '.join(mismatches)}")
    if feature:
        raise ValueError(f"Missing attribute in {source_id}: {', '.join(sorted(missing))}")
    raise ValueError(f"Missing mapped fields for {source_id}: {', '.join(sorted(missing))}")


def _reject_coded_value(mapping: FieldMap, text: str, raw, source_id: str) -> None:
    if text in mapping.values:
        return
    other = {key.casefold(): key for key in mapping.values}.get(text.casefold())
    if other is not None and other != text:
        raise ValueError(f"Value case mismatch in {source_id}.{mapping.field}: {text!r} != {other!r}")
    raise ValueError(f"Unmapped value {raw!r} in {source_id}.{mapping.field}")


def _fold_case(values: tuple) -> tuple:
    return tuple(None if part is None else part.casefold() for part in values)


def _check_role_matrix(matrix: RoleMatrix, attributes: dict, source_id: str, allowed: set) -> None:
    _require_declared_names(source_id, set(matrix.fields), set(attributes), feature=True)
    values = tuple(None if _is_null(attributes[field]) else str(attributes[field]) for field in matrix.fields)
    if values in allowed:
        return
    other = {_fold_case(case): case for case in allowed}.get(_fold_case(values))
    if other is not None and other != values:
        raise ValueError(f"Value case mismatch in {source_id}: {values!r} != {other!r}")
    raise ValueError(f"Unmapped role combination in {source_id}: {values!r}")


def _is_saved_page_name(name: str) -> bool:
    folded = name.casefold()
    return folded.startswith("page") and folded.endswith(".json.gz")


def _saved_page_relatives(directory: Path, source_id: str) -> list[str]:
    """Return every saved page path, including nested and case-variant names."""
    parent = directory.resolve()
    found: list[str] = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"ArcGIS page inventory mismatch for {source_id}")
        if not path.is_file() or not _is_saved_page_name(path.name):
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(parent):
            raise ValueError(f"ArcGIS page inventory mismatch for {source_id}")
        found.append(resolved.relative_to(parent).as_posix())
    return sorted(found)


def _snapshot_pages(snapshot: dict, directory: Path, source_id: str) -> list[tuple[Path, int, str]]:
    pages = snapshot.get("pages")
    if type(pages) is not list:
        raise ValueError(f"Snapshot pages missing for {source_id}")
    listed: list[tuple[Path, int, str]] = []
    names: list[str] = []
    parent = directory.resolve()
    for page in pages:
        name = page.get("file") if isinstance(page, dict) else None
        count = page.get("features") if isinstance(page, dict) else None
        digest = page.get("sha256") if isinstance(page, dict) else None
        if not isinstance(name, str) or not _exact_count(count) or name != Path(name).name or not name.endswith(".json.gz"):
            raise ValueError(f"Invalid snapshot page for {source_id}")
        path = (directory / name).resolve()
        if not path.is_relative_to(parent) or not path.is_file():
            raise ValueError(f"Missing snapshot page for {source_id}: {name}")
        if not isinstance(digest, str) or not digest:
            raise ValueError(f"Snapshot page hash missing for {source_id}: {name}")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"Invalid snapshot page hash for {source_id}: {name}")
        listed.append((path, count, digest))
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError(f"ArcGIS page inventory mismatch for {source_id}")
    if _saved_page_relatives(directory, source_id) != sorted(names):
        raise ValueError(f"ArcGIS page inventory mismatch for {source_id}")
    return listed


def _require_arcgis_counts(snapshot: dict, seen: int, source_id: str) -> None:
    counts = [snapshot.get(key) for key in ("downloaded_count", "id_count", "expected_count_at_start")]
    if any(not _exact_count(count) or count != seen for count in counts):
        raise ValueError(f"ArcGIS source count mismatch for {source_id}")


def _check_feature_values(layer: Layer, attributes: dict, source_id: str, role_cases: set) -> None:
    if layer.role_matrix is not None:
        _check_role_matrix(layer.role_matrix, attributes, source_id, role_cases)
    for mapping in _value_maps(layer):
        value = attributes[mapping.field]
        if not _is_null(value):
            _reject_coded_value(mapping, str(value), value, source_id)


def _check_parquet_layer(root: Path, source: Source, layer: Layer) -> None:
    """Require declared parquet columns, and every coded value when a map is declared."""
    if len(source.paths) != 1:
        raise ValueError(f"Parquet source needs exactly one path: {source.source_id}")
    directory = (root / source.paths[0]).resolve()
    path = (directory / layer.layer).resolve()
    if not directory.is_relative_to(root) or not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f"Missing parquet for {source.source_id}.{layer.layer}")
    declared = _declared_fields(layer)
    _require_declared_names(source.source_id, declared, set(pq.read_schema(path).names), feature=False)
    mappings = _value_maps(layer)
    role_cases = {tuple(case.values) for case in layer.role_matrix.cases} if layer.role_matrix else set()
    columns = {item.field for item in mappings}
    if layer.role_matrix is not None:
        columns.update(layer.role_matrix.fields)
    if not columns:
        return
    frame = pd.read_parquet(path, columns=sorted(columns))
    for mapping in mappings:
        for value in frame[mapping.field].unique():
            if not _is_null(value):
                _reject_coded_value(mapping, str(value), value, source.source_id)
    if layer.role_matrix is not None:
        fields = layer.role_matrix.fields
        for record in frame[fields].drop_duplicates().itertuples(index=False):
            _check_role_matrix(layer.role_matrix, dict(zip(fields, record, strict=True)), source.source_id, role_cases)


def relaxed_restrictions(previous: list[Source], current: list[Source]) -> list[str]:
    """Return sources whose recorded licence restriction was replaced by a weaker licence."""
    now = {source.source_id: source.licence for source in current}
    relaxed = []
    for source in previous:
        before = RESTRICTION_RANK.get(source.licence or "", 0)
        if before and source.source_id in now and RESTRICTION_RANK.get(now[source.source_id] or "", 0) < before:
            relaxed.append(source.source_id)
    return sorted(relaxed)


def load_registry(
    directory: Path,
    *,
    require_reviewed: bool = True,
    raw_root: Path | None = None,
    home_root: Path | None = None,
) -> list[Source]:
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise ValueError(f"No registry files in {directory}")
    sources = []
    for path in files:
        try:
            sources.extend(SourceFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).sources)
        except ValueError as exc:
            raise ValueError(f"Invalid source registry {path.name}: {exc}") from exc
    ids = [source.source_id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source_id in registry")
    unknown = sorted({source.superseded_by for source in sources if source.superseded_by and source.superseded_by not in ids})
    if unknown:
        raise ValueError(f"Unknown superseding sources: {', '.join(unknown)}")
    unreviewed = [source.source_id for source in sources if not source.reviewed]
    if require_reviewed and unreviewed:
        raise ValueError(f"{len(unreviewed)} sources require review")
    if raw_root is not None or home_root is not None:
        for source in sources:
            if not source.reviewed:
                continue
            if source.storage == "home":
                if home_root is None:
                    continue
                root = home_root.resolve()
            elif raw_root is None:
                continue
            else:
                root = raw_root.resolve()
            for raw_path in source.paths:
                path = (root / raw_path).resolve()
                if not path.is_relative_to(root) or not path.exists():
                    raise ValueError(f"Invalid source path for {source.source_id}: {raw_path}")
            for layer in source.layers:
                role_cases = {tuple(case.values) for case in layer.role_matrix.cases} if layer.role_matrix else set()
                if source.driver == "arcgis" and not layer.metadata_path:
                    raise ValueError(f"Missing layer metadata for {source.source_id}")
                if not layer.metadata_path:
                    if layer.layer.lower().endswith(".parquet"):
                        _check_parquet_layer(root, source, layer)
                        continue
                    if not layer.archive_member and not layer.layer.lower().endswith(".csv"):
                        standalone = (
                            len(source.paths) == 1
                            and Path(source.paths[0]).suffix.lower() in VECTOR_SUFFIXES
                        )
                        if not standalone:
                            raise ValueError(f"No verifiable layer metadata for {source.source_id}.{layer.layer}")
                        vector_path = (root / source.paths[0]).resolve()
                        if not vector_path.is_relative_to(root) or not vector_path.is_file():
                            raise ValueError(f"Invalid vector path for {source.source_id}")
                        target_layer = None if vector_path.suffix.lower() in {".geojson", ".json", ".shp"} else layer.layer
                        info = pyogrio.read_info(vector_path, layer=target_layer)
                        if layer.grain in {"service_area", "network", "facility"} and not info.get("geometry_type"):
                            raise ValueError(f"Spatial layer has no geometry for {source.source_id}.{layer.layer}")
                        if layer.grain == "service_area" and info.get("geometry_type", "").removesuffix(" Z") not in {"Polygon", "MultiPolygon"}:
                            raise ValueError(f"Service-area layer is not polygonal for {source.source_id}.{layer.layer}")
                        available = set(info["fields"]) | {info.get("fid_column")}
                        declared = _declared_fields(layer)
                        _require_declared_names(source.source_id, declared, available, feature=False)
                        mappings = _value_maps(layer)
                        if mappings or layer.role_matrix:
                            columns = {item.field for item in mappings}
                            if layer.role_matrix:
                                columns.update(layer.role_matrix.fields)
                            frame = pyogrio.read_dataframe(vector_path, layer=target_layer, columns=sorted(columns), read_geometry=False)
                            for mapping in mappings:
                                for value in frame[mapping.field].unique():
                                    if not _is_null(value):
                                        _reject_coded_value(mapping, str(value), value, source.source_id)
                            if layer.role_matrix:
                                for record in frame[layer.role_matrix.fields].drop_duplicates().to_dict("records"):
                                    _check_role_matrix(layer.role_matrix, record, source.source_id, role_cases)
                        continue
                    if layer.archive_member:
                        if len(source.paths) != 1:
                            raise ValueError(f"Geospatial archive source needs exactly one path: {source.source_id}")
                        archive = (root / source.paths[0]).resolve()
                        member = layer.archive_member.replace("\\", "/")
                        if member.startswith("/") or ".." in member.split("/"):
                            raise ValueError(f"Invalid geospatial archive for {source.source_id}")
                        temp_root = Path(tempfile.gettempdir()).resolve()
                        with tempfile.TemporaryDirectory(prefix="utilitydata-registry-", dir=temp_root) as temp_name:
                            temp_dir = Path(temp_name).resolve()
                            if not temp_dir.is_relative_to(temp_root):
                                raise ValueError("Registry temporary path escapes temporary root")
                            try:
                                extracted = materialize_archive_member(archive, member, temp_dir)
                            except ValueError as exc:
                                raise ValueError(f"Invalid geospatial archive for {source.source_id}: {exc}") from exc
                            info = pyogrio.read_info(extracted, layer=layer.layer)
                            if layer.grain in {"service_area", "network", "facility"} and not info.get("geometry_type"):
                                raise ValueError(f"Spatial layer has no geometry for {source.source_id}.{layer.layer}")
                            if layer.grain == "service_area" and info.get("geometry_type", "").removesuffix(" Z") not in {"Polygon", "MultiPolygon"}:
                                raise ValueError(f"Service-area layer is not polygonal for {source.source_id}.{layer.layer}")
                            available = set(info["fields"]) | {info.get("fid_column")}
                            declared = _declared_fields(layer)
                            _require_declared_names(source.source_id, declared, available, feature=False)
                            mappings = _value_maps(layer)
                            if mappings or layer.role_matrix:
                                columns = {item.field for item in mappings}
                                if layer.role_matrix:
                                    columns.update(layer.role_matrix.fields)
                                frame = pyogrio.read_dataframe(extracted, layer=layer.layer, columns=sorted(columns), read_geometry=False)
                                for mapping in mappings:
                                    for value in frame[mapping.field].unique():
                                        if not _is_null(value):
                                            _reject_coded_value(mapping, str(value), value, source.source_id)
                                if layer.role_matrix:
                                    for record in frame[layer.role_matrix.fields].drop_duplicates().to_dict("records"):
                                        _check_role_matrix(layer.role_matrix, record, source.source_id, role_cases)
                    if layer.layer.lower().endswith(".csv"):
                        if len(source.paths) != 1:
                            raise ValueError(f"CSV archive source needs exactly one path: {source.source_id}")
                        archive = (root / source.paths[0]).resolve()
                        if not archive.is_file():
                            raise ValueError(f"CSV source is unavailable: {source.source_id}")
                        with ExitStack() as stack:
                            if zipfile.is_zipfile(archive):
                                bundle = stack.enter_context(zipfile.ZipFile(archive))
                                if layer.layer not in bundle.namelist():
                                    raise ValueError(f"Missing archive member {source.source_id}.{layer.layer}")
                                raw = stack.enter_context(bundle.open(layer.layer))
                            elif archive.suffix.lower() == ".csv" and layer.layer == archive.name:
                                raw = stack.enter_context(archive.open("rb"))
                            else:
                                raise ValueError(f"Invalid CSV source for {source.source_id}.{layer.layer}")
                            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                                csv.field_size_limit(32 * 1024 * 1024)
                                reader = csv.reader(stream)
                                headers = next(reader, [])
                                if not headers or len(headers) != len(set(headers)) or any(not name for name in headers):
                                    raise ValueError(f"Invalid or duplicate CSV header for {source.source_id}.{layer.layer}")
                                declared = _declared_fields(layer)
                                _require_declared_names(source.source_id, declared, set(headers), feature=False)
                                mappings = _value_maps(layer)
                                positions = {mapping.field: headers.index(mapping.field) for mapping in mappings}
                                if layer.role_matrix:
                                    positions.update({field: headers.index(field) for field in layer.role_matrix.fields})
                                for row in reader:
                                    if len(row) != len(headers):
                                        raise ValueError(f"Malformed CSV row in {source.source_id}.{layer.layer}")
                                    for mapping in mappings:
                                        value = row[positions[mapping.field]]
                                        if value:
                                            _reject_coded_value(mapping, value, value, source.source_id)
                                    if layer.role_matrix:
                                        _check_role_matrix(layer.role_matrix, {field: row[positions[field]] or None for field in layer.role_matrix.fields}, source.source_id, role_cases)
                    continue
                metadata_path = (root / layer.metadata_path).resolve()
                if not metadata_path.is_relative_to(root) or not metadata_path.is_file():
                    raise ValueError(f"Invalid metadata path for {source.source_id}")
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if str(metadata.get("id")) != layer.layer:
                    raise ValueError(f"Layer ID does not match metadata for {source.source_id}")
                if not any(metadata_path.is_relative_to((root / raw_path).resolve()) for raw_path in source.paths):
                    raise ValueError(f"Layer metadata is outside declared source paths for {source.source_id}")
                if source.driver == "arcgis":
                    snapshot_path = metadata_path.parent / "snapshot.json"
                    if not snapshot_path.is_file():
                        raise ValueError(f"Missing snapshot for {source.source_id}")
                    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                    if str(snapshot.get("source_layer", "")).rstrip("/").casefold() != (source.url or "").rstrip("/").casefold():
                        raise ValueError(f"Snapshot URL does not match source for {source.source_id}")
                declared = _declared_fields(layer)
                _require_declared_names(source.source_id, declared, {field["name"] for field in metadata.get("fields", [])}, feature=False)
                if source.driver == "arcgis":
                    pages = _snapshot_pages(snapshot, metadata_path.parent, source.source_id)
                    seen = 0
                    for page_path, expected_count, expected_hash in pages:
                        sha = hashlib.sha256()
                        with page_path.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                sha.update(block)
                        if sha.hexdigest() != expected_hash:
                            raise ValueError(f"ArcGIS page hash mismatch: {page_path.name}")
                        with gzip.open(page_path, "rt", encoding="utf-8") as stream:
                            features = json.load(stream).get("features")
                        if not isinstance(features, list) or len(features) != expected_count:
                            raise ValueError(f"ArcGIS page count mismatch for {source.source_id}: {page_path.name}")
                        seen += len(features)
                        for feature in features:
                            attributes = feature.get("attributes") if type(feature) is dict else None
                            if type(attributes) is not dict:
                                raise ValueError(f"Missing attribute in {source.source_id}: {', '.join(sorted(declared))}")
                            _require_declared_names(source.source_id, declared, set(attributes), feature=True)
                            _check_feature_values(layer, attributes, source.source_id, role_cases)
                    _require_arcgis_counts(snapshot, seen, source.source_id)
                elif _saved_page_relatives(metadata_path.parent, source.source_id):
                    raise ValueError(f"Saved feature pages require an ArcGIS snapshot for {source.source_id}")
    return sources
