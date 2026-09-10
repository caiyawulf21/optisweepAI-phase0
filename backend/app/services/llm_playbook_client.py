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
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :].strip()
    return text


def llm_available() -> bool:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_EMBEDDINGS_DEPLOYMENT")
    return bool(endpoint and api_key and deployment)


def _chat_completion(
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float | None = 0.2,
    response_format: dict[str, str] | None = None,
) -> str | None:
    """Call Azure OpenAI / Foundry chat; return assistant content or None."""
    if not llm_available():
        return None
    from openai import AzureOpenAI, OpenAI

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv(
        "AZURE_EMBEDDINGS_DEPLOYMENT"
    )
    kwargs: dict[str, Any] = {
        "model": str(deployment),
        "messages": messages,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    def _create(client: Any, *, use_max_completion_tokens: bool) -> Any:
        call_kwargs = dict(kwargs)
        if use_max_completion_tokens:
            call_kwargs["max_completion_tokens"] = max_tokens
        else:
            call_kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        try:
            return client.chat.completions.create(**call_kwargs)
        except Exception:
            if temperature is None:
                raise
            call_kwargs.pop("temperature", None)
            return client.chat.completions.create(**call_kwargs)

    if "services.ai.azure.com" in endpoint or "/api/projects/" in endpoint:
        base = endpoint
        if "/openai/v1" not in base:
            base = f"{base}/openai/v1"
        client = OpenAI(base_url=base, api_key=api_key)
        # Newer GPT-5 deployments reject max_tokens; prefer max_completion_tokens.
        response = _create(client, use_max_completion_tokens=True)
    else:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        try:
            response = _create(client, use_max_completion_tokens=True)
        except Exception:
            response = _create(client, use_max_completion_tokens=False)
    content = response.choices[0].message.content
    return str(content).strip() if content else None


def complete_text(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 400,
) -> str | None:
    try:
        return _chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
    except Exception:
        return None


def complete_json(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 700,
) -> str | None:
    """JSON-object chat completion for structured extractors."""
    try:
        return _chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
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


def _excerpt_budget(record_type: str | None) -> int:
    return 900 if str(record_type or "") == "operational_context" else 600


def llm_compose_retrieve_answer(
    query: str,
    hits: list[dict[str, Any]],
    *,
    prior_turns: list[dict[str, Any]] | None = None,
    intent: str | None = None,
    brain_excerpts: list[dict[str, Any]] | None = None,
) -> str | None:
    system_prompt = load_agent_prompt("synthesize", "compose_answer.md")
    if not system_prompt:
        system_prompt = (
            "Compose a short support-safe chatbot answer from the hits and any "
            "brain_excerpts. Cite titles and source_ids inline, and end with a Sources: list. "
            "Label Brain operational_unreviewed material as operational unreviewed. "
            "Do not re-ask clarifying questions when intent is already resolved."
        )
    slim_hits = []
    for hit in hits[:8]:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
        record_type = str(hit.get("record_type") or "")
        excerpt = str(hit.get("snippet") or hit.get("excerpt") or "")
        slim_hits.append(
            {
                "title": (
                    hit.get("title")
                    or metadata.get("title")
                    or hit.get("source_record_id")
                    or hit.get("record_id")
                ),
                "excerpt": excerpt[: _excerpt_budget(record_type)],
                "confidence": hit.get("combined_score") or hit.get("confidence") or 0.0,
                "source_id": hit.get("source_record_id") or hit.get("record_id"),
                "record_type": record_type or None,
            }
        )
    slim_brain = []
    for item in list(brain_excerpts or [])[:8]:
        if not isinstance(item, dict):
            continue
        excerpt = str(item.get("excerpt") or item.get("snippet") or item.get("text") or "")
        if not excerpt.strip():
            continue
        review_state = str(
            item.get("review_state") or item.get("validation_status") or "approved"
        ).strip()
        slim_brain.append(
            {
                "title": item.get("title") or item.get("source_id") or item.get("record_id"),
                "excerpt": excerpt[:800],
                "confidence": item.get("confidence") or item.get("combined_score") or 0.45,
                "source_id": item.get("source_id")
                or item.get("source_record_id")
                or item.get("record_id"),
                "record_type": item.get("record_type") or "brain",
                "origin": "brain",
                "review_state": review_state,
                "validation_status": item.get("validation_status") or review_state,
            }
        )
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
            "brain_excerpts": slim_brain,
            "instructions": (
                "Act as a helpful chatbot. Synthesize what the hits and brain_excerpts say "
                "about the user question — do not dump raw excerpts. "
                "Treat brain_excerpts as supplemental cited evidence from Brain retrieve, "
                "not as a relationship graph. "
                "prior_turns is already trimmed; do not request more history. "
                "If resolved_intent is software_stack, answer that directly and do not ask the "
                "software/maintenance/incident clarifying menu again. "
                "Prefer publish hits and approved Brain excerpts. "
                "If resolved_intent is howto or maintenance, prefer runbook procedure hits "
                "and point to concrete steps. "
                "If a brain excerpt has review_state/validation_status operational_unreviewed, "
                "you may use it but must label it as operational unreviewed and not as approved guidance. "
                "Cite Brain material distinctly when you use it."
            ),
        },
        indent=2,
    )
    return complete_text(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=750)


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
