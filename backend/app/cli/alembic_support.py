"""Alembic helpers for ``lk db migrate|heads|reparent`` (the migration environment itself is
``backend/alembic.ini`` + ``backend/migrations/``)."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.cli import EXIT_UNAVAILABLE, CliError
from app.cli.paths import alembic_ini_path

if TYPE_CHECKING:
    from alembic.config import Config
    from alembic.script import ScriptDirectory


def load_config() -> Config:
    from alembic.config import Config

    ini = alembic_ini_path()
    if not ini.is_file():
        raise CliError(
            f"{ini.as_posix()} does not exist yet, so there is no migration environment",
            code=EXIT_UNAVAILABLE,
            hint="the integrator lane creates backend/alembic.ini and backend/migrations/env.py",
        )
    cfg = Config(str(ini))
    location = cfg.get_main_option("script_location")
    if not location:
        raise CliError(f"{ini.as_posix()} has no script_location")
    # Resolve a relative script_location against the ini file, not the current directory
    # ("package:dir" resource locations are left to Alembic).
    if not Path(location).is_absolute() and ":" not in location:
        cfg.set_main_option("script_location", str((ini.parent / location).resolve()))
    return cfg


def script_directory(cfg: Config | None = None) -> ScriptDirectory:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(cfg or load_config())


def _down_revisions(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def heads_excluding(graph: Mapping[str, tuple[str, ...]], revision: str | None) -> list[str]:
    """Heads of the revision graph after removing ``revision`` and everything that descends from it.

    ``graph`` maps each revision id to its down revisions.
    """
    children: dict[str, set[str]] = {rev: set() for rev in graph}
    for rev, downs in graph.items():
        for down in downs:
            children.setdefault(down, set()).add(rev)
    excluded: set[str] = set()
    if revision is not None:
        stack = [revision]
        while stack:
            current = stack.pop()
            if current in excluded:
                continue
            excluded.add(current)
            stack.extend(children.get(current, ()))
    remaining = [rev for rev in graph if rev not in excluded]
    return sorted(rev for rev in remaining if not (children.get(rev, set()) - excluded))


def revision_graph(script: ScriptDirectory) -> dict[str, tuple[str, ...]]:
    return {s.revision: _down_revisions(s.down_revision) for s in script.walk_revisions()}


@dataclass(frozen=True, slots=True)
class RevisionFile:
    revision: str
    down_revision: tuple[str, ...]


def _module_assignment(tree: ast.Module, name: str) -> ast.expr | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    return None


def read_revision_file(data: bytes, path: Path) -> tuple[RevisionFile, ast.expr]:
    try:
        tree = ast.parse(data, filename=str(path))
    except SyntaxError as exc:
        raise CliError(f"{path.as_posix()} is not valid Python: {exc}") from exc
    revision_node = _module_assignment(tree, "revision")
    down_node = _module_assignment(tree, "down_revision")
    if not (isinstance(revision_node, ast.Constant) and isinstance(revision_node.value, str)):
        raise CliError(f"{path.as_posix()} has no string 'revision = ...' assignment")
    if down_node is None:
        raise CliError(f"{path.as_posix()} has no 'down_revision = ...' assignment")
    try:
        down_value = ast.literal_eval(down_node)
    except ValueError as exc:
        raise CliError(f"{path.as_posix()}: down_revision is not a literal") from exc
    return RevisionFile(revision_node.value, _down_revisions(down_value)), down_node


def rewrite_down_revision(data: bytes, node: ast.expr, new_down: str | None) -> bytes:
    """Replace the ``down_revision`` value (and the docstring ``Revises:`` line), byte-exactly."""
    lines = data.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    if node.end_lineno is None or node.end_col_offset is None:
        raise CliError("cannot locate the down_revision value in the file")
    start = offsets[node.lineno - 1] + node.col_offset  # ast offsets are UTF-8 byte offsets
    end = offsets[node.end_lineno - 1] + node.end_col_offset
    original = data[start:end]
    first_quote = re.search(rb"['\"]", original)  # keep the file's quote style
    quote = first_quote.group(0) if first_quote else b'"'
    replacement = b"None" if new_down is None else quote + new_down.encode() + quote
    updated = data[:start] + replacement + data[end:]
    revises = re.compile(rb"^(Revises:)[ \t]*[^\r\n]*", re.MULTILINE)
    return revises.sub(
        lambda m: m.group(1) + (b" " + new_down.encode() if new_down else b""), updated, count=1
    )


def reparent(path: Path, graph: Mapping[str, tuple[str, ...]]) -> tuple[RevisionFile, str | None]:
    """Point ``path``'s down_revision at the single head that excludes the file itself."""
    data = path.read_bytes()
    info, node = read_revision_file(data, path)
    heads = heads_excluding(graph, info.revision)
    if len(heads) > 1:
        raise CliError(
            f"cannot reparent {path.name}: the remaining history has {len(heads)} heads ({', '.join(heads)})",
            hint="reparent or merge the other branch first so exactly one head remains",
        )
    new_down = heads[0] if heads else None
    if info.down_revision != _down_revisions(new_down):
        path.write_bytes(rewrite_down_revision(data, node, new_down))
    return info, new_down
