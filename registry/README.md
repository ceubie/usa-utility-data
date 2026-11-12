# Source registry

Sources are declared in YAML files under `sources/`. Entries in
`unreviewed.yaml` are seed guesses, not approved mappings. Reviewed publisher
files contain exact source-field names checked against local metadata. Run
`utilitydata registry validate --allow-unreviewed` to inspect the draft;
without that flag the command fails until every source has been reviewed.

`licence: unknown` is an explicit unresolved status. Redistribution defaults
to `internal_only` and the schema permits `shareable` only for an approved
shareable licence. A release must never treat unknown or restricted terms as
shareable. An `irregular` cadence is an initial collection assumption where
not otherwise established, not a claim about publisher update frequency.

`boundary_representation` is separate from authority: it defaults to
`unknown`, and a `mixed` source may contain estimates or placeholders even
when published by a regulator. Later non-modeled coverage calculations must
not count unknown, mixed or modeled geometry as unmodeled unless the
representation is resolved for the individual feature. `unassigned_area`
preserves unassigned polygons without presenting them as serving providers.
Unmapped coded values fail registry validation rather than receiving a
guessed default. A source using seven-digit PWS IDs must explicitly declare
`pwsid_rule: state_prefix_7` before a state prefix can be added.

Cole approved including verified non-community on-site water areas in point
and coverage results as a distinct, labeled role. The criteria are recorded
in `vocab/onsite_service_policy.yaml`: the system must be active and uniquely
identified, and its service footprint must be verified. A modeled or
high-confidence estimated location alone is not footprint verification.
Unverified and conflicting assertions remain available for review; they are
not automatically counted as served.
The broader best-area guard is declared in `vocab/service_area_eligibility.yaml`:
the system must be active with resolved identity, and unresolved placeholders,
unknown status and apparent retail areas linked to a wholesaler flag must go
to review unless the mixed service is verified. Wholesale, planned, proxy,
watershed, unassigned and review-required roles do not compete as serving.
`role_matrix` declares exact combinations of named source fields and their
roles. A new or missing combination fails validation; nulls must have an
explicit case. Classification is a candidate, not verification of a footprint.
`on_invalid_pwsid: preserve_raw_without_federal_id` preserves the raw value
and boundary without claiming a federal ID; route it to matching or review,
and record any identifier-level reject required by the table contract. For
example, Oklahoma's `OKMCD0003` must not be treated as a PWSID, and three
Kansas boundaries have no PWSID. Apply this policy only after evaluating the
standard format, any explicitly authorized seven-digit state-prefix rule,
and the unique SDWIS-verified exception described below.

Cole approved accepting nine-character alphanumeric PWSIDs that do not meet
the standard two-character-plus-seven-digit pattern when they uniquely match
the frozen SDWIS registry after trimming. Preserve the raw value and flag
the exception; do not rewrite its interior or add a prefix. The policy is in
`vocab/pwsid_policy.yaml`. Unmatched nonstandard values and composite fields
containing multiple IDs remain review cases. The comparison that motivated
this decision is recorded in `pwsid_format_audit.json`.
For a reviewed service-area layer, `on_missing_name: preserve_and_review`
means preserve the boundary assertion and its raw fields. A single usable
PWSID can be matched by ID; otherwise route the assertion for review without
minting an unnamed provider. In particular, a polygon listing multiple PWSIDs
must not automatically be assigned in full to every listed system. All rows
must reconcile between assertions and rejects.
Each field-based mapping explicitly declares how to handle null: missing role
or authority values go to rejects, while a status can be recorded as unknown.
An attribute missing entirely from a feature is an error, not a null default.
Declared names must match both the published field list and the saved feature
attributes. A case-only difference is a mismatch: the Texas Water Development
Board service-area metadata publishes `ObjectId` while every saved feature
uses `ObjectID`, so neither spelling can be declared until those copies agree.
Other fields on that layer can be declared when the spellings agree. Coded
maps must include every non-null observed value with the same characters and
case. A saved `0` is a value, not a null. For ArcGIS layers, review reads every
snapshot page, requires the recorded page hash to match the saved bytes,
and reconciles `downloaded_count`, `id_count`, and
`expected_count_at_start`. The published field list alone cannot mark a source
reviewed.

`seed_evidence.json` preserves the collected manifest records, legacy layer
list, metadata field names and snapshot counts used to seed the drafts. It is
evidence, not a substitute for reviewing a source.

Fourteen spatial layers have saved attributes and no geometry (`status: no_geometry`).
They stay attributes-only until a reviewed re-collection replaces them. Cole's
instruction of 2026-11-12 allows `utilitydata refresh --source` to collect one
of them into the next snapshot. That collection stays draft until it is reviewed,
and it is not part of release 2026Q4.2. Do not repair or digitize the saved
empty layers. The two Massachusetts unlocated tables are nonspatial tables, not
failed geometry downloads.

WP2 source review stopped on 2026-11-11 with 120 reviewed sources and 223 drafts.
The drafts stay unreviewed. Do not guess roles to mark them reviewed. Silver,
Core, and Gold builds may consume reviewed sources only.

The 2026-11-12 promotion gate removed eight promoted ids from the anything-else
pattern list. Four ids reviewed by the WP7 and WP8 builds were also removed,
leaving 14, 28, 40, 11, 26, and 92. The gate set nine of this session's
promotions back to draft: Indiana electric, Texas TWDB water, New York gas, HIFLD
gas, both California Energy Commission territory layers, New Jersey gas, Utah
electric, and Vermont electric. Their declarations stay in the registry. The
gate also set Iowa electric and HIFLD electric back to draft. Both were reviewed
under WP7 and built release 2026Q4.1, so they were outside its scope. They were
restored after the role and direct-service fixes recorded in the
scope-correction gate of `docs/review-gates.md`. A build still may consume reviewed sources only.

The snapshot freeze copies and checksums the collection and records file-level
inventory in `manifest.parquet`. Draft sources stay in that manifest with status
`draft`, which is not buildable. The 14 empty-geometry layers stay
`no_geometry`. Reviewed sources keep saved-attribute, hash, and per-layer count
checks, and only they receive the buildable statuses `collected`,
`partial_geometry`, and `nonspatial`. Unassigned collection files still fail
the freeze. Sources with `storage: home` are reference downloads under the data
root. Their paths are not collection files, so they are not a substitute for
assigning or listing a file in the raw collection. The freeze records per-layer feature and geometry counts in
`layers.parquet`, including separate rows for layers within GeoPackages and
records in archived CSV files. The snapshot keeps the source declarations,
vocabularies, overrides, truth files and unused-file reasons that were in
effect when it was frozen. CSV headers and row shapes are checked both during
registry validation and freeze for reviewed sources, and registry validation
scans fields with explicit value mappings. Large archives can therefore take
time to validate.
