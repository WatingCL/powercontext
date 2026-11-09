#!/usr/bin/env bash
# End-to-end demo of the SDD context module (task 001: add status filter).
# Prerequisites: see RUNBOOK.md §1-2 (deps installed, .env sourced,
# PowerContext server running).
set -uo pipefail

cd "$(dirname "$0")/.."

export SDD_PROJECT_DIR="${SDD_PROJECT_DIR:-project}"
if [ -z "${PYTHONPATH:-}" ]; then
  export PYTHONPATH=sddcontext/src
fi
echo "[demo] PYTHONPATH=$PYTHONPATH store=${SDD_STORE_BACKEND:-seekdb}"

step() { echo; echo "==================== $* ===================="; }

step "0. health check"
python -m sddcontext check

step "1. import project material into the store"
python -m sddcontext import

step "2. pre-change tests (target must FAIL, regression must PASS)"
set +e
python -m sddcontext verify --label pre
pre_code=$?
set -e
echo "[demo] pre-change exit code: $pre_code (1 expected: 5 target failures)"

step "3. build development context"
python -m sddcontext context --task "$SDD_PROJECT_DIR/tasks/001-add-status-filter.md" \
  --save .sdd/context-001-pre.json | tee evidence/logs/context-001-pre.md

step "4. implement with MiniMax"
python -m sddcontext implement --task "$SDD_PROJECT_DIR/tasks/001-add-status-filter.md"

step "5. post-change tests (all must PASS)"
python -m sddcontext verify --label post

step "6. save task state to PowerContext"
python -m sddcontext state save --task "$SDD_PROJECT_DIR/tasks/001-add-status-filter.md" --json '{
  "title": "为任务列表增加状态筛选",
  "done": ["导入规格/代码/测试到 seekdb", "构建开发上下文", "MiniMax 完成代码修改", "功能与回归测试全部通过"],
  "todo": [],
  "verification": {"pre": "目标测试 5 failed / 回归 9 passed", "post": "全部 14 passed"},
  "changed_files": ["project/src/todoapp/service.py"]
}'

step "7. recall state (fresh module process = module restart)"
python -m sddcontext state show --task "$SDD_PROJECT_DIR/tasks/001-add-status-filter.md"

step "8. context now includes recalled state"
python -m sddcontext context --task "$SDD_PROJECT_DIR/tasks/001-add-status-filter.md" \
  --save .sdd/context-001-post.json | tee evidence/logs/context-001-post.md

step "9. code diff produced by MiniMax"
mkdir -p evidence/diff
git diff -- project/ > evidence/diff/001-add-status-filter.diff
git diff --stat -- project/

echo
echo "[demo] done. Evidence under evidence/ ; see VERIFY-SAMPLE.md §4."
echo "[demo] Optional spec-update check: edit specs/SPEC-002-filtering.md, re-run"
echo "       'sdd import' and 'sdd context', and confirm the context reflects the change."
