"""Module readiness checks for ``/health/ready``: a module registers ``fn() -> (status, healthy)`` in its manifest
``on_load``; an unhealthy check makes the probe answer 503 (e.g. voice in production with only the browser fallback).
A check that raises is reported as ``error`` and treated as unhealthy."""

from __future__ import annotations

from collections.abc import Callable

ReadinessCheck = Callable[[], tuple[str, bool]]

_CHECKS: dict[str, ReadinessCheck] = {}


def register_readiness_check(name: str, check: ReadinessCheck) -> None:
    _CHECKS[name] = check


def run_checks() -> tuple[dict[str, str], bool]:
    results: dict[str, str] = {}
    healthy = True
    for name in sorted(_CHECKS):
        try:
            status, ok = _CHECKS[name]()
        except Exception as exc:  # noqa: BLE001 - a probe never raises
            status, ok = f"error: {type(exc).__name__}", False
        results[name] = status
        healthy = healthy and ok
    return results, healthy


__all__ = ["ReadinessCheck", "register_readiness_check", "run_checks"]
