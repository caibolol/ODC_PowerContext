# 官方验收项与提交材料

题面：[MiniMax × OceanBase：规有所依](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)。全部资产位于 `minimax/`，开发分支 `2026-competition-ecosystem` 继承官方同名分支（共同基点 `d647275c308e09b7b623f322a26f5c4e85734fb0`）。

| 必做项 | 复现入口与证据 |
| --- | --- |
| 能够运行 | README.md 的安装、启动、两条验证命令；2026-10-28 使用新建虚拟环境、独立源码副本、空 seekdb 数据目录和空 PowerContext 数据目录复现成功，见 evidence/clean-environment/ |
| MiniMax 实际参与 | DEVELOPMENT.md、evidence/minimax-request.txt、evidence/minimax-response.py；最终 sample/after/task_service.py 与原始回复逐字节相同 |
| 上下文正确 | sample/manifest.json、sample/spec.md、sample/before/task_service.py、sample/test_task_service.py；verify_context.py 验证三类来源及更新规格后输出新内容 |
| 数据库实际参与 | context.py 的真实 seekdb 导入和参数绑定查询；evidence/clean-environment/integration.json 记录全部独立进程命令、退出码、来源、查询文本、参数和返回行数 |
| 状态能够复用 | 初始空 scope、PowerContext 写入、再启动 CLI 后恢复状态并进入 previous_state；context-initial.json、state-write.json、context-restored.json |
| 代码修改有效 | evidence/clean-environment/tests.json；同一7项测试，修改前5个断言失败，修改后全部通过；前后测试文件SHA-256一致，均记录代码SHA-256与命令退出码 |

## 材料索引

- 完整源码：context.py、sample/、verify_sample.py、verify_context.py、启动脚本。
- 运行说明：README.md；依赖版本：requirements.txt、requirements-windows-lock.txt。
- 验证样例：sample/spec.md、sample/manifest.json、业务前后快照及同一测试文件；输入输出和重置方式见 README.md。
- 代码差异：evidence/final-change.diff；本地先行实现和差异另行保留。
- 技术使用记录：DEVELOPMENT.md 与 evidence/，包括 MiniMax 原始请求和代码、数据库查询、PowerContext 状态写入与复用。
- 一页技术说明：README.md 对应章节。

## 干净环境复现记录

2026-10-28（Asia/Shanghai），新建 Python 3.12 虚拟环境；从固定 Git 提交安装 PowerContext，而非引用原有 editable 安装；安装 PyMySQL 1.2.0。完整安装结果已冻结为 requirements-windows-lock.txt（Windows/Python 3.12）。使用独立项目副本执行验证，数据库与 PowerContext 均使用全新持久化目录，不复用此前任务数据。

PowerContext 本次实际安装版本：`0.1.dev805+gda0cb9c2e`，固定源码提交 `da0cb9c2e945d6363725b3abfc4f40a854bf9d29`。seekdb 使用原生 1.4.0.0，源码 `bef66ef2f6dc7b6c046a9af9daafa9b811a9c401`。服务分别绑定回环 18754、18755，验证进程经 PC_URL、DB_PORT 配置；README 默认端口为18752、18753，行为一致。

执行 `python verify_sample.py`：验证脚本退出0；业务修改前测试退出1，修改后退出0。执行 `python verify_context.py`：退出0，完成真实资料导入/查询、规格更新、空状态写入及跨进程复用。证据保留原始执行路径以便审计；这些路径不是复现时的硬编码依赖。

平台分数以实际评审结果为准。
