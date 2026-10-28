# 启动 PowerContext 记忆服务（本地 18752 端口）。首次运行会从官方公开仓库安装。
# 用法（在 qoder\ 目录）：powershell -ExecutionPolicy Bypass -File scripts\start-context.ps1
param([int]$Port = 18752)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$pcRepo = 'git+https://github.com/oceanbase/powercontext.git@dab240063bfcfa7917898dc44da4baadb3747bd0'

if (-not (Test-Path .venv-pc\Scripts\powercontext.exe)) {
  Write-Host '[context] 创建虚拟环境并安装 powercontext（官方公开仓库）'
  python -m venv .venv-pc
  & .venv-pc\Scripts\pip.exe install -q $pcRepo
}

New-Item -ItemType Directory -Force -Path .pc-home | Out-Null
$env:POWERCONTEXT_HOME = Join-Path $PWD '.pc-home'
Start-Process -FilePath .venv-pc\Scripts\powercontext.exe `
  -ArgumentList @('server', 'run', '--no-env-file', '--host', '127.0.0.1', '--port', "$Port") `
  -WindowStyle Hidden -RedirectStandardOutput .pc.log -RedirectStandardError .pc.err.log | Out-Null

for ($i = 0; $i -lt 30; $i++) {
  try {
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/scopes" -ContentType 'application/json' `
      -Body '{"title":"probe","summary":"probe","idempotency_key":"probe"}' | Out-Null
    Write-Host "[context] PowerContext ready: http://127.0.0.1:$Port"
    exit 0
  } catch { Start-Sleep 1 }
}
throw 'PowerContext 启动超时，见 .pc.log'
