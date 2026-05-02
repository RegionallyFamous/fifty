#!/usr/bin/env python3
"""One-shot migration: roll the latest cross-document View Transitions
contract from `obel/` to every other theme.

Why this exists: `bin/clone.py` mirrors `obel/` verbatim when creating a
NEW theme, but the five shipped non-obel themes (`aero`, `chonk`,
`foundry`, `lysholm`, `selvedge`) already have hand-tuned `theme.json`
styling and per-theme template tweaks that re-cloning would clobber.
So instead of re-cloning we surgically replace the VT block in each
theme's `theme.json` styles prelude + `functions.php`.

Idempotent: re-running is a no-op once every theme is up to date. Safe
to run repeatedly (the script reports "no change" rather than diffing).

The contract being migrated is documented in:
  - AGENTS.md "View Transitions (cross-document)"
  - bin/check.py rule #22 (`check_view_transitions_wired`)

Run from the repo root:
    python3 bin/migrate-view-transitions.py            # apply
    python3 bin/migrate-view-transitions.py --dry-run  # preview only
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "obel"
TARGETS = ("aero", "chonk", "ferment-co", "foundry", "lysholm", "selvedge")

# Sentinels used in BOTH source and target files. Anything between
# (and including) these markers is the migration unit.
PHP_BEGIN = "// === BEGIN view-transitions ==="
PHP_END = "// === END view-transitions ==="
CSS_BEGIN = "/* === BEGIN view-transitions === */"
CSS_END = "/* === END view-transitions === */"


def _slice_between(text: str, begin: str, end: str) -> str | None:
    """Return the text between (and including) begin..end markers, or
    None if either marker is missing."""
    i = text.find(begin)
    j = text.find(end)
    if i == -1 or j == -1 or j <= i:
        return None
    return text[i:j + len(end)]


def _read_source_blocks() -> tuple[str, str]:
    """Pull the two source blocks (PHP + CSS) from `obel/` so the
    migration always uses obel as the source of truth."""
    php_src = (SOURCE / "functions.php").read_text(encoding="utf-8")
    css_src = (SOURCE / "theme.json").read_text(encoding="utf-8")

    php_block = _slice_between(php_src, PHP_BEGIN, PHP_END)
    if php_block is None:
        sys.exit(
            f"obel/functions.php is missing the {PHP_BEGIN!r} … "
            f"{PHP_END!r} sentinels — migrate obel first."
        )

    css_block = _slice_between(css_src, CSS_BEGIN, CSS_END)
    if css_block is None:
        sys.exit(
            f"obel/theme.json is missing the {CSS_BEGIN!r} … "
            f"{CSS_END!r} sentinels — migrate obel first."
        )

    return php_block, css_block


# Old (pre-migration) PHP block. Matches the inherited shape: a doc
# comment introducing "Per-post View Transitions", the render_block
# add_filter, and the init add_action that resets the dedup tracker.
# Captures everything from the leading `/**` through the closing
# `);` of the init action.
_PHP_OLD_RE = re.compile(
    r"/\*\*\s*\n"
    r" \* Per-post View Transitions:.*?"
    r"add_action\(\s*\n"
    r"\t'init',.*?"
    r"\}\s*\n"
    r"\);",
    re.DOTALL,
)

# Old CSS prelude — the literal one-line opt-in that every theme
# inherited from obel before this migration. We match the
# `@view-transition{navigation:auto}` start and the
# `view-transition-name:fifty-site-title}` end, which are stable
# enough to anchor the replacement.
_CSS_OLD_RE = re.compile(
    r"@view-transition\{navigation:auto\}.*?"
    r"\.wp-block-site-title\{view-transition-name:fifty-site-title\}",
    re.DOTALL,
)

# CSS-block-with-sentinels (post-migration, for re-runs).
_CSS_SENTINEL_RE = re.compile(
    re.escape(CSS_BEGIN) + r".*?" + re.escape(CSS_END),
    re.DOTALL,
)
# PHP-block-with-sentinels (post-migration, for re-runs).
_PHP_SENTINEL_RE = re.compile(
    re.escape(PHP_BEGIN) + r".*?" + re.escape(PHP_END),
    re.DOTALL,
)


def _migrate_file(path: Path, sentinel_re: re.Pattern,
                  legacy_re: re.Pattern, replacement: str) -> str:
    """Returns one of {'updated', 'unchanged', 'not-found'}."""
    src = path.read_text(encoding="utf-8")
    if sentinel_re.search(src):
        new = sentinel_re.sub(_lit(replacement), src, count=1)
    elif legacy_re.search(src):
        new = legacy_re.sub(_lit(replacement), src, count=1)
    else:
        return "not-found"
    if new == src:
        return "unchanged"
    path.write_text(new, encoding="utf-8")
    return "updated"


def _lit(s: str) -> str:
    """Escape backreference markers in `re.sub` replacement strings.
    `\\1`, `\\g<…>`, etc. would otherwise be interpreted."""
    return s.replace("\\", "\\\\")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Roll the obel View Transitions contract to every "
                    "other theme."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing any files.",
    )
    parser.add_argument(
        "--themes", nargs="*", default=list(TARGETS),
        help=f"Theme dirs to migrate (default: {' '.join(TARGETS)})",
    )
    args = parser.parse_args()

    php_block, css_block = _read_source_blocks()

    rc = 0
    for theme in args.themes:
        tdir = ROOT / theme
        if not tdir.is_dir():
            print(f"  SKIP {theme}: directory missing")
            continue
        php_path = tdir / "functions.php"
        css_path = tdir / "theme.json"
        if not php_path.exists() or not css_path.exists():
            print(f"  SKIP {theme}: missing functions.php or theme.json")
            continue

        if args.dry_run:
            php_state = _dry_classify(php_path, _PHP_SENTINEL_RE, _PHP_OLD_RE)
            css_state = _dry_classify(css_path, _CSS_SENTINEL_RE, _CSS_OLD_RE)
            print(f"  DRY  {theme}: php={php_state} css={css_state}")
            continue

        php_state = _migrate_file(
            php_path, _PHP_SENTINEL_RE, _PHP_OLD_RE, php_block,
        )
        css_state = _migrate_file(
            css_path, _CSS_SENTINEL_RE, _CSS_OLD_RE, css_block,
        )
        print(f"  {theme}: php={php_state} css={css_state}")
        if php_state == "not-found" or css_state == "not-found":
            print(
                f"    ! could not locate the VT block in {theme}; this "
                f"theme may have been hand-edited and now needs manual "
                f"reconciliation against obel."
            )
            rc = 1

    return rc


def _dry_classify(path: Path, sentinel_re: re.Pattern,
                  legacy_re: re.Pattern) -> str:
    src = path.read_text(encoding="utf-8")
    if sentinel_re.search(src):
        return "would-replace-sentinels"
    if legacy_re.search(src):
        return "would-replace-legacy"
    return "not-found"


if __name__ == "__main__":
    sys.exit(main())
