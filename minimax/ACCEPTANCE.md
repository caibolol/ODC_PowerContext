# 验收项与证据

题面：[MiniMax × OceanBase：规有所依](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)。全部资产位于 `minimax/`。

本页的"本地通过"仅指**本机按运行说明实际执行**的结果，不代表官方平台已给分。

## 六项必做项

| 必做项 | 如何复现 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| **能够运行** | 按 README「依赖与环境」在干净环境安装依赖、启动 seekdb 与 PowerContext（空状态目录），执行 `python run_demo.py --recorded` | **本地通过**：本机全新 venv（Python 3.12.2）+ 全新 seekdb 数据目录 + 全新 `POWERCONTEXT_HOME`，15 步全部按预期退出，末行 `PASS`（首步 `wait-services` 会先等待 seekdb 与 PowerContext 就绪，不需要手工等待）。另以**实时模式**（真实 MiniMax API Key）跑通同一流程，15 步同样全部 PASS | `evidence/run/steps.json`（每步命令、退出码、stdout/stderr）、`evidence/run/summary.json`（最近一次成功运行 run_id `5b3abb06746b`、git_revision `b321368fa8c82ae48724331fafc49b02891d94b9`），该次运行的完整存档在 `evidence/run/5b3abb06746b/`；另有 `--recorded` 模式的存档 `evidence/run/8ef54fe34756/`（git_revision `00f1a9ababb67b531ef2a743a9309bb8a8fa7968`）；`evidence/run/pip-freeze.txt`、`evidence/run/seekdb-build.txt`；另 `evidence/linux-ci/` 为更早一次 Ubuntu 24.04 + seekdb 官方镜像的干净环境运行，`evidence/clean-environment/` 为队员在另一台干净 Windows 机器上的独立复验 |
| **MiniMax 实际参与** | DEVELOPMENT.md；本轮由 WorkBuddy 中运行的 MiniMax（M3.1 Flash）依据上下文写出 `sample/after/task_service.py`；另以真实 API Key 实时调用 MiniMax API 跑通同一流程 | **本地通过**：有本次任务、送入的上下文文件（含 SHA-256）、模型产出的代码与统一差异，四者一一对应；并有 WorkBuddy 平台自己生成的改动日志可机械复核。另有一次**实时 MiniMax API 调用**（响应 ID `07324d87bd9ca30a48c0ae71d254661b`、usage 2039 tokens、2 轮）产出逐字节相同的代码 | `evidence/workbuddy-minimax/`（`context-before-change.json`、`task_service.py`、`change.diff`、`tests-*.log`、README 为完整开发记录）；`evidence/workbuddy-minimax/platform-record/`（平台会话元数据，模型 ID `minimax-m3.1-flash`；平台改动日志含业务代码逐行 hunk），`python verify_platform_record.py` 复核后重建代码与提交文件 SHA-256 均为 `fc7ab995…`；`evidence/run/5b3abb06746b/`（实时调用的完整记录：请求、回复、响应 ID、usage、生成的代码与测试结果）；更早的独立 MiniMax API 记录保留于 `evidence/minimax-api/`（脱敏后的交付副本，保留响应 ID、usage、代码与测试结果） |
| **上下文正确** | `python context.py context --project P --task TASK-2 --scope S`；`run_demo.py` 最后一步追加规格并重新导入 | **本地通过**：输出含 `spec.md#TASK-2`（implement）、`spec.md#TASK-1`（preserve）、`before/task_service.py#list_tasks`、功能测试 5 项与回归测试 2 项；追加规格并重新 `ingest` 后，implement 条目正文出现新增文字（`context-updated.json`） | `evidence/run/context-initial.json`、`context-restored.json`、`context-updated.json`；本轮 `evidence/workbuddy-minimax/context-*.json` |
| **数据库实际参与** | `context.py` 写入并参数绑定查询 seekdb 的 `sdd_sources` / `sdd_entries` | **本地通过**：每份上下文输出都带 `query.all_queries`，含实际执行的 SQL、参数与返回行数（5 条查询，行数 3/1/1/1/7）；上下文内容即由这些查询结果构造 | 各 `context-*.json` 的 `query.all_queries` 字段 |
| **状态能够复用** | 新建空 scope → 写入任务记录 → **结束 PowerContext 服务进程并重启** → 新进程读回 | **本地通过**：`context-initial.json` 的 `progress` 全为空且 `source=null`；重启服务后 `context-restored.json` 读回 `completed` 3 项、`todo` 空、`verification` 2 组，`source=PowerContext task-progress` | `evidence/workbuddy-minimax/save-start.json`、`save-done.json`、`context-initial.json`、`context-restored.json`；`evidence/run/steps.json` 中 `save-*` / `context-*` 步骤 |
| **代码修改有效** | `run_demo.py` 修改前后各跑同一组测试（同一测试文件，未增删断言） | **本地通过**：功能测试修改前退出码 1（`FAILED (failures=5)`，5 项均为断言失败，非环境错误），修改后退出码 0（`OK`）；回归测试修改前后均退出码 0，且两份回归日志逐字节相同 | `evidence/run/steps.json`（`tests-before-target` / `tests-before-regression` / `tests-after-target` / `tests-after-regression`）；`evidence/workbuddy-minimax/tests-*.log` |

