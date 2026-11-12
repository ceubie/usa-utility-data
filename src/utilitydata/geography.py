"""Census reference downloads and the geography tables built from them.

File locations come from home-storage registry entries. State FIPS codes are the
published Census area list used to expand those URL templates.
"""

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import requests
from pyogrio.errors import DataSourceError
from requests import Response

from utilitydata.core.config import DEFAULT_QUARTER
from utilitydata.registry import Layer, Source, load_registry

CENSUS_AREAS: tuple[tuple[str, str], ...] = (
    ("01", "AL"), ("02", "AK"), ("04", "AZ"), ("05", "AR"), ("06", "CA"), ("08", "CO"), ("09", "CT"), ("10", "DE"),
    ("11", "DC"), ("12", "FL"), ("13", "GA"), ("15", "HI"), ("16", "ID"), ("17", "IL"), ("18", "IN"), ("19", "IA"),
    ("20", "KS"), ("21", "KY"), ("22", "LA"), ("23", "ME"), ("24", "MD"), ("25", "MA"), ("26", "MI"), ("27", "MN"),
    ("28", "MS"), ("29", "MO"), ("30", "MT"), ("31", "NE"), ("32", "NV"), ("33", "NH"), ("34", "NJ"), ("35", "NM"),
    ("36", "NY"), ("37", "NC"), ("38", "ND"), ("39", "OH"), ("40", "OK"), ("41", "OR"), ("42", "PA"), ("44", "RI"),
    ("45", "SC"), ("46", "SD"), ("47", "TN"), ("48", "TX"), ("49", "UT"), ("50", "VT"), ("51", "VA"), ("53", "WA"),
    ("54", "WV"), ("55", "WI"), ("56", "WY"), ("60", "AS"), ("66", "GU"), ("69", "MP"), ("72", "PR"), ("78", "VI"),
)
# The 2020 Block Assignment File directory publishes 52 zips. It has no file for these island areas.
BAF_EXCLUDED = frozenset({"60", "66", "69", "78"})
# 2020 resident population of the 50 states and the District of Columbia. Puerto Rico and the island areas are excluded.
POPULATION_EXCLUDED = frozenset({"60", "66", "69", "72", "78"})
EXPECTED_POP20 = 331_449_281
HANDLED_LAYERS = frozenset({
    "tabblock20", "tiger_place", "tiger_cousub", "tiger_tract", "tiger_zcta520", "tiger_aiannh", "tiger_county",
    "tiger_state", "INCPLACE_CDP", "COUSUB", "MCD", "AIANNH", "ct_county_crosswalk", "government_units",
})
_SPREADSHEET_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_USER_AGENT = {"User-Agent": "utilitydata-reference/0.1"}

if len(CENSUS_AREAS) != 56 or len({code for code, _usps in CENSUS_AREAS}) != 56:
    raise RuntimeError("Census area list must contain 56 unique state FIPS codes")


def download_census(home: Path, registry_dir: Path) -> list[Path]:
    """Download every file declared by the home-storage Census sources."""
    jobs = download_jobs(home, registry_dir)
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_download_file, url, path): (url, path) for url, path in jobs}
        for future in as_completed(futures):
            url, path = futures[future]
            try:
                future.result()
            except (OSError, requests.RequestException, ValueError) as exc:
                failures.append(f"{url}: {exc}")
            else:
                print(f"ready {path.relative_to(home).as_posix()}", flush=True)
    if failures:
        raise ValueError("Census downloads failed:\n" + "\n".join(failures))
    return [path for _url, path in jobs]


def download_jobs(home: Path, registry_dir: Path) -> list[tuple[str, Path]]:
    """Return the Census URL and data-root path for each declared file."""
    jobs: list[tuple[str, Path]] = []
    for source in _home_sources(registry_dir):
        if len(source.paths) != 1 or not source.url:
            raise ValueError(f"{source.source_id} needs one home path and a url")
        relative = source.paths[0]
        if "{" in source.url:
            areas = CENSUS_AREAS
            if any(layer.layer == "INCPLACE_CDP" for layer in source.layers):
                areas = tuple(area for area in areas if area[0] not in BAF_EXCLUDED)
            for statefp, usps in areas:
                url = source.url.format(statefp=statefp, usps=usps)
                if "{" in url or "}" in url:
                    raise ValueError(f"Unresolved Census url template: {url}")
                jobs.append((url, home / relative / url.rsplit("/", 1)[-1]))
        else:
            jobs.append((source.url, home / relative))
    destinations = [path for _url, path in jobs]
    if len(destinations) != len(set(destinations)) or len({url for url, _path in jobs}) != len(jobs):
        raise ValueError("Census download URLs or paths are not unique")
    return jobs


