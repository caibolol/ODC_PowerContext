# Windows 一条命令复现 EvidenceDesk。
# 用法（在 qoder\ 目录）：powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -SeekdbExe C:\seekdb\seekdb.exe
# SeekdbExe 必填：seekdb.exe 路径（与其附带 DLL 同目录）。若 2881 端口已有 seekdb 在运行则直接复用。
param(
  [Parameter(Mandatory = $true)][string]$SeekdbExe,
  [int]$Port = 2881
)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$env:DB_PORT = "$Port"
if (-not $env:DB_NAME) { $env:DB_NAME = 'test' }

Write-Host '[bootstrap] 1/5 安装 Node 依赖'
npm ci

Write-Host "[bootstrap] 2/5 检查 127.0.0.1:$Port 是否已有可用 seekdb"
$env:WAIT_TIMEOUT_SEC = '5'
$running = $false
node scripts/wait-ready.js *> $null
if ($LASTEXITCODE -eq 0) { $running = $true }
Remove-Item Env:WAIT_TIMEOUT_SEC

if (-not $running) {
  if (-not (Test-Path $SeekdbExe)) { throw "seekdb 可执行文件不存在: $SeekdbExe" }
  Write-Host '[bootstrap] 3/5 启动 seekdb'
  $baseDir = Join-Path $PWD '.seekdb-data'
  New-Item -ItemType Directory -Force -Path $baseDir | Out-Null
  $procArgs = @('--nodaemon', '--base-dir', $baseDir, '--port', "$Port",
    '--parameter', 'cpu_count=4', '--parameter', 'memory_budget=2G',
    '--parameter', 'datafile_size=32M', '--parameter', 'datafile_maxsize=2G',
    '--parameter', 'log_disk_size=2G')
  Start-Process -FilePath $SeekdbExe -ArgumentList $procArgs -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $PWD '.seekdb.log') `
    -RedirectStandardError (Join-Path $PWD '.seekdb.err.log') | Out-Null
} else {
  Write-Host '[bootstrap] 检测到已在运行的 seekdb，直接复用'
}

Write-Host '[bootstrap] 4/5 等待就绪、初始化表结构、导入样例'
node scripts/wait-ready.js
if ($LASTEXITCODE -ne 0) { throw 'seekdb 未能在超时时间内就绪，见 .seekdb.log' }
npm run db:init
node scripts/import-sample.js

Write-Host '[bootstrap] 5/5 启动应用 http://127.0.0.1:18748 （Ctrl-C 退出）'
npm start
