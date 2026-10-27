"""``lk admin create-first``, ``lk demo sign-in-link`` and ``lk seed demo`` against the test database."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli import main
from app.core.config import get_settings
from app.platform.identity.models import AppUser
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    login,
    make_member,
    make_tenant,
    origin_headers,
    system,
)

pytestmark = pytest.mark.db


def _create_first(monkeypatch: pytest.MonkeyPatch, password: str, *extra: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    return main(
        ["admin", "create-first", "--email", "owner@example.test", "--name", "Owner Person", "--password-stdin", *extra]
    )


def test_create_first_admin_once(db: None, client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    code = _create_first(monkeypatch, TEST_PASSWORD, "--company-key", "acme-test", "--company-name", "Acme Test Pvt. Ltd.")
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "company acme-test: created" in out.out and "administrator owner@example.test: created" in out.out
    with UnitOfWork(system(None)) as uow:
        company = uow.session.scalars(select(Company).where(Company.company_key == "acme-test")).one()
        assert not company.is_demo and company.legal_name == "Acme Test Pvt. Ltd."
        user = uow.session.scalars(select(AppUser).where(AppUser.email_normalized == "owner@example.test")).one()
        assert user.password_hash and user.password_hash.startswith("$argon2id$")
    signed = login(client, "owner@example.test")
    assert signed.status_code == 200
    boot = client.get("/api/v1/session/bootstrap").json()
    assert boot["membership"]["role_names"] == ["Admin"]
    assert {p["key"] for p in boot["permissions"]} >= {"identity.role.manage", "sales.quote.delete"}

    again = _create_first(monkeypatch, TEST_PASSWORD, "--company-key", "another-co")
    err = capsys.readouterr().err
    assert again == 1 and "already exists" in err
    with UnitOfWork(system(None)) as uow:
        assert uow.session.scalars(select(Company).where(Company.company_key == "another-co")).first() is None


def test_create_first_refuses_when_an_admin_exists_anywhere(db: None, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    tenant = make_tenant()
    make_member(tenant, ["admin"])
    assert _create_first(monkeypatch, TEST_PASSWORD) == 1
    assert "already exists" in capsys.readouterr().err


def test_create_first_enforces_the_password_policy(db: None, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    for weak in ("short-pass", "password1234", "owner-is-me-1234"):
        assert _create_first(monkeypatch, weak) == 1
    err = capsys.readouterr().err
    assert "validation_failed" in err
    with UnitOfWork(system(None)) as uow:
        assert uow.session.scalars(select(AppUser).where(AppUser.email_normalized == "owner@example.test")).first() is None


def test_create_first_needs_a_password_source(db: None, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code = main(["admin", "create-first", "--email", "owner@example.test", "--name", "Owner"])
    assert code == 1 and "password" in capsys.readouterr().err


def test_demo_sign_in_link_prints_a_fragment_url(client: TestClient, world: SeedContext, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["demo", "sign-in-link", "meera"]) == 0
    first_line = capsys.readouterr().out.splitlines()[0]
    prefix = f"http://127.0.0.1:{get_settings().web_port}/demo-sign-in#t="
    assert first_line.startswith(prefix) and "?" not in first_line
    token = first_line.removeprefix(prefix)
    r = client.post("/api/v1/identity/demo-sign-in", json={"token": token}, headers=origin_headers())
    assert r.status_code == 200 and r.json()["user"]["id"] == str(world.refs[keys.USERS.MEERA])


def test_demo_sign_in_link_errors(db: None, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["demo", "sign-in-link", "NOBODY"]) == 1
    assert "unknown user" in capsys.readouterr().err
    tenant = make_tenant()
    member = make_member(tenant, ["sales"])
    assert main(["demo", "sign-in-link", member.email, "--company", tenant.key]) == 1
    assert "not_demo_company" in capsys.readouterr().err


def test_seed_demo_command(db: None, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["seed", "demo", "--anchor-date", "2026-10-12"]) == 0
    out = capsys.readouterr().out
    assert "10:identity" in out and "anchored at 2026-10-12" in out
    assert all(key in out for key in ("SAHIL", "MEERA", "KABIR"))
    assert main(["seed", "demo", "--slice", "0"]) == 1
