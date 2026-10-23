"""Download authorisation registry: files are authorised through the parents that reference them.

A module that stores file ids (quote documents, product media, the company logo, import jobs) registers one
checker for its resource type::

    register_file_access("sales.quote_document", checker)

``checker(uow, file_object)`` returns ``True`` when the actor may read a parent referencing the file,
``False`` when the file is referenced by this resource type but no such parent is readable, and ``None``
when this resource type does not reference the file at all. A download is allowed when any checker says
``True``; otherwise only the creator may download an export, or a file nothing references yet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.files.models import FileObject
    from app.platform.uow import UnitOfWork

FileAccessChecker = Callable[["UnitOfWork", "FileObject"], bool | None]

_CHECKERS: dict[str, FileAccessChecker] = {}


def register_file_access(resource_type: str, checker: FileAccessChecker) -> None:
    existing = _CHECKERS.get(resource_type)
    if existing is not None and existing is not checker:
        raise ValueError(f"file access for {resource_type} is already registered")
    _CHECKERS[resource_type] = checker


def unregister_file_access(resource_type: str) -> None:
    """Tests only: remove a checker registered for a test resource type."""
    _CHECKERS.pop(resource_type, None)


def registered_file_access() -> dict[str, FileAccessChecker]:
    return dict(sorted(_CHECKERS.items()))
