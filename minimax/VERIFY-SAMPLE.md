# 验证样例（VERIFY-SAMPLE）

本样例演示题目要求的完整闭环：**一次真实的代码修改**，由 SDD 上下文模块驱动、
MiniMax 执行、seekdb 提供资料检索、PowerContext 保存任务状态。

对应评委核对要求，先列明：

## 0. 上下文中必须包含的规格、代码和测试来源

| 类别 | 必须包含 | 真实来源 |
| --- | --- | --- |
| 规格条目 | SPEC-002-B（按状态筛选）、SPEC-002-C（无效筛选值） | `project/specs/SPEC-002-filtering.md` |
| 规格条目（辅助） | SPEC-001-A/B（status 字段与合法值） | `project/specs/SPEC-001-task-model.md` |
| 代码符号 | `TaskService.list_tasks`（method）、`TaskService`（class）等 | `project/src/todoapp/service.py` |
| 验证测试 | 目标：`tests/test_filtering.py`（5 项）；回归：`tests/test_service.py`（9 项） | `project/tests/` |
| 任务状态 | 已完成/待办/验证结果 | PowerContext Memory（scope: sdd-todoapp-scope） |

## 1. 任务描述

见 `project/tasks/001-add-status-filter.md`：

- **要改什么**：`TaskService.list_tasks` 增加可选参数 `status`——`None` 返回全部、
  `"todo"`/`"done"` 按状态筛选、非法值抛 `ValueError` 且不修改存储；
- **哪些原有行为必须保持**：创建/列出/完成/删除行为、JSON 持久化格式、
  无参调用返回全部任务——由 `tests/test_service.py` 9 项回归测试锁定。

## 2. 有效规格与初始数据

- 规格：`project/specs/`（3 个文档、10 个条目，导入后存于 seekdb `sdd_spec_items` 表）；
- 代码：`project/src/todoapp/`（19 个符号，存于 `sdd_code_symbols` 表）；
- 测试：`project/tests/`（14 个用例，存于 `sdd_test_cases` 表）；
- 初始代码状态：git 干净工作区，`list_tasks` **尚无** `status` 参数。

## 3. 操作步骤与预期结果

按顺序执行（前置：依赖安装与 `.env` 配置见 RUNBOOK §1-2）：

| # | 命令 | 预期结果 |
| --- | --- | --- |
| 1 | `sdd import` | stdout 报告 spec_items=10 / code_symbols=19 / test_cases=14 |
| 2 | `sdd verify --label pre` | 退出码 1：**test_filtering 5 failed**（TypeError：未实现 status 参数——目标行为未实现），test_service 9 passed；日志落 `evidence/logs/pre-*.log` |
| 3 | `sdd context --task project/tasks/001-add-status-filter.md` | Markdown 上下文包含 §0 列出的全部规格条目、`TaskService.list_tasks` 符号、目标+回归测试；任务状态段显示"尚无已保存状态" |
| 4 | `sdd implement --task project/tasks/001-add-status-filter.md` | 修改 `project/src/todoapp/service.py`；交互记录（模型、完整上下文、响应、usage）落 `evidence/minimax-records/001-*.json` |
| 5 | `sdd verify --label post` | 退出码 0：**14 passed**（目标 5 + 回归 9）；日志落 `evidence/logs/post-*.log` |
| 6 | `sdd state save --task ... --json '{...}'` | 状态写入 PowerContext Memory，返回 citation |
| 7 | 删掉本地 scope 镜像 `.sdd/scope_id.txt`，再 kill PowerContext 并用**同一数据目录**重启 | 服务恢复，数据仍在（持久化存储）；本地已无任何 scope 线索 |
| 8 | `sdd state show --task ...` | 退出码 0，输出第 6 步保存的状态（只可能来自服务端持久化） |
| 9 | `sdd context --task ...` | 上下文"任务状态"段包含第 6 步的内容（状态用于后续上下文构建） |
| 10 | 修改 `project/specs/SPEC-002-filtering.md` 中 SPEC-002-B 的任意内容 → `sdd import` → `sdd context --task ...` | 上下文输出**更新后的**规格内容（非固定答案） |

一键执行第 1-9 步：`bash scripts/run_demo.sh`（第 10 步见脚本内注释或手动执行）。

## 4. 关键证据文件

| 证据 | 位置 |
| --- | --- |
| 修改前测试日志（含命令、退出码、commit） | `evidence/logs/pre-*.log` |
| 修改后测试日志 | `evidence/logs/post-*.log` |
| MiniMax 交互记录（本次任务、提供的上下文、修改过程） | `evidence/minimax-records/001-*.json` |
| 代码差异 | `evidence/diff/001-add-status-filter.diff`（CI 生成）/ 或 `git diff` |
| 修改前代码快照 | `evidence/snapshots/` |
| 前后上下文 JSON | `.sdd/context-001-pre.json` / `.sdd/context-001-post.json` |
| 删缓存 + 重启服务后的状态召回输出 | `evidence/logs/state-recall-post-restart.json` |

