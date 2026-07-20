from __future__ import annotations

import re
from typing import Any

from backend.app.agents.trace import append_agent_trace
from backend.app.corpus.bootstrap import get_corpus_client, get_corpus_index
from backend.app.corpus.settings import get_corpus_settings
from backend.app.graph.playbook_state import PlaybookSessionSlice
from backend.app.retrieval.hybrid_retriever import HybridRetriever, RetrievalConfig
from backend.app.services.canonical_image_lookup import build_canonical_image_lookup
from backend.app.services.embedding_client import build_embedding_client
from backend.app.services.session_service import WorkflowSession, build_session_service

_ABSENCE_AFFIRMATIVE_KEYS = frozenset({"no_rms_alarm"})
_EXTRACTION_TURN_CAP = 8

_GENERIC_OUTCOME_SUMMARY_RE = re.compile(
    r"^(?:select\s+\w+\s+for this check\.?|"
    r"checks for\s+.+?(?:do not indicate|indicate)\s+the fault condition)",
    re.IGNORECASE | re.DOTALL,
)
_EXPECTED_EVIDENCE_SEGMENT_RE = re.compile(
    r"(?P<label>Unhealthy|Healthy|Inconclusive)"
    r"(?:\s+or\s+(?:narrower|healthy|unhealthy|inconclusive))*"
    r"\s+(?:evidence|state|result|condition|path)?\s*"
    r"(?:includes?|would\s+(?:show|indicate)|(?:is|means|would be)|:)?\s*"
    r"(?P<body>.+?)(?=(?:Unhealthy|Healthy|Inconclusive)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_DEFAULT_INCONCLUSIVE_EVIDENCE = (
    "Evidence is missing, conflicting, or incomplete — you cannot confidently "
    "decide healthy vs unhealthy for this check yet."
)


def _parse_expected_outcome_evidence(expected: Any) -> dict[str, str]:
    text = str(expected or "").strip()
    if not text:
        return {}
    parsed: dict[str, str] = {}
    for match in _EXPECTED_EVIDENCE_SEGMENT_RE.finditer(text):
        label = str(match.group("label") or "").strip().lower()
        body = re.sub(r"\s+", " ", str(match.group("body") or "").strip(" .;,"))
        if label in {"healthy", "unhealthy", "inconclusive"} and body:
            parsed.setdefault(label, body)
    return parsed


def _is_generic_outcome_summary(text: Any) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if _GENERIC_OUTCOME_SUMMARY_RE.match(value):
        return True
    return len(_parse_expected_outcome_evidence(value)) >= 2


