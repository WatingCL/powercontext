"""查询侧同义词扩展：把"提问时怎么说"映射到"论文里怎么写"。

NILM 领域同一个概念有多种说法：投切 / 开关动作 / 事件、误报 / 虚警 / false alarm、
GLR / 广义似然比 / 似然比、隐状态 / HMM / 隐马尔可夫。论文正文固定用一种写法，
而研究者提问时用的是另一种，BM25 只认字面重合，于是出现"明明读过却搜不到"。

这里补一层领域词表：命中一组中的任一说法，就把同组其它说法按较低权重
（`SYNONYM_WEIGHT`）加进查询。权重取 0.4 不是拍的，是在
`evidence/recall-eval.md` 里用 16 条标注查询比出来的（关闭/开启两组的召回差异）。

刻意不引入向量模型：词表可读、可审计、离线可跑，扩展了哪些词能逐条打印出来
（`litcontext search --explain`），评审可以自己核对有没有瞎扩。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from .text import tokenize

# 扩展词的权重：原词 1.0，同组替换说法 0.4（低于原词，避免扩出来的词盖过字面命中）
SYNONYM_WEIGHT = 0.4
# 单个查询词最多扩展出多少个 token，防止一个泛词把查询稀释成"什么都匹配"
MAX_PER_TOKEN = 8

# 每组是一个概念，组内任意两种说法视为近义。
# 顺序有意义：靠前的说法优先被采用（达到 MAX_PER_TOKEN 就停）。
GROUPS: List[Tuple[str, List[str]]] = [
    ("event", ["投切", "事件", "开关动作", "开关事件", "通断", "跃变", "阶跃", "突变",
               "状态切换", "edge", "transition"]),
    ("detect", ["检测", "判别", "侦测", "定位", "detection", "detect"]),
    ("false_alarm", ["误报", "虚警", "误检", "假阳性", "false alarm", "false positive"]),
    ("miss", ["漏报", "漏检", "假阴性", "miss", "false negative"]),
    ("threshold", ["阈值", "门限", "判决阈值", "threshold", "cutoff"]),
    ("calibrate", ["标定", "校准", "调参", "重新标定", "calibration"]),
    ("glr", ["glr", "广义似然比", "似然比", "假设检验", "likelihood ratio"]),
    ("cusum", ["cusum", "累积和", "序贯"]),
    ("hmm", ["hmm", "隐马尔可夫", "马尔可夫", "隐状态", "viterbi", "维特比"]),
    ("disagg", ["负荷分解", "功率分解", "负荷辨识", "负荷识别", "非侵入",
                "disaggregation", "nilm"]),
    ("dataset", ["数据集", "公开数据", "dataset", "benchmark"]),
    ("label", ["标注", "标记", "真值", "label", "annotation", "ground truth"]),
    ("window", ["滑动窗口", "窗口", "窗长", "时间容差", "window"]),
    ("sampling", ["采样率", "采样", "sampling", "sample rate"]),
    ("precision", ["精确率", "查准率", "精度", "precision"]),
    ("recall", ["召回", "查全率", "recall"]),
    ("f1", ["f1", "调和平均", "f1-score"]),
    ("steady", ["稳态", "稳态功率", "steady state"]),
    ("transient", ["暂态", "瞬态", "transient"]),
    ("realtime", ["实时", "在线", "流式", "realtime", "online"]),
    ("small_step", ["小跃变", "小幅", "小功率", "小阶跃", "small step"]),
]


def _index_groups() -> Dict[str, Dict[str, float]]:
    """token -> {同组其它说法拆出的 token: 权重}。

    说法本身也要按同一套规则分词，否则"广义似然比"这种多字词永远匹配不上
    中文二元组索引（索引里存的是"广义/义似/似然/然比"）。
    """
    mapping: Dict[str, Dict[str, float]] = {}
    for _, surfaces in GROUPS:
        tokenized = {surface: tokenize(surface) for surface in surfaces}
        for surface, tokens in tokenized.items():
            for token in tokens:
                bucket = mapping.setdefault(token, {})
                for other, other_tokens in tokenized.items():
                    if other == surface:
                        continue
                    if len(bucket) >= MAX_PER_TOKEN:
                        break
                    for sub in other_tokens:
                        if sub != token and sub not in bucket:
                            bucket[sub] = SYNONYM_WEIGHT
    return mapping


_MAP: Dict[str, Dict[str, float]] = _index_groups()


def expand(tokens: Iterable[str]) -> Dict[str, float]:
    """返回 {token: 权重}：原词 1.0，同组扩展词 `SYNONYM_WEIGHT`。"""
    weights: Dict[str, float] = {}
    for token in tokens:
        weights[token] = 1.0
    for token in tokens:
        for other, weight in _MAP.get(token, {}).items():
            if other not in weights:
                weights[other] = weight
    return weights


def explain(tokens: Iterable[str]) -> List[Tuple[str, List[str]]]:
    """用于 `search --explain`：逐条说明每个原词扩出了什么。

    允许传原词（"维特比"）也允许传已分好的 token（"维特"），内部统一再过一遍
    分词——传原词时若直接查表会查不到，静默返回空，是个容易踩的坑。
    """
    normalized: List[str] = []
    for item in tokens:
        normalized.extend(tokenize(item) or [item])
    rows: List[Tuple[str, List[str]]] = []
    seen = set()
    for token in normalized:
        if token in seen:
            continue
        seen.add(token)
        added = [other for other in _MAP.get(token, {}) if other != token]
        if added:
            rows.append((token, added))
    return rows
