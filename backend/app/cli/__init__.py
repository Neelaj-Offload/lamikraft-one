"""The ``lk`` command-line tool: ``uv run python -m app.cli <group> <command> [options]``.

Commands live in ``app/cli/commands/<name>.py`` and are discovered automatically, so a lane adds
commands by dropping in a module, without editing a shared file::

    from app.cli import arg, command, group

    group("seed", "Demo and fixture data")

    @command("seed", "demo", help="Seed the demo company", arguments=[arg("--reset", action="store_true")])
    def seed_demo(args: argparse.Namespace) -> int | None:
        ...

Handlers return an exit code (``None`` means success) or raise :class:`CliError`. Command modules
must keep heavy imports (SQLAlchemy models, ``app.main``) inside their handlers so that
``lk --help`` and ``lk env init`` stay fast and work before the rest of the app exists.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3  # the command, or something it depends on, is not installed yet

Handler = Callable[[argparse.Namespace], int | None]


class CliError(Exception):
    """A user-facing failure: printed without a traceback, mapped to an exit code."""

    def __init__(self, message: str, *, code: int = EXIT_FAILURE, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


@dataclass(frozen=True, slots=True)
class Arg:
    flags: tuple[str, ...]
    options: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Command:
    group: str
    name: str
    help: str
    handler: Handler
    arguments: tuple[Arg, ...]
    module: str


_commands: dict[tuple[str, str], Command] = {}
_group_help: dict[str, str] = {}
_import_failures: dict[str, str] = {}
_discovered = False


def arg(*flags: str, **options: Any) -> Arg:
    """Declare one ``argparse.add_argument`` call for a command."""
    return Arg(flags, options)


def group(name: str, help: str) -> None:
    """Give a command group its one-line help text (optional; first declaration wins)."""
    _group_help.setdefault(name, help)


def command(
    group_name: str, name: str, *, help: str, arguments: Sequence[Arg] = ()
) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        key = (group_name, name)
        if key in _commands:
            raise RuntimeError(
                f"duplicate CLI command 'lk {group_name} {name}' (already defined in {_commands[key].module})"
            )
        _commands[key] = Command(group_name, name, help, fn, tuple(arguments), fn.__module__)
        return fn

    return decorator


def out(*parts: object) -> None:
    sys.stdout.write(" ".join(str(p) for p in parts) + "\n")
    sys.stdout.flush()  # keep order with stderr (library logging) when both are piped


def err(*parts: object) -> None:
    sys.stderr.write(" ".join(str(p) for p in parts) + "\n")


def discover() -> None:
    """Import every module in ``app.cli.commands``; a broken module disables only its own commands."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    from app.cli import commands as package

    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module_name = f"{package.__name__}.{info.name}"
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # a lane's import error must not take down every other command
            _import_failures[module_name] = f"{type(exc).__name__}: {exc}"


def registered() -> dict[tuple[str, str], Command]:
    discover()
    return dict(_commands)


def build_parser() -> argparse.ArgumentParser:
    discover()
    parser = argparse.ArgumentParser(
        prog="lk",
        description="Lamikraft One developer and operations CLI (run from backend/: uv run python -m app.cli).",
    )
    groups = parser.add_subparsers(dest="_group", metavar="<group>", required=True)
    for group_name in sorted({g for g, _ in _commands}):
        group_parser = groups.add_parser(group_name, help=_group_help.get(group_name, ""))
        subcommands = group_parser.add_subparsers(dest="_command", metavar="<command>", required=True)
        for (g, name), cmd in sorted(_commands.items()):
            if g != group_name:
                continue
            command_parser = subcommands.add_parser(name, help=cmd.help, description=cmd.help)
            for a in cmd.arguments:
                command_parser.add_argument(*a.flags, **a.options)
            command_parser.set_defaults(_handler=cmd.handler)
    return parser


def _unknown_command(argv: Sequence[str]) -> str | None:
    words = [w for w in argv if not w.startswith("-")]
    if not words or (argv and argv[0].startswith("-")):
        return None
    groups = {g for g, _ in _commands}
    if words[0] not in groups:
        return " ".join(words[:2])
    if len(words) > 1 and argv[1] == words[1] and (words[0], words[1]) not in _commands:
        return f"{words[0]} {words[1]}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    discover()
    for module_name, reason in _import_failures.items():
        err(f"warning: {module_name} failed to import ({reason}); its commands are unavailable")
    unknown = _unknown_command(args)
    if unknown is not None:
        err(f"error: 'lk {unknown}' is not an installed command.")
        err("hint: run 'lk --help' to list commands; lanes add commands as modules in app/cli/commands/.")
        return EXIT_UNAVAILABLE
    namespace = build_parser().parse_args(args)
    try:
        result = namespace._handler(namespace)
    except CliError as exc:
        err(f"error: {exc.message}")
        if exc.hint:
            err(f"hint: {exc.hint}")
        return exc.code
    except KeyboardInterrupt:
        err("interrupted")
        return 130
    return EXIT_OK if result is None else int(result)


__all__ = [
    "EXIT_FAILURE",
    "EXIT_OK",
    "EXIT_UNAVAILABLE",
    "EXIT_USAGE",
    "Arg",
    "CliError",
    "Command",
    "arg",
    "build_parser",
    "command",
    "discover",
    "err",
    "group",
    "main",
    "out",
    "registered",
]
