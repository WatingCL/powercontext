# 运行说明（RUNBOOK）

从干净环境开始，按本说明可以初始化数据、启动模块并执行验证样例。
参考环境：Ubuntu 22.04+ / Python 3.11+（seekdb 嵌入式引擎仅支持 Linux；
macOS/Windows 请使用 seekdb docker + MySQL 协议后端，见 §1.3 备选方案）。

## 1. 依赖与配置

### 1.1 安装依赖

```bash
cd minimax
python -m pip install --upgrade pip
pip install pytest pyseekdb "powercontext[cli,server]==1.4.0"
```

版本参考（开发验证时使用）：

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.11+ | sddcontext 要求 ≥3.10，pyseekdb 要求 ≥3.11 |
| pyseekdb | 最新（pip） | OceanBase seekdb 嵌入式引擎 |
| powercontext | `==1.4.0`（另在 1.2.0 上回归验证） | 含 `[cli,server]` extra |
| pytest | ≥7 | 测试运行器 |
| sddcontext | 本仓库，零第三方依赖 | `PYTHONPATH=minimax/sddcontext/src` 或 `pip install -e minimax/sddcontext` |

### 1.2 配置环境变量

```bash
cp .env.example .env   # 然后填入你的 MINIMAX_API_KEY
set -a; . ./.env; set +a
```

全部变量及默认值见 `.env.example`。关键项：

- `MINIMAX_API_KEY`（必填，implement 步骤需要）——在 https://platform.minimaxi.com 「接口密钥」创建；
- `SDD_STORE_BACKEND`：`seekdb`（默认，嵌入式）/ `mysql` / `sqlite`（仅开发冒烟）；
- `MINIMAX_MODEL`：默认 `MiniMax-M3`（当前免费试用档，不扣余额）；程序会在该模型不可用时自动依次尝试 `MiniMax-M2.7 → M2.5 → M2 → M1 → Text-01`。

### 1.3 备选：seekdb server / OceanBase（MySQL 协议后端）

不想用嵌入式时（或非 Linux 平台）：

```bash
docker run -d --name seekdb -p 2881:2881 -p 2886:2886 oceanbase/seekdb:latest
export SDD_STORE_BACKEND=mysql
export SDD_STORE_MYSQL_URL='mysql://root@127.0.0.1:2881/sdd'
pip install PyMySQL
```

该后端同样适用于任何 OceanBase MySQL 模式实例。

## 2. 启动服务

PowerContext server（任务状态持久化）：

```bash
powercontext server run > powercontext.log 2>&1 &
curl --fail http://127.0.0.1:8000/health/live   # 返回 ok 即就绪
```

seekdb 嵌入式无需启动服务（进程内引擎，数据落盘在 `SDD_SEEKDB_PATH`）。

## 3. 调用入口

统一 CLI（`PYTHONPATH=sddcontext/src`，或先 `pip install -e sddcontext` 后使用 `sdd` 命令）：

```bash
alias sdd="PYTHONPATH=sddcontext/src python -m sddcontext"

sdd check                                    # 健康检查：存储/PowerContext/MiniMax 配置
sdd import                                   # 导入规格/代码/测试 → seekdb（可重复执行，幂等）
sdd context --task project/tasks/001-add-status-filter.md          # 输出开发上下文（Markdown）
sdd context --task <task.md> --out json --save ctx.json            # JSON 输出并保存
sdd implement --task project/tasks/001-add-status-filter.md        # MiniMax 完成代码修改
sdd verify --label pre                       # 跑测试并留痕（pre/post 标签区分前后）
sdd state save --task <task.md> --json '<JSON对象>'                # 任务状态存入 PowerContext
sdd state show --task <task.md>              # 读取任务状态（删除 .sdd/scope_id.txt 后仍可读）
```

各命令输入/输出说明：

