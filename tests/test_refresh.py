import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
import yaml

from utilitydata.bronze.blobs import blob_file, blob_name
from utilitydata.bronze.drivers.arcgis import fetch_arcgis
from utilitydata.bronze.drivers.discover import fetch_discover
from utilitydata.bronze.drivers.http import fetch_http
from utilitydata.bronze.drivers.protocol import FetchRequest, HttpResponse, PreviousFile
from utilitydata.bronze.gate import Measurement, count_outside_state, evaluate_gate
from utilitydata.bronze.refresh import _select_named, refresh, reproduced_scripts
from utilitydata.core.config import (
    ARCGIS_PAGE_SIZE,
    REFRESH_AREA_DRIFT,
    REFRESH_COUNT_DRIFT,
)
from utilitydata.registry import Source
from utilitydata.sectors.tables import snapshot_path

_MANIFEST = pa.schema([
    ("source_id", pa.string()),
    ("relative_path", pa.string()),
    ("sha256", pa.string()),
    ("bytes", pa.int64()),
    ("retrieved_utc", pa.string()),
    ("feature_count", pa.int64()),
    ("has_geometry", pa.bool_()),
    ("status", pa.string()),
])


class RaisingTransport:
    def request(self, method, url, *, params, headers, data, timeout):
        raise AssertionError(f"transport was called for {url}")


class ScriptedTransport:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def request(self, method, url, *, params, headers, data, timeout):
        self.calls.append({"method": method, "url": url, "params": params, "headers": headers, "data": data})
        return self.handler(method, url, params=params, headers=headers, data=data, timeout=timeout)


def _csv(rows: int) -> bytes:
    lines = ["name", *(f"row-{index}" for index in range(rows))]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _source(driver: str = "http") -> dict:
    return {
        "source_id": "example_rows",
        "publisher": "Publisher",
        "driver": driver,
        "url": "https://example.test/rows.csv",
        "cadence": "irregular",
        "licence": "unknown",
        "redistribution": "internal_only",
        "reviewed": True,
        "paths": ["water/rows.csv"],
        "layers": [{
            "layer": "rows.csv",
            "sector": "water",
            "grain": "registry_table",
            "name_field": "name",
        }],
    }


def _freeze(tmp_path: Path, content: bytes, *, collection: bytes | None = None, driver: str = "http"):
    relative = "water/rows.csv"
    home = tmp_path / "home"
    raw = tmp_path / "raw"
    frozen = home / "snapshots" / "2026-Q4" / "files" / relative
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(content)
    current = raw / relative
    current.parent.mkdir(parents=True)
    current.write_bytes(content if collection is None else collection)
    digest = hashlib.sha256(content).hexdigest()
    row = {
        "source_id": "example_rows",
        "relative_path": relative,
        "sha256": digest,
        "bytes": len(content),
        "retrieved_utc": "2026-11-10T00:00:00Z",
        "feature_count": None,
        "has_geometry": False,
        "status": "nonspatial",
    }
    manifest = home / "snapshots" / "2026-Q4" / "manifest.parquet"
    pq.write_table(pa.Table.from_pylist([row], schema=_MANIFEST), manifest)
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "publisher.yaml").write_text(yaml.safe_dump({"sources": [_source(driver)]}), encoding="utf-8")
    return home, raw, registry, manifest.read_bytes(), digest


def _run(home, raw, registry, **kwargs):
    return refresh(
        "2027-Q1",
        previous="2026-Q4",
        home=home,
        raw_root=raw,
        registry_dir=registry,
        transport=kwargs.pop("transport", RaisingTransport()),
        **kwargs,
    )


def test_unchanged_source_is_skipped(tmp_path):
    content = _csv(4)
    home, raw, registry, manifest, digest = _freeze(tmp_path, content)
    result = _run(home, raw, registry, dry_run=True, limit=1)
    source = result.sources[0]
    assert source.action == "skipped" and source.hashes_match
    assert source.status == "nonspatial"
    assert source.blobs == (blob_name(digest),)
    assert blob_file(home, digest).read_bytes() == content
    assert (home / "snapshots" / "2026-Q4" / "manifest.parquet").read_bytes() == manifest
    assert not (home / "snapshots" / "2027-Q1").exists()
    assert str(home) not in result.report.read_text(encoding="utf-8")


