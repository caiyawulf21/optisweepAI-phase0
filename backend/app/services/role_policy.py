from __future__ import annotations

import re


def _norm(value: str | None) -> str:
    return re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())


def _role_level(value: str | None) -> int | None:
    normalized = _norm(value)
    if not normalized:
        return None
    if normalized in {"support", "operator", "any"}:
        return 1
    if "l1" in normalized:
        return 1
    if "l2" in normalized:
        return 2
    if "l3" in normalized:
        return 3
    if any(
        marker in normalized
        for marker in (
            "engineer",
            "controls",
            "software",
            "infra",
            "systems",
            "devops",
            "dba",
        )
    ):
        return 3
    return None


def is_role_allowed(required_role: str | None, operator_role: str | None) -> bool:
    normalized_required = _norm(required_role)
    if not normalized_required or normalized_required in {"support", "operator", "any"}:
        return True
    required_level = _role_level(required_role)
    if required_level is None:
        return False
    operator_level = _role_level(operator_role)
    if operator_level is None:
        return False
    return operator_level >= required_level


__all__ = ["is_role_allowed"]
