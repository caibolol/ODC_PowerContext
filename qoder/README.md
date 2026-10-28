# 研读档案 EvidenceDesk

OceanBase 数据库大赛 Qoder 赛道作品 - 帮助学生和研究者管理资料摘录、检索带来源的证据、保存复习进度的 Web 应用。

作品介绍页（Qoder Sites，公开）：https://evidence-desk-quxa3c018p9.qoder.zone

在线体验（免部署，主要功能直接在浏览器运行）：https://evidence-desk-quxa3c018p9.qoder.zone/demo.html

Qoder 账号、开发过程和验收材料见 [开发与验收记录](DEVELOPMENT.md)。

## 项目简介

EvidenceDesk 是一个基于 Node.js + Express 的研读档案管理工具，**同时结合 seekdb 与 PowerContext 两种指定技术**：

- **全文检索（seekdb）**：资料摘录存入 seekdb，检索由 seekdb 引擎真实执行。默认嵌入式模式（npm 原生包，进程内 SQL 引擎，无需数据库服务器）；服务端模式使用 SQL `FULLTEXT ... WITH PARSER ik` + `MATCH AGAINST`，两种模式共用同一套 SQL 与相关度公式
- **跨会话记忆（PowerContext）**：每次复习状态更新后，把进度快照写入 PowerContext 记忆；应用重启或下次会话启动时读回最新进度并展示，实现"越用越懂你"的复习延续
- **来源追溯**：每条摘录保存标题、来源 URL、页码、标签
- **复习管理**：已读/待复习/已掌握状态 + 备注，持久化存储
- **安全导入**：一键导入 10 条合成教学样例（example.com 为占位来源，明确标注非真实文献）
- **Markdown 导出**：将检索结果导出为带来源的证据清单
- **响应式 UI**：适配桌面和移动端的中文界面

## 技术架构

```
┌─────────────────────────────────────────┐
│           Frontend (HTML/CSS/JS)        │
│         响应式单页应用，中文界面          │
└────────────────────────────────────────┘
                 │ HTTP REST API
┌────────────────▼────────────────────────┐
│         Backend (Node.js + Express)     │
│  - 输入校验 / SQL 参数绑定 / 安全输出    │
│  - FULLTEXT 搜索编排 / 状态管理          │
└───────┬─────────────────────────┬───────┘
        │ SQL（同一套语句）         │ HTTP（/v1/scopes、/v1/memory/*）
┌───────▼───────────────┐ ┌────────▼──────────────────┐
│ seekdb 嵌入式（默认）   │ │ PowerContext 记忆服务      │
│ @seekdb/js-bindings   │ │ - 复习进度快照 remember    │
│ 进程内 SQL 引擎 + IK   │ │ - 下次启动读回复用          │
│ 数据目录 .evidencedesk- │ └───────────────────────────┘
│ seekdb/               │
├───────────────────────┤
│ seekdb 服务端（可选）   │
│ DB_MODE=server 时经    │
│ mysql2 连接 2881 端口  │
└───────────────────────┘
```

### 数据库表结构

**odc_qoder_excerpts** - 资料摘录表
- `id` BIGINT PRIMARY KEY
- `title` VARCHAR(500) - 标题
- `source_url` VARCHAR(1000) - 来源链接
- `source_page` VARCHAR(100) - 页码
- `body_text` TEXT - 正文摘录
- `tags` VARCHAR(1000) - 标签（逗号分隔）
- FULLTEXT INDEX `ft_body` (body_text) WITH PARSER ik
- FULLTEXT INDEX `ft_title` (title) WITH PARSER ik

**odc_qoder_review_states** - 复习状态表
- `excerpt_id` BIGINT - 关联摘录 ID
- `state` ENUM('unread','read','review','mastered')
- `notes` TEXT - 备注

## 技术分工（seekdb × PowerContext）

