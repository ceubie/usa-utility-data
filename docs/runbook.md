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
field, shapes outside the expected state outline (loaded from `ref_state.parquet`),
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

A release id names one folder, `releases/<release-id>/`, under the data root.
The quarter's snapshot and reference tables must already be there.

### One command

```text
uv run utilitydata pipeline run --release-id 2026Q4.2
```

`--release-id` is required. `--quarter` defaults to `DEFAULT_QUARTER` in
`src/utilitydata/core/config.py`. The stages run in this order: `validate`,
`promote`, `silver_water`, `core_water`, `release_water`, `electric`,
`wastewater`, `gas`, `cross`, `assemble`, `graph_export`, `contracts`, and
`graph_load`.

The run keeps its state in `releases/<release-id>/pipeline_status.json`, and
each finished stage writes its summary to `releases/<release-id>/pipeline/<stage>.json`.
Machine paths in a summary are written as `$UTILITYDATA_HOME` or `.`, the
repository root. The status file and the `pipeline/` folder are run records
and are not listed in `release_manifest.json`.

- A stage that raises is marked `failed` with its reason, and the run stops.
- A stage that cannot run here is marked `skipped` with its reason. Today that
  is only `graph_load` when Docker is not available. A skipped stage is retried
  on the next run.
- When every stage is `done`, the release is sealed.

`uv run utilitydata pipeline run --release-id <id> --resume` continues an open
release at the first stage that is not done. `--from-stage <stage>` resets that
stage and every later one to pending and runs from there. A new id needs
neither flag. An existing folder needs one of them.

`validate` loads the registry and stops when a licence restriction is looser
than the one frozen with the snapshot. `contracts` runs the Core and Gold
contracts and writes `pipeline/contracts_core.json` and
`pipeline/contracts_gold.json`. A failed contract stops the run.

### Which releases can be written

- A release folder without `pipeline_status.json` is a finished release and is
  never written. `2026Q4.1` is one.
- A sealed release is never written.
- Only `release water` and `pipeline run` start a release folder.
- `electric` and `graph export` refuse a release that has not been started.
- `wastewater` and `gas` still build their Core tables when the release has not
  been started, and skip the release copy.

Every command that writes a release takes a required `--release-id` and checks
these rules before it starts work.

### Promotion backups

The Silver, electric, wastewater, and gas builds, and the `promote` stage,
promote a reviewed collection source that the freeze left as draft. Before a
promotion rewrites `snapshots/<quarter>/layers.parquet` and `manifest.parquet`,
it copies both to `snapshots/<quarter>/promotion_backups/<UTC time>/`, with
`promoted.json` listing the promoted source ids. A run that promotes nothing
writes no backup.

### Step by step

The same work can be run one command at a time, in this order. Each command
below takes `--release-id <id>`, except `silver water`, `core water`, and
`cross`, which write quarter tables only.

1. `uv run utilitydata silver water`
2. `uv run utilitydata core water`
3. `uv run utilitydata release water --release-id <id>`

`release water` starts the release and rebuilds drinking-water Gold. Tables are
split into `internal/` and `shareable/` by licence. Unknown and restricted
licences go to `internal/`. The folder also receives `release_manifest.json`,
`data_dictionary.md`, `accuracy_report.md`, `change_report.md`, and
`open_release.sql`. The change report records the cases the draft sources
prevent. It does not compare two release folders. The truth CSVs are read and
are not filled by the build.

4. `uv run utilitydata electric --release-id <id>`
5. `uv run utilitydata wastewater --release-id <id>`
6. `uv run utilitydata gas --release-id <id>`

Electric appends its tables, scorecard rows, and report sections to the release.
It saves rejected territory rows, with their reason, in
`silver/<quarter>/electric_boundary_rejects.parquet`; other electric rejects
are in `silver/<quarter>/electric_rejects.parquet`. Wastewater and gas copy
service areas, update the multi-sector scorecard, and add
`wastewater_service_area` / `gas_service_area` views to `open_release.sql`.
The `assemble` stage rebuilds the multi-sector `service_area_display.parquet`,
`entity_search.parquet`, `state_sector_scorecard.parquet`, and `sector_reports.md`
outputs for the release.

7. `uv run utilitydata cross`

Cross writes facilities, organization relationships, and
`core/<quarter>/facility_review_queue.parquet`. It does not copy files into the
release folder. Graph export reads the facility and relationship tables, so
this step comes first. The `assemble` stage has no separate command; run it
with `pipeline run --resume` or `--from-stage assemble`.

8. `uv run utilitydata graph export --release-id <id>`
9. `uv run utilitydata graph load --release-id <id>`

Export writes `releases/<release-id>/graph/` and checks that the Travis County
water systems in the edge table match Gold.

## Loading and serving the graph

`graph load` reads the release and does not write it, so its `--release-id`
defaults to `DEFAULT_RELEASE_ID`. When Docker is available it loads
`graph/graph.nt` into the Docker volume `utilitydata-tdb2-<release-id>`, starts
Fuseki on `127.0.0.1:3030`, and checks the Travis County set through SPARQL. A
load replaces only that release's volume. The store exposes query only; there
is no update or upload endpoint. `--engine qlever` does not load or start
QLever. It reports whether an index exists under `qlever/<release-id>/` in the
data root and leaves the server off. Fuseki stays the default until QLever
parity is shown.

`docker-compose.yml` serves one loaded release with the app:

```text
uv run utilitydata graph load --release-id <id>
npm --prefix app/frontend run build
UTILITYDATA_RELEASE=<id> docker compose up --build
```

Only the Caddy proxy publishes a port, `127.0.0.1:8080`. It serves the built
frontend and forwards `/api/*` to the backend. The backend and Fuseki share the
proxy's network namespace and publish nothing. The data root is mounted read-only.
The store volume must already exist; compose does not create it.

The app is for local use only. To require a login, also set:

- `CADDYFILE=Caddyfile.login`
- `REQUIRE_AUTH=1`
- `PROXY_SHARED_SECRET`, a long random value
- `PROXY_USER`
- `PROXY_PASSWORD_HASH`, from `docker run --rm caddy:2.10.2 caddy hash-password`

The proxy removes any `X-Forwarded-User` or `X-Proxy-Secret` header a client
sends. After basic authentication it sets both. With `REQUIRE_AUTH=1` the backend answers 401 unless
the shared secret matches and a user is named. Ask questions need the Azure
OpenAI variables; without them Ask reports a configuration error.
