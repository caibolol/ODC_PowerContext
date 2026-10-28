# 研读档案 EvidenceDesk

OceanBase 数据库大赛 Qoder 赛道作品 - 帮助学生和研究者管理资料摘录、检索带来源的证据、保存复习进度的 Web 应用。

作品介绍页（Qoder Sites，公开）：https://evidence-desk-cjpm9j6u4we.qoder.zone

Qoder 账号、开发过程和验收材料见 [开发与验收记录](DEVELOPMENT.md)。

## 项目简介

EvidenceDesk 是一个基于 Node.js + Express + OceanBase(seekdb) 的研读档案管理工具，核心特性：

- **全文检索**：使用 OceanBase seekdb 真实 FULLTEXT 索引 + MATCH AGAINST，采用 IK 解析器支持中英文混合检索
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
└────────────────┬────────────────────────┘
                 │ HTTP REST API
┌────────────────▼────────────────────────┐
│         Backend (Node.js + Express)     │
│  - 输入校验 / SQL 参数绑定 / 安全输出    │
│  - FULLTEXT 搜索编排 / 状态管理          │
└────────────────┬────────────────────────┘
                 │ mysql2 连接池
┌────────────────▼────────────────────────┐
│     OceanBase seekdb (127.0.0.1:2881)   │
│  - odc_qoder_excerpts (FULLTEXT IK)     │
│  - odc_qoder_review_states              │
└─────────────────────────────────────────┘
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

## 快速开始

### 环境要求

- Node.js >= 18.0.0
- seekdb 服务端（本项目在 `5.7.25-OceanBase seekdb-v1.4.0.0` 验证，MySQL 协议端口默认为 `2881`）。需提供 IK 全文解析器；普通 MySQL 不能替代指定的 seekdb。

### 先启动 seekdb

