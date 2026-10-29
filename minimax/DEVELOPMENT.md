# 开发记录

## 本次代码修改：MiniMax API 复核（2026-10-29，v2 上下文）

v2 上下文模块（验证结果绑定版本、失效规格单独列出）完成后，用新的上下文再次让 MiniMax 完成同一修改。最终输出与 2026-10-28 采用的 `sample/after/task_service.py` 逐字节相同（SHA-256 `8b9c31f7af6e8d3b0bfb634f9d1ae9ad9c6c7189d4b02e69ed9693f6ca6fe4f0`），因此该文件未变。

- 接入方式：HTTP，OpenAI 兼容 Chat Completions，`https://api.minimaxi.com/v1/chat/completions`，模型 `MiniMax-M3`，temperature 0.2；入口 `minimax_agent.py`；Key 为参赛 MiniMax Token Plan，由环境变量提供，不写入任何文件。
- 提供的上下文：`evidence/minimax-api/ci-context-before-change-v2.json`，即干净 Linux 环境（GitHub Actions run 40810634417，seekdb 官方镜像 + PowerContext）中 `context-before-change` 步骤的真实输出：`spec.md#TASK-2`（implement）、`spec.md#TASK-1`（preserve）、`work/task_service.py#list_tasks`（工作副本，内容即 `before/` 快照）、功能测试 5 个与回归测试 2 个，以及从 PowerContext 读回的进展：已完成、待办和修改前验证结果（功能测试退出 1、回归测试退出 0，validity=current）。提示中没有任何参考实现。
- 过程（`evidence/minimax-api/20261029T032003Z-exchange.json`）：
  - 第 1 轮（10.5 秒，1625 tokens）：实现了筛选，但对记录中的 status 也做了 strip，`FeatureTests.test_done` 失败。
  - 第 2 轮（2.8 秒，2213 tokens）：助手把失败输出交回 MiniMax，MiniMax 去掉对记录 status 的 strip，7 个测试全部通过。
- 代码差异：`evidence/minimax-api/20261029T032003Z-change.diff`。
- 运行命令：`python minimax_agent.py --context-file evidence/minimax-api/ci-context-before-change-v2.json --output sample/after/task_service.py`；随后 CI 以 `run_demo.py --recorded` 在干净环境中用该输出完成全部流程。

## 本次代码修改：MiniMax API（2026-10-28，首次采用）

最终业务代码 `sample/after/task_service.py` 与 MiniMax 第 2 轮回复中的代码块逐字节相同（SHA-256 `8b9c31f7af6e8d3b0bfb634f9d1ae9ad9c6c7189d4b02e69ed9693f6ca6fe4f0`）。

- 接入方式：HTTP，OpenAI 兼容 Chat Completions，`https://api.minimaxi.com/v1/chat/completions`，模型 `MiniMax-M3`，temperature 0.2；入口 `minimax_agent.py`。
- 提供的上下文：`evidence/minimax-api/ci-context-before-change.json`，即 `run_demo.py` 在干净 Linux 环境（GitHub Actions，seekdb 官方镜像 + PowerContext）中 `context-before-change` 步骤的真实输出：规格条目 `spec.md#TASK-2`（implement）与 `spec.md#TASK-1`（preserve），代码符号 `before/task_service.py#list_tasks`，功能测试 5 个、回归测试 2 个，以及从 PowerContext 读回的进展（已完成：导入资料；待办：由 MiniMax 修改代码、运行测试）。提示中没有任何参考实现。
- 过程（`evidence/minimax-api/20261028T010349Z-exchange.json`，含每轮完整请求、原始回复、代码哈希与测试输出）：
  - 第 1 轮（21.9 秒，1393 tokens）：实现了筛选，但把记录中的 status 也做了 strip，`FeatureTests.test_done` 失败（规格只要求记录 status 做 casefold）。
  - 第 2 轮（4.9 秒，2010 tokens）：助手把失败输出交回 MiniMax，MiniMax 去掉对记录 status 的 strip，7 个测试全部通过。
- 代码差异：`evidence/minimax-api/20261028T010349Z-change.diff`（`before/task_service.py` → MiniMax 输出）。
- 运行方式：本地 Windows 以 `python minimax_agent.py --context-file evidence/minimax-api/ci-context-before-change.json --output sample/after/task_service.py` 调用（API Key 由环境变量提供，不写入任何文件）；随后 CI 以 `run_demo.py --recorded` 在干净环境中用该输出完成修改前后测试、状态保存与复用验证。配置 `MINIMAX_API_KEY` 后，`python run_demo.py` 在同一流程内实时调用 MiniMax。

## 早期网页会话（2026-10-28，未采用为最终代码）

此前队员通过 MiniMax 网页端（`https://agent.minimax.cn/`，M3.1-Flash）进行过一次探路请求和一次正式请求，请求中给出了完整实现描述。记录保留于 `evidence/minimax-request.txt`、`evidence/minimax-response.py`、`evidence/final-change.diff`、`evidence/local-task_service.py`，以说明真实过程；最终业务代码以上面的 API 记录为准。
