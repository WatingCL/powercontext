# 技术使用记录（USAGE-RECORDS）

本文件记录三项指定技术在本次任务中的实际使用过程，供评审核对。
对应的原始证据存放在 `evidence/` 目录。

## 1. MiniMax 开发记录

| 项 | 值 |
| --- | --- |
| 接入方式 | HTTP API（原生 `POST {MINIMAX_BASE_URL}/text/chatcompletion_v2`，Bearer 鉴权） |
| 端点 | `https://api.minimaxi.com/v1`（`MINIMAX_BASE_URL` 可配置） |
| 模型 | `MiniMax-M3`（`MINIMAX_MODEL` 可配置；M3 为推理模型，本模块发送 `thinking: {"type": "disabled"}` 关闭思考，否则推理 token 会吃光输出预算导致内容为空） |
| 参与环节 | 任务 001 的代码修改：接收上下文模块组装的开发上下文，产出 `project/src/todoapp/service.py` 的修改 |

**记录流程**（`sddcontext/agent.py`）：

1. `sdd implement` 组装上下文（规格 SPEC-002-B/C、符号 `TaskService.list_tasks`、
   目标/回归测试清单、任务状态）；
2. 以固定 system prompt（修改约束 + `### FILE:` 输出格式约定）调用 MiniMax；
3. 解析响应中的文件块，快照原文件后写回；
4. 完整交互（system prompt、上下文、模型响应、token usage、变更文件）落盘
   `evidence/minimax-records/001-*.json`，并作为 Source 证据写入 PowerContext。

实际运行记录见 `evidence/minimax-records/`；代码差异见 `evidence/diff/`。

### 1.1 真实调用记录（2026-11-10）

| 项 | 值 |
| --- | --- |
| 调用时间 | 2026-11-10T13:35:19Z |
| 模型 | `MiniMax-M3`（响应 `base_resp.status_code = 0`） |
| token 用量 | prompt 2527 / completion 546 / total 3073 |
| 上下文规模 | 6757 字符（含规格条目、符号表、目标文件完整源码、测试清单、任务状态） |
| 响应 | 2314 字符，含 `### FILE: project/src/todoapp/service.py` 代码块 |
| 落盘证据 | `evidence/minimax-records/001-2026-11-10T133519+0000.json`、`evidence/diff/001-add-status-filter.diff`、`evidence/logs/post-20261110T133526Z.log` |
| 效果 | 修改前 `5 failed / 9 passed` → 修改后 `14 passed` |

> 模型名协商：`implement` 会依次尝试 `MINIMAX_MODEL` 与内置候选
> （`MiniMax-M3 → M2.7 → M2.5 → M2 → M1 → Text-01`），平台下线某个模型名（错误码 2069/2013）
> 时会自动切换到下一个，因此不会因模型改名而失败。`1008`（余额不足）、`1004`（鉴权失败）
> 会立即给出可操作的报错。


## 2. 数据库查询记录（seekdb / OceanBase）

| 项 | 值 |
| --- | --- |
| 数据库 | OceanBase seekdb（嵌入式模式，`pip install pyseekdb`） |
| 接入方式 | `pylibseekdb` DBAPI（`sddcontext/store.py`）；备选 MySQL 协议（seekdb server / OceanBase，`PyMySQL`） |
| 存储内容 | `sdd_spec_items`（10 条规格条目）、`sdd_code_symbols`（19 个代码符号）、`sdd_test_cases`（14 个测试用例） |
| 查询用途 | 每次构建上下文时执行库内检索（全文 `MATCH...AGAINST`，不可用时 `LIKE` 兜底），**检索结果直接构成上下文的规格/代码/测试内容** |

**典型查询**（`BaseStore.search`，以规格表为例）：

```sql
SELECT * FROM sdd_spec_items
WHERE MATCH(title, content) AGAINST ('<任务检索词>' IN NATURAL LANGUAGE MODE);
-- 不可用时兜底：
SELECT * FROM sdd_spec_items WHERE title LIKE '%状态%' OR content LIKE '%status%' OR ...;
```

导入与查询的行数统计在 `sdd import` / `sdd check` 输出中打印；
上下文 Markdown 头部记录了本次使用的检索词与后端，可对照库中数据核对。

## 3. PowerContext 状态写入与复用记录

| 项 | 值 |
| --- | --- |
| 接入方式 | HTTP API（本地 `powercontext server run`，默认 `http://127.0.0.1:8000`，SQLite 后端，认证关闭） |
| Scope | `sdd-todoapp-scope`（`POST /v1/scopes` 幂等创建，scope_id 缓存于 `.sdd/scope_id.txt`） |
| Memory 写入 | `POST /v1/memory/remember`，kind=`state`，文本格式 `SDD-TASK-STATE <task_id>` + JSON 状态体（已完成/待办/验证结果） |
| 状态召回 | `POST /v1/memory/search`（`/v1/context/prepare` 兜底），解析最新快照合并 |
| Source 证据 | `POST /v1/sources/content` 记录 MiniMax 交互摘要（origin=`sddcontext.implement`） |

**复用验证路径**（对应必做项"状态能够复用"）：

1. `sdd state save --task ... --json '{...}'` 写入状态；
2. `kill` PowerContext 进程后重新 `powercontext server run`（服务重启）；
3. `sdd state show --task ...` 仍返回该状态（CLI 每次调用都是新的模块进程，模块重启成立）；
4. `sdd context --task ...` 输出的"任务状态"段包含该内容——状态被用于后续上下文构建。

## 4. 版本与环境

| 组件 | 版本 |
| --- | --- |
| OS（验证环境） | Ubuntu（GitHub Actions `ubuntu-latest`） |
| Python | 3.11 |
| pyseekdb / seekdb | pip 最新版 |
| powercontext | `==1.4.0`（1.2.0 / 1.5.1 亦通过 `state-compat` 矩阵） |
| pytest | ≥7 |
| sddcontext | 0.1.0（本仓库） |

> 注：开发调试亦在 Windows + sqlite 冒烟后端下进行过单元级验证
> （`sddcontext/tests/`，9 项），不作为评审路径。
