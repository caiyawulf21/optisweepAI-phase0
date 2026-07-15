from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_RUNTIME_PACKAGES = {
    "fastapi",
    "uvicorn[standard]",
    "streamlit",
    "requests",
    "pydantic",
    "langgraph",
    "PyYAML",
    "openai",
    "python-dotenv",
    "azure-cosmos",
    "azure-storage-blob",
    "azure-identity",
    "azure-search-documents",
}

APPROVED_COSMOS_CONTAINERS = {
    "COSMOS_CONTAINER_RUNBOOKS": "runbooks",
    "COSMOS_CONTAINER_PLAYBOOKS_A": "playbooks_prompt_a",
    "COSMOS_CONTAINER_PLAYBOOKS_B": "playbooks_prompt_b",
    "COSMOS_CONTAINER_OPERATIONAL_CONTEXT": "operational_context",
    "COSMOS_CONTAINER_RELATIONSHIP_LINKS": "relationship_links",
    "COSMOS_CONTAINER_SOURCE_ARTIFACTS": "source_artifacts",
    "COSMOS_CONTAINER_CANONICAL_IMAGES": "publish_canonical_images",
}

REQUIRED_DEMO_ENV = (
    "COSMOS_ENDPOINT",
    "COSMOS_KEY",
    "COSMOS_DATABASE",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_EMBEDDINGS_DEPLOYMENT",
    "AZURE_EMBEDDING_DIMENSIONS",
)


def _failures() -> list[str]:
    failures: list[str] = []
    requirements = _read_requirements()
    missing_packages = sorted(REQUIRED_RUNTIME_PACKAGES - requirements)
    if missing_packages:
        failures.append(
            "requirements.txt is missing runtime packages: "
            + ", ".join(missing_packages)
        )

    streamlit_entrypoint = REPO_ROOT / "ui" / "Home.py"
    if not streamlit_entrypoint.exists():
        failures.append("Streamlit entrypoint missing: ui/Home.py")
    else:
        try:
            compile(streamlit_entrypoint.read_text(encoding="utf-8"), str(streamlit_entrypoint), "exec")
        except SyntaxError as exc:
            failures.append(f"Streamlit entrypoint syntax error: {exc}")

    try:
        app_module = importlib.import_module("backend.app.main")
        if getattr(app_module, "app", None) is None:
            failures.append("backend.app.main imported but did not expose 'app'")
    except Exception as exc:
        failures.append(f"FastAPI app import failed: {exc}")

    app_env = os.getenv("APP_ENV", "").strip().lower()
    retrieval_backend = os.getenv("RETRIEVAL_BACKEND", "").strip().lower()
    if app_env == "demo":
        if retrieval_backend != "cosmos":
            failures.append("APP_ENV=demo requires RETRIEVAL_BACKEND=cosmos")
        missing_env = [name for name in REQUIRED_DEMO_ENV if not os.getenv(name)]
        if missing_env:
            failures.append("APP_ENV=demo missing env vars: " + ", ".join(missing_env))

    for name, expected in APPROVED_COSMOS_CONTAINERS.items():
        value = os.getenv(name, expected).strip()
        if value != expected:
            failures.append(f"{name} must resolve to {expected!r}, got {value!r}")

    return failures


def _read_requirements() -> set[str]:
    path = REPO_ROOT / "requirements.txt"
    if not path.exists():
        return set()
    packages: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if clean:
            packages.add(clean)
    return packages


def main() -> int:
    failures = _failures()
    if failures:
        print("Deployment preflight failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Deployment preflight passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
