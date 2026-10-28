#!/usr/bin/env bash
# 一条命令复现 EvidenceDesk：安装/启动 seekdb → 建表与 IK 索引 → 导入样例 → 启动服务。
# 用法：在 qoder/ 目录执行  bash scripts/bootstrap.sh
# 可选环境变量：SEEKDB_PORT（默认 2881）、DB_NAME（默认 test）、SEEKDB_BIN（指定已有 seekdb 可执行文件）
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${SEEKDB_PORT:-2881}"
BASE_DIR="$PWD/.seekdb-data"
DL_DIR="$PWD/.seekdb-dl"
LOG="$PWD/.seekdb.log"
export DB_PORT="$PORT"
export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_NAME="${DB_NAME:-test}"
export DB_USER="${DB_USER:-root}"
export DB_PASSWORD="${DB_PASSWORD:-}"
RELEASE="https://github.com/oceanbase/seekdb/releases/download/v1.4.0"

echo "[bootstrap] 1/6 安装 Node 依赖"
npm ci || npm install

echo "[bootstrap] 2/6 检查 ${DB_HOST}:${PORT} 是否已有可用 seekdb"
if WAIT_TIMEOUT_SEC=5 node scripts/wait-ready.js >/dev/null 2>&1; then
  echo "[bootstrap] 检测到已在运行的 seekdb，直接复用"
else
  BIN="${SEEKDB_BIN:-}"
  if [ -z "$BIN" ]; then BIN="$(command -v seekdb || true)"; fi

  if [ -z "$BIN" ] && [ -d "$DL_DIR/root" ]; then
    BIN="$(find "$DL_DIR/root" -type f -name seekdb | head -1 || true)"
    [ -n "$BIN" ] && chmod +x "$BIN"
  fi

  if [ -z "$BIN" ]; then
    echo "[bootstrap] 3/6 安装 seekdb v1.4.0"
    mkdir -p "$DL_DIR"
    ARCH="$(uname -m)"
    case "$ARCH" in
      x86_64) DEB_ARCH=amd64; RPM_ARCH=x86_64 ;;
      aarch64 | arm64) DEB_ARCH=arm64; RPM_ARCH=aarch64 ;;
      *) echo "[bootstrap] 不支持的架构 $ARCH，请按 README 手动安装 seekdb" >&2; exit 1 ;;
    esac
    if [ "$(uname -s)" = "Darwin" ]; then
      echo "[bootstrap] macOS 请执行: brew tap oceanbase/seekdb && brew install seekdb" >&2
      exit 1
    fi
    . /etc/os-release
    case "$ID" in
      ubuntu) PKG="seekdb_1.4.0-100000212026082616ubuntu$([ "${VERSION_ID%%.*}" = "24" ] && echo 24.04 || echo 22.04)_${DEB_ARCH}.deb"; KIND=deb ;;
      debian) PKG="seekdb_1.4.0-100000212026082616debian$([ "$VERSION_ID" = "13" ] && echo 13 || echo 12)_${DEB_ARCH}.deb"; KIND=deb ;;
      rhel | centos | fedora | alinux | anolis) PKG="seekdb-1.4.0-100000172026082615.el$([ "${VERSION_ID%%.*}" -ge 9 ] 2>/dev/null && echo 9 || echo 7).${RPM_ARCH}.rpm"; KIND=rpm ;;
      *) PKG="seekdb_1.4.0-100000212026082616debian12_${DEB_ARCH}.deb"; KIND=deb ;;
    esac
    echo "[bootstrap] 下载 $PKG"
    curl -fL --retry 3 -o "$DL_DIR/pkg" "$RELEASE/$PKG"
    mkdir -p "$DL_DIR/root"
    if [ "$KIND" = deb ]; then
      if command -v dpkg-deb >/dev/null 2>&1; then
        dpkg-deb -x "$DL_DIR/pkg" "$DL_DIR/root"
      else
        echo "[bootstrap] 缺少 dpkg-deb，请改用官方安装器: curl -fsSL https://obportal.s3.ap-southeast-1.amazonaws.com/download-center/opensource/seekdb/seekdb_install.sh | bash" >&2
        exit 1
      fi
    else
      if command -v rpm2cpio >/dev/null 2>&1 && command -v cpio >/dev/null 2>&1; then
        (cd "$DL_DIR/root" && rpm2cpio ../pkg | cpio -idmu --quiet)
      else
        echo "[bootstrap] 缺少 rpm2cpio/cpio，请改用官方安装器: curl -fsSL https://obportal.s3.ap-southeast-1.amazonaws.com/download-center/opensource/seekdb/seekdb_install.sh | bash" >&2
        exit 1
      fi
    fi
    BIN="$(find "$DL_DIR/root" -type f -name seekdb | head -1 || true)"
    [ -n "$BIN" ] && chmod +x "$BIN"
  fi

  if [ -z "$BIN" ]; then
    echo "[bootstrap] 未找到 seekdb 可执行文件，请按 README 手动安装后重试" >&2
    exit 1
  fi

  echo "[bootstrap] 4/6 启动 seekdb（$BIN，端口 $PORT）"
  mkdir -p "$BASE_DIR"
  nohup "$BIN" --nodaemon --base-dir "$BASE_DIR" --port "$PORT" \
    --parameter cpu_count=4 --parameter memory_budget=2G \
    --parameter datafile_size=32M --parameter datafile_maxsize=2G \
    --parameter log_disk_size=2G >"$LOG" 2>&1 &
  echo $! > "$PWD/.seekdb.pid"
fi

echo "[bootstrap] 5/6 等待数据库就绪并初始化表结构、导入样例"
node scripts/wait-ready.js
npm run db:init
node scripts/import-sample.js

echo "[bootstrap] 6/6 启动应用 http://127.0.0.1:${PORT:-18748} （Ctrl-C 退出）"
exec npm start
