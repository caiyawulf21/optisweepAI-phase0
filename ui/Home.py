import os

import requests
import streamlit as st

st.set_page_config(page_title="OptiSweep Playbook Runtime", layout="wide")
st.title("OptiSweep Playbook Runtime")

st.markdown(
    """
This app exposes two runtime surfaces over the same Cosmos corpus. Pick a page
from the sidebar depending on what you need.
"""
)

st.subheader("Guided Troubleshoot")
st.markdown(
    """
Use **Guided Troubleshoot** when you are working through a live incident.

- Turn 1: hybrid search over playbook embeddings, then pin a playbook or fall back to a runbook.
- Turn 2+: follow the pinned playbook node-by-node with linked runbook steps.
- Supports branch questions, reference images, and escalation summaries.
- Best for structured, step-by-step support workflows.
"""
)

st.subheader("Search / Chat")
st.markdown(
    """
Use **Search / Chat** when you want corpus Q&A without executing a playbook.

- Uses the **live Azure Cosmos** publish, confirmed via `GET /corpus/status`.
- Every turn searches **all published embeddings** by default (runbooks + playbooks + operational context when present).
- Composes a short answer with cited sources and reference images from top runbook hits.
- Best for looking up procedures, context, or evidence while triaging.
"""
)

st.subheader("Backend")
backend = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
try:
    health = requests.get(f"{backend}/health", timeout=5)
    if health.ok:
        st.success(f"Connected to {backend}")
    else:
        st.error(f"Backend returned an error at {backend}")
except requests.RequestException as exc:
    st.error(f"Backend unreachable at {backend}: {exc}")

st.caption(
    "Start the API with `uvicorn backend.app.main:app --reload`. "
    "Set `API_BASE_URL` if the backend is not on port 8000."
)
