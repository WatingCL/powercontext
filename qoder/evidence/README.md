# evidence —— 运行证据

本目录保存**真实执行**产生的日志与产物，用于核对"PowerContext 在项目里确实起了作用"。
所有文件均由 `scripts/demo.sh` 与手工命令直接生成，未经改写。

| 文件 | 内容 | 对应验证点 |
| --- | --- | --- |
| `logs/demo-20261110-014711.log` | 一次完整流程：doctor → ingest → search ×2 → 召回评测 → 11 次记忆写入 → resume → brief → compare | 全链路 |
| `logs/doctor.log` | 索引规模、PowerContext 连通性、记忆条数按类型统计 | 记忆真实写入 |
| `logs/resume-after-restart.log` | **停掉并重启 PowerContext 服务后**执行 `resume` 的输出 | 记忆落盘、跨进程复用 |
| `logs/web.log` | Web UI 启动日志 | UI 可运行 |
| `snapshots/brief.md` | 生成的综述初稿（1891 字符，6 段原文引用） | 出稿 |
| `snapshots/compare.md` | 生成的方法对比表（3 条记忆） | 出稿 |
| `snapshots/ui-01-home.png` | Web UI 首页：左侧检索结果、右侧记忆面板、顶部状态徽标 | 可运行性 / 体验 |
| `snapshots/ui-02-brief.png` | Web UI 生成综述初稿后的页面 | 主要流程完整 |
| `recall-eval.md` | 16 条标注查询的检索评测：关闭/开启同义扩展的命中率、MRR、逐条名次与失败案例 | 检索质量可量化 |
| `recall-eval.json` | 同一份评测的机器可读结果（CI 里也会重新生成） | 可复现 |

## 怎么自己复现

```bash
cd qoder
powercontext server run          # 终端 A
bash scripts/demo.sh             # 终端 B：会新写一份 logs/demo-*.log 和 recall-eval.*
```

## 另有一条独立证据链：CI

本机是 Windows，评审未必有同样的环境，所以同一套流程在干净的 Ubuntu 上也跑：

- 工作流：`.github/workflows/qoder-verify.yml`（`qoder-litcontext-verify`）
- 步骤：装 `powercontext[cli,server]==1.5.0` → 起服务 → 20 个单测 → `scripts/demo.sh`
  → `scripts/eval_recall.py --check`（命中@5 ≥ 0.95 且未命中率 ≤ 0.05 才放行）→ 传 Artifacts
- 产物：整个 `evidence/` 与 `out/`，可直接下载核对，含日志与召回评测 JSON

**运行记录**：[Actions 工作流页面](https://github.com/WatingCL/powercontext/actions/workflows/qoder-verify.yml)
按分支头倒序列出每一次运行，点开任意一次都能看到每条命令与其输出。
截至本版本，分支 `2026-competition-ecosystem` 连续三次推送（`6c201d5` / `2d230faa` / `016c792c`）
均为 success：10 个业务步骤全过，单次约 50 秒，Artifacts `qoder-evidence` 约 483 KB。

> 一段需要说明的插曲：2026-11-09 18:10Z—18:28Z 期间 GitHub Actions 发生平台级故障
> （状态页标记 major outage），那三次运行为 **0 job 直接失败**——job 根本没被创建，
> 与本项目代码无关。故障恢复后同一套代码重新运行即为上面两次全绿；
> 故障前的四次运行（`b458926` / `f35a364` / `466cbaf` / `4692ede`）同样都是 success。

## 怎么核对"记忆不在本地"

1. 看 `logs/resume-after-restart.log`：该文件是**服务重启后**由新进程生成的，
   内容与重启前一致，说明数据在 PowerContext 的库里，不在 `litcontext` 进程内。
2. 删掉 `qoder/.data/`（本地索引与 scope 缓存）后重跑 `litcontext resume`：
   进度与结论仍在，因为 `.data/` 只存论文段落。
3. 记忆实体在 PowerContext 侧：`scope_id=scp_5jzgwts2bgf6gjxzkhmz8d3mzq`，
   `family=atomic-memory`，可按 `kind` 区分 finding / decision / constraint / edge / progress。
