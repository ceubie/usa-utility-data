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

`seed_evidence.json` preserves the collected manifest records, legacy layer
list, metadata field names and snapshot counts used to seed the drafts. It is
evidence, not a substitute for reviewing a source.

The snapshot freeze refuses draft sources and unassigned files, copies and
checksums the collection, and records file-level inventory in
`manifest.parquet`. It records per-layer feature and geometry counts in
`layers.parquet`, including separate rows for layers within GeoPackages and
records in archived CSV files. The snapshot keeps the source declarations and
unused-file reasons that were in effect when it was frozen. CSV headers and
row shapes are checked both during registry validation and freeze, and
registry validation scans fields with explicit value mappings. Large archives
can therefore take time to validate.
