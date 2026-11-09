# Qoder 开发记录：照着念的录屏脚本

赛题要求"必须真实使用 Qoder 开发并录制开发过程"。这一步只能你本人做，
但**不需要现场想**——下面把五个会话的提问逐字写好了，你复制、粘贴、等结果、
录屏即可。每个会话都对应仓库里已经存在的一份真实代码，Qoder 生成的东西
应当和它们高度相似（不完全一致没关系，方向对就行）。

## 0. 录屏前 5 分钟准备

```bash
# 1. 确认分支与仓库
cd <你的本地 powercontext 仓库>
git checkout 2026-competition-ecosystem
git log --oneline -2          # 应看到 f85d546 / a5926fd 之后的新提交

# 2. 清掉本地数据，让 Qoder 从零跑一遍（录屏里"从零到有"更有说服力）
rm -rf qoder/.data qoder/out

# 3. 起 PowerContext（另开一个终端，整段录屏期间不要关）
cd pc_runtime && ../.venv_pc/Scripts/powercontext.exe server run
curl http://127.0.0.1:8000/health/live     # 返回 {"status":"ok"}
```

录屏软件建议：Windows 用 Win+G（Xbox Game Bar）或 OBS，全程 1080p，
**不要剪辑掉报错片段**——评审看的就是你怎么定位问题。

开场先录这三样，各停 3 秒：

1. Qoder 窗口里登录的账号（能看到 UID 或绑定邮箱）
2. 终端 `git remote -v` 显示 `https://github.com/WatingCL/powercontext`
3. 终端 `powercontext server run` 正在跑

## 会话 1：让 Qoder 读懂赛题与仓库（约 3 分钟）

在 Qoder 里打开仓库根目录，新建对话，粘贴：

```
读一下仓库根目录的赛题要求和 qoder/ 目录的现状。
仓库是 oceanbase/powercontext 的 fork，分支 2026-competition-ecosystem。
旁边 minimax/ 是其他选手的参考实现。

回答三个问题：
1. 这道题验收时最看重什么？
2. minimax/ 这个参考实现的结构是怎样的，哪几个文件是核心？
3. 如果我要做一个"NILM 科研文献助手"，本地检索用 SQLite，研究判断用 PowerContext 存，
   应该分成哪几个模块？
先不要写代码，只给结构和理由。
```

**要录到的画面**：Qoder 打开 `qoder/`、`minimax/sddcontext/` 的文件树，
回答里明确提到"真实使用 PowerContext""有可复现的验证过程"。

## 会话 2：实现 PowerContext 客户端（约 8 分钟，核心）

```
在 qoder/litcontext/src/litcontext/pc.py 实现一个 PowerContext 1.5 的 HTTP 客户端，
只用标准库 urllib，不要引 requests。

需要这几个方法：
- healthy()           GET  /health/live
- ensure_scope()      POST /v1/scopes，用 idempotency_key 保证幂等，结果缓存到本地文件
- remember(kind,text,reason)  POST /v1/memory/remember
- search_memory(q,n)  POST /v1/memory/search
- prepare(q,max_bytes) POST /v1/context/prepare

要求：
1. 服务不可达时抛 PowerContextError，不要让调用方看到 URLError；
2. 记录 self.calls，每条包含 method/path/status/耗时，UI 上要展示"真的调用过"；
3. 本机有 HTTP_PROXY 环境变量，访问 127.0.0.1 时必须绕过代理。

写完后告诉我怎么用 curl 核对每个端点的真实返回结构。
```

**要录到的画面**：Qoder 写出文件 → 你在终端跑
`curl -s http://127.0.0.1:8000/openapi.json | python -m json.tool | head -50`
核对字段。这一步是"没瞎编 API"的证据。

> 如果 Qoder 写的是 `requests` 或猜了错误的响应结构，当场让它改：
> "不要用 requests，只用标准库；另外 /v1/memory/search 返回的是
> hits[].memory.text 这种嵌套结构，按真实结构改。"

## 会话 3：让 Qoder 踩一次真坑（约 6 分钟，最能体现"真实使用"）

```
我在 Windows 上执行 powercontext server run，启动即退出，报错：
  ValueError: MCP path must be an absolute non-root path: '/mcp'

但我 .env 里写的是 POWERCONTEXT_SERVER_MCP_PATH=/mcp，这明显是绝对路径。
帮我定位：是配置加载的问题还是我写错了？给出排查步骤。
```

**要录到的画面**：Qoder 去读 `site-packages/powercontext/server/settings.py`
和 `configuration.py`，最后给出"Windows 下路径解析异常 / 本作品不需要 MCP，
移除这两行"的结论，然后你在终端改 `.env` 重启，服务起来。

> 这段是整场录屏最有价值的部分：真实的报错、真实的定位过程。
> 如果 Qoder 一次答对，就把这一段多讲两句为什么这样改。

## 会话 4：加同义扩展与召回评测（约 10 分钟）

```
qoder/litcontext 里已经有 BM25 检索（index.py + text.py，中文按二元组分词）。
问题是：用户用"虚警""维特比"提问时完全搜不到，论文里写的是"误报""Viterbi"。

请：
1. 新增 synonyms.py，做查询侧领域同义词扩展（NILM 领域词表），
   原词权重 1.0，扩展词 0.4，单个词最多扩 8 个 token；
2. index.py 的 search 增加 expand 参数，默认开启，能关掉做对比；
3. 新增 scripts/eval_recall.py：写 16 条标注查询（提问 + 真正能回答它的 paper_id），
   分别算关闭/开启扩展的 命中@1/@3/@5、MRR、完全未命中率，输出 markdown 表格；
4. 补单元测试：扩展必须能救回一条字面检索搜不到的查询。
```

**要录到的画面**：Qoder 改完 → 你跑
`litcontext search "维特比解码" --no-expand`（无结果）
再跑 `litcontext search "维特比解码" --explain`（有结果 + 打印扩展词），
最后 `python scripts/eval_recall.py` 输出对比表。

## 会话 5：修一个线程 bug（约 4 分钟）

```
litcontext serve 起来后，浏览器打开首页，每个面板都报
"SQLite objects created in a thread can only be used in that same thread"。
web.py 用的是 ThreadingHTTPServer。请给出最小改动方案并说明为什么这么改。
```

**要录到的画面**：Qoder 说明 `check_same_thread=False` + 一把 `threading.Lock`
串行化访问，你改完重启，页面正常。

## 收尾（约 2 分钟）

```bash
cd qoder
bash scripts/demo.sh          # 一条命令跑完：导入→检索→评测→记忆→召回→出稿
```

把终端最后的输出停在 `resume` 那一段（显示 `ready 3592/4000 字节`）和
`已写出 out/brief.md` 上，停 5 秒。然后打开 `http://127.0.0.1:8765/` 展示 UI。

## 交付前核对清单

- [ ] 录屏里有 Qoder 账号 UID（评审要核对是不是本人）
- [ ] 五个会话都在，且中间有真实的报错与修复
- [ ] 最后 demo.sh 跑通、UI 能打开
- [ ] 录屏文件放进网盘，链接写进 `USAGE-RECORDS.md` 的"开发过程"一节
- [ ] Qoder Sites 发布的站点链接也写进同一节

> 别用 AI 生成 Qoder 的聊天截图。评审见过太多，一眼能看出来，
> 一旦被认定为伪造，整份作品直接出局。
