# SDD 任务上下文模块（MiniMax × seekdb × PowerContext）

为 AI 开发助手提供“当前有效的规格、要改的代码、要跑的测试和任务进展”，并用 MiniMax 完成一次实际代码修改。

| 技术 | 在流程中的作用 |
| --- | --- |
| seekdb | `sdd_sources` 保存规格、代码、测试原文与 SHA-256；`sdd_entries` 保存规格条目、代码符号、测试用例索引。`context` 的全部结果来自对这两张表的参数绑定查询 |
| PowerContext | `/v1/scopes` 建立任务边界，`/v1/memory/remember` 保存任务进展与验证结果，`/v1/memory/entries/list` 在模块重启后读回，作为下一次上下文的 `progress` |
| MiniMax | `minimax_agent.py` 把上下文交给 MiniMax Chat Completions（`https://api.minimaxi.com/v1`，模型 `MiniMax-M3`），写入其返回的代码；测试失败时把失败输出交回 MiniMax 继续修改 |

## 调用入口（CLI）

| 命令 | 输入 | 输出 |
| --- | --- | --- |
| `python context.py ingest --project P --manifest M` | 清单（来源路径、类别 spec/code/test、关联任务） | 导入的来源数、索引条目数 |
| `python context.py scope --key K` | 幂等键 | PowerContext `scope_id` |
| `python context.py context --project P --task T --scope S` | 项目、任务、scope | JSON：`spec_entries`（implement / preserve，含行号与正文）、`code_targets`（文件、符号、行号）、`tests`（功能 / 回归测试用例）、`progress`（已完成、待办、已有验证结果）、`sources`、`query`（实际执行的 SQL、参数、行数） |
| `python context.py save --scope S --state F` | 任务状态 JSON（`task`、`completed`、`todo`、`tests`） | PowerContext 写入结果 |
| `python minimax_agent.py --project P --task T --scope S --output F` | 同上，加输出文件 | MiniMax 修改后的文件；`evidence/minimax-api/<时间>-exchange.json` 与 `-change.diff` |
| `python run_demo.py [--recorded]` | 无 | 完整验证样例；`evidence/run/` 下的步骤日志与上下文 |

上下文选择方式：规格按 `## <编号> <标题>` 切分为条目；任务编号对应的条目为 implement，同一规格中的其他条目为 preserve（必须保持的原有行为）；implement 条目中以 `` `name(` `` 引用的函数，在代码符号索引中查到需要修改的文件与行号；调用这些函数的测试用例按测试类分为功能测试与回归测试。规格修改后重新 `ingest`，同一编号的条目随之更新，不返回固定答案。

## 依赖与环境

已验证：Ubuntu 24.04（GitHub Actions）与 Windows；Python 3.12；PyMySQL 1.2.0；seekdb 官方镜像 `oceanbase/seekdb:latest`（本次 digest `sha256:4db4961869d554313520d6081fca29265ba6da6db7313311bd8acbed771a956b`）；PowerContext 源码提交 `da0cb9c2e945d6363725b3abfc4f40a854bf9d29`（HTTP API）；MiniMax OpenAI 兼容 Chat Completions，模型 `MiniMax-M3`。

### Linux（推荐，与评审的干净环境一致）

```bash
cd minimax
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install "powercontext[cli,server] @ git+https://github.com/caibolol/ODC_PowerContext.git@da0cb9c2e945d6363725b3abfc4f40a854bf9d29"
docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
export POWERCONTEXT_HOME=$(mktemp -d)        # 空的 PowerContext 状态
powercontext server run --no-env-file --host 127.0.0.1 --port 18752 &
export DB_HOST=127.0.0.1 DB_PORT=2881 DB_USER=root DB_PASSWORD= DB_NAME=minimax_sdd PC_URL=http://127.0.0.1:18752
python run_demo.py --recorded                 # 不调用 MiniMax，使用仓库中记录的 MiniMax 输出
export MINIMAX_API_KEY=<你的 MiniMax API Key>  # 占位值；可选 MINIMAX_MODEL、MINIMAX_BASE_URL
python run_demo.py                            # 实时调用 MiniMax 完成修改
```

seekdb 启动需要约 1 分钟，`run_demo.py` 第一步连接失败时稍候重试。`.github/workflows/minimax-demo.yml`（开发分支 `claude/minimax`）按同样步骤在干净的 GitHub Actions 环境执行。

### Windows

按 `start-seekdb.ps1`（原生 seekdb 二进制）与 `start-powercontext.ps1` 启动服务，连接变量默认 `DB_PORT=18753`、`PC_URL=http://127.0.0.1:18752`，其余命令相同（激活脚本为 `.venv/Scripts/Activate.ps1`）。`requirements-windows-lock.txt` 为 Windows/Python 3.12 完整依赖锁定。

## 验证样例

任务 TASK-2：给 `list_tasks(tasks, status=None)` 增加 todo/done 筛选（规格 `sample/spec.md#TASK-2`），同时保持 TASK-1 原有行为：不筛选时返回全部任务的副本、保持顺序、不修改输入（`sample/spec.md#TASK-1`）。

上下文必须包含：

- 规格：`spec.md#TASK-2`（implement）、`spec.md#TASK-1`（preserve）
- 代码：`before/task_service.py#list_tasks`
- 测试：功能测试 `FeatureTests` 的 5 个用例；回归测试 `RegressionTests` 的 2 个用例（`sample/test_task_service.py`）
- 进展：PowerContext 中该任务最新的已完成、待办与验证结果

`run_demo.py` 的步骤（每步一个新进程，即模块重启）：导入 → 新 scope 空状态 → 保存起始进展 → 修改前测试（目标功能测试因行为未实现而断言失败，回归测试通过）→ 重启后读取进展并交给 MiniMax → 修改后同一组功能与回归测试全部通过 → 保存验证结果 → 重启后上下文包含该结果 → 追加规格并重新导入后上下文使用新内容。断言任一不满足即以非零退出码结束。

重置：每次运行使用新的项目 ID 与 scope，样例在临时副本中修改，仓库文件不变；需要完全清空时删除 seekdb 中的 `minimax_sdd` 库并使用新的 `POWERCONTEXT_HOME`。

原有脚本 `verify_sample.py`（修改前后快照、同一测试文件）与 `verify_context.py`（导入、规格更新、状态复用）仍可单独运行。

## 已知限制

- 规格条目以二级标题编号识别，代码符号与测试用例解析面向 Python。
- 单个项目的导入应串行执行；连接用户需要建库建表权限。
- MiniMax 每次生成的代码不必完全相同；仓库保存的是本次实际采用的输出与完整交互记录。

技术说明见 [TECHNICAL.md](TECHNICAL.md)，开发记录见 [DEVELOPMENT.md](DEVELOPMENT.md)，验收项与证据对照见 [ACCEPTANCE.md](ACCEPTANCE.md)。
依赖来源：[PowerContext](https://github.com/oceanbase/powercontext)、[seekdb](https://github.com/oceanbase/seekdb)、[PyMySQL](https://github.com/PyMySQL/PyMySQL)；样例业务代码为本次编写。
