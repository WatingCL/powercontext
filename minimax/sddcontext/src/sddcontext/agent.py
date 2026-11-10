"""MiniMax-driven implementation step.

Sends the assembled context to the MiniMax chatcompletion API and applies
the returned code changes. The full interaction (prompt context, model,
response, usage) is persisted as a JSON record under ``evidence/`` and also
captured as a PowerContext Source, which is what evaluators check against
the submitted code diff.

Output contract given to the model:

    ### FILE: <path relative to the repo root>
    ```python
    <complete new file content>
    ```
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .state import PowerContextClient

FILE_MARKER_RE = re.compile(r"###\s*FILE:\s*(\S+)")
CODE_BLOCK_RE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.S)

SYSTEM_PROMPT = """你是一名严谨的 Python 工程师。你会收到一份“开发上下文”，包含任务目标、适用规格条目、
相关代码符号和验证测试。请完成代码修改，并严格遵守：

1. 只修改任务要求涉及的文件，输出每个被修改文件的完整新内容；
2. 完全满足“适用规格条目”中列出的要求；
3. 不得破坏“必须保持的行为”，回归测试必须继续通过；
4. 不修改任何测试文件。

输出格式（不要输出其他解释性文字）：

### FILE: <相对仓库根目录的文件路径>
```python
<完整的新文件内容>
```
"""


@dataclass
class MiniMaxRecord:
    task_id: str
    model: str
    prompt_context: str
    response_text: str
    usage: Dict[str, Any] = field(default_factory=dict)
    changed_files: List[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "created_at": self.created_at,
            "system_prompt": SYSTEM_PROMPT,
            "prompt_context": self.prompt_context,
            "response_text": self.response_text,
            "usage": self.usage,
            "changed_files": self.changed_files,
        }


class MiniMaxError(RuntimeError):
    pass


def _DIRECT_OPENER():
    """An opener that ignores ``http_proxy``/``https_proxy`` (direct dial)."""
    from urllib.request import ProxyHandler, build_opener

    return build_opener(ProxyHandler({}))


# base_resp.status_code values that mean "this model name is unusable, try the
# next candidate" rather than "the request/account is broken".
MODEL_UNAVAILABLE_CODES = {2013, 2069}
# Account-level problems: retrying another model cannot help.
FATAL_CODES = {
    1002: "rate limited by MiniMax",
    1004: "invalid MINIMAX_API_KEY (authentication failed)",
    1008: "MiniMax account has insufficient balance - top up or use a funded key",
}


class MiniMaxClient:
    def __init__(self, cfg: Config):
        if not cfg.minimax_api_key:
            raise MiniMaxError(
                "MINIMAX_API_KEY is not set; export it before running the implement step"
            )
        self.cfg = cfg

    def chat(self, system: str, user: str, temperature: float = 0.2,
             max_tokens: int = 8192) -> Dict[str, Any]:
        """Call MiniMax, negotiating the model name when a name is retired.

        Returns ``{"text", "usage", "raw", "model"}`` where ``model`` is the
        model that actually answered.
        """
        attempts: List[str] = []
        for model in self.cfg.minimax_model_candidates:
            try:
                return self._chat_with_model(
                    model, system, user, temperature, max_tokens
                )
            except _ModelUnavailable as error:
                attempts.append(f"{model}: {error}")
                continue
            except MiniMaxError:
                raise
        raise MiniMaxError(
            "no usable MiniMax model available for this account; tried: "
            + " | ".join(attempts)
        )

    def _chat_with_model(self, model: str, system: str, user: str,
                         temperature: float, max_tokens: int) -> Dict[str, Any]:
        data = self._post(model, system, user, temperature, max_tokens)

        base_resp = data.get("base_resp") or {}
        status_code = base_resp.get("status_code")
        status_msg = base_resp.get("status_msg") or ""
        if status_code not in (None, 0):
            if status_code in MODEL_UNAVAILABLE_CODES:
                raise _ModelUnavailable(f"code {status_code}: {status_msg}")
            if status_code in FATAL_CODES:
                raise MiniMaxError(
                    f"MiniMax code {status_code}: {FATAL_CODES[status_code]}"
                    f" (server said: {status_msg})"
                )
            raise MiniMaxError(f"MiniMax code {status_code}: {status_msg}")

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as error:
            raise MiniMaxError(f"unexpected MiniMax response: {json.dumps(data)[:1000]}") from error
        return {
            "text": text,
            "usage": data.get("usage", {}),
            "raw": data,
            "model": model,
        }

    def _post(self, model: str, system: str, user: str,
              temperature: float, max_tokens: int) -> Dict[str, Any]:
        """POST to the chat API.

        Tries the environment-configured proxy first (the API is reachable
        directly from mainland China but may need a proxy elsewhere), and
        retries without any proxy when the connection itself fails.
        """
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, build_opener

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self.cfg.minimax_base_url.rstrip('/')}/text/chatcompletion_v2"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cfg.minimax_api_key}",
        }

        last_error: Optional[Exception] = None
        for use_proxy in (True, False):
            opener = build_opener() if use_proxy else _DIRECT_OPENER()
            request = Request(url, data=body, headers=headers, method="POST")
            try:
                with opener.open(request, timeout=600) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:1000]
                raise MiniMaxError(f"MiniMax API HTTP {error.code}: {detail}") from error
            except (URLError, OSError) as error:
                last_error = error
                continue
        raise MiniMaxError(f"MiniMax API unreachable: {last_error}")


class _ModelUnavailable(MiniMaxError):
    """Model name not offered to this account - try the next candidate."""


def parse_file_blocks(response_text: str) -> List[Dict[str, str]]:
    """Parse ``### FILE: path`` + fenced code block pairs from the response."""
    results: List[Dict[str, str]] = []
    positions = [(m.start(), m.group(1)) for m in FILE_MARKER_RE.finditer(response_text)]
    for i, (start, path) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(response_text)
        segment = response_text[start:end]
        block = CODE_BLOCK_RE.search(segment)
        if block:
            content = block.group(1)
            if not content.endswith("\n"):
                content += "\n"
            results.append({"path": path.strip(), "content": content})
    return results


