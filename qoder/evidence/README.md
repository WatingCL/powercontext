# evidence —— 运行证据

本目录保存**真实执行**产生的日志与产物，用于核对"PowerContext 在项目里确实起了作用"。
所有文件均由 `scripts/demo.sh` 与手工命令直接生成，未经改写。

| 文件 | 内容 | 对应验证点 |
| --- | --- | --- |
| `logs/demo-20261110-013548.log` | 一次完整流程：doctor → ingest → search ×2 → 11 次记忆写入 → resume → brief → compare | 全链路 |
| `logs/doctor.log` | 索引规模、PowerContext 连通性、记忆条数按类型统计 | 记忆真实写入 |
| `logs/resume-after-restart.log` | **停掉并重启 PowerContext 服务后**执行 `resume` 的输出 | 记忆落盘、跨进程复用 |
| `logs/web.log` | Web UI 启动日志 | UI 可运行 |
| `snapshots/brief.md` | 生成的综述初稿（1869 字符，6 段原文引用） | 出稿 |
| `snapshots/compare.md` | 生成的方法对比表（3 条记忆） | 出稿 |
| `snapshots/ui-01-home.png` | Web UI 首页：左侧检索结果、右侧记忆面板、顶部状态徽标 | 可运行性 / 体验 |
| `snapshots/ui-02-brief.png` | Web UI 生成综述初稿后的页面 | 主要流程完整 |

## 怎么自己复现

```bash
cd qoder
powercontext server run          # 终端 A
bash scripts/demo.sh             # 终端 B：会新写一份 logs/demo-*.log
```

## 怎么核对"记忆不在本地"

1. 看 `logs/resume-after-restart.log`：该文件是**服务重启后**由新进程生成的，
   内容与重启前一致，说明数据在 PowerContext 的库里，不在 `litcontext` 进程内。
2. 删掉 `qoder/.data/`（本地索引与 scope 缓存）后重跑 `litcontext resume`：
   进度与结论仍在，因为 `.data/` 只存论文段落。
3. 记忆实体在 PowerContext 侧：`scope_id=scp_6b38kwtshr9g4k2h7ycfh2yy8g`，
   `family=atomic-memory`，可按 `kind` 区分 finding / decision / constraint / edge / progress。
