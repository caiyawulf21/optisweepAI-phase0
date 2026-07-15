from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts" / "agents"


def load_agent_prompt(agent: str, filename: str) -> str:
    path = _PROMPTS_ROOT / agent / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def llm_available() -> bool:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_EMBEDDINGS_DEPLOYMENT")
    return bool(endpoint and api_key and deployment)


def complete_text(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 400,
) -> str | None:
    if not llm_available():
        return None
    try:
        from openai import AzureOpenAI, OpenAI

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv(
            "AZURE_EMBEDDINGS_DEPLOYMENT"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # Foundry / AI Services project endpoints speak OpenAI-compatible /openai/v1.
        if "services.ai.azure.com" in endpoint or "/api/projects/" in endpoint:
            base = endpoint
            if "/openai/v1" not in base:
                base = f"{base}/openai/v1"
            client = OpenAI(base_url=base, api_key=api_key)
            # Newer GPT-5 deployments reject max_tokens; prefer max_completion_tokens.
            try:
                response = client.chat.completions.create(
                    model=str(deployment),
                    messages=messages,
                    max_completion_tokens=max_tokens,
                    temperature=0.2,
                )
            except Exception:
                response = client.chat.completions.create(
                    model=str(deployment),
                    messages=messages,
                    max_completion_tokens=max_tokens,
                )
        else:
            client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
            try:
                response = client.chat.completions.create(
                    model=str(deployment),
                    messages=messages,
                    max_completion_tokens=max_tokens,
                    temperature=0.2,
                )
            except Exception:
                response = client.chat.completions.create(
                    model=str(deployment),
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.2,
                )
        content = response.choices[0].message.content
        return str(content).strip() if content else None
    except Exception:
        return None


def llm_match_branch(user_message: str, allowed_answers: list[str]) -> str | None:
    classified = llm_classify_branch_reply(user_message, allowed_answers)
    if not classified or classified.get("action") != "match":
        return None
    label = str(classified.get("label") or "").strip()
    for allowed in allowed_answers:
        if label.lower() == str(allowed).lower():
            return str(allowed)
    return None


def llm_classify_branch_reply(
    user_message: str,
    allowed_answers: list[str],
    *,
    node_title: str | None = None,
    node_intent: str | None = None,
) -> dict[str, str] | None:
    system_prompt = load_agent_prompt("branch", "match_branch.md")
    if not system_prompt:
        system_prompt = (
            "Classify the operator reply as match, retriage, or probe. "
            "Return JSON with action, optional label, optional probe_question."
        )
    user_prompt = json.dumps(
        {
            "user_message": user_message,
            "allowed_answers": allowed_answers,
            "node_title": node_title or "",
            "node_intent": node_intent or "",
        },
        indent=2,
    )
    result = complete_text(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=120)
    if not result:
        return None
    text = result.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    payload: dict[str, Any] | None = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            payload = parsed
    except json.JSONDecodeError:
        normalized = text.lower().strip('"').strip("'")
        for label in allowed_answers:
            if normalized == str(label).lower():
                return {"action": "match", "label": str(label), "probe_question": ""}
        return None
    if not payload:
        return None
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"match", "retriage", "probe"}:
        return None
    label = str(payload.get("label") or "").strip()
    probe = str(payload.get("probe_question") or "").strip()
    if action == "match":
        matched = None
        for allowed in allowed_answers:
            if label.lower() == str(allowed).lower():
                matched = str(allowed)
                break
        if matched is None:
            return None
        return {"action": "match", "label": matched, "probe_question": ""}
    if action == "retriage":
        return {"action": "retriage", "label": "", "probe_question": ""}
    return {
        "action": "probe",
        "label": "",
        "probe_question": probe
        or "Please choose one of the branch options, or describe new site symptoms.",
    }


def llm_compose_retrieve_answer(
    query: str,
    hits: list[dict[str, Any]],
    *,
    prior_turns: list[dict[str, Any]] | None = None,
    intent: str | None = None,
) -> str | None:
    system_prompt = load_agent_prompt("synthesize", "compose_answer.md")
    if not system_prompt:
        system_prompt = (
            "Compose a short support-safe chatbot answer from the hits. "
            "Cite titles and source_ids inline, and end with a Sources: list. "
            "Do not re-ask clarifying questions when intent is already resolved."
        )
    slim_hits = []
    for hit in hits[:5]:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
        excerpt = str(hit.get("snippet") or hit.get("excerpt") or "")
        slim_hits.append(
            {
                "title": (
                    hit.get("title")
                    or metadata.get("title")
                    or hit.get("source_record_id")
                    or hit.get("record_id")
                ),
                "excerpt": excerpt[:280],
                "confidence": hit.get("combined_score") or hit.get("confidence") or 0.0,
                "source_id": hit.get("source_record_id") or hit.get("record_id"),
                "record_type": hit.get("record_type"),
            }
        )
    # Bounded LangChain-trimmed turns only — never dump full prior answers.
    history = []
    for turn in list(prior_turns or [])[-4:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        if role and content:
            history.append({"role": role, "content": content[:220]})
    user_prompt = json.dumps(
        {
            "query": query,
            "resolved_intent": intent,
            "prior_turns": history,
            "hits": slim_hits,
            "instructions": (
                "Act as a helpful chatbot. Summarize what the hits say about the user question. "
                "prior_turns is already trimmed; do not request more history. "
                "If resolved_intent is software_stack, answer that directly and do not ask the "
                "software/maintenance/incident clarifying menu again."
            ),
        },
        indent=2,
    )
    return complete_text(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=650)


def llm_compose_orchestrator_message(briefing: dict[str, Any]) -> dict[str, str] | None:
    """Compose operator-facing orchestration text from a compact tool briefing."""
    system_prompt = load_agent_prompt("orchestrator", "orchestrate_turn.md")
    if not system_prompt:
        return None
    user_prompt = json.dumps(briefing, indent=2, default=str)
    raw = complete_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=450,
    )
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {
            "user_message": raw.strip(),
            "confidence_reason": str(briefing.get("confidence_reason_seed") or ""),
        }
    if not isinstance(payload, dict):
        return None
    user_message = str(payload.get("user_message") or "").strip()
    confidence_reason = str(payload.get("confidence_reason") or "").strip()
    if not user_message and not confidence_reason:
        return None
    return {
        "user_message": user_message
        or str(briefing.get("fallback_user_message") or "").strip(),
        "confidence_reason": confidence_reason
        or str(briefing.get("confidence_reason_seed") or "").strip(),
    }
