from __future__ import annotations

import sys
from pathlib import Path

"""Backward-compatible entry point.

Prefer: streamlit run ui/Home.py
This module forwards to the playbook runtime UI.
"""

_HOME = Path(__file__).resolve().with_name("Home.py")
exec(compile(_HOME.read_text(encoding="utf-8"), str(_HOME), "exec"), {"__name__": "__main__", "__file__": str(_HOME)})