def build_reference(home: Path, registry_dir: Path, *, quarter: str = DEFAULT_QUARTER) -> dict[str, int]:
    """Build the reference tables. Raise if a declared column or block county is missing."""
    if not re.fullmatch(r"[0-9]{4}-Q[1-4]", quarter):
        raise ValueError("Reference quarter must be formatted YYYY-QN")
    index = _layer_index(registry_dir)
    jobs = download_jobs(home, registry_dir)
    missing_files = [path.name for _url, path in jobs if not path.is_file()]
    if missing_files:
        raise ValueError(f"{len(missing_files)} Census files are not downloaded, first: {missing_files[0]}")
    counties = _read_named_areas(index["tiger_county"], _paths_for(home, index["tiger_county"][0], jobs))
    places = _read_named_areas(index["tiger_place"], _paths_for(home, index["tiger_place"][0], jobs))
    states = _read_named_areas(index["tiger_state"], _paths_for(home, index["tiger_state"][0], jobs))
    blocks = _read_blocks(home, index, jobs)
    crosswalk = read_crosswalk(home / index["ct_county_crosswalk"][0].paths[0], index["ct_county_crosswalk"][1].attribute_fields)
    require_old_county_count(crosswalk, 8)
    blocks, alias = apply_county_crosswalk(blocks, crosswalk)
    blocks = resolve_ambiguous_counties(blocks, home / index["tiger_county"][0].paths[0])
    _check_area_identity(counties, "county_geoid", ("state", "countyfp"), "County GEOID")
    _check_area_identity(places, "place_geoid", ("state", "placefp"), "Place GEOID")
    if not states["geoid"].eq(states["state"]).all():
        raise ValueError("State GEOID does not match STATEFP")
    blocks, outside_places = _finish_blocks(blocks, places)
    missing_counties = sorted(set(blocks["county_geoid"]) - set(counties["county_geoid"]))
    if missing_counties:
        raise ValueError(f"{len(missing_counties)} block county codes are missing from ref_county, for example {missing_counties[0]}")
    counties = _attach_population(counties, "county_geoid", blocks)
    places = _attach_population(places, "place_geoid", blocks)
    states = _attach_population(states, "state", blocks)
    total = population_of_states(blocks)
    included = {code for code, _usps in CENSUS_AREAS if code not in POPULATION_EXCLUDED}
    if total != EXPECTED_POP20:
        raise ValueError(f"Block population for the 50 states and DC is {total}, expected {EXPECTED_POP20}")
    if set(blocks.loc[blocks["state"].isin(included), "state"]) != included:
        raise ValueError("Block population is missing a state or the District of Columbia")
    for frame, key in ((states, "state"), (counties, "state")):
        rolled = int(frame.loc[frame[key].isin(included), "pop20"].sum())
        if rolled != total:
            raise ValueError(f"Population rolled to {key} is {rolled}, expected {total}")
    units = read_government_units(home / index["government_units"][0].paths[0], set(index["government_units"][1].attribute_fields.values()))
    output = home / "silver" / quarter
    output.mkdir(parents=True, exist_ok=True)
    block_columns = ["block_geoid", "state", "county_geoid", "tract_geoid", "place_geoid", "cousub_geoid", "pop20", "housing20", "aland20", "lat", "lon"]
    _write(blocks[block_columns], output / "ref_block.parquet")
    _write(counties[["county_geoid", "state", "countyfp", "name", "namelsad", "pop20"]], output / "ref_county.parquet")
    _write(places[["place_geoid", "state", "placefp", "name", "namelsad", "pop20"]], output / "ref_place.parquet")
    _write(states[["state", "geoid", "usps", "name", "pop20"]], output / "ref_state.parquet")
    _write(alias, output / "ref_county_alias.parquet")
    _write(units, output / "ref_government_unit.parquet")
    return {
        "ref_block_rows": len(blocks),
        "ref_county_rows": len(counties),
        "ref_place_rows": len(places),
        "ref_state_rows": len(states),
        "ref_county_alias_rows": len(alias),
        "ref_government_unit_rows": len(units),
        "pop20_states_dc": total,
        "block_place_codes_outside_2025": outside_places,
    }


