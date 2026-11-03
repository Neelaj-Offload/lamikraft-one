"""Channels module manifest: models, policies, the WhatsApp worker jobs (inbox processing, outbox sending,
reconciliation, template sync), the reconcile schedule, subscriptions, the ``prepare_quote_send`` agent tool and
the API (channels endpoints, the public webhook and review links). ``on_load`` registers the
``channels.message.send`` approval handler and the WhatsApp integration definition with its verification."""

from __future__ import annotations

from typing import Any

from app.modules.channels import events as ev
from app.modules.channels.policies import POLICIES
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.channels.router import router

    return router


def _webhook_router() -> Any:
    from app.modules.channels.webhook import router

    return router


def _review_router() -> Any:
    from app.modules.channels.router import review_router

    return review_router


def _inbox_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.channels.whatsapp import inbound

    return inbound.process_inbox_job(ctx, payload)


def _send_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.channels.whatsapp import outbound

    return outbound.send_job(ctx, payload)


def _reconcile_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.channels.whatsapp import reconcile

    return reconcile.reconcile_job(ctx, payload)


def _templates_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.channels.whatsapp import templates

    return templates.sync_job(ctx, payload)


def _on_load() -> None:
    from app.modules.channels import send_approval
    from app.modules.channels.whatsapp import accounts

    send_approval.register()
    accounts.register_integration_def()


def _tools() -> list[Any]:
    from app.modules.channels.tools import TOOLS

    return list(TOOLS)


MANIFEST = ModuleManifest(
    name="channels",
    models=("app.modules.channels.models",),
    policies=list(POLICIES),
    subscriptions=list(ev.SUBSCRIPTIONS),
    jobs=[
        JobDef(ev.JOB_INBOX_PROCESS, _inbox_job, queue=ev.JOB_QUEUE, max_attempts=6, lease_seconds=120),
        #: one attempt per job: retries are business decisions recorded on the outbox row (never a blind resend)
        JobDef(ev.JOB_OUTBOX_SEND, _send_job, queue=ev.JOB_QUEUE, max_attempts=1, lease_seconds=120),
        JobDef(ev.JOB_OUTBOX_RECONCILE, _reconcile_job, queue=ev.JOB_QUEUE, max_attempts=3),
        JobDef(ev.JOB_TEMPLATES_SYNC, _templates_job, queue=ev.JOB_QUEUE, max_attempts=3),
    ],
    schedules=[ScheduleDef("channels.outbox_reconcile", ev.JOB_OUTBOX_RECONCILE, "interval", interval_seconds=60)],
    tools=_tools(),
    routers=[_router, _webhook_router, _review_router],
    on_load=_on_load,
)
