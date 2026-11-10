# 提交对照表

按赛题「四、提交材料」与「3.1 基础验收」逐条对，左边是要求，右边是本仓库里的位置。
提交前只需把三处 `【待填】` 换成你自己的信息。

## 一、提交材料

| 材料 | 位置 | 状态 |
| --- | --- | --- |
| 项目网站网址 | <https://litcontext-tr1zylcd1ih.qoder.website>（Qoder Sites 发布，可见范围「任何人都可访问」） | ✅ 已发布，无痕窗口可打开 |
| 站点归属凭据 | `qoder/site/.文献脉络 LitContext.qoder.site`：Qoder Sites 写入的发布元数据，含 `siteId` / `deploymentId` / `releaseId` | ✅ 可核对发布来源 |
| 代码仓库 | `https://github.com/WatingCL/powercontext`，分支 `2026-competition-ecosystem`，目录 `qoder/` | ✅ 已推送 |
| 运行说明 | `qoder/RUNBOOK.md`：环境、版本、PowerContext 部署与接入、从安装到启动 | ✅ |
| 验证样例 | `qoder/VERIFY-SAMPLE.md`：初始数据、命令、预期输出、PowerContext 作用记录 | ✅ 含 10 条断言与实跑日志 |
| Qoder 开发记录 | 对话截图 3 张：`evidence/qoder-screenshots/01-uid.png`（账号 ID）、`02-pc-py-qa.png`（pc.py 如何对接 PowerContext）、`03-memory-index-qa.png`（记忆与本地索引分工）；UID：`01a1c332-5c99-7209-bf5d-8b85d7ee9836` | ✅ 已采集入库 |
| 使用效果材料 | `qoder/USAGE-RECORDS.md`：开发期自用数据已填，真实用户部分留表待填 | ⚠️ 部分待补 |

## 二、基础验收四条

| 要求 | 怎么核对 | 状态 |
| --- | --- | --- |
| 1. 网站可访问（未登录也能开） | <https://litcontext-tr1zylcd1ih.qoder.website>，无痕窗口直接打开 | ✅ 实测 HTTP 200，两张截图资源均 200 |
| 2. 项目能够运行 | `RUNBOOK.md` 三步 → `litcontext doctor` 显示 `PowerContext 可用` + `记忆条数 11` | ✅ 本机实跑；干净 Ubuntu 上 13 步 CI 全绿 |
| 3. Qoder 开发可核对 | 对话截图见 `evidence/qoder-screenshots/`（Qoder 对本仓库 `pc.py` 与 `index.py`/`memory.py` 的真实解读），UID 截图 `01-uid.png` | ✅ UID：`01a1c332-5c99-7209-bf5d-8b85d7ee9836` |
| 4. 技术结合有效 | 记忆读写记录：`evidence/logs/demo-*.log`、`evidence/logs/doctor.log`；召回：`evidence/recall-eval.md` | ✅ |

CI 运行记录（评审可直接点开看每一步命令与产物）：

- 工作流页面：<https://github.com/WatingCL/powercontext/actions/workflows/qoder-verify.yml>
- 分支头每次推送自动运行；截至本版本连续三次（`6c201d5` / `2d230faa` / `016c792c`）均 success，
  每次 10 个业务步骤全过、约 50 秒，Artifacts `qoder-evidence`（约 483 KB）可直接下载核对

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

- [x] **Qoder 开发记录**：3 张对话截图已存入 `evidence/qoder-screenshots/`（含账号 ID 页）
- [x] **发布 Qoder Sites**：<https://litcontext-tr1zylcd1ih.qoder.website>，可见范围「任何人都可访问」，无痕窗口已验证
- [ ] **补使用数据**：把 `data/samples` 换成你真正在读的论文，用一两周，再把真实数字填进 `USAGE-RECORDS.md` 第二、三节；
      站点后台的「访问统计」可以一并截图作为来源

## 五、提交信息模板

```
项目网站网址：https://litcontext-tr1zylcd1ih.qoder.website
代码仓库：https://github.com/WatingCL/powercontext
分支：2026-competition-ecosystem
Commit id：填分支头的完整 40 位（提交前用 git rev-parse origin/2026-competition-ecosystem 取最新值）
Qoder 账号 UID：01a1c332-5c99-7209-bf5d-8b85d7ee9836
指定技术：PowerContext（未使用 seekdb，赛题二选一）
```
