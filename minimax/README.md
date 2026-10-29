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
| `python minimax_agent.py --project P --task T --scope S --output F [--evidence-dir D]` | 同上，加输出文件与证据目录 | MiniMax 修改后的文件；`D`（默认 `evidence/minimax-api/`）下的 `<时间>-exchange.json` 与 `-change.diff` |
| `python run_demo.py [--recorded]` | 无 | 完整验证样例；证据写入 `evidence/run/<运行编号>/`，成功时另刷新 `evidence/run/` 根目录的「最近一次成功运行」 |
| `python verify_platform_record.py` | 无 | 由 WorkBuddy 平台改动日志重建本轮 MiniMax 写出的业务代码，并与 `sample/after/task_service.py` 比对（只依赖交付目录内的文件） |
| `python verify_acceptance.py` | 无 | 交付材料一致性自检：按官方六项必做项逐项判定，全部通过退出码 0，任一失败为 1（只依赖交付目录内的文件） |
| `python test_tooling.py` | 无 | 工具自身的单测：生成前/生成后的输出校验、测试执行的字节码隔离、模型失败后的修复循环、就绪探测（503 不得判为就绪），以及验收脚本的负例（损坏的成功归档必须被判失败），共 21 项 |

上下文选择方式：规格按 `## <编号> <标题>` 切分为条目；任务编号对应的条目为 implement，同一规格中的其他条目为 preserve（必须保持的原有行为）；implement 条目中以 `` `name(` `` 引用的函数，在代码符号索引中查到需要修改的文件与行号；调用这些函数的测试用例按测试类分为功能测试与回归测试。规格修改后重新 `ingest`，同一编号的条目随之更新，不返回固定答案。

## 依赖与环境

### 先取得代码

作品在参赛仓库的 `minimax/` 目录下，评审按官方说明克隆仓库后再进入该目录：

```bash
git clone --branch 2026-competition-ecosystem https://<你的用户名>:<你的访问令牌>@github.com/caibolol/ODC_PowerContext.git
cd ODC_PowerContext/minimax
```

（私有仓库的访问方式见官方《GitHub 在大赛中的使用说明》。克隆后可用 `git rev-parse HEAD`
确认拿到的提交；下文所有命令都在 `minimax/` 目录下执行。）

已验证：Ubuntu 24.04（GitHub Actions 与本机实测）、Ubuntu 22.04、WSL2、Windows；Python 3.11 / 3.12；PyMySQL 1.2.0；seekdb 官方镜像 `oceanbase/seekdb:latest`（本次实测 digest `sha256:4db4961869d554313520d6081fca29265ba6da6db7313311bd8acbed771a956b`，容器路径与原生二进制路径都跑通）；PowerContext 取自官方公开仓库 `https://github.com/oceanbase/powercontext.git`，固定在提交 `dab240063bfcfa7917898dc44da4baadb3747bd0`（该提交位于 `2026-competition` 分支上），通过 HTTP API 使用；MiniMax OpenAI 兼容 Chat Completions，模型 `MiniMax-M3`。

> PowerContext 从**官方公开仓库**安装，评审在干净环境无需任何私有凭据即可完成安装。
> 安装命令直接固定到提交号，而不是分支名——分支会前进，固定提交才能保证评审装到的版本与本次验证的一致。

