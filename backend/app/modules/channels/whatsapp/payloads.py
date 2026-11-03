"""Typed WhatsApp webhook payloads (Cloud API ``whatsapp_business_account`` object, fields ``messages`` and
``message_template_status_update``), parsed tolerantly: unknown keys are ignored, unknown message types are kept
as ``unsupported`` so the worker can answer politely. Shapes checked against the Cloud API webhooks reference on
2026-11-03 (Graph API v26.0).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

KNOWN_MESSAGE_TYPES = frozenset({"text", "audio", "image", "document", "interactive", "button", "system", "reaction", "sticker", "video", "location", "contacts", "order", "unsupported"})
STATUS_VALUES = ("sent", "delivered", "read", "played", "failed", "deleted", "warning")


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Metadata(_Model):
    display_phone_number: str | None = None
    phone_number_id: str


class Profile(_Model):
    name: str | None = None


class Contact(_Model):
    wa_id: str | None = None
    #: business-scoped user id (BSUID) when the user has one
    user_id: str | None = None
    username: str | None = None
    profile: Profile | None = None


class TextBody(_Model):
    body: str = ""


class Media(_Model):
    id: str | None = None
    mime_type: str | None = None
    sha256: str | None = None
    caption: str | None = None
    filename: str | None = None
    voice: bool | None = None


class ButtonReply(_Model):
    id: str
    title: str | None = None


class ListReply(_Model):
    id: str
    title: str | None = None
    description: str | None = None


class Interactive(_Model):
    type: str
    button_reply: ButtonReply | None = None
    list_reply: ListReply | None = None

    @property
    def reply_id(self) -> str | None:
        if self.button_reply is not None:
            return self.button_reply.id
        if self.list_reply is not None:
            return self.list_reply.id
        return None


class Context(_Model):
    from_: str | None = Field(default=None, alias="from")
    id: str | None = None


class SystemBody(_Model):
    body: str | None = None
    type: str | None = None
    #: user_changed_number: the new wa_id; user_id_update / user_changed_user_id: the new BSUID
    wa_id: str | None = None
    user_id: str | None = None
    new_wa_id: str | None = None
    identity: str | None = None


class WaError(_Model):
    code: int | None = None
    title: str | None = None
    message: str | None = None
    error_data: dict[str, Any] | None = None


class Message(_Model):
    id: str
    from_: str | None = Field(default=None, alias="from")
    #: BSUID of the sender when present (username users may have no phone)
    from_user_id: str | None = None
    timestamp: str | None = None
    type: str = "unsupported"
    text: TextBody | None = None
    audio: Media | None = None
    image: Media | None = None
    document: Media | None = None
    video: Media | None = None
    interactive: Interactive | None = None
    system: SystemBody | None = None
    context: Context | None = None
    errors: list[WaError] = Field(default_factory=list)
    #: group messages carry a group identifier (Cloud API groups beta); always ignored
    group_id: str | None = None
    recipient_type: str | None = None

    @property
    def provider_ts(self) -> datetime | None:
        return _ts(self.timestamp)

    @property
    def is_group(self) -> bool:
        return bool(self.group_id) or self.recipient_type == "group" or (self.from_ or "").endswith("@g.us")

    @property
    def media(self) -> Media | None:
        return self.audio or self.image or self.document or self.video


class Conversation(_Model):
    id: str | None = None
    origin: dict[str, Any] | None = None
    expiration_timestamp: str | None = None


class Status(_Model):
    id: str
    status: str
    timestamp: str | None = None
    recipient_id: str | None = None
    recipient_user_id: str | None = None
    biz_opaque_callback_data: str | None = None
    conversation: Conversation | None = None
    pricing: dict[str, Any] | None = None
    errors: list[WaError] = Field(default_factory=list)

    @property
    def provider_ts(self) -> datetime | None:
        return _ts(self.timestamp)


class MessagesValue(_Model):
    messaging_product: str | None = None
    metadata: Metadata
    contacts: list[Contact] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    statuses: list[Status] = Field(default_factory=list)
    errors: list[WaError] = Field(default_factory=list)


class TemplateStatusValue(_Model):
    event: str
    message_template_id: int | str
    message_template_name: str
    message_template_language: str
    reason: str | None = None
    #: paused/disabled details
    disable_info: dict[str, Any] | None = None
    other_info: dict[str, Any] | None = None


class Change(_Model):
    field: str
    value: dict[str, Any]


class Entry(_Model):
    id: str
    time: int | str | None = None
    changes: list[Change] = Field(default_factory=list)


class WebhookPayload(_Model):
    object: str
    entry: list[Entry] = Field(default_factory=list)


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return None


def parse_payload(raw: dict[str, Any]) -> WebhookPayload:
    return WebhookPayload.model_validate(raw)


def messages_changes(payload: WebhookPayload) -> list[tuple[str, MessagesValue]]:
    """(waba id, value) for every ``messages`` change."""
    out: list[tuple[str, MessagesValue]] = []
    for entry in payload.entry:
        for change in entry.changes:
            if change.field == "messages":
                out.append((entry.id, MessagesValue.model_validate(change.value)))
    return out


def template_changes(payload: WebhookPayload) -> list[tuple[str, TemplateStatusValue]]:
    out: list[tuple[str, TemplateStatusValue]] = []
    for entry in payload.entry:
        for change in entry.changes:
            if change.field == "message_template_status_update":
                out.append((entry.id, TemplateStatusValue.model_validate(change.value)))
    return out


def status_event_key(status: Status) -> str:
    return f"{status.id}:{status.status}:{status.timestamp or ''}"


def template_event_key(value: TemplateStatusValue, entry_time: int | str | None) -> str:
    return f"tpl:{value.message_template_id}:{value.event}:{entry_time or ''}"


TEMPLATE_EVENT_TO_STATUS: dict[str, str] = {
    "APPROVED": "approved",
    "REJECTED": "rejected",
    "PENDING": "pending",
    "PAUSED": "paused",
    "DISABLED": "disabled",
    "FLAGGED": "paused",
    "PENDING_DELETION": "disabled",
    "IN_APPEAL": "pending",
    "REINSTATED": "approved",
}

MessageKind = Literal["text", "audio", "image", "document", "interactive", "system", "unsupported"]


def classify_message(message: Message) -> MessageKind:
    if message.type == "text" and message.text is not None:
        return "text"
    if message.type == "audio" and message.audio is not None:
        return "audio"
    if message.type == "image" and message.image is not None:
        return "image"
    if message.type == "document" and message.document is not None:
        return "document"
    if message.type == "interactive" and message.interactive is not None and message.interactive.reply_id:
        return "interactive"
    if message.type == "system" and message.system is not None:
        return "system"
    return "unsupported"


__all__ = [
    "KNOWN_MESSAGE_TYPES", "STATUS_VALUES", "TEMPLATE_EVENT_TO_STATUS", "Contact", "Message", "MessageKind", "MessagesValue",
    "Metadata", "Status", "TemplateStatusValue", "WaError", "WebhookPayload", "classify_message", "messages_changes",
    "parse_payload", "status_event_key", "template_changes", "template_event_key",
]
