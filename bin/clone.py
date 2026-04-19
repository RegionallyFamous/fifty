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
  5. Skips the source theme's playground/content/ and playground/images/
     folders. Per-theme Playground content lives there; the new theme should
     start empty and get seeded fresh by `bin/seed-playground-content.py`,
     which rewrites image URLs inside the CSV/XML to point at the new
     theme's own images folder. Copying obel's CSV/XML directly would
     leave the new theme pointing at obel's image URLs (clone.py's text
     substitution doesn't touch .csv/.xml).

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

# Per-theme Playground content/assets are NOT copied during clone. They are
# populated by bin/seed-playground-content.py instead, which fills them
# from the canonical wonders-oddities source and rewrites every image URL
# to point at the new theme's own images/ folder. Skipping them here keeps
# the cloned theme's content set theme-correct from the first commit.
SKIP_RELPATHS = {
    Path("playground") / "content",
    Path("playground") / "images",
}


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

    def ignore(dir_path: str, names: list[str]) -> list[str]:
        # Always skip the global SKIP_DIRS by name, and additionally skip
        # any directory whose path relative to src matches a SKIP_RELPATHS
        # entry. We compute the relative path on the parent directory
        # because `dir_path` here is the directory currently being copied.
        skipped = [n for n in names if n in SKIP_DIRS]
        rel_parent = Path(dir_path).relative_to(src)
        for n in names:
            rel = rel_parent / n
            if rel in SKIP_RELPATHS:
                skipped.append(n)
        return skipped

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
    print(f"  6. Run `python3 bin/seed-playground-content.py` to populate")
    print(f"     {dest.name}/playground/content/ (CSV + WXR + category map) and")
    print(f"     {dest.name}/playground/images/ from the canonical W&O source,")
    print(f"     with every image URL rewritten to point at the new theme's")
    print(f"     own images folder. (This script intentionally did NOT copy")
    print(f"     {source.name}/playground/content or images — see SKIP_RELPATHS.)")
    print(f"  7. Run `python3 bin/sync-playground.py` so the new theme's")
    print(f"     playground/blueprint.json picks up the latest shared helpers")
    print(f"     and the per-theme constants are prepended to each inlined script")
    print(f"     (the blueprint itself was already copied from {source.name} and the")
    print(f"     '{source.name}' / '{title_case(source.name)}' identifiers were rewritten above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
