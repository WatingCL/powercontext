#!/usr/bin/env bash
# 清空本地索引与出稿产物。PowerContext 里的记忆不会被删除——
# 这正是本作品想说明的一点：文献索引可以重建，研究判断不行。
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf .data out
echo "已清空 .data/（本地索引、scope 缓存）与 out/（出稿产物）"
echo "PowerContext 中的记忆保持不动。如要一并清空，请停掉服务后删除"
echo "  \$POWERCONTEXT_HOME/powercontext.db"
echo "再重新 \`powercontext server run\`。"
