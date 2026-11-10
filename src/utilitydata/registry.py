"""Hand-declared source registry and strict review-state validation."""

import csv
import gzip
import io
import json
import shutil
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

import pandas as pd
import pyogrio
import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Sector = Literal["water", "electric", "wastewater", "natural_gas", "multi_utility", "reference", "stormwater", "telecommunications", "petroleum_liquids"]
Grain = Literal["service_area", "facility", "network", "admin_association", "registry_table"]
Authority = Literal["utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy"]
AUTHORITIES = {"utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy"}
ZONE_ROLES = {"active_retail_service", "certified_franchise_territory", "planned_or_future_service", "administrative_unit_proxy", "source_watershed_or_basin", "regional_wholesale_or_district", "not_serviced_or_excluded", "unassigned_area"}
STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "AS", "GU", "MP", "PR", "VI"}


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FieldMap(RegistryModel):
    field: str = Field(min_length=1)
    values: dict[str, str] = Field(min_length=1)
    on_null: Literal["reject", "unknown"]


class Layer(RegistryModel):
    layer: str = Field(min_length=1)
    archive_member: str | None = None
    sector: Sector | None = None
    grain: Grain | None = None
    role: str | None = None
    role_field: FieldMap | None = None
    authority: Authority | FieldMap | None = None
    boundary_representation: Literal["unmodeled", "modeled", "mixed", "unknown"] = "unknown"
    name_field: str | None = None
    on_missing_name: Literal["preserve_and_review"] | None = None
    id_fields: dict[str, str] = Field(default_factory=dict)
    attribute_fields: dict[str, str] = Field(default_factory=dict)
    pwsid_rule: Literal["state_prefix_7"] | None = None
    on_invalid_pwsid: Literal["preserve_raw_without_federal_id"] | None = None
    state_field: str | None = None
    state_fixed: str | None = None
    state_from_geometry: StrictBool = False
    status_field: FieldMap | None = None
    vintage_field: str | None = None
    vintage_fixed: str | None = None
    dissolve: StrictBool = False
    metadata_path: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def exclusive_fields(self):
        if self.role and self.role_field:
            raise ValueError("Choose role or role_field, not both")
        if sum(bool(x) for x in (self.state_field, self.state_fixed, self.state_from_geometry)) > 1:
            raise ValueError("Choose only one state source")
        if self.vintage_field and self.vintage_fixed:
            raise ValueError("Choose vintage_field or vintage_fixed, not both")
        if self.role and self.role not in ZONE_ROLES:
            raise ValueError("Unknown zone role")
        if self.role_field and set(self.role_field.values.values()) - ZONE_ROLES:
            raise ValueError("Unknown zone role mapping")
        if self.role_field and self.role_field.on_null != "reject":
            raise ValueError("Null role values must be rejected and reconciled")
        if isinstance(self.authority, FieldMap) and set(self.authority.values.values()) - AUTHORITIES:
            raise ValueError("Unknown authority mapping")
        if isinstance(self.authority, FieldMap) and self.authority.on_null != "reject":
            raise ValueError("Null authority values must be rejected and reconciled")
        if self.status_field and set(self.status_field.values.values()) - {"active", "inactive", "unknown"}:
            raise ValueError("Unknown status mapping")
        if self.state_fixed and self.state_fixed not in STATES:
            raise ValueError("Invalid fixed state")
        if self.pwsid_rule and ("pwsid" not in self.id_fields or not self.state_fixed):
            raise ValueError("A PWSID rule requires a PWSID field and fixed state")
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
            if layer.grain == "service_area" and (not (layer.role or layer.role_field) or not layer.authority):
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


