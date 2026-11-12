# Runbook

Generated data lives under `UTILITYDATA_HOME`. Set it to an absolute path before
any command below. The local default is the ignored `data` directory; see
[rebuild setup](rebuild-setup.md). Commands are run from the repository root
with `uv run utilitydata ...`.

These steps are the commands the code implements. A refresh does not rebuild
Silver, Core, Gold, or a release. Cutting a release does not download sources.

## Quarterly refresh

`uv run utilitydata refresh --snapshot <new-quarter> --previous <old-quarter>`

The new quarter must be a different `YYYY-Q#` than the previous one. The
previous snapshot must already exist at `snapshots/<old-quarter>/manifest.parquet`
under the data root.

The command reads `registry/sources`. It keeps a source only when all of these
are true:

- the source id is already in the previous manifest
- the registry entry is reviewed and has a driver
- every manifest status for that source is `collected`, `partial_geometry`, or
  `nonspatial`

Drafts, sources with no driver, and sources that are not in the previous
manifest are left out. A brand-new source is not fetched by refresh. It enters
a later snapshot only through `snapshot freeze` of a new quarter.

`--dry-run` compares the frozen bytes and does not contact publishers. It does
not publish a snapshot. It still stores a blob for every selected source,
because skipped, carried-forward, and dry-run rows all go through the blob
store. `--limit N` keeps the N smallest eligible sources by frozen byte count
and does not publish. Without `--dry-run`, a limited run still contacts
publishers for sources that changed.

A publish requires neither flag and at least one selected source. It writes
`snapshots/<new-quarter>/manifest.parquet`, `snapshots/<new-quarter>/layers.parquet`,
and a copy of `registry/` (`sources`, `unused.yaml`, `vocab`, `overrides`, `truth`)
under `snapshots/<new-quarter>/registry/`. The manifest columns are
`source_id`, `relative_path`, `sha256`, `bytes`, `retrieved_utc`, `blob`, `status`,
`action`, `feature_count`, `has_geometry`, and `area`. Publish refuses when that
directory already exists. It stores bytes in `blobs/` rather than copying `files/`.
The previous snapshot stays in place. Subsequent refreshes and sector helpers can
resolve previous files from either `snapshots/<quarter>/files/` or `blobs/`.

Unchanged bytes are recorded as skipped. A download error, a missing mapped
field,shapes outside the expected state outline (loaded from `ref_state.parquet`),
or a feature-count or area move larger than the drift settings in
`src/utilitydata/core/config.py` (both 0.10) carries the last good bytes forward
and marks the source `carried_forward`.

Custom sources are hashed locally and are not downloaded. Every selected
source, including a dry run, is stored by SHA-256 under `blobs/` in the data
root. An existing blob is not overwritten.

The run writes `refresh/<new-quarter>/triage_report.md` and
`refresh/<new-quarter>/manifest.parquet`. On a non-dry-run CLI invocation, a
`collect_round*.py` script is deleted when every path it names was reproduced.
Refresh does not start the sector builds.

## Working the review queue

Drinking water is the only queue the next build reads.

`uv run utilitydata core water` writes `state/review_queue.csv` under the data
root. The file lists up to three candidates per unresolved assertion
(`assertion_id`, `source_id`, `rank`, `candidate_system_id`, `name_score`,
`iou`, `geom_state`, `name_norm`, `queued_system_id`, `reason`). Editing that
CSV does nothing. The build does not read it back.

A decision goes in `registry/overrides/match_overrides.csv`, with columns
`assertion_id`, `system_id`, `decided_by`, and `notes`. The core build creates
the file with those headers when it is missing and does not add rows. On the
next `uv run utilitydata core water`, a row in that file wins before a federal
id or a name match. The match method is `manual`. A blank `decided_by` is
stored as `override`. The assertion id must already exist, and the same
assertion cannot appear twice.

These files are outputs. No command reads them back on the next build:

- `state/electric_review_queue.csv`
- `state/wastewater_review_queue.csv`
- `state/wastewater_unlinked_zone_sample.csv`
- `state/gas_review_queue.csv`
- `state/gas_eia_review_queue.csv`
- `core/<quarter>/facility_review_queue.parquet`

There is no command that marks one of those rows decided. Name, overlap, and
distance thresholds stay at the starting values in `core/config.py`.

## Adding a source

Add a hand-written entry under `registry/sources`. One YAML file can hold
several sources, each with `source_id`, `publisher`, `driver` (`arcgis`, `http`,
`discover`, or `custom`), `url`, `cadence`, `licence`, `paths`, and `layers`.
Leave `reviewed` false until a person has checked the field mapping. A reviewed
in-scope source also needs a sector and grain on every layer, and a service-area
layer needs a role, an authority, a name field, and
`on_missing_name: preserve_and_review`.

`redistribution` defaults to `internal_only`. A licence of `unknown`,
`internal_or_no_redistribution`, or `attribution_no_commercial_sale` cannot be
marked `shareable`. Unknown licences stay in the internal edition.

Every file under the raw collection must be listed on a source `paths` entry or
in `registry/unused.yaml`. Then run:

```text
uv run utilitydata registry validate --allow-unreviewed
uv run utilitydata registry coverage
```

`--allow-unreviewed` checks drafts. It does not make a draft eligible for a
build. Silver, Core, and Gold read reviewed sources only.

`uv run utilitydata snapshot freeze <quarter>` copies the collection into
`snapshots/<quarter>/` and fails when any raw file has no disposition or when
that quarter already exists. Freeze does not download. After that snapshot
exists, a later refresh can re-fetch the source only if the entry is reviewed
and the snapshot status is buildable.

## Cutting a release

The current commands write release `2026Q4.1` from quarter `2026-Q4`. Pass
`--quarter` and `--release-id` for another pair. The quarter's snapshot and
reference tables must already be in the data root.

1. `uv run utilitydata silver water`
2. `uv run utilitydata core water`
3. `uv run utilitydata release water`

`release water` rebuilds drinking-water Gold and writes
`releases/<release-id>/`. Tables are split into `internal/` and `shareable/` by
licence. Unknown and restricted licences go to `internal/`. The folder also
receives `release_manifest.json`, `data_dictionary.md`, `accuracy_report.md`,
`change_report.md`, and `open_release.sql`. The change report records the cases
the draft sources prevent. It does not compare two release folders. The truth
CSVs are read and are not filled by the build.

4. `uv run utilitydata electric`
5. `uv run utilitydata wastewater`
6. `uv run utilitydata gas`

Electric appends its tables, display geometries, scorecard rows, and report
sections to the release the water command created. Wastewater and gas copy
service areas, append active best display geometries, update the multi-sector
scorecard, and add `wastewater_service_area` / `gas_service_area` views to
`open_release.sql` when the release directory already exists. If it does not,
those two commands still write their Core tables and skip the release copy.

7. `uv run utilitydata cross`

Cross writes facilities, organization relationships, and
`core/<quarter>/facility_review_queue.parquet`. It does not copy files into the
release folder. Graph export reads the facility and relationship tables, so
this step comes first.

8. `uv run utilitydata graph export`
9. `uv run utilitydata graph load`

Export writes `releases/<release-id>/graph/` and checks that the Travis County
water systems in the edge table match Gold. Load starts Fuseki on `127.0.0.1`
when Docker is available and checks the same Travis County set through SPARQL.
The query service is the only published service.
