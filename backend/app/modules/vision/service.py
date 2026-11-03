"""Vision service: masked screen captures, instant screen answers and photo/document extraction (ai-routing.md
sections 3, 4.2, 5.2 and 6).

- Captures are client-side, masked, downscaled WebP (PNG where WebP cannot be encoded), at most 1.5 MB and 1568 px
  on the longest edge; stored as ``file_object`` purpose ``screen_capture`` ``restricted``; deduplicated per
  (user, conversation) by SHA-256; purged after 24 hours by ``vision.captures.purge``. Never logged: the call log and
  ``vision_request`` reference the image by hash only.
- ``screen_capture.enabled`` (company, mandatory) gates every capture and screen answer; the personal preference
  ``assistant.screen_share`` only decides whether the client asks first.
- Screen answers use the masked screenshot plus the **re-read** screen context (the client's labels are never used);
  money/quantity figures not found in the re-read records are replaced ("see screen"). A question that needs data or
  an action is handed off: the client sends it to the assistant as a normal turn.
- Extractions never write records. They become an ``ExtractionCard``; fields below the confidence threshold or
  missing are confirmation fields with an empty value (the model's reading is only a hint) and must be answered
  explicitly before the card counts as confirmed. Everything here is tainted (external content).
- Failures degrade visibly: "Vision unavailable — enter details" with the manual form. Live mode without
  ``GEMINI_API_KEY`` raises 409 ``not_configured`` (no silent Demo fallback, ai-routing.md section 1 rule 5).
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotConfigured, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.agents.grounding import check_claims, decimals_in
from app.modules.agents.models import AiCallLog
from app.modules.agents.schemas import ScreenContext
from app.modules.vision.contract import (
    CONFIDENCE_THRESHOLD,
    EXTRACTION_KINDS,
    HEADER_FIELDS,
    LINE_FIELDS,
    UNAVAILABLE_MESSAGE,
    ExtractedValue,
    ExtractionKind,
    FieldSpec,
    ScreenFacts,
    VisionProvider,
    VisionUnavailable,
)
from app.modules.vision.models import CaptureStatus, RequestKind, RequestStatus, VisionCapture, VisionRequest
from app.modules.vision.schemas import (
    SCREEN_CAPTURE_SETTING,
    ExtractionCard,
    ExtractionConfirm,
    ExtractionCreate,
    ExtractionField,
    ExtractionLine,
    ScreenAnswerCreate,
    ScreenAnswerOut,
    ScreenCaptureOut,
    ScreenCaptureSetting,
    VisionCapabilities,
)
from app.platform.files.models import FileKind, FileObject, FilePurpose
from app.platform.files.storage import get_storage
from app.platform.uow import UnitOfWork

log = get_logger("lk.vision")

ASSISTANT_USE = "agents.assistant.use"
MAX_CAPTURE_BYTES = 3 * 1024 * 1024 // 2
MAX_EDGE_PX = 1568
CAPTURE_RETENTION = timedelta(hours=24)
#: ai-routing.md section 7 default; the routing table's ``vision_calls_per_user`` wins once agents-s3 is merged
DEFAULT_VISION_CALLS_PER_USER = 60
EXTRACTABLE_KINDS = {FileKind.PNG: "image/png", FileKind.JPEG: "image/jpeg", FileKind.WEBP: "image/webp",
                     FileKind.PDF: "application/pdf"}
MAX_EXTRACTION_BYTES = 15 * 1024 * 1024
SEE_SCREEN = "see screen"


# ---- access ----------------------------------------------------------------------------------------------------
def _require_use(uow: UnitOfWork) -> uuid.UUID:
    uow.actor.require(ASSISTANT_USE)
    if uow.actor.user_id is None:
        raise Forbidden(code="permission_denied", permission=ASSISTANT_USE)
    return uow.actor.user_id


def capture_setting(uow: UnitOfWork) -> ScreenCaptureSetting:
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, SCREEN_CAPTURE_SETTING.key)
    return value if isinstance(value, ScreenCaptureSetting) else ScreenCaptureSetting.model_validate(value.model_dump())


def _require_capture_enabled(uow: UnitOfWork) -> None:
    if not capture_setting(uow).enabled:
        raise Forbidden(
            "Masked screenshots are switched off for this company.", code="screen_capture_disabled",
        )


def screen_share_preference(uow: UnitOfWork) -> str:
    from app.platform.identity.models import UserPreference

    row = uow.session.get(UserPreference, uow.actor.user_id) if uow.actor.user_id else None
    value = (row.assistant or {}).get("screen_share") if row is not None else None
    return value if value in ("ask", "auto") else "ask"


# ---- provider selection ----------------------------------------------------------------------------------------
def _routing_table(uow: UnitOfWork) -> Any | None:
    """agents-s3 seam: the configurable routing table (``agents/routing.py``) when that lane is merged."""
    try:
        from app.modules.agents import routing  # type: ignore[attr-defined]
    except ImportError:
        return None
    try:
        return routing.resolve(uow)
    except Exception:  # noqa: BLE001 - a broken setting must not break vision; defaults apply
        log.warning("vision.routing_unavailable")
        return None


def vision_model(uow: UnitOfWork) -> str:
    table = _routing_table(uow)
    return table.model_for("vision") if table is not None else get_settings().model_vision


def vision_quota(uow: UnitOfWork) -> int:
    table = _routing_table(uow)
    if table is not None:
        return int(table.quotas.get("vision_calls_per_user", DEFAULT_VISION_CALLS_PER_USER))
    return DEFAULT_VISION_CALLS_PER_USER


def is_live() -> bool:
    return get_settings().ai_mode == "live"


def key_missing() -> bool:
    return not get_settings().gemini_api_key.get_secret_value()


def get_provider(uow: UnitOfWork) -> VisionProvider:
    if not is_live():
        from app.modules.agents.providers.demo_vision import DemoVisionProvider

        return DemoVisionProvider()
    if key_missing():
        raise NotConfigured(
            "Vision live mode is selected but GEMINI_API_KEY is not configured; set the key on the server or switch "
            "LK_AI_MODE to demo.", integration="gemini", mode="live",
        )
    from app.modules.agents.providers.gemini_vision import GeminiVisionProvider

    return GeminiVisionProvider(api_key=get_settings().gemini_api_key.get_secret_value(), model=vision_model(uow))


def provider_label() -> str:
    return "Gemini" if is_live() else "Demo"


def capabilities(uow: UnitOfWork) -> VisionCapabilities:
    _require_use(uow)
    return VisionCapabilities(
        screen_capture_enabled=capture_setting(uow).enabled,
        screen_share=screen_share_preference(uow),  # type: ignore[arg-type]
        provider_label=provider_label(),
        mode="live" if is_live() else "demo",
        configured=not (is_live() and key_missing()),
        max_capture_bytes=MAX_CAPTURE_BYTES,
        max_edge_px=MAX_EDGE_PX,
        extraction_kinds=list(EXTRACTION_KINDS),
    )


# ---- quota and the usage store ---------------------------------------------------------------------------------
def _day_start(uow: UnitOfWork) -> datetime:
    from app.platform.org.models import Company

    zone_name = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
    local = uow.now().astimezone(ZoneInfo(zone_name or "Asia/Kolkata"))
    return datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)


def calls_today(uow: UnitOfWork, user_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(VisionRequest).where(
        VisionRequest.company_id == uow.actor.company_id, VisionRequest.user_id == user_id,
        VisionRequest.created_at >= _day_start(uow),
    )
    return int(uow.session.execute(stmt).scalar_one())


def _check_quota(uow: UnitOfWork, user_id: uuid.UUID) -> None:
    limit = vision_quota(uow)
    used = calls_today(uow, user_id)
    if used >= limit:
        raise Conflict(
            f"The daily vision quota is used up ({used}/{limit}). Enter the details by hand; vision is available "
            "again tomorrow.", code="quota_exceeded", used=used, limit=limit,
        )


def _log_call(uow: UnitOfWork, *, provider: str, model: str, latency_ms: int, input_tokens: int, output_tokens: int,
              request_id: str | None, error: str | None) -> uuid.UUID:
    """One ``agents_ai_call_log`` row (workflow ``vision``): usage only, never the image or its text."""
    row = AiCallLog(
        id=uuid.uuid7(), run_id=None, step_seq=None, workflow="vision", provider=provider, model=model[:80],
        task_class="vision", input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms,
        outcome="ok" if error is None else "error", error_type=error, request_id=request_id, created_at=uow.now(),
    )
    # agents-s3 adds the quota owner and the trace id to the call log; set them when the columns exist
    if hasattr(AiCallLog, "user_id"):
        row.user_id = uow.actor.user_id  # type: ignore[attr-defined]
    if hasattr(AiCallLog, "correlation_id"):
        row.correlation_id = uow.actor.correlation_id  # type: ignore[attr-defined]
    uow.add(row)
    return row.id


# ---- captures --------------------------------------------------------------------------------------------------
def _capture_out(capture: VisionCapture, *, deduplicated: bool) -> ScreenCaptureOut:
    return ScreenCaptureOut(
        id=capture.id, sha256=capture.sha256, width=capture.width, height=capture.height, size_bytes=capture.size_bytes,
        masked_count=capture.masked_count, deduplicated=deduplicated, purge_at=capture.purge_at,
        status=capture.status,  # type: ignore[arg-type]
    )


def _image_size(data: bytes) -> tuple[str, int, int]:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt, (width, height) = (image.format or "").upper(), image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationFailed("The screenshot is not a readable image.", code="invalid_capture") from exc
    if fmt not in ("WEBP", "PNG"):
        raise ValidationFailed("Screenshots must be WebP (or PNG).", code="invalid_capture")
    return ("image/webp" if fmt == "WEBP" else "image/png"), width, height


def store_capture(
    uow: UnitOfWork, data: bytes, *, conversation_id: uuid.UUID | None, masked_count: int, route_path: str | None,
) -> ScreenCaptureOut:
    user_id = _require_use(uow)
    _require_capture_enabled(uow)
    if len(data) > MAX_CAPTURE_BYTES:
        raise ValidationFailed("The screenshot is larger than 1.5 MB.", code="capture_too_large")
    mime, width, height = _image_size(data)
    if max(width, height) > MAX_EDGE_PX:
        raise ValidationFailed(f"The screenshot's longest edge is over {MAX_EDGE_PX} px.", code="capture_too_large")
    import hashlib

    sha256 = hashlib.sha256(data).hexdigest()
    existing = uow.session.scalars(
        select(VisionCapture).where(
            VisionCapture.company_id == uow.actor.company_id, VisionCapture.user_id == user_id,
            VisionCapture.sha256 == sha256, VisionCapture.status != CaptureStatus.PURGED.value,
            VisionCapture.conversation_id.is_(None) if conversation_id is None else VisionCapture.conversation_id == conversation_id,
        ).with_for_update()
    ).first()
    now = uow.now()
    if existing is not None:
        existing.status = CaptureStatus.ATTACHED.value
        return _capture_out(existing, deduplicated=True)
    from app.platform.files.service import store_generated

    stored = store_generated(uow, data, filename=f"screen-{sha256[:12]}.{mime.split('/')[1]}",
                             purpose=FilePurpose.SCREEN_CAPTURE, restricted=True)
    capture = VisionCapture(
        id=uuid.uuid7(), user_id=user_id, conversation_id=conversation_id, file_id=stored.id, sha256=sha256,
        mime_type=mime, size_bytes=len(data), width=width, height=height, masked_count=max(0, min(masked_count, 10_000)),
        route_path=(route_path or None) and route_path[:300], status=CaptureStatus.ATTACHED.value,
        purge_at=now + CAPTURE_RETENTION,
    )
    uow.add(capture)
    uow.flush()
    return _capture_out(capture, deduplicated=False)


def _own_capture(uow: UnitOfWork, capture_id: uuid.UUID, *, for_update: bool = False) -> VisionCapture:
    user_id = _require_use(uow)
    stmt = select(VisionCapture).where(
        VisionCapture.company_id == uow.actor.company_id, VisionCapture.id == capture_id, VisionCapture.user_id == user_id,
    )
    row = uow.session.scalars(stmt.with_for_update() if for_update else stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="vision.capture")
    return row


def remove_capture(uow: UnitOfWork, capture_id: uuid.UUID) -> ScreenCaptureOut:
    """The chip's remove: the capture is detached at once and its bytes purged now (not after 24 hours)."""
    capture = _own_capture(uow, capture_id, for_update=True)
    if capture.status != CaptureStatus.PURGED.value:
        _purge_capture(uow, capture)
    return _capture_out(capture, deduplicated=False)


