param([Parameter(Mandatory=$true)][string]$SeekdbExe,
      [int]$Port=18753, [string]$DataDirectory=(Join-Path $PSScriptRoot '.runtime/seekdb'))
$ErrorActionPreference='Stop'
$binary=(Resolve-Path -LiteralPath $SeekdbExe).Path
New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
$data=(Resolve-Path -LiteralPath $DataDirectory).Path
& $binary --nodaemon --base-dir $data --port $Port --parameter memory_limit=4G --parameter log_disk_size=2G --parameter datafile_size=2G
exit $LASTEXITCODE
