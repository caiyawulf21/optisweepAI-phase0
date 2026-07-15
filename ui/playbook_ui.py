"""Shared Streamlit helpers for playbook runtime UI."""

from __future__ import annotations

import re
from typing import Any

import requests
import streamlit as st

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


def parse_expected_outcome_evidence(expected: Any) -> dict[str, str]:
    """Split expected_or_observed_result into per-outcome evidence strings."""
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
    return len(parse_expected_outcome_evidence(value)) >= 2


def _node_title_index(playbook: dict[str, Any] | None) -> dict[str, str]:
    titles: dict[str, str] = {}
    for item in list((playbook or {}).get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if node_id:
            titles[node_id] = str(item.get("title") or node_id).strip() or node_id
    return titles


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


def branch_qualification_metrics(
    node: dict[str, Any] | None,
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
    node = node if isinstance(node, dict) else {}
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
    for option in branch_options_from_node(node, playbook):
        label = str(option.get("label") or "").strip().lower()
        if label not in metrics:
            continue
        if option.get("next_node_id") and not metrics[label]["next_node_id"]:
            metrics[label]["next_node_id"] = option.get("next_node_id")
            metrics[label]["next_node_title"] = option.get("next_node_title")
    expected = str(node.get("expected_or_observed_result") or "").strip()
    parsed = parse_expected_outcome_evidence(expected)
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


def branch_options_from_node(
    node: dict[str, Any] | None,
    playbook: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    titles = _node_title_index(playbook)
    node = node if isinstance(node, dict) else {}
    destinations = _branch_destination_map(node, playbook)

    def add(label: Any, next_node_id: Any = None) -> None:
        text = str(label or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        destination_id = str(next_node_id or "").strip() or destinations.get(key) or None
        options.append(
            {
                "label": text,
                "next_node_id": destination_id,
                "next_node_title": (titles.get(destination_id) if destination_id else None)
                or destination_id,
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


def _fetch_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params or {}, timeout=60)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _options_missing_destinations(options: Any) -> bool:
    if not isinstance(options, list) or not options:
        return True
    return all(not isinstance(item, dict) or not item.get("next_node_id") for item in options)


def _metrics_missing_option_destinations(metrics: Any, options: Any) -> bool:
    if not isinstance(options, list):
        return False
    if not isinstance(metrics, dict):
        return True
    for item in options:
        if not isinstance(item, dict) or not item.get("next_node_id"):
            continue
        label = str(item.get("label") or "").strip().lower()
        payload = metrics.get(label)
        if not isinstance(payload, dict) or not payload.get("next_node_id"):
            return True
    return False


def _apply_expected_evidence_to_metrics(
    metrics: dict[str, Any] | None,
    expected: Any,
) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return metrics
    refreshed: dict[str, Any] = {}
    for label in ("healthy", "unhealthy", "inconclusive"):
        payload = metrics.get(label)
        refreshed[label] = (
            dict(payload) if isinstance(payload, dict) else {
                "summary": None,
                "checks": [],
                "next_node_id": None,
                "next_node_title": None,
            }
        )
    parsed = parse_expected_outcome_evidence(expected)
    for label in ("healthy", "unhealthy", "inconclusive"):
        current = refreshed[label].get("summary")
        if current and not _is_generic_outcome_summary(current):
            continue
        if parsed.get(label):
            refreshed[label]["summary"] = parsed[label]
        elif label == "inconclusive":
            refreshed[label]["summary"] = _DEFAULT_INCONCLUSIVE_EVIDENCE
        elif not current:
            refreshed[label]["summary"] = f"Select {label} for this check."
    return refreshed


def enrich_troubleshoot_payload(
    payload: dict[str, Any],
    *,
    backend_url: str,
    variant: str = "prompt_a",
) -> dict[str, Any]:
    """Backfill node details, branch metrics, and images for sparse/legacy responses."""
    enriched = dict(payload)
    workflow = dict(enriched.get("workflow_state") or {})
    guided = dict(enriched.get("guided_question") or {})
    playbook_id = str(
        workflow.get("playbook_id") or enriched.get("selected_workflow_id") or ""
    ).strip()
    node_id = str(
        workflow.get("current_node_id") or guided.get("node_id") or ""
    ).strip()
    if node_id == "playbook_candidate_select":
        node_id = ""
    current_node = workflow.get("current_node") if isinstance(workflow.get("current_node"), dict) else {}
    runbook = workflow.get("runbook") if isinstance(workflow.get("runbook"), dict) else {}
    base = backend_url.rstrip("/")

    playbook_payload: dict[str, Any] = {}
    existing_metrics = (
        guided.get("branch_qualification_metrics")
        or current_node.get("branch_qualification_metrics")
    )
    existing_options = guided.get("branch_options")
    needs_playbook = playbook_id and (
        not workflow.get("playbook_title")
        or not current_node.get("title")
        or not existing_metrics
        or not guided.get("branch_qualification_metrics")
        or not guided.get("branch_options")
        or _options_missing_destinations(existing_options)
        or _metrics_missing_option_destinations(existing_metrics, existing_options)
    )
    if needs_playbook:
        try:
            viewer = _fetch_json(
                f"{base}/corpus/playbooks/{playbook_id}",
                params={"variant": variant},
            )
            playbook_payload = viewer.get("payload") if isinstance(viewer.get("payload"), dict) else {}
        except Exception:
            playbook_payload = {}
        if playbook_payload and not workflow.get("playbook_title"):
            workflow["playbook_title"] = playbook_payload.get("title")
        if playbook_payload and not workflow.get("case_id"):
            workflow["case_id"] = playbook_payload.get("case_id")
        if playbook_payload and not workflow.get("observed_entry_symptoms"):
            workflow["observed_entry_symptoms"] = list(
                playbook_payload.get("observed_entry_symptoms") or []
            )
        if playbook_payload and not workflow.get("user_facing_summary"):
            workflow["user_facing_summary"] = playbook_payload.get("user_facing_summary")
        if playbook_payload and node_id:
            node = next(
                (
                    item
                    for item in list(playbook_payload.get("nodes") or [])
                    if isinstance(item, dict) and str(item.get("node_id")) == node_id
                ),
                {},
            )
            if node:
                metrics = branch_qualification_metrics(node, runbook, playbook_payload)
                options = branch_options_from_node(node, playbook_payload)
                current_node = {
                    "node_id": node.get("node_id"),
                    "node_order": node.get("node_order"),
                    "node_type": node.get("node_type"),
                    "title": node.get("title"),
                    "intent": node.get("intent") or node.get("goal"),
                    "expected_or_observed_result": node.get("expected_or_observed_result"),
                    "stop_or_escalation_note": node.get("stop_or_escalation_note"),
                    "allowed_roles": list(node.get("allowed_roles") or []),
                    "branch_qualification_metrics": metrics,
                }
                workflow["current_node"] = current_node
                workflow["current_node_id"] = node_id
                if guided:
                    guided["branch_qualification_metrics"] = metrics
                    if options and (
                        not guided.get("branch_options")
                        or _options_missing_destinations(guided.get("branch_options"))
                    ):
                        guided["branch_options"] = options
                    if not guided.get("allowed_answers") and options:
                        guided["allowed_answers"] = [
                            str(item.get("label")) for item in options
                        ]
                    enriched["guided_question"] = guided

    procedure_id = str(runbook.get("procedure_id") or "").strip()
    steps = list(runbook.get("steps") or [])
    needs_step_images = (not steps and bool(procedure_id)) or any(
        isinstance(step, dict) and not list(step.get("images") or [])
        for step in steps
    )
    if procedure_id and (needs_step_images or not steps):
        try:
            if not steps:
                runbook_view = _fetch_json(f"{base}/corpus/runbooks/{procedure_id}")
                remote = (
                    runbook_view.get("payload")
                    if isinstance(runbook_view.get("payload"), dict)
                    else {}
                )
                if remote:
                    runbook = {
                        **runbook,
                        "title": runbook.get("title") or remote.get("title"),
                        "summary": runbook.get("summary") or remote.get("summary"),
                        "visual_references": list(
                            runbook.get("visual_references")
                            or remote.get("visual_references")
                            or []
                        ),
                        "steps": list(remote.get("steps") or []),
                    }
                    steps = list(runbook.get("steps") or [])
            image_payload = _fetch_json(f"{base}/corpus/runbooks/{procedure_id}/images")
            step_image_rows = list(image_payload.get("steps") or [])
            by_number = {
                str(item.get("step_number")): item
                for item in step_image_rows
                if isinstance(item, dict)
            }
            if steps:
                merged_steps = []
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    row = by_number.get(str(step.get("step_number"))) or {}
                    merged = dict(step)
                    if not merged.get("screens_or_images"):
                        merged["screens_or_images"] = list(row.get("screens_or_images") or [])
                    if not merged.get("images"):
                        images = list(row.get("images") or [])
                        if not images:
                            images = images_from_screen_refs(
                                list(merged.get("screens_or_images") or []),
                                backend_url=base,
                            )
                        merged["images"] = images
                    merged_steps.append(merged)
                runbook["steps"] = merged_steps
                workflow["runbook"] = runbook
                current_step = runbook.get("current_step")
                if isinstance(current_step, dict) and not current_step.get("images"):
                    match = next(
                        (
                            item
                            for item in merged_steps
                            if str(item.get("step_number"))
                            == str(current_step.get("step_number"))
                        ),
                        merged_steps[0] if merged_steps else None,
                    )
                    if isinstance(match, dict):
                        current_step = dict(current_step)
                        current_step["images"] = list(match.get("images") or [])
                        if not current_step.get("screens_or_images"):
                            current_step["screens_or_images"] = list(
                                match.get("screens_or_images") or []
                            )
                        runbook["current_step"] = current_step
                        workflow["runbook"] = runbook
        except Exception:
            pass

    expected = (
        (workflow.get("current_node") or {}).get("expected_or_observed_result")
        if isinstance(workflow.get("current_node"), dict)
        else None
    )
    for target in (workflow.get("current_node"), guided):
        if not isinstance(target, dict):
            continue
        metrics = target.get("branch_qualification_metrics")
        refreshed = _apply_expected_evidence_to_metrics(
            metrics if isinstance(metrics, dict) else None,
            expected or target.get("expected_or_observed_result"),
        )
        if isinstance(refreshed, dict):
            target["branch_qualification_metrics"] = refreshed
    if isinstance(workflow.get("current_node"), dict):
        workflow["current_node"] = workflow["current_node"]
    if guided:
        enriched["guided_question"] = guided

    enriched["canonical_images"] = []
    enriched["workflow_state"] = workflow
    if playbook_id and not enriched.get("selected_workflow_id"):
        enriched["selected_workflow_id"] = playbook_id
    return enriched


def images_from_screen_refs(
    refs: list[Any],
    *,
    backend_url: str,
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    base = backend_url.rstrip("/")
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        artifact_id = str(ref.get("artifact_id") or ref.get("image_id") or "").strip()
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        images.append(
            {
                "image_id": artifact_id,
                "caption": ref.get("what_to_look_at") or ref.get("description"),
                "title": ref.get("what_to_look_at") or artifact_id,
                "render_uri": f"{base}/images/{artifact_id}",
            }
        )
    return images


def render_canonical_images(
    images: list[dict[str, Any]] | None,
    *,
    backend_url: str,
    heading: str | None = "**Reference images**",
    as_expander: bool = True,
    expanded: bool = False,
) -> None:
    if not images:
        return
    label = (heading or "Reference images").replace("**", "").strip() or "Reference images"
    container = st.expander(label, expanded=expanded) if as_expander else st.container()
    base = backend_url.rstrip("/")
    with container:
        if not as_expander and heading:
            st.markdown(heading)
        for image in images:
            if not isinstance(image, dict):
                continue
            title = str(
                image.get("caption")
                or image.get("title")
                or image.get("image_id")
                or "Screenshot"
            )
            image_id = str(image.get("image_id") or "").strip()
            candidates = []
            if image_id:
                candidates.append(f"{base}/images/{image_id}")
            direct = str(image.get("render_uri") or image.get("storage_uri") or "").strip()
            if direct and direct not in candidates:
                candidates.append(direct)
            loaded = False
            last_status = "no URI"
            for uri in candidates:
                try:
                    response = requests.get(uri, timeout=45, allow_redirects=True)
                    last_status = str(response.status_code)
                    if response.ok and response.content:
                        st.image(response.content, caption=title, use_container_width=True)
                        loaded = True
                        break
                except Exception as exc:
                    last_status = str(exc)
                    continue
            if not loaded:
                st.caption(f"{title} — unavailable ({last_status})")


def merge_runbook_step_images(
    runbook: dict[str, Any],
    *,
    backend_url: str,
    image_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(runbook)
    steps = [step for step in list(merged.get("steps") or []) if isinstance(step, dict)]
    by_number: dict[str, dict[str, Any]] = {}
    if isinstance(image_payload, dict):
        for item in list(image_payload.get("steps") or []):
            if isinstance(item, dict):
                by_number[str(item.get("step_number"))] = item
    if not steps:
        return merged
    out_steps: list[dict[str, Any]] = []
    for step in steps:
        row = by_number.get(str(step.get("step_number"))) or {}
        item = dict(step)
        if not item.get("screens_or_images"):
            item["screens_or_images"] = list(row.get("screens_or_images") or [])
        if not item.get("images"):
            images = list(row.get("images") or [])
            if not images:
                images = images_from_screen_refs(
                    list(item.get("screens_or_images") or []),
                    backend_url=backend_url,
                )
            item["images"] = images
        out_steps.append(item)
    merged["steps"] = out_steps
    return merged


def load_runbook_with_images(backend_url: str, procedure_id: str) -> dict[str, Any]:
    procedure_id = str(procedure_id or "").strip()
    if not procedure_id:
        return {}
    base = backend_url.rstrip("/")
    try:
        viewer = _fetch_json(f"{base}/corpus/runbooks/{procedure_id}")
    except Exception:
        return {}
    remote = viewer.get("payload") if isinstance(viewer.get("payload"), dict) else {}
    if not remote:
        return {}
    runbook = {
        "procedure_id": remote.get("procedure_id") or procedure_id,
        "title": remote.get("title"),
        "summary": remote.get("summary"),
        "when_to_use": remote.get("when_to_use"),
        "not_for": list(remote.get("not_for") or []),
        "safety_notes": list(remote.get("safety_notes") or []),
        "access_or_tools_needed": list(remote.get("access_or_tools_needed") or []),
        "role_required": remote.get("role_required"),
        "visual_references": list(remote.get("visual_references") or []),
        "steps": list(remote.get("steps") or []),
    }
    try:
        image_payload = _fetch_json(f"{base}/corpus/runbooks/{procedure_id}/images")
    except Exception:
        image_payload = {}
    return merge_runbook_step_images(
        runbook,
        backend_url=base,
        image_payload=image_payload if isinstance(image_payload, dict) else {},
    )


def render_runbook_panel(
    runbook: dict[str, Any] | None,
    *,
    backend_url: str,
    expanded: bool = False,
    load_images: bool = True,
    heading_prefix: str = "Runbook",
    score: float | None = None,
    detail_level: str = "full",
) -> None:
    runbook = runbook if isinstance(runbook, dict) else {}
    if not (
        runbook.get("title") or runbook.get("procedure_id") or runbook.get("steps")
    ):
        return
    title = runbook.get("title") or runbook.get("procedure_id")
    heading = f"{heading_prefix} — {title}"
    if score is not None:
        heading = f"{heading} · {float(score):.4f}"
    with st.expander(heading, expanded=expanded):
        if runbook.get("summary"):
            st.write(str(runbook.get("summary")))
        if runbook.get("when_to_use"):
            st.caption(f"When to use: {runbook.get('when_to_use')}")
        if runbook.get("procedure_id"):
            st.caption(f"Procedure: `{runbook.get('procedure_id')}`")
        steps = [step for step in list(runbook.get("steps") or []) if isinstance(step, dict)]
        if detail_level != "full":
            if steps:
                st.caption(f"{len(steps)} documented steps available")
                preview = steps[0]
                if preview.get("title"):
                    st.caption(f"Starts with: {preview.get('title')}")
            visuals = list(runbook.get("visual_references") or [])
            if visuals and load_images:
                st.caption(f"{len(visuals)} visual reference(s)")
            return
        not_for = list(runbook.get("not_for") or [])
        if not_for:
            st.markdown("**Not for**")
            for item in not_for:
                st.write(f"- {item}")
        safety = list(runbook.get("safety_notes") or [])
        if safety:
            st.markdown("**Safety notes**")
            for item in safety:
                st.write(f"- {item}")
        tools = list(runbook.get("access_or_tools_needed") or [])
        if tools:
            st.caption("Tools/access: " + ", ".join(str(item) for item in tools))
        if runbook.get("role_required"):
            st.caption(f"Role required: {runbook.get('role_required')}")
        visuals = list(runbook.get("visual_references") or [])
        if visuals:
            st.markdown("**Visual references**")
            for ref in visuals:
                if not isinstance(ref, dict):
                    continue
                level = ref.get("required_level") or ""
                desc = ref.get("description") or ref.get("artifact_id")
                st.caption(f"- [{level}] {desc}" if level else f"- {desc}")
        current = runbook.get("current_step") or {}
        if steps:
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_label = step.get("step_number")
                heading_step = step.get("title") or "Step"
                if step_label is not None:
                    st.markdown(f"**Step {step_label}** — {heading_step}")
                else:
                    st.markdown(f"**{heading_step}**")
                if step.get("purpose"):
                    st.caption(str(step.get("purpose")))
                if step.get("instruction"):
                    st.write(step.get("instruction"))
                if step.get("expected_result"):
                    st.caption(f"Expected: {step.get('expected_result')}")
                if step.get("healthy_condition"):
                    st.caption(f"Healthy: {step.get('healthy_condition')}")
                if step.get("failure_condition"):
                    st.caption(f"Unhealthy: {step.get('failure_condition')}")
                for stop in list(step.get("stop_or_escalate_if") or []):
                    st.caption(f"Stop/escalate: {stop}")
                if not load_images:
                    continue
                step_images = list(step.get("images") or [])
                if not step_images:
                    step_images = images_from_screen_refs(
                        list(step.get("screens_or_images") or []),
                        backend_url=backend_url,
                    )
                if step_images:
                    render_canonical_images(
                        step_images,
                        backend_url=backend_url,
                        heading="Step images",
                        as_expander=True,
                        expanded=False,
                    )
                else:
                    for ref in list(step.get("screens_or_images") or []):
                        if not isinstance(ref, dict):
                            continue
                        note = ref.get("what_to_look_at") or ref.get("artifact_id")
                        if note:
                            st.caption(f"Screen ref: {note}")
        elif current.get("instruction") or current.get("title"):
            step_label = current.get("step_number")
            heading_step = current.get("title") or "Current step"
            if step_label is not None:
                st.markdown(f"**Step {step_label}** — {heading_step}")
            else:
                st.markdown(f"**{heading_step}**")
            if current.get("instruction"):
                st.write(current.get("instruction"))
            if current.get("expected_result"):
                st.caption(f"Expected: {current.get('expected_result')}")
            if current.get("healthy_condition"):
                st.caption(f"Healthy: {current.get('healthy_condition')}")
            if current.get("failure_condition"):
                st.caption(f"Unhealthy: {current.get('failure_condition')}")
            if load_images:
                current_images = list(current.get("images") or [])
                if not current_images:
                    current_images = images_from_screen_refs(
                        list(current.get("screens_or_images") or []),
                        backend_url=backend_url,
                    )
                if current_images:
                    render_canonical_images(
                        current_images, backend_url=backend_url, heading=None
                    )


def _friendly_metadata_lines(metadata: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    preferred = (
        ("category", "Category"),
        ("context_type", "Type"),
        ("topic", "Topic"),
        ("system", "System"),
        ("component", "Component"),
        ("source", "Source"),
        ("source_title", "Source"),
        ("audience", "Audience"),
    )
    seen: set[str] = set()
    for key, label in preferred:
        value = metadata.get(key)
        if value is None or value == "" or key in seen:
            continue
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(item) for item in value if str(item).strip())
        else:
            text = str(value).strip()
        if not text or text.lower() in {key.lower(), "n/a", "none"}:
            continue
        seen.add(key)
        lines.append(f"{label}: {text}")
    return lines


def render_operational_context_panel(
    hit: dict[str, Any] | None,
    *,
    expanded: bool = False,
) -> None:
    hit = hit if isinstance(hit, dict) else {}
    metadata = (
        hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
    )
    title = str(
        hit.get("title")
        or metadata.get("title")
        or hit.get("source_record_id")
        or "Operational context"
    ).strip()
    score = hit.get("combined_score")
    heading = f"Operational context — {title}"
    if score is not None:
        heading = f"{heading} · {float(score):.4f}"
    with st.expander(heading, expanded=expanded):
        body = str(
            hit.get("body")
            or hit.get("excerpt")
            or hit.get("snippet")
            or metadata.get("summary")
            or metadata.get("text")
            or ""
        ).strip()
        if body:
            st.write(body)
        for line in _friendly_metadata_lines(metadata):
            st.caption(line)
        source_id = str(hit.get("source_record_id") or "").strip()
        if source_id and source_id != title:
            st.caption(f"Record: `{source_id}`")


def post_troubleshoot(
    backend_url: str,
    *,
    session_id: str,
    user_message: str,
    playbook_variant: str,
    operator_role: str | None = None,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "user_message": user_message,
        "playbook_variant": playbook_variant,
    }
    if operator_role:
        payload["operator_role"] = operator_role
    response = requests.post(f"{backend_url.rstrip('/')}/troubleshoot", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def post_retrieve(
    backend_url: str,
    *,
    query: str,
    session_id: str | None,
    playbook_variant: str,
    record_types: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "session_id": session_id,
        "playbook_variant": playbook_variant,
        "top_k": top_k,
    }
    if record_types is not None:
        payload["record_types"] = record_types
    response = requests.post(f"{backend_url.rstrip('/')}/retrieve", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def get_corpus_status(backend_url: str) -> dict[str, Any]:
    try:
        response = requests.get(f"{backend_url.rstrip('/')}/corpus/status", timeout=30)
    except requests.RequestException as exc:
        return {"ok": False, "source": "unknown", "error": str(exc)}
    if not response.ok:
        return {"ok": False, "source": "unknown", "error": response.text}
    return response.json()


def get_interactions(backend_url: str, session_id: str, *, surface: str = "troubleshoot") -> list[dict[str, Any]]:
    prefix = "/troubleshoot" if surface == "troubleshoot" else "/retrieve"
    response = requests.get(
        f"{backend_url.rstrip('/')}{prefix}/sessions/{session_id}/interactions",
        timeout=60,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    return list(payload.get("interactions") or [])


def get_playbook_viewer(backend_url: str, playbook_id: str, variant: str) -> dict[str, Any]:
    response = requests.get(
        f"{backend_url.rstrip('/')}/corpus/playbooks/{playbook_id}",
        params={"variant": variant},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def get_runbook_viewer(backend_url: str, procedure_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{backend_url.rstrip('/')}/corpus/runbooks/{procedure_id}",
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