def test_hash_change_is_detected(tmp_path):
    original = _csv(4)
    changed = _csv(4) + b"\n"
    home, raw, registry, manifest, digest = _freeze(tmp_path, original, collection=changed)
    result = _run(home, raw, registry, dry_run=True, limit=1)
    source = result.sources[0]
    assert source.action == "changed" and not source.hashes_match
    assert digest in source.differences[0]
    assert hashlib.sha256(changed).hexdigest() in source.differences[0]
    assert blob_file(home, digest).read_bytes() == original
    assert not blob_file(home, hashlib.sha256(changed).hexdigest()).exists()
    assert (home / "snapshots" / "2026-Q4" / "files" / "water" / "rows.csv").read_bytes() == original
    assert (home / "snapshots" / "2026-Q4" / "manifest.parquet").read_bytes() == manifest


def test_count_or_area_move_above_ten_percent_fails_the_gate():
    previous = Measurement(100, 10.0, frozenset({"name"}))
    assert evaluate_gate(previous, Measurement(110, 11.0, frozenset({"name"})), frozenset({"name"})) == ()
    count = evaluate_gate(previous, Measurement(111, 10.0, frozenset({"name"})), frozenset({"name"}))
    area = evaluate_gate(previous, Measurement(100, 11.1, frozenset({"name"})), frozenset({"name"}))
    assert count == ("feature count moved from 100 to 111",)
    assert area == ("total area moved from 10.0 to 11.1",)
    assert REFRESH_COUNT_DRIFT == 0.10 and REFRESH_AREA_DRIFT == 0.10
    assert evaluate_gate(Measurement(0, 0.0, frozenset()), Measurement(0, 0.0, frozenset()), frozenset()) == ()
    assert evaluate_gate(Measurement(0, None, frozenset()), Measurement(1, None, frozenset()), frozenset())


def test_disappeared_mapped_field_fails():
    previous = Measurement(2, None, frozenset({"name"}))
    current = Measurement(2, None, frozenset())
    failures = evaluate_gate(previous, current, frozenset({"name"}))
    assert failures == ("mapped field disappeared: name",)


def test_shapes_outside_the_expected_state_fail():
    state = shapely.box(0, 0, 1, 1)
    assert count_outside_state([shapely.points(0.2, 0.2)], state) == 0
    assert count_outside_state([shapely.points(2, 2)], state) == 1
    with pytest.raises(ValueError, match="missing"):
        count_outside_state([None], state)
    failures = evaluate_gate(Measurement(1, 0.0, frozenset(), 0, True), Measurement(1, 0.0, frozenset(), 1, True), frozenset())
    assert failures == ("1 shapes fall outside the expected state",)


def test_refresh_count_failure_carries_forward(tmp_path):
    original = _csv(10)
    updated = _csv(12)
    home, raw, registry, manifest, digest = _freeze(tmp_path, original)

    def handler(method, url, *, params, headers, data, timeout):
        assert headers["If-None-Match"] == f'"{digest}"'
        return HttpResponse(200, {}, updated)

    result = _run(home, raw, registry, dry_run=False, limit=1, transport=ScriptedTransport(handler))
    source = result.sources[0]
    assert source.action == "carried_forward" and source.status == "carried_forward"
    assert "feature count moved from 10 to 12" in source.note
    assert blob_file(home, digest).read_bytes() == original
    assert not blob_file(home, hashlib.sha256(updated).hexdigest()).exists()
    assert (home / "snapshots" / "2026-Q4" / "files" / "water" / "rows.csv").read_bytes() == original
    assert (home / "snapshots" / "2026-Q4" / "manifest.parquet").read_bytes() == manifest
    assert "carried_forward" in result.report.read_text(encoding="utf-8")


