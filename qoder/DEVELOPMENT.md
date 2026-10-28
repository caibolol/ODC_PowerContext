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

## 2026-10-28 在线体验与一条命令引导补充（Qoder 开发）

背景：首次提测（commit 2ff487206bd65ef）评审反馈「主要功能运行失败」。复核结论：公开站点当时为静态介绍页，主要功能必须按 README 在本地连接 seekdb 部署后才能体验，评审在作品链接上无法直接运行主要功能；同时手动部署步骤多（seekdb 需自行安装、示例为 Windows 命令），干净环境复现门槛高。

本次改动（在 Qoder 会话中完成开发，提交者复核实际结果）：

- 新增 `site/demo.html` 在线体验页：全文检索与相关度排序（浏览器本地 tf-idf 近似，标题权重 ×2 与数据库公式一致）、资料录入（校验错误文案与服务端逐条一致）、复习状态与备注持久化（localStorage）、合成样例一键导入、Markdown 导出（格式与服务端 `/api/export` 一致）。页面显著位置声明演示模式及其与 seekdb 真实部署的关系，不以任何方式冒充数据库检索。
- 介绍页 `site/index.html` 增加导航与 hero 的「在线体验」入口、#demo 与 #start 段落补充在线体验与一条命令引导说明；测试计数表述统一为 84/84（含 2026-10-27 复核追加的 3 项相关度一致性回归）。
- 新增 `scripts/bootstrap.sh`（Linux/macOS）与 `scripts/bootstrap.ps1`（Windows，`-SeekdbExe` 必填）：一条命令完成依赖安装、seekdb 复用或安装启动（官方 release v1.4.0 包，无 root 时 dpkg-deb/rpm2cpio 解包，有 root 时优先官方安装脚本）、`scripts/wait-ready.js` 轮询就绪并建库、`npm run db:init` 建表与 IK 索引、`scripts/import-sample.js` 幂等导入样例、前台启动服务。
- README 增加一条命令引导、在线体验验证样例（含预期结果）与项目结构更新；本记录与 `evidence/online-demo-verification-20261028.txt` 记录验证过程。

验证摘要（详见 evidence 记录）：全新 seekdb 实例上 npm test 84/84 通过；浏览器实测导入/检索/状态持久化/校验/导出全流程；bootstrap.ps1 在 Windows 实测到服务可用（/api/health、/api/search 命中）；bootstrap.sh 通过 bash -n，Linux 解包路径因本机无 Linux 环境未实跑。

技术结合说明不变：seekdb 的 FULLTEXT IK 索引与 MATCH AGAINST 仍是项目检索能力的真实实现（集成测试直连真实 seekdb）；在线体验页仅为免部署的功能体验入口，演示数据保存在浏览器本地。

发布记录（2026-10-28）：更新后的介绍页与在线体验页以当前提测账号新发布为公开站点 https://evidence-desk-quxa3c018p9.qoder.zone（可见范围「任何人都可访问」，demo 入口为同域 /demo.html）；原站点 https://evidence-desk-cjpm9j6u4we.qoder.zone 保留不删除。README 中的站点地址已同步为新站。
