# 验证证据

所有文件都由仓库内脚本生成，可重跑。

| 文件 | 生成方式 | 说明 |
| --- | --- | --- |
| `eval-latest.json` / `eval-<时间戳>.json` | `npm run eval` | 三档精度（FP32/FP16/INT8）× 两条检索路径（混合 / 纯向量）的 Recall@5、nDCG@10、MRR，含逐条查询明细、模型体积、压缩比、向量保真度、Top1/Top5 排序一致性 |
| `browser-check.json` | `node scripts/browser-check.mjs` | 无头 Chrome 真实加载模型、导入语料、检索、跑基准的结果记录，含后端徽标、选择理由、导入日志、分阶段时延 |
| `browser-bench.json` | 界面「跑基准」按钮（10 次） | 浏览器侧端到端时延原始数据：每次耗时、中位数、后端与精度、语料规模、UA |
| `shot-1-imported.png` | 同上 | 导入完成后的界面（进度、块数、写入与刷新耗时） |
| `shot-2-search.png` | 同上 | 混合检索结果 + 分阶段时延 + 检索路径 |
| `shot-3-bench.png` | 同上 | 基准测试后的界面 |

## 环境

见 `browser-check.json` 的 `userAgent` 与 `backend` 字段；数据库版本见 `/api/health` 输出（seekdb v1.4.0）。

## 复现命令

```bash
node server/index.mjs      # 终端 1
npm run eval               # 终端 2（质量指标，不需要浏览器）

npx vite --port 5173       # 终端 3
node scripts/browser-check.mjs   # 终端 4（浏览器侧，需要本机安装 Chrome）
```
