# SPEC-002 任务筛选规格

> 适用范围：`todoapp.service.TaskService`
> 版本：1.0

## SPEC-002-A 列出全部任务

`TaskService.list_tasks()` 在不传任何筛选参数时，返回当前存储中的全部任务，
顺序与任务创建顺序一致（先创建的在前）。

## SPEC-002-B 按状态筛选

`TaskService.list_tasks(status=...)` 必须支持按状态筛选：

- `status` 为 `None`（缺省）时，行为与 SPEC-002-A 相同，返回全部任务；
- `status` 为 `"todo"` 时，仅返回状态为 `todo` 的任务；
- `status` 为 `"done"` 时，仅返回状态为 `done` 的任务；
- 筛选结果的相对顺序仍遵循创建顺序。

## SPEC-002-C 无效筛选值

当 `status` 既不是 `None`，也不在合法状态值（见 SPEC-001-B：`todo`、`done`）之内时，
`list_tasks` 必须抛出 `ValueError`，且不得修改存储内容。

## SPEC-002-D 按优先级筛选（预留）

`list_tasks(priority=...)` 按优先级筛选的能力属于后续版本范围，
本版本不要求实现，也不得因此改变现有接口行为。
