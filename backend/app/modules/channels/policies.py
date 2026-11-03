"""Resource policies of the channels module.

The frozen catalogue has six ``channels.*`` keys and none of them follow the ``<prefix>.<action>`` pattern for
most tables, so every policy maps its actions to one catalogued key (``FixedKeyPolicy``). Record scope is
applied by the services (own identity, own messages, admin keys at company scope), never by the model alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.channels.models import (
    ActionRef,
    ChannelAccount,
    ChannelConsent,
    ChannelEnrolment,
    ChannelIdentity,
    ChannelMessage,
    ChannelSession,
    InboundEvent,
    MessageStatusEvent,
    OutboxMessage,
    ReviewLink,
    WaTemplate,
)
from app.platform.authz.policy import ParentRef, ResourcePolicy

IDENTITY_MANAGE = "channels.identity.manage"
ACCOUNT_MANAGE = "channels.account.manage"
MESSAGE_READ = "channels.message.read"
MESSAGE_SEND = "channels.message.send"
CONSENT_UPDATE = "channels.consent.update"
OUTBOX_MANAGE = "channels.outbox.manage"


@dataclass(frozen=True)
class FixedKeyPolicy(ResourcePolicy):
    """Every action needs the one catalogued key named by ``permission_prefix``."""

    def permission(self, action: str) -> str:  # noqa: ARG002 - the key does not vary by action
        return self.permission_prefix


ACCOUNT_POLICY = FixedKeyPolicy(
    resource_type="channels.account", model=ChannelAccount, permission_prefix=ACCOUNT_MANAGE,
    label=lambda a: f"WhatsApp {a.display_phone or a.phone_number_id}", canonical_path=lambda _a: "/settings/whatsapp",
    archived_column=None,
)
IDENTITY_POLICY = FixedKeyPolicy(
    resource_type="channels.identity", model=ChannelIdentity, permission_prefix=IDENTITY_MANAGE,
    owner_columns=("user_id",), canonical_path=lambda _i: "/settings/whatsapp", archived_column=None,
)
ENROLMENT_POLICY = FixedKeyPolicy(resource_type="channels.enrolment", model=ChannelEnrolment, permission_prefix=IDENTITY_MANAGE, owner_columns=("user_id",), archived_column=None)
SESSION_POLICY = ResourcePolicy(
    resource_type="channels.session", model=ChannelSession, permission_prefix="channels.identity",
    parent=ParentRef("channels.identity", "identity_id"), archived_column=None,
)
INBOUND_EVENT_POLICY = FixedKeyPolicy(resource_type="channels.inbound_event", model=InboundEvent, permission_prefix=OUTBOX_MANAGE, archived_column=None)
MESSAGE_POLICY = FixedKeyPolicy(
    resource_type="channels.message", model=ChannelMessage, permission_prefix=MESSAGE_READ,
    canonical_path=lambda _m: "/settings/whatsapp", archived_column=None,
)
STATUS_EVENT_POLICY = ResourcePolicy(
    resource_type="channels.message_status_event", model=MessageStatusEvent, permission_prefix="channels.message",
    parent=ParentRef("channels.message", "message_id"), archived_column=None,
)
OUTBOX_POLICY = FixedKeyPolicy(resource_type="channels.outbox_message", model=OutboxMessage, permission_prefix=OUTBOX_MANAGE, archived_column=None)
CONSENT_POLICY = ResourcePolicy(
    resource_type="channels.consent", model=ChannelConsent, permission_prefix="channels.consent",
    parent=ParentRef("channels.identity", "identity_id"), archived_column=None,
)
TEMPLATE_POLICY = FixedKeyPolicy(resource_type="channels.template", model=WaTemplate, permission_prefix=ACCOUNT_MANAGE, archived_column=None)
REVIEW_LINK_POLICY = FixedKeyPolicy(resource_type="channels.review_link", model=ReviewLink, permission_prefix=IDENTITY_MANAGE, owner_columns=("user_id",), archived_column=None)
ACTION_REF_POLICY = ResourcePolicy(
    resource_type="channels.action_ref", model=ActionRef, permission_prefix="channels.identity",
    parent=ParentRef("channels.identity", "identity_id"), archived_column=None,
)

POLICIES = [
    ACCOUNT_POLICY, IDENTITY_POLICY, ENROLMENT_POLICY, SESSION_POLICY, INBOUND_EVENT_POLICY, MESSAGE_POLICY,
    STATUS_EVENT_POLICY, OUTBOX_POLICY, CONSENT_POLICY, TEMPLATE_POLICY, REVIEW_LINK_POLICY, ACTION_REF_POLICY,
]

__all__ = ["ACCOUNT_MANAGE", "CONSENT_UPDATE", "IDENTITY_MANAGE", "MESSAGE_READ", "MESSAGE_SEND", "OUTBOX_MANAGE", "POLICIES", "FixedKeyPolicy"]
