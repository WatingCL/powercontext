# 文献脉络 LitContext

[![qoder-litcontext-verify](https://github.com/WatingCL/powercontext/actions/workflows/qoder-verify.yml/badge.svg?branch=2026-competition-ecosystem)](https://github.com/WatingCL/powercontext/actions/workflows/qoder-verify.yml)

**在线站点（Qoder Sites 发布，未登录可访问）**：<https://litcontext-tr1zylcd1ih.qoder.website>

> 面向科研新手的文献上下文助手：把「读到哪、得出什么结论、为什么否掉某条路线」留在数据库里，
> 而不是留在上一次的聊天记录和你自己的脑子里。

本目录是 Qoder × OceanBase 赛题的参赛作品，核心模块 `litcontext` 把
**PowerContext** 当作研究记忆层：结论、取舍、约束、进度写入 Memory，
下次开工前按字节预算召回成一份可直接使用的上下文，并据此生成综述初稿与方法对比表。

---

## 一、要解决的问题

写毕设综述时，真实状态是这样的：

- 三个月前读过的 40 篇论文，只记得"有一篇说阈值法不行"，不记得是哪篇、为什么；
- 当时否掉 HMM 的理由（状态空间随电器数指数增长）写在了某个草稿里，找不到，于是又研究了一遍；
- 每次重新打开这个方向，都要花半小时翻聊天记录和笔记，才能想起"上次做到哪一步"；
- 笔记散在 Word、微信收藏、浏览器书签里，检索不到，也对照不起来。

根因不是"资料不够"，而是**研究判断没有被结构化地保存**。文献可以重新下载，
但"我为什么这么选"只存在于当时的上下文里，一旦会话结束就丢了。

`litcontext` 把这件事拆成两层：

| 层 | 存什么 | 丢了会怎样 |
| --- | --- | --- |
| 文献索引（本地 SQLite） | 论文正文切成的段落 | 可重建：重新 `ingest` 一遍即可 |
| 研究记忆（PowerContext） | 结论、否决理由、实验约束、进度、方法对比数据 | 不可重建：这是你自己的判断 |

---

## 二、它做什么

1. **导入文献**：`litcontext ingest <目录>`，支持 Markdown / 纯文本 / PDF（PDF 需 `pypdf`）。
   正文按章节切块写入索引，同时把摘要片段写进 PowerContext 的 Source journal 作为证据。
2. **检索原文**：`litcontext search "广义似然比 事件检测 误报"`，中英混排分词 + BM25，
   支持年份区间与"方法/数据集"字段过滤，结果带 `[paper_id §章节]` 出处。
   查询侧带一层 **NILM 领域同义扩展**（"虚警"→"误报"、"维特比"→"Viterbi"），
   `--explain` 可逐条查看扩了哪些词，`--no-expand` 可关掉做对比。
3. **写下判断**：三条命令分别记录——
   - `note --kind finding` 读到的结论（带 `--paper`、`--evidence`）
   - `note --kind decision --verdict reject` 否掉的路线**和理由**
   - `note --kind constraint` 实验约束（例如"只用 REDD house1"）
4. **召回上下文**：`litcontext resume` 输出"上次进度 / 已否掉的方向 / 约束 / 已积累结论"，
   并显示 PowerContext 的 `PreparedContext` 状态与字节占用（真实有界召回，不是把全部记忆倒出来）。
5. **出稿**：`litcontext brief --topic 事件检测` 生成综述初稿（每条论断带 `[paper_id]`），
   `litcontext compare` 生成方法对比表（方法 × 数据集 × 指标）。
6. **Web UI**：`litcontext serve`，左侧检索、右侧记忆读写、底边一键出稿，
   每个面板标注数据来自"本地索引"还是"PowerContext"。

---

## 三、各项技术的分工

本作品**只选用了 PowerContext**（赛题要求 seekdb / PowerContext 二者至少其一）。

| 组成 | 在项目中的角色 | 具体承担 | 能否替换 |
| --- | --- | --- | --- |
| **PowerContext** | 研究记忆层（核心） | Memory 存结论/取舍/约束/进度/对比数据；Source 存论文摘要证据；`/v1/context/prepare` 做有界上下文装配 | 不能：换成文件或数据库就退化成"另一个笔记软件"，跨会话召回与预算控制都没了 |
| 本地 SQLite + BM25 | 文献段落索引 | 把论文正文变成可检索的段落，供 `search` 与 `brief` 引用原文 | 能：删掉 `.data/` 重新 `ingest` 即可重建，不影响任何研究判断 |
| 大模型 | 不使用 | 初稿是确定性模板拼装，不调任何模型 API | 无：这样评审在自己机器上的输出与这里逐字一致 |

**为什么不接大模型？** 初稿的每条论断都来自记忆里的结论和索引里的原文段落，
出处必须可追溯。用模板拼装能保证"引用不幻觉"，而且评审不需要任何 API Key 就能复现。
如果以后要润色成通顺的自然语言，可以在 `report.py` 外面再加一层可选的改写步骤，
不改变"结论来自记忆、引用来自索引"的结构。

---

## 四、目录结构

```
qoder/
├── README.md                 本文件：项目说明与技术分工
├── RUNBOOK.md                运行说明：从装 PowerContext 到跑通验证样例
├── VERIFY-SAMPLE.md          验证样例：初始数据、操作步骤、预期结果
├── USAGE-RECORDS.md          真实使用记录（含数据来源与空白说明）
├── SUBMISSION.md             提交对照表：赛题要求 → 交付物位置，含提交前待办
├── docs/QODER-SESSION.md     Qoder 开发记录的录屏脚本（五个会话的逐字提问）
├── .env.example              配置样例（不含任何真实凭据）
├── data/samples/             5 篇演示语料（重写样本，见其中 README）
├── litcontext/               核心模块
│   ├── pyproject.toml
│   ├── src/litcontext/
│   │   ├── cli.py            ingest / search / note / progress / edge / resume / brief / compare
│   │   ├── pc.py             PowerContext HTTP 客户端（回环地址自动绕过代理）
│   │   ├── memory.py         记忆读写与解析（LITCORE|{...} 单行 JSON）
│   │   ├── builder.py        有界上下文装配（resume）
│   │   ├── report.py         综述初稿与方法对比表
│   │   ├── index.py          SQLite 索引 + BM25（支持同义扩展开关）
│   │   ├── synonyms.py       NILM 领域同义词表与查询扩展
│   │   ├── parser.py         md / txt / pdf 解析与切块
│   │   ├── text.py           中英混排分词
│   │   └── web.py            本地 Web UI（标准库 http.server）
│   └── tests/test_unit.py    20 个单元测试（不依赖 PowerContext，两个 PDF 用例需 pypdf）
├── scripts/demo.sh           一键跑完整验证流程
├── scripts/eval_recall.py    检索召回评测（16 条标注查询，扩展前/后对比）
├── scripts/reset.sh          清空本地索引（不动 PowerContext 记忆）
└── evidence/                 运行日志、出稿快照、UI 截图、召回评测结果
```

---

## 五、三步跑起来

```bash
# 1) 装好并启动 PowerContext（Server 默认 127.0.0.1:8000）
pip install "powercontext[cli,server]==1.5.0"
powercontext config init --template    # 模型全留空，Basic memory 即可
powercontext server run                # 保持这个终端

# 2) 装本作品
cd qoder
cp .env.example .env
pip install -e ./litcontext

# 3) 跑通
litcontext doctor
bash scripts/demo.sh
litcontext serve --port 8765
```

完整步骤与常见问题见 [RUNBOOK.md](RUNBOOK.md)。

---

## 六、验证样例（摘要）

5 篇演示语料 → 5 篇 / 24 段入索引 → 写 11 条记忆（3 结论 / 3 取舍 / 1 约束 / 1 进度 / 3 对比）
→ `resume` 召回 `ready`（3592 / 4000 字节）→ 生成 1891 字符综述初稿（引用 6 段原文）
与 3 行方法对比表。逐条命令与预期输出见 [VERIFY-SAMPLE.md](VERIFY-SAMPLE.md)。

另有一项可复现的量化：`python scripts/eval_recall.py` 用 16 条标注查询对比
"关闭 / 开启同义扩展"——命中@5 从 81% 提升到 100%，完全未命中率从 19% 降到 0，
MRR 从 0.573 升到 0.700；代价是 1 条查询从第 3 名降到第 4 名（仍在 top-5 内）。
逐条结果与失败案例分析见 [evidence/recall-eval.md](evidence/recall-eval.md)。

---

## 七、已知限制

- **检索以词面匹配为主**：中文按二元组切、英文按词切，没有语义向量。
  同义改写靠 `synonyms.py` 的领域词表兜底（实测 16 条标注查询命中@5 从 81%→100%），
  但换句式的语义改写（"小跃变为什么难检" vs "检测小的功率变化"）仍可能漏召回——
  领域词表只能覆盖术语级同义，覆盖不了句式级改写。这是为了"零依赖可复现"做的取舍。
- **PowerContext 的检索是"全部词命中"语义**：长句查询容易空召回，
  因此本模块统一用前缀 `LITCORE` 作为召回键，再在本地按类型/主题筛选。
- **记忆容量**：单次召回最多取服务端允许的 50 条；超过后建议按课题拆分 scope。
- **Windows 注意**：PowerContext 的 Windows 支持标注为 experimental。
  另外 `.env` 里的 `POWERCONTEXT_SERVER_MCP_PATH` 在 Windows 上会触发
  "MCP path must be an absolute non-root path" 校验错误，本作品不使用 MCP，删掉该行即可（见 RUNBOOK）。
- **PDF 只取文字层**：解析靠 `pypdf` 抽文字，扫描件（纯图片）抽不出内容，需要先 OCR；
  中文 PDF 的抽取质量取决于字体是否嵌入。测试里有一个最小 PDF 用例覆盖这条路径。
- 演示语料是为验证链路重写的样本，数值标注为"演示数值"，不能作为引用依据。
