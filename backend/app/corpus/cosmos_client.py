from __future__ import annotations

from typing import Any

from backend.app.corpus.models import CorpusIndex, EmbeddingRecord, RelationshipLink
from backend.app.corpus.publish_version import resolve_publish_version_id
from backend.app.corpus.settings import CorpusSettings, get_corpus_settings


class CosmosCorpusClient:
    def __init__(self, settings: CorpusSettings | None = None) -> None:
        self.settings = settings or get_corpus_settings()
        self._index: CorpusIndex | None = None
        self._publish_version_id = resolve_publish_version_id(self.settings)

    @property
    def publish_version_id(self) -> str:
        return self._publish_version_id

    @property
    def _use_sample_corpus(self) -> bool:
        return not self.settings.cosmos_configured

    def load_index(self, *, force: bool = False) -> CorpusIndex:
        if self._index is not None and not force:
            return self._index
        if self._use_sample_corpus:
            self._index = _sample_corpus_index(self._publish_version_id)
            return self._index
        self._index = CorpusIndex(
            publish_version_id=self._publish_version_id,
            embeddings=self._load_embeddings_from_cosmos(),
            links=self._load_links_from_cosmos(),
            symptom_cards=self._load_symptom_cards_from_cosmos(),
            gate_phrase_table=self._load_gate_phrase_table_from_cosmos(),
        )
        return self._index

    def load_embedding_index(
        self,
        version: str | None = None,
        record_types: set[str] | None = None,
    ) -> list[EmbeddingRecord]:
        version_id = version or self._publish_version_id
        index = self.load_index()
        if index.publish_version_id != version_id:
            index = self.load_index(force=True)
        records = index.embeddings
        if record_types:
            records = [item for item in records if item.record_type in record_types]
        return records

    def get_playbook(self, playbook_id: str, variant: str = "prompt_a") -> dict[str, Any] | None:
        if self._use_sample_corpus:
            return _sample_playbook(playbook_id, variant)
        payload = self._load_playbook_document(playbook_id, variant)
        if payload is not None:
            return payload
        return self._load_playbook_by_case_hint(playbook_id, variant)

    def find_playbook_for_case(self, case_id: str, variant: str = "prompt_a") -> tuple[str, dict[str, Any]] | None:
        if self._use_sample_corpus and case_id == "228086":
            playbook_id = "playbook_incident_228086_site_wide_motion_stoppage_service_recovery"
            payload = _sample_playbook(playbook_id, variant)
            return (playbook_id, payload) if payload else None
        container = (
            self.settings.container_playbooks_a
            if variant == "prompt_a"
            else self.settings.container_playbooks_b
        )
        rows = self._query(
            container,
            """
            SELECT c.record_id, c.payload FROM c
            WHERE c.publish_version_id = @version
              AND c.doc_type = 'playbook'
              AND (c.payload.case_id = @case_id OR CONTAINS(c.record_id, @case_id))
            """,
            [
                {"name": "@version", "value": self._publish_version_id},
                {"name": "@case_id", "value": case_id},
            ],
        )
        if not rows:
            return None
        row = rows[0]
        record_id = str(row.get("record_id") or "")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            return None
        return record_id, payload

    def _load_playbook_document(self, playbook_id: str, variant: str) -> dict[str, Any] | None:
        container = (
            self.settings.container_playbooks_a
            if variant == "prompt_a"
            else self.settings.container_playbooks_b
        )
        rows = self._query(
            container,
            """
            SELECT c.payload FROM c
            WHERE c.publish_version_id = @version
              AND c.doc_type = 'playbook'
              AND c.record_id = @playbook_id
            """,
            [
                {"name": "@version", "value": self._publish_version_id},
                {"name": "@playbook_id", "value": playbook_id},
            ],
        )
        if not rows:
            return None
        payload = rows[0].get("payload")
        return payload if isinstance(payload, dict) else None

    def _load_playbook_by_case_hint(self, playbook_id: str, variant: str) -> dict[str, Any] | None:
        import re

        match = re.search(r"(\d{5,6})", playbook_id)
        if not match:
            return None
        found = self.find_playbook_for_case(match.group(1), variant=variant)
        if not found:
            return None
        return found[1]

    def get_runbook(self, procedure_id: str) -> dict[str, Any] | None:
        if self._use_sample_corpus:
            return _sample_runbooks().get(procedure_id)
        rows = self._query(
            self.settings.container_runbooks,
            """
            SELECT c.payload FROM c
            WHERE c.publish_version_id = @version
              AND c.doc_type = 'runbook'
              AND c.record_id = @procedure_id
            """,
            [
                {"name": "@version", "value": self._publish_version_id},
                {"name": "@procedure_id", "value": procedure_id},
            ],
        )
        if not rows:
            return None
        payload = rows[0].get("payload")
        return payload if isinstance(payload, dict) else None

    def load_relationship_graph(self, version: str | None = None) -> list[RelationshipLink]:
        version_id = version or self._publish_version_id
        index = self.load_index()
        if index.publish_version_id != version_id:
            index = self.load_index(force=True)
        return list(index.links)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        if self._use_sample_corpus:
            return None
        rows = self._query(
            self.settings.container_source_artifacts,
            """
            SELECT c.retrieval_text, c.filter_metadata, c.source_refs
            FROM c
            WHERE c.publish_version_id = @version
              AND c.doc_type = 'rag_record'
              AND c.record_type = 'source_artifact'
              AND c.source_record_id = @artifact_id
            """,
            [
                {"name": "@version", "value": self._publish_version_id},
                {"name": "@artifact_id", "value": artifact_id},
            ],
        )
        return rows[0] if rows else None

    def resolve_runbooks_for_node(
        self,
        playbook_id: str,
        node_id: str,
        playbook_payload: dict[str, Any] | None = None,
    ) -> list[str]:
        payload = playbook_payload or self.get_playbook(
            playbook_id,
            variant=self.settings.default_playbook_variant,
        )
        ordered: list[str] = []
        seen: set[str] = set()

        def _add(procedure_id: Any) -> None:
            value = str(procedure_id or "").strip()
            if not value or value in seen:
                return
            seen.add(value)
            ordered.append(value)

        if payload:
            for node in payload.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                if str(node.get("node_id")) != node_id:
                    continue
                for procedure_id in list(node.get("resolved_runbook_ids") or []):
                    _add(procedure_id)
                runbook_links = list(node.get("runbook_links") or [])
                if runbook_links:
                    sorted_links = sorted(
                        [
                            link
                            for link in runbook_links
                            if isinstance(link, dict)
                        ],
                        key=lambda item: int(item.get("link_rank") or 999),
                    )
                    for link in sorted_links:
                        _add(link.get("procedure_id"))
                if ordered:
                    return ordered
        links = self.load_relationship_graph()
        matches = [
            link
            for link in links
            if link.link_type == "playbook_runbook"
            and link.source_record_id == f"{playbook_id}:{node_id}"
        ]
        matches.sort(key=lambda item: item.link_rank)
        for link in matches:
            _add(link.target_record_id)
        return ordered

    def resolve_runbook_for_node(
        self,
        playbook_id: str,
        node_id: str,
        playbook_payload: dict[str, Any] | None = None,
    ) -> str | None:
        resolved = self.resolve_runbooks_for_node(
            playbook_id,
            node_id,
            playbook_payload,
        )
        return resolved[0] if resolved else None

    def _load_symptom_cards_from_cosmos(self) -> dict[str, dict[str, Any]]:
        sql = """
            SELECT c.record_id, c.payload FROM c
            WHERE c.publish_version_id = @version AND c.doc_type = 'playbook'
        """
        params = [{"name": "@version", "value": self._publish_version_id}]
        cards: dict[str, dict[str, Any]] = {}
        for container in (
            self.settings.container_playbooks_a,
            self.settings.container_playbooks_b,
        ):
            for row in self._query(container, sql, params):
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                playbook_id = str(
                    payload.get("playbook_id") or row.get("record_id") or ""
                ).strip()
                if not playbook_id:
                    continue
                cards[playbook_id] = {
                    "playbook_id": playbook_id,
                    "case_id": payload.get("case_id"),
                    "title": payload.get("title"),
                    "observed_entry_symptoms": list(
                        payload.get("observed_entry_symptoms") or []
                    ),
                    "support_user_language_examples": list(
                        payload.get("support_user_language_examples") or []
                    ),
                    "affected_systems_or_components": list(
                        payload.get("affected_systems_or_components") or []
                    ),
                    "user_facing_summary": payload.get("user_facing_summary"),
                }
        return cards

    def _load_embeddings_from_cosmos(self) -> list[EmbeddingRecord]:
        embedding_sql = """
            SELECT c.id, c.record_type, c.source_record_id, c.embedded_text, c.retrieval_text,
                   c.summary, c.text, c.body, c.content, c.title, c.vector, c.embedding_model,
                   c.filter_metadata
            FROM c
            WHERE c.publish_version_id = @version AND c.doc_type = 'embedding'
        """
        # Operational context is published as rag_record + vector (not doc_type=embedding).
        context_sql = """
            SELECT c.id, c.record_type, c.source_record_id, c.embedded_text, c.retrieval_text,
                   c.summary, c.text, c.body, c.content, c.title, c.vector, c.embedding_model,
                   c.filter_metadata
            FROM c
            WHERE c.publish_version_id = @version
              AND c.doc_type = 'rag_record'
              AND c.record_type = 'operational_context'
              AND IS_DEFINED(c.vector)
              AND ARRAY_LENGTH(c.vector) > 0
        """
        params = [{"name": "@version", "value": self._publish_version_id}]
        records: list[EmbeddingRecord] = []
        for container in (
            self.settings.container_playbooks_a,
            self.settings.container_playbooks_b,
            self.settings.container_runbooks,
        ):
            for row in self._query(container, embedding_sql, params):
                records.append(self._row_to_embedding(row))
        for row in self._query(
            self.settings.container_operational_context, embedding_sql, params
        ):
            records.append(self._row_to_embedding(row))
        for row in self._query(
            self.settings.container_operational_context, context_sql, params
        ):
            records.append(self._row_to_embedding(row))
        return records

    @staticmethod
    def _row_to_embedding(row: dict[str, Any]) -> EmbeddingRecord:
        metadata = dict(row.get("filter_metadata") or {})
        title_candidates = [
            metadata.get("title"),
            metadata.get("topic"),
            metadata.get("heading"),
            metadata.get("section_title"),
            metadata.get("source_title"),
            row.get("title"),
        ]
        if not metadata.get("title"):
            for value in title_candidates:
                if isinstance(value, str) and value.strip():
                    metadata["title"] = value.strip()[:160]
                    break
            summary = str(row.get("summary") or "").strip()
            retrieval = str(row.get("retrieval_text") or "").strip()
            if not metadata.get("title") and summary:
                cut = summary.find(". ")
                metadata["title"] = (summary[:cut] if cut > 20 else summary)[:120].strip()
            if not metadata.get("title") and retrieval:
                cut = retrieval.find(". ")
                metadata["title"] = (retrieval[:cut] if cut > 20 else retrieval)[:120].strip()
        embedded = (
            str(row.get("embedded_text") or "").strip()
            or str(row.get("retrieval_text") or "").strip()
            or str(row.get("summary") or "").strip()
            or str(row.get("text") or "").strip()
            or str(row.get("body") or "").strip()
            or str(row.get("content") or "").strip()
            or str(row.get("title") or "").strip()
        )
        record_type = str(row.get("record_type") or "").strip()
        if not record_type and str(row.get("doc_type") or "") == "rag_record":
            record_type = "operational_context"
        return EmbeddingRecord(
            record_id=str(row.get("id") or ""),
            record_type=record_type,
            source_record_id=str(row.get("source_record_id") or ""),
            embedded_text=embedded,
            vector=[float(v) for v in row.get("vector") or []],
            embedding_model=str(row.get("embedding_model") or ""),
            filter_metadata=metadata,
        )

    def _load_links_from_cosmos(self) -> list[RelationshipLink]:
        sql = """
            SELECT c.links FROM c
            WHERE c.publish_version_id = @version AND c.doc_type = 'relationship_graph'
        """
        params = [{"name": "@version", "value": self._publish_version_id}]
        links: list[RelationshipLink] = []
        for row in self._query(self.settings.container_relationship_links, sql, params):
            for link in row.get("links") or []:
                if not isinstance(link, dict):
                    continue
                links.append(
                    RelationshipLink(
                        link_type=str(link.get("link_type") or ""),
                        source_record_id=str(link.get("source_record_id") or ""),
                        target_record_id=str(link.get("target_record_id") or ""),
                        link_confidence=str(link.get("link_confidence") or ""),
                        link_rank=int(link.get("link_rank") or 999),
                    )
                )
        return links

    def _load_gate_phrase_table_from_cosmos(self) -> dict[str, Any] | None:
        from backend.app.services.gate_phrase_loader import (
            GATE_PHRASE_DOC_ID,
            GATE_PHRASE_DOC_TYPE,
            normalize_gate_phrase_doc,
        )

        rows = self._query(
            self.settings.container_gate_phrase_tables,
            """
            SELECT * FROM c
            WHERE c.publish_version_id = @version
              AND c.doc_type = @doc_type
              AND (c.id = @id OR c.record_id = @id)
            """,
            [
                {"name": "@version", "value": self._publish_version_id},
                {"name": "@doc_type", "value": GATE_PHRASE_DOC_TYPE},
                {"name": "@id", "value": GATE_PHRASE_DOC_ID},
            ],
        )
        if not rows:
            return None
        maps = normalize_gate_phrase_doc(rows[0])
        return {
            "id": GATE_PHRASE_DOC_ID,
            "doc_type": GATE_PHRASE_DOC_TYPE,
            "publish_version_id": self._publish_version_id,
            "symptom_phrases": maps["symptom_phrases"],
            # Keep ingest field name for debugging / older readers.
            "legacy_signal_phrases": maps["symptom_phrases"],
            "canonical_signal_phrases": maps["canonical_signal_phrases"],
            "component_phrases": maps["component_phrases"],
        }

    def _query(
        self,
        container_name: str,
        sql: str,
        parameters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        from backend.app.repositories.cosmos_client import cosmos_container

        container = cosmos_container(container_name)
        return list(
            container.query_items(
                query=sql,
                parameters=parameters,
                partition_key=self._publish_version_id,
            )
        )


def _sample_playbook(playbook_id: str, variant: str = "prompt_a") -> dict[str, Any] | None:
    del variant
    canonical_id = "playbook_incident_228086_site_wide_motion_stoppage_service_recovery"
    if playbook_id != canonical_id and "228086" not in playbook_id:
        return None
    return {
        "playbook_id": canonical_id,
        "case_id": "228086",
        "title": "Site-wide robotic motion stoppage service recovery",
        "observed_entry_symptoms": [
            "AGVs stopped",
            "nothing is moving on site",
            "site-wide robotic motion stoppage",
            "tipper flow stopped",
        ],
        "support_user_language_examples": [
            "AGVs stopped",
            "AGVs are stopped",
            "robots stopped",
            "nothing is moving",
            "AGVs aren't moving",
            "no RMS alarms",
            "rms showing no alarms",
            "AGVs stopped and nothing is moving on site",
        ],
        "affected_systems_or_components": ["AGV", "RMS", "OptiSweep service"],
        "user_facing_summary": "Use this playbook when robotic motion appears stopped across the site.",
        "nodes": [
            {
                "node_id": "node_1",
                "title": "Confirm site-wide stoppage and abnormal control-system presentation",
                "intent": "Confirm whether the report is a site-wide AGV stoppage pattern or a localized issue.",
                "resolved_runbook_ids": ["proc_confirm_site_wide_stoppage"],
                "decision_outcomes": [
                    {
                        "outcome_label": "healthy",
                        "descriptor": "Site-wide stoppage pattern is confirmed and ready for the recovery branch.",
                        "next_node_id": "node_6",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "unhealthy",
                        "descriptor": "The evidence points to a narrower or different fault pattern.",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "inconclusive",
                        "descriptor": "The breadth of the stoppage cannot be confirmed yet.",
                        "source": "playbook_expected_result",
                    },
                ],
                "branches": [{"outcome": "healthy", "next_node_id": "node_6"}],
            },
            {
                "node_id": "node_6",
                "title": "Check for residual AGV desynchronization after service recovery",
                "intent": "Determine whether AGVs remain out of sync after service recovery.",
                "resolved_runbook_ids": ["proc_rms_active_faults"],
                "decision_outcomes": [
                    {
                        "outcome_label": "healthy",
                        "descriptor": "AGV state is synchronized and RMS does not show active AGV faults.",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "unhealthy",
                        "descriptor": "Residual AGV desynchronization or active RMS faults remain.",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "inconclusive",
                        "descriptor": "RMS or AGV state cannot be confirmed.",
                        "source": "playbook_expected_result",
                    },
                ],
            },
        ],
    }


def _sample_runbooks() -> dict[str, dict[str, Any]]:
    return {
        "proc_confirm_site_wide_stoppage": {
            "procedure_id": "proc_confirm_site_wide_stoppage",
            "title": "Confirm site-wide robotic stoppage",
            "steps": [
                {
                    "step_number": 1,
                    "instruction": "Check RMS and the operator HMI for site-wide AGV stoppage indicators.",
                    "expected_result": "The issue is confirmed as site-wide or narrowed to a local fault.",
                    "healthy_condition": "Site-wide stoppage is confirmed.",
                    "failure_condition": "Only one robot, zone, or station is affected.",
                }
            ],
        },
        "proc_rms_active_faults": {
            "procedure_id": "proc_rms_active_faults",
            "title": "Check RMS for active AGV faults",
            "steps": [
                {
                    "step_number": 1,
                    "instruction": "Open RMS, review active AGV faults, and compare robot state with the HMI after service recovery.",
                    "expected_result": "No residual AGV desynchronization remains after recovery.",
                    "healthy_condition": "RMS shows no active AGV faults and robot state is synchronized.",
                    "failure_condition": "RMS still shows active AGV faults or desynchronized robot state.",
                }
            ],
        },
    }


def _sample_corpus_index(publish_version_id: str) -> CorpusIndex:
    from backend.app.retrieval.hybrid_retriever import mock_embed

    playbook_id = "playbook_incident_228086_site_wide_motion_stoppage_service_recovery"
    playbook = _sample_playbook(playbook_id) or {}
    symptoms = list(playbook.get("observed_entry_symptoms") or [])
    examples = list(playbook.get("support_user_language_examples") or [])
    playbook_text = " ".join(
        [
            str(playbook.get("title") or ""),
            str(playbook.get("user_facing_summary") or ""),
            " ".join(symptoms),
            " ".join(examples),
        ]
    )
    runbook_text = (
        "Check RMS for active AGV faults. Review RMS alarms, active faults, robot state, "
        "and AGV desynchronization after OptiSweep service recovery."
    )
    software_stack_text = (
        "OptiSweep software service stack: OptiSweep / WCS orchestrates robotic sortation, "
        "RMS provides fleet and AGV status views, Ignition hosts gateway and HMI pages, and "
        "support uses Windows Services plus Event Viewer when validating service health."
    )
    blank_rms_text = (
        "Blank RMS pages can mean the overview control failed to render, RMS access is blocked, "
        "or the control service / gateway path is unhealthy. Corroborate with site interview and "
        "Windows Event Viewer before assuming a single-robot fault."
    )
    return CorpusIndex(
        publish_version_id=publish_version_id,
        embeddings=[
            EmbeddingRecord(
                record_id=f"playbook_prompt_a:{playbook_id}",
                record_type="playbook_prompt_a",
                source_record_id=playbook_id,
                embedded_text=playbook_text,
                vector=mock_embed(playbook_text),
                embedding_model="mock-hash-v1",
                filter_metadata={
                    "title": str(playbook.get("title") or ""),
                    "case_id": "228086",
                },
            ),
            EmbeddingRecord(
                record_id="runbook:proc_rms_active_faults",
                record_type="canonical_runbook",
                source_record_id="proc_rms_active_faults",
                embedded_text=runbook_text,
                vector=mock_embed(runbook_text),
                embedding_model="mock-hash-v1",
                filter_metadata={"title": "Check RMS for active AGV faults"},
            ),
            EmbeddingRecord(
                record_id="operational_context:optisweep_software_stack",
                record_type="operational_context",
                source_record_id="ctx_optisweep_software_stack",
                embedded_text=software_stack_text,
                vector=mock_embed(software_stack_text),
                embedding_model="mock-hash-v1",
                filter_metadata={
                    "title": "OptiSweep software/service stack",
                    "topic": "software_stack",
                    "category": "training",
                },
            ),
            EmbeddingRecord(
                record_id="operational_context:blank_rms_context",
                record_type="operational_context",
                source_record_id="ctx_blank_rms_context",
                embedded_text=blank_rms_text,
                vector=mock_embed(blank_rms_text),
                embedding_model="mock-hash-v1",
                filter_metadata={
                    "title": "Blank RMS page context",
                    "topic": "rms_ui",
                    "category": "training",
                },
            ),
        ],
        links=[
            RelationshipLink(
                link_type="playbook_runbook",
                source_record_id=f"{playbook_id}:node_1",
                target_record_id="proc_confirm_site_wide_stoppage",
                link_confidence="high",
                link_rank=1,
            ),
            RelationshipLink(
                link_type="playbook_runbook",
                source_record_id=f"{playbook_id}:node_6",
                target_record_id="proc_rms_active_faults",
                link_confidence="high",
                link_rank=1,
            ),
        ],
        symptom_cards={
            playbook_id: {
                "playbook_id": playbook_id,
                "case_id": "228086",
                "title": playbook.get("title"),
                "observed_entry_symptoms": symptoms,
                "support_user_language_examples": examples,
                "affected_systems_or_components": list(
                    playbook.get("affected_systems_or_components") or []
                ),
                "user_facing_summary": playbook.get("user_facing_summary"),
            }
        },
    )
