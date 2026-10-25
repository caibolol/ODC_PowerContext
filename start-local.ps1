$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:POWERCONTEXT_HOME = Join-Path $PSScriptRoot '.powercontext'
& .\.venv\Scripts\powercontext.exe server run --no-env-file --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
