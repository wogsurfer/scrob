# Quick preview: Watchd's backend with live reload on port 8000, against the
# live database. Pair it with the frontend preview (npm run dev -- --port 4331
# in frontend) and open http://localhost:4331; changes show on save, with no
# rebuild. The live site on 7330 keeps running; rebuild it once the changes
# are done. The preview leaves the live site's syncs and timers alone.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\backend"
foreach ($line in Get-Content "..\.env") {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"'))
    }
}
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "5433"
$env:PYTHONPATH = "."
$env:WATCHD_PREVIEW = "1"
# Windows doesn't report file changes to the reloader reliably.
$env:WATCHFILES_FORCE_POLLING = "true"
# Its own environment, so the WSL one in .venv is left alone.
$env:UV_PROJECT_ENVIRONMENT = ".venv-win"
# uvloop (a Linux speed-up) doesn't install on Windows.
uv sync --python 3.12 --frozen --no-install-package uvloop
if ($LASTEXITCODE) { exit $LASTEXITCODE }
# Windows has no time-zone database of its own; Linux images do.
uv pip install --quiet --python .venv-win tzdata
# Only the code folders are watched (the WSL .venv trips the watcher), so a
# change to main.py itself needs a restart of this script.
uv run --no-sync uvicorn main:app --host 127.0.0.1 --port 8000 --reload `
    --reload-dir core --reload-dir models --reload-dir routers --reload-dir services
