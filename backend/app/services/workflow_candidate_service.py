from __future__ import annotations

from collections import defaultdict

from backend.app.schemas.procedure import EvidenceReference
from backend.app.schemas.workflow_candidate import ReusableWorkflowDefinition, WorkflowCandidate


class WorkflowCandidateService:
    def merge_candidates(self, candidates: list[WorkflowCandidate]) -> list[ReusableWorkflowDefinition]:
        groups: dict[tuple, list[WorkflowCandidate]] = defaultdict(list)
        for candidate in candidates:
            groups[self._merge_key(candidate)].append(candidate)

        definitions: list[ReusableWorkflowDefinition] = []
        for grouped_candidates in groups.values():
            if not self._has_evidence_backed_overlap(grouped_candidates):
                continue
            first = grouped_candidates[0]
            definitions.append(
                ReusableWorkflowDefinition(
                    workflow_id=first.workflow_id,
                    title=first.title,
                    issue_category=first.issue_category,
                    operational_intent=first.operational_intent,
                    required_signals=sorted({signal for candidate in grouped_candidates for signal in candidate.required_signals}),
                    procedure_refs=sorted({ref for candidate in grouped_candidates for ref in candidate.procedure_refs}),
                    related_incidents=sorted({incident for candidate in grouped_candidates for incident in candidate.related_incidents}),
                    source_candidate_ids=[candidate.workflow_id for candidate in grouped_candidates],
                    evidence_refs=self._dedupe_evidence([ref for candidate in grouped_candidates for ref in candidate.evidence_refs]),
                    escalation_conditions=sorted({condition for candidate in grouped_candidates for condition in candidate.escalation_conditions}),
                    status="draft",
                )
            )
        return definitions

    def _merge_key(self, candidate: WorkflowCandidate) -> tuple:
        return (
            candidate.workflow_id,
            candidate.issue_category,
            tuple(sorted(candidate.required_signals)),
            tuple(sorted(candidate.procedure_refs)),
        )

    def _has_evidence_backed_overlap(self, candidates: list[WorkflowCandidate]) -> bool:
        incident_ids = {incident for candidate in candidates for incident in candidate.related_incidents}
        evidence_incidents = {ref.incident_id for candidate in candidates for ref in candidate.evidence_refs}
        evidence_sources = {
            (ref.evidence_id, ref.source_artifact_id)
            for candidate in candidates
            for ref in candidate.evidence_refs
            if ref.evidence_id or ref.source_artifact_id
        }
        return len(incident_ids) >= 2 and incident_ids.issubset(evidence_incidents) and len(evidence_sources) >= 2

    def _dedupe_evidence(self, refs: list[EvidenceReference]) -> list[EvidenceReference]:
        seen: set[tuple[str, str]] = set()
        deduped: list[EvidenceReference] = []
        for ref in refs:
            key = (ref.incident_id, ref.evidence_id)
            if key not in seen:
                seen.add(key)
                deduped.append(ref)
        return deduped