### Linux（推荐，与评审的干净环境一致）

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@dab240063bfcfa7917898dc44da4baadb3747bd0"
docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
export POWERCONTEXT_HOME=$(mktemp -d)        # 空的 PowerContext 状态
powercontext server run --no-env-file --host 127.0.0.1 --port 18752 &
export DB_HOST=127.0.0.1 DB_PORT=2881 DB_USER=root DB_PASSWORD= DB_NAME=minimax_sdd PC_URL=http://127.0.0.1:18752
python run_demo.py --recorded                 # 不调用 MiniMax，使用仓库中记录的 MiniMax 输出
export MINIMAX_API_KEY=<你的 MiniMax API Key>  # 占位值；可选 MINIMAX_MODEL、MINIMAX_BASE_URL
python run_demo.py                            # 实时调用 MiniMax 完成修改
```

> **Python 版本**（Ubuntu 上两种情况都会撞到）：
> - Ubuntu 22.04 自带的 `python3` 是 **3.10**，低于 PowerContext 要求的 3.11，直接 `python3 -m venv` 装不上。
>   改用 `python3.12 -m venv .venv`，或 `apt-get install python3.12`，或
>   `uv python install 3.12 && uv venv --python 3.12 --seed .venv`（`--seed` 必须加，
>   否则 uv 建的 venv 里没有 `pip`）。
> - Ubuntu 24.04 的 `python3` 是 3.12，但**默认不带 `ensurepip`**，`python3 -m venv` 会报
>   `ensurepip is not available`。此时 `apt-get install python3.12-venv`，或同样用上面的 uv 方式。
>
> 本次验证覆盖：Ubuntu 22.04 + Python 3.11.18 与 3.12.16、Ubuntu 24.04 + Python 3.12.16、
> Windows + Python 3.12.2，均全部通过。**上面的 Docker 路径本身也已实测**（WSL2 / Ubuntu 24.04，
> Docker Engine 29.1.3，官方镜像 digest 与本文记录一致），见 `evidence/run/docker-environment.txt`。
>
> **若 `docker pull` 报 `TLS handshake timeout`**：`dockerd` 不继承 shell 的 `http_proxy`，
> 需要给 daemon 单独配（把端口换成实际代理端口；没有代理的环境不需要这一步）：
>
> ```bash
> mkdir -p /etc/systemd/system/docker.service.d
> cat > /etc/systemd/system/docker.service.d/http-proxy.conf <<'EOF'
> [Service]
> Environment="HTTP_PROXY=http://127.0.0.1:7897"
> Environment="HTTPS_PROXY=http://127.0.0.1:7897"
> Environment="NO_PROXY=localhost,127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"
> EOF
> systemctl daemon-reload && systemctl restart docker
> ```

seekdb 冷启动需要数秒到数十秒（容器内更久）。`run_demo.py` 第一步是 `wait-services`：先轮询等待 seekdb 与 PowerContext 就绪（默认最多 180 秒，可用环境变量 `DEMO_WAIT_TIMEOUT` 调整），就绪后才开始后面的步骤，因此**不需要手工等待或重试**。该等待也会作为一步记录在 `evidence/run/steps.json` 里。

> 若 `pip install` 报 `Could not find a version that satisfies ... (from versions: none)`，多半是本机 pip 镜像源临时不可用（同一版本用 `pip index versions` 往往能列出来）。改用官方源即可：
> `pip install --index-url https://pypi.org/simple --no-cache-dir -r requirements.txt`（PowerContext 那条同理）。

#### 没有 Docker 时：用官方 seekdb 二进制

seekdb 官方发布了 Linux 二进制，可替代上面的容器（本次在 Ubuntu 22.04 上按此路径跑通）：

```bash
# 1) 取官方二进制（Ubuntu 22.04 amd64；24.04 用 ubuntu24.04 那份，其他发行版见 releases 页）
curl -L -o seekdb.deb https://github.com/oceanbase/seekdb/releases/download/v1.4.0/seekdb_1.4.0-100000212026082616ubuntu22.04_amd64.deb
dpkg-deb -x seekdb.deb ./seekdb_pkg
# 2) seekdb 需要 libaio：22.04 是 libaio.so.1，24.04 是 libaio.so.1t64（time64 迁移版）。
#    没有 sudo 时可同样解包官方包并用 LD_LIBRARY_PATH 提供（下面以 22.04 为例，24.04 换成 libaio1t64_*）
curl -L -o libaio1.deb http://archive.ubuntu.com/ubuntu/pool/main/liba/libaio/libaio1_0.3.112-13build1_amd64.deb
dpkg-deb -x libaio1.deb ./libaio_pkg
export LD_LIBRARY_PATH="$PWD/libaio_pkg/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
# 3) 起服务（其余环境变量同上，把 DB_PORT 改成实际端口）
./seekdb_pkg/usr/bin/seekdb --nodaemon --base-dir "$PWD/seekdb-data" --port 2881 \
  --parameter memory_limit=4G --parameter log_disk_size=2G --parameter datafile_size=2G &
```

> 有 sudo 时更简单：`apt-get install -y libaio1`（24.04 上是 `libaio1t64`）。
> 本次 Linux 验证即按上面的免 root 方式在 Ubuntu 22.04 与 Ubuntu 24.04 上分别跑通。

`.github/workflows/minimax-demo.yml`（开发分支 `claude/minimax`）按同样步骤在干净的 GitHub Actions 环境执行。

### Windows

按 `start-seekdb.ps1`（原生 seekdb 二进制）与 `start-powercontext.ps1` 启动服务，连接变量默认 `DB_PORT=18753`、`PC_URL=http://127.0.0.1:18752`，其余命令相同（激活脚本为 `.venv/Scripts/Activate.ps1`）。`requirements-windows-lock.txt` 为 Windows/Python 3.12 完整依赖锁定，其中 PowerContext 同样固定在官方公开仓库的提交 `dab240063bfcfa7917898dc44da4baadb3747bd0`，评审在干净环境无需任何私有凭据。

`start-seekdb.ps1` 的 `-SeekdbExe` 是必填参数，需指向 `seekdb.exe`（可用 `-Port` 改端口，默认 18753）：