def _capture_bytes(uow: UnitOfWork, capture: VisionCapture) -> bytes:
    if capture.status != CaptureStatus.ATTACHED.value or capture.file_id is None:
        raise NotFound("The screenshot is no longer attached.", code="capture_not_attached", resource_type="vision.capture")
    obj = uow.session.get(FileObject, capture.file_id)
    if obj is None:
        raise NotFound(code="capture_not_attached", resource_type="vision.capture")
    with get_storage().open(obj.storage_key) as fh:
        return fh.read()


def _purge_capture(uow: UnitOfWork, capture: VisionCapture) -> None:
    """Delete the blob and the file row unless another live capture or another purpose still holds the bytes."""
    file_id = capture.file_id
    capture.status = CaptureStatus.PURGED.value
    capture.purged_at = uow.now()
    capture.file_id = None
    if file_id is None:
        return
    uow.flush()
    still_used = uow.session.scalar(
        select(func.count()).select_from(VisionCapture).where(
            VisionCapture.file_id == file_id, VisionCapture.status != CaptureStatus.PURGED.value,
        )
    )
    obj = uow.session.get(FileObject, file_id)
    if obj is None or still_used:
        return
    if any(isinstance(c, dict) and c.get("purpose") != FilePurpose.SCREEN_CAPTURE.value for c in obj.claims or []):
        return  # identical bytes were stored for another purpose: that owner keeps them
    from sqlalchemy import update

    uow.session.execute(update(VisionRequest).where(VisionRequest.source_file_id == file_id).values(source_file_id=None))
    key = obj.storage_key
    uow.session.delete(obj)
    uow.flush()
    uow.after_commit(lambda: get_storage().delete(key))