## 自查汇总

| # | 必做项 | 结论 |
| --- | --- | --- |
| 1 | 能够运行 | 本地通过 |
| 2 | MiniMax 实际参与 | 本地通过 |
| 3 | 上下文正确 | 本地通过 |
| 4 | 数据库实际参与 | 本地通过 |
| 5 | 状态能够复用 | 本地通过 |
| 6 | 代码修改有效 | 本地通过 |

六项均为本地通过；**官方评分以平台记录的固定提交为准**。

上表逐项结论由 `verify_acceptance.py` 判定，评审可自行运行复核（只读交付目录内的文件，不需要数据库、网络或本机 WorkBuddy 安装；全部通过退出码 0，任一失败为 1）：

```bash
python verify_acceptance.py
```

实际输出见 `evidence/run/acceptance-check.txt`。

该脚本是**交付材料一致性自检**：核对材料是否齐备、来源是否真实存在、各份材料之间是否自洽（模型名属于 MiniMax、
变更记录的会话 ID 与平台会话一致、API 每一轮字段完整、交付副本已脱敏且保留关键证据、验收文档引用当前保留的运行记录）。
它**不能**认证模型服务商的来源、不能证明回复确实由某个服务商生成，也**不能代替官方验收**——官方评分以平台记录的固定提交为准。

`test_tooling.py` 另有 10 项工具自身单测：输出文件校验（防止自检测到旧代码）与就绪探测（503 不得判为就绪）。

## 材料索引

- **完整源码**：`context.py`、`minimax_agent.py`、`run_demo.py`、`sample/`、启动脚本；`verify_sample.py`、`verify_context.py`、`verify_platform_record.py`、`verify_acceptance.py`、`test_tooling.py`。
- **运行说明**：`README.md`；依赖：`requirements.txt`（Windows 完整锁定 `requirements-windows-lock.txt`，PowerContext 指向官方公开仓库）。
- **验证样例**：`README.md`「验证样例」；`sample/spec.md`、`sample/manifest.json`、`sample/before/`、`sample/after/`、`sample/test_task_service.py`。
- **代码与测试**：修改前后快照 `sample/before/`、`sample/after/`；差异 `evidence/workbuddy-minimax/change.diff` 与 `evidence/minimax-api/*-change.diff`；测试日志 `evidence/run/steps.json`、`evidence/workbuddy-minimax/tests-*.log`。
- **技术使用记录**：MiniMax 见 `DEVELOPMENT.md` 与 `evidence/workbuddy-minimax/`、`evidence/minimax-api/`；数据库查询见各 `context-*.json` 的 `query.all_queries`；PowerContext 写入与重启复用见 `evidence/workbuddy-minimax/save-*.json`、`context-restored.json` 与 `evidence/run/steps.json`。
- **一页技术说明**：`TECHNICAL.md`。
- **更早的运行环境证据**：`evidence/linux-ci/`（Ubuntu 24.04 + seekdb 官方镜像）、`evidence/clean-environment/`（队员在另一台干净 Windows 机器上的复验）。
- **运行记录归档**：每次 `run_demo.py` 的证据在 `evidence/run/<运行编号>/`；`evidence/run/` 根目录是最近一次成功运行的副本。实时复跑不会覆盖 `sample/after/task_service.py`，失败运行也不会破坏已有成功证据。
