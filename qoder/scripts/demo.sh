#!/usr/bin/env bash
# 一键跑通验证样例：导入 -> 检索 -> 记忆 -> 召回 -> 出稿
# 用法：bash scripts/demo.sh            （litcontext 已在 PATH 中）
#      LITCONTEXT=/path/to/litcontext bash scripts/demo.sh
set -euo pipefail

cd "$(dirname "$0")/.."
LC="${LITCONTEXT:-litcontext}"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="evidence/logs/demo-${STAMP}.log"
mkdir -p evidence/logs out

step() {
  echo
  echo "\$ $*"
  "$@"
}

{
  echo "==== litcontext 验证流程 $(date '+%Y-%m-%d %H:%M:%S') ===="
  echo

  step "$LC" doctor
  step "$LC" ingest data/samples

  echo
  echo "---- 检索：同一问题在 5 篇文献里的命中 ----"
  step "$LC" search "广义似然比 事件检测 误报" --top 3
  step "$LC" search "阈值 跨户 标定" --top 3

  echo
  echo "---- 写入研究判断（PowerContext Memory）----"
  step "$LC" note --kind finding --paper p-anderson12 --topic 事件检测 \
    --text "GLR/CUSUM 这类统计检验在大幅跃变上对误报的控制明显好于固定阈值" \
    --evidence "BLUED，|ΔP|>300W，精确率 0.86"
  step "$LC" note --kind finding --paper p-blued12 --topic 数据集 \
    --text "BLUED 是单户高密度事件标注，适合事件级评测，不适合训练数据驱动模型" \
    --evidence "单户约一周"
  step "$LC" note --kind finding --paper p-review20 --topic 评测 \
    --text "事件式方法在公开数据上 F1 多在 0.7–0.9，误差主要来自小跃变与多电器同时投切" \
    --evidence "综述汇总"
  step "$LC" note --kind decision --topic 事件检测 --method 固定阈值 --verdict reject \
    --text "固定阈值跨户迁移会明显掉点，需按户重标定，不适合作为毕设主线" \
    --reason "毕设只做单户但要求方法可迁移"
  step "$LC" note --kind decision --topic 事件检测 --method HMM --verdict reject \
    --text "因子 HMM 状态空间随电器数指数增长，全屋场景推断耗时不可接受" \
    --reason "算力有限，且事件式评测需要显式事件输出"
  step "$LC" note --kind decision --topic 事件检测 --method GLR --verdict keep \
    --text "GLR 作为主线：能输出显式事件，误报可控，且可解释" \
    --reason "与事件级评测口径一致"
  step "$LC" note --kind constraint \
    --text "只用 REDD house1，不外采数据；评测必须报事件级 F1 与匹配容差窗口"

  step "$LC" edge --paper p-anderson12 --method GLR --dataset BLUED \
    --metric F1 --value 0.89 --note "|ΔP|>300W"
  step "$LC" edge --paper p-blued12 --method 固定阈值 --dataset BLUED \
    --metric F1 --value 0.75 --note "基线"
  step "$LC" edge --paper p-review20 --method 事件式综述区间 --dataset 公开数据 \
    --metric F1 --value "0.70-0.90" --note "跨论文汇总"

  step "$LC" progress --done "读完 5 篇事件检测基础文献并做了取舍" \
    --current "在 REDD house1 上复现阈值基线" \
    --next "对比 GLR 与 CUSUM 的小跃变误报率"

  echo
  echo "---- 召回：重启进程后仍能拿到同样的上下文（数据在 PowerContext）----"
  step "$LC" resume

  echo
  echo "---- 出稿：综述初稿 + 方法对比表 ----"
  step "$LC" brief --topic 事件检测 -o out/brief.md
  step "$LC" compare -o out/compare.md

  echo
  echo "==== 完成 ===="
} 2>&1 | tee "$LOG"

echo
echo "日志已保存：$LOG"
