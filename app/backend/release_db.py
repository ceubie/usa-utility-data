"""One read-only DuckDB connection over the release Parquet files."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from threading import Lock

import duckdb

from app.backend.settings import Settings
from utilitydata.gold.text import county_name_key, place_name_key, search_key

_AREA_FILES = (
    "internal/territories_water.parquet",
    "shareable/territories_water.parquet",
    "internal/territories_electric.parquet",
    "shareable/territories_electric.parquet",
    "internal/wastewater_service_area.parquet",
    "shareable/wastewater_service_area.parquet",
    "internal/gas_service_area.parquet",
    "shareable/gas_service_area.parquet",
    "internal/territories_wastewater.parquet",
    "shareable/territories_wastewater.parquet",
    "internal/territories_gas.parquet",
    "shareable/territories_gas.parquet",
)
_COUNTY_COVERAGE_FILES = (
    "system_county_coverage.parquet",
    "electric_system_county_coverage.parquet",
    "wastewater_system_county_coverage.parquet",
    "gas_system_county_coverage.parquet",
)
_DISPLAY_FILES = (
    "internal/service_area_display.parquet",
    "shareable/service_area_display.parquet",
)
_SEARCH_FILES = (
    "internal/entity_search.parquet",
    "shareable/entity_search.parquet",
)
_KINDS = frozenset({"system", "organization", "facility", "county", "place", "state"})
_SEGMENT = re.compile(r"[A-Za-z0-9_]+")


class ReleaseDB:
    """SELECT-only access to one release. Each request uses its own cursor."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.release_dir = settings.release_dir
        self.base = settings.graph_base_iri
        self.row_limit = settings.row_limit
        self._lock = Lock()
        self._connection = duckdb.connect()
        try:
            self._connection.execute("LOAD spatial")
        except duckdb.Error as exc:
            self._connection.close()
            raise ValueError("The DuckDB spatial extension is not available") from exc
        self._states = self._load_states()
        self._usps = {str(row["usps"]) for row in self._states if row.get("usps")}

    def close(self) -> None:
        self._connection.close()

    def search_entities(
        self,
        query: str,
        *,
        kind: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Find entities by name or identifier. The query text is a bound parameter."""
        text = query.strip()
        if not text:
            return []
        if kind is not None and kind not in _KINDS:
            return []
        capped = _cap(limit, 100)
        key = search_key(text, state_codes=self._usps) or ""
        usps, fips = self._resolve_state(state)
        like = _like_literal(key or text)
        with self._cursor() as cursor:
            rows: list[dict] = []
            if kind in {None, "system"}:
                rows.extend(self._search_index(cursor, key, like, text, usps, fips, capped))
            rows.extend(self._search_nodes(cursor, text, kind, usps, fips, capped))
        return _dedupe(rows)[:capped]

    def locate_place(self, name: str, *, state: str | None = None, limit: int = 25) -> list[dict]:
        """Resolve a place, county, or state name."""
        text = name.strip()
        if not text:
            return []
        capped = _cap(limit, 100)
        usps, fips = self._resolve_state(state)
        like = _like_literal(text)
        with self._cursor() as cursor:
            rows = []
            rows.extend(self._places(cursor, text, like, usps, fips, capped))
            rows.extend(self._counties(cursor, text, like, usps, fips, capped))
            rows.extend(self._state_names(cursor, text, like, usps, fips, capped))
        return _rank_places(rows, text)[:capped]

    def who_serves(self, lat: float, lon: float, sector: str) -> list[dict]:
        """Return best service areas whose exact polygon covers the point."""
        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            raise ValueError("lat or lon is out of range")
        paths = self._existing(_AREA_FILES)
        with self._cursor() as cursor:
            cursor.execute(
                """
                WITH hit AS (
                    SELECT DISTINCT service_area_id, system_id, sector
                    FROM read_parquet(?, union_by_name = true)
                    WHERE is_best
                      AND sector = ?
                      AND geometry IS NOT NULL
                      AND ST_Covers(geometry, ST_Point(?, ?))
                )
                SELECT
                    hit.service_area_id,
                    hit.system_id,
                    hit.sector,
                    system.name,
                    system.status,
                    system.primary_state,
                    area.authority,
                    area.source_vintage_date,
                    area.boundary_representation,
                    area.zone_role,
                    area.licence,
                    area.grain
                FROM hit
                LEFT JOIN read_parquet(?) AS system ON system.system_id = hit.system_id
                LEFT JOIN read_parquet(?) AS area ON area.service_area_id = hit.service_area_id
                LIMIT ?
                """,
                [
                    paths,
                    sector,
                    lon,
                    lat,
                    self._node_path("utility_system"),
                    self._node_path("service_area"),
                    self.row_limit,
                ],
            )
            rows = _table(cursor)
        for row in rows:
            row["iri"] = _iri(self.base, "system", row.get("system_id"))
            row["service_area_iri"] = _iri(self.base, "area", row.get("service_area_id"))
        return rows

    def service_areas(
        self,
        *,
        ids: list[str] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        sector: str | None = None,
        simplify_degrees: float = 0.01,
        limit: int = 300,
    ) -> tuple[list[dict], bool]:
        """Return simplified display features for ids or a bounding box."""
        if not ids and bbox is None:
            raise ValueError("Service areas need an id or a bbox.")
        capped = _cap(limit, 300)
        clauses = ["abs(simplify_degrees - ?) < 1e-9"]
        params: list[object] = [simplify_degrees]
        if sector is not None:
            clauses.append("sector = ?")
            params.append(sector)
        if ids:
            clauses.append("service_area_id IN (SELECT UNNEST(?))")
            params.append(list(ids))
        if bbox is not None:
            clauses.append("ST_Intersects(geometry, ST_MakeEnvelope(?, ?, ?, ?))")
            params.extend(bbox)
        params.append(capped + 1)
        where = " AND ".join(clauses)
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT service_area_id, system_id, sector, zone_role, authority, licence,
                       simplify_degrees, ST_AsGeoJSON(geometry) AS geojson
                FROM read_parquet(?, union_by_name = true)
                WHERE {where}
                LIMIT ?
                """,
                [self._existing(_DISPLAY_FILES), *params],
            )
            rows = _table(cursor)
        truncated = len(rows) > capped
        return rows[:capped], truncated

    def county_statistics(
        self,
        *,
        sector: str | None = None,
        county_geoid: str | None = None,
    ) -> list[dict]:
        """Return county coverage rows. Wastewater and gas use their own coverage files."""
        paths = [
            str(self.release_dir / folder / name)
            for name in _COUNTY_COVERAGE_FILES
            for folder in ("internal", "shareable")
            if (self.release_dir / folder / name).is_file()
        ]
        if not paths:
            raise ValueError("Release file is missing: system_county_coverage.parquet")
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT system_id, county_geoid, state, sector, pop_in_area, pop_share_of_county,
                       area_share, evidence, authority, is_served, licence, source_id
                FROM read_parquet(?, union_by_name = true)
                WHERE (? IS NULL OR sector = ?)
                  AND (? IS NULL OR county_geoid = ?)
                ORDER BY sector, county_geoid, system_id
                LIMIT ?
                """,
                [paths, sector, sector, county_geoid, county_geoid, self.row_limit],
            )
            return _table(cursor)

    def scorecard(self, *, state: str | None = None, sector: str | None = None) -> list[dict]:
        """Return the state and sector scorecard."""
        path = self.release_dir / "internal" / "state_sector_scorecard.parquet"
        if not path.is_file():
            raise ValueError("Release file is missing: internal/state_sector_scorecard.parquet")
        usps, _fips = self._resolve_state(state) if state else (None, None)
        state_value = usps or (state.strip() if state else None)
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM read_parquet(?)
                WHERE (? IS NULL OR state = ?)
                  AND (? IS NULL OR sector = ?)
                ORDER BY state, sector
                LIMIT ?
                """,
                [str(path), state_value, state_value, sector, sector, self.row_limit],
            )
            return _table(cursor)

    @contextmanager
    def _cursor(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            cursor = self._connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def _load_states(self) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT usps, state AS fips, name FROM read_parquet(?)",
                [self._node_path("state")],
            )
            return _table(cursor)

    def _resolve_state(self, value: str | None) -> tuple[str | None, str | None]:
        if value is None or not value.strip():
            return None, None
        token = value.strip()
        folded = token.casefold()
        for row in self._states:
            usps = str(row.get("usps") or "")
            fips = str(row.get("fips") or "")
            name = str(row.get("name") or "")
            if folded in {usps.casefold(), fips, name.casefold()}:
                return usps or None, fips or None
        return token, token

    def _search_index(
        self,
        cursor: duckdb.DuckDBPyConnection,
        key: str,
        like: str,
        text: str,
        usps: str | None,
        fips: str | None,
        limit: int,
    ) -> list[dict]:
        paths = self._existing(_SEARCH_FILES)
        cursor.execute(
            """
            SELECT entity_id, kind, state, label, label_role, scheme, licence
            FROM read_parquet(?, union_by_name = true)
            WHERE (
                (? <> '' AND (search_norm = ? OR search_norm LIKE ('%' || ? || '%') ESCAPE '\\'))
                OR label = ?
            )
            AND (? IS NULL OR state = ? OR state = ?)
            LIMIT ?
            """,
            [paths, key, key, like, text, usps, usps, fips, limit],
        )
        rows = []
        for row in _table(cursor):
            rows.append({
                "iri": _iri(self.base, "system", row.get("entity_id")),
                "id": row.get("entity_id"),
                "kind": row.get("kind") or "system",
                "label": row.get("label"),
                "state": row.get("state"),
                "sector": None,
                "status": None,
                "match": row.get("scheme") or row.get("label_role"),
            })
        return rows

    def _search_nodes(
        self,
        cursor: duckdb.DuckDBPyConnection,
        text: str,
        kind: str | None,
        usps: str | None,
        fips: str | None,
        limit: int,
    ) -> list[dict]:
        like = _like_literal(text)
        found: list[dict] = []
        specs = (
            ("system", "utility_system", "system_id", "primary_state", True, True),
            ("organization", "organization", "org_id", "state", True, False),
            ("facility", "facility", "facility_id", "state", True, True),
            ("county", "county", "county_geoid", "state", False, False),
            ("place", "place", "place_geoid", "state", False, False),
            ("state", "state", "usps", "usps", False, False),
        )
        for node_kind, table, identifier, state_column, has_sector, has_status in specs:
            if kind is not None and kind != node_kind:
                continue
            extra = []
            if has_sector:
                extra.append("sector")
            if has_status:
                extra.append("status")
            selected = ", ".join(["iri", f"{identifier} AS id", "name", f"{state_column} AS state", *extra])
            name_sql = "(name ILIKE ('%' || ? || '%') ESCAPE '\\' OR " + identifier + " = ? OR iri = ?)"
            params = [self._node_path(table), like, text, f"{self.base}{_kind_segment(node_kind)}/{text}"]
            if node_kind in {"county", "place"}:
                name_sql = (
                    "(name ILIKE ('%' || ? || '%') ESCAPE '\\' OR namelsad ILIKE ('%' || ? || '%') ESCAPE '\\' OR "
                    + identifier
                    + " = ? OR iri = ?)"
                )
                params = [
                    self._node_path(table),
                    like,
                    like,
                    text,
                    f"{self.base}{_kind_segment(node_kind)}/{text}",
                ]
            params.extend([usps, usps, fips, limit])
            cursor.execute(
                f"""
                SELECT {selected}
                FROM read_parquet(?)
                WHERE {name_sql}
                  AND (? IS NULL OR {state_column} = ? OR {state_column} = ?)
                LIMIT ?
                """,
                params,
            )
            for row in _table(cursor):
                found.append({
                    "iri": row.get("iri"),
                    "id": row.get("id"),
                    "kind": node_kind,
                    "label": row.get("name"),
                    "state": row.get("state"),
                    "sector": row.get("sector"),
                    "status": row.get("status"),
                    "match": "name",
                })
        return found

    def _places(self, cursor, text, like, usps, fips, limit) -> list[dict]:
        cursor.execute(
            """
            SELECT place_geoid AS id, iri, name, namelsad, state AS state_fips
            FROM read_parquet(?)
            WHERE (name ILIKE ('%' || ? || '%') ESCAPE '\\'
                   OR namelsad ILIKE ('%' || ? || '%') ESCAPE '\\'
                   OR place_geoid = ?)
              AND (? IS NULL OR state = ? OR state = ?)
            LIMIT ?
            """,
            [self._node_path("place"), like, like, text, usps, usps, fips, limit],
        )
        return [_geo_row("place", row, self.base, self._states) for row in _table(cursor)]

    def _counties(self, cursor, text, like, usps, fips, limit) -> list[dict]:
        cursor.execute(
            """
            SELECT county_geoid AS id, iri, name, namelsad, state AS state_fips
            FROM read_parquet(?)
            WHERE (name ILIKE ('%' || ? || '%') ESCAPE '\\'
                   OR namelsad ILIKE ('%' || ? || '%') ESCAPE '\\'
                   OR county_geoid = ?)
              AND (? IS NULL OR state = ? OR state = ?)
            LIMIT ?
            """,
            [self._node_path("county"), like, like, text, usps, usps, fips, limit],
        )
        return [_geo_row("county", row, self.base, self._states) for row in _table(cursor)]

    def _state_names(self, cursor, text, like, usps, fips, limit) -> list[dict]:
        cursor.execute(
            """
            SELECT usps AS id, iri, name, usps AS namelsad, state AS state_fips, usps
            FROM read_parquet(?)
            WHERE (name ILIKE ('%' || ? || '%') ESCAPE '\\' OR usps = ?)
              AND (? IS NULL OR usps = ? OR state = ?)
            LIMIT ?
            """,
            [self._node_path("state"), like, text.upper(), usps, usps, fips, limit],
        )
        rows = []
        for row in _table(cursor):
            rows.append({
                "kind": "state",
                "id": row.get("id"),
                "iri": row.get("iri"),
                "name": row.get("name"),
                "namelsad": row.get("name"),
                "state_fips": row.get("state_fips"),
                "state_usps": row.get("usps"),
            })
        return rows

    def _existing(self, relatives: tuple[str, ...]) -> list[str]:
        found = [str(self.release_dir / relative) for relative in relatives if (self.release_dir / relative).is_file()]
        if not found:
            raise ValueError(f"Release file is missing: {relatives[0]}")
        return found

    def _node_path(self, name: str) -> str:
        if not re.fullmatch(r"[a-z_]+", name):
            raise ValueError("Unknown node table")
        relative = f"graph/nodes/{name}.parquet"
        path = self.release_dir / relative
        if not path.is_file():
            raise ValueError(f"Release file is missing: {relative}")
        return str(path)


