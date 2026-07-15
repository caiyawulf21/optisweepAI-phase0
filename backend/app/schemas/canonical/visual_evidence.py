from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ImageCategory = Literal[
    "rms_screen",
    "ignition_screen",
    "database_screen",
    "home_screen",
    "map_monitor_screen",
    "alarm_screen",
    "runtime_screen",
    "windows_services_screen",
    "api_client_screen",
    "workflow_step_visual",
    "other_ui",
    "non_ui_visual",
]

ImageVisualPurpose = Literal[
    "diagnostic_confirmation",
    "state_verification",
    "navigation_reference",
    "workflow_step_support",
    "evidence_reference",
    "other",
]

ScreenshotType = Literal[
    "navigation",
    "procedure_step",
    "healthy_state",
    "failure_state",
    "validation_state",
    "evidence",
]

EvidencePolarity = Literal[
    "positive",
    "negative",
    "neutral",
    "ambiguous",
]

ReviewStatus = Literal[
    "needs_review",
    "sme_reviewed",
    "approved",
    "approved_for_workflow",
    "rejected",
    "deprecated",
]


class VisualEvidence(BaseModel):
    primary_screenshot_refs: list[str] = Field(default_factory=list)
    supporting_screenshot_refs: list[str] = Field(default_factory=list)
    required_screenshot_types: list[str] = Field(default_factory=list)
    visual_region_hints: list[str] = Field(default_factory=list)
    screenshot_required: bool = False


class StepVisualEvidence(BaseModel):
    screenshot_required: bool = False
    screenshot_refs: list[str] = Field(default_factory=list)
    visual_region_hint: str | None = None
    screenshot_refs_detailed: list["StepScreenshotRef"] = Field(default_factory=list)


class StepScreenshotRef(BaseModel):
    screenshot_id: str
    usage: Literal[
        "navigation",
        "action_reference",
        "healthy_state",
        "failure_state",
        "validation_reference",
    ]


class VisualArtifact(BaseModel):
    artifact_id: str
    artifact_type: str
    source_path: str | None = None
    blob_ref: str | None = None
    incident_id: str | None = None
    ocr_text: str | None = None
    visual_summary: str | None = None
    linked_evidence_ids: list[str] = Field(default_factory=list)


class SourceArtifact(BaseModel):
    artifact_id: str
    source_document: str | None = None
    artifact_type: str
    original_path: str | None = None
    blob_ref: str | None = None
    incident_id: str | None = None
    retrieval_text: str | None = None


class CanonicalImage(BaseModel):
    image_id: str
    category: ImageCategory
    visual_purpose: ImageVisualPurpose = "other"
    evidence_polarity: EvidencePolarity = "neutral"
    screenshot_type: ScreenshotType | None = None
    title: str
    description: str
    use_case: str
    annotation_summary: str | None = None
    screen_name: str | None = None
    system_name: str | None = None
    normal_state_description: str | None = None
    abnormal_state_description: str | None = None
    observable_signals: list[str] = Field(default_factory=list)
    visual_elements: list[str] = Field(default_factory=list)
    navigation_context: str | None = None
    component: str | None = None
    issue_categories: list[str] = Field(default_factory=list)
    related_signals: list[str] = Field(default_factory=list)
    linked_incident_ids: list[str] = Field(default_factory=list)
    linked_workflow_ids: list[str] = Field(default_factory=list)
    linked_procedure_ids: list[str] = Field(default_factory=list)
    linked_step_ids: list[str] = Field(default_factory=list)
    observed_signals: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "needs_review"
    source_artifact_ids: list[str] = Field(default_factory=list)


class CanonicalImageAnnotation(BaseModel):
    source_artifact: SourceArtifact
    canonical_image: CanonicalImage
