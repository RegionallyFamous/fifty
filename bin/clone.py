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
import subprocess
import sys
from pathlib import Path

EDITABLE_SUFFIXES = {".php", ".json", ".html", ".md", ".txt", ".css"}
SKIP_DIRS = {".git", "node_modules", "vendor", "bin", "__pycache__"}

# Per-theme Playground content/assets are NOT copied during clone. They are
# populated by bin/seed-playground-content.py instead, which fills them
# from the canonical wonders-oddities source and rewrites every image URL
# to point at the new theme's own images/ folder. Skipping them here keeps
# the cloned theme's content set theme-correct from the first commit.
#
# styles/claude.json is also skipped: it was an experimental "Claude" style
# variation that the maintainer explicitly retired (chonk + aero both had
# it deleted in follow-up commits). Skipping at clone time stops it from
# silently re-appearing in every new theme.
SKIP_RELPATHS = {
    Path("playground") / "content",
    Path("playground") / "images",
    Path("styles") / "claude.json",
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
    from _lib import MONOREPO_ROOT

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
    parser.add_argument(
        "--snap",
        action="store_true",
        help=(
            "After the clone + slug-rewrite finish, immediately run "
            "`bin/snap.py shoot <new-theme>` and `bin/snap.py baseline "
            "<new-theme>` so the new theme starts with a committed "
            "baseline. Off by default because the new theme has no "
            "seeded content yet; pass --snap once you've completed the "
            "Next Steps below (especially seed-playground-content + "
            "sync-playground)."
        ),
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
    print("\nNext steps:")
    print(f"  1. cd {dest}")
    print("  2. Edit theme.json (set palette, fonts, layout sizes)")
    print("  3. Replace screenshot.png with your own (1200x900px recommended)")
    print("  4. Update style.css Author, Author URI, and Theme URI headers")
    print("  5. Replace or extend the starter patterns in patterns/")
    print("  6. Run `python3 bin/seed-playground-content.py` to populate")
    print(f"     {dest.name}/playground/content/ (CSV + WXR + category map) and")
    print(f"     {dest.name}/playground/images/ from the canonical W&O source,")
    print("     with every image URL rewritten to point at the new theme's")
    print("     own images folder. (This script intentionally did NOT copy")
    print(f"     {source.name}/playground/content or images — see SKIP_RELPATHS.)")
    print("  7. Run `python3 bin/sync-playground.py` so the new theme's")
    print("     playground/blueprint.json picks up the latest shared helpers")
    print("     and the per-theme constants are prepended to each inlined script")
    print(f"     (the blueprint itself was already copied from {source.name} and the")
    print(f"     '{source.name}' / '{title_case(source.name)}' identifiers were rewritten above)")
    print("  8. Run `python3 bin/build-redirects.py` to (re)generate the GH")
    print("     Pages short URLs for every theme. The new theme will be")
    print("     reachable at:")
    print(f"        https://demo.regionallyfamous.com/{dest.name}/")
    print("     (plus /shop/, /product/bottled-morning/, /cart/, …) as soon")
    print(f"     as you commit + push the new docs/{dest.name}/ folder and")
    print("     GH Pages picks up the change. GH Pages must be enabled once")
    print("     for the repo (Source: deploy from branch, Branch: main, Folder: /docs).")
    print("  9. Redesign templates/front-page.html. Hard rule: every theme's")
    print("     homepage must be STRUCTURALLY distinct from every sibling's —")
    print("     not just different colors. Change the section count, swap the")
    print("     dynamic-surface mix (woocommerce/product-collection vs terms-query")
    print("     vs query vs media-text vs cover), introduce your own hero pattern,")
    print("     or reorder. `bin/check.py check_front_page_unique_layout` enforces")
    print("     this — see AGENTS.md rule 8 and the SKILL.md hard-rule section")
    print("     'every theme's homepage layout must be unique'.")
    print(f"  10. Run `python3 bin/check.py {dest.name} --quick` and fix anything")
    print("      that fails (especially the front-page uniqueness check).")
    print(f"  11. Run `python3 bin/snap.py shoot {dest.name}` then")
    print(f"      `python3 bin/snap.py baseline {dest.name}` to seed")
    print(f"      tests/visual-baseline/{dest.name}/ with reference PNGs.")
    print("      (Or re-run this script with --snap to do steps 11+12 inline.)")
    print("  12. Commit and push everything (theme, blueprint, content, images,")
    print(f"      docs/, AND the new tests/visual-baseline/{dest.name}/ tree).")

    if args.snap:
        print(f"\n--snap: shooting {dest.name} and promoting to baseline...")
        # Run the snap pipeline from the monorepo root (where bin/snap.py
        # lives). A failure here is non-fatal -- the clone is still
        # complete and the user can re-run the snap step manually.
        snap_path = Path(__file__).resolve().parent / "snap.py"
        snap_cwd = MONOREPO_ROOT
        for cmd in (
            [sys.executable, str(snap_path), "shoot", dest.name],
            [sys.executable, str(snap_path), "baseline", dest.name],
            [sys.executable, str(snap_path), "report", dest.name],
        ):
            print(f"\n>> {' '.join(cmd[1:])}")
            rc = subprocess.call(cmd, cwd=str(snap_cwd))
            if rc != 0:
                print(f"   warn: command exited with {rc}; continuing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
