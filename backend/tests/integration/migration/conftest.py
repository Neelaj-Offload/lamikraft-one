"""Fixtures for the migration tests: the seeded catalogue world (parties, catalogue, pricing) and a private copy of
the synthetic legacy export per test."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.integration.catalogue.world import media_storage, member_actors, personas, world  # noqa: F401
from tests.integration.migration.helpers import FIXTURE


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    """A private copy of the synthetic export, so a test may edit files."""
    target = tmp_path / "legacy_export"
    shutil.copytree(FIXTURE, target)
    return target
