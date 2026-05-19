from __future__ import annotations

from fastapi import APIRouter

from backend.app.graph.graph import run_troubleshooting
from backend.app.schemas.assistant import TroubleshootRequest, TroubleshootResponse


router = APIRouter()


@router.post("/troubleshoot", response_model=TroubleshootResponse)
def troubleshoot(request: TroubleshootRequest) -> TroubleshootResponse:
    state = run_troubleshooting(request.session_id, request.user_message)
    return TroubleshootResponse(**state)
