# Windows 本地开发环境

队伍说明见 [TEAM.md](TEAM.md)。源码基线为官方 `2026-competition` 分支，初始化提交为 `9db1753434162c0aa7c9f1189a1722e617880a52`。

## 安装与启动

在仓库目录打开 PowerShell：

```powershell
uv sync --locked --python 3.12 --extra cli --extra server
.\start-local.ps1
```

服务地址为 `http://127.0.0.1:8000`，MCP 地址为 `http://127.0.0.1:8000/mcp`。数据保存在本仓库的 `.powercontext` 目录中；在运行终端按 Ctrl+C 停止服务。

本地基础模式使用 SQLite，支持显式记忆写入和读取。自动提取与语义检索还需另行配置生成模型、嵌入模型及对应 API 凭据。

## 检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
uv lock --check
uv run --no-sync pytest tests/e2e/test_release_smoke.py -q
```

2026-10-25 本机验证：健康检查 `ready`，显式记忆写入和上下文读取通过，发布冒烟检查 `1 passed`。

## Git

`origin` 指向队伍仓库，`upstream` 指向 `https://github.com/oceanbase/powercontext.git`。初始化前的本地提交保存在 `backup/pre-init-20261025` 分支中。开发源码使用 `2026-competition` 分支。

官方基线：[2026-competition](https://github.com/oceanbase/powercontext/tree/2026-competition)。
