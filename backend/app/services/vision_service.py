from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable


logger = logging.getLogger(__name__)

OCR_TEXT_LIMIT = 1200
TAG_LIMIT = 8


@dataclass
class VisionAnalysis:
    provider: str = "azure_ai_vision"
    caption: str = ""
    ocr_text: str = ""
    tags: list[str] = field(default_factory=list)
    raw_ref: str | None = None
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "caption": self.caption,
            "ocr_text": self.ocr_text,
            "tags": list(self.tags),
            "raw_ref": self.raw_ref,
        }


def compose_image_summary(
    *,
    user_description: str | None,
    vision: VisionAnalysis | None,
) -> str:
    """Deterministic fusion of Computer Vision output and user description."""
    description = " ".join(str(user_description or "").split()).strip()
    caption = ""
    ocr = ""
    tags: list[str] = []
    vision_failed = vision is None or vision.status == "failed"
    if vision is not None and vision.status != "failed":
        caption = " ".join(str(vision.caption or "").split()).strip()
        ocr = " ".join(str(vision.ocr_text or "").split()).strip()
        if len(ocr) > OCR_TEXT_LIMIT:
            ocr = ocr[: OCR_TEXT_LIMIT - 3].rstrip() + "..."
        tags = [str(tag).strip() for tag in list(vision.tags or []) if str(tag).strip()][
            :TAG_LIMIT
        ]

    parts: list[str] = []
    if description:
        parts.append(f"User description: {description}.")
    else:
        parts.append("User description: (none provided).")

    if vision_failed:
        if description:
            parts.append(
                "Computer Vision analysis failed; using the user description only."
            )
            return " ".join(parts)
        return "Computer Vision analysis failed and no user description was provided."

    if caption:
        parts.append(f"Image appears to show: {caption}.")
    if ocr:
        parts.append(f"Visible text includes: {ocr}.")
    if tags:
        parts.append(f"Detected tags: {', '.join(tags)}.")
    if not caption and not ocr and not tags:
        parts.append("Computer Vision returned no caption, OCR text, or tags.")
    return " ".join(parts)


class AzureComputerVisionClient:
    """Thin Azure AI Vision Image Analysis client (caption + read)."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        key: str | None = None,
        api_version: str | None = None,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        from backend.app.config.settings import get_settings

        settings = get_settings()
        self.endpoint = (endpoint if endpoint is not None else settings.vision_endpoint) or ""
        self.key = (key if key is not None else settings.vision_key) or ""
        self.api_version = api_version or settings.vision_api_version
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.endpoint.strip() and self.key.strip())

    def analyze_bytes(self, image_bytes: bytes, content_type: str = "application/octet-stream") -> VisionAnalysis:
        if not image_bytes:
            return VisionAnalysis(status="failed")
        if not self.configured:
            logger.warning("azure_vision_not_configured")
            return VisionAnalysis(status="failed")
        try:
            return self._analyze(image_bytes, content_type)
        except Exception:
            logger.warning("azure_vision_analyze_failed", exc_info=True)
            return VisionAnalysis(status="failed")

    def _analyze(self, image_bytes: bytes, content_type: str) -> VisionAnalysis:
        import urllib.request

        base = self.endpoint.rstrip("/")
        url = (
            f"{base}/computervision/imageanalysis:analyze"
            f"?api-version={self.api_version}&features=caption,read,tags"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": content_type or "application/octet-stream",
        }
        if self._transport is not None:
            payload = self._transport(url, image_bytes, headers)
        else:
            request = urllib.request.Request(
                url, data=image_bytes, headers=headers, method="POST"
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                import json

                payload = json.loads(response.read().decode("utf-8"))
        return self._parse_payload(payload)

    def _parse_payload(self, payload: dict[str, Any]) -> VisionAnalysis:
        caption = ""
        caption_result = payload.get("captionResult") or payload.get("caption") or {}
        if isinstance(caption_result, dict):
            caption = str(caption_result.get("text") or "").strip()

        tags: list[str] = []
        tags_result = payload.get("tagsResult") or payload.get("tags") or {}
        values = []
        if isinstance(tags_result, dict):
            values = list(tags_result.get("values") or tags_result.get("tags") or [])
        elif isinstance(tags_result, list):
            values = tags_result
        for item in values:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("text") or "").strip()
            else:
                name = str(item or "").strip()
            if name and name not in tags:
                tags.append(name)

        ocr_chunks: list[str] = []
        read_result = payload.get("readResult") or {}
        blocks = list(read_result.get("blocks") or []) if isinstance(read_result, dict) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for line in list(block.get("lines") or []):
                if isinstance(line, dict):
                    text = str(line.get("text") or "").strip()
                    if text:
                        ocr_chunks.append(text)
        # Older shape: analyzeResult.readResults
        analyze = payload.get("analyzeResult") or {}
        if isinstance(analyze, dict) and not ocr_chunks:
            for page in list(analyze.get("readResults") or []):
                if not isinstance(page, dict):
                    continue
                for line in list(page.get("lines") or []):
                    if isinstance(line, dict):
                        text = str(line.get("text") or "").strip()
                        if text:
                            ocr_chunks.append(text)

        return VisionAnalysis(
            caption=caption,
            ocr_text=" ".join(ocr_chunks).strip(),
            tags=tags[:TAG_LIMIT],
            status="ok",
        )


def build_vision_client(
    transport: Callable[..., Any] | None = None,
) -> AzureComputerVisionClient:
    return AzureComputerVisionClient(transport=transport)


__all__ = [
    "AzureComputerVisionClient",
    "VisionAnalysis",
    "build_vision_client",
    "compose_image_summary",
]
