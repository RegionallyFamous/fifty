#!/usr/bin/env python3
"""Inline shared playground PHP scripts into every theme's playground/blueprint.json,
rewriting per-theme constants and the importWxr URL along the way.

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
    theme.json AND a playground/blueprint.json) this script:

      1. Walks the blueprint's `steps` array, finds every `writeFile`
         step whose target path matches a known shared script, and
         replaces the `data` field with the current content of that
         source file from playground/, prepending the per-theme
         constants block so the script knows which theme it's running
         against and where its content lives.

      2. Walks the same `steps` array, finds the `importWxr` step, and
         rewrites its URL to point at that theme's per-theme content.xml
         (under <theme>/playground/content/content.xml on the fifty
         monorepo on raw.githubusercontent.com).

    Themes are discovered automatically via _lib.iter_themes(); there is
    intentionally no hardcoded theme list here. Add a new theme variant by
    cloning obel via bin/clone.py (which copies playground/blueprint.json
    and rewrites the slug) — the next run of this script picks it up
    without any code change.

    Per-theme PHP constants prepended to every inlined script body:

        <?php
        define( 'WO_THEME_NAME', '<Theme>' );
        define( 'WO_THEME_SLUG', '<theme>' );
        define( 'WO_CONTENT_BASE_URL',
            'https://raw.githubusercontent.com/<org>/<repo>/<branch>/<theme>/playground/' );

    The shared scripts under playground/*.php are theme-agnostic; they
    read these constants instead of hardcoding any theme-specific URL
    or name. The source files MUST NOT start with <?php — they start
    with a doc-comment protected by `if (!defined('ABSPATH')) exit;`
    and this script supplies the opening tag along with the constants.

    The MU plugin (wo-cart-mu.php) is excepted: it does not need any
    constants, so it gets prepended only with `<?php\n` if its source
    file is missing one.

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

# Targets that should receive the WO_* constants block at the top.
# wo-cart-mu.php is excluded because it's an MU plugin that does not
# touch per-theme content; keeping it constant-free keeps the diff small.
TARGETS_NEEDING_CONSTANTS = {
    "/wordpress/wo-import.php",
    "/wordpress/wo-configure.php",
}

# The fifty monorepo on GitHub. Used to derive the per-theme content base
# URL that gets baked into each blueprint and into the inlined PHP. If we
# ever rename the GitHub org or repo, change this in one place.
GITHUB_ORG = "RegionallyFamous"
GITHUB_REPO = "fifty"
GITHUB_BRANCH = "main"


def theme_display_name(theme_dir: Path) -> str:
    """Return the human-readable theme name from theme.json `title`,
    falling back to the title-cased directory slug.

    Used as WO_THEME_NAME so the demo storefront tagline / blogname read
    "<Theme> demo storefront" instead of the generic "Demo".
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


def content_base_url(theme_slug: str) -> str:
    """Return the per-theme playground/ base URL on raw.githubusercontent.com.
    Trailing slash is significant — every PHP consumer concatenates a
    sub-path onto this prefix."""
    return (
        f"https://raw.githubusercontent.com/"
        f"{GITHUB_ORG}/{GITHUB_REPO}/{GITHUB_BRANCH}/{theme_slug}/playground/"
    )


def build_body(target_path: str, source_path: Path, theme_name: str, theme_slug: str) -> str:
    """Read source_path. For scripts that need theme-aware constants,
    prepend a `<?php define(...)` block with WO_THEME_NAME / WO_THEME_SLUG /
    WO_CONTENT_BASE_URL and strip the source's own `<?php` opener so we
    don't end up with two opening tags in the inlined body.

    PHP single-quoted string literals only escape backslash and single
    quote; we sanitise the theme name accordingly so a name containing an
    apostrophe (e.g. "Lina's Theme") cannot break out of the literal."""
    body = source_path.read_text()
    if target_path not in TARGETS_NEEDING_CONSTANTS:
        return body

    safe_name = theme_name.replace("\\", "\\\\").replace("'", "\\'")
    safe_slug = theme_slug.replace("\\", "\\\\").replace("'", "\\'")
    base_url = content_base_url(theme_slug)

    constants_block = (
        "<?php\n"
        f"define( 'WO_THEME_NAME', '{safe_name}' );\n"
        f"define( 'WO_THEME_SLUG', '{safe_slug}' );\n"
        f"define( 'WO_CONTENT_BASE_URL', '{base_url}' );\n"
    )

    stripped = body.lstrip()
    if stripped.startswith("<?php"):
        stripped = stripped[5:].lstrip("\n")
    return constants_block + stripped


def sync_write_file_steps(bp: dict, theme_name: str, theme_slug: str) -> list[str]:
    """Update every writeFile step whose target path matches a shared
    script. Returns the list of target paths that actually changed."""
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

        body = build_body(target, source, theme_name, theme_slug)
        if step.get("data") == body:
            continue
        step["data"] = body
        updated.append(target)
    return updated


def sync_import_wxr_step(bp: dict, theme_slug: str) -> bool:
    """Point the importWxr step at this theme's per-theme content.xml.
    Returns True if the URL changed.

    There must be exactly one importWxr step per blueprint. If the
    blueprint omits it entirely, return False without warning -- a theme
    that legitimately has no WXR to import is allowed to drop the step
    (though none currently do)."""
    expected_url = content_base_url(theme_slug) + "content/content.xml"
    changed = False
    for step in bp.get("steps", []):
        if step.get("step") != "importWxr":
            continue
        file_block = step.get("file") or {}
        if file_block.get("resource") != "url":
            continue
        if file_block.get("url") == expected_url:
            continue
        file_block["url"] = expected_url
        step["file"] = file_block
        changed = True
    return changed


def sync(theme_dir: Path) -> list[str]:
    """Sync the blueprint for a single theme. Returns the list of items
    that changed (writeFile target paths and/or 'importWxr')."""
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
    theme_slug = theme_dir.name

    updated = sync_write_file_steps(bp, theme_name, theme_slug)
    if sync_import_wxr_step(bp, theme_slug):
        updated.append("importWxr")

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
