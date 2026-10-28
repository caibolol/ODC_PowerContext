param([int]$Port=18752, [string]$DataDirectory=(Join-Path $PSScriptRoot '.runtime/powercontext'))
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
$env:POWERCONTEXT_HOME=(Resolve-Path -LiteralPath $DataDirectory).Path
powercontext server run --no-env-file --host 127.0.0.1 --port $Port
