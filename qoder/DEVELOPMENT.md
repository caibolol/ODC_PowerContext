# Qoder 开发与验收记录

- Qoder CN 个人账号名称：`aliyun-1935493103034789`；个人信息页显示的阿里云账号 ID：`1935493103034789`。该 ID 可供赛事核对 Qoder CN 使用记录和站点归属。
- 工作区：报名仓库 `2026-competition-ecosystem` 分支下的 `qoder` 目录。
- Qoder 在任务中完成应用需求拆解、seekdb 表和全文索引、接口、界面、测试、运行说明，以及 Qoder Sites 作品介绍页。参赛者在对话中提出要求、复核实际结果并反馈修复事项。
- [初始开发请求](evidence/development-request.txt)和 [Qoder 开始开发截图](evidence/qoder-development-start.png)记录实际过程；[Qoder 成果与发布状态截图](evidence/qoder-delivery.png)记录交付状态。
- 初版验证后反馈了索引列匹配、未读状态、真实 HTTP 输入校验和测试数据保护问题；Qoder 修改后，又补上导出合成样例的来源标记及相关测试。公开网站由 Qoder Sites 发布并更新。
- 独立复跑真实 seekdb 测试共 81 项，全部通过，详见 [测试日志](evidence/verification-tests-20261027.txt)。[浏览器验证截图](evidence/browser-persistence.png)展示保存的合成资料、待复习状态和备注。
- 公开介绍网站：https://evidence-desk-cjpm9j6u4we.qoder.zone。它是静态展示页，真实应用需按照 README 在本地连接 seekdb 后运行。

样例全部为合成教学内容；`example.com` 为占位地址，不是真实文献或真实用户反馈。
