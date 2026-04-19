#!/usr/bin/env python3
"""Inline shared playground PHP scripts into every theme's playground/blueprint.json.

Why this exists:
    Playground blueprints can fetch a script via writeFile { resource: url },
    but raw.githubusercontent.com sets cache-control: max-age=300 on every
    response, and Playground's own resource layer caches URL fetches across
    boot attempts. The result is that updates to playground/*.php can take
    5+ minutes to propagate, and Playground will happily run the previous
    version of the script against the new blueprint.

    Inlining the scripts directly into each blueprint.json makes every script
    body part of the same payload as the blueprint itself: there is only one
    URL to invalidate, and it is fetched fresh on every boot anyway.

What this script does:
    For every theme in the monorepo (any sibling of bin/ that contains a
    theme.json AND a playground/blueprint.json) it walks the blueprint's
    `steps` array, finds every `writeFile` step whose target path matches a
    known shared script, and replaces the `data` field with the current
    content of that source file from playground/.

    Themes are discovered automatically via _lib.iter_themes(); there is
    intentionally no hardcoded theme list here. Add a new theme variant by
    cloning obel via bin/clone.py (which copies playground/blueprint.json
    and rewrites the slug) — the next run of this script picks it up
    without any code change.

    Special case — wo-configure.php:
        The source file (playground/wo-configure.php) is theme-agnostic. Each
        theme needs its own WO_THEME_NAME constant, derived from that
        theme's theme.json `title` (falling back to the title-cased slug if
        title is missing). This script prepends:

            <?php define('WO_THEME_NAME', '<Theme>');

        …to the inlined data field so the shared source stays clean.
        The source file must NOT start with <?php (it starts with a doc-comment
        protected by `if (!defined('ABSPATH')) exit;`).

Usage:
    python3 bin/sync-playground.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes  # noqa: E402

# Map each blueprint writeFile target path -> source file path (relative to ROOT).
MAPPINGS: dict[str, Path] = {
    "/wordpress/wo-import.php":
        MONOREPO_ROOT / "playground" / "wo-import.php",
    "/wordpress/wo-configure.php":
        MONOREPO_ROOT / "playground" / "wo-configure.php",
    "/wordpress/wp-content/mu-plugins/wo-cart-mu.php":
        MONOREPO_ROOT / "playground" / "wo-cart-mu.php",
}


def theme_display_name(theme_dir: Path) -> str:
    """Return the human-readable theme name from theme.json `title`,
    falling back to the title-cased directory slug.

    Used as the WO_THEME_NAME constant prepended to wo-configure.php so
    the demo storefront tagline / blogname read "<Theme> demo storefront"
    instead of the generic "Demo".
    """
    theme_json = theme_dir / "theme.json"
    if theme_json.is_file():
        try:
            data = json.loads(theme_json.read_text())
            title = data.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        except (OSError, json.JSONDecodeError):
            pass
    slug = theme_dir.name
    return slug[:1].upper() + slug[1:].lower()


def build_body(target_path: str, source_path: Path, theme_name: str) -> str:
    """Read source_path and optionally prepend the theme-name define."""
    body = source_path.read_text()
    if target_path == "/wordpress/wo-configure.php":
        define_line = f"<?php define('WO_THEME_NAME', '{theme_name}');\n"
        # Strip the opening <?php from the source so we don't get two opening tags.
        stripped = body.lstrip()
        if stripped.startswith("<?php"):
            stripped = stripped[5:].lstrip("\n")
        body = define_line + stripped
    return body


def sync(theme_dir: Path) -> list[str]:
    """Sync all writeFile targets for a single theme. Returns list of updated paths."""
    bp_path = theme_dir / "playground" / "blueprint.json"
    if not bp_path.exists():
        # A theme without a Playground blueprint is a real bug — every theme
        # in this monorepo is expected to ship one (see AGENTS.md). Surface
        # it loudly so the omission is fixed, not silently skipped.
        print(
            f"warn: {theme_dir.name} has no playground/blueprint.json — "
            f"every theme must ship one. Re-clone via bin/clone.py or copy "
            f"obel/playground/blueprint.json and adjust the slug.",
            file=sys.stderr,
        )
        return []

    bp = json.loads(bp_path.read_text())
    theme_name = theme_display_name(theme_dir)
    updated: list[str] = []

    for step in bp.get("steps", []):
        if step.get("step") != "writeFile":
            continue
        target = step.get("path", "")
        if target not in MAPPINGS:
            continue
        source = MAPPINGS[target]
        if not source.exists():
            print(f"warn: source {source} not found for step path {target}", file=sys.stderr)
            continue

        body = build_body(target, source, theme_name)
        if step.get("data") == body:
            continue  # already in sync; skip to keep git diffs clean

        step["data"] = body
        updated.append(target)

    if updated:
        bp_path.write_text(json.dumps(bp, indent=2) + "\n")

    return updated


def main() -> int:
    # Verify all source files exist before touching any blueprint.
    missing = [p for p in MAPPINGS.values() if not p.exists()]
    if missing:
        for p in missing:
            print(f"error: source file not found: {p}", file=sys.stderr)
        return 1

    themes = list(iter_themes())
    if not themes:
        print("error: no themes found in monorepo", file=sys.stderr)
        return 1

    any_changed = False
    for theme_dir in themes:
        updated = sync(theme_dir)
        if updated:
            any_changed = True
            for path in updated:
                print(f"updated {theme_dir.name}: {path}")

    if not any_changed:
        print(f"already in sync ({len(themes)} themes checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
