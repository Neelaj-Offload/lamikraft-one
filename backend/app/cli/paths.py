"""Filesystem locations used by the CLI: the checkout this code runs from and the machine-shared dev home."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from app.cli import CliError

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEV_HOME_ENV = "LK_DEV_HOME"


def _is_repo_root(path: Path) -> bool:
    return (path / "package.json").is_file() and (path / "backend" / "pyproject.toml").is_file()


def repo_root() -> Path:
    """The root of the checkout (main tree or git worktree) that contains this backend.

    The CLI always acts on its own checkout, never on whatever directory it was started from, so
    two worktrees cannot write each other's ``.env``. In a worktree ``.git`` is a file, so the
    markers are the repository's own files; ``git rev-parse`` is only a fallback.
    """
    for candidate in (BACKEND_DIR.parent, *BACKEND_DIR.parent.parents):
        if _is_repo_root(candidate):
            return candidate
    git = shutil.which("git")
    if git:
        result = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
            [git, "-C", str(BACKEND_DIR), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            top = Path(result.stdout.strip())
            if _is_repo_root(top):
                return top
    raise CliError(
        f"cannot locate the repository root above {BACKEND_DIR}",
        hint="expected a directory containing package.json and backend/pyproject.toml",
    )


def dev_home() -> Path:
    """Machine-shared state for every worktree: dev secrets and the e2e lock (``~/.lamikraft-dev``)."""
    override = os.environ.get(DEV_HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / ".lamikraft-dev"


def shared_secrets_path() -> Path:
    return dev_home() / "dev-secrets.env"


def alembic_ini_path() -> Path:
    return BACKEND_DIR / "alembic.ini"