def purge_due(uow: UnitOfWork) -> int:
    """``vision.captures.purge``: captures older than 24 hours (one company, system actor)."""
    due = list(uow.session.scalars(
        select(VisionCapture).where(
            VisionCapture.company_id == uow.actor.company_id, VisionCapture.status != CaptureStatus.PURGED.value,
            VisionCapture.purge_at <= uow.now(),
        ).order_by(VisionCapture.purge_at).limit(500).with_for_update(skip_locked=True)
    ))
    for capture in due:
        _purge_capture(uow, capture)
    return len(due)


# ---- instant screen answers ------------------------------------------------------------------------------------
def _screen_facts(uow: UnitOfWork, context: ScreenContext | None) -> tuple[ScreenFacts, set[Any]]:
    from app.modules.agents.context import ground_screen_context
    from app.platform import sources

    refs = ground_screen_context(uow, context)
    records: list[dict[str, Any]] = []
    allowed: set[Any] = set()
    for ref in refs[:20]:
        facts = sources.read(uow, ref.resource_type, ref.resource_id)
        if facts is None:
            continue
        records.append({"type": ref.resource_type, "label": facts.label, "status": facts.status, "facts": dict(facts.facts)})
        allowed |= decimals_in(facts.facts)
        allowed |= decimals_in(facts.label.replace(",", "").split())
    route = context.route if context is not None else None
    return ScreenFacts(route_path=route.path if route else None, area=route.area if route else None,
                       records=tuple(records)), allowed