def read_crosswalk(path: Path, columns: dict[str, str]) -> pd.DataFrame:
    """Read the pipe-delimited Connecticut crosswalk, including its multiline header."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream, delimiter="|"))
    if len(rows) < 2:
        raise ValueError(f"Crosswalk has no data rows: {path.name}")
    header = [cell.split("(")[0].strip() for cell in rows[0]]
    if len(header) != len(set(header)) or any(not name for name in header):
        raise ValueError(f"Invalid crosswalk header: {path.name}")
    missing = [name for name in columns.values() if name not in header]
    if missing:
        raise ValueError(f"Crosswalk missing columns: {', '.join(missing)}")
    positions = {name: header.index(name) for name in columns.values()}
    records = []
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            trailer = " ".join(cell.strip() for cell in row)
            if records and (trailer == "" or trailer == "GLOSSARY" or "=" in trailer):
                break
            raise ValueError(f"Crosswalk ragged row {line_number} in {path.name}")
        records.append({output: row[positions[source]].strip() for output, source in columns.items()})
    frame = pd.DataFrame.from_records(records)
    for column, width in (("state", 2), ("old_countyfp", 3), ("new_countyfp", 3), ("cousubfp", 5)):
        frame[column] = _require_text(frame[column], column, width)
    old_id = frame["state"] + frame["old_countyfp"] + frame["cousubfp"]
    new_id = frame["state"] + frame["new_countyfp"] + frame["cousubfp"]
    if "old_cousub_geoid" in frame and not frame["old_cousub_geoid"].eq(old_id).all():
        raise ValueError("Crosswalk old county subdivision id does not match its codes")
    if "new_cousub_geoid" in frame and not frame["new_cousub_geoid"].eq(new_id).all():
        raise ValueError("Crosswalk new county subdivision id does not match its codes")
    return frame


def require_old_county_count(crosswalk: pd.DataFrame, expected: int) -> None:
    found = int(crosswalk["old_countyfp"].nunique())
    if found != expected:
        raise ValueError(f"Crosswalk has {found} old county codes, expected {expected}")


def apply_county_crosswalk(blocks: pd.DataFrame, crosswalk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign planning-region counties when block county codes are the crosswalk's old codes."""
    blocks = blocks.copy()
    states = set(crosswalk["state"])
    if len(states) != 1:
        raise ValueError("County crosswalk covers more than one state")
    state = next(iter(states))
    keys = ["state", "old_countyfp", "cousubfp"]
    key_count = crosswalk.groupby(keys)["new_countyfp"].nunique()
    ambiguous_keys = {tuple(key) for key, count in key_count.items() if int(count) > 1}
    row_keys = crosswalk[keys].apply(tuple, axis=1)
    crosswalk = crosswalk.loc[~row_keys.isin(ambiguous_keys)].drop_duplicates(keys)
    alias = crosswalk[["state", "old_countyfp", "old_county_name", "new_countyfp", "new_county_name"]].copy()
    alias["old_county_geoid"] = alias["state"] + alias["old_countyfp"]
    alias["county_geoid"] = alias["state"] + alias["new_countyfp"]
    alias = alias.rename(columns={"new_county_name": "county_name"})
    alias = alias[["state", "old_county_geoid", "old_county_name", "county_geoid", "county_name"]].drop_duplicates()
    if alias.duplicated(["old_county_geoid", "county_geoid"]).any():
        raise ValueError("County alias has conflicting names for one old and new county")
    blocks["county_geoid"] = blocks["state"] + blocks["countyfp"]
    selected = blocks["state"].eq(state)
    if not bool(selected.any()):
        raise ValueError(f"No blocks for crosswalk state {state}")
    observed = set(blocks.loc[selected, "countyfp"])
    old_codes = set(crosswalk["old_countyfp"])
    new_codes = set(crosswalk["new_countyfp"])
    if observed == old_codes:
        lookup = crosswalk.rename(columns={"old_countyfp": "countyfp"})
        current = blocks.loc[selected, ["block_geoid", "state", "countyfp", "cousubfp"]]
        merged = current.merge(lookup[["state", "countyfp", "cousubfp", "new_countyfp", "new_cousub_geoid"]], how="left", indicator=True)
        if len(merged) != len(current) or not merged["block_geoid"].eq(current["block_geoid"].to_numpy()).all():
            raise ValueError("Crosswalk match changed the block row count")
        merged.index = current.index
        unmatched = merged["_merge"].ne("both")
        ambiguous_rows = pd.Series(False, index=merged.index)
        if bool(unmatched.any()):
            row_keys = list(zip(merged["state"], merged["countyfp"], merged["cousubfp"], strict=True))
            ambiguous_rows = pd.Series([key in ambiguous_keys for key in row_keys], index=merged.index) & unmatched
            missing = unmatched & ~ambiguous_rows
            if bool(missing.any()):
                example = merged.loc[missing, "block_geoid"].iloc[0]
                raise ValueError(f"{int(missing.sum())} blocks in state {state} have no crosswalk county, for example {example}")
        blocks["crosswalk_ambiguous"] = False
        blocks.loc[selected, "crosswalk_ambiguous"] = ambiguous_rows.to_numpy()
        matched = ~unmatched
        expected_new = merged.loc[matched, "state"] + merged.loc[matched, "new_countyfp"] + merged.loc[matched, "cousubfp"]
        if not merged.loc[matched, "new_cousub_geoid"].eq(expected_new).all():
            raise ValueError("Crosswalk new county subdivision id does not match its codes")
        matched_index = merged.index[matched.to_numpy()]
        blocks.loc[matched_index, "county_geoid"] = (merged.loc[matched, "state"] + merged.loc[matched, "new_countyfp"]).to_numpy()
        blocks.loc[matched_index, "cousub_geoid"] = merged.loc[matched, "new_cousub_geoid"].to_numpy()
    elif not (observed <= new_codes and not (observed & old_codes)):
        raise ValueError(f"Unexpected county codes for state {state}: {', '.join(sorted(observed))}")
    return blocks, alias.sort_values(["old_county_geoid", "county_geoid"], kind="stable").reset_index(drop=True)


