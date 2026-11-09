#!/usr/bin/env bash
# Reset the demo state: restore code/specs, clear seekdb data and module state.
# PowerContext records are kept (they do not affect re-verification); see
# VERIFY-SAMPLE.md §5 for a full wipe.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[reset] restoring project/ from git"
git checkout -- project/ || true

echo "[reset] removing module state (.sdd/ contains seekdb data + scope cache)"
rm -rf .sdd

echo "[reset] done. Re-run 'sdd import' to reinitialise the store."
