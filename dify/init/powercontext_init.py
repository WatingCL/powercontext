"""PowerContext 初始化脚本 —— 《记仇的酒馆掌柜》Dify 作品

作用：
  1. 在本地 PowerContext Server 上创建一个全新的演示作用域（scope）；
  2. 预置两条“旧账”记忆（蟑螂恶作剧 + 赊账承诺），供 NPC 跨会话翻旧账；
  3. 打印 PC_SCOPE_ID，粘贴到 Dify 应用的环境变量即可。

前置：本地已启动 PowerContext Server（默认 http://127.0.0.1:8000）。

用法：
  py powercontext_init.py            # 复用同名作用域（若存在），否则新建
  py powercontext_init.py --new      # 强制新建一个空作用域（复验前重置用）

仅依赖标准库，无需安装任何第三方包。
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
SCOPE_TITLE = "记仇NPC大赛演示"

# 预置的“旧账”记忆：NPC 在新会话里会主动提起这些
SEED_MEMORIES = [
    {
        "kind": "fact",
        "text": "玩家张三趁掌柜不注意，往酒坛里放了一只蟑螂。",
        "reason": "init seed：恶作剧，供 NPC 记仇",
    },
    {
        "kind": "fact",
        "text": "张三上次喝酒赊了账，承诺下回一起还，至今未还。",
        "reason": "init seed：欠款承诺，供 NPC 记仇",
    },
]


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.load(r)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.status, json.load(r)


def main():
    fresh = "--new" in sys.argv
    suffix = time.strftime("%m%d%H%M") if fresh else ""
    title = SCOPE_TITLE + suffix

    st, scopes = get("/v1/scopes")
    hit = [s for s in scopes["items"] if s["title"] == title]
    if hit:
        scope_id = hit[0]["scope_id"]
        print("复用作用域:", scope_id)
    else:
        st, sc = post("/v1/scopes", {
            "title": title,
            "summary": "数据库大赛 Dify《记仇的酒馆掌柜》演示作用域",
            "idempotency_key": "grudge-npc-demo-" + (suffix or "001"),
        })
        scope_id = sc["scope_id"]
        print("新建作用域:", st, scope_id)

    for m in SEED_MEMORIES:
        body = dict(m)
        body["scope_id"] = scope_id
        st, mem = post("/v1/memory/remember", body)
        print("写入记忆:", st, json.dumps(mem, ensure_ascii=False)[:200])

    print()
    print("=" * 60)
    print("请把下面这个 ID 填到 Dify 应用环境变量 PC_SCOPE_ID：")
    print("PC_SCOPE_ID=" + scope_id)
    print("=" * 60)


if __name__ == "__main__":
    main()
