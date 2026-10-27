# Local Seek：浏览器本地向量化知识库

浏览器使用 Transformers.js 3.8.1 / ONNX Runtime 加载公开的 [Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2/tree/751bff37182d3f1213fa05d7196b954e230abad9)（固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`），生成 384 维归一化向量。默认 INT8；优先检查 WebGPU adapter，不可用时明确回退 WASM。若 GPU 初始化中途失败，销毁 Worker 后在新 Worker 中重试 WASM，避免失败的运行时初始化状态污染后续请求。

Node 服务不加载任何向量模型，仅通过 seekdb-js 1.3.0 调用真实 seekdb。建库禁用服务端 embeddingFunction，导入必须传入浏览器向量。全文候选、向量候选和 RRF 融合均在 seekdb `hybridSearch` 内完成，没有前端或服务端手工拼接排名。

## 启动

支持 Chrome / Edge 现代版本。先准备原生 seekdb 1.4.0 server（[源码与安装说明](https://github.com/oceanbase/seekdb)）；本次验证使用 Windows 原生构建。提供 `start-seekdb.ps1`：

```powershell
.\start-seekdb.ps1 -SeekdbExe 'C:\seekdb\seekdb.exe' -DataDirectory 'C:\seekdb-data\local-seek' -Port 2881
```

路径替换为实际可执行文件和专用数据目录。脚本保留数据，不停止或覆盖已有实例；端口占用时拒绝启动。用 MySQL 兼容客户端连接后执行 `CREATE DATABASE IF NOT EXISTS test;`。Linux 原生 server 可用相同 `--nodaemon --base-dir --port --parameter` 参数启动；此包不宣称已在 Linux 浏览器完成验收。

需要 Node.js 20+ 和运行中的 seekdb。默认连接 `127.0.0.1:2881` 的 `test` 库，root 空密码；可通过 `SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE` 配置，凭据只保留在后端环境中。

```sh
cd stepfun/app
npm ci --ignore-scripts --legacy-peer-deps
npm run dev
```

默认网页 `http://127.0.0.1:5173`，可用 `PORT` 修改。仅绑定本机回环地址。`npm run build` 生成静态资源；生产模式设置 `NODE_ENV=production` 后启动同一服务。

新建集合 → 导入示例、TXT 或手写文档 → 查询。相同文档 ID 增量 upsert，每次写入调用 `refresh_index()`；也可手动刷新索引。集合列表和数量均从数据库读取，刷新页面后仍保留。TXT 使用文件名作为 ID，重复导入会更新对应文档。导入/查询开始时固定目标集合，执行期间锁定集合、模型与文件输入；Worker 依序处理请求，避免模型切换释放仍在使用的推理实例。切换集合会清空旧结果。

## 一页技术说明与实测

模型采用该固定版本发布的 ONNX FP32 文件与 INT8 `model_quantized.onnx`，Transformers.js 通过 `dtype: q8` 选择预量化权重；本项目不训练模型，也不将服务端推理结果回放。模型采用 Apache-2.0 许可，原始模型来源见上方模型卡。统计口径为各配置实际下载的单个 ONNX 权重文件字节数，不包括两组共用的 tokenizer/config 和运行时。

2026-10-27，AMD Ryzen 9 8945HX、32 逻辑线程、Windows、Edge 156.0.0.0，原生 seekdb 1.4.0（4 GB 内存、端口 2881），ONNX WASM 1 线程。固定 12 篇英文文档、8 个单一相关文档标注问题，数据在 `app/src/sample.js`，批大小为 12；先首次加载与导入，再预热查询模型，执行 3 轮完整写入/刷新与检索。逐查询的向量与数据库结果均实际产生。原始数据见 [本次三轮报告](evidence/benchmark-review-20261027.json)，旧单轮报告保留作历史记录。

