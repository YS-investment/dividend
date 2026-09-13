# Wrapper invoked by the Windows Scheduled Task. Runs local_update.py with
# the project's venv Python and captures full output to a timestamped log
# file, since a scheduled task has no visible console to read afterward.

$RepoRoot = Split-Path -Parent $PSScriptRoot

# Task Scheduler launches this with an unrelated working directory (typically
# System32), not the project folder - without this, every relative path the
# pipeline uses (data/final_df2.csv, etc.) resolves to the wrong place and
# fails immediately.
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "local_update_$Timestamp.log"

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "local_update.py"

& $Python $Script *>> $LogFile
$ExitCode = $LASTEXITCODE

# Keep only the 30 most recent logs so this doesn't grow unbounded.
Get-ChildItem $LogDir -Filter "local_update_*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 |
    Remove-Item -Force

exit $ExitCode
