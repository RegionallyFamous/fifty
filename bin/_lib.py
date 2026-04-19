"""Shared helpers for the Fifty monorepo bin/ scripts.

The bin/ scripts live at the monorepo root and operate on a single theme at a
time. Each script resolves its target theme via :func:`resolve_theme_root`:

* If the user passes a positional theme name (e.g. ``python3 bin/check.py obel``),
  resolve it as a sibling directory of bin/.
* Otherwise, if the current working directory contains a ``theme.json``, treat
  cwd as the target theme.
* Otherwise, error out.

Scripts should also expose ``--all`` where it makes sense (check, build-index,
list-tokens) to iterate every theme in the monorepo.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable


MONOREPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_theme_root(name: str | None = None) -> Path:
    """Return the absolute path of the target theme directory.

    Raises :class:`SystemExit` with a helpful message if no theme can be
    determined.
    """
    if name:
        candidate = (MONOREPO_ROOT / name).resolve()
        if candidate.is_dir() and (candidate / "theme.json").is_file():
            return candidate
        # Allow passing an absolute or cwd-relative path too
        candidate = Path(name).resolve()
        if candidate.is_dir() and (candidate / "theme.json").is_file():
            return candidate
        raise SystemExit(
            f"Theme '{name}' not found. Looked in {MONOREPO_ROOT}/{name} and {Path(name).resolve()}."
        )

    cwd = Path.cwd()
    if (cwd / "theme.json").is_file():
        return cwd

    available = ", ".join(sorted(t.name for t in iter_themes())) or "(none found)"
    raise SystemExit(
        "No theme target. Either run from inside a theme directory (one with theme.json), "
        f"or pass a theme name. Available themes: {available}"
    )


def iter_themes(monorepo_root: Path = MONOREPO_ROOT) -> Iterable[Path]:
    """Yield every theme directory in the monorepo (any sibling of bin/ that
    contains theme.json)."""
    for entry in sorted(monorepo_root.iterdir()):
        if entry.is_dir() and not entry.name.startswith(".") and (entry / "theme.json").is_file():
            yield entry


def add_theme_arg(parser) -> None:
    """Add the standard ``theme`` positional argument and ``--all`` flag.

    Most scripts accept either:
        python3 bin/<script>.py [theme_name]
        python3 bin/<script>.py --all
    """
    parser.add_argument(
        "theme",
        nargs="?",
        default=None,
        help="Theme directory name (e.g. 'obel'). Defaults to cwd if it contains theme.json.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run against every theme in the monorepo.",
    )
