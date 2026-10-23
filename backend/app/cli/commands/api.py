"""``lk api``: the deterministic OpenAPI export behind ``npm run api:generate`` / ``api:check``."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

from app.cli import EXIT_UNAVAILABLE, CliError, arg, command, err, group

group("api", "HTTP API contract tooling")


def render_openapi(spec: dict[str, object]) -> str:
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


@command(
    "api",
    "export-openapi",
    help="Write the FastAPI OpenAPI document as sorted, indented JSON",
    arguments=[
        arg("--out", required=True, help="output file ('-' for stdout); relative paths resolve from the cwd"),
        arg(
            "--env",
            choices=["development", "test", "production"],
            default="development",
            help="LK_ENV to build the app with (default development, so test-only routes are excluded)",
        ),
    ],
)
def export_openapi(args: argparse.Namespace) -> int:
    os.environ["LK_ENV"] = args.env
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    try:
        main_module = importlib.import_module("app.main")
    except ModuleNotFoundError as exc:
        if exc.name != "app.main":
            raise
        raise CliError(
            "app.main is not importable yet, so there is no API to export",
            code=EXIT_UNAVAILABLE,
            hint="the integrator lane provides backend/app/main.py with create_app()",
        ) from exc
    create_app = getattr(main_module, "create_app", None)
    if not callable(create_app):
        raise CliError("app.main does not define create_app()", code=EXIT_UNAVAILABLE)
    spec = create_app().openapi()
    text = render_openapi(spec)
    if args.out == "-":
        sys.stdout.write(text)
        return 0
    target = Path(args.out).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    paths = len(spec.get("paths", {}))
    schemas = len(spec.get("components", {}).get("schemas", {}))
    err(f"wrote {target.as_posix()} ({paths} paths, {schemas} schemas)")
    return 0
