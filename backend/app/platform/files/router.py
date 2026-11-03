"""Files API: streamed, rate-limited multipart upload and cookie-authenticated, parent-authorised downloads.

No presigned URLs and no tokens in query strings: downloads are plain same-origin links. Download responses
carry ``CSP: sandbox``, an RFC 6266 ``filename*``, ``inline`` only for images and PDFs, and a private cache
with an ETag (``no-store`` for restricted files). ``nosniff`` comes from the request-context middleware.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.errors import RateLimited
from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor
from app.platform.files import service
from app.platform.files.limits import check_upload_rate
from app.platform.files.schemas import FileRead, UploadPurpose
from app.platform.files.storage import staging_dir
from app.platform.files.upload import receive_upload

router = APIRouter(prefix="/files", tags=["files"])

_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


@router.post(
    "",
    status_code=201,
    response_model=FileRead,
    openapi_extra={**requires("files.file.create"), **_UPLOAD_BODY},
    operation_id="files_upload_file",
    summary="Upload one file (multipart part 'file'); limits: image 15 MB, document 25 MB, import 50 MB",
    responses={
        413: {"description": "payload_too_large"},
        415: {"description": "unsupported_media_type"},
        429: {"description": "rate_limited (Retry-After header)"},
    },
)
def upload_file(request: Request, actor: Actor, purpose: UploadPurpose = Query()) -> FileRead | Response:
    # both checks run before a single byte of the body is read
    actor.require("files.file.create")
    try:
        check_upload_rate(actor)
    except RateLimited as exc:
        retry_after = str(exc.extra.get("retry_after_seconds", 1))
        return JSONResponse(
            exc.to_problem(getattr(request.state, "request_id", None)),
            status_code=exc.status,
            media_type="application/problem+json",
            headers={"Retry-After": retry_after},
        )
    received = receive_upload(request, max_bytes=service.limit_for(purpose), staging=staging_dir())
    try:
        return service.create_from_upload(actor, received, purpose=purpose)
    finally:
        received.discard()


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = [c.strip().removeprefix("W/") for c in if_none_match.split(",")]
    return "*" in candidates or etag in candidates


@router.get(
    "/{file_id}/content",
    openapi_extra=authenticated(),
    operation_id="files_download_file_content",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}},
)
def download_file_content(
    file_id: uuid.UUID,
    request: Request,
    actor: Actor,
    variant: Literal["thumb", "medium"] | None = Query(default=None),
) -> Response:
    ticket = service.open_download(actor, file_id, variant)  # authorised; the unit of work is closed before streaming
    headers = {
        "ETag": ticket.etag,
        "Cache-Control": "no-store" if ticket.restricted else "private, no-cache",
        "Content-Security-Policy": "sandbox",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Disposition": service.content_disposition(ticket.original_name, inline=ticket.inline),
    }
    if not ticket.restricted and _matches(request.headers.get("if-none-match"), ticket.etag):
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(ticket.size_bytes)
    return StreamingResponse(ticket.iter_bytes(), media_type=ticket.content_type, headers=headers)
