# 验收项与证据

题面：[MiniMax × OceanBase：规有所依](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)。全部资产位于 `minimax/`。

| 必做项 | 如何复现 | 证据 |
| --- | --- | --- |
| 能够运行 | README.md「Linux」一节：安装依赖、启动 seekdb 官方镜像与 PowerContext（空数据目录），执行 `python run_demo.py --recorded` | `evidence/run/steps.json`、`summary.json`（每步命令、退出码、输出、git 版本） |
| MiniMax 实际参与 | DEVELOPMENT.md；`python run_demo.py`（配置 MINIMAX_API_KEY）实时复现 | `evidence/minimax-api/20261029T032003Z-exchange.json`（v2 上下文、每轮请求与回复、测试结果）与 `20261028T010349Z-exchange.json`、对应 `*-change.diff`；`sample/after/task_service.py` 与两次记录的最终输出逐字节相同 |
| 上下文正确 | `python context.py context ...`；`run_demo.py` 追加规格、声明替代并重新导入 | `evidence/run/context-initial.json`、`context-updated.json`、`context-superseded.json`：含 `spec.md#TASK-2`/`#TASK-1`、`list_tasks` 代码符号、`FeatureTests` 5 个与 `RegressionTests` 2 个用例；更新后 implement 条目包含新增文字，旧验证结果标为 stale；替代后 TASK-1 列入 `inactive_spec_entries` |
| 数据库实际参与 | context.py 写入并查询 seekdb 的 `sdd_sources`、`sdd_entries` | 每份 context 输出的 `query.all_queries`（SQL、参数、返回行数） |
| 状态能够复用 | `run_demo.py`：新 scope 为空 → 保存进展 → 新进程读回 → MiniMax 修改 → 保存验证结果 → 新进程读回 | `context-initial.json`（`progress` 为空）、`context-before-change.json`（读回待办与修改前结果）、`context-after-change.json`（代码变化后修改前结果 stale）、`context-restored.json`（已完成、待办为空、修改后结果 current） |
| 代码修改有效 | `run_demo.py` 修改前后各运行同一组测试 | `steps.json`：`tests-before-target` 退出 1（5 个断言失败，非环境错误），`tests-before-regression` 退出 0，`tests-after-target`、`tests-after-regression` 退出 0；测试文件 SHA-256 前后相同 |

## 材料索引

- 完整源码：`context.py`、`minimax_agent.py`、`run_demo.py`、`sample/`、启动脚本；离线单元测试 `test_context_units.py`；原有 `verify_sample.py`、`verify_context.py`。
- 运行说明：README.md；依赖：`requirements.txt`（Windows 完整锁定 `requirements-windows-lock.txt`）。
- 验证样例：README.md「验证样例」；`sample/spec.md`、`sample/manifest.json`、`sample/before/`、`sample/after/`、`sample/test_task_service.py`。
- 代码与测试：修改前后快照 `sample/before/`、`sample/after/`；差异 `evidence/minimax-api/*-change.diff`；测试日志 `evidence/run/steps.json`。
- 技术使用记录：DEVELOPMENT.md（MiniMax）、context 输出中的 `query`（数据库查询）、`steps.json` 中的 `save-*` 与 `context-*` 步骤（PowerContext 写入与复用）。
- 一页技术说明：TECHNICAL.md。