def test_forced_failure_carries_forward_without_replacing_bytes(tmp_path):
    original = _csv(4)
    updated = b"replaced"
    home, raw, registry, manifest, digest = _freeze(tmp_path, original, collection=updated)
    result = _run(home, raw, registry, dry_run=False, limit=1, forced_failures={"example_rows": "forced gate failure"})
    source = result.sources[0]
    assert source.action == "carried_forward" and source.status == "carried_forward"
    assert blob_file(home, digest).read_bytes() == original
    assert not blob_file(home, hashlib.sha256(updated).hexdigest()).exists()
    assert (home / "snapshots" / "2026-Q4" / "files" / "water" / "rows.csv").read_bytes() == original
    assert (home / "snapshots" / "2026-Q4" / "manifest.parquet").read_bytes() == manifest
    report = result.report.read_text(encoding="utf-8")
    assert "carried_forward" in report and str(home) not in report


def test_page_size_is_halved_once_on_a_simulated_timeout(tmp_path):
    calls = []

    def handler(method, url, *, params, headers, data, timeout):
        query = dict(params or {})
        if url.endswith("/query") and query.get("returnCountOnly") == "true":
            return HttpResponse(200, {}, b'{"count": 1000}')
        if url.endswith("/query") and query.get("returnIdsOnly") == "true":
            return HttpResponse(200, {}, json.dumps({"objectIds": list(range(1, 1001))}).encode())
        if url.endswith("/query"):
            identifiers = [int(part) for part in query["objectIds"].split(",")]
            calls.append(len(identifiers))
            if len(identifiers) == ARCGIS_PAGE_SIZE:
                raise TimeoutError("simulated")
            features = [{"attributes": {"OBJECTID": value, "name": "A"}, "geometry": {"x": 1, "y": 2}} for value in identifiers]
            return HttpResponse(200, {}, json.dumps({"features": features}).encode())
        metadata = {
            "id": 0,
            "type": "Feature Layer",
            "geometryType": "esriGeometryPoint",
            "objectIdField": "OBJECTID",
            "maxRecordCount": 2000,
            "fields": [{"name": "OBJECTID"}, {"name": "name"}],
        }
        return HttpResponse(200, {}, json.dumps(metadata).encode())

    source = Source.model_validate({
        "source_id": "example_points",
        "publisher": "Publisher",
        "driver": "arcgis",
        "url": "https://example.test/FeatureServer/0",
        "cadence": "irregular",
        "licence": "unknown",
        "reviewed": True,
        "paths": ["gis/points"],
        "layers": [{"layer": "0", "sector": "water", "grain": "facility", "name_field": "name"}],
    })
    staging = tmp_path / "staging"
    result = fetch_arcgis(FetchRequest(
        source=source,
        dry_run=False,
        staging=staging,
        previous=(),
        read_previous=lambda relative: b"",
        read_current=lambda relative: b"",
        transport=ScriptedTransport(handler),
        page_size=ARCGIS_PAGE_SIZE,
        timeout_seconds=5,
    ))
    assert calls == [ARCGIS_PAGE_SIZE, ARCGIS_PAGE_SIZE // 2, ARCGIS_PAGE_SIZE // 2]
    assert ARCGIS_PAGE_SIZE // 4 not in calls
    snapshot = json.loads((staging / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["downloaded_count"] == snapshot["expected_count_at_start"] == 1000
    assert sum(page["features"] for page in snapshot["pages"]) == 1000
    assert result.files


def test_arcgis_does_not_commit_when_geometry_or_counts_do_not_match(tmp_path):
    def handler(method, url, *, params, headers, data, timeout):
        query = dict(params or {})
        if url.endswith("/query") and query.get("returnCountOnly") == "true":
            return HttpResponse(200, {}, b'{"count": 1}')
        if url.endswith("/query") and query.get("returnIdsOnly") == "true":
            return HttpResponse(200, {}, b'{"objectIds": [1]}')
        if url.endswith("/query"):
            return HttpResponse(200, {}, b'{"features": [{"attributes": {"OBJECTID": 1, "name": "A"}, "geometry": null}]}')
        metadata = {
            "id": 0,
            "type": "Feature Layer",
            "geometryType": "esriGeometryPoint",
            "objectIdField": "OBJECTID",
            "maxRecordCount": 10,
            "fields": [{"name": "OBJECTID"}, {"name": "name"}],
        }
        return HttpResponse(200, {}, json.dumps(metadata).encode())

    source = Source.model_validate({
        "source_id": "example_points",
        "publisher": "Publisher",
        "driver": "arcgis",
        "url": "https://example.test/FeatureServer/0",
        "cadence": "irregular",
        "licence": "unknown",
        "reviewed": True,
        "paths": ["gis/points"],
        "layers": [{"layer": "0", "sector": "water", "grain": "facility", "name_field": "name"}],
    })
    staging = tmp_path / "staging"
    with pytest.raises(ValueError, match="missing geometry"):
        fetch_arcgis(FetchRequest(
            source=source,
            dry_run=False,
            staging=staging,
            previous=(),
            read_previous=lambda relative: b"",
            read_current=lambda relative: b"",
            transport=ScriptedTransport(handler),
            page_size=ARCGIS_PAGE_SIZE,
            timeout_seconds=5,
        ))
    assert not staging.exists()


def test_http_conditional_request_compares_hash():
    source = Source.model_validate(_source())
    original = b"old"
    digest = hashlib.sha256(original).hexdigest()
    seen = {}

    def handler(method, url, *, params, headers, data, timeout):
        seen["headers"] = headers
        if headers and headers.get("If-None-Match") == f'"{digest}"' and seen.get("once") is None:
            seen["once"] = True
            return HttpResponse(304, {}, b"")
        return HttpResponse(200, {}, b"new")

    request = FetchRequest(
        source=source,
        dry_run=False,
        staging=Path("unused"),
        previous=(PreviousFile("water/rows.csv", digest, len(original), "2026-11-10T00:00:00Z"),),
        read_previous=lambda relative: original,
        read_current=lambda relative: original,
        transport=ScriptedTransport(handler),
        page_size=ARCGIS_PAGE_SIZE,
        timeout_seconds=5,
    )
    unchanged = fetch_http(request)
    assert unchanged.unchanged and seen["headers"]["If-None-Match"] == f'"{digest}"'
    changed = fetch_http(request)
    assert not changed.unchanged
    assert digest in changed.differences[0] and hashlib.sha256(b"new").hexdigest() in changed.differences[0]


def test_discover_chooses_the_newest_dated_file():
    source = Source.model_validate({**_source("discover"), "url": "https://example.test/landing"})
    requested = []

    def handler(method, url, *, params, headers, data, timeout):
        requested.append(url)
        if url.endswith("file-2026-03-01.zip"):
            return HttpResponse(200, {}, b"newest")
        html = '<a href="file-2024-01-01.zip">old</a><a href="file-2026-03-01.zip">new</a>'
        return HttpResponse(200, {}, html.encode())

    result = fetch_discover(FetchRequest(
        source=source,
        dry_run=False,
        staging=Path("unused"),
        previous=(),
        read_previous=lambda relative: b"",
        read_current=lambda relative: b"",
        transport=ScriptedTransport(handler),
        page_size=ARCGIS_PAGE_SIZE,
        timeout_seconds=5,
    ))
    assert requested == ["https://example.test/landing", "https://example.test/file-2026-03-01.zip"]
    assert result.files[0].content == b"newest"


def test_custom_driver_does_not_download(tmp_path):
    content = _csv(2)
    home, raw, registry, _manifest, _digest = _freeze(tmp_path, content, driver="custom")
    result = _run(home, raw, registry, dry_run=False, limit=1)
    assert result.sources[0].action == "skipped"
    assert result.sources[0].hashes_match


def test_conditional_publish_points_at_blobs_without_copying_files(tmp_path):
    content = _csv(3)
    home, raw, registry, manifest, digest = _freeze(tmp_path, content)

    def handler(method, url, *, params, headers, data, timeout):
        return HttpResponse(304, {}, b"")

    result = _run(home, raw, registry, dry_run=False, transport=ScriptedTransport(handler))
    assert result.published and result.sources[0].action == "skipped"
    assert not (home / "snapshots" / "2027-Q1" / "files").exists()
    assert snapshot_path(home, "2027-Q1", "water/rows.csv").read_bytes() == content
    assert snapshot_path(home, "2026-Q4", "water/rows.csv").read_bytes() == content
    assert (home / "snapshots" / "2026-Q4" / "manifest.parquet").read_bytes() == manifest
    stored = blob_file(home, digest)
    assert stored.is_file() and stored.read_bytes() == content


def test_snapshot_file_wins_over_a_blob_pointer(tmp_path):
    home = tmp_path / "home"
    copied = home / "snapshots" / "2026-Q4" / "files" / "water/rows.csv"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b"copied")
    digest = hashlib.sha256(b"blob").hexdigest()
    blob_file(home, digest).parent.mkdir(parents=True)
    blob_file(home, digest).write_bytes(b"blob")
    row = {
        "source_id": "example_rows",
        "relative_path": "water/rows.csv",
        "sha256": digest,
        "bytes": 4,
        "blob": blob_name(digest),
        "status": "nonspatial",
        "action": "skipped",
        "feature_count": None,
        "area": None,
    }
    schema = pa.schema([
        ("source_id", pa.string()),
        ("relative_path", pa.string()),
        ("sha256", pa.string()),
        ("bytes", pa.int64()),
        ("blob", pa.string()),
        ("status", pa.string()),
        ("action", pa.string()),
        ("feature_count", pa.int64()),
        ("area", pa.float64()),
    ])
    pq.write_table(pa.Table.from_pylist([row], schema=schema), home / "snapshots" / "2026-Q4" / "manifest.parquet")
    assert snapshot_path(home, "2026-Q4", "water/rows.csv").read_bytes() == b"copied"
    copied.unlink()
    assert snapshot_path(home, "2026-Q4", "water/rows.csv").read_bytes() == b"blob"


def test_named_refresh_keeps_a_draft_and_rejects_an_unknown_id():
    source = type("Source", (), {"source_id": "draft_layer"})()
    manifest = pa.table({"source_id": ["draft_layer", "other"], "bytes": [3, 4]}).to_pandas()
    chosen, count, excluded = _select_named([source], manifest, ("draft_layer",))
    assert count == 1
    assert excluded == (0, 0)
    assert chosen[0][0].source_id == "draft_layer"
    assert list(chosen[0][1]["source_id"]) == ["draft_layer"]
    with pytest.raises(ValueError, match="not in the registry"):
        _select_named([source], manifest, ("missing",))
    absent = type("Source", (), {"source_id": "missing_rows"})()
    with pytest.raises(ValueError, match="previous snapshot"):
        _select_named([source, absent], manifest, ("missing_rows",))


def test_collect_script_is_deleted_only_when_every_path_is_reproduced(tmp_path):
    covered = {"water/rows.csv"}
    scripts = tmp_path / "collection"
    scripts.mkdir()
    ready = scripts / "collect_round1.py"
    ready.write_text("SOURCES = [('water/rows.csv', 'https://example.test/rows.csv')]\n", encoding="utf-8")
    partial = scripts / "collect_round2.py"
    partial.write_text("SOURCES = [('water/rows.csv', 'https://example.test/a'), ('water/other.csv', 'https://example.test/b')]\n", encoding="utf-8")
    assert reproduced_scripts(covered, scripts) == ["collect_round1.py"]
    content = _csv(1)
    home, raw, registry, _manifest, _digest = _freeze(tmp_path, content)
    result = _run(home, raw, registry, dry_run=True, limit=1, script_dir=scripts)
    assert result.deleted_scripts == ("collect_round1.py",)
    assert not ready.exists()
    assert partial.exists()
