from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.troubleshoot import router as troubleshoot_router


app = FastAPI(title="Optisweep AI Support Assistant Phase 0")
app.include_router(troubleshoot_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