def answer_screen(uow: UnitOfWork, data: ScreenAnswerCreate) -> ScreenAnswerOut:
    user_id = _require_use(uow)
    _require_capture_enabled(uow)
    capture = _own_capture(uow, data.capture_id)
    image = _capture_bytes(uow, capture)
    _check_quota(uow, user_id)
    provider = get_provider(uow)
    facts, allowed = _screen_facts(uow, data.context)
    request = VisionRequest(
        id=uuid.uuid7(), user_id=user_id, conversation_id=data.conversation_id or capture.conversation_id,
        kind=RequestKind.SCREEN_ANSWER.value, capture_id=capture.id, input_sha256=capture.sha256, question=data.question,
        provider=provider.name, model=provider.model, status=RequestStatus.UNAVAILABLE.value, tainted=True,
    )
    try:
        answer = provider.answer_screen(image, capture.mime_type, data.question, facts)
    except VisionUnavailable as exc:
        request.error_code = exc.code
        request.latency_ms = exc.latency_ms
        request.call_log_id = _log_call(uow, provider=provider.name, model=provider.model, latency_ms=exc.latency_ms,
                                        input_tokens=0, output_tokens=0, request_id=exc.request_id, error=exc.code)
        uow.add(request)
        return ScreenAnswerOut(request_id=request.id, status="unavailable", text=UNAVAILABLE_MESSAGE, handoff=True,
                               handoff_reason="vision_unavailable", provider_label=provider.label, capture_sha256=capture.sha256)
    text, replaced = check_claims(answer.text, allowed)
    text = text.replace("see card", SEE_SCREEN)
    status = RequestStatus.HANDED_OFF if answer.needs_handoff else RequestStatus.ANSWERED
    request.status = status.value
    request.latency_ms = answer.latency_ms
    request.result = {"text": text, "handoff": answer.needs_handoff, "reason": answer.handoff_reason,
                      "confidence": answer.confidence, "claims_replaced": replaced}
    request.call_log_id = _log_call(uow, provider=answer.provider, model=answer.model, latency_ms=answer.latency_ms,
                                    input_tokens=answer.input_tokens, output_tokens=answer.output_tokens,
                                    request_id=answer.request_id, error=None)
    uow.add(request)
    return ScreenAnswerOut(
        request_id=request.id, status=status.value, text=text, handoff=answer.needs_handoff,  # type: ignore[arg-type]
        handoff_reason=answer.handoff_reason, provider_label=provider.label, capture_sha256=capture.sha256,
    )


