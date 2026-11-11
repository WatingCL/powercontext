# 规有所依 —— 面向软件持续演进的 SDD 上下文管理系统

MiniMax × OceanBase 赛题作品。本目录包含一个**规格驱动开发（SDD）上下文模块**
`sddcontext`：根据开发任务从数据库中检索适用的规格条目、相关代码符号和验证测试，
结合 PowerContext 中保存的任务状态，为 AI 开发助手组装完整的开发上下文，
并驱动 MiniMax 完成一次真实的代码修改。

## 一页技术说明

### 模块结构

```
minimax/
├── project/                 业务工程 todoapp（待办管理库，纯标准库实现）
│   ├── src/todoapp/         models.py / storage.py / service.py
│   ├── specs/               条目化规格文档（SPEC-001 数据模型 / SPEC-002 筛选 / SPEC-003 持久化）
│   ├── tests/               test_service.py（回归）+ test_filtering.py（目标功能测试）
│   └── tasks/               任务定义（001-add-status-filter.md）
├── sddcontext/              ★ SDD 上下文模块（本题核心交付）
│   └── src/sddcontext/
│       ├── cli.py           CLI 入口（import / context / implement / verify / state / check）
│       ├── importer.py      规格条目解析、AST 代码符号提取、测试元数据提取
│       ├── store.py         存储层：seekdb 嵌入式 / MySQL 协议(seekdb server·OceanBase) / sqlite 冒烟
│       ├── retriever.py     检索层：中英混合分词 + 库内全文/LIKE 查询 + 词命中重排
│       ├── context_builder.py  上下文组装（规格 + 代码 + 测试 + 任务状态 + 来源校验）
│       ├── state.py         PowerContext HTTP 客户端（任务状态写入/召回、开发证据 Source）
│       ├── agent.py         MiniMax 调用（上下文 → 代码修改 → 交互记录落盘）
│       └── verify.py        pytest 运行器（命令、退出码、commit、日志留痕）
├── evidence/                验证证据：测试日志、MiniMax 交互记录、代码 diff、快照
├── scripts/                 一键演示 / 重置脚本
└── RUNBOOK.md · VERIFY-SAMPLE.md · USAGE-RECORDS.md
```

### 上下文选择方式

1. **任务解析**：`tasks/*.md` 中提取任务目标、预期修改位置、必须保持的行为、验证方式；
2. **检索词提取**：中英混合——拉丁标识符（`list_tasks`、`status`）+ 中文二元组（"状态"、"筛选"）；
3. **库内检索**（真实执行于 seekdb/OceanBase）：先全文索引 `MATCH...AGAINST`，
   不可用时 `LIKE` 兜底，候选行再按检索词命中数重排，取 Top-N；
4. **来源校验**：输出引用的每个规格条目/文件都必须真实存在于工程中，否则剔除；
5. **状态合并**：从 PowerContext 召回该任务的历史状态（已完成/待办/验证结果）并入上下文；
6. **双格式输出**：机器可读 JSON（`--out json`）与人读 Markdown（默认，同时作为 MiniMax 的输入）。

### 各项技术的分工

| 技术 | 角色 | 具体承担 |
| --- | --- | --- |
| **seekdb（OceanBase）** | 工程资料库 | 规格条目、代码符号、测试用例三张表存入 seekdb；上下文构建时**每次真实执行 SQL 检索**，检索结果即上下文内容；规格更新后重新导入，输出随之更新 |
| **PowerContext** | 任务状态库 | 任务进展（已完成/待办/验证结果）以 Memory（kind=state）持久化；模块重启、PowerContext 重启后仍可召回并注入后续上下文；MiniMax 交互与验证结果另存为 Source 证据 |
| **MiniMax** | 开发助手 | 接收完整开发上下文（规格+代码+测试+状态），产出代码修改（chatcompletion_v2 接口）；全程交互记录留档 `evidence/minimax-records/` |

### 状态召回与服务器版本兼容

任务状态是**服务端持久化**的，客户端不依赖本地缓存：

1. 写入：`POST /v1/memory/remember`（`kind=state`，正文形如 `SDD-TASK-STATE 001\n{...}`）；
2. 召回先走 `POST /v1/memory/search`：不同版本把正文放在 `hits[].text`（1.2.x）或
   `hits[].memory.text`（1.4.x/1.5.x），客户端按结构逐层取正文，不写死布局；
3. 检索无结果时回退 `POST /v1/context/prepare`：1.4+ 的正文被包在
   `BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1{...}` 信封里且 JSON 被二次转义，
   客户端先解信封再解转义，取 `items[].content` 解析状态体；
4. `.sdd/scope_id.txt` 只是加速缓存：`POST /v1/scopes` 以 `idempotency_key` 幂等，
   缓存丢失会重新解析到同一 scope；缓存指向已失效 scope 时，从 `GET /v1/scopes`
   按项目标题找回真实 scope 再检索；
5. 因此「保存 → 换进程 → 重启服务 → 再次构建上下文」这条链在 1.2.0 / 1.4.0 / 1.5.1
   上都成立，CI 的 `state-compat` 任务逐版本断言这一点。

### 验证样例一句话版

> 任务 001 要求 `TaskService.list_tasks` 支持状态筛选（规格 SPEC-002-B/C）。
> 修改前目标测试 5 项失败、回归 9 项通过；经本模块构建上下文并交由 MiniMax 修改后，
> 全部 14 项测试通过；任务状态保存后重启 PowerContext 仍可召回。
> 详见 [VERIFY-SAMPLE.md](VERIFY-SAMPLE.md)，完整操作步骤见 [RUNBOOK.md](RUNBOOK.md)。

### 端到端验证状态（可复现）

在 GitHub Actions 的干净 Ubuntu 环境（`ubuntu-latest` + Python 3.11）中，一次
`sdd-demo` 流水线跑完全部环节并全部通过：

| 环节 | 结果 |
| --- | --- |
| 依赖安装 / 模块单测 | ✅（`pyseekdb` 嵌入式 seekdb 可用，sddcontext 17 项单测通过） |
| seekdb 导入 | ✅ spec_items=10 / code_symbols=19 / test_cases=14 |
| 修改前测试 | ✅ 目标测试 5 失败、回归 9 通过（语义断言：必须是这个状态） |
| 上下文构建 | ✅ 含规格条目、符号表、目标文件完整源码、测试清单 |
| **MiniMax 实现** | ✅ `MiniMax-M3` 真实调用，仅修改 `project/src/todoapp/service.py`（+10/−5） |
| 修改后测试 | ✅ 14 passed / 0 failed |
| 状态保存 + 重启召回 | ✅ 删除 `.sdd/scope_id.txt` + kill 重启 PowerContext（同一数据目录）后，`state show` 退出码 0，上下文仍含任务状态 |
| 跨版本状态回归 | ✅ `state-compat` 矩阵在 PowerContext 1.2.0 / 1.4.0 / 1.5.1 上各跑一遍 save→丢缓存→重启→召回 |
| 规格更新传播 | ✅ 改规格 → 重新导入 → 上下文同步更新 |
| 变更 diff 归档 | ✅ `evidence/diff/001-add-status-filter.diff`（仅业务工程范围） |

复现方式：仓库 **Actions → sdd-demo → Run workflow**（需配置 `MINIMAX_API_KEY` secret），
或本地按 [RUNBOOK.md](RUNBOOK.md) 执行 `bash scripts/run_demo.sh`。