| 技术 | 在本项目中的作用 | 核对方式 |
| :--- | :--- | :--- |
| seekdb | 资料与复习状态的存储、全文检索与相关度排序的唯一执行者。默认嵌入式部署（`@seekdb/js-bindings` 原生包，进程内 SQL 引擎，含 IK 解析器）；可选服务端部署（MySQL 协议 2881） | `npm run demo` 自检输出检索命中与相关度；`npm test`（服务端模式）84 项直连真实 seekdb；数据目录 `.evidencedesk-seekdb/` 可直接检查 |
| PowerContext | 跨会话记忆层：复习状态更新后写入进度快照（`/v1/memory/remember`），应用启动与 `GET /api/context` 读回最新进度（`/v1/memory/entries/list`），重启后复用 | `npm run demo` 含"记忆写入并读回"自检；重启应用后 `GET /api/context` 返回上次进度；PowerContext 服务端日志可见 remember/list 调用 |

两者分工：seekdb 负责"找得到"（存储与检索），PowerContext 负责"记得住"（跨会话进度与历史互动复用）。

## 快速开始

### 环境要求

- Node.js >= 18.0.0（验收路径在 Node 18/20/24 均可）
- **验收路径不需要数据库服务器、不需要 Docker、不需要 root 权限**：seekdb 以嵌入式随进程启动
- PowerContext 记忆层需要 Python 3.11+（3.12 已验证）；仅需检索功能时可用 `SKIP_CONTEXT=1 npm run demo` 跳过记忆层自检
- Linux 评审环境无需联网下载原生包：仓库内置 `vendor/seekdb-js-bindings-linux-x64.zip`，启动时经本机回环地址离线加载；其他平台首次运行从 seekdb 官方制品源下载并缓存

### 验收路径（默认，零外部服务）

```bash
# 1. 获取比赛分支并进入项目目录
git clone --branch 2026-competition-ecosystem --single-branch https://github.com/caibolol/ODC_PowerContext.git
cd ODC_PowerContext/qoder

# 2. 安装依赖（已生成 package-lock.json；含 seekdb 嵌入式原生包）
npm ci

# 3. 启动 PowerContext 记忆服务（本地 18752 端口；首次会从官方公开仓库安装）
bash scripts/start-context.sh            # Windows: powershell -ExecutionPolicy Bypass -File scripts\start-context.ps1

# 4. 零依赖自检：嵌入式 seekdb 检索/状态/统计 + PowerContext 记忆读写，全 PASS 退出码 0
npm run demo

# 5. 启动应用（嵌入式后端，数据目录 .evidencedesk-seekdb/）
npm start
```

服务默认绑定 127.0.0.1，启动后访问 http://127.0.0.1:18748 ，按「验证样例 A」体验主要功能。