def resolve_ambiguous_counties(blocks: pd.DataFrame, county_path: Path) -> pd.DataFrame:
    """Place blocks whose subdivision maps to more than one new county by internal point."""
    if "crosswalk_ambiguous" not in blocks.columns or not bool(blocks["crosswalk_ambiguous"].any()):
        return blocks.drop(columns=["crosswalk_ambiguous"], errors="ignore")
    pending = blocks["crosswalk_ambiguous"].fillna(False).astype(bool)
    counties = gpd.read_file(county_path)
    counties = counties.loc[counties["STATEFP"].isin(set(blocks.loc[pending, "state"])), ["GEOID", "geometry"]]
    points = gpd.GeoDataFrame(
        blocks.loc[pending, ["block_geoid", "state", "cousubfp"]],
        geometry=gpd.points_from_xy(blocks.loc[pending, "lon"], blocks.loc[pending, "lat"]),
        crs=counties.crs,
    )
    joined = gpd.sjoin(points, counties, predicate="within", how="left")
    if joined["GEOID"].isna().any() or joined["block_geoid"].duplicated().any():
        example = joined.loc[joined["GEOID"].isna() | joined["block_geoid"].duplicated(keep=False), "block_geoid"].iloc[0]
        raise ValueError(f"Ambiguous crosswalk block is not inside exactly one county, for example {example}")
    if not joined["GEOID"].str.slice(0, 2).eq(joined["state"]).all():
        raise ValueError("Ambiguous crosswalk block fell in a different state")
    located = joined.drop_duplicates("block_geoid").set_index("block_geoid")
    blocks.loc[pending, "county_geoid"] = blocks.loc[pending, "block_geoid"].map(located["GEOID"]).to_numpy()
    blocks.loc[pending, "cousub_geoid"] = blocks.loc[pending, "state"] + blocks.loc[pending, "county_geoid"].str.slice(2, 5) + blocks.loc[pending, "cousubfp"]
    if blocks.loc[pending, "county_geoid"].isna().any():
        raise ValueError("Ambiguous crosswalk block was not assigned a county")
    return blocks.drop(columns=["crosswalk_ambiguous"])


def population_of_states(blocks: pd.DataFrame) -> int:
    """Sum 2020 population for the 50 states and the District of Columbia."""
    included = ~blocks["state"].isin(POPULATION_EXCLUDED)
    return int(blocks.loc[included, "pop20"].sum())


def read_government_units(path: Path, required: set[str]) -> pd.DataFrame:
    """Read every sheet of the Government Units workbook inside its zip."""
    with zipfile.ZipFile(path) as bundle:
        workbooks = [name for name in bundle.namelist() if name.lower().endswith(".xlsx")]
        if len(workbooks) != 1:
            raise ValueError(f"Expected one workbook in {path.name}")
        payload = bundle.read(workbooks[0])
    frame = read_workbook(payload, required)
    if frame.empty:
        raise ValueError(f"Government units workbook has no rows: {path.name}")
    return frame


def read_workbook(payload: bytes, required: set[str]) -> pd.DataFrame:
    """Read every worksheet, keeping each source column and the sheet name."""
    with zipfile.ZipFile(io.BytesIO(payload)) as book:
        shared = _shared_strings(book)
        sheets = _worksheets(book)
        frames = []
        for name, sheet_path in sheets:
            frame = _read_sheet(book.read(sheet_path), name, shared)
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError(f"Government units sheet {name} missing columns: {', '.join(missing)}")
            if "listing" in frame.columns:
                raise ValueError(f"Government units sheet {name} already has a listing column")
            frame.insert(0, "listing", name)
            frames.append(frame)
    if not frames:
        raise ValueError("Government units workbook has no worksheets")
    return pd.concat(frames, ignore_index=True)


