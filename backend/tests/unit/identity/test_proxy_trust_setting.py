"""LK_TRUSTED_PROXY_HOPS lives in core Settings; identity reads it through ``trusted_proxy_hops()``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings, reset_settings_cache
from app.platform.identity.config import trusted_proxy_hops


def test_proxy_hops_default_to_zero_and_are_bounded() -> None:
    assert Settings.model_fields["trusted_proxy_hops"].default == 0
    assert Settings(trusted_proxy_hops=1).trusted_proxy_hops == 1
    for bad in (-1, 6):
        with pytest.raises(ValidationError):
            Settings(trusted_proxy_hops=bad)


def test_identity_reads_the_core_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LK_TRUSTED_PROXY_HOPS", "1")
    reset_settings_cache()
    try:
        assert get_settings().trusted_proxy_hops == 1
        assert trusted_proxy_hops() == 1
    finally:
        monkeypatch.delenv("LK_TRUSTED_PROXY_HOPS")
        reset_settings_cache()
