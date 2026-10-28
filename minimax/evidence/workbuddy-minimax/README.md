# 本轮 MiniMax 开发记录（WorkBuddy 宿主）

本文件记录**本次实际产出最终业务代码**的那一次修改：模型在 WorkBuddy 会话中直接读到上下文模块产出的上下文，据此写出 `sample/after/task_service.py`。

`evidence/minimax-api/` 下另有一份独立 MiniMax API 调用记录（更早完成，行为等价），两者都保留，见文末对照。

## 宿主与模型

| 项 | 值 |
| --- | --- |
| 开发宿主 | WorkBuddy（开发助手宿主，本次会话即在 WorkBuddy 中进行） |
| 参与代码修改的模型 | MiniMax M3.1 Flash（WorkBuddy 界面中当前选择的 MiniMax 模型） |
| 模型如何取得上下文 | 把 `context.py context` 的真实输出文件读入会话（见下） |
| 模型如何交付代码 | 在会话中写出 `sample/after/task_service.py` 的完整内容，落盘后运行同一组测试验证 |

## 本次任务

任务 `TASK-2`：为 `list_tasks(tasks, status=None)` 增加 todo/done 状态筛选，同时保持 `TASK-1` 规定的原有行为（不传筛选条件时返回全部任务的副本、保持顺序、不修改输入）。

## 实际提供给模型的上下文

文件：`evidence/workbuddy-minimax/context-before-change.json`
SHA-256：`74f2d5c5cc23f5869c5fbed42c926011d98fb41102f965a5772df46b458bdd2c`

该文件是 `context.py context --project taskboard-wb-20261028 --task TASK-2 --scope scp_42y0s3qk3n7deptnseawwhbrq3` 的真实输出（独立进程执行），内容全部来自 seekdb 的 5 条参数绑定查询与 PowerContext 的状态读回：

- **适用规格条目**（`spec_entries`）
  - `[implement] spec.md#TASK-2 L6-10 状态筛选`
  - `[preserve] spec.md#TASK-1 L3-5 原有行为`
- **需要修改的代码**（`code_targets`）：`before/task_service.py#list_tasks`（FunctionDef，L1-2）
- **验证测试**（`tests`）
  - 功能测试 5 项：`FeatureTests.test_done` / `test_normalization_and_default` / `test_invalid` / `test_empty_filtered` / `test_no_mutation`
  - 回归测试 2 项：`RegressionTests.test_no_filter` / `test_empty_unfiltered`
- **任务进展**（`progress`，来自 PowerContext，模块重启后读回）
  - 已完成：导入规格、代码与测试到 seekdb
  - 待办：由 MiniMax 依据上下文修改代码；运行功能与回归测试
- **seekdb 查询记录**（`query.all_queries`）：5 条 SQL，各自带参数与返回行数（3 / 1 / 1 / 1 / 7）

上下文中**不含任何参考实现**：`sample/after/` 的既有内容未出现在 `sources` 中，`before/task_service.py` 是修改前原始实现。

## 实际修改过程

模型依据上下文中三条约束推导实现：

1. `implement` 条目要求 status 先 `strip().casefold()`，且只允许 `todo` / `done`，否则抛 `ValueError` → 对**筛选参数**做 strip + casefold 并校验。
2. `implement` 条目写明"记录中的 status 使用 casefold() 比较"，**未**要求对记录里的 status 做 strip → 对**记录中的 status** 只做 casefold。
3. `implement` 条目写明"缺失 status 的任务视为 todo" → `task.get('status', 'todo')`。
4. `preserve` 条目要求不筛选时返回副本、不改顺序、不改输入 → `status is None` 时直接 `return list(tasks)`；筛选路径用列表推导保持顺序且不修改输入。

第 2 点是本样例的关键分歧点：若对记录中的 status 也做 strip，`FeatureTests.test_done` 中 `' DONE '` 的记录会被错误计入，从而失败。

## 产出与差异

- 产出文件：`sample/after/task_service.py`，SHA-256 `fc7ab99516ea1a020618687592277247e51ad1033296b9a2e29bf408cb8a88c4`
- 同一份字节另存为 `evidence/workbuddy-minimax/task_service.py`
- 统一差异：`evidence/workbuddy-minimax/change.diff`（`sample/before/task_service.py` → `sample/after/task_service.py`）
- 修改前快照：`sample/before/task_service.py`，SHA-256 `e233a73b2736188e2fe9a8790ca9533a09a4d9dc9ec86110ee17e762a7ded978`
- 测试文件未被修改：`sample/test_task_service.py`，SHA-256 `2c01d2de7e49987f1ead4e38a0916f4a7f3bae40dcfcf701d24a171435f899a7`（修改前后一致）

