from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import PurePosixPath


README_PATH = "README.md"

WATCHED_PREFIXES = (
    "backend/app/api/",
    "backend/app/graph/",
    "backend/app/models/",
    "backend/app/repositories/",
    "backend/app/schemas/",
    "backend/app/search/",
    "backend/app/seed/",
    "backend/app/services/",
    "backend/app/storage/",
    "data/context/",
    "data/curated/",
    "data/evidence/",
    "data/incidents/",
    "data/procedures/",
    "data/review/",
    "data/taxonomy/",
    "data/timelines/",
    "data/video_sources/",
    "data/workflows/",
    "docs/",
    "ingestion/",
    "scripts/",
)

WATCHED_EXACT = {
    ".env.example",
    "requirements.txt",
    "requirements-backend.txt",
    "requirements-ocr.txt",
}


def respond(payload: dict[str, object]) -> None:
    print(json.dumps(payload))


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def requires_readme(path: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    return normalized in WATCHED_EXACT or normalized.startswith(WATCHED_PREFIXES)


def command_from_input(raw: str) -> str:
    if not raw.strip():
        return ""
    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return str(hook_input.get("command") or "")


def is_git_commit_command(command: str) -> bool:
    return bool(re.search(r"(^|[;&|]\s*)git\s+commit\b", command))


def main() -> int:
    try:
        raw = sys.stdin.read() or "{}"
        command = command_from_input(raw)
        if not is_git_commit_command(command):
            respond({"permission": "allow"})
            return 0

        files = staged_files()
        if not files or README_PATH in files:
            respond({"permission": "allow"})
            return 0

        watched = [path for path in files if requires_readme(path)]
        if not watched:
            respond({"permission": "allow"})
            return 0

        sample = "\n".join(f"- {path}" for path in watched[:10])
        suffix = "" if len(watched) <= 10 else f"\n- ...and {len(watched) - 10} more"
        respond(
            {
                "permission": "deny",
                "user_message": (
                    "README maintenance required before this commit. The staged changes touch architecture, "
                    "runtime, dataset, workflow, ingestion, docs, or dependency areas, but README.md is not staged.\n\n"
                    f"Review README.md and stage an update, or explicitly make a no-op README update if the current "
                    f"README already reflects these changes.\n\nFlagged files:\n{sample}{suffix}"
                ),
                "agent_message": "The README maintenance hook blocked git commit because README.md was not staged with significant repository changes.",
            }
        )
        return 0
    except Exception as exc:
        respond(
            {
                "permission": "deny",
                "user_message": f"README maintenance hook failed: {exc}",
                "agent_message": "Fix .cursor/hooks/readme_maintenance_guard.py or retry after confirming README.md maintenance manually.",
            }
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
