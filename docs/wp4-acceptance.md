# Water identifier and assertion acceptance cases

Implement these cases with WP4 and WP5; the current registry tests validate
declarations only and do not exercise the transformations.

- Preserve `090600058` unchanged; trim surrounding whitespace in
  `ND2801430\r\n` without rewriting interior characters.
- Accept `WA53AA101`, `WA53HD840` and `UTAH18166` when each has a unique exact
  match in frozen SDWIS. A duplicate or ambiguous match cannot verify an ID.
- Preserve unmatched `OKMCD0003` as raw non-federal evidence. Add a state
  prefix to a seven-digit value only where the source declares that rule.
- Preserve the unnamed `FL4565183` boundary assertion and match its single
  usable identifier; do not require the boundary itself to supply a name.
- Preserve each of the nine unnamed CWS features with multiple PWSIDs once,
  retain all 26 identifier candidates with provenance, and queue the shared
  polygons for review rather than assigning each polygon in full to every
  listed system.
- Preserve unnamed assertions without usable IDs for review. Reconcile every
  source's feature count as assertions plus rejected rows.
- Enforce per-source null and missing-name policies, keep unknown licences
  internal, and exclude mixed or unknown geometry from non-modeled coverage
  until the individual feature's representation has been resolved.
