# 运行说明（RUNBOOK）

从零到跑通验证样例的完整步骤。示例在 **Windows 11 + Python 3.13** 上执行过，
Linux / macOS 步骤相同（仅虚拟环境激活命令不同）。

---

## 0. 前置

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.11+ | PowerContext 要求 >=3.11 |
| PowerContext | 1.5.0 | 本作品的记忆层 |
| 网络 | 可访问 PyPI | 首次安装需要 |

不需要 Docker、不需要数据库服务、不需要任何大模型 API Key。
（PowerContext 的 Basic memory 模式无需模型凭证。）

---

## 1. 安装 PowerContext 并启动服务

```bash
# 建议单独建一个虚拟环境，避免污染系统 Python
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install "powercontext[cli,server]==1.5.0"

# 生成配置（一路回车用默认值即可）
powercontext config init

# 启动服务，保持这个终端不关
powercontext server run
```

服务默认监听 `http://127.0.0.1:8000`。另开一个终端确认存活：

```bash
curl http://127.0.0.1:8000/health/live
```

> 若 `powercontext config init` 要求填写模型凭证：Basic memory 模式下全部留空即可，
> 本作品不使用生成式模型，结论由你自己写、由程序组装。

---

## 2. 安装本作品

```bash
cd qoder

# 复制配置（把 POWERCONTEXT_URL 指向你刚启动的服务）
cp .env.example .env

# 安装模块（-e 表示可编辑安装，改了代码立即生效）
pip install -e ./litcontext

# 自检：能看到索引与 PowerContext 状态
litcontext doctor
```

`doctor` 期望输出：

```
数据目录       .../qoder/.data
本地索引       0 篇 / 0 段（SQLite）
PowerContext   http://127.0.0.1:8000 -> 可用
scope          <scope_id>（litcontext-nilm-event-detection）
记忆条数       0
```

> **代理注意事项**：如果你的机器设置了 `HTTP_PROXY` / `HTTPS_PROXY`，
> 访问 127.0.0.1 会被转到代理上并失败。本模块对回环地址自动绕过代理
> （见 `litcontext/src/litcontext/pc.py` 的 `_opener`），无需手动处理。

---

## 3. 导入文献

```bash
# 仓库自带 5 篇演示语料（重写样本，见 data/samples/README.md）
litcontext ingest data/samples

# 换成你自己的论文（支持 .md / .txt / .pdf，目录会递归扫描）
litcontext ingest ~/papers/nilm
```

每条导入会同时做两件事：

1. 正文切块写入本地 SQLite 索引（供检索）；
2. 摘要片段写入 PowerContext 的 Source journal（作为证据留存）。

产出形如：

```
[导入] p-anderson12 Event Detection for Non-Intrusive Load Monitoring   5 段
完成：新增/更新 5 篇，索引现有 5 篇 24 段
```

---

## 4. 检索

```bash
litcontext search "广义似然比 事件检测 误报" --top 3
litcontext search "阈值 跨户" --year-from 2018 --top 5
```

---

## 5. 写入研究记忆（本作品的核心）

三类记忆，分别回答三个问题：

```bash
# 我读到了什么结论（来源可追溯）
litcontext note --kind finding --paper p-anderson12 --topic 事件检测 \
  --text "GLR 在大幅跃变上精确率明显高于固定阈值，但小跃变仍是瓶颈" \
  --evidence "BLUED，|ΔP|>300W"

# 我为什么否决一条路线（避免下次再走一遍）
litcontext note --kind decision --topic 事件检测 --method HMM --verdict reject \
  --text "因子 HMM 的状态空间随电器数指数增长，全屋场景推断耗时不可接受" \
  --reason "毕设只做单户事件检测，算力有限"

# 实验约束（防止方案跑偏）
litcontext note --kind constraint \
  --text "只用 REDD house1，不外采数据；评测必须报事件级 F1"

# 进度
litcontext progress --done "读完 5 篇事件检测基础文献" \
  --current "在 REDD 上复现阈值基线" --next "对比 GLR 与 CUSUM 的误报率"

# 方法对比（生成对比表用）
litcontext edge --paper p-anderson12 --method GLR --dataset BLUED \
  --metric F1 --value 0.89 --note "|ΔP|>300W"
```

---

## 6. 召回与出稿

```bash
# 一屏看到"上次读到哪、为什么这么定"
litcontext resume

# 生成综述初稿（每条论断带 [paper_id] 出处）
litcontext brief --topic 事件检测 -o out/brief.md

# 生成方法对比表
litcontext compare -o out/compare.md
```

---

## 7. Web UI

```bash
litcontext serve --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`：左侧检索原文，右侧查看/写入研究记忆，
底部一键出稿。页面右上角会显示 PowerContext 是否连通。

---

## 8. 复现验证样例

见 [VERIFY-SAMPLE.md](VERIFY-SAMPLE.md)，一条命令式的流程与预期输出都在里面。

一键脚本：

```bash
bash scripts/demo.sh      # 跑完整流程
bash scripts/reset.sh     # 清空本地索引（不动 PowerContext 记忆）
```

---

## 9. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `PowerContext ... 不可达` | 服务没起：`powercontext server run`；或端口不是 8000，改 `.env` 的 `POWERCONTEXT_URL` |
| 召回为空但确实写过记忆 | 确认两次用的是同一个 `LITCONTEXT_SCOPE_KEY`；scope 不同记忆不互通 |
| `powercontext: command not found` | 没激活虚拟环境，或没装 `[cli,server]` 附加依赖 |
| 导入 PDF 报 `需要 pypdf` | `pip install pypdf`（PDF 解析是可选的） |
| Windows 上服务启动即退出 | 用 PowerShell / CMD 而不是 Git Bash 启动 `powercontext server run`；Windows 支持在 PowerContext 中标注为 experimental |
| 中文检索命中少 | 中文按二元组切分，查询尽量用论文里的实词（如"暂态 阶跃 事件"） |
