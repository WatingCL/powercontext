# 综述初稿：事件检测

## 研究脉络

- **2012**　Event Detection for Non-Intrusive Load Monitoring　`[p-anderson12]`
- **2012**　BLUED - A Fully Labeled Public Dataset for Event-Based Non-Intrusive Load Monitoring Research　`[p-blued12]`
- **2020**　A Review of Non-Intrusive Load Monitoring - Methods, Datasets and Evaluation　`[p-review20]`

## 已有结论

- GLR/CUSUM 这类统计检验在大幅跃变上对误报的控制明显好于固定阈值 `[p-anderson12]` （依据：BLUED，|ΔP|>300W，精确率 0.86）
- BLUED 是单户高密度事件标注，适合事件级评测，不适合训练数据驱动模型 `[p-blued12]` （依据：单户约一周）
- 事件式方法在公开数据上 F1 多在 0.7–0.9，误差主要来自小跃变与多电器同时投切 `[p-review20]` （依据：综述汇总）

## 已排除的路线（附理由）

- **HMM**：因子 HMM 状态空间随电器数指数增长，全屋场景推断耗时不可接受
- **固定阈值**：固定阈值跨户迁移会明显掉点，需按户重标定，不适合作为毕设主线

## 实验约束

- 只用 REDD house1，不外采数据；评测必须报事件级 F1 与匹配容差窗口

## 可直接引用的原文段落

- 本文把事件检测从"阈值比较"提升为"统计检验"：把功率序列的变化看作均值跃变， 用广义似然比（GLR）与累积和（CUSUM）检测跃变点，再对候选事件做分类。作者报告在 BLUED 上， 统计检验类方法比固定阈值基线在误报控制上更稳。 `[p-anderson12 摘要]`
- 演示数值：以功率阶跃阈值做基线事件检测，事件级 F1 约 0.75，误报集中在多电器同时投切与待机功率波动。 `[p-blued12 结果]`
- GLR 维护两段滑动窗口（跃变前/后），对每一点计算两段均值差的对数似然比，超过阈值的点判为候选事件； CUSUM 则累积偏离参考均值的残差。两者都需要设定"最小可检测跃变幅值"和"判决阈值"。 论文的一个关键做法是把事件检测与事件分类分开评测，避免分类误差掩盖检测误差。 `[p-anderson12 方法]`
- 事件式 NILM 研究长期缺少带完整标注的公开数据。BLUED 采集单户住宅约一周的高频电压电流， 并对每一次电器投切给出人工标注的事件时刻与电器标签，用来支撑事件检测与负荷辨识的可复现评测。 `[p-blued12 摘要]`
- 演示数值：在公开数据上，事件式方法的检测 F1 多在 0.7–0.9，主要误差来源依次是 小幅跃变、多电器同时投切、以及跨户的阈值失效。 `[p-review20 结论]`
- 本文按"是否显式检测事件"把 NILM 分成事件式与非事件式两条路线。事件式先检测投切事件再做辨识， 中间结果可解释、便于人工核查；非事件式直接把功率序列映射到各电器功率，端到端但对数据量要求高。 `[p-review20 摘要]`

## 参考文献

- [p-anderson12] K. D. Anderson, M. E. Berges, A. Ocneanu, D. Benitez, J. M. F. Moura. Event Detection for Non-Intrusive Load Monitoring. IECON, 2012.
- [p-blued12] K. Anderson, A. Ocneanu, D. Benitez, D. Carlson, A. Rowe, M. Berges. BLUED - A Fully Labeled Public Dataset for Event-Based Non-Intrusive Load Monitoring Research. SustKDD, 2012.
- [p-review20] 综述整理（演示样本）. A Review of Non-Intrusive Load Monitoring - Methods, Datasets and Evaluation. 演示样本, 2020.