```powershell
.\start-seekdb.ps1 -SeekdbExe D:\path\to\seekdb.exe
```

未传该参数时 PowerShell 会报「强制参数缺失: SeekdbExe」。
Windows 版 seekdb 二进制可从 <https://github.com/oceanbase/seekdb/releases> 取对应安装包，
或按官方源码编译；本次验证用的是自行编译的 1.4.0（`seekdb.exe`）。
若评审环境没有 Docker，Linux 下也可用上面的「官方 seekdb 二进制」路径，两者等价。

## 验证样例

任务 TASK-2：给 `list_tasks(tasks, status=None)` 增加 todo/done 筛选（规格 `sample/spec.md#TASK-2`），同时保持 TASK-1 原有行为：不筛选时返回全部任务的副本、保持顺序、不修改输入（`sample/spec.md#TASK-1`）。

上下文必须包含：

- 规格：`spec.md#TASK-2`（implement）、`spec.md#TASK-1`（preserve）
- 代码：`before/task_service.py#list_tasks`
- 测试：功能测试 `FeatureTests` 的 5 个用例；回归测试 `RegressionTests` 的 2 个用例（`sample/test_task_service.py`）
- 进展：PowerContext 中该任务最新的已完成、待办与验证结果

`run_demo.py` 的步骤（每步一个新进程，即模块重启）：导入 → 新 scope 空状态 → 保存起始进展 → 修改前测试（目标功能测试因行为未实现而断言失败，回归测试通过）→ 重启后读取进展并交给 MiniMax → 修改后同一组功能与回归测试全部通过 → 保存验证结果 → 重启后上下文包含该结果 → 追加规格并重新导入后上下文使用新内容。断言任一不满足即以非零退出码结束。

重置：每次运行使用新的项目 ID 与 scope，样例在临时副本中修改，仓库文件不变；需要完全清空时删除 seekdb 中的 `minimax_sdd` 库并使用新的 `POWERCONTEXT_HOME`。

证据与快照的写入规则：

- **交付的业务快照是固定的**：`sample/after/task_service.py` 是本次采用的业务代码，**实时复跑不会覆盖它**。实时调用 MiniMax 得到的代码存进该次运行的证据目录 `evidence/run/<运行编号>/task_service.py`，MiniMax 的交互记录存进同一目录。
- **失败不破坏已有成功证据**：每次运行的 `steps.json` / `summary.json` / `context-*.json` 都写在 `evidence/run/<运行编号>/` 下；只有该次运行成功时，才会把它们复制到 `evidence/run/` 根目录作为「最近一次成功运行」。失败运行的 `summary.json` 里 `result` 为 `FAIL`。
- 评审自行复跑后会在 `evidence/run/` 下多出新的运行编号目录，属正常现象。

原有脚本 `verify_sample.py`（修改前后快照、同一测试文件）与 `verify_context.py`（导入、规格更新、状态复用）仍可单独运行；`verify_platform_record.py`（平台改动日志与提交代码比对）、`verify_acceptance.py`（六项必做项一致性自检）与 `test_tooling.py`（工具自身单测）也可单独运行。

`verify_acceptance.py` 会对**每一份**声明「成功且为实时调用」的归档逐份核对：首轮请求的提示必须等于该次 `context-before-change` 构造出的提示，每轮的 `code_sha256` 必须能由回复里的代码复算出来，`exchange.after_sha256` 与运行摘要的 `after_sha256` 都是**必需字段**（缺失、为 None 或空串都判失败），末轮回复代码、这两个摘要、归档里的 `task_service.py` 必须互相对应，并且要能把归档产出放进交付的那份测试文件里实跑通过。任何一个环节对不上都会指名道姓地报出是哪一次运行、哪一处不一致——旧的成功记录不会掩盖较新归档的损坏。

有一类记录是**合法**的：模型某一轮只回了文字、没有给代码块（`code_sha256` 明确记为 `None`），失败输出交回模型后下一轮修正成功。这种归档只要末轮有有效代码、摘要、产出且测试通过，就会被接受；反过来，有代码却缺摘要、摘要为 `None`（而不是字段缺失）、或末轮没有代码，都会被拒绝。

## 证据目录

