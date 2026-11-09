# 证据目录（evidence）

本目录存放验证过程中产生的真实证据材料：

```
evidence/
├── logs/                  # 测试运行日志（命令、退出码、commit、完整输出）
│   ├── pre-*.log          #   修改前：目标测试失败 + 回归通过
│   ├── post-*.log         #   修改后：全部通过
│   ├── context-*.md       #   前后上下文快照（含任务状态差异）
│   └── minimax-change.diff
├── minimax-records/       # MiniMax 交互记录（prompt 上下文、响应、usage、变更文件）
├── diff/                  # 代码差异（修改前后对比）
└── snapshots/             # 修改前原文件快照（implement 步骤自动备份）
```

- 本地运行：`bash scripts/run_demo.sh` 自动生成以上材料；
- CI 运行：GitHub Actions（`.github/workflows/sdd-demo.yml`）在干净 Ubuntu 环境
  执行同一流程，并将本目录作为 artifact 上传；
- 各文件如何对应题目要求，见 `VERIFY-SAMPLE.md` §4。
