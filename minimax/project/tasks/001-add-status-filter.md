# 任务 001：为任务列表增加状态筛选

## 目标

按照 SPEC-002-B 与 SPEC-002-C 的要求，为 `todoapp.service.TaskService.list_tasks`
增加可选参数 `status`：

1. `status=None`（缺省）返回全部任务，行为与现有版本完全一致；
2. `status="todo"` / `status="done"` 仅返回对应状态的任务，保持创建顺序；
3. `status` 为其他任意值时抛出 `ValueError`，存储内容不被修改。

## 需要修改的位置

- `project/src/todoapp/service.py` 中的 `TaskService.list_tasks`
- 如需引用合法状态值，可复用 `project/src/todoapp/models.py` 中的常量

## 必须保持的行为（回归要求）

- `add_task`：创建任务、空标题与非法优先级的校验行为不变；
- `get_task` / `complete_task` / `delete_task`：行为不变；
- JSON 持久化格式（SPEC-003-A）与原子写入（SPEC-003-B）不变；
- `list_tasks()` 无参调用返回全部任务，顺序不变。

## 验证

- 新增功能测试：`project/tests/test_filtering.py`（当前失败，修改后必须全部通过）
- 回归测试：`project/tests/test_service.py`（修改前后都必须通过）
