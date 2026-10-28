# 技术说明

## 模块结构

```
context.py         上下文模块 CLI：ingest / scope / context / save
minimax_agent.py   MiniMax 开发助手接入：上下文 → MiniMax → 代码文件 → 测试 → 失败时再交回 MiniMax
run_demo.py        验证样例编排：每步独立进程，记录命令、退出码、输出与代码版本
sample/            业务工程：spec.md、manifest.json、before/（修改前）、after/（MiniMax 输出）、test_task_service.py
evidence/          运行与开发证据
```

## 数据与上下文选择

seekdb 两张表：

- `sdd_sources(project_id, path, kind, tasks, content, sha256)`：来源原文。
- `sdd_entries(project_id, path, kind, entry_id, title, body, line_start, line_end, refs)`：规格条目（按 `## <编号>` 切分，`refs` 为条目中引用的函数）、代码符号（顶层函数/类，`refs` 为其调用）、测试用例（`类.方法`，`refs` 为其调用的函数）。

`context` 依次执行：查询任务关联的来源；查询 `entry_id = 任务编号` 的规格条目（implement）与同一规格的其他条目（preserve）；以 implement 条目的 `refs` 查询代码符号；查询测试用例并保留调用这些符号的用例，按测试类名区分功能与回归测试。每条 SQL、参数和返回行数随输出给出（`query.all_queries`）。

## 各项技术的分工

| 阶段 | seekdb | PowerContext | MiniMax |
| --- | --- | --- | --- |
| 导入 | 写入来源与条目索引（事务替换旧数据） | | |
| 构造上下文 | 查询规格条目、代码符号、测试用例 | 读回最新任务进展 | |
| 代码修改 | | | 依据上下文生成完整文件；测试失败时依据失败输出修正 |
| 验证与交接 | | 保存“已完成 / 待办 / 验证结果”，重启后读回 | |

## 状态复用

任务状态为 JSON（`task`、`completed`、`todo`、`tests`），以 `kind=task-progress` 写入 PowerContext。`context` 取同一 scope 中该任务最后一条记录作为 `progress`；`minimax_agent.py` 在提示中带上已完成与待办，`run_demo.py` 在修改前、修改后各从新进程读取一次，确认状态在重启后可用。
