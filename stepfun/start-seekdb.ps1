param(
    [Parameter(Mandatory=$true)][string]$SeekdbExe,
    [string]$DataDirectory = (Join-Path $PSScriptRoot '.seekdb-data'),
    [int]$Port = 2881
)
$ErrorActionPreference = 'Stop'
$binary = (Resolve-Path -LiteralPath $SeekdbExe).Path
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Port must be between 1024 and 65535.' }
New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
$data = (Resolve-Path -LiteralPath $DataDirectory).Path
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Use the existing database or choose another port."
}
# 前台启动，不修改已有实例；终止脚本后数据仍保留在独立目录。
& $binary --nodaemon --base-dir $data --port $Port --parameter memory_limit=4G --parameter log_disk_size=2G --parameter datafile_size=2G
exit $LASTEXITCODE
