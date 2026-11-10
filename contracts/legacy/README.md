# Legacy contracts for the first review

These contracts describe only the legacy tables needed to measure the known
baseline; they are not the contracts for the rebuilt platform. Each YAML file
names a table and its path relative to the data directory, a composite
`primary_key`, and column specifications. Columns may declare `type`,
`nullable`, `references` as `table.column`, or a vocabulary name. A
`group_by` on a foreign-key column breaks failures down by another column.
`min_fill` maps a column to its required non-null fraction. The 100% fill
requirements here deliberately expose completely empty legacy fields; they
are not proposed release thresholds.

The runner checks Parquet text and nested columns, supported textual output,
and DuckDB view definitions and table text for apparent absolute paths. Its
path recognition is heuristic: ambiguous slash-containing values are reported
separately and fail the check for review. Unknown file types fail closed as
unverifiable. Geometry-bearing Parquet files must contain valid
GeoParquet metadata; declare a column as `type: geometry` if its name is not
`geometry` or `geometry_wkb`. Missing contracts, tables, columns and
vocabularies cause an error rather than a pass. Query checks include the SQL
needed to retrieve violating rows; minimum-fill queries return the null rows.

Before WP6 relies on this check for a release, add a way to inspect ambiguous
path candidates and record narrowly scoped, reviewed exceptions. The current
check fails closed on those candidates and does not yet support exceptions;
some legacy utility names are known examples of benign candidates.