# ---- extraction ------------------------------------------------------------------------------------------------
def _store_values(values: dict[str, ExtractedValue]) -> dict[str, dict[str, Any]]:
    return {k: {"value": v.value, "confidence": round(v.confidence, 3)} for k, v in values.items()}


def _needs_confirmation(raw: dict[str, Any]) -> bool:
    return raw.get("value") is None or float(raw.get("confidence") or 0) < CONFIDENCE_THRESHOLD


def _field(spec: FieldSpec, raw: dict[str, Any], confirmed: dict[str, Any] | None) -> ExtractionField:
    uncertain = _needs_confirmation(raw)
    if confirmed is not None:
        return ExtractionField(key=spec.key, label=spec.label, type=spec.type, value=confirmed.get(spec.key),
                               suggestion=None, confidence=float(raw.get("confidence") or 0), needs_confirmation=False)
    return ExtractionField(
        key=spec.key, label=spec.label, type=spec.type, value=None if uncertain else raw.get("value"),
        suggestion=raw.get("value") if uncertain else None, confidence=float(raw.get("confidence") or 0),
        needs_confirmation=uncertain,
    )


def card_for(request: VisionRequest) -> ExtractionCard:
    kind: ExtractionKind = request.extraction_kind  # type: ignore[assignment]
    result = request.result or {"header": {}, "lines": []}
    confirmed = request.confirmed
    raw_header = result.get("header") or {}
    header = [
        _field(spec, raw_header.get(spec.key) or {"value": None, "confidence": 0},
               (confirmed or {}).get("header") if confirmed else None)
        for spec in HEADER_FIELDS[kind]
    ]
    lines: list[ExtractionLine] = []
    confirmed_lines = (confirmed or {}).get("lines") if confirmed else None
    for index, raw in enumerate(result.get("lines") or []):
        fields = [
            _field(spec, raw.get(spec.key) or {"value": None, "confidence": 0},
                   confirmed_lines[index] if confirmed_lines is not None and index < len(confirmed_lines) else None)
            for spec in LINE_FIELDS[kind]
        ]
        lines.append(ExtractionLine(index=index, fields=fields))
    pending = sum(f.needs_confirmation for f in header) + sum(f.needs_confirmation for line in lines for f in line.fields)
    status = request.status if request.status in ("extracted", "confirmed", "unavailable") else "extracted"
    return ExtractionCard(
        request_id=request.id, status=status, extraction_kind=kind,  # type: ignore[arg-type]
        provider_label="Gemini" if request.provider == "gemini" else "Demo", header=header, lines=lines,
        pending_confirmations=pending, message=UNAVAILABLE_MESSAGE if status == "unavailable" else None,
        version=request.version,
    )


