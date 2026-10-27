# 记忆侦探：三扇数据库之门

玩家通过三个数据库谜题打开档案室。提示会扣分，错误答案保留作答记录，关闭应用后可用同一代号继续。Dify 负责整个回合的规则与编排，seekdb 实际保存玩家进度、分数、答案历史和版本号。

本作品是确定性规则游戏，不调用大模型，不需要模型密钥。它以可验证的线索匹配实现判题，不宣称具有开放问答能力。

## 运行

1. 启动 seekdb，创建 `test` 数据库。默认连接 `127.0.0.1:2881`，用户 `root`，空密码；可通过 `SEEKDB_HOST`、`SEEKDB_PORT`、`SEEKDB_USER`、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE` 覆盖。
2. 在本目录执行 `npm ci`、`npm start`，存储桥接服务监听 `127.0.0.1:18747`，自动创建 `odc_detective_sessions` 表。
3. 启动官方 Dify（实测版本 1.18.0）。Docker Desktop 场景中，将 Dify 的 `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` 配置为 `host.docker.internal`，允许工作流访问这个本机服务。不要将无认证的存储桥接服务暴露到公网。
4. 在 Dify 工作室导入 `detective.yml`。也可从 URL `http://host.docker.internal:18747/workflow.yml` 导入。非 Docker Desktop 环境需要将 DSL 两个 HTTP 节点的地址改为 Dify 可访问的存储服务地址。
5. 发布工作流并打开生成的应用链接。填写一个英文字母、数字、下划线或连字符组成的玩家代号，行动填“开始”。根据线索作答，或输入“提示”“继续”“重开”。

本机已发布演示地址为 `http://127.0.0.1:18744/workflow/VHMGLXS50ALjSLor`，仅在部署机器可用；他人需按上述步骤导入并发布自己的实例。

## 工作流与数据

`输入 → 校验代号 → HTTP 读取 seekdb → Code 执行游戏规则 → HTTP 写入 seekdb → 确认保存 → 输出`

游戏代码完整嵌入 DSL 的 Code 节点。`server.mjs` 只提供数据库读写，不代替 Dify 处理游戏规则。所有 SQL 参数均绑定；写入携带 revision，旧版本返回 409，防止并发回合覆盖进度。玩家代号是演示用存档键，并非身份认证，不应用于存储个人敏感数据。

`game.py` 是 Code 节点源码；修改后用 `pip install pyyaml`、`python build_dsl.py` 重新生成 DSL，再导入 Dify。

## 实测记录（2026-10-27）

- 官方 Dify 1.18.0 导入、发布成功，七个节点全部执行成功。
- `audit20261027` 从“开始”进入第一关；回答“混合检索”后保存为 10 分、版本 2。
- 重启 Dify API 和网关后，在发布应用中输入“继续”，从 seekdb 恢复 10 分、第二关，保存为版本 3。
- 回答“持久化”“乐观锁”后通关，30 分、3 次作答、版本 5；见 [真实页面截图](evidence/completed-20261027.jpg) 与 [数据库回读](evidence/state-20261027.json)。
- `npm test` 验证真实 seekdb 的写入、读取与旧版本冲突；规则测试覆盖提示扣分、错误答案、通关和恢复。

这里的 30 分是游戏内部得分，不是竞赛平台评测分数。
