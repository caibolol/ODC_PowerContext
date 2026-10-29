# 开发记录

本作品有**两份真实**的 MiniMax 开发记录，均可核对：

| 记录 | 模型 / 接入方式 | 产出的代码 | 证据 |
| --- | --- | --- | --- |
| **本轮（最终采用）** | WorkBuddy 宿主中运行的 MiniMax M3.1 Flash，模型直接读入会话 | `sample/after/task_service.py` | `evidence/workbuddy-minimax/` |
| 更早一次（保留） | 独立 MiniMax API 调用，模型 `MiniMax-M3`，OpenAI 兼容 Chat Completions | `evidence/minimax-api/20261028T010349Z-task_service.py` | `evidence/minimax-api/` |

两次产出的**行为完全一致**，只差局部变量名与引号风格；最终业务代码采用本轮 WorkBuddy 的产出。

## 一、本轮：WorkBuddy 中的 MiniMax 完成代码修改（最终采用）

完整记录见 **[evidence/workbuddy-minimax/README.md](evidence/workbuddy-minimax/README.md)**。要点：

- **宿主与模型**：WorkBuddy 开发助手宿主，模型为 WorkBuddy 界面中当前选择的 MiniMax M3.1 Flash。
- **本次任务**：`TASK-2` —— 为 `list_tasks(tasks, status=None)` 增加 todo/done 筛选，同时保持 `TASK-1` 的原有行为。
- **提供的上下文**：`evidence/workbuddy-minimax/context-before-change.json`（SHA-256 `74f2d5c5cc23f5869c5fbed42c926011d98fb41102f965a5772df46b458bdd2c`），即 `context.py context` 的真实输出，含 implement / preserve 规格条目、`before/task_service.py#list_tasks` 符号、功能测试 5 项与回归测试 2 项、以及从 PowerContext 读回的进展；另含 5 条 seekdb 查询的 SQL、参数与返回行数。上下文中不含任何参考实现。
- **产出**：`sample/after/task_service.py`，SHA-256 `fc7ab99516ea1a020618687592277247e51ad1033296b9a2e29bf408cb8a88c4`；差异 `evidence/workbuddy-minimax/change.diff`。
- **修改前后同组测试**：功能测试修改前 `FAILED (failures=5)`（退出码 1，断言失败），修改后 `OK`（退出码 0）；回归测试前后均 `OK`，两份回归日志逐字节相同（SHA-256 `467ba065cd858b5e033cbfdee32c2a6e4c7cd0d2c9cd13bd2af867a36c0a0b9a`）。测试文件未被修改（SHA-256 `2c01d2de7e49987f1ead4e38a0916f4a7f3bae40dcfcf701d24a171435f899a7`）。
- **状态复用**：新建 scope 为空 → 写入进展 → 新进程读回 → 写入验证结果 → **杀掉 PowerContext 服务进程后重启服务**再读回，`completed` 3 项、`todo` 空、`verification` 2 组。

## 二、更早一次：独立 MiniMax API 调用（保留）

- 接入方式：HTTP，OpenAI 兼容 Chat Completions，`https://api.minimaxi.com/v1/chat/completions`，模型 `MiniMax-M3`，temperature 0.2；入口 `minimax_agent.py`。API Key 由环境变量提供，未写入任何文件。
- 提供的上下文：`evidence/minimax-api/ci-context-before-change.json`，即 `run_demo.py` 在干净 Linux 环境（GitHub Actions，seekdb 官方镜像 + PowerContext）中 `context-before-change` 步骤的真实输出。
- 过程（`evidence/minimax-api/20261028T010349Z-exchange.json`，含每轮完整请求、回复、代码哈希与测试输出）：
  - 第 1 轮（21.9 秒，1393 tokens）：实现了筛选，但把记录中的 status 也做了 strip，`FeatureTests.test_done` 失败（规格只要求记录 status 做 casefold）。
  - 第 2 轮（4.9 秒，2010 tokens）：助手把失败输出交回 MiniMax，MiniMax 去掉对记录 status 的 strip，7 个测试全部通过。
- **该文件是脱敏后的交付副本**：回复中的模型私有思维链段落（think 标签包裹）已替换为占位说明，未随作品提交；每轮的响应 ID（`07307cf6…`、`07307d0c…`）、`usage`（含 prompt/completion/reasoning tokens）、生成的代码块与测试结果原样保留，文件顶部的 `_redaction` 字段写明了脱敏范围与被移除的字符数（2283）。因此它**不是未经处理的完整原始回复**，只是可核对的交付副本。
  `minimax_agent.py` 现在写出交互记录时会自动做同样的脱敏，后续实时运行不会再把思维链写进仓库。
- 代码差异：`evidence/minimax-api/20261028T010349Z-change.diff`；该版本的完整文件另存为 `evidence/minimax-api/20261028T010349Z-task_service.py`（SHA-256 `8b9c31f7af6e8d3b0bfb634f9d1ae9ad9c6c7189d4b02e69ed9693f6ca6fe4f0`）。
- 运行方式：`python minimax_agent.py --context-file evidence/minimax-api/ci-context-before-change.json --output <输出路径>`。配置 `MINIMAX_API_KEY` 后，`python run_demo.py` 可在同一流程内实时调用 MiniMax；本次运行的证据会写在 `evidence/run/<运行编号>/` 下，不会覆盖交付的业务快照。

## 三、最早的网页会话（未采用为最终代码）

此前队员通过 MiniMax 网页端（`https://agent.minimax.cn/`，M3.1-Flash）进行过一次探路请求和一次正式请求，请求中给出了完整实现描述。记录保留于 `evidence/minimax-request.txt`、`evidence/minimax-response.py`、`evidence/final-change.diff`、`evidence/local-task_service.py`，以说明真实过程。

## 四、平台原始记录与缺口说明

本轮修改发生在 WorkBuddy 会话内。WorkBuddy **自己生成**的改动日志已逐字导出到 `evidence/workbuddy-minimax/platform-record/`：

- `session.json`：WorkBuddy 本地数据库 `sessions` / `session_usage` 表原行，记录本会话的模型 ID 为 **`minimax-m3.1-flash`**、工作目录、创建时间与上下文用量。
- `changes-<requestId>.json`：平台变更日志原文件，记录本轮每次模型请求驱动下写过的每一个文件及其 unified-diff hunks，其中 `task_service.py` 的 hunk 逐行保存了本轮 MiniMax 写出的代码。

由该 hunk 重建的文件 SHA-256 为 `fc7ab99516ea1a020618687592277247e51ad1033296b9a2e29bf408cb8a88c4`，与提交的 `sample/after/task_service.py` 逐字节一致。评审可自行复核：

```bash
python verify_platform_record.py     # 只依赖交付目录内的文件
```

**缺口**：平台改动日志记录的是文件改动（含逐行 diff），不是模型的消息原文；WorkBuddy 未提供整段会话的导出功能，因此没有"平台导出的完整对话文件"。模型私有思维链不提交——交付的 API 交互记录已脱敏（见第二节）。本轮未额外调用付费 MiniMax API。