def extract(uow: UnitOfWork, data: ExtractionCreate) -> ExtractionCard:
    from app.platform.files.service import get_readable

    user_id = _require_use(uow)
    obj = get_readable(uow, data.file_id)
    mime = EXTRACTABLE_KINDS.get(FileKind(obj.kind))
    if mime is None:
        raise ValidationFailed("Only photos (PNG, JPEG, WebP) and PDF documents can be read.", code="unsupported_file")
    if obj.size_bytes > MAX_EXTRACTION_BYTES:
        raise ValidationFailed("The file is larger than 15 MB.", code="file_too_large")
    _check_quota(uow, user_id)
    provider = get_provider(uow)
    with get_storage().open(obj.storage_key) as fh:
        image = fh.read()
    request = VisionRequest(
        id=uuid.uuid7(), user_id=user_id, conversation_id=data.conversation_id, kind=RequestKind.EXTRACTION.value,
        extraction_kind=data.kind, source_file_id=obj.id, input_sha256=obj.sha256, provider=provider.name,
        model=provider.model, status=RequestStatus.UNAVAILABLE.value, tainted=True,
    )
    try:
        extraction = provider.extract(image, mime, data.kind)
    except VisionUnavailable as exc:
        request.extraction_kind = data.kind or "delivery_note"
        request.error_code = exc.code
        request.latency_ms = exc.latency_ms
        request.result = {"header": {}, "lines": []}
        request.call_log_id = _log_call(uow, provider=provider.name, model=provider.model, latency_ms=exc.latency_ms,
                                        input_tokens=0, output_tokens=0, request_id=exc.request_id, error=exc.code)
        uow.add(request)
        uow.flush()
        return card_for(request)
    request.extraction_kind = extraction.kind
    request.status = RequestStatus.EXTRACTED.value
    request.latency_ms = extraction.latency_ms
    request.result = {"header": _store_values(dict(extraction.header)),
                      "lines": [_store_values(dict(line)) for line in extraction.lines]}
    request.call_log_id = _log_call(uow, provider=extraction.provider, model=extraction.model,
                                    latency_ms=extraction.latency_ms, input_tokens=extraction.input_tokens,
                                    output_tokens=extraction.output_tokens, request_id=extraction.request_id, error=None)
    uow.add(request)
    uow.flush()
    return card_for(request)


