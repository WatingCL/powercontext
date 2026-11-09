# 验证样例

一组可按步骤执行的样例：初始数据 → 输入 → 操作 → 预期结果 → **PowerContext 发挥作用的记录**。

- 环境：Windows 11 + Python 3.13，PowerContext 1.5.0（模型全留空，Basic memory 模式）
- 初始数据：`data/samples/` 下 5 篇演示语料（重写样本，见该目录 README）
- 一键执行：`bash scripts/demo.sh`（日志自动落 `evidence/logs/`）

> 下面所有输出都是**真实执行结果**，对应日志 `evidence/logs/demo-20261110-014711.log`。

---

## 0. 清净起点

```bash
$ litcontext doctor
数据目录       ...\qoder\.data
本地索引       0 篇 / 0 段（SQLite）
PowerContext   http://127.0.0.1:8000 -> 可用
scope          scp_5jzgwts2bgf6gjxzkhmz8d3mzq（litcontext-nilm-event-detection）
记忆条数       0
```

预期：索引为空、PowerContext 可用、记忆为空。若 PowerContext 显示"不可达"，
先 `powercontext server run`。

---

## 1. 导入：正文进索引，摘要进 Source

```bash
$ litcontext ingest data/samples
[导入] p-hart92   Nonintrusive Appliance Load Monitoring                 5 段
[导入] p-blued12  BLUED - A Fully Labeled Public Dataset ...             5 段
[导入] p-anderson12 Event Detection for Non-Intrusive Load Monitoring    5 段
[导入] p-zeifman11 Disaggregation of Home Energy Display Data ...        4 段
[导入] p-review20 A Review of Non-Intrusive Load Monitoring ...          5 段
完成：新增/更新 5 篇，索引现有 5 篇 24 段
```

**技术记录**：每篇同时写了一条 Source（`POST /v1/sources/content`，
`source_id=litcontext/paper/<paper_id>`），可在 PowerContext 的 Source journal 里查到。

---

## 2. 检索：本地索引返回段落 + 出处

```bash
$ litcontext search "广义似然比 事件检测 误报" --top 3
1. [p-anderson12] 2012 Event Detection for Non-Intrusive Load Monitoring
   §摘要  score=17.06
   本文把事件检测从"阈值比较"提升为"统计检验"：把功率序列的变化看作均值跃变，
   用广义似然比（GLR）与累积和（CUSUM）检测跃变点，再对候选事件做分类。……

2. [p-anderson12] 2012 Event Detection for Non-Intrusive Load Monitoring
   §方法  score=8.38
   GLR 维护两段滑动窗口（跃变前/后），对每一点计算两段均值差的对数似然比……

3. [p-blued12] 2012 BLUED - A Fully Labeled Public Dataset ...
   §结果  score=5.73
   演示数值：以功率阶跃阈值做基线事件检测，事件级 F1 约 0.75……
```

**预期**：`p-anderson12` 排第一（它正是 GLR/CUSUM 那篇），同篇最多取 2 段。
这一步由本地 SQLite + BM25 完成，**不经过 PowerContext**。

---

## 3. 检索召回评测：同义扩展救了哪些漏召回

同一套语料，16 条标注查询（提问用的是研究者的口语，标注是"哪篇真正回答了它"）：

```bash
$ python scripts/eval_recall.py
语料 5 篇 / 24 段；16 条查询
指标                关闭扩展      开启扩展
命中@1             0.375     0.500
命中@3             0.812     0.812
命中@5             0.812     1.000
未命中率             0.188     0.000
MRR              0.573     0.700
已写出 evidence/recall-eval.md
已写出 evidence/recall-eval.json
```

单个例子（`--no-expand` 与默认行为对比）：

```bash
$ litcontext search "维特比解码" --no-expand
没有命中。试试更短的关键词，或先 `litcontext ingest` 导入文献。

$ litcontext search "维特比解码" --explain
查询词 4 个；同义扩展 8 个（权重 0.4）
  原始：比解 特比 维特 解码
  扩展：hmm viterbi 可夫 尔可 状态 隐状 隐马 马尔
  特比 -> hmm 隐马 马尔 尔可 可夫 隐状 状态 viterbi
  维特 -> hmm 隐马 马尔 尔可 可夫 隐状 状态 viterbi

1. [p-zeifman11] 2011 Disaggregation of Home Energy Display Data ...  score=7.68
   §摘要  把负荷分解写成隐马尔可夫模型（HMM）的推断问题……用 Viterbi 求最可能的状态序列。
```

