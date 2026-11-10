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

The runner also checks each Parquet file's text columns for absolute paths,
geometry-bearing Parquet files for GeoParquet metadata, textual output files
for absolute paths, and stored DuckDB view definitions for absolute paths.
Other binary file formats are not inspected for embedded paths. Missing
contracts, tables, columns and vocabularies cause an error rather than a pass.
