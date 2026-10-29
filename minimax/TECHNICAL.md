# 技术说明

## 模块结构

```
context.py         上下文模块 CLI：ingest / scope / context / save
minimax_agent.py   MiniMax 开发助手接入：上下文 → MiniMax → 代码文件 → 测试 → 失败时再交回 MiniMax
run_demo.py        验证样例编排：每步独立进程，记录命令、退出码、输出与代码版本
test_context_units.py  离线单元测试：规格替代/废弃、验证结果适用性、进展过滤、提示内容
sample/            业务工程：spec.md、manifest.json、before/（修改前）、after/（MiniMax 输出）、test_task_service.py
evidence/          运行与开发证据
```

## 数据与上下文选择

seekdb 两张表：

- `sdd_sources(project_id, path, kind, tasks, content, sha256)`：来源原文。
- `sdd_entries(project_id, path, kind, entry_id, title, body, line_start, line_end, refs)`：规格条目（按 `## <编号>` 切分，`refs` 为条目中引用的函数）、代码符号（顶层函数/类，`refs` 为其调用）、测试用例（`类.方法`，`refs` 为其调用的函数）。

`context` 依次执行：查询任务关联的来源；查询 `entry_id = 任务编号` 的规格条目（implement）与同一规格的其他条目（preserve）；以 implement 条目的 `refs` 查询代码符号；查询测试用例并保留调用这些符号的用例，按测试类名区分功能与回归测试。每条 SQL、参数和返回行数随输出给出（`query.all_queries`）。

规格演进：条目正文可写 `> 替代：TASK-1`（被替代条目失效）或 `> 状态：废弃`（本条目失效）。失效条目不进入 implement / preserve，单独列在 `inactive_spec_entries`（含 `status`、`by`、`reason`），提示中标注“不得作为要求”。同一编号的补充小节并入该条目；重新导入时整体替换旧索引，旧文字不会残留。

## 各项技术的分工

| 阶段 | seekdb | PowerContext | MiniMax |
| --- | --- | --- | --- |
| 导入 | 写入来源与条目索引（事务替换旧数据） | | |
| 构造上下文 | 查询规格条目、代码符号、测试用例 | 读回最新任务进展 | |
| 代码修改 | | | 依据上下文生成完整文件；测试失败时依据失败输出修正 |
| 验证与交接 | | 保存“已完成 / 待办 / 验证结果”，重启后读回 | |

## 状态复用与验证结果的适用性

任务状态为 JSON（`task`、`completed`、`todo`、`tests`），以 `kind=task-progress` 写入 PowerContext。`context` 只采用该 scope 中 `kind=task-progress`、状态 active、字段类型正确的记录，按 `saved_at` 取该任务最新一条作为 `progress`；其他类别的记忆不会混入。

每条验证结果带 `basis`：保存时适用规格条目正文、代码文件、测试文件的 SHA-256（取自 seekdb `sdd_sources` / `sdd_entries`）。`context` 用当前导入的版本逐条比较，标注 `validity`：`current`（仍适用）、`stale`（`changed` 列出变化的是 spec / code / tests）、`unknown`（无版本信息）。最近一条不是 `current` 时，`needs_reverification=true`，并在待办中追加一条“重新运行功能与回归测试”。旧结果保留为历史，不会被当作当前代码的证据。

`minimax_agent.py` 把已完成、待办、各条验证结果及其适用性、失效规格一并交给 MiniMax；自身的测试自检记录绑定本轮生成代码的版本。`run_demo.py` 每步一个新进程，依次断言：代码修改并重新导入后修改前的验证变为 stale；修改后验证为 current；规格更新后它变为 stale（changed=spec）；新条目替代 TASK-1 后 TASK-1 不再下发。