def _home_sources(registry_dir: Path) -> list[Source]:
    """Return home-storage sources whose layers are all reference layers.

    Other home-storage sources, such as a downloaded tabular release, are not
    Census files and are not expanded by the reference builder.
    """
    sources = []
    for source in load_registry(registry_dir, require_reviewed=False):
        if source.storage != "home" or not source.layers:
            continue
        if any(layer.sector != "reference" for layer in source.layers):
            continue
        sources.append(source)
    if not sources:
        raise ValueError("No home-storage reference sources are declared")
    return sources


def _layer_index(registry_dir: Path) -> dict[str, tuple[Source, Layer]]:
    index: dict[str, tuple[Source, Layer]] = {}
    for source in _home_sources(registry_dir):
        for layer in source.layers:
            if layer.layer in index:
                raise ValueError(f"Duplicate reference layer {layer.layer}")
            index[layer.layer] = (source, layer)
    unknown = sorted(set(index) - HANDLED_LAYERS)
    missing = sorted(HANDLED_LAYERS - set(index))
    if unknown or missing:
        raise ValueError(f"Reference layers do not match the builder. Missing: {', '.join(missing)}. Unknown: {', '.join(unknown)}")
    return index


def _paths_for(home: Path, source: Source, jobs: list[tuple[str, Path]]) -> list[Path]:
    root = (home / source.paths[0]).resolve()
    paths = [path for _url, path in jobs if path.resolve() == root or path.resolve().is_relative_to(root)]
    if not paths:
        raise ValueError(f"No Census files declared for {source.paths[0]}")
    return paths


def _read_blocks(home: Path, index: dict[str, tuple[Source, Layer]], jobs: list[tuple[str, Path]]) -> pd.DataFrame:
    source, layer = index["tabblock20"]
    required = {"block_geoid", "state", "countyfp", "tractce", "pop20", "housing20", "aland20", "lat", "lon"}
    if set(layer.attribute_fields) != required:
        raise ValueError("tabblock20 must declare block, state, county, tract, population, housing, land, and point columns")
    baf_source = index["INCPLACE_CDP"][0]
    usps = dict(CENSUS_AREAS)
    frames = []
    files = sorted(_paths_for(home, source, jobs))
    for number, path in enumerate(files, start=1):
        print(f"reading {path.name} ({number}/{len(files)})", flush=True)
        frame = _read_feature_table(path, layer)
        if frame.empty:
            raise ValueError(f"{path.name} has no blocks")
        statefp = str(frame["state"].iloc[0]).strip()
        if path.name != f"tl_2025_{statefp}_tabblock20.zip":
            raise ValueError(f"{path.name} contains state {statefp}")
        if statefp not in usps:
            raise ValueError(f"Unexpected state in {path.name}")
        frame["pop20"] = _require_int(frame["pop20"], f"{path.name} POP20")
        frame["housing20"] = _require_int(frame["housing20"], f"{path.name} HOUSING20")
        frame["aland20"] = _require_int(frame["aland20"], f"{path.name} ALAND20")
        if (frame[["pop20", "housing20", "aland20"]] < 0).any().any():
            raise ValueError(f"Negative population, housing, or land area in {path.name}")
        frame["state"] = _require_text(frame["state"], f"{path.name} state", 2)
        frame["countyfp"] = _require_text(frame["countyfp"], f"{path.name} county", 3)
        frame["tractce"] = _require_text(frame["tractce"], f"{path.name} tract", 6)
        frame["block_geoid"] = _require_text(frame["block_geoid"], f"{path.name} block", 15)
        if frame["state"].nunique() != 1 or frame["block_geoid"].duplicated().any():
            raise ValueError(f"{path.name} does not contain one state of unique blocks")
        tract_geoid = frame["state"] + frame["countyfp"] + frame["tractce"]
        if not frame["block_geoid"].str.slice(0, 11).eq(tract_geoid).all():
            raise ValueError(f"GEOID20 does not match state, county, and tract in {path.name}")
        frame["tract_geoid"] = tract_geoid
        frame["lat"] = _require_float(frame["lat"], f"{path.name} latitude")
        frame["lon"] = _require_float(frame["lon"], f"{path.name} longitude")
        baf_path = home / baf_source.paths[0] / f"BlockAssign_ST{statefp}_{usps[statefp]}.zip"
        if statefp in BAF_EXCLUDED:
            if baf_path.exists():
                raise ValueError(f"Unexpected block assignment file {baf_path.name}")
            frame["placefp"] = pd.Series(pd.NA, index=frame.index, dtype="string")
            frame["cousubfp"] = pd.Series(pd.NA, index=frame.index, dtype="string")
        else:
            if not baf_path.is_file():
                raise ValueError(f"Missing block assignment file for state {statefp}")
            frame = _attach_baf(frame, baf_path, baf_source)
        frames.append(frame)
    blocks = pd.concat(frames, ignore_index=True)
    if blocks["block_geoid"].duplicated().any():
        raise ValueError("Duplicate block GEOID20")
    blank_place = blocks["placefp"].isna()
    blocks["place_geoid"] = (blocks["state"] + blocks["placefp"]).astype("string")
    blocks.loc[blank_place, "place_geoid"] = pd.NA
    blank_cousub = blocks["cousubfp"].isna()
    blocks["cousub_geoid"] = (blocks["state"] + blocks["countyfp"] + blocks["cousubfp"]).astype("string")
    blocks.loc[blank_cousub, "cousub_geoid"] = pd.NA
    return blocks


