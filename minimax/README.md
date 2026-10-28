# SDD 任务上下文模块

输入为项目 ID、任务 ID、来源清单和 PowerContext scope ID；输出为数据库中真实的规格、代码、测试内容、来源路径、SHA-256 和恢复的任务状态。入口为 `context.py`。

## 当前验证结果

本地独立实现已完成：相同的 7 项测试在修改前因状态筛选未实现而失败（5 个失败断言），修改后全部通过。真实 seekdb 导入、查询、规格更新重导入、PowerContext 从空状态保存和跨进程读取均已验证。

MiniMax 正式阶段已完成：先独立完成本地实现，再将完整实现的自然语言描述、数据库上下文和任务要求提供给 MiniMax，原样采用其返回的业务文件并通过同组7项测试。正式阶段一次请求，网页显示11秒。此前探路请求的扩展版代码未采用。详见 DEVELOPMENT.md。新虚拟环境、独立源码副本、空数据库和空PowerContext状态的完整复现也已通过。官方逐项材料索引与复现记录见 [ACCEPTANCE.md](ACCEPTANCE.md)。平台分数以实际评审为准。

## 依赖与启动

验证环境：Windows、Python 3.12.10、PyMySQL 1.2.0、原生 seekdb 1.4.0.0（`bef66ef2f6dc7b6c046a9af9daafa9b811a9c401`）、PowerContext 源码 `da0cb9c2e945d6363725b3abfc4f40a854bf9d29`。PowerContext 安装版本元数据为 `0.1.dev1+g9db175343`，实际为该源码目录的 editable 安装。项目仅使用公开 HTTP 接口，无推理模型依赖。

以下命令均在本目录执行。seekdb 二进制由官方构建或从 OceanBase seekdb 对应源码构建获得；数据库服务可以部署在其他机器，配置连接地址即可，无需比赛作者的本地数据。

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
pip install -r requirements.txt
pip install "powercontext[cli,server] @ git+https://github.com/caibolol/ODC_PowerContext.git@da0cb9c2e945d6363725b3abfc4f40a854bf9d29"
# 在独立终端各启动一个服务
./start-seekdb.ps1 -SeekdbExe <seekdb.exe的绝对路径>
./start-powercontext.ps1
```

也可按 PowerContext 官方说明先安装对应源码，再在该环境安装 requirements.txt。服务启动需要约数 GB 内存；PowerContext 默认 SQLite 存储任务状态，工程资料存入真实 seekdb。

Windows/Python 3.12 的已验证完整依赖版本另存为 requirements-windows-lock.txt，可用 `pip install -r requirements-windows-lock.txt` 代替上面的两条依赖安装命令。固定PowerContext源码位于参赛仓库的另一分支历史，拉取时使用有该仓库读取权限的GitHub账号；不需要作者的本地源码目录。

连接变量：`DB_HOST=127.0.0.1`、`DB_PORT=18753`、`DB_USER=root`、`DB_PASSWORD=`、`DB_NAME=minimax_sdd`、`PC_URL=http://127.0.0.1:18752`，可选 `PC_TOKEN`。仅开发机回环地址使用无认证默认配置。凭据通过环境变量提供。

## 样例与复现

```powershell
python verify_sample.py
python verify_context.py
```

第一条验证业务修改前后快照，记录完全相同的测试文件哈希、代码哈希、命令和退出码。第二条从新项目、新 scope、空状态开始，验证真实数据库和状态复用，每次 CLI 都启动新进程。测试生成的临时规格文件在进程结束后清理，仓库中的原始规格不变。每次重跑使用唯一项目和 scope，无需删除既有数据。

手动操作：

```powershell
python context.py ingest --project taskboard --manifest sample/manifest.json
python context.py scope --key my-independent-sdd-demo
# 将上一条返回的 scope_id 填入下面命令
python context.py context --project taskboard --task TASK-2 --scope <scope_id>
python context.py save --scope <scope_id> --state <任务状态JSON文件>
# 退出程序再执行 context，previous_state 包含已保存的任务进展。
```

任务状态 JSON 使用 `task`、`completed`、`todo`、`tests` 字段；示例见 evidence/context-restored.json 中 previous_state.entries 的 text。首次 scope 创建时使用自己的独立样例键，同一样例后续重用返回的 scope ID。

更新 `sample/spec.md` 后重新 ingest，下一次 context 使用更新内容。清单中路径相对清单目录，任务关联显式声明；未知任务报错，不返回固定示例答案。

## 验证任务

任务 TASK-2 给 `list_tasks(tasks, status=None)` 增加 todo/done 筛选。有效规格为 `sample/spec.md#TASK-2`，原有行为为 TASK-1；修改符号为 `sample/before/task_service.py::list_tasks`，最终本地实现为 `sample/after/task_service.py`；功能和回归测试在 `sample/test_task_service.py`。测试文件在两个版本之间保持一致。

示例输入 `[{'id':1},{'id':2,'status':'DONE'}]`，筛选 `' done '` 返回第二条，筛选 todo 返回第一条，不传筛选返回全部任务的列表副本。无效筛选即使输入为空也抛 ValueError。输入记录的 status（若存在）应为字符串；筛选参数为字符串或 None。

## 一页技术说明

1. `ingest` 读取清单内真实文件，验证路径，计算哈希，然后事务替换该项目的 seekdb 索引。删除的来源不会残留在下一轮结果中。
2. `context` 参数绑定查询项目记录，再按清单 task ID 选择相关来源；显式任务映射适合小型可验收工程，没有使用向量模型。查询文本、参数及实际行数随输出保存。
3. PowerContext 使用 `/v1/scopes` 建立独立样例边界，`/v1/memory/remember` 保存进展，`/v1/memory/entries/list` 恢复状态。恢复值直接进入下一轮开发上下文。
4. MiniMax 已通过官方网页端接收完整实现描述、实际检索上下文和验收要求，生成最终业务代码。正式输入、原始回复、代码差异和后续测试均已保留，正式请求为一次。

证据：`evidence/tests.json`、`evidence/integration.json`、`evidence/context-initial.json`、`evidence/context-restored.json`、`evidence/state-write.json`、`evidence/minimax-request.txt`、`evidence/minimax-response.py`、`evidence/final-change.diff`。本地先行实现另存于 `evidence/local-task_service.py`。这些是本地运行证据，不是平台评分。

限制：单项目导入应串行执行；来源按任务映射选择，没有语义召回；不处理任意语言的符号解析；已配置用户需具备建库建表权限。未实施网站或完整 Agent 框架。

依赖来源：[PowerContext](https://github.com/oceanbase/powercontext)、[seekdb](https://github.com/oceanbase/seekdb)、[PyMySQL](https://github.com/PyMySQL/PyMySQL)。本目录的模块和合成任务样例为本次编写，未复制第三方业务代码。
