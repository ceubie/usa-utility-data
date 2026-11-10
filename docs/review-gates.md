# Independent review gates

Cole directed that each plan review gate be performed by a subagent. Record
the reviewed state and any required follow-through here; a review does not
make unreviewed source entries eligible for a build.

| Gate | Result | Required follow-through |
| --- | --- | --- |
| WP1 contracts and checks | Approved after corrections to false path matches, strict validation, GeoParquet checks and the baseline. | Before WP6, provide inspection and narrowly scoped reviewed exceptions for ambiguous path candidates. |
| WP2 registry schema and first 20 water sources | Approved after correcting identifiers, unassigned areas, licence restrictions and geometry representation. | Complete the remaining source reviews; enforce identifier, unnamed-feature, licence and representation policies in WP4 and later products. |
| WP2 EPA archive declarations and snapshot checks | Approved after adding CSV and geospatial validation, archived-layer counts, copied-tree revalidation and final checksum checks. | Run a real freeze only after every source is reviewed and all collection files have a disposition. |
| WP4 non-community replacement decision | Pending independent review. | Compare the newer archive and older source before choosing a replacement. |
| WP5 thresholds and sampled matches | Pending independent review. | Calibrate on the hand-labelled sample and inspect the queue and 50 matches. |
| WP6 first release | Pending independent review. | Review accuracy, coverage, licence editions and release artifacts. |
| WP11 ontology and query language | Pending independent review. | Confirm the ontology and SPARQL choice before WP12. |

The approved PWSID exception and the evidence behind it are in
`registry/vocab/pwsid_policy.yaml` and `registry/pwsid_format_audit.json`.
Future transformation acceptance cases are in `docs/wp4-acceptance.md`.
