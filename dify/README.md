# 记仇的酒馆掌柜 · 运行说明（README）

> OceanBase 数据库大赛 · Dify 赛道（Just for Fun）参赛作品
> 一个会「记仇」的酒馆掌柜 NPC：通过 **PowerContext** 跨会话记住玩家的恶作剧与承诺，
> 并在全新会话里主动翻旧账。

---

## 1. 作品一句话

玩家每次和 NPC 对话，NPC 都会把本轮发言写进 PowerContext 记忆；下次哪怕开一个
**全新会话**，NPC 也会先检索这些记忆，然后阴阳怪气地提起你以前干过的坏事（往酒坛放蟑螂、赊账不还）。

**技术组合**：Dify（必需，Chatflow 编排）+ PowerContext（真实 functioning，记忆读写）+ DeepSeek（LLM）。

---

## 2. 目录结构

```
dify/
├── README.md                          # 本文件（运行说明）
├── .env.example                       # 配置样例（占位符，复制为 .env 后填写）
├── dsl/
│   └── grudge-npc-chatflow.yml        # Dify 应用 DSL（由 Dify Cloud 导出，权威配置）
├── init/
│   └── powercontext_init.py           # PowerContext 初始化脚本（建作用域 + 预置旧账记忆）
└── evidence/
    ├── 验证样例.md                     # 评审照做的复现步骤 + 预期结果
    └── 验证证据01-跨会话记仇运行轨迹.md # 一次真实运行的完整节点轨迹（含 request-id）
```

---

## 3. 工作流节点图

```
开始(start) → 回忆检索(recall) → 掌柜回话(keeper) → 回复(reply) → 记忆写回(remember)
```

| 节点 | 类型 | 作用 |
|------|------|------|
| 开始 start | start | 接收玩家输入 `sys.query` |
| 回忆检索 recall | http-request | `POST {PC_BASE_URL}/v1/memory/entries/list`，拉取该作用域全部历史记忆 |
| 掌柜回话 keeper | llm（deepseek-v4-pro） | 人设 + `{{#recall.body#}}` 注入记忆 → 生成翻旧账回复（≤80字） |
| 回复 reply | answer | 输出 `{{#keeper.text#}}` |
| 记忆写回 remember | http-request | `POST {PC_BASE_URL}/v1/memory/remember`，把本轮发言写回记忆 |

> 说明：检索用 `entries/list`（列出全部记忆）而非 `search`（词法检索），
> 因为中文分词下 `search` 召回不稳定；`entries/list` 让 NPC 看到完整历史，翻旧账更可靠。

---

## 4. 运行环境要求

- **PowerContext**：本地 Server（`pip install "powercontext[server,cli]"`，作品验证用 1.5.1，sqlite 存储）。
- **Dify**：二选一
  - **Dify Cloud**（cloud.dify.ai，本作品实际运行环境）；
  - **自托管 Dify**（与 PowerContext 同机时最简单，直接用 `127.0.0.1`）。
- **模型**：DeepSeek，模型名 `deepseek-v4-pro`，供应商 `langgenius/deepseek/deepseek`（Dify 插件市场安装）。
- Python 3.10+（仅初始化脚本用，纯标准库）。

---

## 5. 运行步骤

### 步骤 1 — 启动 PowerContext Server

```bash
pip install "powercontext[server,cli]"
powercontext server run        # 前台运行，默认监听 127.0.0.1:8000
```

### 步骤 2 — 初始化演示作用域（预置旧账）

```bash
py init/powercontext_init.py --new
```

脚本会新建一个空作用域，写入两条“旧账”记忆（蟑螂恶作剧、赊账承诺），并打印：

```
PC_SCOPE_ID=scp_xxxxxxxxxxxxxxxx
```

**记下这个 ID**，下一步要用。

### 步骤 3 — 让 Dify 能访问 PowerContext

- **自托管 Dify（同机）**：跳过本步，`PC_BASE_URL` 直接填 `http://127.0.0.1:8000`。
- **Dify Cloud（跨网络）**：需要把本地 8000 端口暴露成公网地址。免下载方案用 localhost.run：
  ```bash
  ssh -R 80:localhost:8000 nokey@localhost.run
  ```
  命令会输出一个形如 `https://xxxxxxxx.lhr.life` 的公网地址，把它作为 `PC_BASE_URL`。
  > 注意：localhost.run 免费隧道空闲约 1–2 分钟会断开（返回 502 "no tunnel"），
  > 验证时请保持该 SSH 窗口开着并尽快操作；断了重跑命令换新地址即可。
  > 也可换用 cloudflared / ngrok 等任意内网穿透工具。

### 步骤 4 — 在 Dify 导入 DSL 并配置

1. Dify 控制台 → 创建应用 → **导入 DSL**，上传 `dsl/grudge-npc-chatflow.yml`。
2. 进入应用 → **环境变量**，设置：
   - `PC_BASE_URL` = 步骤 3 得到的地址（隧道 URL 或 `http://127.0.0.1:8000`）
   - `PC_SCOPE_ID` = 步骤 2 打印的 ID
3. 在 **模型供应商** 里安装 DeepSeek 插件并填入 API Key（见下方「凭据」）。
4. 打开应用「运行 / 预览」，开始对话。

### 步骤 5 — 验证

按 `evidence/验证样例.md` 操作：开一个**全新会话**输入 `掌柜的，好久不见，来壶酒`，
NPC 应主动提起蟑螂 / 赊账旧账。完整真实运行轨迹见 `evidence/验证证据01-跨会话记仇运行轨迹.md`。

---

## 6. 凭据（重要：仓库内一律占位符，勿提交真实值）

| 变量 | 说明 | 示例（占位符） |
|------|------|--------------|
| DeepSeek API Key | Dify 模型供应商里填写，**不进仓库** | `sk-xxxxxxxxxxxxxxxxxxxxxxxx` |
| `PC_BASE_URL` | PowerContext 可访问地址 | `http://127.0.0.1:8000` 或隧道 URL |
| `PC_SCOPE_ID` | 演示作用域 ID，由 init 脚本生成 | `scp_xxxxxxxxxxxxxxxx` |

- API Key 只在 Dify 控制台配置，本仓库任何文件都不包含真实密钥。
- 隧道地址是临时的，每次重连都会变，无需也不应写入仓库。

---

## 7. 常见问题

- **NPC 没翻旧账 / 说不知道**：检查 `PC_SCOPE_ID` 是否和 init 脚本打印的一致；
  用 `验证样例.md` 的 curl 命令确认作用域里确实有记忆条目。
- **Dify 报连接超时 / 502**：隧道断了，重跑 `ssh -R 80:localhost:8000 nokey@localhost.run`
  拿新地址并更新 `PC_BASE_URL`；或改用自托管 Dify + `127.0.0.1`。
- **模型报不兼容**：确认模型名为 `deepseek-v4-pro`（本插件版本无 `deepseek-chat`）。
