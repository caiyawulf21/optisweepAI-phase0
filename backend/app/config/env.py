from __future__ import annotations

import os
from pathlib import Path


def _load_env_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    for candidate in (Path.cwd() / ".env", repo_root / ".env"):
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip("'").strip('"')


def load_local_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_fallback()
        return

    load_dotenv()
