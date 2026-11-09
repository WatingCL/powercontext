"""运行配置：全部来自环境变量或 ``.env``，不写死地址与凭据。

优先级：命令行参数 > 环境变量 > ``.env`` > 默认值。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

# qoder/ 目录（仓库内本作品根目录）：.../qoder/litcontext/src/litcontext/config.py
MODULE_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_PC_URL = "http://127.0.0.1:8000"
DEFAULT_SCOPE_KEY = "litcontext-nilm-event-detection"
DEFAULT_SCOPE_TITLE = "NILM 事件检测（毕业设计）"


def read_dotenv(path: Optional[Path] = None) -> Dict[str, str]:
    """极简 .env 解析：``KEY=VALUE``，忽略注释与空行。"""
    path = path or (MODULE_ROOT / ".env")
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class Config:
    """一次运行需要的全部配置。"""

    data_dir: Path
    db_path: Path
    pc_url: str
    scope_key: str
    scope_title: str
    timeout: int = 20

    @classmethod
    def load(
        cls,
        data_dir: Optional[str] = None,
        pc_url: Optional[str] = None,
        scope_key: Optional[str] = None,
        scope_title: Optional[str] = None,
    ) -> "Config":
        dotenv = read_dotenv()

        def pick(cli_value: Optional[str], env_key: str, default: str) -> str:
            if cli_value:
                return cli_value
            return os.environ.get(env_key) or dotenv.get(env_key) or default

        root = Path(pick(data_dir, "LITCONTEXT_DATA_DIR", str(MODULE_ROOT / ".data")))
        root = root if root.is_absolute() else (MODULE_ROOT / root)
        return cls(
            data_dir=root,
            db_path=root / "index.sqlite3",
            pc_url=pick(pc_url, "POWERCONTEXT_URL", DEFAULT_PC_URL).rstrip("/"),
            scope_key=pick(scope_key, "LITCONTEXT_SCOPE_KEY", DEFAULT_SCOPE_KEY),
            scope_title=pick(scope_title, "LITCONTEXT_SCOPE_TITLE", DEFAULT_SCOPE_TITLE),
            timeout=int(pick(None, "LITCONTEXT_TIMEOUT", "20")),
        )
