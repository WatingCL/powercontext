# 提交对照表

按赛题「四、提交材料」与「3.1 基础验收」逐条对，左边是要求，右边是本仓库里的位置。
提交前只需把三处 `【待填】` 换成你自己的信息。

## 一、提交材料

| 材料 | 位置 | 状态 |
| --- | --- | --- |
| 项目网站网址 | Qoder Sites 发布 `qoder/site/index.html` 后的公开链接 | 【待填】只有你能发 |
| 代码仓库 | `https://github.com/WatingCL/powercontext`，分支 `2026-competition-ecosystem`，目录 `qoder/` | ✅ 已推送 |
| 运行说明 | `qoder/RUNBOOK.md`：环境、版本、PowerContext 部署与接入、从安装到启动 | ✅ |
| 验证样例 | `qoder/VERIFY-SAMPLE.md`：初始数据、命令、预期输出、PowerContext 作用记录 | ✅ 含 9 条断言与实跑日志 |
| Qoder 开发记录 | 录屏 + 账号 UID；五个会话的逐字提问见 `qoder/docs/QODER-SESSION.md` | 【待填】只有你能录 |
| 使用效果材料 | `qoder/USAGE-RECORDS.md`：开发期自用数据已填，真实用户部分留表待填 | ⚠️ 部分待补 |

## 二、基础验收四条

| 要求 | 怎么核对 | 状态 |
| --- | --- | --- |
| 1. 网站可访问（未登录也能开） | Qoder Sites 发布时选「任何人都可访问」，用无痕窗口打开验证 | 【待填】 |
| 2. 项目能够运行 | `RUNBOOK.md` 三步 → `litcontext doctor` 显示 `PowerContext 可用` + `记忆条数 11` | ✅ 本机实跑；干净 Ubuntu 上 13 步 CI 全绿 |
| 3. Qoder 开发可核对 | 录屏里应有 Qoder 账号 UID、五个会话、以及 `pc.py` / `memory.py` / `synonyms.py` 的生成过程 | 【待填】 |
| 4. 技术结合有效 | 记忆读写记录：`evidence/logs/demo-*.log`、`evidence/logs/doctor.log`；召回：`evidence/recall-eval.md` | ✅ |

CI 运行记录（评审可直接点开看每一步命令与产物）：

- 最绿的一次：[run 42684277218](https://github.com/WatingCL/powercontext/actions/runs/42684277218)
  —— 提交 `2d230faa`，10 个业务步骤全部 success，耗时 51 秒，Artifacts `qoder-evidence`（483 KB）
- 前一次同样全绿（证明可重复）：[run 42675737264](https://github.com/WatingCL/powercontext/actions/runs/42675737264)，提交 `6c201d5`
- 工作流总览：<https://github.com/WatingCL/powercontext/actions/workflows/qoder-verify.yml>

## 三、评价维度对应物

| 维度 | 本作品的对应物 | 需要提醒自己的地方 |
| --- | --- | --- |
| 实用价值 | 痛点来自毕设真实场景（否掉 HMM 的理由第三次重推） | 别写成"通用文献管理"，要讲"研究判断流失" |
| 使用效果 | 开发期自用数据可核对；真实用户待补 | **不要填估算值**，评审能看出编造 |
| 完成度与体验 | 9 条命令 + Web UI + 确定性出稿；一条命令跑完整流程 | UI 是本地起服务，评委需按 RUNBOOK 操作 |
| 技术结合 | PowerContext 承担不可重建的部分（结论/否决/约束/进度/对比），SQLite 只承担可重建的段落索引 | 别让人误以为 SQLite 才是核心 |
| Qoder 开发实践 | `docs/QODER-SESSION.md` 的五个会话，包含两次真实报错定位 | 录屏不要剪掉报错片段 |
| 工程质量 | 20 个单元测试、CI 从零复现、召回阈值门禁、依赖仅标准库 + 可选 pypdf | CI 徽标在 README 顶部，可直接点开 |

## 四、提交前最后三件事（只有你能做）

- [ ] **录 Qoder 开发过程**：照 `docs/QODER-SESSION.md` 走五个会话，开头露账号 UID，结尾跑 `bash scripts/demo.sh`
- [ ] **发布 Qoder Sites**：源目录 `qoder/site/`，可见范围设为「任何人都可访问」，用无痕窗口确认
- [ ] **补使用数据**：把 `data/samples` 换成你真正在读的论文，用一两周，再把真实数字填进 `USAGE-RECORDS.md` 第二、三节

## 五、提交信息模板

```
项目网站网址：https://【Qoder Sites 链接】
代码仓库：https://github.com/WatingCL/powercontext
分支 / commit：2026-competition-ecosystem / 【填 git rev-parse --short HEAD】
Qoder 账号 UID：【填】
指定技术：PowerContext（未使用 seekdb，赛题二选一）
```