def _read_feature_table(path: Path, layer: Layer) -> pd.DataFrame:
    columns = list(layer.attribute_fields.values())
    try:
        frame = pyogrio.read_dataframe(path, columns=columns, read_geometry=False)
    except (OSError, ValueError, RuntimeError, DataSourceError) as exc:
        raise ValueError(f"Missing columns or unreadable file {path.name}: {exc}") from exc
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} missing columns: {', '.join(missing)}")
    return frame.rename(columns={source: output for output, source in layer.attribute_fields.items()})


def _attach_baf(blocks: pd.DataFrame, path: Path, source: Source) -> pd.DataFrame:
    place_layers = [layer for layer in source.layers if "placefp" in layer.attribute_fields]
    cousub_layers = [layer for layer in source.layers if "cousubfp" in layer.attribute_fields]
    tribal_layers = [layer for layer in source.layers if "aiannhce" in layer.attribute_fields]
    if len(place_layers) != 1:
        raise ValueError("Block assignment source needs one incorporated-place layer")
    place_member = _zip_member(path, place_layers[0].layer)
    if place_member is None:
        raise ValueError(f"{path.name} has no {place_layers[0].layer} file")
    place = _read_delimited(path, place_member, place_layers[0].attribute_fields)
    if place["block_geoid"].duplicated().any():
        raise ValueError(f"Duplicate block in {path.name} {place_member}")
    missing_blocks = set(place["block_geoid"]) - set(blocks["block_geoid"])
    if missing_blocks:
        raise ValueError(f"{path.name} assigns {len(missing_blocks)} blocks that are not in the block file, for example {min(missing_blocks)}")
    place["placefp"] = _optional_code(place["placefp"], f"{path.name} place", 5)
    blocks = blocks.merge(place[["block_geoid", "placefp"]], on="block_geoid", how="left")
    cousub_frame = None
    for layer in cousub_layers:
        member = _zip_member(path, layer.layer)
        if member is None:
            continue
        if cousub_frame is not None:
            raise ValueError(f"{path.name} has more than one county subdivision file")
        cousub_frame = _read_delimited(path, member, layer.attribute_fields)
        if cousub_frame["block_geoid"].duplicated().any():
            raise ValueError(f"Duplicate block in {path.name} {member}")
        cousub_frame["cousubfp"] = _optional_code(cousub_frame["cousubfp"], f"{path.name} county subdivision", 5)
        cousub_frame["countyfp"] = _require_text(cousub_frame["countyfp"], f"{path.name} county subdivision county", 3)
    if cousub_frame is None:
        blocks["cousubfp"] = pd.Series(pd.NA, index=blocks.index, dtype="string")
    else:
        blocks = blocks.merge(cousub_frame[["block_geoid", "countyfp", "cousubfp"]].rename(columns={"countyfp": "baf_countyfp"}), on="block_geoid", how="left")
        comparable = blocks["baf_countyfp"].notna()
        if bool((comparable & blocks["baf_countyfp"].ne(blocks["countyfp"])).any()):
            raise ValueError(f"County subdivision county does not match the block in {path.name}")
        blocks = blocks.drop(columns=["baf_countyfp"])
    for layer in tribal_layers:
        member = _zip_member(path, layer.layer)
        if member is None:
            continue
        tribal = _read_delimited(path, member, layer.attribute_fields)
        _optional_code(tribal["aiannhce"], f"{path.name} tribal area", 4)
    return blocks


def _zip_member(path: Path, suffix: str) -> str | None:
    with zipfile.ZipFile(path) as bundle:
        matches = [name for name in bundle.namelist() if Path(name).name.endswith(f"_{suffix}.txt")]
    if len(matches) > 1:
        raise ValueError(f"{path.name} has multiple {suffix} files")
    return matches[0] if matches else None


