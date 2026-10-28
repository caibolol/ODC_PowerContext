#!/usr/bin/env bash
# 启动 PowerContext 记忆服务（本地 18752 端口）。首次运行会从官方公开仓库安装。
set -euo pipefail
cd "$(dirname "$0")/.."
PC_REPO="git+https://github.com/oceanbase/powercontext.git@dab240063bfcfa7917898dc44da4baadb3747bd0"
PORT="${PC_PORT:-18752}"

if [ ! -x .venv-pc/bin/powercontext ]; then
  echo "[context] 创建虚拟环境并安装 powercontext（官方公开仓库）"
  python3 -m venv .venv-pc
  .venv-pc/bin/pip install -q "$PC_REPO"
fi

mkdir -p .pc-home
POWERCONTEXT_HOME="$PWD/.pc-home" nohup .venv-pc/bin/powercontext server run --no-env-file --host 127.0.0.1 --port "$PORT" > .pc.log 2>&1 &
echo $! > .pc.pid

for _ in $(seq 1 30); do
  if curl -sf -X POST "http://127.0.0.1:$PORT/v1/scopes" -H 'Content-Type: application/json' \
    -d '{"title":"probe","summary":"probe","idempotency_key":"probe"}' >/dev/null 2>&1; then
    echo "[context] PowerContext ready: http://127.0.0.1:$PORT"
    exit 0
  fi
  sleep 1
done
echo "[context] PowerContext 启动超时，见 .pc.log" >&2
exit 1