| 路径 | 内容 |
| --- | --- |
| `evidence/run/` | 每次 `run_demo.py` 的完整步骤日志与上下文输出。**每次运行的证据存在 `evidence/run/<运行编号>/` 下**；`evidence/run/` 根目录是最近一次成功运行的副本（当前为实时调用运行 `78fbec8ada1e`）。**只有成功**的运行才会刷新根目录，失败运行不会破坏已有成功证据。已跑过的环境：Windows 全新 venv（`5b3abb06746b` 等）、Windows 从零重装（`3729a7adf522`、`2e8d57635521`）、**Docker 容器路径（`3107b6f350ab`、`f6d579e0f14e`，官方镜像 `oceanbase/seekdb:latest`）**、**实时调用（`5b3abb06746b`、`2e8d57635521`、`bd8dc0ba1dce`、`0a8e51dde0b5`、`78fbec8ada1e`）**、**Linux / WSL2 全新克隆（Ubuntu 22.04：`a0e4dce9e43f`、`e652ce859b41` 等；Ubuntu 24.04：`9d19b43b0b8c`；用官方 seekdb 1.4.0 Linux 二进制，其中 `bd8dc0ba1dce` 是 Linux 上的实时调用）**。Python 3.11.18 / 3.12.x 均验证通过。`pip-freeze.txt` 为 Windows 实际依赖，`pip-freeze-linux.txt` / `pip-freeze-docker.txt` 为 Linux / Docker 实际依赖，`seekdb-build.txt` / `linux-environment.txt` / `docker-environment.txt` 为实际使用的 seekdb 版本与启动参数，`acceptance-check.txt` / `acceptance-check-docker.txt` 为 `verify_acceptance.py` 的判定输出 |
| `evidence/workbuddy-minimax/` | 本轮由 WorkBuddy 中运行的 MiniMax（M3.1 Flash）产出最终业务代码的完整开发记录：送入的上下文、产出的代码、统一差异、修改前后测试日志、PowerContext 写入与跨服务重启读回；`platform-record/` 为 WorkBuddy 平台自己生成的会话元数据（模型 ID `minimax-m3.1-flash`）与改动日志 |
| `evidence/minimax-api/` | 更早一次独立 MiniMax API 调用（模型 `MiniMax-M3`）的真实交互记录与产出代码 |
| `evidence/reinstall/` | 一次**从零重装**验证的记录：删除旧虚拟环境后按 README 命令从公开源重装、全新数据库与全新 PowerContext 状态目录，各入口与实时调用的结果，以及环境快照与完整依赖 |
| `evidence/linux-ci/` | 更早一次 Ubuntu 24.04 + seekdb 官方镜像的干净环境运行证据 |
| `evidence/clean-environment/` | 队员在另一台干净 Windows 机器上的独立复验记录 |
| `evidence/minimax-request.txt`、`evidence/minimax-response.py`、`evidence/final-change.diff`、`evidence/local-task_service.py` | 最早的 MiniMax 网页端会话记录 |

## 已知限制

- 规格条目以二级标题编号识别，代码符号与测试用例解析面向 Python。
- 单个项目的导入应串行执行；连接用户需要建库建表权限。
- MiniMax 每次生成的代码不必完全相同；仓库保存的是本次实际采用的输出与完整交互记录。
- 本轮 MiniMax 修改发生在 WorkBuddy 会话内。WorkBuddy 没有整段会话的导出功能，因此没有"平台导出的完整对话文件"；但平台自己生成的改动日志（`evidence/workbuddy-minimax/platform-record/`）逐行保存了本轮写出的业务代码，`python verify_platform_record.py` 可复核其与提交文件逐字节一致。
- `evidence/linux-ci/pip-freeze-linux.txt` 与 `evidence/workbuddy-minimax/platform-record/changes-*.json` 里能看到队伍私有仓库地址 `caibolol/ODC_PowerContext`：前者是那次 Linux CI 运行的历史记录，后者是平台改动日志中「修改前」那一侧的原文。二者都是历史记录，不是当前安装依赖——当前 `requirements*.txt` 与 README 的安装命令都指向官方公开仓库，`verify_acceptance.py` 会检查这一点。
- 评审环境若设置了 `http_proxy` / `HTTPS_PROXY`，`context.py` 与 `run_demo.py` 对本机 PowerContext 的请求一律直连（绕过代理），避免代理不转发 localhost 时连接失败。
- `minimax_agent.py` 与 `run_demo.py` 写入的 MiniMax 交互记录**已脱敏**：回复中的模型私有思维链段落（think 标签包裹）被替换为占位说明，不随作品提交；响应 ID、usage、生成的代码与测试结果原样保留。`verify_acceptance.py` 会检查交付副本中不含该类标记。

技术说明见 [TECHNICAL.md](TECHNICAL.md)，开发记录见 [DEVELOPMENT.md](DEVELOPMENT.md)，验收项与证据对照见 [ACCEPTANCE.md](ACCEPTANCE.md)。
依赖来源：[PowerContext](https://github.com/oceanbase/powercontext)、[seekdb](https://github.com/oceanbase/seekdb)、[PyMySQL](https://github.com/PyMySQL/PyMySQL)；样例业务代码为本次编写。