**关键验证点**：语料里只有 `Viterbi`，没有"维特比"三个字，字面检索必然为零；
扩展后不仅命中，还排第一。扩展词逐个可见（`--explain`），不是黑箱。

**代价也如实记**：16 条里有 1 条名次下降（"deep learning 在 NILM 上" 第 3 → 第 4），
因为扩展词稀释了原词权重。完整逐条结果见 `evidence/recall-eval.md`。

---

## 4. 写下研究判断：11 条记忆进 PowerContext

```bash
$ litcontext note --kind finding --paper p-anderson12 --topic 事件检测 \
    --text "GLR/CUSUM 这类统计检验在大幅跃变上对误报的控制明显好于固定阈值" \
    --evidence "BLUED，|ΔP|>300W，精确率 0.86"
[记忆已写入] finding -> {"changed": true, "records": [{"artifact": {...}}]}

$ litcontext note --kind decision --topic 事件检测 --method HMM --verdict reject \
    --text "因子 HMM 状态空间随电器数指数增长，全屋场景推断耗时不可接受" \
    --reason "算力有限，且事件式评测需要显式事件输出"
[记忆已写入] decision -> ...

$ litcontext note --kind constraint \
    --text "只用 REDD house1，不外采数据；评测必须报事件级 F1 与匹配容差窗口"
[记忆已写入] constraint -> ...

$ litcontext edge --paper p-anderson12 --method GLR --dataset BLUED --metric F1 --value 0.89 --note "|ΔP|>300W"
[记忆已写入] edge

$ litcontext progress --done "读完 5 篇事件检测基础文献并做了取舍" \
    --current "在 REDD house1 上复现阈值基线" --next "对比 GLR 与 CUSUM 的小跃变误报率"
[记忆已写入] progress
```

**技术记录**：每类各调一次 `POST /v1/memory/remember`，kind 分别为
`finding` / `decision` / `constraint` / `edge` / `progress`，正文是单行 JSON（前缀 `LITCORE|`），
`reason` 字段单独存"为什么"。

累积结果：

```bash
$ litcontext doctor
...
记忆条数       11  {'edge': 3, 'constraint': 1, 'decision': 3, 'finding': 3, 'progress': 1}
```

---

## 5. 召回：换一个进程，上下文仍在

```bash
$ litcontext resume
# 上次的进度

- 已完成：读完 5 篇事件检测基础文献并做了取舍
- 正在做：在 REDD house1 上复现阈值基线
- 下一步：对比 GLR 与 CUSUM 的小跃变误报率
- 记录时间：2026-11-10 01:35

## 已经否掉的方向（别再走一遍）

- **HMM**：因子 HMM 状态空间随电器数指数增长，全屋场景推断耗时不可接受
- **固定阈值**：固定阈值跨户迁移会明显掉点，需按户重标定，不适合作为毕设主线

## 实验约束

- 只用 REDD house1，不外采数据；评测必须报事件级 F1 与匹配容差窗口

## 已积累的结论（3 条）
...

## 上下文预算

- 状态：`ready`　占用：3592 / 4000 字节

PowerContext 调用：
  POST /v1/scopes -> 200
  POST /v1/memory/search -> 200
  POST /v1/context/prepare -> 200
```

**关键验证点**：

1. `resume` 是**独立进程**，没有任何本地缓存参与召回 —— 内容全部来自 PowerContext。
2. `状态 ready / 3592 / 4000 字节` 是 `POST /v1/context/prepare` 的真实返回值
   （`status`、`content_bytes`、`max_bytes`），说明召回是**有界**的，不是全量倾倒。
3. 掉过服务再启动，`resume` 输出不变 —— 记忆落盘在 PowerContext 的 sqlite 里。

---

## 6. 出稿：初稿与对比表

