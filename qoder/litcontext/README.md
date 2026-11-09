# litcontext

科研文献上下文模块：把"NILM 事件检测"这类研究方向上的论文、结论、否决理由和阅读进度，
拆成可检索的文献索引（本地 SQLite）和可跨会话复用的记忆（PowerContext）。

安装（开发模式）：

```bash
pip install -e ./litcontext
```

模块只依赖标准库；PDF 解析额外需要 `pypdf`（可选）。

入口：`litcontext`（命令行）、`litcontext serve`（本地 Web UI）。
