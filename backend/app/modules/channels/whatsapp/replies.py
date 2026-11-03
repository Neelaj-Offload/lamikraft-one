"""Replies and assistant hand-off for WhatsApp.

- ``notice``: a short system reply (generic "not linked", link outcomes, consent confirmations, unsupported types).
  Notices carry no business data and are allowed to any identity status (the sender just wrote to us).
- ``submit_turn``: an employee's text (or voice transcript, or a chosen clarification option) becomes an agents turn
  with the message's ``input_mode`` (``wa_text`` / ``wa_voice`` / ``card_action``), created **as the linked user** (``channel=whatsapp``, ``auth_strength=channel_linked``) in the user's own unit of
  work, idempotent on the wamid (``client_utterance_id = uuid5(wamid)``). Permissions are exactly the web's.
- ``reply_for_run``: when the run finishes (``agents.run.completed`` / ``.failed``), the server-built cards are
  rendered (figures from cards, never model prose) with up to three reply buttons, each an armed action ref.
- ``handle_button``: an interactive reply consumes its action ref (no model involved): open → the app URL;
  review / approve / reject → a 15-minute review link (decisions happen on the web); option → a clarification
  answer turn.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.channels import action_refs, review_links
from app.modules.channels.models import ChannelAccount, ChannelIdentity, ChannelMessage
from app.modules.channels.schemas import ReviewPurpose
from app.modules.channels.whatsapp import outbound
from app.modules.channels.whatsapp.render import ButtonSpec, plain, render_turn
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

log = get_logger("lk.channels.replies")

UTTERANCE_NAMESPACE = uuid.UUID("6f0b7c64-3a0e-5d7c-9a47-1c2e5b7d8a90")

NOT_LINKED = (
    "This number is not linked to Lamikraft One. To use the assistant here, sign in on the web and choose "
    "Settings > WhatsApp > Link my WhatsApp."
)
UNSUPPORTED = "I can read text messages, voice notes, images and documents. Please send your request as text or a voice note."
ASSISTANT_UNAVAILABLE = "The assistant could not take that request right now. Please try again in a moment or use the web app."


def utterance_id(wamid: str) -> uuid.UUID:
    return uuid.uuid5(UTTERANCE_NAMESPACE, wamid)


def _account(uow: UnitOfWork, identity: ChannelIdentity) -> ChannelAccount:
    account = uow.session.get(ChannelAccount, identity.account_id)
    assert account is not None
    return account


def notice(uow: UnitOfWork, identity: ChannelIdentity, text: str, *, key: str, reply_to: str | None = None) -> None:
    demo = _account(uow, identity).mode == "demo"
    outbound.queue_message(
        uow, identity, kind="session", payload={"type": "text", "text": plain(text, demo=demo), "notice": True},
        text=plain(text, demo=demo), purpose="assistant_replies", idempotency_key=f"notice:{key}", cause_ref=f"notice:{key}"[:120],
        reply_to=reply_to,
    )


def app_url(path: str) -> str:
    origin = get_settings().public_origin.rstrip("/")
    return f"{origin}{path if path.startswith('/') else '/' + path}"


# ---- turns -------------------------------------------------------------------------------------------------------
def member_actor(company_id: uuid.UUID, user_id: uuid.UUID, correlation_id: str | None) -> ActorContext:
    from app.platform.authz.actors import actor_for_member

    actor = actor_for_member(company_id, user_id, channel="whatsapp")
    return actor.with_(auth_strength="channel_linked", correlation_id=correlation_id)


def submit_turn(
    company_id: uuid.UUID, message_id: uuid.UUID, *, text: str, wamid: str, selected_option: dict[str, str] | None = None,
) -> uuid.UUID | None:
    """Create the turn as the linked user (own unit of work) and link the message; returns the run id.
    Failures produce an honest reply instead of silence."""
    from app.modules.agents import service as agents
    from app.modules.agents.schemas import ConversationChannel, ConversationCreate, SelectedOption, TurnCreate, TurnInputMode

    with UnitOfWork(ActorContext.system(company_id, reason="channels.turn.lookup")) as uow:
        message = uow.session.get(ChannelMessage, message_id)
        identity = uow.session.get(ChannelIdentity, message.identity_id) if message else None
        if message is None or identity is None or identity.user_id is None:
            return None
        user_id, conversation_id, correlation_id = identity.user_id, identity.conversation_id, message.correlation_id
        # recorded by inbound processing (wa_text / wa_voice / card_action); a chosen option is a card action
        input_mode = TurnInputMode(message.input_mode or ("card_action" if selected_option else "wa_text"))
        identity_id = identity.id
    try:
        actor = member_actor(company_id, user_id, correlation_id)
        with UnitOfWork(actor) as uow:
            if conversation_id is not None:
                try:
                    agents.own_conversation(uow, conversation_id)
                except Exception:
                    conversation_id = None
            if conversation_id is None:
                conversation_id = agents.create_conversation(uow, ConversationCreate(channel=ConversationChannel.WHATSAPP, title="WhatsApp")).id
            body = TurnCreate(
                text=text, client_utterance_id=utterance_id(wamid),
                selected_option=SelectedOption(**selected_option) if selected_option else None,
                input_mode=input_mode,
            )
            accepted = agents.create_turn(uow, conversation_id, body)
            row = uow.session.get(ChannelMessage, message_id)
            identity_row = uow.session.get(ChannelIdentity, identity_id)
            if row is not None:
                row.turn_id, row.run_id = accepted.turn_id, accepted.run_id
            if identity_row is not None and identity_row.conversation_id != conversation_id:
                identity_row.conversation_id = conversation_id
            return accepted.run_id
    except Exception as exc:
        log.warning("channels.turn_failed", message_id=str(message_id), error=type(exc).__name__, detail=str(exc)[:200])
        with UnitOfWork(ActorContext.system(company_id, reason="channels.turn.failed")) as uow:
            identity = uow.session.get(ChannelIdentity, identity_id)
            if identity is not None:
                notice(uow, identity, ASSISTANT_UNAVAILABLE, key=f"turn_failed:{wamid}", reply_to=wamid)
        return None


# ---- assistant replies -------------------------------------------------------------------------------------------
def _arm(uow: UnitOfWork, identity: ChannelIdentity, button: ButtonSpec) -> dict[str, str]:
    assert identity.user_id is not None
    action = {"option": "choose_option", "review": "open", "open": "open"}.get(button.kind, "open")
    ref = action_refs.arm(
        uow, user_id=identity.user_id, identity_id=identity.id, action=action,
        option_payload={"kind": button.kind, "label": button.title, **{k: v for k, v in button.data.items() if v is not None}},
    )
    return {"id": action_refs.button_id(ref), "title": button.title, "ref": str(ref.id)}


def reply_for_run(uow: UnitOfWork, run_id: uuid.UUID, *, failed: bool) -> bool:
    """Queue the WhatsApp reply for a finished run started from WhatsApp; True when a reply was queued."""
    from app.modules.agents.models import Run, Turn

    inbound = uow.session.scalars(
        select(ChannelMessage).where(ChannelMessage.company_id == uow.actor.company_id, ChannelMessage.run_id == run_id, ChannelMessage.direction == "inbound")
    ).first()
    if inbound is None:
        return False
    identity = uow.session.get(ChannelIdentity, inbound.identity_id)
    run = uow.session.get(Run, run_id)
    if identity is None or run is None or identity.status != "active":
        return False
    turn = uow.session.get(Turn, run.assistant_turn_id) if run.assistant_turn_id else None
    cards: list[dict[str, Any]] = list(turn.cards or []) if turn is not None else []
    text = turn.text if turn is not None else None
    demo = _account(uow, identity).mode == "demo"
    rendered = render_turn(text, cards, demo=demo, failed=failed or run.status != "succeeded")
    key = f"run:{run_id}"
    if rendered.buttons:
        buttons = [_arm(uow, identity, b) for b in rendered.buttons]
        outbox = outbound.queue_message(
            uow, identity, kind="interactive",
            payload={"type": "interactive", "text": rendered.text, "buttons": [{"id": b["id"], "title": b["title"]} for b in buttons]},
            text=rendered.text, idempotency_key=key, cause_ref=f"agents.run:{run_id}", run_id=run_id, reply_to=inbound.provider_message_id,
        )
        refs = [action_refs.get(uow, uuid.UUID(b["ref"])) for b in buttons]
        action_refs.bind_message(uow, [r for r in refs if r is not None], outbox.message_id)  # type: ignore[arg-type]
    else:
        outbound.queue_message(
            uow, identity, kind="session", payload={"type": "text", "text": rendered.text}, text=rendered.text,
            idempotency_key=key, cause_ref=f"agents.run:{run_id}", run_id=run_id, reply_to=inbound.provider_message_id,
        )
    return True


# ---- buttons -----------------------------------------------------------------------------------------------------
REF_OUTCOME_TEXT = {
    "unknown": "That button is not valid any more. Send your request again or open the web app.",
    "wrong_identity": "That button belongs to another conversation.",
    "expired": "That button has expired. Send your request again for fresh options.",
    "consumed": "That button was already used.",
    "voided": "That request is no longer open (it was decided, expired or changed). Nothing was done.",
    "stale": "That reply came before the options were offered; please choose again.",
}


def handle_button(uow: UnitOfWork, identity: ChannelIdentity, reply_id: str, *, wamid: str, provider_ts: Any) -> dict[str, Any] | None:
    """Consume the button; returns a follow-up for after commit ({"turn": {...}}) or None."""
    nonce = action_refs.nonce_from_button_id(reply_id)
    if nonce is None:
        notice(uow, identity, REF_OUTCOME_TEXT["unknown"], key=f"btn:{wamid}", reply_to=wamid)
        return None
    ref, outcome = action_refs.consume(uow, nonce, identity_id=identity.id, now=uow.now(), provider_ts=provider_ts)
    if ref is None or outcome != "ok":
        notice(uow, identity, REF_OUTCOME_TEXT.get(outcome, REF_OUTCOME_TEXT["unknown"]), key=f"btn:{wamid}", reply_to=wamid)
        return None
    data = dict(ref.option_payload or {})
    kind = data.get("kind") or ref.action
    if ref.action == "choose_option" and data.get("slot") and data.get("value") is not None:
        return {"turn": {"text": str(data.get("label") or data["value"]), "selected_option": {"slot": str(data["slot"]), "value": str(data["value"])}}}
    if ref.action in ("approve", "reject", "confirm") or (kind == "review" and data.get("target_id")):
        purpose = ReviewPurpose.DECIDE if ref.action in ("approve", "reject", "confirm") else ReviewPurpose.VIEW
        target_type = str(data.get("target_type") or ("approvals.proposal" if ref.proposal_id else "page"))
        target_id = uuid.UUID(str(data.get("target_id") or ref.proposal_id or ref.id))
        path = str(data.get("path") or (f"/inbox/approvals/{ref.proposal_id}" if ref.proposal_id else "/today"))
        assert identity.user_id is not None
        _row, token = review_links.create(uow, user_id=identity.user_id, target_type=target_type, target_id=target_id,
                                          redirect_path=path, proposal_id=ref.proposal_id, purpose=purpose)
        text = f"Review on the web (sign in as yourself; the link works for 15 minutes): {app_url(review_links.url_path(token))}"
        notice(uow, identity, text, key=f"btn:{wamid}", reply_to=wamid)
        return None
    path = str(data.get("path") or "/today")
    notice(uow, identity, f"Open the workspace: {app_url(path)}", key=f"btn:{wamid}", reply_to=wamid)
    return None


__all__ = [
    "ASSISTANT_UNAVAILABLE", "NOT_LINKED", "REF_OUTCOME_TEXT", "UNSUPPORTED", "app_url", "handle_button", "member_actor", "notice",
    "reply_for_run", "submit_turn", "utterance_id",
]
