from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.app.services.attachment_service import build_attachment_service


router = APIRouter()


class AttachmentResponse(BaseModel):
    attachment_id: str
    session_id: str
    content_type: str
    filename: str
    blob_container: str = ""
    blob_path: str = ""
    storage_uri: str | None = None
    created_at: str
    source: str
    user_description: str = ""
    vision: dict[str, Any] = Field(default_factory=dict)
    image_summary: str = ""
    vision_status: str = "skipped"


class SummarizeRequest(BaseModel):
    attachment_id: str
    user_description: str | None = None
    reanalyze: bool = False


def _to_response(attachment: Any) -> AttachmentResponse:
    payload = attachment.to_dict() if hasattr(attachment, "to_dict") else dict(attachment)
    payload.pop("id", None)
    return AttachmentResponse(**payload)


@router.post("/attachments/upload", response_model=AttachmentResponse)
async def upload_attachment(
    session_id: str = Form(...),
    source: Literal["troubleshoot", "retrieve", "feedback"] = Form("troubleshoot"),
    user_description: str = Form(""),
    file: UploadFile = File(...),
) -> AttachmentResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty upload")
    content_type = file.content_type or "application/octet-stream"
    if not str(content_type).startswith("image/"):
        raise HTTPException(status_code=400, detail="only image uploads are supported")
    try:
        attachment = build_attachment_service().upload(
            session_id=session_id,
            filename=file.filename or "upload.bin",
            content_type=content_type,
            image_bytes=content,
            source=source,
            user_description=user_description,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"attachment upload failed: {exc}") from exc
    return _to_response(attachment)


@router.get("/attachments/{attachment_id}", response_model=AttachmentResponse)
def get_attachment(attachment_id: str) -> AttachmentResponse:
    attachment = build_attachment_service().get(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    return _to_response(attachment)


@router.post("/attachments/summarize", response_model=AttachmentResponse)
def summarize_attachment(request: SummarizeRequest) -> AttachmentResponse:
    attachment = build_attachment_service().summarize(
        request.attachment_id,
        user_description=request.user_description,
        reanalyze=request.reanalyze,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    return _to_response(attachment)