def _table(cursor: duckdb.DuckDBPyConnection) -> list[dict]:
    columns = [item[0] for item in cursor.description or []]
    return [{column: _plain(value) for column, value in zip(columns, record, strict=True)} for record in cursor.fetchall()]


def _plain(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _cap(limit: int, ceiling: int) -> int:
    return max(1, min(int(limit), ceiling))


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _iri(base: str, kind: str, identifier: object) -> str | None:
    if not isinstance(identifier, str) or not _SEGMENT.fullmatch(identifier):
        return None
    return f"{base}{kind}/{identifier}"


def _kind_segment(kind: str) -> str:
    return {
        "system": "system",
        "organization": "org",
        "facility": "facility",
        "county": "county",
        "place": "place",
        "state": "state",
    }[kind]


def _geo_row(kind: str, row: dict, base: str, states: list[dict]) -> dict:
    fips = str(row.get("state_fips") or "")
    usps = next((str(item["usps"]) for item in states if str(item.get("fips") or "") == fips), None)
    return {
        "kind": kind,
        "id": row.get("id"),
        "iri": row.get("iri") or _iri(base, kind if kind != "organization" else "org", row.get("id")),
        "name": row.get("name"),
        "namelsad": row.get("namelsad"),
        "state_fips": fips or None,
        "state_usps": usps,
    }


def _rank_places(rows: list[dict], text: str) -> list[dict]:
    place_key = place_name_key(text)
    county_key = county_name_key(text)
    folded = text.casefold()
    exact: list[dict] = []
    partial: list[dict] = []
    for row in rows:
        name = str(row.get("name") or "")
        matched = False
        if row["kind"] == "place":
            matched = place_name_key(name) == place_key
        elif row["kind"] == "county":
            matched = county_name_key(name) == county_key or county_name_key(row.get("namelsad")) == county_key
        elif row["kind"] == "state":
            matched = name.casefold() == folded or str(row.get("id") or "").casefold() == folded
        if matched:
            exact.append(row)
        else:
            partial.append(row)
    return exact + partial


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[tuple[object, object, object]] = set()
    output: list[dict] = []
    for row in rows:
        key = (row.get("kind"), row.get("id"), row.get("label"))
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output
