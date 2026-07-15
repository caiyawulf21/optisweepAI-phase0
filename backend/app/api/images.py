from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import RedirectResponse

from backend.app.services.canonical_image_lookup import build_canonical_image_lookup


router = APIRouter()


def _guess_media_type(url: str, content_type: str | None) -> str:
    if content_type and content_type.startswith("image/"):
        return content_type.split(";")[0].strip()
    lowered = url.lower()
    if ".png" in lowered:
        return "image/png"
    if ".gif" in lowered:
        return "image/gif"
    if ".webp" in lowered:
        return "image/webp"
    return "image/jpeg"


@router.get("/images/{image_id}")
def get_image(image_id: str, proxy: bool = True) -> Response:
    lookup = build_canonical_image_lookup()
    record = lookup.get_by_image_id(image_id)
    if not record:
        raise HTTPException(status_code=404, detail="image not found")
    storage_uri = str(record.get("storage_uri") or "").strip()
    if not (storage_uri.startswith("http://") or storage_uri.startswith("https://")):
        raise HTTPException(
            status_code=404,
            detail="image storage_uri missing (Blob publish required)",
        )
    if not proxy:
        return RedirectResponse(url=storage_uri, status_code=307)
    try:
        import requests
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=502, detail="image proxy unavailable") from exc
    try:
        response = requests.get(storage_uri, timeout=60)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"failed to fetch image: {exc}") from exc
    if response.status_code >= 400 or not response.content:
        raise HTTPException(
            status_code=502,
            detail=f"blob fetch failed ({response.status_code})",
        )
    return Response(
        content=response.content,
        media_type=_guess_media_type(
            storage_uri, response.headers.get("content-type")
        ),
        headers={"Cache-Control": "private, max-age=300"},
    )