## 修改前后测试（同一组测试，同一测试文件）

命令（在 `minimax/` 下执行，`PYTHONPATH` 指向工作副本与 `sample/`）：

```
python -B -m unittest -v test_task_service.FeatureTests
python -B -m unittest -v test_task_service.RegressionTests
```

| 阶段 | 用例组 | 退出码 | 日志 | SHA-256 |
| --- | --- | --- | --- | --- |
| 修改前 | 功能测试 FeatureTests（5 项） | **1**（`FAILED (failures=5)`，断言失败） | `tests-before-target.log` | `7712bd46d5211fa376d7f4026980bb1cf16228dc7b4d744369fa8f9449d1d892` |
| 修改前 | 回归测试 RegressionTests（2 项） | 0（`OK`） | `tests-before-regression.log` | `467ba065cd858b5e033cbfdee32c2a6e4c7cd0d2c9cd13bd2af867a36c0a0b9a` |
| 修改后 | 功能测试 FeatureTests（5 项） | 0（`OK`） | `tests-after-target.log` | `d9c628469555805dede5ced2b8d756896f06a1fb29f39bc0013d8513dfe2673c` |
| 修改后 | 回归测试 RegressionTests（2 项） | 0（`OK`） | `tests-after-regression.log` | `467ba065cd858b5e033cbfdee32c2a6e4c7cd0d2c9cd13bd2af867a36c0a0b9a` |

修改前的失败是断言失败（`AssertionError: ValueError not raised`、`Lists differ: ...`），不是缺依赖、无法启动或语法错误。修改前后两份回归测试日志**逐字节相同**（同一 SHA-256），说明原有行为基准未被改动。

## 状态写入与重启复用

| 步骤 | 记录 | 说明 |
| --- | --- | --- |
| 空状态 | `context-initial.json` | 新建 scope，`progress` 的 completed / todo / verification 均为空数组，`source` 为 `null` |
| 写入起始进展 | `save-start.json` | `context.py save` → PowerContext `/v1/memory/remember`（`kind=task-progress`） |
| 重启后读回 | `context-before-change.json` | 新进程执行 `context.py context`，`progress.source` = `PowerContext task-progress` |
| 写入验证结果 | `save-done.json` | 含修改前后两组退出码与代码 / 测试文件 SHA-256 |
| **停掉 PowerContext 服务进程后重启** | `context-restored.json` | 杀掉监听 18752 的 PowerContext 进程（PID 21880），用同一 `POWERCONTEXT_HOME` 重新启动服务，再次执行 `context.py context` 读回：`completed` 3 项、`todo` 空、`verification` 2 组（before / after） |

PowerContext 状态落在 `$POWERCONTEXT_HOME/powercontext.db`（SQLite）。因此上表最后一行是**跨服务进程重启**的复用，不是在同一进程内读内存变量，也没有把先前导出的状态文件当作读回结果。

## 与更早的 MiniMax API 记录的关系

`evidence/minimax-api/20261028T010349Z-exchange.json` 是更早一次**独立 MiniMax API 调用**（端点 `https://api.minimaxi.com/v1/chat/completions`，模型 `MiniMax-M3`，2 轮，含每轮完整请求、原始回复与测试结果）的真实记录，其产出的代码已另存为 `evidence/minimax-api/20261028T010349Z-task_service.py`（SHA-256 `8b9c31f7af6e8d3b0bfb634f9d1ae9ad9c6c7189d4b02e69ed9693f6ca6fe4f0`）。

两次产出的**行为完全一致**，只差局部变量名与引号风格：

```diff
-    normalized_status = status.strip().casefold()
-    if normalized_status not in ("todo", "done"):
+    wanted = status.strip().casefold()
+    if wanted not in ('todo', 'done'):
         raise ValueError("status must be either 'todo' or 'done'")
-        if task.get("status", "todo").casefold() == normalized_status
+        if task.get('status', 'todo').casefold() == wanted
```

`sample/after/task_service.py` 现在是**本轮 WorkBuddy 中运行的 MiniMax 产出**，即上面的 `wanted` 版本；`evidence/minimax-api/20261028T010349Z-task_service.py` 保留更早 API 版本的原始字节。两份记录都真实可核对。

## 已知缺口

- 本轮修改发生在 WorkBuddy 会话内，**没有平台导出的会话文件**。可核对的实物证据是本目录中的：上下文输入文件（含 SHA-256）、模型产出的代码文件、统一差异、以及修改前后的测试日志与退出码；会话原文以 WorkBuddy 的会话记录为准。
- 本轮未额外调用付费 MiniMax API（WorkBuddy 中的 MiniMax 已实际承担代码修改）。