def _node_title_index(playbook: dict[str, Any] | None) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in list((playbook or {}).get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        index[node_id] = str(item.get("title") or node_id).strip() or node_id
    return index


def _branch_destination_map(
    node: dict[str, Any],
    playbook: dict[str, Any] | None = None,
) -> dict[str, str]:
    destinations: dict[str, str] = {}

    def add(label: Any, next_node_id: Any) -> None:
        key = str(label or "").strip().lower()
        destination = str(next_node_id or "").strip()
        if key and destination and key not in destinations:
            destinations[key] = destination

    for branch in node.get("branches") or []:
        if not isinstance(branch, dict):
            continue
        add(
            branch.get("outcome") or branch.get("condition_label"),
            branch.get("next_node_id")
            or branch.get("to_node_id")
            or branch.get("target_node_id"),
        )
    node_id = str(node.get("node_id") or "").strip()
    if node_id:
        for branch in list((playbook or {}).get("branches") or []):
            if not isinstance(branch, dict):
                continue
            source = str(
                branch.get("from_node_id") or branch.get("source_node_id") or ""
            ).strip()
            if source and source != node_id:
                continue
            add(
                branch.get("outcome") or branch.get("condition_label"),
                branch.get("next_node_id")
                or branch.get("to_node_id")
                or branch.get("target_node_id"),
            )
    for item in node.get("decision_outcomes") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") == "runbook_step":
            continue
        add(item.get("outcome_label"), item.get("next_node_id"))
    return destinations


def _branch_options(
    node: dict[str, Any],
    playbook: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    titles = _node_title_index(playbook)
    destinations = _branch_destination_map(node, playbook)

    def add(label: Any, next_node_id: Any = None) -> None:
        text = str(label or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        destination_id = (
            str(next_node_id or "").strip()
            or destinations.get(key)
            or None
        )
        destination_title = titles.get(destination_id) if destination_id else None
        options.append(
            {
                "label": text,
                "next_node_id": destination_id,
                "next_node_title": destination_title or destination_id,
            }
        )

    playbook_outcomes = [
        item
        for item in (node.get("decision_outcomes") or [])
        if isinstance(item, dict) and str(item.get("source") or "") != "runbook_step"
    ]
    if playbook_outcomes:
        for item in playbook_outcomes:
            add(item.get("outcome_label"), item.get("next_node_id"))
        return options

    for branch in node.get("branches") or []:
        if isinstance(branch, dict):
            add(
                branch.get("outcome") or branch.get("condition_label"),
                branch.get("next_node_id")
                or branch.get("to_node_id")
                or branch.get("target_node_id"),
            )
    if options:
        return options

    for item in node.get("decision_outcomes") or []:
        if isinstance(item, dict):
            add(
                item.get("outcome_label") or item.get("descriptor"),
                item.get("next_node_id"),
            )
    return options


def _resolve_next_node_id(
    node: dict[str, Any],
    chosen: str | None,
    *,
    branch_options: list[dict[str, Any]] | None = None,
    playbook: dict[str, Any] | None = None,
) -> str | None:
    label = str(chosen or "").strip().lower()
    if not label:
        return None
    for option in branch_options or []:
        if str(option.get("label") or "").strip().lower() != label:
            continue
        destination = str(option.get("next_node_id") or "").strip()
        if destination:
            return destination
    return _branch_destination_map(node, playbook).get(label)


def _unique_branch_answers(
    node: dict[str, Any],
    playbook: dict[str, Any] | None = None,
) -> list[str]:
    return [str(item.get("label")) for item in _branch_options(node, playbook)]


_BRANCH_HEALTHY_SYNONYMS = {
    "ok",
    "okay",
    "good",
    "fine",
    "normal",
    "all good",
    "looks good",
    "looks fine",
    "no issues",
    "no faults",
    "healthy",
}
_BRANCH_UNHEALTHY_SYNONYMS = {
    "bad",
    "fault",
    "faulty",
    "failing",
    "failed",
    "broken",
    "unhealthy",
    "not healthy",
    "not ok",
    "not okay",
    "problem",
    "abnormal",
}
_BRANCH_INCONCLUSIVE_SYNONYMS = {
    "unknown",
    "not sure",
    "unsure",
    "maybe",
    "inconclusive",
    "cannot tell",
    "can't tell",
    "unclear",
}
_SYMPTOM_HINT_TOKENS = {
    "agv",
    "agvs",
    "amr",
    "amrs",
    "hospital",
    "rms",
    "hmi",
    "zone",
    "pair",
    "tote",
    "totes",
    "stopped",
    "stoppage",
    "fault",
    "faults",
    "sync",
    "desync",
    "gateway",
    "optisweep",
    "ignition",
    "blank",
    "moving",
    "nothing",
}


def _normalize_branch_message(message: str) -> str:
    return " ".join(str(message or "").strip().lower().split())


def _allowed_label_lookup(allowed: list[str]) -> dict[str, str]:
    return {str(item).strip().lower(): str(item) for item in allowed if str(item).strip()}


def _looks_like_new_symptoms(message: str) -> bool:
    text = _normalize_branch_message(message)
    if not text:
        return False
    tokens = set(text.replace("/", " ").replace("-", " ").split())
    if len(tokens) >= 4 and tokens & _SYMPTOM_HINT_TOKENS:
        return True
    if len(tokens) >= 6:
        return True
    symptom_phrases = (
        "nothing is moving",
        "can't get a pair",
        "cannot get a pair",
        "going to the hospital",
        "out of sync",
        "small sort",
        "system faults",
    )
    return any(phrase in text for phrase in symptom_phrases)


def _classify_branch_reply_deterministic(
    message: str,
    allowed: list[str],
) -> dict[str, str]:
    text = _normalize_branch_message(message)
    lookup = _allowed_label_lookup(allowed)
    probe = {
        "action": "probe",
        "label": "",
        "probe_question": (
            "I could not map that to a branch option. Choose healthy / unhealthy / "
            "inconclusive, or describe new site symptoms to re-run retrieval."
        ),
    }
    if not text:
        return {
            "action": "probe",
            "label": "",
            "probe_question": (
                "Please choose one of the branch options, or describe new site symptoms."
            ),
        }
    if text in lookup:
        return {"action": "match", "label": lookup[text], "probe_question": ""}
    for key, label in lookup.items():
        if key in text and len(text) <= len(key) + 12:
            return {"action": "match", "label": label, "probe_question": ""}

    synonym_map: dict[str, str] = {}
    if "healthy" in lookup:
        for item in _BRANCH_HEALTHY_SYNONYMS:
            synonym_map[item] = lookup["healthy"]
    if "unhealthy" in lookup:
        for item in _BRANCH_UNHEALTHY_SYNONYMS:
            synonym_map[item] = lookup["unhealthy"]
    if "inconclusive" in lookup:
        for item in _BRANCH_INCONCLUSIVE_SYNONYMS:
            synonym_map[item] = lookup["inconclusive"]
    if text in synonym_map:
        return {"action": "match", "label": synonym_map[text], "probe_question": ""}
    if (
        "healthy" in lookup
        and "health" in text
        and "unhealth" not in text
        and len(text.split()) <= 4
    ):
        return {"action": "match", "label": lookup["healthy"], "probe_question": ""}

    if _looks_like_new_symptoms(text):
        return {"action": "retriage", "label": "", "probe_question": ""}
    return probe


def _append_path_evidence(
    slice_: PlaybookSessionSlice,
    *,
    node_id: str | None,
    title: str | None,
    outcome: str | None,
    evidence: str | None = None,
) -> None:
    node = str(node_id or "").strip()
    if not node:
        return
    entry = {
        "node_id": node,
        "title": str(title or "")[:80],
        "outcome": str(outcome or "")[:40],
        "evidence": str(evidence or "")[:160],
    }
    rows = list(slice_.path_evidence or [])
    rows.append(entry)
    slice_.path_evidence = rows[-12:]


def _lean_working_memory(
    state: dict[str, Any],
    slice_: PlaybookSessionSlice | None = None,
) -> dict[str, Any]:
    slice_ = slice_ or state.get("_playbook_slice")
    signals = {}
    path_rows: list[dict[str, Any]] = []
    if isinstance(slice_, PlaybookSessionSlice):
        signals = {
            str(key): True
            for key, value in dict(slice_.observed_signals or {}).items()
            if value
        }
        path_rows = list(slice_.path_evidence or [])
    else:
        signals = {
            str(key): True
            for key, value in dict(state.get("extracted_observed_signals") or {}).items()
            if value
        }
        path_rows = list(state.get("path_evidence") or [])
    prior = state.get("_retriage_prior") if isinstance(state.get("_retriage_prior"), dict) else {}
    return {
        "signals": sorted(signals)[:12],
        "path": [
            {
                "n": str(item.get("node_id") or ""),
                "o": str(item.get("outcome") or ""),
                "t": str(item.get("title") or "")[:40],
            }
            for item in path_rows[-6:]
            if isinstance(item, dict)
        ],
        "prior_playbook": str(prior.get("playbook_id") or "") or None,
        "prior_node": str(prior.get("node_id") or "") or None,
    }


def _is_exact_allowed_answer(message: str, allowed: list[str]) -> bool:
    text = _normalize_branch_message(message)
    if not text:
        return False
    return text in _allowed_label_lookup(allowed)


def _clear_active_playbook(
    state: dict[str, Any],
    slice_: PlaybookSessionSlice,
    *,
    preserve_path_memory: bool = True,
) -> None:
    prior_playbook = slice_.active_playbook_id
    prior_node = slice_.current_node_id
    slice_.active_playbook_id = None
    slice_.active_case_id = None
    slice_.current_node_id = None
    slice_.current_procedure_id = None
    slice_.current_step_index = 0
    slice_.pin_source = None
    slice_.branch_state = {}
    slice_.completed_node_ids = []
    if not preserve_path_memory:
        slice_.path_evidence = []
    state["active_playbook_id"] = None
    state["active_case_id"] = None
    state["current_node_id"] = None
    state["playbook_payload"] = {}
    state["runbook_payload"] = {}
    state["runbook_step"] = {}
    state["current_node_payload"] = {}
    state["guided_question"] = None
    state["branch_state"] = {}
    state["completed_node_ids"] = []
    state["canonical_images"] = []
    state["branch_qualification_metrics"] = {}
    if preserve_path_memory:
        state["_retriage_prior"] = {
            "playbook_id": prior_playbook,
            "node_id": prior_node,
        }
        state["path_evidence"] = list(slice_.path_evidence or [])


def _branch_qualification_metrics(
    node: dict[str, Any],
    runbook: dict[str, Any] | None = None,
    playbook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del runbook
    metrics: dict[str, dict[str, Any]] = {
        "healthy": {"summary": None, "checks": [], "next_node_id": None, "next_node_title": None},
        "unhealthy": {"summary": None, "checks": [], "next_node_id": None, "next_node_title": None},
        "inconclusive": {
            "summary": None,
            "checks": [],
            "next_node_id": None,
            "next_node_title": None,
        },
    }
    titles = _node_title_index(playbook)
    for item in node.get("decision_outcomes") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") == "runbook_step":
            continue
        label = str(item.get("outcome_label") or "").strip().lower()
        if label not in metrics:
            continue
        text = str(item.get("descriptor") or item.get("observable_signal") or "").strip()
        if text and not metrics[label]["summary"]:
            metrics[label]["summary"] = text
        next_node_id = str(item.get("next_node_id") or "").strip() or None
        if next_node_id and not metrics[label]["next_node_id"]:
            metrics[label]["next_node_id"] = next_node_id
            metrics[label]["next_node_title"] = titles.get(next_node_id) or next_node_id
    for option in _branch_options(node, playbook):
        label = str(option.get("label") or "").strip().lower()
        if label not in metrics:
            continue
        if option.get("next_node_id") and not metrics[label]["next_node_id"]:
            metrics[label]["next_node_id"] = option.get("next_node_id")
            metrics[label]["next_node_title"] = option.get("next_node_title")
    expected = str(node.get("expected_or_observed_result") or "").strip()
    parsed = _parse_expected_outcome_evidence(expected)
    for label in ("healthy", "unhealthy", "inconclusive"):
        current = metrics[label]["summary"]
        if current and not _is_generic_outcome_summary(current):
            continue
        if parsed.get(label):
            metrics[label]["summary"] = parsed[label]
        elif label == "inconclusive":
            metrics[label]["summary"] = _DEFAULT_INCONCLUSIVE_EVIDENCE
        else:
            metrics[label]["summary"] = f"Select {label} for this check."
    return metrics


def _enriched_retrieval_query(state: dict[str, Any]) -> str:
    query = str(state.get("user_message") or "").strip()
    observed = state.get("extracted_observed_signals") or {}
    extras = [
        str(key).replace("_", " ")
        for key, value in observed.items()
        if value
    ][:8]
    slice_: PlaybookSessionSlice | None = state.get("_playbook_slice")
    memory = dict((slice_.extraction_memory if slice_ is not None else None) or {})
    prior_turns = [
        str(item.get("content") or "").strip()
        for item in list(memory.get("operator_symptom_turns") or [])
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    prior_text = " ".join(prior_turns[-4:])
    path_bits: list[str] = []
    path_rows = list((slice_.path_evidence if slice_ is not None else None) or state.get("path_evidence") or [])
    for item in path_rows[-4:]:
        if not isinstance(item, dict):
            continue
        outcome = str(item.get("outcome") or "").strip()
        title = str(item.get("title") or item.get("node_id") or "").strip()
        if outcome and title:
            path_bits.append(f"{title} {outcome}")
        elif outcome:
            path_bits.append(outcome)
    expansions = _retrieve_query_expansions(query, state) if state.get("surface") == "retrieve" else []
    prior_bits: list[str] = []
    if state.get("surface") == "retrieve":
        hints = list(state.get("retrieve_memory_hints") or [])
        for hint in hints[-3:]:
            text = str(hint or "").strip()
            if text and text.lower() != query.lower():
                prior_bits.append(text)
        if not prior_bits:
            for turn in list(state.get("conversation_history") or [])[-4:]:
                if not isinstance(turn, dict) or turn.get("role") != "user":
                    continue
                content = str(turn.get("content") or "").strip()
                if content and content.lower() != query.lower():
                    prior_bits.append(content)
    parts = [
        part
        for part in [
            query,
            prior_text,
            " ".join(prior_bits),
            " ".join(extras),
            " ".join(path_bits),
            " ".join(expansions),
        ]
        if part
    ]
    return " ".join(parts).strip()


def _retrieve_query_expansions(query: str, state: dict[str, Any] | None = None) -> list[str]:
    """Light lexical expansions for ambiguous overview / service questions."""
    text = str(query or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    intent = str((state or {}).get("retrieve_intent") or "")
    expansions: list[str] = []
    if intent == "software_stack" or (
        ({"service", "software", "stack", "roles", "components"} & tokens)
        and ("optisweep" in tokens or "opti" in tokens or intent == "software_stack")
    ):
        expansions.extend(
            [
                "OptiSweep software components",
                "core OptiSweep environment",
                "communication path WCS RMS Ignition UPS Chat",
                "software integration roles AVEVA",
            ]
        )
    elif "optisweep" in tokens or "opti" in tokens:
        if {"about", "overview", "what", "explain", "tell", "describe", "service"} & tokens:
            expansions.extend(
                [
                    "OptiSweep software components",
                    "core OptiSweep environment",
                    "communication path WCS RMS Ignition",
                ]
            )
    return expansions


def _collect_runbook_artifact_ids(
    *,
    runbook: dict[str, Any],
    step: dict[str, Any] | None = None,
    node: dict[str, Any] | None = None,
) -> list[str]:
    artifacts: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        artifacts.append(text)

    for ref in list(runbook.get("visual_references") or []):
        if isinstance(ref, dict):
            add(ref.get("artifact_id") or ref.get("image_id"))
        else:
            add(ref)
    for image in list(runbook.get("canonical_images") or []):
        if isinstance(image, dict):
            add(image.get("image_id") or image.get("artifact_id"))
    for item in list((step or {}).get("screens_or_images") or []):
        if isinstance(item, dict):
            add(item.get("artifact_id") or item.get("image_id"))
    for item in list((step or {}).get("canonical_images") or []):
        if isinstance(item, dict):
            add(item.get("image_id") or item.get("artifact_id"))
    if isinstance(node, dict):
        for item in list(node.get("inherited_image_refs") or []):
            add(item)
        for item in list(node.get("related_artifact_ids") or []):
            add(item)
    return artifacts


def _step_screen_refs(step: dict[str, Any] | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if not isinstance(step, dict):
        return refs
    for item in list(step.get("screens_or_images") or []):
        if isinstance(item, dict):
            artifact_id = str(item.get("artifact_id") or item.get("image_id") or "").strip()
            if not artifact_id:
                continue
            refs.append(
                {
                    "artifact_id": artifact_id,
                    "what_to_look_at": item.get("what_to_look_at") or item.get("description"),
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                refs.append({"artifact_id": text, "what_to_look_at": None})
    return refs


def _resolve_step_images(
    lookup: Any,
    *,
    screen_refs: list[dict[str, Any]],
    embedded_images: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    artifact_ids = [str(item.get("artifact_id")) for item in screen_refs if item.get("artifact_id")]
    try:
        images = lookup.resolve_for_artifacts(
            artifact_ids=artifact_ids,
            embedded_images=list(embedded_images or []),
        )
    except Exception:
        images = []
    if images:
        return images
    recovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        try:
            record = lookup.get_by_image_id(artifact_id)
        except Exception:
            record = None
        if not isinstance(record, dict):
            continue
        key = str(record.get("image_id") or artifact_id)
        if key in seen:
            continue
        seen.add(key)
        recovered.append(record)
    return recovered


def _attach_runbook_images(state: dict[str, Any]) -> None:
    settings = get_corpus_settings()
    runbook = state.get("runbook_payload") or {}
    if not isinstance(runbook, dict):
        state["canonical_images"] = []
        return
    if not settings.cosmos_configured:
        state["canonical_images"] = []
        return

    lookup = build_canonical_image_lookup()
    steps = list(runbook.get("steps") or [])
    fallback_refs = _step_screen_refs(
        {"screens_or_images": list(runbook.get("screens_or_images") or [])}
    )
    if not fallback_refs:
        fallback_refs = [
            {
                "artifact_id": str(ref.get("artifact_id") or "").strip(),
                "what_to_look_at": ref.get("description") or ref.get("what_to_look_at"),
            }
            for ref in list(runbook.get("visual_references") or [])
            if isinstance(ref, dict) and str(ref.get("artifact_id") or "").strip()
        ]
    enriched_steps: list[dict[str, Any]] = []
    all_step_images: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        screen_refs = _step_screen_refs(step)
        if not screen_refs and index == 0 and fallback_refs:
            screen_refs = list(fallback_refs)
        embedded = list(step.get("canonical_images") or step.get("images") or [])
        images = _resolve_step_images(
            lookup,
            screen_refs=screen_refs,
            embedded_images=embedded,
        )
        for image in images:
            caption = next(
                (
                    str(ref.get("what_to_look_at") or "").strip()
                    for ref in screen_refs
                    if str(ref.get("artifact_id") or "")
                    in {
                        str(image.get("image_id") or ""),
                        *(str(item) for item in list(image.get("source_artifact_ids") or [])),
                    }
                    and str(ref.get("what_to_look_at") or "").strip()
                ),
                "",
            )
            if caption and not image.get("title"):
                image["title"] = caption
            elif caption:
                image["caption"] = caption
        step_out = dict(step)
        step_out["screens_or_images"] = screen_refs
        step_out["images"] = images
        enriched_steps.append(step_out)
        for image in images:
            key = str(image.get("image_id") or "")
            if key and key not in seen_ids:
                seen_ids.add(key)
                all_step_images.append(image)

    if enriched_steps:
        runbook = dict(runbook)
        runbook["steps"] = enriched_steps
        state["runbook_payload"] = runbook
        current = state.get("runbook_step") if isinstance(state.get("runbook_step"), dict) else {}
        if current:
            match = next(
                (
                    item
                    for item in enriched_steps
                    if str(item.get("step_number")) == str(current.get("step_number"))
                ),
                enriched_steps[0],
            )
            state["runbook_step"] = match

    state["canonical_images"] = []
    append_agent_trace(
        state,
        "image_agent",
        "resolve_step_screens",
        procedure_id=runbook.get("procedure_id"),
        step_count=len(enriched_steps),
        image_count=len(all_step_images),
        unresolved_screen_refs=sum(
            1
            for step in enriched_steps
            for ref in list(step.get("screens_or_images") or [])
            if not any(
                str(ref.get("artifact_id") or "")
                in {
                    str(image.get("image_id") or ""),
                    *(str(item) for item in list(image.get("source_artifact_ids") or [])),
                }
                for image in list(step.get("images") or [])
            )
        ),
    )


def extract_symptoms(state: dict[str, Any]) -> dict[str, Any]:
    from backend.app.config import get_app_settings
    from backend.app.services.keyword_signal_extractor import get_default_extractor

    extractor = get_default_extractor()
    user_message = state.get("user_message") or ""
    result = extractor.extract(user_message)
    turn_observed = {
        key: bool(value)
        for key, value in dict(result.observed_signals or {}).items()
        if value
    }
    components = set(result.components or [])
    canonical_signals = {
        key: bool(value)
        for key, value in dict(result.canonical_signals or {}).items()
    }
    metadata: dict[str, Any] = {
        "extractor": "keyword",
        "negated_signals": sorted(result.negated_signals or []),
        "matched_phrases": dict(result.matched_phrases or {}),
        "components": sorted(components),
    }

    slice_: PlaybookSessionSlice | None = state.get("_playbook_slice")
    memory = dict((slice_.extraction_memory if slice_ is not None else None) or {})
    already_observed = {}
    if slice_ is not None:
        already_observed = {
            key: bool(value)
            for key, value in dict(slice_.observed_signals or {}).items()
            if value
        }
    prior_turns = [
        item
        for item in list(memory.get("operator_symptom_turns") or [])
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    last_rationale = str(memory.get("last_rationale") or "").strip() or None

    llm_payload = _maybe_llm_symptom_overlay(
        user_message=user_message,
        keyword_result=result,
        already_observed_signals=already_observed,
        prior_operator_turns=prior_turns,
        last_extraction_rationale=last_rationale,
        settings=get_app_settings(),
    )
    if llm_payload is not None:
        for key, value in dict(llm_payload.get("signals") or {}).items():
            key_s = str(key)
            if key_s in _ABSENCE_AFFIRMATIVE_KEYS:
                if value:
                    turn_observed[key_s] = True
                continue
            if value:
                turn_observed[key_s] = True
            elif key_s in turn_observed and value is False:
                turn_observed.pop(key_s, None)
        for key, value in dict(llm_payload.get("canonical_signals") or {}).items():
            canonical_signals[str(key)] = bool(value)
        if turn_observed.get("no_rms_alarm"):
            canonical_signals.setdefault("rms_screen_no_faults_visible", True)
        for component in llm_payload.get("components") or ():
            components.add(str(component))
        metadata["extractor"] = "keyword+llm"
        metadata["llm"] = {
            "rationale": llm_payload.get("rationale"),
            "confidences": llm_payload.get("confidences", {}),
            "fresh_issue": llm_payload.get("fresh_issue", False),
            "extracted_canonical_signals": llm_payload.get("canonical_signals", {}),
            "model": llm_payload.get("model"),
            "dropped_unknown_keys": llm_payload.get("dropped_unknown_keys") or [],
        }
        if llm_payload.get("fresh_issue"):
            metadata["fresh_issue"] = True
        append_agent_trace(
            state,
            "symptom_agent",
            "llm_overlay",
            model=llm_payload.get("model"),
            added_signals=sorted(
                str(key)
                for key, value in dict(llm_payload.get("signals") or {}).items()
                if value or str(key) in _ABSENCE_AFFIRMATIVE_KEYS
            ),
        )

    fresh_issue = bool(metadata.get("fresh_issue"))
    if slice_ is not None and fresh_issue:
        already_observed = {}
        slice_.observed_signals = {}
        memory = {}
        _clear_active_playbook(state, slice_, preserve_path_memory=False)

    if slice_ is not None:
        merged = dict(already_observed)
        merged.update(turn_observed)
        slice_.observed_signals = merged
        observed = merged
    else:
        observed = dict(turn_observed)

    if slice_ is not None:
        turns = list(prior_turns)
        content = str(user_message or "").strip()
        if content and (
            not turns or str(turns[-1].get("content") or "").strip().lower() != content.lower()
        ):
            turns.append({"role": "user", "content": content})
        memory = {
            "components": sorted(components),
            "canonical_signals": dict(canonical_signals),
            "last_rationale": (
                str((metadata.get("llm") or {}).get("rationale") or last_rationale or "")
                or None
            ),
            "operator_symptom_turns": turns[-_EXTRACTION_TURN_CAP:],
            "last_confidences": dict(
                (metadata.get("llm") or {}).get("confidences")
                or memory.get("last_confidences")
                or {}
            ),
        }
        slice_.extraction_memory = memory

    state["extracted_signals"] = dict(observed)
    state["extracted_observed_signals"] = dict(observed)
    state["extracted_canonical_signals"] = canonical_signals
    state["extracted_components"] = sorted(components)
    state["extracted_signal_metadata"] = metadata
    state["issue_category"] = None
    affirmative = dict(observed)
    state["needs_symptom_clarification"] = not bool(affirmative)
    append_agent_trace(
        state,
        "symptom_agent",
        "extract",
        observed_count=len(affirmative),
        observed_signals=sorted(affirmative.keys()),
        extractor=metadata.get("extractor"),
        memory_turns=len((memory or {}).get("operator_symptom_turns") or []),
    )
    if state["needs_symptom_clarification"]:
        state["response_type"] = "answer"
        state["final_response"] = (
            "I need observable symptoms before matching a playbook. "
            "Describe what you see (for example: AGVs stopped, nothing moving, "
            "stopped at bag-out after sorting, hospital tote removal blocked, "
            "RMS/HMI blank or abnormal, alarms)."
        )
        state["retrieval_hits"] = []
        state["retrieval_confidence"] = 0.0
        append_agent_trace(state, "orchestrator_agent", "request_symptoms")
    return state


def _maybe_llm_symptom_overlay(
    *,
    user_message: str,
    keyword_result: Any,
    already_observed_signals: dict[str, bool],
    settings: Any,
    prior_operator_turns: list[dict[str, Any]] | None = None,
    last_extraction_rationale: str | None = None,
) -> dict[str, Any] | None:
    if not getattr(settings, "enable_llm_symptom_extraction", False):
        return None
    try:
        from backend.app.tools.llm_signal_extractor import LLMSignalExtractor

        return LLMSignalExtractor().extract(
            user_message=user_message,
            keyword_result=keyword_result,
            already_observed_signals=already_observed_signals,
            prior_operator_turns=prior_operator_turns,
            last_extraction_rationale=last_extraction_rationale,
        )
    except Exception:
        return None


def _entry_symptoms_for_hit(hit: dict[str, Any]) -> list[str]:
    playbook_id = str(hit.get("source_record_id") or "")
    card = get_corpus_index().symptom_cards.get(playbook_id) or {}
    symptoms = list(card.get("observed_entry_symptoms") or [])
    if symptoms:
        return [str(item) for item in symptoms]
    metadata = hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
    return [str(item) for item in (metadata.get("observed_entry_symptoms") or [])]


def _candidate_from_card(
    playbook_id: str,
    card: dict[str, Any],
    *,
    score: float,
) -> dict[str, Any]:
    symptoms = [str(item) for item in (card.get("observed_entry_symptoms") or []) if str(item).strip()]
    examples = [
        str(item)
        for item in (card.get("support_user_language_examples") or [])
        if str(item).strip()
    ]
    case_id = card.get("case_id")
    incidence_id = str(case_id or "").strip() or None
    title = str(card.get("title") or playbook_id)
    summary = str(card.get("user_facing_summary") or "").strip()
    incidence_summary = summary
    if incidence_id and title:
        incidence_summary = f"Incidence {incidence_id}: {title}"
        if summary:
            incidence_summary = f"{incidence_summary}. {summary}"
    elif title:
        incidence_summary = title
    when_parts = []
    if summary:
        when_parts.append(summary)
    if symptoms:
        when_parts.append("Choose when site report includes: " + "; ".join(symptoms[:6]))
    elif examples:
        when_parts.append("Operator language like: " + "; ".join(examples[:4]))
    when_to_choose = " ".join(when_parts).strip()
    return {
        "playbook_id": playbook_id,
        "title": title,
        "case_id": case_id,
        "incidence_id": incidence_id,
        "incidence_summary": incidence_summary,
        "when_to_choose": when_to_choose,
        "score": round(float(score), 4),
        "summary": summary,
        "observed_entry_symptoms": symptoms,
        "support_user_language_examples": examples,
        "selection_label": title[:120],
    }


def _rank_playbook_candidates(
    state: dict[str, Any],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    from backend.app.retrieval.hybrid_retriever import symptom_overlap_score

    query = _enriched_retrieval_query(state)
    index = get_corpus_index()
    variant = state.get("playbook_variant") or "prompt_a"
    record_type = "playbook_prompt_a" if variant == "prompt_a" else "playbook_prompt_b"
    allowed_ids = {
        item.source_record_id
        for item in index.embeddings
        if item.record_type == record_type
    }
    scored: dict[str, dict[str, Any]] = {}
    for hit in list(state.get("retrieval_hits") or []):
        if not isinstance(hit, dict):
            continue
        playbook_id = str(hit.get("source_record_id") or "")
        if not playbook_id or (allowed_ids and playbook_id not in allowed_ids):
            continue
        card = index.symptom_cards.get(playbook_id) or {}
        if not card:
            card = {
                "title": hit.get("title") or playbook_id,
                "case_id": (hit.get("filter_metadata") or {}).get("case_id"),
                "observed_entry_symptoms": _entry_symptoms_for_hit(hit),
                "user_facing_summary": hit.get("snippet") or "",
            }
        score = float(hit.get("combined_score") or 0.0)
        scored[playbook_id] = _candidate_from_card(playbook_id, card, score=score)
    for playbook_id, card in index.symptom_cards.items():
        if allowed_ids and playbook_id not in allowed_ids:
            continue
        if not isinstance(card, dict):
            continue
        score = symptom_overlap_score(
            query,
            list(card.get("observed_entry_symptoms") or []),
            list(card.get("support_user_language_examples") or []),
        )
        if score <= 0.0:
            continue
        existing = scored.get(playbook_id)
        if existing is None or score > float(existing.get("score") or 0.0):
            scored[playbook_id] = _candidate_from_card(playbook_id, card, score=score)
    ranked = sorted(scored.values(), key=lambda item: (-float(item.get("score") or 0.0), item["playbook_id"]))
    return ranked[:top_k]


def _correlated_symptoms(candidates: list[dict[str, Any]], observed: dict[str, bool]) -> list[str]:
    from backend.app.retrieval.hybrid_retriever import tokenize

    observed_tokens = set()
    for key, value in observed.items():
        if value:
            observed_tokens |= tokenize(str(key).replace("_", " "))
    collected: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for symptom in candidate.get("observed_entry_symptoms") or []:
            text = str(symptom).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            symptom_tokens = tokenize(text)
            if observed_tokens and symptom_tokens and symptom_tokens <= observed_tokens:
                continue
            seen.add(key)
            collected.append(text)
    return collected[:12]


def request_more_symptoms(state: dict[str, Any]) -> dict[str, Any]:
    settings = get_corpus_settings()
    hits = list(state.get("retrieval_hits") or [])
    top_hit = hits[0] if hits and isinstance(hits[0], dict) else {}
    confidence = float(state.get("retrieval_confidence") or top_hit.get("combined_score") or 0.0)
    coverage = float(top_hit.get("coverage") or 0.0)
    threshold = settings.playbook_match_threshold
    coverage_threshold = settings.playbook_pin_coverage_threshold
    use_mock = any(
        item.embedding_model == "mock-hash-v1" for item in get_corpus_index().embeddings
    )
    if use_mock:
        threshold = min(threshold, 0.35)
    slice_: PlaybookSessionSlice = state["_playbook_slice"]
    slice_.active_playbook_id = None
    slice_.active_case_id = None
    slice_.current_node_id = None
    slice_.pin_source = None
    slice_.last_retrieval_confidence = confidence
    state["active_playbook_id"] = None
    state["active_case_id"] = None
    state["current_node_id"] = None
    state["playbook_payload"] = {}
    state["runbook_payload"] = {}
    state["runbook_step"] = {}
    state["canonical_images"] = []

    candidates = _rank_playbook_candidates(state, top_k=5)
    observed = dict(state.get("extracted_observed_signals") or {})
    correlated = _correlated_symptoms(candidates, observed)
    state["playbook_candidates"] = candidates
    state["correlated_symptoms"] = correlated
    top_title = str(top_hit.get("title") or top_hit.get("source_record_id") or "")
    breakdown = {
        "cosine": float(top_hit.get("cosine_score") or 0.0),
        "jaccard": float(top_hit.get("jaccard_score") or 0.0),
        "symptom": float(top_hit.get("symptom_score") or 0.0),
    }
    state["retrieval_confidence_reason"] = _explain_retrieval_confidence(
        combined=confidence,
        cosine=breakdown["cosine"],
        jaccard=breakdown["jaccard"],
        symptom=breakdown["symptom"],
        coverage=coverage,
        threshold=threshold,
        coverage_threshold=coverage_threshold,
        pinned=False,
        top_title=top_title or None,
    )
    pin_gate = (
        f"rank {confidence:.2f} (need >= {threshold:.2f}) and "
        f"coverage {coverage:.2f} (need >= {coverage_threshold:.2f})"
    )

    if not candidates:
        state["guided_question"] = None
        state["response_type"] = "answer"
        fallback = (
            f"No playbook matched strongly enough yet ({pin_gate}). "
            "Share more observable symptoms so I can match a playbook."
        )
        message, reason = _maybe_llm_orchestrate(
            state,
            mode="request_symptoms",
            fallback_user_message=fallback,
            confidence_reason_seed=str(state.get("retrieval_confidence_reason") or ""),
        )
        state["final_response"] = message
        state["retrieval_confidence_reason"] = reason
        slice_.branch_state = {}
        state["branch_state"] = {}
        append_agent_trace(
            state,
            "orchestrator_agent",
            "request_more_symptoms",
            confidence=confidence,
            threshold=threshold,
            coverage=coverage,
            coverage_threshold=coverage_threshold,
            candidate_count=0,
            confidence_reason=state.get("retrieval_confidence_reason"),
        )
        return state

    labels: list[str] = []
    label_map: dict[str, str] = {}
    for index, candidate in enumerate(candidates, start=1):
        label = f"{index}. {candidate.get('title') or candidate.get('playbook_id')}"
        labels.append(label)
        label_map[label] = str(candidate["playbook_id"])
        label_map[str(candidate["playbook_id"])] = str(candidate["playbook_id"])
        title = str(candidate.get("title") or "")
        if title:
            label_map[title.lower()] = str(candidate["playbook_id"])

    slice_.branch_state = {
        "awaiting_candidate": True,
        "awaiting_branch": False,
        "resolved": False,
        "allowed_answers": labels,
        "candidate_map": label_map,
        "candidates": candidates,
    }
    state["branch_state"] = slice_.branch_state
    state["guided_question"] = {
        "question": "Select the playbook that best matches the site report",
        "allowed_answers": labels,
        "node_id": "playbook_candidate_select",
        "mode": "playbook_candidates",
    }
    state["response_type"] = "playbook_candidates"
    top_candidate = candidates[0] if candidates else {}
    top_name = str(top_candidate.get("title") or top_candidate.get("playbook_id") or "a candidate")
    symptom_hint = ""
    if correlated:
        symptom_hint = f" Add symptoms like: {correlated[0]}"
        if len(correlated) > 1:
            symptom_hint += f"; {correlated[1]}"
        symptom_hint += "."
    fallback = (
        f"Best match ~{float(top_candidate.get('score') or confidence):.2f}: "
        f"{top_name}. Pick the playbook that matches your site report, "
        f"or reply with more symptoms.{symptom_hint}"
    )
    message, reason = _maybe_llm_orchestrate(
        state,
        mode="present_candidates",
        fallback_user_message=fallback,
        confidence_reason_seed=str(state.get("retrieval_confidence_reason") or ""),
        extra={
            "candidates": [
                {
                    "title": item.get("title"),
                    "score": item.get("score"),
                    "case_id": item.get("case_id"),
                    "incidence_id": item.get("incidence_id"),
                    "incidence_summary": item.get("incidence_summary"),
                    "when_to_choose": item.get("when_to_choose"),
                }
                for item in candidates[:5]
            ],
            "correlated_symptoms": correlated[:4],
        },
    )
    state["final_response"] = message
    state["retrieval_confidence_reason"] = reason
    append_agent_trace(
        state,
        "orchestrator_agent",
        "present_playbook_candidates",
        confidence=confidence,
        threshold=threshold,
        coverage=coverage,
        coverage_threshold=coverage_threshold,
        candidate_count=len(candidates),
        correlated_symptom_count=len(correlated),
        cosine=float(top_hit.get("cosine_score") or 0.0),
        jaccard=float(top_hit.get("jaccard_score") or 0.0),
        symptom=float(top_hit.get("symptom_score") or 0.0),
        combined=confidence,
        confidence_reason=state.get("retrieval_confidence_reason"),
    )
    return state


def apply_candidate_selection(state: dict[str, Any]) -> dict[str, Any]:
    slice_: PlaybookSessionSlice = state["_playbook_slice"]
    message = (state.get("user_message") or "").strip()
    branch_state = dict(state.get("branch_state") or slice_.branch_state or {})
    label_map = {
        str(key): str(value)
        for key, value in dict(branch_state.get("candidate_map") or {}).items()
    }
    allowed_labels = [str(item) for item in list(branch_state.get("allowed_answers") or [])]
    if _is_exact_allowed_answer(message, allowed_labels) or message in label_map:
        state["_guided_button_answer"] = True
    chosen_id = label_map.get(message) or label_map.get(message.lower())
    if chosen_id is None:
        lowered = message.lower()
        for label, playbook_id in label_map.items():
            if label.lower() in lowered or playbook_id.lower() in lowered:
                chosen_id = playbook_id
                break
    if not chosen_id:
        if _looks_like_new_symptoms(message):
            state["_retriage_turn"] = True
            _clear_active_playbook(state, slice_, preserve_path_memory=True)
            state["_route_after_candidate"] = "extract"
            append_agent_trace(
                state,
                "orchestrator_agent",
                "candidate_retriage",
                message=message,
                working_memory=_lean_working_memory(state, slice_),
            )
            return state
        state["response_type"] = "playbook_candidates"
        state["guided_question"] = {
            "question": "Select the playbook that best matches the site report",
            "allowed_answers": list(branch_state.get("allowed_answers") or []),
            "node_id": "playbook_candidate_select",
            "mode": "playbook_candidates",
        }
        state["playbook_candidates"] = list(branch_state.get("candidates") or [])
        state["final_response"] = (
            "I could not match that selection. Pick one of the listed playbooks "
            "or add more symptoms."
        )
        append_agent_trace(state, "orchestrator_agent", "candidate_match_failed", message=message)
        return state

    client = get_corpus_client()
    playbook = client.get_playbook(chosen_id, variant=slice_.playbook_variant)
    if playbook is None:
        found = client.find_playbook_for_case(chosen_id, variant=slice_.playbook_variant)
        if found:
            chosen_id, playbook = found
    if not playbook:
        state["response_type"] = "answer"
        state["final_response"] = f"Could not load playbook `{chosen_id}`."
        append_agent_trace(state, "orchestrator_agent", "candidate_load_failed", playbook_id=chosen_id)
        return state

    score = 0.0
    for candidate in branch_state.get("candidates") or []:
        if str(candidate.get("playbook_id")) == chosen_id:
            score = float(candidate.get("score") or 0.0)
            break
    slice_.active_playbook_id = chosen_id
    slice_.active_case_id = str(playbook.get("case_id") or "")
    slice_.pin_source = "user_select"
    slice_.last_retrieval_confidence = max(score, 0.01)
    slice_.branch_state = {}
    nodes = list(playbook.get("nodes") or [])
    if nodes:
        first_node = sorted(nodes, key=lambda item: int(item.get("node_order") or 999))[0]
        slice_.current_node_id = str(first_node.get("node_id") or "")
    state["active_playbook_id"] = slice_.active_playbook_id
    state["active_case_id"] = slice_.active_case_id
    state["current_node_id"] = slice_.current_node_id
    state["playbook_payload"] = playbook
    state["branch_state"] = {}
    state["retrieval_confidence"] = slice_.last_retrieval_confidence
    seed = (
        f"Operator selected `{playbook.get('title') or chosen_id}` "
        f"(prior retrieval score {score:.2f}; pin confirmed by user, not auto-pin)."
    )
    _, reason = _maybe_llm_orchestrate(
        state,
        mode="user_selected",
        fallback_user_message=seed,
        confidence_reason_seed=seed,
        extra={"selected_playbook_id": chosen_id, "selected_score": score},
    )
    state["retrieval_confidence_reason"] = reason
    state["playbook_candidates"] = []
    append_agent_trace(
        state,
        "orchestrator_agent",
        "user_selected_playbook",
        playbook_id=chosen_id,
        score=score,
        confidence_reason=state["retrieval_confidence_reason"],
    )
    append_agent_trace(
        state,
        "orchestrator_agent",
        "explain_confidence",
        reason=state["retrieval_confidence_reason"],
        pinned=True,
    )
    return state


def load_playbook_session(session: WorkflowSession | None) -> PlaybookSessionSlice:
    settings = get_corpus_settings()
    payload = None
    if session and isinstance(session.dynamic_path, dict):
        payload = session.dynamic_path.get("playbook")
    return PlaybookSessionSlice.from_dict(
        payload if isinstance(payload, dict) else None,
        default_version=settings.publish_version_id,
    )


def save_playbook_session(
    session_id: str,
    slice_: PlaybookSessionSlice,
    *,
    state: dict[str, Any] | None = None,
) -> None:
    service = build_session_service()
    session = service.get_or_create(session_id)
    dynamic_path = dict(session.dynamic_path or {})
    dynamic_path["playbook"] = slice_.to_dict()
    session.dynamic_path = dynamic_path
    session.current_node_id = slice_.current_node_id
    session.current_procedure_id = slice_.current_procedure_id
    session.current_step_index = slice_.current_step_index
    session.active_workflow_id = slice_.active_playbook_id
    session.merge_signals(slice_.observed_signals)
    session.mode = "playbook"
    if state:
        if state.get("operator_role"):
            session.operator_role = str(state.get("operator_role"))
        hit_ids = [
            str(hit.get("record_id") or hit.get("source_record_id") or "")
            for hit in list(state.get("retrieval_hits") or [])
            if isinstance(hit, dict)
        ]
        session.record_retrieval_ids([item for item in hit_ids if item])
        if state.get("current_node_id"):
            session.record_step(str(state.get("current_node_id")))
    service.save(session)


def session_load(state: dict[str, Any]) -> dict[str, Any]:
    settings = get_corpus_settings()
    service = build_session_service()
    session = service.get_or_create(state["session_id"])
    slice_ = load_playbook_session(session)
    requested_variant = state.get("playbook_variant") or settings.default_playbook_variant
    if slice_.playbook_variant != requested_variant and slice_.active_playbook_id:
        slice_.active_playbook_id = None
        slice_.active_case_id = None
        slice_.current_node_id = None
        slice_.branch_state = {}
        slice_.completed_node_ids = []
        slice_.path_evidence = []
        slice_.last_retrieval_confidence = 0.0
        slice_.pin_source = None
        append_agent_trace(state, "session_agent", "clear_pin_on_variant_change")
    slice_.playbook_variant = requested_variant
    if slice_.publish_version_id != settings.publish_version_id:
        slice_ = PlaybookSessionSlice(default_version=settings.publish_version_id, playbook_variant=requested_variant)
        append_agent_trace(state, "session_agent", "reset_on_version_change")
    stale_pin = (
        slice_.active_playbook_id
        and slice_.last_retrieval_confidence <= 0.0
        and slice_.pin_source != "user_select"
    )
    if stale_pin:
        append_agent_trace(
            state,
            "orchestrator_agent",
            "clear_stale_pin",
            playbook_id=slice_.active_playbook_id,
            reason="zero_confidence",
        )
        slice_.active_playbook_id = None
        slice_.active_case_id = None
        slice_.current_node_id = None
        slice_.branch_state = {}
        slice_.completed_node_ids = []
        slice_.current_procedure_id = None
        slice_.current_step_index = 0
        slice_.pin_source = None
    state["playbook_variant"] = slice_.playbook_variant
    state["publish_version_id"] = slice_.publish_version_id
    state["active_playbook_id"] = slice_.active_playbook_id
    state["active_case_id"] = slice_.active_case_id
    state["current_node_id"] = slice_.current_node_id
    state["branch_state"] = slice_.branch_state
    state["completed_node_ids"] = slice_.completed_node_ids
    state["path_evidence"] = list(slice_.path_evidence or [])
    state["retrieval_confidence"] = float(slice_.last_retrieval_confidence or 0.0)
    state["extracted_observed_signals"] = dict(slice_.observed_signals or {})
    state["extracted_signals"] = dict(slice_.observed_signals or {})
    state["issue_category"] = None
    state["operator_role"] = state.get("operator_role") or session.operator_role
    append_agent_trace(
        state,
        "session_agent",
        "load",
        active_playbook_id=slice_.active_playbook_id,
        path_evidence_count=len(slice_.path_evidence or []),
    )
    state["_playbook_slice"] = slice_
    return state


def embed_query(state: dict[str, Any]) -> dict[str, Any]:
    from backend.app.retrieval.hybrid_retriever import mock_embed

    query = state.get("user_message") or ""
    index = get_corpus_index()
    target_dims = len(index.embeddings[0].vector) if index.embeddings else 1536
    models = {item.embedding_model for item in index.embeddings if item.embedding_model}
    use_mock = bool(models) and models <= {"mock-hash-v1"}
    client = build_embedding_client()
    if use_mock or not client.available():
        vector = mock_embed(query, dimensions=target_dims)
        append_agent_trace(state, "embed_agent", "mock_embed", dimensions=len(vector))
    else:
        prefer_azure = any(
            model.startswith("text-embedding") or "openai" in model
            for model in models
        ) or client.azure_configured()
        try:
            vector = client.embed_texts(
                [query],
                dimensions=target_dims,
                prefer_azure=prefer_azure,
            )[0]
            append_agent_trace(
                state,
                "embed_agent",
                "azure_embed" if prefer_azure and client.azure_configured() else "local_embed",
                dimensions=len(vector),
                target_dimensions=target_dims,
                corpus_models=sorted(models),
            )
        except Exception as exc:
            if models & {"mock-hash-v1"} or not models:
                vector = mock_embed(query, dimensions=target_dims)
                append_agent_trace(
                    state,
                    "embed_agent",
                    "mock_embed_fallback",
                    error=str(exc),
                    dimensions=len(vector),
                )
            else:
                raise
    state["query_vector"] = vector
    return state


def _score_breakdown(hit: dict[str, Any] | None) -> dict[str, float]:
    hit = hit or {}
    return {
        "cosine": float(hit.get("cosine_score") or 0.0),
        "jaccard": float(hit.get("jaccard_score") or 0.0),
        "symptom": float(hit.get("symptom_score") or 0.0),
        "coverage": float(hit.get("coverage") or 0.0),
        "combined": float(hit.get("combined_score") or 0.0),
    }


def _should_invoke_orchestrator_llm(state: dict[str, Any], mode: str) -> bool:
    """LLM rewrite only for free-text retriage turns — not button / template paths."""
    del mode
    settings = get_corpus_settings()
    if not settings.enable_llm_orchestrator:
        return False
    if state.get("_guided_button_answer"):
        return False
    return bool(state.get("_retriage_turn"))


def _maybe_llm_orchestrate(
    state: dict[str, Any],
    *,
    mode: str,
    fallback_user_message: str,
    confidence_reason_seed: str,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Optional LLM polish for operator-facing orchestrator text (lean briefing only)."""
    settings = get_corpus_settings()
    reason = confidence_reason_seed
    message = fallback_user_message
    if not _should_invoke_orchestrator_llm(state, mode):
        append_agent_trace(
            state,
            "orchestrator_agent",
            "template_only",
            mode=mode,
            retriage=bool(state.get("_retriage_turn")),
            guided_button=bool(state.get("_guided_button_answer")),
        )
        return message, reason
    try:
        from backend.app.services.llm_playbook_client import llm_compose_orchestrator_message

        top = (state.get("retrieval_hits") or [{}])[0] if state.get("retrieval_hits") else {}
        slice_: PlaybookSessionSlice | None = state.get("_playbook_slice")
        briefing = {
            "mode": mode,
            "operator_message": state.get("user_message"),
            "working_memory": _lean_working_memory(state, slice_),
            "retrieval_confidence": state.get("retrieval_confidence"),
            "retrieval_score_breakdown": {
                "cosine": float((top or {}).get("cosine_score") or 0.0),
                "jaccard": float((top or {}).get("jaccard_score") or 0.0),
                "symptom": float((top or {}).get("symptom_score") or 0.0),
                "coverage": float((top or {}).get("coverage") or 0.0),
                "combined": float(state.get("retrieval_confidence") or 0.0),
            },
            "pin_thresholds": {
                "match": settings.playbook_match_threshold,
                "coverage": settings.playbook_pin_coverage_threshold,
            },
            "confidence_reason_seed": confidence_reason_seed,
            "fallback_user_message": fallback_user_message,
            "candidates": [
                {
                    "title": item.get("title") if isinstance(item, dict) else None,
                    "score": item.get("score") if isinstance(item, dict) else None,
                    "case_id": item.get("case_id") if isinstance(item, dict) else None,
                }
                for item in list(state.get("playbook_candidates") or [])[:5]
                if isinstance(item, dict)
            ],
            "correlated_symptoms": list(state.get("correlated_symptoms") or [])[:4],
            "active_playbook": {
                "id": state.get("active_playbook_id"),
                "title": (state.get("playbook_payload") or {}).get("title"),
                "node_id": state.get("current_node_id"),
            },
        }
        if extra:
            briefing.update(extra)
        composed = llm_compose_orchestrator_message(briefing)
        if not composed:
            append_agent_trace(state, "orchestrator_agent", "llm_compose_skipped")
            return message, reason
        if composed.get("user_message"):
            message = composed["user_message"]
        if composed.get("confidence_reason"):
            reason = composed["confidence_reason"]
        append_agent_trace(state, "orchestrator_agent", "llm_compose", mode=mode)
        return message, reason
    except Exception as exc:
        append_agent_trace(
            state,
            "orchestrator_agent",
            "llm_compose_failed",
            error=str(exc)[:200],
        )
        return message, reason


def _explain_retrieval_confidence(
    *,
    combined: float,
    cosine: float,
    jaccard: float,
    symptom: float,
    coverage: float,
    threshold: float,
    coverage_threshold: float,
    pinned: bool,
    top_title: str | None = None,
) -> str:
    """Operator-facing explanation owned by orchestrator_agent."""
    scores = (
        f"Retrieval confidence {combined:.2f} "
        f"(cosine {cosine:.2f}, lexical {jaccard:.2f}, symptom {symptom:.2f}, "
        f"coverage {coverage:.2f})."
    )
    if pinned:
        target = f" for `{top_title}`" if top_title else ""
        return f"{scores} Auto-pinned{target}."
    if combined < threshold:
        why = f"below pin threshold {threshold:.2f}"
    elif coverage < coverage_threshold:
        why = f"coverage below pin floor {coverage_threshold:.2f}"
    elif cosine <= 0.0 and combined > 0.0:
        why = "lexical/symptom overlap only (vector 0.00)"
    else:
        why = "pin gates not met"
    target = f" Top: `{top_title}`." if top_title else ""
    return f"{scores} Not auto-pinned ({why}).{target}"


def hybrid_search(state: dict[str, Any], *, record_types: set[str], top_k: int = 5) -> dict[str, Any]:
    from backend.app.graph.playbook_state import hits_to_dict

    index = get_corpus_index()
    settings = get_corpus_settings()
    retriever = HybridRetriever(
        index.embeddings,
        config=RetrievalConfig(
            playbook_match_threshold=settings.playbook_match_threshold,
            playbook_high_confidence_threshold=settings.playbook_high_confidence_threshold,
            playbook_pin_coverage_threshold=settings.playbook_pin_coverage_threshold,
        ),
        symptom_cards=index.symptom_cards,
    )
    query_text = _enriched_retrieval_query(state)
    hits = retriever.search(
        query_text,
        query_vector=state.get("query_vector"),
        record_types=record_types,
        top_k=top_k,
    )
    state["retrieval_hits"] = hits_to_dict(hits)
    top_hit = state["retrieval_hits"][0] if state["retrieval_hits"] else None
    top_score = float(top_hit.get("combined_score") or 0.0) if top_hit else 0.0
    state["retrieval_confidence"] = top_score
    breakdown = _score_breakdown(top_hit)
    append_agent_trace(
        state,
        "retrieval_agent",
        "search",
        record_types=sorted(record_types),
        top_hit=top_hit,
        retrieval_confidence=top_score,
        query_text=query_text,
        cosine=breakdown["cosine"],
        jaccard=breakdown["jaccard"],
        symptom=breakdown["symptom"],
        coverage=breakdown["coverage"],
        combined=breakdown["combined"],
    )
    return state


def pin_playbook(state: dict[str, Any]) -> dict[str, Any]:
    settings = get_corpus_settings()
    hits = list(state.get("retrieval_hits") or [])
    slice_: PlaybookSessionSlice = state["_playbook_slice"]
    record_type = (
        "playbook_prompt_a"
        if slice_.playbook_variant == "prompt_a"
        else "playbook_prompt_b"
    )
    playbook_hits = [hit for hit in hits if hit.get("record_type") == record_type]
    threshold = settings.playbook_match_threshold
    coverage_threshold = settings.playbook_pin_coverage_threshold
    use_mock = any(item.embedding_model == "mock-hash-v1" for item in get_corpus_index().embeddings)
    if use_mock:
        threshold = min(threshold, 0.35)
    state["retrieval_confidence"] = float(
        (playbook_hits[0].get("combined_score") if playbook_hits else 0.0) or 0.0
    )
    slice_.last_retrieval_confidence = float(state["retrieval_confidence"] or 0.0)
    if not playbook_hits:
        state["active_playbook_id"] = None
        state["retrieval_confidence_reason"] = (
            "Retrieval confidence 0.00. No playbook candidates matched the observed symptoms."
        )
        append_agent_trace(
            state,
            "playbook_pin_agent",
            "no_playbook_match",
        )
        append_agent_trace(
            state,
            "orchestrator_agent",
            "explain_confidence",
            reason=state["retrieval_confidence_reason"],
            pinned=False,
        )
        return state
    top = playbook_hits[0]
    score = float(top.get("combined_score") or 0.0)
    coverage = float(top.get("coverage") or 0.0)
    breakdown = _score_breakdown(top)
    top_title = str(top.get("title") or top.get("source_record_id") or "")
    if score < threshold or score <= 0.0 or coverage < coverage_threshold:
        state["active_playbook_id"] = None
        state["retrieval_confidence_reason"] = _explain_retrieval_confidence(
            combined=score,
            cosine=breakdown["cosine"],
            jaccard=breakdown["jaccard"],
            symptom=breakdown["symptom"],
            coverage=coverage,
            threshold=threshold,
            coverage_threshold=coverage_threshold,
            pinned=False,
            top_title=top_title or None,
        )
        append_agent_trace(
            state,
            "playbook_pin_agent",
            "below_threshold",
            score=score,
            threshold=threshold,
            coverage=coverage,
            coverage_threshold=coverage_threshold,
            cosine=breakdown["cosine"],
            jaccard=breakdown["jaccard"],
            symptom=breakdown["symptom"],
            combined=breakdown["combined"],
        )
        append_agent_trace(
            state,
            "orchestrator_agent",
            "explain_confidence",
            reason=state["retrieval_confidence_reason"],
            pinned=False,
        )
        return state
    high_confidence = (
        score >= settings.playbook_high_confidence_threshold
        and coverage >= coverage_threshold
    )
    should_auto_pin = bool(settings.skip_playbook_confirmation)
    if not should_auto_pin:
        state["active_playbook_id"] = None
        slice_.active_playbook_id = None
        slice_.active_case_id = None
        slice_.current_node_id = None
        slice_.pin_source = None
        state["retrieval_confidence_reason"] = _explain_retrieval_confidence(
            combined=score,
            cosine=breakdown["cosine"],
            jaccard=breakdown["jaccard"],
            symptom=breakdown["symptom"],
            coverage=coverage,
            threshold=threshold,
            coverage_threshold=coverage_threshold,
            pinned=False,
            top_title=top_title or None,
        )
        append_agent_trace(
            state,
            "playbook_pin_agent",
            "defer_to_candidates",
            score=score,
            threshold=threshold,
            coverage=coverage,
            coverage_threshold=coverage_threshold,
            cosine=breakdown["cosine"],
            jaccard=breakdown["jaccard"],
            symptom=breakdown["symptom"],
            combined=breakdown["combined"],
            high_confidence=high_confidence,
            top_playbook_id=str(top.get("source_record_id") or ""),
            case_id=str((top.get("filter_metadata") or {}).get("case_id") or ""),
        )
        append_agent_trace(
            state,
            "orchestrator_agent",
            "explain_confidence",
            reason=state["retrieval_confidence_reason"],
            pinned=False,
            candidate_first=True,
        )
        return state
    playbook_id = str(top.get("source_record_id") or "")
    client = get_corpus_client()
    playbook = client.get_playbook(playbook_id, variant=slice_.playbook_variant)
    resolved_playbook_id = playbook_id
    if playbook is None:
        case_id = str((top.get("filter_metadata") or {}).get("case_id") or "")
        if case_id:
            found = client.find_playbook_for_case(case_id, variant=slice_.playbook_variant)
            if found:
                resolved_playbook_id, playbook = found
    slice_.active_playbook_id = resolved_playbook_id
    slice_.active_case_id = str((playbook or {}).get("case_id") or top.get("filter_metadata", {}).get("case_id") or "")
    slice_.last_retrieval_confidence = score
    slice_.pin_source = "retrieval"
    nodes = list((playbook or {}).get("nodes") or [])
    if nodes:
        first_node = sorted(nodes, key=lambda item: int(item.get("node_order") or 999))[0]
        slice_.current_node_id = str(first_node.get("node_id") or "")
    state["active_playbook_id"] = slice_.active_playbook_id
    state["active_case_id"] = slice_.active_case_id
    state["current_node_id"] = slice_.current_node_id
    state["playbook_payload"] = playbook or {}
    state["retrieval_confidence"] = score
    seed = _explain_retrieval_confidence(
        combined=score,
        cosine=breakdown["cosine"],
        jaccard=breakdown["jaccard"],
        symptom=breakdown["symptom"],
        coverage=coverage,
        threshold=threshold,
        coverage_threshold=coverage_threshold,
        pinned=True,
        top_title=str((playbook or {}).get("title") or top_title or resolved_playbook_id),
    )
    title = str((playbook or {}).get("title") or resolved_playbook_id)
    fallback = (
        f"Pinned playbook `{title}` (score {score:.2f}). "
        "Answer the current node as healthy, unhealthy, or inconclusive."
    )
    message, reason = _maybe_llm_orchestrate(
        state,
        mode="pinned",
        fallback_user_message=fallback,
        confidence_reason_seed=seed,
    )
    state["retrieval_confidence_reason"] = reason
    # final_response is filled by execute_playbook_node; keep polished fallback if needed
    state["_orchestrator_pin_message"] = message
    append_agent_trace(
        state,
        "orchestrator_agent",
        "pin_playbook",
        playbook_id=resolved_playbook_id,
        score=score,
        threshold=threshold,
        coverage=coverage,
        coverage_threshold=coverage_threshold,
        cosine=breakdown["cosine"],
        jaccard=breakdown["jaccard"],
        symptom=breakdown["symptom"],
        combined=breakdown["combined"],
        confidence_reason=state["retrieval_confidence_reason"],
    )
    append_agent_trace(
        state,
        "playbook_pin_agent",
        "pin",
        playbook_id=playbook_id,
        score=score,
        threshold=threshold,
        coverage=coverage,
        coverage_threshold=coverage_threshold,
        cosine=breakdown["cosine"],
        jaccard=breakdown["jaccard"],
        symptom=breakdown["symptom"],
        combined=breakdown["combined"],
        auto_pin=True,
    )
    append_agent_trace(
        state,
        "orchestrator_agent",
        "explain_confidence",
        reason=state["retrieval_confidence_reason"],
        pinned=True,
    )
    return state


def execute_playbook_node(state: dict[str, Any]) -> dict[str, Any]:
    slice_: PlaybookSessionSlice = state["_playbook_slice"]
    client = get_corpus_client()
    playbook_id = slice_.active_playbook_id or ""
    playbook = state.get("playbook_payload") or client.get_playbook(
        playbook_id, variant=slice_.playbook_variant
    )
    if not playbook:
        state["final_response"] = "Playbook could not be loaded."
        state["response_type"] = "answer"
        return state
    node_id = slice_.current_node_id
    node = next(
        (item for item in playbook.get("nodes", []) if str(item.get("node_id")) == node_id),
        None,
    )
    if not node:
        state["final_response"] = "Playbook node not found."
        state["response_type"] = "answer"
        return state
    procedure_id = client.resolve_runbook_for_node(playbook_id, str(node_id), playbook)
    runbook = client.get_runbook(procedure_id) if procedure_id else None
    slice_.current_procedure_id = procedure_id
    state["playbook_payload"] = playbook
    state["runbook_payload"] = runbook or {}
    state["current_node_payload"] = node if isinstance(node, dict) else {}
    playbook_dict = playbook if isinstance(playbook, dict) else {}
    state["branch_qualification_metrics"] = _branch_qualification_metrics(
        node if isinstance(node, dict) else {},
        runbook if isinstance(runbook, dict) else {},
        playbook_dict,
    )
    steps = list((runbook or {}).get("steps") or [])
    step = steps[slice_.current_step_index] if steps else {}
    state["runbook_step"] = step if isinstance(step, dict) else {}
    branch_options = _branch_options(node if isinstance(node, dict) else {}, playbook_dict)
    answers = [str(item.get("label")) for item in branch_options]
    if answers and not state.get("branch_state", {}).get("resolved"):
        slice_.branch_state = {
            "awaiting_branch": True,
            "resolved": False,
            "allowed_answers": answers,
            "branch_options": branch_options,
            "node_id": node_id,
        }
        state["branch_state"] = slice_.branch_state
        state["guided_question"] = {
            "question": str(node.get("title") or "Select the observed outcome"),
            "allowed_answers": answers,
            "branch_options": branch_options,
            "node_id": node_id,
            "branch_qualification_metrics": state["branch_qualification_metrics"],
        }
        state["response_type"] = "guided_question"
        fallback = (
            f"{node.get('title')}: {node.get('intent') or node.get('goal') or ''}".strip()
        )
        message, _ = _maybe_llm_orchestrate(
            state,
            mode="branch_prompt",
            fallback_user_message=fallback,
            confidence_reason_seed=str(
                state.get("retrieval_confidence_reason")
                or state.get("_orchestrator_pin_message")
                or fallback
            ),
            extra={
                "node": {
                    "id": node_id,
                    "title": node.get("title"),
                    "intent": node.get("intent") or node.get("goal"),
                },
                "allowed_answers": answers,
            },
        )
        state["final_response"] = message
        append_agent_trace(
            state,
            "execute_agent",
            "branch_prompt",
            node_id=node_id,
            allowed_answers=answers,
            branch_options=branch_options,
        )
        append_agent_trace(
            state,
            "orchestrator_agent",
            "branch_prompt_compose",
            node_id=node_id,
        )
        _attach_runbook_images(state)
        return state
    instruction = str(step.get("instruction") or node.get("intent") or node.get("goal") or "")
    expected = str(step.get("expected_result") or "")
    state["response_type"] = "workflow_step"
    state["final_response"] = instruction
    if expected:
        state["final_response"] += f"\n\nExpected: {expected}"
    append_agent_trace(
        state,
        "execute_agent",
        "render_step",
        node_id=node_id,
        procedure_id=procedure_id,
    )
    _attach_runbook_images(state)
    return state


def apply_branch_answer(state: dict[str, Any]) -> dict[str, Any]:
    slice_: PlaybookSessionSlice = state["_playbook_slice"]
    message = (state.get("user_message") or "").strip()
    guided = state.get("guided_question") or {}
    branch_state = dict(state.get("branch_state") or slice_.branch_state or {})
    allowed = [
        str(item)
        for item in (guided.get("allowed_answers") or branch_state.get("allowed_answers") or [])
    ]
    source_node_id = str(
        branch_state.get("node_id") or slice_.current_node_id or ""
    ).strip() or None
    playbook = state.get("playbook_payload") if isinstance(state.get("playbook_payload"), dict) else {}
    if not playbook and slice_.active_playbook_id:
        playbook = get_corpus_client().get_playbook(
            slice_.active_playbook_id, variant=slice_.playbook_variant
        ) or {}
        state["playbook_payload"] = playbook
    source_node = next(
        (
            item
            for item in list((playbook or {}).get("nodes") or [])
            if isinstance(item, dict) and str(item.get("node_id") or "") == source_node_id
        ),
        {},
    )
    if not isinstance(source_node, dict):
        source_node = {}
    branch_options = list(
        guided.get("branch_options")
        or branch_state.get("branch_options")
        or _branch_options(source_node, playbook)
    )

    exact_button = _is_exact_allowed_answer(message, allowed)
    if exact_button:
        state["_guided_button_answer"] = True

    classified: dict[str, str] | None = None
    settings = get_corpus_settings()
    # Buttons / exact labels: deterministic only. Free text may use branch LLM.
    if exact_button or not settings.enable_llm_branch_match:
        classified = _classify_branch_reply_deterministic(message, allowed)
        append_agent_trace(
            state,
            "branch_agent",
            "keyword_classify",
            classification=classified.get("action"),
            choice=classified.get("label") or message,
            guided_button=exact_button,
        )
    else:
        deterministic = _classify_branch_reply_deterministic(message, allowed)
        det_action = str(deterministic.get("action") or "").strip().lower()
        # Synonyms / clear retriage stay deterministic; LLM only when still ambiguous.
        if det_action in {"match", "retriage"} or not str(message or "").strip():
            classified = deterministic
            append_agent_trace(
                state,
                "branch_agent",
                "keyword_classify",
                classification=classified.get("action"),
                choice=classified.get("label") or message,
            )
        else:
            from backend.app.services.llm_playbook_client import llm_classify_branch_reply

            classified = llm_classify_branch_reply(
                message,
                allowed,
                node_title=str(source_node.get("title") or ""),
                node_intent=str(source_node.get("intent") or source_node.get("goal") or ""),
            )
            if classified:
                append_agent_trace(
                    state,
                    "branch_agent",
                    "llm_classify",
                    classification=classified.get("action"),
                    choice=classified.get("label") or None,
                )
            else:
                classified = deterministic
                append_agent_trace(
                    state,
                    "branch_agent",
                    "keyword_classify",
                    classification=classified.get("action"),
                    choice=classified.get("label") or message,
                )

    action = str(classified.get("action") or "").strip().lower()
    if action == "retriage":
        state["_retriage_turn"] = True
        _clear_active_playbook(state, slice_, preserve_path_memory=True)
        state["_route_after_branch"] = "extract"
        append_agent_trace(
            state,
            "branch_agent",
            "retriage",
            message=message,
            from_node_id=source_node_id,
            path_evidence_count=len(slice_.path_evidence or []),
        )
        append_agent_trace(
            state,
            "orchestrator_agent",
            "accept_retriage",
            reason="new_symptoms_during_branch",
            working_memory=_lean_working_memory(state, slice_),
        )
        return state

    if action == "probe":
        probe = str(classified.get("probe_question") or "").strip() or (
            "Please choose one of the branch options, or describe new site symptoms."
        )
        slice_.branch_state = {
            "awaiting_branch": True,
            "resolved": False,
            "allowed_answers": allowed,
            "branch_options": branch_options,
            "node_id": source_node_id,
        }
        state["branch_state"] = slice_.branch_state
        state["guided_question"] = {
            "question": str(source_node.get("title") or guided.get("question") or "Select the observed outcome"),
            "allowed_answers": allowed,
            "branch_options": branch_options,
            "node_id": source_node_id,
            "branch_qualification_metrics": state.get("branch_qualification_metrics")
            or guided.get("branch_qualification_metrics"),
        }
        state["response_type"] = "guided_question"
        state["final_response"] = probe
        state["_route_after_branch"] = "save"
        append_agent_trace(
            state,
            "branch_agent",
            "probe",
            message=message,
            node_id=source_node_id,
            probe=probe,
        )
        return state

    chosen = str(classified.get("label") or "").strip() or None
    if chosen is None:
        state["_route_after_branch"] = "save"
        state["response_type"] = "guided_question"
        state["final_response"] = (
            "Please choose one of the branch options, or describe new site symptoms."
        )
        slice_.branch_state = {
            "awaiting_branch": True,
            "resolved": False,
            "allowed_answers": allowed,
            "branch_options": branch_options,
            "node_id": source_node_id,
        }
        state["branch_state"] = slice_.branch_state
        append_agent_trace(state, "branch_agent", "classify_failed", message=message)
        return state

    next_node_id = _resolve_next_node_id(
        source_node,
        chosen,
        branch_options=branch_options,
        playbook=playbook if isinstance(playbook, dict) else {},
    )
    next_node_title = next(
        (
            str(option.get("next_node_title") or option.get("next_node_id") or "")
            for option in branch_options
            if str(option.get("label") or "").strip().lower() == str(chosen or "").strip().lower()
            and option.get("next_node_id")
        ),
        None,
    )
    if next_node_id and not next_node_title:
        next_node_title = _node_title_index(playbook).get(next_node_id) or next_node_id

    if source_node_id and source_node_id not in slice_.completed_node_ids:
        slice_.completed_node_ids.append(source_node_id)
    state["completed_node_ids"] = list(slice_.completed_node_ids)
    metrics = state.get("branch_qualification_metrics") or {}
    metric_row = metrics.get(str(chosen or "").strip().lower()) if isinstance(metrics, dict) else {}
    evidence_summary = ""
    if isinstance(metric_row, dict):
        evidence_summary = str(metric_row.get("summary") or "").strip()
    _append_path_evidence(
        slice_,
        node_id=source_node_id,
        title=str(source_node.get("title") or source_node_id or ""),
        outcome=chosen,
        evidence=evidence_summary,
    )
    state["path_evidence"] = list(slice_.path_evidence or [])
    state["_route_after_branch"] = "execute"

    if next_node_id:
        slice_.current_node_id = next_node_id
        state["current_node_id"] = next_node_id
        slice_.current_step_index = 0
        slice_.branch_state = {}
        state["branch_state"] = {}
        append_agent_trace(
            state,
            "branch_agent",
            "advance_node",
            choice=chosen,
            from_node_id=source_node_id,
            next_node_id=next_node_id,
            next_node_title=next_node_title,
            guided_button=bool(state.get("_guided_button_answer")),
        )
        return state

    slice_.branch_state = {
        "awaiting_branch": False,
        "resolved": True,
        "choice": chosen,
        "allowed_answers": allowed,
        "branch_options": branch_options,
        "node_id": source_node_id,
    }
    state["branch_state"] = slice_.branch_state
    append_agent_trace(
        state,
        "branch_agent",
        "no_next_node",
        choice=chosen,
        node_id=source_node_id,
        guided_button=bool(state.get("_guided_button_answer")),
    )
    return state


def runbook_fallback(state: dict[str, Any]) -> dict[str, Any]:
    state = hybrid_search(state, record_types={"canonical_runbook"}, top_k=3)
    hits = list(state.get("retrieval_hits") or [])
    if not hits:
        state["final_response"] = "No matching playbook or runbook found."
        state["response_type"] = "answer"
        return state
    top = hits[0]
    client = get_corpus_client()
    runbook = client.get_runbook(str(top.get("source_record_id") or ""))
    case_id = str((top.get("filter_metadata") or {}).get("case_id") or "")
    state["active_case_id"] = case_id or state.get("active_case_id")
    state["runbook_payload"] = runbook or {}
    steps = list((runbook or {}).get("steps") or [])
    step = steps[0] if steps else {}
    state["runbook_step"] = step if isinstance(step, dict) else {}
    state["response_type"] = "answer"
    state["final_response"] = str(step.get("instruction") or runbook.get("summary") or top.get("snippet") or "")
    append_agent_trace(state, "playbook_pin_agent", "runbook_fallback", procedure_id=top.get("source_record_id"))
    _attach_runbook_images(state)
    return state


def _hit_display_title(hit: dict[str, Any]) -> str:
    title = str(hit.get("title") or "").strip()
    if title:
        return title
    metadata = hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
    meta_title = str(metadata.get("title") or "").strip()
    if meta_title:
        return meta_title
    return str(hit.get("source_record_id") or hit.get("record_id") or "Unknown source")


def _hit_source_id(hit: dict[str, Any]) -> str:
    return str(hit.get("source_record_id") or hit.get("record_id") or "").strip()


def _format_retrieve_sources_block(hits: list[dict[str, Any]]) -> str:
    lines = ["Sources:"]
    for index, hit in enumerate(hits[:5], start=1):
        if not isinstance(hit, dict):
            continue
        title = _hit_display_title(hit)
        source_id = _hit_source_id(hit)
        if source_id and source_id != title:
            lines.append(f"- {title} (`{source_id}`)")
        else:
            lines.append(f"- {title}")
    return "\n".join(lines)


def _answer_cites_hits(answer: str, hits: list[dict[str, Any]]) -> bool:
    text = str(answer or "").lower()
    if "sources:" in text or "**sources**" in text:
        return True
    for hit in hits[:5]:
        if not isinstance(hit, dict):
            continue
        title = _hit_display_title(hit).lower()
        source_id = _hit_source_id(hit).lower()
        if title and len(title) >= 4 and title in text:
            return True
        if source_id and source_id in text:
            return True
    return False


def _ensure_retrieve_answer_cites_sources(answer: str, hits: list[dict[str, Any]]) -> str:
    text = str(answer or "").strip()
    usable = [hit for hit in hits if isinstance(hit, dict)]
    if not usable:
        return text
    if _answer_cites_hits(text, usable):
        if "sources:" not in text.lower():
            return f"{text}\n\n{_format_retrieve_sources_block(usable)}"
        return text
    if not text:
        return _format_retrieve_sources_block(usable)
    return f"{text}\n\n{_format_retrieve_sources_block(usable)}"


def _compose_template_retrieve_answer(
    query: str,
    hits: list[dict[str, Any]],
    *,
    intent: str | None = None,
    prior_turns: list[dict[str, Any]] | None = None,
) -> str:
    del prior_turns
    if not hits:
        return (
            "I could not find published runbooks or operational context for that question. "
            "Could you clarify what you need — OptiSweep **software/service** roles "
            "(WCS/RMS/Ignition), a **hardware/maintenance** procedure, or a **fault/symptom** "
            "to troubleshoot?"
        )
    top = hits[0]
    top_title = _hit_display_title(top)
    top_id = _hit_source_id(top)
    top_snippet = _clean_hit_excerpt(top)
    top_score = float(top.get("combined_score") or 0.0)
    cosine = float(top.get("cosine_score") or 0.0)
    coverage = float(top.get("coverage") or 0.0)
    cite = f"**{top_title}**"
    if top_id and top_id != top_title:
        cite = f"{cite} (`{top_id}`)"
    weak = top_score < 0.35 or (cosine < 0.25 and coverage < 0.45)
    resolved = intent in {"software_stack", "maintenance", "incident"}
    needs_clarify = _looks_like_overview_query(query) and not resolved
    lines: list[str] = []
    if needs_clarify:
        lines.extend(
            [
                "I found related published material for OptiSweep. To narrow this: by "
                "**OptiSweep service**, do you mean:",
                "",
                "1. The **software/service stack** (roles of OptiSweep, WCS, RMS, Ignition / "
                "communication path)?",
                "2. A **maintenance or hardware** procedure on OptiSweep equipment?",
                "3. A **live incident / symptom** (use Guided Troubleshoot)?",
                "",
                f"Meanwhile, one strong published match is {cite}.",
            ]
        )
    elif intent == "software_stack":
        lines.append(
            "Here is a concise summary of the OptiSweep **software/service stack** "
            f"from published training materials ({cite}):"
        )
    elif weak:
        lines.append(
            f"Closest published match: {cite}. "
            "If this is not what you meant, say whether you need software roles, "
            "maintenance steps, or help with a specific fault."
        )
    else:
        lines.append(f"Based on published materials ({cite}):")
    if top_snippet:
        lines.append(top_snippet)
    # Chatbot synthesis across top hits (avoid dumping procedure IDs alone).
    bullets: list[str] = []
    for hit in hits[:4]:
        if not isinstance(hit, dict):
            continue
        title = _hit_display_title(hit)
        sid = _hit_source_id(hit)
        excerpt = _clean_hit_excerpt(hit)
        if not excerpt or len(excerpt) < 20:
            continue
        if title == top_title and excerpt == top_snippet:
            continue
        label = f"**{title}**"
        if sid and sid != title:
            label = f"{label} (`{sid}`)"
        bullets.append(f"- {label}: {excerpt}")
    if bullets:
        lines.append("")
        lines.append("Additional grounded points:")
        lines.extend(bullets[:3])
    lines.append("")
    lines.append(_format_retrieve_sources_block(hits))
    return "\n".join(lines)


def _clean_hit_excerpt(hit: dict[str, Any]) -> str:
    snippet = str(hit.get("snippet") or hit.get("excerpt") or "").strip()
    if not snippet:
        return ""
    title = _hit_display_title(hit)
    if snippet.lower().startswith(title.lower()):
        snippet = snippet[len(title) :].lstrip(" :-—")
    return re.sub(r"\s+", " ", snippet)[:280].strip()


def _looks_like_overview_query(query: str) -> bool:
    text = str(query or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    if not tokens:
        return False
    if {"stack", "roles", "components", "wcs", "rms", "ignition"} & tokens:
        return False
    if "software" in tokens and "service" in tokens:
        return False
    overview = {"about", "what", "explain", "overview", "tell", "describe", "service"}
    return bool(tokens & overview) and ("optisweep" in tokens or "opti" in tokens)


def _attach_retrieve_hit_images(state: dict[str, Any]) -> None:
    """Resolve reference images for top runbook hits on `/retrieve`."""
    hits = list(state.get("retrieval_hits") or [])
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from backend.app.corpus.bootstrap import get_corpus_client
        from backend.app.services.canonical_image_lookup import build_canonical_image_lookup

        client = get_corpus_client()
        lookup = build_canonical_image_lookup()
    except Exception:
        state["canonical_images"] = []
        append_agent_trace(state, "image_agent", "retrieve_images_unavailable")
        return

    for hit in hits[:3]:
        if not isinstance(hit, dict):
            continue
        if str(hit.get("record_type") or "") not in {
            "canonical_runbook",
            "incident_source_runbook",
        }:
            continue
        procedure_id = str(hit.get("source_record_id") or "").strip()
        if not procedure_id:
            continue
        try:
            runbook = client.get_runbook(procedure_id) or {}
        except Exception:
            continue
        if not isinstance(runbook, dict) or not runbook:
            continue
        fallback_refs = _step_screen_refs(
            {"screens_or_images": list(runbook.get("screens_or_images") or [])}
        )
        if not fallback_refs:
            fallback_refs = [
                {
                    "artifact_id": str(ref.get("artifact_id") or "").strip(),
                    "what_to_look_at": ref.get("description") or ref.get("what_to_look_at"),
                }
                for ref in list(runbook.get("visual_references") or [])
                if isinstance(ref, dict) and str(ref.get("artifact_id") or "").strip()
            ]
        steps = [step for step in list(runbook.get("steps") or []) if isinstance(step, dict)]
        for index, step in enumerate(steps[:2]):
            screen_refs = _step_screen_refs(step)
            if not screen_refs and index == 0 and fallback_refs:
                screen_refs = list(fallback_refs)
            step_images = _resolve_step_images(
                lookup,
                screen_refs=screen_refs,
                embedded_images=list(step.get("canonical_images") or step.get("images") or []),
            )
            for image in step_images:
                key = str(image.get("image_id") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                out = dict(image)
                if not out.get("title"):
                    out["title"] = (
                        str(step.get("title") or "").strip()
                        or _hit_display_title(hit)
                    )
                out["source_procedure_id"] = procedure_id
                images.append(out)
            if len(images) >= 6:
                break
        if len(images) >= 6:
            break

    state["canonical_images"] = images
    append_agent_trace(
        state,
        "image_agent",
        "resolve_retrieve_hit_screens",
        image_count=len(images),
        hit_count=len(hits),
    )


def template_answer_from_hits(state: dict[str, Any]) -> dict[str, Any]:
    hits = list(state.get("retrieval_hits") or [])
    _attach_retrieve_hit_images(state)
    intent = state.get("retrieve_intent")
    prior = list(state.get("conversation_history") or [])
    if not hits:
        state["final_response"] = _compose_template_retrieve_answer(
            state.get("user_message") or "",
            [],
            intent=intent if isinstance(intent, str) else None,
            prior_turns=prior,
        )
        append_agent_trace(state, "synthesize_agent", "template_answer")
        return state
    settings = get_corpus_settings()
    if settings.enable_llm_retrieve_synthesis:
        from backend.app.services.llm_playbook_client import llm_compose_retrieve_answer

        answer = llm_compose_retrieve_answer(
            state.get("user_message") or "",
            hits,
            prior_turns=prior,
            intent=intent if isinstance(intent, str) else None,
        )
        if answer:
            state["final_response"] = _ensure_retrieve_answer_cites_sources(answer, hits)
            append_agent_trace(
                state,
                "synthesize_agent",
                "llm_compose",
                retrieve_intent=intent,
            )
            return state
    state["final_response"] = _compose_template_retrieve_answer(
        state.get("user_message") or "",
        hits,
        intent=intent if isinstance(intent, str) else None,
        prior_turns=prior,
    )
    append_agent_trace(
        state,
        "synthesize_agent",
        "template_answer",
        retrieve_intent=intent,
    )
    return state