def _read_delimited(path: Path, member: str, fields: dict[str, str]) -> pd.DataFrame:
    with zipfile.ZipFile(path) as bundle, bundle.open(member) as raw:
        frame = pd.read_csv(raw, sep="|", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if frame.columns.duplicated().any() or any(not str(column) for column in frame.columns):
        raise ValueError(f"Invalid header in {path.name} {member}")
    missing = [name for name in fields.values() if name not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} {member} missing columns: {', '.join(missing)}")
    renamed = frame.rename(columns={source: output for output, source in fields.items()})
    renamed["block_geoid"] = _require_text(renamed["block_geoid"], f"{path.name} block", 15)
    return renamed


def _read_named_areas(item: tuple[Source, Layer], paths: list[Path]) -> pd.DataFrame:
    _source, layer = item
    frames = [_read_feature_table(path, layer) for path in paths]
    if not frames:
        raise ValueError(f"No files for {layer.layer}")
    frame = pd.concat(frames, ignore_index=True)
    for column, width in (("state", 2), ("countyfp", 3), ("placefp", 5), ("usps", 2)):
        if column in frame:
            frame[column] = _require_text(frame[column], f"{layer.layer} {column}", width)
    for column in ("name", "namelsad", "county_geoid", "place_geoid", "geoid"):
        if column in frame:
            width = {"county_geoid": 5, "place_geoid": 7, "geoid": 2}.get(column)
            frame[column] = _require_text(frame[column], f"{layer.layer} {column}", width)
    identity = "county_geoid" if "county_geoid" in frame else "place_geoid" if "place_geoid" in frame else "geoid"
    if frame[identity].duplicated().any():
        raise ValueError(f"Duplicate {identity} in {layer.layer}")
    return frame


def _check_area_identity(frame: pd.DataFrame, geoid: str, parts: tuple[str, ...], label: str) -> None:
    combined = frame[parts[0]]
    for part in parts[1:]:
        combined = combined + frame[part]
    if not frame[geoid].eq(combined).all():
        raise ValueError(f"{label} does not match its source codes")


def _finish_blocks(blocks: pd.DataFrame, places: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep every block. 2020 place codes absent from the 2025 place file stay on the block."""
    assigned = blocks.loc[blocks["place_geoid"].notna(), "place_geoid"]
    missing = set(assigned) - set(places["place_geoid"])
    if blocks["county_geoid"].isna().any() or blocks["tract_geoid"].isna().any():
        raise ValueError("A block is missing its county or tract")
    return blocks.sort_values("block_geoid", kind="stable").reset_index(drop=True), len(missing)


def _attach_population(frame: pd.DataFrame, key: str, blocks: pd.DataFrame) -> pd.DataFrame:
    totals = blocks.dropna(subset=[key]).groupby(key)["pop20"].sum()
    frame = frame.copy()
    frame["pop20"] = frame[key].map(totals).fillna(0).astype("int64")
    return frame


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_parquet(path, index=False)


def _require_text(series: pd.Series, label: str, width: int | None) -> pd.Series:
    text = series.astype("string").str.strip()
    if text.isna().any() or text.eq("").any():
        raise ValueError(f"Blank values in {label}")
    if width is not None and not bool(text.str.len().eq(width).all()):
        example = text.loc[text.str.len().ne(width)].iloc[0]
        raise ValueError(f"{label} is not {width} characters: {example}")
    if width is not None and "usps" not in label and not bool(text.str.fullmatch(r"\d+").all()):
        example = text.loc[~text.str.fullmatch(r"\d+")].iloc[0]
        raise ValueError(f"{label} is not numeric: {example}")
    return text


def _optional_code(series: pd.Series, label: str, width: int) -> pd.Series:
    text = series.astype("string").str.strip()
    blank = text.isna() | text.eq("") | text.str.lower().eq("nan")
    present = text.loc[~blank]
    if not present.empty and (not bool(present.str.len().eq(width).all()) or not bool(present.str.fullmatch(r"\d+").all())):
        raise ValueError(f"{label} is not a {width}-digit code: {present.iloc[0]}")
    return text.mask(blank)


def _require_int(series: pd.Series, label: str) -> pd.Series:
    if series.isna().any():
        raise ValueError(f"Blank values in {label}")
    if not pd.api.types.is_integer_dtype(series):
        values = pd.to_numeric(series, errors="coerce")
        if values.isna().any() or not values.eq(values.round()).all():
            raise ValueError(f"{label} is not an integer column")
        return values.astype("int64")
    return series.astype("int64")


def _require_float(series: pd.Series, label: str) -> pd.Series:
    text = series.astype("string").str.strip()
    if text.isna().any() or text.eq("").any():
        raise ValueError(f"Blank values in {label}")
    values = pd.to_numeric(text, errors="coerce")
    if values.isna().any():
        raise ValueError(f"Non-numeric values in {label}")
    return values.astype("float64")


def _download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            total = _content_length(url)
            if total and destination.is_file() and destination.stat().st_size == total:
                if destination.suffix.lower() == ".zip":
                    _require_zip(destination)
                return
            _stream(url, partial, total)
            size = partial.stat().st_size
            if total and size != total:
                raise ValueError(f"Incomplete download for {destination.name}: {size} of {total}")
            if size <= 0:
                raise ValueError(f"Empty download for {destination.name}")
            if destination.suffix.lower() == ".zip":
                _require_zip(partial)
            partial.replace(destination)
            return
        except (OSError, requests.RequestException, ValueError) as exc:
            last_error = exc
    raise ValueError(f"Download failed for {destination.name}: {last_error}")


def _content_length(url: str) -> int | None:
    response = requests.head(url, timeout=60, allow_redirects=True, headers=_USER_AGENT)
    response.raise_for_status()
    length = response.headers.get("Content-Length")
    if length is None or not str(length).isdigit() or int(length) <= 0:
        return None
    return int(length)


def _stream(url: str, partial: Path, total: int | None) -> None:
    existing = partial.stat().st_size if partial.is_file() else 0
    headers = dict(_USER_AGENT)
    if existing and (total is None or existing >= total):
        partial.unlink()
        existing = 0
    if total and existing:
        headers["Range"] = f"bytes={existing}-"
    with requests.get(url, headers=headers, stream=True, timeout=(30, 300), allow_redirects=True) as response:
        response.raise_for_status()
        _write_response(response, partial, existing)


def _write_response(response: Response, partial: Path, existing: int) -> None:
    if response.status_code == 206 and existing:
        mode = "ab"
    elif response.status_code == 200:
        mode = "wb"
    else:
        raise ValueError(f"Unexpected download status {response.status_code}")
    with partial.open(mode) as output:
        for chunk in response.iter_content(1024 * 1024):
            if chunk:
                output.write(chunk)


def _require_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as bundle:
        if not bundle.namelist():
            raise ValueError(f"Empty zip: {path.name}")


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join((node.text or "") for node in item.findall(".//m:t", _SPREADSHEET_NS)) for item in root.findall("m:si", _SPREADSHEET_NS)]


def _worksheets(book: zipfile.ZipFile) -> list[tuple[str, str]]:
    relationships = {item.attrib["Id"]: item.attrib["Target"] for item in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    sheets = []
    relation_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.findall("m:sheets/m:sheet", _SPREADSHEET_NS):
        target = relationships[sheet.attrib[relation_key]]
        path = target if target.startswith("xl/") else f"xl/{target}"
        sheets.append((sheet.attrib["name"], path.lstrip("/")))
    return sheets


def _read_sheet(payload: bytes, name: str, shared: list[str]) -> pd.DataFrame:
    root = ET.fromstring(payload)
    rows = root.findall("m:sheetData/m:row", _SPREADSHEET_NS)
    if not rows:
        raise ValueError(f"Government units sheet {name} has no header")
    header_cells = _cell_map(rows[0], shared)
    if not header_cells or sorted(header_cells) != list(range(len(header_cells))):
        raise ValueError(f"Government units sheet {name} has a gap in its header")
    header = [header_cells[index] for index in range(len(header_cells))]
    if any(cell is None or not str(cell).strip() for cell in header) or len(header) != len(set(header)):
        raise ValueError(f"Government units sheet {name} has a blank or duplicate header")
    records = []
    width = len(header)
    for row in rows[1:]:
        cells = _cell_map(row, shared)
        if any(index >= width for index in cells):
            raise ValueError(f"Government units sheet {name} has a value outside its header")
        records.append({header[index]: cells.get(index) for index in range(width)})
    return pd.DataFrame.from_records(records, columns=header)


def _cell_map(row: ET.Element, shared: list[str]) -> dict[int, str | None]:
    values: dict[int, str | None] = {}
    for cell in row.findall("m:c", _SPREADSHEET_NS):
        reference = cell.attrib.get("r")
        if not reference:
            raise ValueError("Worksheet cell has no reference")
        values[_column_index(reference)] = _cell_text(cell, shared)
    return values


def _cell_text(cell: ET.Element, shared: list[str]) -> str | None:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join((node.text or "") for node in cell.findall(".//m:t", _SPREADSHEET_NS))
    value = cell.find("m:v", _SPREADSHEET_NS)
    if value is None or value.text is None:
        return None
    if kind == "s":
        return shared[int(value.text)]
    return value.text


def _column_index(reference: str) -> int:
    letters = []
    for character in reference:
        if not character.isalpha():
            break
        letters.append(character.upper())
    if not letters:
        raise ValueError(f"Invalid cell reference {reference}")
    index = 0
    for character in letters:
        index = index * 26 + ord(character) - 64
    return index - 1
