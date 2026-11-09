---
id: p-zeifman11
title: Disaggregation of Home Energy Display Data Using Probabilistic Approach
authors: M. Zeifman, K. Roth
year: 2011
venue: IEEE Transactions on Consumer Electronics
methods: HMM, Viterbi, factorial HMM
datasets: 自采住宅数据
---

# 摘要

把负荷分解写成隐马尔可夫模型（HMM）的推断问题：每个电器的运行状态是隐状态，
聚合功率是观测，用电器的状态转移刻画投切行为，用 Viterbi 求最可能的状态序列。
相比逐事件判定，HMM 能利用时间连续性抑制孤立误报。

# 方法

单电器 HMM 的隐状态对应"关/开/多档"，观测为聚合功率（需减去其它已知负荷）。
多电器时使用因子 HMM，状态空间随电器数指数增长，论文用近似推断控制复杂度。
转移矩阵由电器使用统计得到，排放分布用高斯或混合高斯建模。

# 结果

演示数值：在两户自采数据上，单电器状态识别准确率 0.85–0.95；因子 HMM 随电器数增加，
推断耗时增长明显，五台以上时接近实时上限。

# 局限

- 需要预先知道电器清单与转移统计，冷启动阶段效果差。
- 观测是聚合功率，功率相近的电器之间容易混淆。
- 状态空间随电器数量指数增长，不适合全屋几十台电器的场景。
- 该方法直接做状态分解，不显式输出"事件"，与事件式评测口径不一致。