| 项目 | FP32 | INT8 |
|---|---:|---:|
| ONNX 模型字节数 | 90,387,606 | 22,972,370 |
| 首次下载与模型初始化 | 18,002.3 ms | 6,107.9 ms |
| 首次 12 篇向量化 | 388.8 ms | 225.4 ms |
| 预热后 12 篇向量化中位数 | 346.7 ms | 218.5 ms |
| 写入并刷新中位数 | 539.6 ms | 629.3 ms |
| 单查询向量化中位数 | 11.35 ms | 7.30 ms |
| seekdb 混合检索中位数 | 4.27 ms | 4.20 ms |
| 单查询端到端中位数 | 26.60 ms | 21.15 ms |
| Recall@5 | 1.000 | 1.000 |
| nDCG@5 | 0.9539 | 0.9539 |

压缩比为 3.9346，体积减少 74.6%；文档推理耗时减少 37.0%，查询端到端耗时减少 20.5%，本评测集质量无下降。写入与刷新没有加速（本轮 INT8 反而较慢），不将量化解释为数据库写入优化。首次加载计时包含模型资源获取和初始化，受网络/缓存影响，不用于稳态加速结论。端到端覆盖提交查询向量化至浏览器取得可展示结果的往返耗时；日常检索界面另计结果 DOM 更新完成时间。中位数保留所有轮次，偶数样本取中间两值平均，不挑最快一次。

数据层：384 维 cosine HNSW + BENG 全文索引，原文/ID/title/model/dtype 一并写入；`embeddingFunction: null` 禁用数据库端向量化。seekdb-js 1.3.0 的 `hybridSearch` 在 seekdb 内以 RRF 融合两路各 20 个候选，返回最多 5 条。每批 upsert 后统一 `refresh_index()`，减少逐文档刷新；连续导入按 ID 更新，集合/会话从数据库读取并在页面恢复选择。评测每次新建独立集合，避免残留文档影响结果。

端侧策略：显式优先 `device: webgpu`，无 adapter 时使用 WASM；GPU 初始化失败时在新 Worker 重建 WASM。界面显示当前设备。本机浏览器未提供可用 GPU adapter；本次已用默认 WebGPU 选项验证自动回退，成功返回 Browser inference 原文（[运行截图](evidence/fallback-review-20261027.png)）。实现满足“支持时优先、不可用时回退”的条件逻辑；题面 3.2 第 6 项要求的双环境测试，目前覆盖了不可用环境，WebGPU 可用环境尚未实测。可在提供 adapter 的设备上按下列步骤补充记录。

## 验收复现

1. 按启动说明打开页面，新建 `review_knowledge`，保持“优先 WebGPU”，导入 12 篇示例，观察进度、实际后端与集合计数。
2. 查询 `How can a browser run a model without a GPU?`，应看到 Browser inference 原文；记录界面的实际后端和三段计时。无 adapter 时应自动显示 WASM，仍可完成查询。
3. 再导入同一批示例，计数仍是 12；添加一篇新的手写文档后计数变为 13，查询其中的词可找到新内容。
4. 新建另一个集合，旧结果应清空；切回原集合仍能检索 13 篇内容。导入过程中集合、模型、文件选择均锁定，不能将请求误送到另一集合。
5. 点击“运行真实对照评测”，等待 FP32/INT8 各 3 轮完成，导出 JSON。报告记录每次真实结果及时间；未运行不会预填成绩。公开模型首次需联网下载。
6. 用显式 WASM 重复第 1–2 步；在有真实 WebGPU adapter 的环境用默认选项重复，保存显示 WebGPU 的截图和结果，才可补齐双后端验证。若自动回落，记录原因，不能标作 GPU 成功。
7. `npm test` 在运行中的服务执行自包含数据层测试；服务默认 5173，可用 `TEST_URL` 指定地址。测试使用明确标注的合成向量，只检查增量写入、更新、集合隔离与无效输入；真实模型质量以浏览器评测报告为准。

小型英文数据集用于可重复验收，不代表大规模准确率。更换多语言模型需同步维数并新建集合。所有截图和报告均对应实际运行，不作为官方评分替代。

## 数据边界

本地推理不等于全程不联网：首次加载从 Hugging Face 下载模型，文档与向量发送到配置的 seekdb。数据库之外没有外部向量化接口。应用作为本机演示，不提供公网多用户鉴权。请求限制为每批 128 篇、每篇 20,000 字符和 384 维有限数值向量。