应用使用 MySQL 协议连接独立的 seekdb 服务端，Python 嵌入式客户端不能直接代替该端口。Linux/macOS 安装入口见 [seekdb 官方部署说明](https://github.com/oceanbase/seekdb/blob/master/README_CN.md#快速开始)。安装后按其部署说明启动服务，并创建用于本项目的数据库。

本次验收使用原生 Windows 构建的 `seekdb.exe`，启动参数如下（先将可执行文件及附带 DLL 放在同一目录，替换实际路径，在专用目录运行）：

```powershell
& 'C:\seekdb\seekdb.exe' --nodaemon --base-dir 'C:\seekdb\evidencedesk-data' --port 2881 --parameter memory_limit=4G --parameter log_disk_size=2G --parameter datafile_size=2G
```

服务保持运行，在另一个终端通过 MySQL 客户端连接，确认版本并创建数据库：

```bash
mysql -h127.0.0.1 -P2881 -uroot -p -e "SELECT VERSION(); CREATE DATABASE IF NOT EXISTS evidencedesk DEFAULT CHARACTER SET utf8mb4;"
```

按部署时设置的账号输入密码；空密码测试实例可直接回车。下方 `.env` 的 `DB_NAME` 改成 `evidencedesk`，用户名和密码与该实例一致。本机历史验证使用现有 `test` 数据库；应用只操作 `odc_qoder_` 前缀的表。

### 安装步骤

```bash
# 1. 获取比赛分支并进入项目目录
git clone --branch 2026-competition-ecosystem --single-branch https://github.com/caibolol/ODC_PowerContext.git
cd ODC_PowerContext/qoder

# 2. 安装依赖（已生成 package-lock.json）
npm ci

# 3. 配置环境变量（可选，默认值已内置）
cp .env.example .env
# 编辑 .env 文件设置数据库连接参数

# 4. 初始化数据库表结构
npm run db:init

# 5. 启动服务
npm start
```

服务默认绑定 127.0.0.1，启动后访问 http://127.0.0.1:18748

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DB_HOST | 127.0.0.1 | 数据库主机 |
| DB_PORT | 2881 | 数据库端口 |
| DB_NAME | test | 数据库名；新部署按上文设为 evidencedesk |
| DB_USER | root | 数据库用户 |
| DB_PASSWORD | (空) | 数据库密码 |
| PORT | 18748 | 服务端口 |
| HOST | 127.0.0.1 | 应用监听地址 |

## 核心功能

### 1. 资料录入

- 填写标题（必填，≤500字）、来源 URL（格式校验）、页码、正文摘录（必填，≤20000字）、标签
- 所有输入经 SQL 参数绑定，防止注入
- 输出经 HTML 转义与属性转义，防止 XSS
- 新记录在没有复习行时默认视为“未读”

### 2. 全文检索

- 使用 OceanBase seekdb FULLTEXT 索引 + MATCH AGAINST 语法
- 使用 seekdb 实际支持的 IK 解析器（已验证中英文查询均命中；BENG 作为备用探测）
- 两个单列索引 `ft_body`、`ft_title` 分别检索后合并相关度
- 搜索结果按相关度排序（标题权重 ×2 + 正文权重）
- 支持按标签和复习状态过滤

### 3. 复习状态管理

- 四种状态：未读 / 已读 / 待复习 / 已掌握
- 每条记录可添加备注
- 状态持久化，重启不丢失

### 4. 样例数据导入

- 一键导入 10 条合成教学样例（中英文混合）
- example.com 为占位来源，不是真实文献或真实用户数据
- 资料列表与导入入口均有醒目标注，样例条目显示“合成样例·占位来源”徽标

### 5. Markdown 导出

- 将当前检索结果导出为 Markdown 格式证据清单
- 包含来源 URL、页码、标签、状态、备注
- 显示相关度评分
- 对 example.com / synthetic 来源自动标注“合成教学样例 · 占位来源 · 非真实文献”，并在清单顶部加入数据性质说明

### 6. 数据库状态监控

- 页面顶部实时显示数据库连接状态
- 统计面板展示资料总数和各状态分布
- 连接失败时明确报错，不静默降级

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/stats | 统计信息 |
| GET | /api/excerpts | 资料列表（支持 tag/state 过滤） |
| POST | /api/excerpts | 创建资料 |
| GET | /api/excerpts/:id | 获取详情 |
| DELETE | /api/excerpts/:id | 删除资料 |
| GET | /api/search?q=keyword | 全文检索 |
| PUT | /api/excerpts/:id/review | 更新复习状态 |
| GET | /api/excerpts/:id/review | 获取复习状态 |
| POST | /api/import-sample | 导入样例数据 |
| GET | /api/export | 导出 Markdown |

## 测试验证

### 集成测试

运行完整测试套件（最新复核 84 项全部通过，历史 81 项原始记录仍保留）：

```bash
npm test
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

### 手动验证步骤

1. **启动服务**
   ```bash
   npm start
   ```

2. **访问页面**
   打开 http://127.0.0.1:18748

3. **导入样例数据**
   点击"统计"标签 → "导入合成教学样例"。页面与条目会明确标注：合成教学样例，example.com 为占位来源，不是真实文献。

4. **测试全文检索**
   在搜索框输入 "OceanBase"、"分布式数据库" 或 "Paxos"，查看带相关度评分的结果

5. **测试录入**
   切换到"录入"标签，添加新资料

6. **测试状态管理**
   点击任意资料的"设置状态"按钮，修改复习状态和备注

7. **测试导出**
   搜索后点击"导出 Markdown"，下载证据清单

8. **测试响应式**
   调整浏览器窗口大小，验证移动端适配

## 安全特性

- **SQL 注入防护**：所有查询使用参数绑定（mysql2 prepared statements）
- **XSS 防护**：文本输出经 HTML 转义，URL/属性输出经属性转义，状态按钮不再内联拼接备注
- **输入校验**：标题/正文/URL/页码/标签/备注的长度与类型校验，URL 仅允许 http/https
- **权限隔离**：仅操作 odc_qoder_ 前缀表，不影响其他数据
- **默认绑定**：服务默认只监听 127.0.0.1:18748，可通过 HOST 环境变量显式覆盖

## 项目结构

```
qoder/
├── src/
│   ├── server.js          # Express 服务器 + API 路由
│   ├── db.js              # 数据库连接与操作
│   └── sample-data.js     # 合成教学样例
├── public/
│   └── index.html         # 前端单页应用
├── scripts/
│   └── init-db.js         # 数据库初始化与 IK/BENG 索引迁移
├── test/
│   └── integration.test.js # 集成测试
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

- **真实 FULLTEXT 搜索**：非前端字符串匹配，使用数据库原生全文索引与 MATCH AGAINST
- **相关度排序**：基于 MATCH AGAINST 自然语言模式评分，标题权重 ×2
- **seekdb IK 解析器**：已在真实 seekdb 验证中英文查询均命中；不使用 MySQL ngram 预设
- **安全设计**：参数绑定 + HTML/属性转义 + 服务端类型/长度校验
- **完整测试**：84 项集成测试覆盖核心功能、真实 HTTP 校验、Markdown 导出标记、排序分数一致性与安全性
- **数据保护**：测试仅清理本次创建的 ID，保留既有资料

## 许可证

MIT

## 团队

参赛者（Qoder辅助开发） - OceanBase 数据库大赛 2026
