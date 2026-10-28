# Qoder 开发记录

## 账号信息

- Qoder CN 账号：`nick1693700399`
- 账号 UUID：`01a17d35-a7d3-7e86-9df1-a58cbea0c743`
- 用途：项目主要开发在 Qoder 桌面端完成，网站通过 Qoder Sites 发布，账号信息用于核对站点归属与使用记录。

## Qoder 在本项目中承担的工作

| 环节 | Qoder 完成的内容 |
| --- | --- |
| 需求拆解 | 阅读赛题，确认基础验收的四条标准（网站可访问 / 项目可运行 / 开发可核对 / 技术结合有效），据此确定"一条命令跑通、零外部服务"的目标 |
| 技术选型 | 对比 seekdb 的嵌入式、服务端、Docker 三种接入方式，选择 `pyseekdb` 嵌入式以保证评审环境可复现；确认 `hybrid_search` 的 RRF 融合与 `where_document` 全文过滤能力 |
| 数据建模 | 设计单 collection 结构：正文 + `doc_id/title/source/page/topic` 元数据 + 复习状态字段，检索与复习共用一张表 |
| 编码 | 实现 `pagetrail/library.py`（seekdb 封装）、`embedding.py`（离线确定性嵌入）、`review.py`（简化 SM-2）、`corpus.py`（合成语料）、`web.py`（标准库 HTTP 服务与 JSON API）、`static/index.html`（单页界面） |
| 调试 | 定位并修复了自定义嵌入类未注册导致重开失败、`get` 与 `query` 返回结构不一致、`update` 整块替换元数据等问题（见下） |
| 验证 | 编写 `demo.py` 的 12 项自检与 20 个单元测试，产出 `evidence/` 下的运行日志与界面截图 |
| 文档 | 编写 README、运行说明、验证样例与本站点内容 |

## 关键迭代记录

1. **技术可行性验证**：先在 Windows 上安装 `pyseekdb 1.4.0.post1 + pylibseekdb 1.4.0.post2`（官方提供 `win_amd64` 轮子），确认嵌入式引擎可启动；再用一个最小脚本验证中文 `$contains`、`$in/$and/$lte` 元数据过滤、`hybrid_search` 的 RRF 排序都能正常工作。
2. **确定嵌入方案**：pyseekdb 默认嵌入会下载 ONNX 模型（英文 MiniLM），对中文资料不合适且需要联网。改为项目内置的离线确定性哈希嵌入，保证评审在断网、干净环境下结果完全一致。
3. **第一次运行失败**：自定义 `EmbeddingFunction` 的类名被持久化进 collection 元数据，重新打开时报 `Embedding function class 'pagetrail-local-hash-v1' not found`。用 `pyseekdb.register_embedding_function` 注册后解决。
4. **返回结构适配**：`collection.get()` 返回扁平列表，而 `query()` / `hybrid_search()` 返回按查询嵌套的列表，统一在 `_rows()` 中兼容。
5. **元数据更新语义**：实测 `collection.update(ids=..., metadatas=...)` 会**整块替换**元数据而不是合并，因此复习评分改为"读出现有元数据 → 合并新状态 → 整体写回"。
6. **检索质量调整**：三通道对比发现全文通道存在文档长度偏置（短文档更容易排前），而混合后的 Top-1 更符合预期；演示中保留这一对比作为技术结合的直观证据。
7. **界面与证据**：补充可分享的检索深链接、复习队列面板；用无头 Chrome 截图产出 `evidence/ui-search.png`、`evidence/ui-channel.png`。
8. **Linux 干净环境验证**：在 GitHub Actions（ubuntu-latest + Python 3.12）上跑同一套命令，发现"同一进程内重复打开数据目录"会与嵌入式引擎的本地 socket 启动时机竞争，报 `Can't connect to local server through socket`。进一步实验确认嵌入式引擎按进程绑定首个数据目录，因此把跨进程持久化用例改成"子进程写入 + 另一个子进程读回"，并给引擎启动加了指数退避重试，使 Windows / Linux 行为一致。

## 环境与复现

- 开发与验证环境：Windows 11 + Python 3.12.10；seekdb 以嵌入式方式运行（`pylibseekdb` win_amd64）。
- README 中的命令在 Linux x86_64 / macOS(arm64) 上同样适用，`requirements.txt` 已按平台区分依赖。
- 持续验证：GitHub Actions `qoder-ci`（ubuntu-latest + Python 3.12）依次执行依赖安装、20 个单元测试、`demo.py` 与 Web 接口冒烟测试，运行记录见 <https://github.com/caibolol/ODC_PowerContext/actions/workflows/qoder-ci.yml>。
- 作品介绍网站由 Qoder Sites 发布：<https://pagetrail-ul4zn1269im.qoder.zone>，静态源码在 `site/`。
- 运行日志：[evidence/demo-run.txt](evidence/demo-run.txt)（12/12 通过）、[evidence/tests.txt](evidence/tests.txt)（20 个用例全部通过）。

## 说明

- 语料为合成教学样例，`example.com` 一类的占位信息不涉及真实文献或真实用户数据。
- 配置与代码中不含任何真实 API Key、密码或其他凭据。
