# Local Seek：浏览器本地向量化知识库

浏览器使用 Transformers.js 3.8.1 / ONNX Runtime 加载公开的 `Xenova/all-MiniLM-L6-v2`，生成 384 维归一化向量。默认 INT8；优先检查 WebGPU adapter，不可用时明确回退 WASM。若 GPU 初始化中途失败，销毁 Worker 后在新 Worker 中重试 WASM，避免失败的运行时初始化状态污染后续请求。

Node 服务不加载任何向量模型，仅通过 seekdb-js 1.3.0 调用真实 seekdb。建库禁用服务端 embeddingFunction，导入必须传入浏览器向量。全文候选、向量候选和 RRF 融合均在 seekdb `hybridSearch` 内完成，没有前端或服务端手工拼接排名。

## 启动

需要 Node.js 20+ 和运行中的 seekdb。默认连接 `127.0.0.1:2881` 的 `test` 库，root 空密码；可通过 `SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE` 配置，凭据只保留在后端环境中。

```sh
cd stepfun/app
npm ci --ignore-scripts --legacy-peer-deps
npm run dev
```

默认网页 `http://127.0.0.1:5173`，可用 `PORT` 修改。仅绑定本机回环地址。`npm run build` 生成静态资源；生产模式设置 `NODE_ENV=production` 后启动同一服务。

新建集合 → 导入示例、TXT 或手写文档 → 查询。相同文档 ID 增量 upsert，每次写入调用 `refresh_index()`；也可手动刷新索引。集合列表和数量均从数据库读取，刷新页面后仍保留。TXT 使用文件名作为 ID，重复导入会更新对应文档。

## 实测

2026-10-27 在 Windows / Edge 的真实浏览器中运行，连接本机 seekdb 1.4.0。当前浏览器没有提供 GPU adapter，实际执行设备为 WASM；没有声称已测得 GPU 加速。

原始结果见 `evidence/benchmark-20261027.json`，界面截图见同目录。固定 12 篇英文文档、8 个标注问题，两组均使用 WASM，独立建库并真实查询：

| 项目 | FP32 | INT8 |
|---|---:|---:|
| ONNX 模型字节数 | 90,387,606 | 22,972,370 |
| 12 篇文档向量化 | 511.2 ms | 254.7 ms |
| 8 个查询向量化 | 108.6 ms | 71.1 ms |
| 数据库平均混合检索 | 4.65 ms | 4.66 ms |
| Recall@5 | 1.000 | 1.000 |
| nDCG@5 | 0.9539 | 0.9539 |

INT8 权重体积减少约 74.6%。这是小型功能数据集的一次实测，不代表大规模准确率或稳态吞吐。FP32 首次加载包含网络下载，INT8 已缓存，因此不使用总耗时比较速度；上表只比较推理计时。评测按钮可重新生成两组真实结果并导出 JSON，未运行时不会显示预填成绩。示例采用英文，因为本模型主要适用于英文语义；更换多语言模型需同时调整维数并新建集合。

## 数据边界

本地推理不等于全程不联网：首次加载从 Hugging Face 下载模型，文档与向量发送到配置的 seekdb。数据库之外没有外部向量化接口。应用作为本机演示，不提供公网多用户鉴权。请求限制为每批 128 篇、每篇 20,000 字符和 384 维有限数值向量。
