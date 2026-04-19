#!/usr/bin/env python3
"""Clone Obel into a new theme folder, renaming all identifiers.

Cross-platform replacement for the macOS-only `sed` example in README.md.
Works on macOS, Linux, and Windows.

Usage:
    python3 bin/clone.py NEW_NAME [--target /path/to/parent/dir]

Examples:
    # Clone Obel into a sibling folder named "acme":
    python3 bin/clone.py acme

    # Clone into a specific destination:
    python3 bin/clone.py acme --target ~/Projects

What this script does:
  1. Copies the Obel theme folder to a new folder named NEW_NAME (lowercased).
  2. Replaces "Obel" with "Acme" (title-case) and "obel" with "acme" (lowercase)
     in every .php, .json, .html, .md, .txt, and .css file.
  3. Skips .git/, node_modules/, vendor/, and the bin/ folder.
  4. Skips binary files (screenshot.png, fonts).

Requires Python 3.8+ (standard library only).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

EDITABLE_SUFFIXES = {".php", ".json", ".html", ".md", ".txt", ".css"}
SKIP_DIRS = {".git", "node_modules", "vendor", "bin", "__pycache__"}


def title_case(name: str) -> str:
    """Return the new theme name with the first letter uppercased."""
    return name[:1].upper() + name[1:].lower()


def slug_validate(name: str) -> str:
    """Reject names that aren't safe theme slugs."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,38}", name.lower()):
        raise SystemExit(
            f"error: '{name}' is not a valid theme slug. "
            "Use lowercase letters, digits, and hyphens (start with a letter, max 39 chars)."
        )
    return name.lower()


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        raise SystemExit(f"error: destination {dst} already exists. Aborting.")

    def ignore(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n in SKIP_DIRS]

    shutil.copytree(src, dst, ignore=ignore)


def replace_in_file(path: Path, old_lower: str, new_lower: str, old_title: str, new_title: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return False

    new_text = text.replace(old_title, new_title).replace(old_lower, new_lower)

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _lib import MONOREPO_ROOT  # noqa: E402

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("new_name", help="New theme slug (lowercase, e.g. 'acme')")
    parser.add_argument(
        "--target",
        default=None,
        help="Parent directory to clone into. Defaults to the monorepo root (sibling of source).",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Path to the source theme folder. Defaults to <monorepo>/obel.",
    )
    args = parser.parse_args()

    new_lower = slug_validate(args.new_name)
    new_title = title_case(new_lower)

    source = Path(args.source) if args.source else MONOREPO_ROOT / "obel"
    if not source.is_dir():
        raise SystemExit(f"error: source folder {source} does not exist or is not a directory.")

    parent = Path(args.target).expanduser() if args.target else MONOREPO_ROOT
    parent.mkdir(parents=True, exist_ok=True)
    dest = parent / new_lower

    print(f"Cloning {source} -> {dest}")
    copy_tree(source, dest)

    print(f"Renaming 'Obel' -> '{new_title}' and 'obel' -> '{new_lower}' in editable files...")
    changed = 0
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in EDITABLE_SUFFIXES:
            continue
        if replace_in_file(path, "obel", new_lower, "Obel", new_title):
            changed += 1

    print(f"Done. {changed} files updated.")
    print(f"\nNext steps:")
    print(f"  1. cd {dest}")
    print(f"  2. Edit theme.json (set palette, fonts, layout sizes)")
    print(f"  3. Replace screenshot.png with your own (1200x900px recommended)")
    print(f"  4. Update style.css Author, Author URI, and Theme URI headers")
    print(f"  5. Replace or extend the starter patterns in patterns/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
