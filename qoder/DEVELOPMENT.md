# Qoder 开发与验收记录

- Qoder CN 个人账号名称：`aliyun-1935493103034789`；个人信息页显示的阿里云账号 ID：`1935493103034789`。该 ID 可供赛事核对 Qoder CN 使用记录和站点归属。
- 工作区：报名仓库 `2026-competition-ecosystem` 分支下的 `qoder` 目录。
- Qoder 在任务中完成应用需求拆解、seekdb 表和全文索引、接口、界面、测试、运行说明，以及 Qoder Sites 作品介绍页。参赛者在对话中提出要求、复核实际结果并反馈修复事项。
- [初始开发请求](evidence/development-request.txt)和 [Qoder 开始开发截图](evidence/qoder-development-start.png)记录实际过程；[Qoder 成果与发布状态截图](evidence/qoder-delivery.png)记录交付状态。
- 初版验证后反馈了索引列匹配、未读状态、真实 HTTP 输入校验和测试数据保护问题；Qoder 修改后，又补上导出合成样例的来源标记及相关测试。公开网站由 Qoder Sites 发布并更新。
- 独立复跑真实 seekdb 测试共 81 项，全部通过，详见 [测试日志](evidence/verification-tests-20261027.txt)。[浏览器验证截图](evidence/browser-persistence.png)展示保存的合成资料、待复习状态和备注。
- 公开介绍网站：https://evidence-desk-cjpm9j6u4we.qoder.zone。它是静态展示页，真实应用需按照 README 在本地连接 seekdb 后运行。

样例全部为合成教学内容；`example.com` 为占位地址，不是真实文献或真实用户反馈。

## 2026-10-27 题面复核补充

公开的 Qoder Sites 介绍页可直接打开，网站中的 81 项测试为首次交付记录。后续审校由 Codex 完成：修正页面和 Markdown 导出未应用标题两倍权重的问题，使其显示分数与实际检索排序一致；补充独立部署、获取比赛分支及安装锁定依赖的步骤。原 Qoder 主要开发记录、原始截图和首次测试日志保持可核对。

在真实 seekdb 上重跑现有集成测试并增加3项相关度一致性回归，共84项通过、0失败；测试前后既有11条资料均保留。API返回的 `relevance_score`、页面展示及导出使用同一分数。

题面尚未公布作品评价的具体权重；目前有开发、运行和测试证据，没有外部用户使用规模、真实提效时间对照或用户问卷，因此不把这些材料表述为已取得满分或真实用户效果。