## 5. 重置方法

```bash
bash scripts/reset.sh
```

脚本执行：`git checkout -- project/`（恢复代码与规格）、删除 `.sdd/`（seekdb 数据 + scope 缓存）。
重新执行 `sdd import` 即回到初始状态。PowerContext 中的历史记录不影响重新验证
（`sdd context` 只召回最新任务状态；如需彻底清空，删除 PowerContext 数据目录后重启并删 `.sdd/`）。

## 6. 评委核对提示

- **上下文正确性**：第 3/9/10 步输出中每个规格条目均标注来源文件与内容指纹，
  可直接与 `project/specs/` 比对；第 10 步证明输出跟随导入内容更新；
- **数据库实际参与**：`sdd import` 后可直接查库（如 `pyseekdb` SQL 控制台或 MySQL 客户端）
  核对三张表内容；上下文检索词与命中结果在输出的头部元信息中可见；
- **状态复用**：第 7-9 步跨越了 PowerContext 进程重启与模块进程重启（CLI 每次调用都是新进程），
  且第 7 步先删除了 `.sdd/scope_id.txt`——召回只能来自 `POST /v1/memory/search`
  （1.4+ 的正文在 `hits[].memory.text`）或 `POST /v1/context/prepare` 的信封解析，
  两者都不会因为缓存缺失而失忆；
- **MiniMax 参与**：`evidence/minimax-records/` 中的 prompt_context 与第 3 步上下文一致，
  changed_files 与代码 diff 对应。

## 7. 实际运行结果（2026-11-10 实测，Windows + sqlite 冒烟后端 + 真实 MiniMax 调用）

本节记录一次**真实执行**的结果（非设计预期），与上面各步一一对应。seekdb 相关步骤在
GitHub Actions 的 Ubuntu 环境执行（见 `.github/workflows/sdd-demo.yml` 运行记录）。

| 步骤 | 实际输出 |
| --- | --- |
| `sdd import` | `spec_items: 10` / `code_symbols: 19` / `test_cases: 14` |
| `sdd verify --label pre` | `exit=1 passed=9 failed=5`（目标测试 5 项全部因 `TypeError: unexpected keyword argument 'status'` 失败） |
| `sdd context` | 目标规格 SPEC-002-B/C 排在最前；`TaskService.list_tasks` 为第一条代码符号；目标/回归测试全部命中；上下文含"目标文件当前内容"（完整源码） |
| `sdd implement` | `model=MiniMax-M3`，真实 HTTP 调用，usage：prompt 2527 / completion 546 / total 3073 tokens，修改 `project/src/todoapp/service.py` |
| `sdd verify --label post` | `exit=0 passed=14 failed=0` |
| `sdd state save` | 写入 PowerContext Memory（返回 citation，`_snapshots: 3`） |
| 删除 `.sdd/scope_id.txt` + 重启 PowerContext 后 `sdd state show` | 退出码 0，完整召回 `done`/`todo`/`verification`；PowerContext 1.4.0 / 1.5.1 实测，1.2.0 由 CI `state-compat` 覆盖 |
| 重启后 `sdd context` | "任务状态（来自 PowerContext）"章节含上述字段 |

MiniMax 实际产出的代码差异（`evidence/diff/001-add-status-filter.diff`，10 增 5 删）：

```diff
-from typing import List
+from typing import List, Optional
 
-from .models import Task, STATUS_TODO
+from .models import Task, STATUS_TODO, VALID_STATUSES
 
-    def list_tasks(self) -> List[Task]:
-        """Return all tasks in creation order (SPEC-002-A)."""
-        return self._store.load()
+    def list_tasks(self, status: Optional[str] = None) -> List[Task]:
+        """Return tasks in creation order, optionally filtered by status."""
+        if status is not None and status not in VALID_STATUSES:
+            raise ValueError(f"invalid status: {status}")
+        tasks = self._store.load()
+        if status is None:
+            return tasks
+        return [task for task in tasks if task.status == status]
```

> 说明：这是模型在**只有符号签名**的早期上下文下无法做到的结果——第一版上下文不含目标文件源码时，
> 模型倾向于整篇重写该模块。为让上下文真正可用，`context_builder` 现在会把任务"需要修改的位置"
> 所指文件的**完整当前源码**注入上下文（`## 目标文件当前内容` 章节），系统提示词同时要求最小改动、
> 保留原有结构与签名。上述 diff 即为改进后的真实产出。
