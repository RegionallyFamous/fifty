#!/usr/bin/env python3
"""Apply ``<theme>/microcopy-overrides.json`` to the theme's source files.

The overrides file is a plain ``{needle: replacement}`` JSON dict.  Every
occurrence of a ``needle`` string in the theme's ``templates/``, ``parts/``,
and ``patterns/`` directories is replaced with the corresponding value.
Replacements are applied with ``str.replace`` so they are literal and exact.
Cascade-safety check: any pair where the replacement contains the needle as a
substring is rejected before writing so re-runs are idempotent.

Usage
-----
    python3 bin/apply-microcopy-overrides.py --theme agave
    python3 bin/apply-microcopy-overrides.py --theme agave --dry-run

Exit codes
----------
    0  Applied (or nothing to do).
    1  Cascade-hazard detected, or I/O error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, resolve_theme_root

SCAN_DIRS = ("templates", "parts", "patterns")
SCAN_EXT = {".html", ".php"}


def _check_cascade_safety(overrides: dict[str, str]) -> list[tuple[str, str]]:
    """Return any (needle, replacement) pairs where replacement ⊃ needle."""
    return [
        (needle, repl)
        for needle, repl in overrides.items()
        if needle in repl
    ]


def apply_overrides(
    theme_root: Path,
    overrides: dict[str, str],
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> tuple[int, int]:
    """Apply substitutions; return (files_touched, subs_made)."""
    slug = theme_root.name
    files_touched = 0
    subs_made = 0

    for sub in SCAN_DIRS:
        d = theme_root / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_EXT:
                continue
            try:
                original = path.read_text(encoding="utf-8")
            except OSError:
                continue
            updated = original
            file_subs = 0
            for needle, replacement in overrides.items():
                if needle not in updated:
                    continue
                count = updated.count(needle)
                updated = updated.replace(needle, replacement)
                file_subs += count
            if updated != original:
                files_touched += 1
                subs_made += file_subs
                if not dry_run:
                    path.write_text(updated, encoding="utf-8")
                rel = path.relative_to(theme_root).as_posix()
                marker = "(dry-run) " if dry_run else ""
                if not quiet:
                    print(f"  {slug:9s} {rel:50s} {file_subs} sub(s) {marker}")

    return files_touched, subs_made


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", metavar="SLUG", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    theme_root = resolve_theme_root(args.theme)
    overrides_path = theme_root / "microcopy-overrides.json"
    if not overrides_path.is_file():
        if not args.quiet:
            try:
                rel = overrides_path.relative_to(MONOREPO_ROOT)
            except ValueError:
                rel = overrides_path
            print(f"No {rel} found — nothing to apply.")
        return 0

    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not overrides:
        return 0

    bad = _check_cascade_safety(overrides)
    if bad:
        print("ERROR: cascade-hazard substitutions detected — refusing to apply:",
              file=sys.stderr)
        for n, r in bad:
            print(f"  needle={n!r}  repl={r!r}", file=sys.stderr)
        return 1

    files, subs = apply_overrides(
        theme_root, overrides, dry_run=args.dry_run, quiet=args.quiet
    )
    label = "would touch" if args.dry_run else "touched"
    if not args.quiet:
        print(f"{label} {files} file(s); {subs} substitution(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