| 命令 | 输入 | 输出 |
| --- | --- | --- |
| `import` | `project/` 下的 specs/src/tests | 写入 seekdb 三张表；stdout 打印行数统计 |
| `context` | 任务 markdown | 上下文 Markdown（stdout）；`--save` 另存 JSON。包含：适用规格条目、代码符号、验证测试、任务状态 |
| `implement` | 任务 markdown（内部先构建上下文） | 修改 `project/src` 代码；交互记录 JSON 落 `evidence/minimax-records/` |
| `verify` | 无（跑 `project/tests/`） | 退出码=pytest 退出码；日志（命令/退出码/commit/输出）落 `evidence/logs/` |
| `state save/show` | 任务 markdown（+状态 JSON） | Memory 写入/读取 PowerContext |

## 4. 完整验证样例

见 [VERIFY-SAMPLE.md](VERIFY-SAMPLE.md)（含预期结果与重置方法）。一键执行：

```bash
bash scripts/run_demo.sh
```

## 5. 测试命令

```bash
# sddcontext 模块自身单元测试（不依赖外部服务，sqlite 后端）
cd sddcontext && python -m pytest tests/ -v

# 业务工程测试（修改前：test_filtering 失败 / test_service 通过；修改后全部通过）
cd project && python -m pytest tests/ -v
```

## 6. 已知限制

1. seekdb 嵌入式仅支持 Linux（glibc ≥ 2.28）；其他平台请用 §1.3 的 MySQL 协议后端；
2. `implement` 需要 MiniMax API Key；模块不会重试生成——失败请检查 `evidence/minimax-records/` 中的响应记录后重跑；
3. PowerContext 在 Windows 上为 experimental 支持；
4. 模型若返回不可解析的输出格式，`implement` 会报错并保留原始响应以便排查；
5. `sdd verify` 的日志统计基于 pytest `-v` 输出解析，只支持常规 `PASSED/FAILED/ERROR` 行格式。

### 6.1 MiniMax 报错对照表

`implement` 会依次尝试 `MINIMAX_MODEL` 与内置候选（`MiniMax-M3` → `MiniMax-M2.7` → `MiniMax-M2.5`
→ `MiniMax-M2` → `MiniMax-M1` → `MiniMax-Text-01`），因此平台下线某个模型名不会让流程直接失败。
常见错误码含义：

| 错误码 | 含义 | 处理方式 |
|---|---|---|
| `1008` insufficient balance | 账户余额为空（`sk-api-` 开头的是**按量计费**密钥，从余额扣费） | 在开放平台「账户管理 → 余额与账单」充值；或改用已订阅套餐的 `sk-cp-` 开头密钥 |
| `1004` | 密钥无效/鉴权失败 | 重新创建接口密钥并同步更新 `MINIMAX_API_KEY` |
| `2069` / `2013` | 模型名对该账号不可用（模型已下线或名称错误） | 无需处理，程序会自动尝试下一个候选；也可显式设置 `MINIMAX_MODEL` |
| `1002` | 触发频率限制 | 稍后重试 |

注意：MiniMax 存在两类密钥——`sk-api-`（余额计费）与 `sk-cp-`（Coding Plan 套餐）。
用 `sk-api-` 密钥调用而账户无余额时即报 `1008`，与代码无关。

## 7. 重置方法

```bash
bash scripts/reset.sh    # 恢复代码、清空 seekdb 数据与模块状态目录（不影响 PowerContext 中的记录）
```

彻底重置（含 PowerContext 状态）：删除 PowerContext 数据目录后重启 server，
并删除 `minimax/.sdd/`（其中缓存了 scope_id）。

注意：`.sdd/scope_id.txt` 只是加速缓存，**不是召回前提**。`POST /v1/scopes` 以
`idempotency_key` 幂等，删除缓存后会重新解析到同一个 scope；若缓存指向已不存在的
scope，模块会从 `GET /v1/scopes` 中按项目标题找回真实 scope 再检索。
