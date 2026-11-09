# SPEC-001 任务数据模型规格

> 适用范围：`todoapp.models`
> 版本：1.0

## SPEC-001-A 任务字段

每个任务（`Task`）必须包含以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 8 位十六进制唯一标识，由服务端生成 |
| `title` | str | 任务标题，不能为空 |
| `status` | str | 任务状态，初始值为 `todo` |
| `notes` | str | 备注信息，可为空 |
| `priority` | int | 优先级，取值 1（高）、2（中）、3（低），默认 2 |
| `created_at` | str | 创建时间，UTC ISO-8601 格式 |

## SPEC-001-B 合法状态值

任务状态目前只允许两个取值：

- `todo`：未完成
- `done`：已完成

状态由 `complete_task` 从 `todo` 置为 `done`，不存在其他状态迁移。

## SPEC-001-C 序列化

`Task` 必须支持与 dict 的双向转换（`to_dict` / `from_dict`），
dict 字段名与数据类字段名一致，用于持久化和接口返回。
