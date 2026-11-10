# RUNBOOK · 从零复现

## 0. 环境要求

| 项 | 要求 |
| --- | --- |
| Node.js | **22 或更高**（seekdb 原生运行时要求 ≥22；本机 22.22.2 验证） |
| 浏览器 | Chrome / Edge 最新版（WebGPU 可选，没有则自动走 WASM） |
| 磁盘 | 约 1.2GB（依赖 600MB + 模型 160MB + 数据库目录） |
| 网络 | 仅首次安装依赖与下载模型需要 |

## 1. 安装依赖

```bash
cd stepfun
npm install
```

> 仓库带 `.npmrc`（`legacy-peer-deps=true`）。seekdb 的 `@seekdb/default-embed` 与主包的 peer 声明不兼容，不加这个参数会报 `EUNSUPPORTEDPROTOCOL workspace:*`。

## 2. 下载模型（三档精度，共 159MB）

```bash
npm run setup:model
```

默认走 `hf-mirror.com`，失败自动换 `huggingface.co`；两者都不可用时手动下载放到 `public/models/bge-small-zh-v1.5/`：

```
config.json  tokenizer.json  tokenizer_config.json  special_tokens_map.json  vocab.txt
onnx/model.onnx  onnx/model_fp16.onnx  onnx/model_int8.onnx
```

来源：<https://huggingface.co/Xenova/bge-small-zh-v1.5>（BAAI/bge-small-zh-v1.5 的 ONNX 转换版，512 维）。

## 3. 启动

```bash
npm run dev
```

会同时起两个进程：

- `node server/index.mjs` → API 与本地 seekdb（默认 8787）
- `vite` → 前端（默认 5173）

浏览器打开 **http://127.0.0.1:5173**。

首次启动会初始化数据库目录，约 2–3 秒；控制台会打印实际数据目录与端口。

## 4. 演示流程

1. 左上角已自动创建 `kb-default` 集合
2. 点「载入示例语料」→ 12 篇文档切成 47 块 → 本地向量化 → 写入 seekdb → 自动刷新索引
3. 输入问题（例如「冰箱启动的功率增量大概是多少」）→ 看排序结果、分数与分阶段时延
4. 右上下拉切换推理配置（WASM INT8 / WASM FP32 / 强制 WebGPU）可以复现三档对比
5. 「跑基准」按钮会把 10 次端到端时延写进 `evidence/browser-bench.json`

## 5. 复现质量评测（不需浏览器）

```bash
# 另开一个终端，先让 API 运行
node server/index.mjs

# 再跑评测：三档精度 × 混合/纯向量 两条检索路径
npm run eval
```

输出 `evidence/eval-<时间戳>.json` 与控制台表格（Recall@5 / nDCG@10 / MRR / 向量保真度 / 排序一致性）。

## 6. 常见问题

**Q：启动报 `Cannot create/access database directory ... errno=2`**
seekdb 原生层无法处理含中文的路径。本项目会自动降级到 `D:\stepfun-kb-data\seekdb`（或当前盘符根目录下的 `stepfun-kb-data`），控制台会打印提示。想固定位置就设环境变量：

```bash
SEEKDB_DIR=D:\seekdb-data npm run dev      # Windows PowerShell: $env:SEEKDB_DIR="D:\seekdb-data"
```

**Q：端口被占用**
`PORT=8788 node server/index.mjs`，同时把 `vite.config.ts` 里的代理目标改掉。

**Q：想清空数据库重来**
```bash
npm run reset
```

**Q：不想让数据库占内存**
默认 `memory_budget=1G`，可用 `SEEKDB_MEMORY=512M npm run dev` 降低。

**Q：界面一直显示「推理后端待检测」**
看浏览器控制台。常见原因是模型文件没下载（`public/models/...` 缺失），或浏览器既没有 WebGPU 又禁用了 WASM。
