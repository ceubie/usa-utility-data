# Rebuild setup

Install Python 3.11 or later and [uv](https://docs.astral.sh/uv/), then run
`uv sync --locked` and `uv run pytest`. CI uses the same commands and does not
require the raw collection or derived data.

Set `UTILITYDATA_HOME` to an absolute path for generated data. For the local
default, use the ignored `data` directory in this checkout, for example in
PowerShell:

```powershell
$env:UTILITYDATA_HOME = Join-Path (Get-Location) 'data'
```

The preserved raw collection defaults to `collection/data` in the checkout;
it is ignored by Git and must be copied separately. Legacy outputs belong in
`$env:UTILITYDATA_HOME/legacy/silver` and `.../legacy/gold`. This environment
variable must be set in each shell that runs data commands.
