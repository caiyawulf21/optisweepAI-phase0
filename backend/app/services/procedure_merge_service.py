from __future__ import annotations

import re
from collections import defaultdict

from backend.app.schemas.procedure import EvidenceReference, MergeReport, ProcedureCandidate, ReusableProcedure


class ProcedureMergeService:
    def merge_candidates(self, candidates: list[ProcedureCandidate]) -> tuple[list[ReusableProcedure], list[MergeReport]]:
        groups: dict[tuple, list[ProcedureCandidate]] = defaultdict(list)
        for candidate in candidates:
            groups[self._merge_key(candidate)].append(candidate)

        reusable: list[ReusableProcedure] = []
        reports: list[MergeReport] = []
        for grouped_candidates in groups.values():
            if not self._has_evidence_backed_overlap(grouped_candidates):
                continue
            merged = self._build_reusable(grouped_candidates)
            reusable.append(merged)
            reports.append(
                MergeReport(
                    merge_id=f"merge_{merged.procedure_id}",
                    reusable_id=merged.procedure_id,
                    source_candidate_ids=merged.source_candidate_ids,
                    related_incidents=merged.related_incidents,
                    reasons=[
                        "Shared operational intent",
                        "Shared role",
                        "Shared supported steps",
                        "Shared validation and escalation conditions",
                        "Evidence-backed overlap across multiple incidents",
                    ],
                )
            )
        return reusable, reports

    def _merge_key(self, candidate: ProcedureCandidate) -> tuple:
        return (
            self._normalize(candidate.operational_intent),
            self._normalize(candidate.role_required),
            tuple(self._normalize(step.instruction) for step in candidate.steps),
            tuple(sorted(self._normalize(check) for check in candidate.validation_checks)),
            tuple(sorted(self._normalize(condition) for condition in candidate.escalation_conditions)),
        )

    def _has_evidence_backed_overlap(self, candidates: list[ProcedureCandidate]) -> bool:
        if len(candidates) < 2:
            return False
        incident_ids = {incident for candidate in candidates for incident in candidate.related_incidents}
        evidence_incidents = {ref.incident_id for candidate in candidates for ref in candidate.evidence_refs}
        evidence_sources = {
            (ref.evidence_id, ref.source_artifact_id)
            for candidate in candidates
            for ref in candidate.evidence_refs
            if ref.evidence_id or ref.source_artifact_id
        }
        return (
            len(incident_ids) >= 2
            and incident_ids.issubset(evidence_incidents)
            and len(evidence_sources) >= len(candidates)
            and all(candidate.steps for candidate in candidates)
        )

    def _build_reusable(self, candidates: list[ProcedureCandidate]) -> ReusableProcedure:
        first = candidates[0]
        related_incidents = sorted({incident for candidate in candidates for incident in candidate.related_incidents})
        evidence_refs = self._dedupe_evidence([ref for candidate in candidates for ref in candidate.evidence_refs])
        return ReusableProcedure(
            procedure_id=self._versioned_id(first.operational_intent),
            title=first.title,
            operational_intent=first.operational_intent,
            role_required=first.role_required,
            support_safe=first.support_safe,
            steps=first.steps,
            validation_checks=first.validation_checks,
            escalation_conditions=first.escalation_conditions,
            related_incidents=related_incidents,
            source_candidate_ids=[candidate.procedure_id for candidate in candidates],
            evidence_refs=evidence_refs,
            status="needs_sme_review",
        )

    def _dedupe_evidence(self, refs: list[EvidenceReference]) -> list[EvidenceReference]:
        seen: set[tuple[str, str]] = set()
        deduped: list[EvidenceReference] = []
        for ref in refs:
            key = (ref.incident_id, ref.evidence_id)
            if key not in seen:
                seen.add(key)
                deduped.append(ref)
        return deduped

    def _versioned_id(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        if not slug.endswith("_v1"):
            slug = f"{slug}_v1"
        return slug

    def _normalize(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())