def _own_request(uow: UnitOfWork, request_id: uuid.UUID, *, for_update: bool = False) -> VisionRequest:
    user_id = _require_use(uow)
    stmt = select(VisionRequest).where(
        VisionRequest.company_id == uow.actor.company_id, VisionRequest.id == request_id, VisionRequest.user_id == user_id,
    )
    row = uow.session.scalars(stmt.with_for_update() if for_update else stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="vision.request")
    return row


def get_extraction(uow: UnitOfWork, request_id: uuid.UUID) -> ExtractionCard:
    request = _own_request(uow, request_id)
    if request.kind != RequestKind.EXTRACTION.value:
        raise NotFound(code="not_found", resource_type="vision.request")
    return card_for(request)


def confirm_extraction(uow: UnitOfWork, request_id: uuid.UUID, data: ExtractionConfirm) -> ExtractionCard:
    """Record the person's confirmed values. Every confirmation field must be answered explicitly; values the model
    read with confidence may be corrected. Nothing is written anywhere else."""
    request = _own_request(uow, request_id, for_update=True)
    if request.kind != RequestKind.EXTRACTION.value:
        raise NotFound(code="not_found", resource_type="vision.request")
    uow.expect_version(request, data.expected_version)
    if request.status == RequestStatus.CONFIRMED.value:
        raise Conflict("These details were already confirmed.", code="already_confirmed")
    card = card_for(request)
    errors: list[dict[str, Any]] = []
    header_keys = {f.key for f in card.header}
    for key in data.header:
        if key not in header_keys:
            errors.append({"loc": ["body", "header", key], "msg": "unknown field", "type": "unknown_field"})
    header = {f.key: (data.header[f.key] or None) if f.key in data.header else f.value for f in card.header}
    for f in card.header:
        if f.needs_confirmation and f.key not in data.header:
            errors.append({"loc": ["body", "header", f.key], "msg": "confirm this field", "type": "confirmation_required"})
    if len(data.lines) != len(card.lines):
        errors.append({"loc": ["body", "lines"], "msg": f"expected {len(card.lines)} lines", "type": "line_count"})
    lines: list[dict[str, Any]] = []
    for line, given in zip(card.lines, data.lines, strict=False):
        values: dict[str, Any] = {}
        for f in line.fields:
            if f.key in given:
                values[f.key] = given[f.key] or None
            elif f.needs_confirmation:
                errors.append({"loc": ["body", "lines", line.index, f.key], "msg": "confirm this field",
                               "type": "confirmation_required"})
            else:
                values[f.key] = f.value
        lines.append(values)
    if errors:
        raise ValidationFailed("Confirm every highlighted field first.", code="confirmation_required", errors=errors)
    request.confirmed = {"header": header, "lines": lines}
    request.confirmed_at = uow.now()
    request.status = RequestStatus.CONFIRMED.value
    uow.flush()
    return card_for(request)


def untrusted_payload(uow: UnitOfWork, request_id: uuid.UUID) -> dict[str, Any]:
    """Seam for the orchestrator (integrator request): a confirmed extraction as the untrusted tool-result block of
    ai-routing.md section 6 — ``{"untrusted": true, "source": ..., "text": ...}`` — so a run that uses it is tainted."""
    request = _own_request(uow, request_id)
    if request.status != RequestStatus.CONFIRMED.value or not request.confirmed:
        raise Conflict("Confirm the extracted details first.", code="confirmation_required")
    import json

    return {"untrusted": True, "source": f"vision.extraction:{request.extraction_kind}",
            "text": json.dumps(request.confirmed, ensure_ascii=False, sort_keys=True)}


__all__ = [
    "MAX_CAPTURE_BYTES",
    "MAX_EDGE_PX",
    "answer_screen",
    "capabilities",
    "capture_setting",
    "card_for",
    "confirm_extraction",
    "extract",
    "get_extraction",
    "get_provider",
    "purge_due",
    "remove_capture",
    "store_capture",
    "untrusted_payload",
]
