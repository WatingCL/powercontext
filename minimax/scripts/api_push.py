#!/usr/bin/env python
"""Push changed files to a branch via the GitHub REST API.

Used while the local proxy cannot reach github.com (git push fails with
CONNECT 502) but api.github.com is reachable directly.

Usage:
    python api_push.py <token> <branch> <commit-message-file> <path> [<path> ...]
"""
import base64
import json
import sys
import urllib.request

API = "https://api.github.com/repos/WatingCL/powercontext"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(method, url, token, data=None):
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "sdd-demo",
        },
    )
    with OPENER.open(req, timeout=60) as r:
        return json.loads(r.read().decode())


TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".json", ".txt", ".toml", ".sh",
                 ".diff", ".cfg", ".ini", ".example", ".gitattributes"}


def read_blob_content(path: str) -> bytes:
    """Read the file the way git would store it (LF line endings for text).

    .gitattributes normalises text files to LF, but this script uploads raw
    bytes through the API and therefore has to do the same, otherwise every
    checkout on Linux shows the whole file as rewritten.
    """
    import os

    raw = open(path, "rb").read()
    suffix = os.path.splitext(path)[1] or os.path.basename(path)
    if suffix in TEXT_SUFFIXES:
        raw = raw.replace(b"\r\n", b"\n")
    return raw


def main():
    token, branch, msg_file = sys.argv[1], sys.argv[2], sys.argv[3]
    paths = sys.argv[4:]
    message = open(msg_file, encoding="utf-8").read().strip()

    head = api("GET", f"{API}/branches/{branch}", token)
    head_sha = head["commit"]["sha"]
    base_tree = head["commit"]["commit"]["tree"]["sha"]
    print("remote head:", head_sha[:9])

    entries = []
    for path in paths:
        raw = read_blob_content(path)
        sha = api("POST", f"{API}/git/blobs", token,
                  {"content": base64.b64encode(raw).decode(), "encoding": "base64"})["sha"]
        entries.append({"path": path.replace("\\", "/"), "mode": "100644",
                        "type": "blob", "sha": sha})
    tree = api("POST", f"{API}/git/trees", token,
               {"base_tree": base_tree, "tree": entries})
    print("new tree:", tree["sha"][:9])

    commit = api("POST", f"{API}/git/commits", token,
                 {"message": message, "tree": tree["sha"], "parents": [head_sha]})
    print("new commit:", commit["sha"][:9])

    ref = api("PATCH", f"{API}/git/refs/heads/{branch}", token, {"sha": commit["sha"]})
    print("ref updated ->", ref["object"]["sha"][:9])


if __name__ == "__main__":
    main()
