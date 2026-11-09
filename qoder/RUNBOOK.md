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

### 1.1 两个必踩的坑（Windows）

**① `config init` 生成 `.env` 后启动可能报错**

```
Invalid value: 1 validation error for ServerSettings
mcp.path
  Value error, MCP path must be an absolute non-root path
```

原因：PowerContext 在 Windows 上把 `POWERCONTEXT_SERVER_MCP_PATH=/mcp` 解析成了非绝对路径。
本作品不使用 MCP，**把 `.env` 里这两行删掉即可**：

```diff
- POWERCONTEXT_SERVER_MCP_ENABLED=true
- POWERCONTEXT_SERVER_MCP_PATH=/mcp
```

**② 数据库默认落在 C 盘**

默认位置是 `%LOCALAPPDATA%\PowerContext\powercontext.db`。想放到别处，在 `.env` 里加一行：

```
POWERCONTEXT_HOME=D:/your/path/pc_runtime/home
```

（同一份 `.env` 里 `POWERCONTEXT_HOME` 指向的目录会被创建并用于存放 sqlite 库。）

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

> PDF 需要 `pip install pypdf`，且只能抽文字层：扫描件要先 OCR，中文 PDF 取决于字体是否嵌入。
> 抽不出文字的 PDF 会报"没有解析出任何正文段落"，不会静默进一个空文档。

---

## 4. 检索

```bash
litcontext search "广义似然比 事件检测 误报" --top 3
litcontext search "阈值 跨户" --year-from 2018 --top 5
```

### 4.1 同义扩展：为什么"虚警"也能搜到"误报"

检索是 BM25 字面匹配，但查询侧加了一层 NILM 领域词表（`synonyms.py`）：
命中"虚警/门限/维特比"这类说法时，会把同组的"误报/阈值/Viterbi"以 0.4 的权重
一并加进查询。索引里始终存原文，重建索引不会改变检索口径。

```bash
# 看它到底扩了什么（评审可逐条核对，不是黑箱）
litcontext search "门限设多少才不虚警" --explain

# 关掉扩展，对比一下字面检索会漏什么
litcontext search "维特比解码" --no-expand     # 无结果
litcontext search "维特比解码" --explain       # 命中 p-zeifman11，排第一
```

改了词表或调了权重之后，用固定评测集回测（脚本自带 16 条标注查询，不读外部文件）：

```bash
python scripts/eval_recall.py
# 输出：命中@1/@3/@5、完全未命中率、MRR，逐条名次写进 evidence/recall-eval.md
# CI 里用 --check：命中@5 ≥ 0.95 且未命中率 ≤ 0.05，不达标直接让流水线红掉
```

> 当前基线：未命中率 18.8% → 0，命中@5 81% → 100%，MRR 0.573 → 0.700，
> 代价是 1 条查询名次下降（deep learning 第 3 → 第 4）。

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
| Windows 上服务启动即退出 | 见 §1.1：删掉 `.env` 里的 `POWERCONTEXT_SERVER_MCP_*` 两行；另建议用 PowerShell / CMD 而不是 Git Bash 启动 |
| 中文检索命中少 | 先用 `--explain` 看查询被切/扩成什么；领域词表覆盖不到的说法，在 `synonyms.py` 里加一组即可，然后用 `scripts/eval_recall.py` 回测有没有把别的查询带坏 |
| 想确认换台机器也能跑 | 看 GitHub Actions 的 [qoder-litcontext-verify](https://github.com/WatingCL/powercontext/actions/workflows/qoder-verify.yml)：干净 Ubuntu 上装 PowerContext、起服务、跑完整流程与召回评测，10 个业务步骤全绿，产物在 Artifacts |