免部署体验主要功能：直接打开作品介绍页的 [在线体验](https://evidence-desk-quxa3c018p9.qoder.zone/demo.html)（演示模式，数据保存在浏览器本地；真实检索能力以本地 seekdb 运行为准）。

### 服务端模式（可选，SQL FULLTEXT IK 增强验证）

```bash
# Linux / macOS：自动完成 依赖安装 → seekdb 服务端安装与启动 → 建库建表与 IK 索引 → 导入样例 → 启动服务
DB_MODE=server bash scripts/bootstrap.sh
```

```powershell
# Windows：-SeekdbExe 为 seekdb.exe 的完整路径（必填）
$env:DB_MODE='server'; powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -SeekdbExe 'C:\seekdb\seekdb.exe'
```

引导脚本行为：端口上已有可用 seekdb 时直接复用；否则 Linux 下从官方 release 包（v1.4.0）无 root 解包安装（dpkg-deb / rpm2cpio），随后以验证过的参数启动（`--nodaemon --base-dir ... --parameter cpu_count=4 --parameter memory_budget=2G --parameter datafile_size=32M --parameter datafile_maxsize=2G --parameter log_disk_size=2G`）；`scripts/wait-ready.js` 轮询就绪并创建数据库，`npm run db:init` 建表与 IK 索引，`scripts/import-sample.js` 幂等导入 10 条合成样例，最后前台启动服务。改端口用环境变量 `SEEKDB_PORT`（Linux）或 `-Port`（Windows）。

手动启动 seekdb 服务端（不使用引导脚本时）：Linux/macOS 安装入口见 [seekdb 官方部署说明](https://github.com/oceanbase/seekdb/blob/master/README_CN.md#快速开始)；Windows 将 `seekdb.exe` 及附带 DLL 放同一目录后：

```powershell
& 'C:\seekdb\seekdb.exe' --nodaemon --base-dir 'C:\seekdb\evidencedesk-data' --port 2881 --parameter memory_limit=4G --parameter log_disk_size=2G --parameter datafile_size=2G
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DB_MODE | embedded | `embedded`=嵌入式 seekdb（默认，零外部服务）；`server`=连接 seekdb 服务端 |
| EMBEDDED_DB_DIR | ./.evidencedesk-seekdb | 嵌入式数据目录 |
| POWERCONTEXT_URL | http://127.0.0.1:18752 | PowerContext 服务地址 |
| SKIP_CONTEXT | (未设) | 设为 1 时 `npm run demo` 跳过 PowerContext 自检 |
| SEEKDB_BINDINGS_BASE_URL | (自动) | 原生包下载源；Linux 默认自动指向仓库内置 vendor 包的回环服务 |
| DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD | 127.0.0.1 / 2881 / test / root / 空 | 仅服务端模式使用 |
| PORT / HOST | 18748 / 127.0.0.1 | 应用监听地址 |

## 核心功能

### 1. 资料录入

- 填写标题（必填，≤500字）、来源 URL（格式校验）、页码、正文摘录（必填，≤20000字）、标签
- 所有输入经 SQL 参数绑定，防止注入
- 输出经 HTML 转义与属性转义，防止 XSS
- 新记录在没有复习行时默认视为“未读”

### 2. 全文检索

- 检索由 seekdb 引擎执行：嵌入式与服务端模式共用同一套 SQL（`MATCH ... AGAINST(... IN NATURAL LANGUAGE MODE)`）与 IK 解析器
- 两个单列索引 `ft_body`、`ft_title` 分别检索后合并相关度
- 搜索结果按相关度排序（标题权重 ×2 + 正文权重）
- 支持按标签和复习状态过滤

### 3. 复习状态管理

- 四种状态：未读 / 已读 / 待复习 / 已掌握
- 每条记录可添加备注
- 状态持久化在 seekdb，重启不丢失；每次更新同时写入 PowerContext 记忆快照

### 4. 跨会话记忆（PowerContext）

- 复习状态更新后自动 `remember` 一条进度快照（资料总数、各状态分布、本次操作）
- 应用启动与 `GET /api/context` 读回最新快照，展示"上次复习进度"
- PowerContext 不可用时明确降级提示，检索主功能不受影响

### 5. 样例数据导入

- 一键导入 10 条合成教学样例（中英文混合）
- example.com 为占位来源，不是真实文献或真实用户数据
- 资料列表与导入入口均有醒目标注，样例条目显示“合成样例·占位来源”徽标

### 6. Markdown 导出

- 将当前检索结果导出为 Markdown 格式证据清单
- 包含来源 URL、页码、标签、状态、备注
- 显示相关度评分
- 对 example.com / synthetic 来源自动标注“合成教学样例 · 占位来源 · 非真实文献”，并在清单顶部加入数据性质说明

### 7. 数据库状态监控

- 页面顶部实时显示数据库连接状态与后端模式（embedded / server）
- 统计面板展示资料总数和各状态分布
- 连接失败时明确报错，不静默降级

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查（含后端模式） |
| GET | /api/stats | 统计信息 |
| GET | /api/context | PowerContext 连接状态与最新记忆快照 |
| GET | /api/excerpts | 资料列表（支持 tag/state 过滤） |
| POST | /api/excerpts | 创建资料 |
| GET | /api/excerpts/:id | 获取详情 |
| DELETE | /api/excerpts/:id | 删除资料 |
| GET | /api/search?q=keyword | 全文检索 |
| PUT | /api/excerpts/:id/review | 更新复习状态（同时写入 PowerContext 记忆） |
| GET | /api/excerpts/:id/review | 获取复习状态 |
| POST | /api/import-sample | 导入样例数据 |
| GET | /api/export | 导出 Markdown |

## 测试验证

### 零依赖自检（验收入口）

```bash
npm run demo
```

在嵌入式 seekdb 上依次自检：schema 与 IK 索引、样例幂等导入、中文/英文全文检索命中、相关度排序、新增立即可检索、复习状态与备注持久化、统计、删除清理、PowerContext 记忆写入并读回；全部 PASS 时退出码 0。

### 集成测试（服务端模式）

运行完整测试套件（最新复核 84 项全部通过，历史 81 项原始记录仍保留）：

```bash
DB_MODE=server npm test
```

测试覆盖：
- ✓ 数据库连接与状态检查
- ✓ Schema 初始化与 seekdb IK 解析器验证（拒绝 ngram 预设）
- ✓ CRUD 操作（创建/读取/列表/删除）
- ✓ 英文 FULLTEXT 检索命中指定 ID 与相关度
- ✓ 中文 FULLTEXT 检索命中指定中文文本 ID 与相关度
- ✓ 标题索引单独检索验证
- ✓ 复习状态管理（创建/更新/关闭连接池后仍持久化）
- ✓ 标签与状态过滤（未建复习行默认 unread，过滤与统计均包含）
- ✓ SQL 注入安全性（恶意文本安全存储、查询安全处理）
- ✓ 真实 HTTP 接口校验：空标题、空正文、非法 URL、错误类型、超长输入均返回 400
- ✓ 合法数据经 HTTP 正常保存并可全文检索
- ✓ 测试仅删除本次创建的 ID，原有资料数量保持不变
- ✓ 统计接口
- ✓ 搜索 API 与 Markdown 导出的相关度一致，均使用正文分数 + 2 × 标题分数，与数据库排序一致

### 验证样例 A：嵌入式验收路径（默认）

1. **启动**：按「验收路径」执行 1-5 步；`npm run demo` 预期输出全部 PASS、退出码 0
2. **中文检索**：`curl "http://127.0.0.1:18748/api/search?q=分布式数据库"` 预期命中「OceanBase 分布式数据库架构设计」等记录并带 `relevance_score`
3. **录入与状态**：`POST /api/excerpts` 新增一条 → `PUT /api/excerpts/<id>/review` 设为 `review` 并写备注 → `GET /api/excerpts/<id>/review` 读回一致
4. **记忆复用**：`GET /api/context` 预期 `connected:true` 且 `latest_progress.entry.stats` 与第 3 步后的统计一致；**重启应用后再次调用仍返回同一快照**（跨会话复用）
5. **导出**：`curl "http://127.0.0.1:18748/api/export?q=分布式数据库"` 得到含来源、页码、状态、相关度与合成样例说明的 Markdown

### 验证样例 B：服务端模式

按「服务端模式」启动后重复验证样例 A 的第 2-5 步，并执行 `DB_MODE=server npm test` 预期 84/84 通过。

### 在线体验验证样例（免部署）

1. **打开在线体验**：浏览器（无痕窗口亦可）访问 https://evidence-desk-quxa3c018p9.qoder.zone/demo.html
2. **确认样例**：首次打开自动预载 10 条合成教学样例，状态栏显示资料总数 10、各状态均为未读；若曾手动清空，点击「导入 10 条合成教学样例」恢复
3. **中文检索**：输入「分布式数据库」检索，预期命中「OceanBase 分布式数据库架构设计」等记录并显示相关度评分
4. **中英混合检索**：输入「Paxos」检索，预期命中「Paxos 共识算法原理与实践」与包含 Paxos 的分布式数据库样例
5. **复习状态**：在「资料与复习状态」页将任一条设为「待复习」并填写备注保存，刷新页面后状态与备注仍在（浏览器本地持久化）
6. **导出**：点击「导出 Markdown 证据清单」，下载内容与本地部署 `/api/export` 格式一致，含合成样例数据性质说明

预期结果如上；演示模式数据仅存于浏览器 localStorage，不连接数据库。seekdb 与 PowerContext 实际发挥作用的记录见上述自检/集成测试与 evidence/ 目录日志。

## 安全特性

- **SQL 注入防护**：所有查询使用参数绑定（服务端 mysql2 prepared statements；嵌入式经原生绑定参数化执行）
- **XSS 防护**：文本输出经 HTML 转义，URL/属性输出经属性转义，状态按钮不再内联拼接备注
- **输入校验**：标题/正文/URL/页码/标签/备注的长度与类型校验，URL 仅允许 http/https
- **权限隔离**：仅操作 odc_qoder_ 前缀表，不影响其他数据
- **默认绑定**：服务默认只监听 127.0.0.1:18748，可通过 HOST 环境变量显式覆盖

## 项目结构

```
qoder/
├── src/
│   ├── server.js          # Express 服务器 + API 路由
│   ├── db.js              # 数据访问层（embedded / server 双后端，同一套 SQL）
│   ├── embedded.js        # 嵌入式 seekdb 驱动适配（含 vendor 离线加载）
│   ├── context.js         # PowerContext 记忆层客户端
│   └── sample-data.js     # 合成教学样例
├── public/
│   └── index.html         # 前端单页应用
├── scripts/
│   ├── demo.js            # 零依赖自检（验收入口）
│   ├── init-db.js         # 数据库初始化与 IK/BENG 索引迁移
│   ├── wait-ready.js      # 轮询 seekdb 服务端就绪并创建数据库
│   ├── import-sample.js   # 幂等导入合成教学样例
│   ├── start-context.sh   # 启动 PowerContext（Linux/macOS）
│   ├── start-context.ps1  # 启动 PowerContext（Windows）
│   ├── bootstrap.sh       # 服务端模式一条命令引导（Linux/macOS）
│   └── bootstrap.ps1      # 服务端模式一条命令引导（Windows）
├── vendor/
│   └── seekdb-js-bindings-linux-x64.zip  # Linux 评审环境离线原生包
├── site/
│   ├── index.html         # Qoder Sites 作品介绍页
│   ├── demo.html          # Qoder Sites 在线体验页（演示模式）
│   └── assets/            # 介绍页截图与图标
├── test/
│   └── integration.test.js # 集成测试（服务端模式）
├── package.json
├── package-lock.json
├── .env.example
├── .gitignore
└── README.md
```

## 待解决项

1. **多列索引限制**：当前使用两个单列 FULLTEXT 索引（ft_body、ft_title），查询用两个单列 MATCH 条件后合并排序；未依赖不存在的多列组合索引
2. **BENG 备用**：seekdb 若缺少 IK 会尝试 BENG；两者都不可用时初始化会明确失败，不会静默降级或退回假数据
3. **性能优化**：大数据量下可考虑分页优化或缓存层

## 技术亮点

- **真实 FULLTEXT 搜索**：非前端字符串匹配，检索由 seekdb 引擎执行（嵌入式与服务端同一套 SQL 与 IK 解析器）
- **双部署形态**：嵌入式零外部服务即可验收（npm 原生包，Linux 离线 vendor 包），服务端模式可切换，代码零分叉
- **双技术结合**：seekdb 承担存储与检索，PowerContext 承担跨会话记忆，分工与核对方式见「技术分工」
- **相关度排序**：基于 MATCH AGAINST 自然语言模式评分，标题权重 ×2
- **安全设计**：参数绑定 + HTML/属性转义 + 服务端类型/长度校验
- **完整测试**：零依赖自检 + 84 项服务端集成测试，覆盖核心功能、真实 HTTP 校验、Markdown 导出标记、排序分数一致性与安全性
- **数据保护**：测试仅清理本次创建的 ID，保留既有资料

## 许可证

MIT

## 团队

参赛者（Qoder辅助开发） - OceanBase 数据库大赛 2026