def load_registry(directory: Path, *, require_reviewed: bool = True, raw_root: Path | None = None) -> list[Source]:
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
    if raw_root is not None:
        root = raw_root.resolve()
        for source in sources:
            if not source.reviewed:
                continue
            for raw_path in source.paths:
                path = (root / raw_path).resolve()
                if not path.is_relative_to(root) or not path.exists():
                    raise ValueError(f"Invalid source path for {source.source_id}: {raw_path}")
            for layer in source.layers:
                if source.driver == "arcgis" and not layer.metadata_path:
                    raise ValueError(f"Missing layer metadata for {source.source_id}")
                if not layer.metadata_path:
                    if not layer.archive_member and not layer.layer.lower().endswith(".csv"):
                        raise ValueError(f"No verifiable layer metadata for {source.source_id}.{layer.layer}")
                    if layer.archive_member:
                        if len(source.paths) != 1:
                            raise ValueError(f"Geospatial archive source needs exactly one path: {source.source_id}")
                        archive = (root / source.paths[0]).resolve()
                        member = layer.archive_member.replace("\\", "/")
                        if member.startswith("/") or ".." in member.split("/") or not zipfile.is_zipfile(archive):
                            raise ValueError(f"Invalid geospatial archive for {source.source_id}")
                        with zipfile.ZipFile(archive) as bundle:
                            if member not in bundle.namelist():
                                raise ValueError(f"Missing archive member {source.source_id}.{member}")
                            temp_root = Path(tempfile.gettempdir()).resolve()
                            with tempfile.TemporaryDirectory(prefix="utilitydata-registry-", dir=temp_root) as temp_name:
                                temp_dir = Path(temp_name).resolve()
                                if not temp_dir.is_relative_to(temp_root):
                                    raise ValueError("Registry temporary path escapes temporary root")
                                extracted = temp_dir / Path(member).name
                                with bundle.open(member) as raw, extracted.open("xb") as output:
                                    shutil.copyfileobj(raw, output, 4 * 1024 * 1024)
                                info = pyogrio.read_info(extracted, layer=layer.layer)
                                if layer.grain in {"service_area", "network", "facility"} and not info.get("geometry_type"):
                                    raise ValueError(f"Spatial layer has no geometry for {source.source_id}.{layer.layer}")
                                if layer.grain == "service_area" and info.get("geometry_type", "").removesuffix(" Z") not in {"Polygon", "MultiPolygon"}:
                                    raise ValueError(f"Service-area layer is not polygonal for {source.source_id}.{layer.layer}")
                                available = set(info["fields"]) | {info.get("fid_column")}
                                mapped = set(layer.id_fields.values()) | set(layer.attribute_fields.values()) | {x for x in (layer.name_field, layer.state_field, layer.vintage_field) if x}
                                mappings = [item for item in (layer.role_field, layer.status_field, layer.authority if isinstance(layer.authority, FieldMap) else None) if item]
                                mapped |= {item.field for item in mappings}
                                missing = mapped - available
                                if missing:
                                    raise ValueError(f"Missing mapped fields for {source.source_id}: {', '.join(sorted(missing))}")
                                if mappings:
                                    frame = pyogrio.read_dataframe(extracted, layer=layer.layer, columns=list({item.field for item in mappings}), read_geometry=False)
                                    for mapping in mappings:
                                        for value in frame[mapping.field].unique():
                                            if not pd.isna(value) and str(value) not in mapping.values:
                                                raise ValueError(f"Unmapped value {value!r} in {source.source_id}.{mapping.field}")
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
                                reader = csv.reader(stream)
                                headers = next(reader, [])
                                if not headers or len(headers) != len(set(headers)) or any(not name for name in headers):
                                    raise ValueError(f"Invalid or duplicate CSV header for {source.source_id}.{layer.layer}")
                                available = set(headers)
                                mapped = set(layer.id_fields.values()) | set(layer.attribute_fields.values()) | {x for x in (layer.name_field, layer.state_field, layer.vintage_field) if x}
                                mappings = [item for item in (layer.role_field, layer.status_field, layer.authority if isinstance(layer.authority, FieldMap) else None) if item]
                                mapped |= {item.field for item in mappings}
                                missing = mapped - available
                                if missing:
                                    raise ValueError(f"Missing mapped fields for {source.source_id}: {', '.join(sorted(missing))}")
                                positions = {mapping.field: headers.index(mapping.field) for mapping in mappings}
                                for row in reader:
                                    if len(row) != len(headers):
                                        raise ValueError(f"Malformed CSV row in {source.source_id}.{layer.layer}")
                                    for mapping in mappings:
                                        value = row[positions[mapping.field]]
                                        if value and value not in mapping.values:
                                            raise ValueError(f"Unmapped value {value!r} in {source.source_id}.{mapping.field}")
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
                available = {field["name"] for field in metadata.get("fields", [])}
                mapped = set(layer.id_fields.values()) | set(layer.attribute_fields.values()) | {x for x in (layer.name_field, layer.state_field, layer.vintage_field) if x}
                mapped |= {item.field for item in (layer.role_field, layer.status_field, layer.authority if isinstance(layer.authority, FieldMap) else None) if item}
                missing = mapped - available
                if missing:
                    raise ValueError(f"Missing mapped fields for {source.source_id}: {', '.join(sorted(missing))}")
                mappings = [item for item in (layer.role_field, layer.status_field, layer.authority if isinstance(layer.authority, FieldMap) else None) if item]
                if mappings:
                    for page in sorted(metadata_path.parent.glob("page*.json.gz")):
                        with gzip.open(page, "rt", encoding="utf-8") as stream:
                            features = json.load(stream).get("features", [])
                        for feature in features:
                            for mapping in mappings:
                                attributes = feature.get("attributes", {})
                                if mapping.field not in attributes:
                                    raise ValueError(f"Missing attribute in {source.source_id}.{mapping.field}")
                                value = attributes[mapping.field]
                                if value is not None and str(value) not in mapping.values:
                                    raise ValueError(f"Unmapped value {value!r} in {source.source_id}.{mapping.field}")
    return sources