def apply_changes(cfg: Config, blocks: List[Dict[str, str]], repo_root: Path) -> List[Path]:
    """Write returned file contents back, after safety checks.

    Paths are resolved against the repo root and must stay inside it.
    Originals are snapshotted to ``evidence/snapshots/`` first.
    """
    snapshot_dir = cfg.evidence_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for block in blocks:
        rel = block["path"].replace("\\", "/").lstrip("/")
        # normalise "minimax/project/..." and "project/..." to project-relative
        if rel.startswith("minimax/"):
            rel = rel[len("minimax/"):]
        target = (repo_root / rel).resolve()
        project_root = cfg.project_dir.resolve()
        if project_root not in target.parents:
            raise MiniMaxError(f"refusing to write outside project dir: {block['path']}")
        if not target.exists():
            raise MiniMaxError(f"model returned unknown file: {block['path']}")
        backup = snapshot_dir / f"{stamp}_{rel.replace('/', '__')}"
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.write_text(block["content"], encoding="utf-8")
        written.append(target)
    return written


def implement(cfg: Config, context_markdown: str, task_id: str,
              repo_root: Path, pc: Optional[PowerContextClient] = None) -> MiniMaxRecord:
    """Run the MiniMax implementation step end to end."""
    client = MiniMaxClient(cfg)
    result = client.chat(SYSTEM_PROMPT, context_markdown)
    blocks = parse_file_blocks(result["text"])
    if not blocks:
        raise MiniMaxError(
            "model response contained no parsable '### FILE:' blocks; "
            f"response head: {result['text'][:500]}"
        )
    written = apply_changes(cfg, blocks, repo_root)
    used_model = result.get("model") or cfg.minimax_model

    record = MiniMaxRecord(
        task_id=task_id,
        model=used_model,
        prompt_context=context_markdown,
        response_text=result["text"],
        usage=result.get("usage", {}),
        changed_files=[str(w) for w in written],
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    cfg.evidence_dir.mkdir(parents=True, exist_ok=True)
    record_dir = cfg.evidence_dir / "minimax-records"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{task_id}-{record.created_at.replace(':', '')}.json"
    record_path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if pc is not None:
        try:
            pc.record_source(
                source_id=f"minimax-implement-{task_id}",
                content=json.dumps(record.to_dict(), ensure_ascii=False),
                metadata={
                    "origin": "sddcontext.implement",
                    "task_id": task_id,
                    "model": used_model,
                    "changed_files": record.changed_files,
                },
            )
        except Exception:
            # evidence is already on disk; PowerContext capture is best-effort
            pass
    return record
