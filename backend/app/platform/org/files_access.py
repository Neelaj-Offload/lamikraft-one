"""File access for files referenced by org settings: the company logo is branding every member may load
with ``org.settings.read`` (it appears in the shell and on documents)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.platform.org.models import Setting

if TYPE_CHECKING:
    from app.platform.files.models import FileObject
    from app.platform.uow import UnitOfWork


def company_logo_access(uow: UnitOfWork, file: FileObject) -> bool | None:
    referenced = uow.session.scalar(
        select(Setting.id).where(
            Setting.company_id == uow.actor.company_id,
            Setting.key == "company_identity",
            Setting.value["logo_file_id"].astext == str(file.id),
        )
    )
    if referenced is None:
        return None
    return uow.actor.can("org.settings.read")
