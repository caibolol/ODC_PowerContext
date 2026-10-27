# 记忆侦探：三扇数据库之门

玩家通过三个数据库谜题打开档案室。提示会扣分，错误答案保留作答记录，关闭应用后可用同一代号继续。Dify 负责整个回合的规则与编排，seekdb 实际保存玩家进度、分数、答案历史和版本号。

本作品是确定性规则游戏，不调用大模型，不需要模型密钥。它以可验证的线索匹配实现判题，不宣称具有开放问答能力。

## 运行环境与初始化

本次验证环境是 Windows + Node.js 24.19.0、原生 seekdb 1.4.0，以及 Docker Desktop 中的官方 Dify 1.18.0。Dify 自身使用其官方 PostgreSQL/Redis 等基础服务；seekdb 单独承载本游戏的存档表，不将它描述为 Dify 的内部数据库。游戏无需模型、Embedding/Rerank 服务或插件。Node.js 20 以上可安装配套依赖。

先获取 [Dify 官方 1.18.0](https://github.com/langgenius/dify/tree/1.18.0)：`git clone --branch 1.18.0 --depth 1 https://github.com/langgenius/dify.git dify-runtime`。进入 `dify-runtime/docker`，复制 `.env.example` 为 `.env`，按该版本官方配置说明设置本地凭据。将 `EXPOSE_NGINX_PORT` 设置为 `127.0.0.1:18744`，将 `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` 设置为 `host.docker.internal`。运行 `docker compose up -d`，打开 `http://127.0.0.1:18744/install` 完成自己的本地账号初始化。详细依赖说明见 [官方部署文档](https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose)，复现时固定 1.18.0，勿将最新版新增配置混入旧版。

seekdb 使用原生 server，可运行：`seekdb.exe --nodaemon --base-dir <独立数据目录> --port 2881 --parameter memory_limit=4G --parameter log_disk_size=2G --parameter datafile_size=2G`。通过 MySQL 兼容客户端执行 `CREATE DATABASE IF NOT EXISTS test;`。服务端自动建表，无需预置玩家数据。若已有可用实例，直接配置下面的连接变量即可。

## 运行

1. 启动 seekdb，创建 `test` 数据库。默认连接 `127.0.0.1:2881`，用户 `root`，空密码；可通过 `SEEKDB_HOST`、`SEEKDB_PORT`、`SEEKDB_USER`、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE` 覆盖。
2. 在本目录执行 `npm ci`、`npm start`，存储桥接服务监听 `127.0.0.1:18747`，自动创建 `odc_detective_sessions` 表。
3. 启动官方 Dify（实测版本 1.18.0）。Docker Desktop 场景中，将 Dify 的 `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` 配置为 `host.docker.internal`，允许工作流访问这个本机服务。不要将无认证的存储桥接服务暴露到公网。
4. 在 Dify 工作室导入 `detective.yml`。也可从 URL `http://host.docker.internal:18747/workflow.yml` 导入。本次支持并实测的是同机 Docker Desktop + Windows 宿主服务；普通 Linux 容器无法直接访问宿主 127.0.0.1，此交付未声明该网络组合已经验证。若采用原生同机 Dify，可把 DSL 中 `load` 和 `save` 两个 HTTP 节点的 `host.docker.internal` 改为 `127.0.0.1`，并在自己的 Dify HTTP 出站设置中允许这个明确地址。
5. 发布工作流并打开生成的应用链接。填写一个英文字母、数字、下划线或连字符组成的玩家代号，行动填“开始”。根据线索作答，或输入“提示”“继续”“重开”。

本机已发布演示地址为 `http://127.0.0.1:18744/workflow/VHMGLXS50ALjSLor`，仅在部署机器可用；他人需按上述步骤导入并发布自己的实例。

## 工作流与数据

`输入 → 校验代号 → HTTP 读取 seekdb → Code 执行游戏规则 → HTTP 写入 seekdb → 确认保存 → 输出`

游戏代码完整嵌入 DSL 的 Code 节点。`server.mjs` 只提供数据库读写，不代替 Dify 处理游戏规则。所有 SQL 参数均绑定；写入携带 revision，旧版本返回 409，防止并发回合覆盖进度。玩家代号是演示用存档键，并非身份认证，不应用于存储个人敏感数据。

`game.py` 是 Code 节点源码；修改后用 `pip install pyyaml`、`python build_dsl.py` 重新生成 DSL，再导入 Dify。

## 可重复验证样例

使用新的玩家代号，例如 `review_demo_01`。若同名存档已存在，第一步输入“重开”；“开始”只恢复已有进度，不清空存档。每次运行均保持相同玩家代号，只改变行动：

| 顺序 | 行动 | 预期表现 |
|---|---|---|
| 1 | 重开 | 第一关，0 分、0 次作答；版本号从已有值继续增长 |
| 2 | 混合检索 | 进入第二关，10 分、1 次作答 |
| 3 | 继续 | 保持第二关和 10 分，提示进度已恢复 |
| 4 | 持久化 | 进入第三关，20 分、2 次作答 |
| 5 | 乐观锁 | 三扇门全部打开，30 分、3 次作答 |
| 6 | 重开 | 返回第一关，清空游戏得分、作答与历史 |
| 7 | 提示，然后回答混合检索 | 第一关得 8 分，进入第二关；错误答案只增加作答次数，不推进关卡 |

关闭发布页后重新打开，或者重启 Dify 后执行第 3 步，应恢复数据库中的当前状态。可直接访问存储服务 `http://127.0.0.1:18747/state/review_demo_01`，核对 `room`、`score`、`history` 和 `revision`。此地址只读；重置操作通过工作流“重开”进行。应用不依赖作者已有账号、玩家或固定的发布 URL。

`npm test` 验证真实存档服务的读写和并发冲突；可用 `TEST_URL` 改端口。另运行 `python -m unittest discover -s test -p test_rules.py` 验证同一份 DSL 规则源码的提示、错误答案、恢复和重开行为。Python 规则测试不替代 Dify 实际运行，二者分别记录。

## 实测记录（2026-10-27）

- 官方 Dify 1.18.0 导入、发布成功，七个节点全部执行成功。
- `audit20261027` 从“开始”进入第一关；回答“混合检索”后保存为 10 分、版本 2。
- 重启 Dify API 和网关后，在发布应用中输入“继续”，从 seekdb 恢复 10 分、第二关，保存为版本 3。
- 回答“持久化”“乐观锁”后通关，30 分、3 次作答、版本 5；见 [真实页面截图](evidence/completed-20261027.jpg) 与 [数据库回读](evidence/state-20261027.json)。
- `npm test` 验证真实 seekdb 的写入、读取与旧版本冲突；规则测试覆盖提示扣分、错误答案、通关和恢复。

这里的 30 分是游戏内部得分，不是竞赛平台评测分数。