```bash
$ litcontext brief --topic 事件检测 -o out/brief.md
已写出 out/brief.md（1891 字符，引用 6 段原文）

$ litcontext compare -o out/compare.md
已写出 out/compare.md（3 条对比记忆）
```

`out/brief.md` 结构（完整内容见 `evidence/snapshots/brief.md`）：

```markdown
# 综述初稿：事件检测

## 研究脉络
- **2012**　Event Detection for Non-Intrusive Load Monitoring　`[p-anderson12]`
- **2012**　BLUED - A Fully Labeled Public Dataset ...　`[p-blued12]`
- **2020**　A Review of Non-Intrusive Load Monitoring ...　`[p-review20]`

## 已有结论
- GLR/CUSUM 这类统计检验在大幅跃变上对误报的控制明显好于固定阈值 `[p-anderson12]`（依据：BLUED，|ΔP|>300W，精确率 0.86）
...

## 已排除的路线（附理由）
- **HMM**：因子 HMM 状态空间随电器数指数增长……
- **固定阈值**：固定阈值跨户迁移会明显掉点……

## 实验约束
- 只用 REDD house1……

## 可直接引用的原文段落
- GLR 维护两段滑动窗口……`[p-anderson12 方法]`
...

## 参考文献
- [p-anderson12] K. D. Anderson, ... IECON, 2012.
```

`out/compare.md`：

```markdown
# 方法对比表

## 数据集：BLUED

| 方法 | 指标 | 数值 | 来源 | 备注 |
| --- | --- | --- | --- | --- |
| GLR | F1 | 0.89 | `[p-anderson12]` | \|ΔP\|>300W |
| 固定阈值 | F1 | 0.75 | `[p-blued12]` | 基线 |
```

**对照点**：初稿里的"已排除的路线"和"实验约束"两节，**只可能来自 PowerContext 记忆**
（本地索引里没有任何段落写过"我不选 HMM"）；"可直接引用的原文段落"只可能来自本地索引。
两份材料各自负责一半，来源在输出里是分开的。

---

## 7. Web UI（可选）

```bash
$ litcontext serve --port 8765
浏览器打开 http://127.0.0.1:8765/
```

三块面板分别标注了数据来源：`SQLite · BM25` / `PowerContext` / `检索结果 + 记忆`。
右上角徽标显示 PowerContext 是否连通。截图见 `evidence/snapshots/ui-01-home.png`。

**动手验证"记忆真的在 PowerContext 里"**：

1. 在右侧表单写一条记忆 → 点"写入记忆"，面板立刻多一条；
2. `Ctrl+C` 停掉 Web UI，再 `litcontext serve` 重启；
3. 刷新页面，那条记忆还在（浏览器没有存任何东西，storage 里也没有）。

---

## 8. 单元测试（不依赖 PowerContext）

```bash
$ cd litcontext && python -m unittest discover -s tests
....................
Ran 20 tests in 0.500s
OK
```

---

## 附：验证清单

| # | 断言 | 怎么核对 | 结果 |
| --- | --- | --- | --- |
| 1 | 文献能导入并切块 | `litcontext papers` 列出 5 篇 | ✅ 5 篇 / 24 段 |
| 2 | 检索能定位到正确论文 | `search 广义似然比` 首条为 `p-anderson12` | ✅ |
| 3 | 记忆真实写入 PowerContext | `doctor` 显示 11 条且分类型统计 | ✅ |
| 4 | 跨进程召回 | 新进程执行 `resume` 拿到完整上下文 | ✅ |
| 5 | 召回有界 | `PreparedContext` 状态 ready，3592/4000 字节 | ✅ |
| 6 | 出稿引用可追溯 | 初稿每条论断带 `[paper_id]`，共 6 段原文 | ✅ |
| 7 | 服务重启后记忆仍在 | 重启 `powercontext server run` 后 `resume` 输出不变 | ✅ |
| 8 | 同义扩展救回字面漏召回 | `search 维特比解码 --no-expand` 空 / 默认命中 `p-zeifman11` | ✅ 16 条查询未命中率 19% → 0 |
| 9 | 干净环境可从零复现 | GitHub Actions `qoder-litcontext-verify` 全绿 | ✅ 见仓库 Actions |
