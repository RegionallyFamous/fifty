#!/usr/bin/env python3
"""Rewrite `textColor` attributes on blocks whose resolved
(textColor, backgroundColor) pair fails WCAG AA against the theme's
palette.

Motivation
----------
`check_block_text_contrast()` catches the failure mode where a
`wp:group` or its children declare `{"textColor":"X","backgroundColor":"Y"}`
but X-on-Y is mathematically illegible in this theme's palette
(e.g. `base on accent` at 2.64:1 on agave's `#f5efe6 / #d87e3a`). That
check blocks the commit — this script repairs it. Run it as:

    python3 bin/autofix-contrast.py agave       # one theme
    python3 bin/autofix-contrast.py --all       # every theme

It re-parses each template/part/pattern, walks the block tree the
same way the check does, locates every block whose effective
(textColor, backgroundColor) fails WCAG AA (4.5:1) against the
palette, and rewrites `textColor` (NOT `backgroundColor` — the
designer picked the bg for a reason) to the best-contrast slug from
`contrast | base | secondary | tertiary`. If no candidate passes,
we leave the block alone and print a warning so a human picks a
different palette combination.

The script is idempotent: a clean re-run on an already-fixed tree
is a no-op. It writes the minimum diff (single attr per block) so
git blame stays readable.

Flags
-----
    --all               Run against every theme in the monorepo.
    --check             Dry-run: print the planned rewrites, exit 0
                        iff no rewrites needed, else 1. Used by the
                        pre-commit drift check.
    --quiet             Suppress per-file logging; only print summary.

Exit codes
----------
    0   Nothing to do, or rewrites applied successfully.
    1   --check mode: rewrites would be applied (so check fails).
    2   Rewrite failed (file i/o error, palette missing, etc.).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contrast import best_text_slug, contrast_ratio, load_palette
from _lib import iter_themes, resolve_theme_root

# --- Block walker + textColor rewriter ---------------------------------

_BLOCK_OPEN_RE = re.compile(
    r"<!--\s*wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)"
    r"(?:\s+(\{[^<>]*?\}))?\s*(/?)-->",
)
_BLOCK_CLOSE_RE = re.compile(
    r"<!--\s*/wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)\s*-->",
)
_TEXTCOLOR_RE = re.compile(r'"textColor"\s*:\s*"([a-z0-9-]+)"')
_BGCOLOR_RE = re.compile(r'"backgroundColor"\s*:\s*"([a-z0-9-]+)"')

# Same NON_TEXT_BLOCKS set as check_block_text_contrast.
_NON_TEXT_BLOCKS = {
    "spacer", "image", "gallery", "cover", "embed",
    "video", "audio", "separator", "html",
}


def _rewrite_file(
    path: Path,
    palette: dict[str, str],
    *,
    min_ratio: float,
    verbose: bool,
) -> tuple[str, list[str]]:
    """Return (new_text, messages). messages is a list of
    human-readable descriptions of each rewrite — empty list means
    no changes."""
    text = path.read_text(encoding="utf-8", errors="replace")
    messages: list[str] = []

    # We'll build a list of (span, replacement_json) rewrites, then
    # splice them in in reverse order so earlier offsets stay valid.
    rewrites: list[tuple[int, int, str]] = []

    # Stack tracks (text_slug, bg_slug) for each open block. We need
    # the stack to resolve inherited bg when a child declares only a
    # textColor (or vice versa).
    stack: list[tuple[str | None, str | None]] = []
    name_stack: list[str] = []

    pos = 0
    while True:
        m_open = _BLOCK_OPEN_RE.search(text, pos)
        m_close = _BLOCK_CLOSE_RE.search(text, pos)
        if m_open is None and m_close is None:
            break
        if m_open is not None and (m_close is None or m_open.start() < m_close.start()):
            name = m_open.group(1)
            block_json = m_open.group(2) or ""
            self_closing = m_open.group(3) == "/"
            short = name.split("/")[-1]

            t_match = _TEXTCOLOR_RE.search(block_json)
            b_match = _BGCOLOR_RE.search(block_json)
            local_text = t_match.group(1) if t_match else None
            local_bg = b_match.group(1) if b_match else None

            eff_text = local_text
            eff_bg = local_bg
            if eff_text is None:
                for st, _ in reversed(stack):
                    if st is not None:
                        eff_text = st
                        break
            if eff_bg is None:
                for _, sb in reversed(stack):
                    if sb is not None:
                        eff_bg = sb
                        break

            introduces_local = bool(local_text or local_bg)
            check_this = (
                short not in _NON_TEXT_BLOCKS
                and introduces_local
                and eff_text is not None
                and eff_bg is not None
                and eff_text in palette
                and eff_bg in palette
            )
            if check_this:
                assert eff_text is not None and eff_bg is not None
                try:
                    ratio = contrast_ratio(palette[eff_text], palette[eff_bg])
                except ValueError:
                    ratio = 0.0
                if ratio < min_ratio:
                    # Pick a replacement. We only rewrite `textColor`
                    # (never `backgroundColor`) — the designer's bg
                    # pick usually IS the intent, and the text is the
                    # inherited/defaulted side that needs correcting.
                    #
                    # Candidate list is ordered by "most likely to be
                    # text"; best_text_slug picks the highest-ratio
                    # candidate that meets min_ratio.
                    new_slug_and_ratio = best_text_slug(
                        palette[eff_bg],
                        palette,
                        candidates=(
                            "contrast", "base", "secondary", "tertiary",
                            "accent", "accent-2",
                        ),
                        min_ratio=min_ratio,
                    )
                    if new_slug_and_ratio is None:
                        messages.append(
                            f"WARN: no palette slug passes "
                            f"{min_ratio}:1 against "
                            f"backgroundColor:{eff_bg} (#{palette[eff_bg].lstrip('#')}); "
                            f"block `{name}` at offset {m_open.start()} "
                            f"needs a manual fix (try changing the "
                            f"backgroundColor)"
                        )
                    else:
                        new_slug, new_ratio = new_slug_and_ratio
                        # Where to inject the rewrite:
                        # - if local_text was already set, replace it
                        #   in-place in the block_json
                        # - else, we need to inject `"textColor":"<slug>"`
                        #   INTO the block_json. If the block_json is
                        #   empty (`"<!-- wp:paragraph -->"`), we need
                        #   to add the `{...}` too.
                        if local_text is not None and t_match is not None:
                            # Replace the existing textColor value.
                            # t_match is relative to block_json, which
                            # started at m_open.start() + "<!-- wp:<name> "
                            # but we have the exact match span; simpler
                            # to re-search in the file-slice between
                            # m_open.start() and m_open.end().
                            open_span = (m_open.start(), m_open.end())
                            slice_text = text[open_span[0] : open_span[1]]
                            new_slice = _TEXTCOLOR_RE.sub(
                                f'"textColor":"{new_slug}"',
                                slice_text,
                                count=1,
                            )
                            if new_slice != slice_text:
                                rewrites.append((open_span[0], open_span[1], new_slice))
                                messages.append(
                                    f"rewrite `{name}`: textColor "
                                    f"{eff_text} -> {new_slug} "
                                    f"({ratio:.2f}:1 -> {new_ratio:.2f}:1, "
                                    f"bg={eff_bg})"
                                )
                        else:
                            # Block inherits textColor from ancestor.
                            # Inject an explicit override on this block.
                            open_span = (m_open.start(), m_open.end())
                            slice_text = text[open_span[0] : open_span[1]]
                            if block_json:
                                # Insert `"textColor":"<slug>",` after
                                # the opening `{` of the attrs.
                                new_slice = re.sub(
                                    r"(\{)",
                                    f'{{"textColor":"{new_slug}",',
                                    slice_text,
                                    count=1,
                                )
                            else:
                                # `<!-- wp:<name> -->` → add attrs.
                                new_slice = re.sub(
                                    rf"(<!--\s*wp:{re.escape(name)})(\s*/?-->)",
                                    rf'\1 {{"textColor":"{new_slug}"}}\2',
                                    slice_text,
                                    count=1,
                                )
                            if new_slice != slice_text:
                                rewrites.append((open_span[0], open_span[1], new_slice))
                                messages.append(
                                    f"inject `{name}`: "
                                    f"textColor={new_slug} "
                                    f"(was inherited {eff_text} -> "
                                    f"{new_ratio:.2f}:1 vs bg={eff_bg})"
                                )

            if not self_closing:
                stack.append((local_text, local_bg))
                name_stack.append(name)
            pos = m_open.end()
        else:
            if stack and name_stack:
                stack.pop()
                name_stack.pop()
            pos = m_close.end()  # type: ignore[union-attr]

    # Splice rewrites from tail to head.
    if not rewrites:
        return text, messages

    new_text = text
    for start, end, replacement in sorted(rewrites, key=lambda s: s[0], reverse=True):
        new_text = new_text[:start] + replacement + new_text[end:]

    return new_text, messages


def _rewrite_css_hover_contrast(
    css: str,
    palette: dict[str, str],
    *,
    min_ratio: float = 3.0,
) -> tuple[str, list[str]]:
    """Scan CSS hover/focus rules and fix color-vs-background contrast.

    Any rule that sets ``color: var(--X)`` inside a ``:hover``/``:focus``/
    ``:focus-visible``/``:active`` selector, where the resolved color has
    < `min_ratio` contrast against the effective background, is rewritten:
    ``color: var(--X)`` → ``color: var(--<best_slug>)`` where
    ``<best_slug>`` is the palette token with the highest contrast against
    that background.

    Returns ``(new_css, [message, …])``.
    """
    # Match a :hover/:focus/:active/:focus-visible rule block, e.g.
    # ``.foo:hover { color: var(--base); background: var(--accent); }``
    # We handle both "standalone" and "comma-joined" selectors.
    _state_selectors_re = re.compile(
        r"(:hover|:focus(?:-visible)?|:active|:focus-within)",
    )
    _rule_re = re.compile(
        r"([^{}]+\{[^{}]*\})",
        re.DOTALL,
    )
    _color_var_re = re.compile(r"(?<![a-z-])color\s*:\s*var\(--([a-z0-9-]+)\)")
    _bg_var_re = re.compile(
        r"background(?:-color)?\s*:\s*var\(--([a-z0-9-]+)\)"
    )

    messages: list[str] = []
    rewrites: list[tuple[int, int, str]] = []

    for m in _rule_re.finditer(css):
        block = m.group(1)
        # Only look at state-selector rules
        if not _state_selectors_re.search(block):
            continue

        # Extract color + background var slugs from the rule body
        brace_open = block.index("{")
        selector = block[:brace_open]
        body = block[brace_open:]

        color_m = _color_var_re.search(body)
        bg_m = _bg_var_re.search(body)
        if not color_m:
            continue

        color_slug = color_m.group(1)
        bg_slug = bg_m.group(1) if bg_m else "base"

        color_hex = palette.get(color_slug, "")
        bg_hex = palette.get(bg_slug, "")
        if not color_hex or not bg_hex:
            continue

        ratio = contrast_ratio(color_hex, bg_hex)
        if ratio >= min_ratio:
            continue

        # Pick the best-contrast replacement from {contrast, base, secondary, tertiary}
        best = best_text_slug(bg_hex, palette)
        if best is None:
            continue
        new_slug, new_ratio = best

        if new_slug == color_slug:
            continue  # Already the best we can do

        messages.append(
            f"hover/focus rule `{selector.strip()[:60]}`: "
            f"color var(--{color_slug}) ({color_hex}) vs "
            f"bg var(--{bg_slug}) ({bg_hex}) = {ratio:.2f}:1 < {min_ratio}:1 → "
            f"var(--{new_slug}) ({new_ratio:.2f}:1)"
        )

        # Splice: rewrite the color var inside the body
        new_body = _color_var_re.sub(
            lambda mc, ns=new_slug: mc.group(0).replace(
                f"var(--{mc.group(1)})", f"var(--{ns})"
            ),
            body,
            count=1,
        )
        new_block = block[:brace_open] + new_body
        rewrites.append((m.start(), m.end(), new_block))

    if not rewrites:
        return css, messages

    new_css = css
    for start, end, replacement in sorted(rewrites, key=lambda s: s[0], reverse=True):
        new_css = new_css[:start] + replacement + new_css[end:]

    return new_css, messages


def _run_theme_css_contrast(
    theme_root: Path,
    *,
    check_only: bool,
    quiet: bool,
    min_ratio: float = 3.0,
) -> int:
    """Fix hover/focus contrast in the ``styles.css`` section of ``theme.json``.

    Returns 1 if a rewrite was made (or would be made in check mode), else 0.
    """
    tj_path = theme_root / "theme.json"
    if not tj_path.is_file():
        return 0

    palette = load_palette(tj_path)
    if not palette:
        return 0

    try:
        tj = json.loads(tj_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    css_original = tj.get("styles", {}).get("css", "")
    if not css_original:
        return 0

    new_css, messages = _rewrite_css_hover_contrast(
        css_original, palette, min_ratio=min_ratio
    )
    if not messages:
        return 0

    if not quiet:
        print(f"{theme_root.name}/theme.json styles.css hover-contrast:")
        for msg in messages:
            print(f"  - {msg}")

    if new_css != css_original and not check_only:
        tj["styles"]["css"] = new_css
        tj_path.write_text(json.dumps(tj, indent="\t", ensure_ascii=False) + "\n",
                           encoding="utf-8")

    return 1


def _run_theme(
    theme_root: Path,
    *,
    check_only: bool,
    quiet: bool,
    min_ratio: float,
    fix_css: bool = True,
) -> int:
    """Return number of files that changed (or would change)."""
    palette = load_palette(theme_root / "theme.json")
    if not palette:
        print(f"{theme_root.name}: palette missing or empty — skipping",
              file=sys.stderr)
        return 0

    total_changes = 0
    skip_dirs = ("templates", "parts", "patterns")
    for sub in skip_dirs:
        dir_ = theme_root / sub
        if not dir_.is_dir():
            continue
        for path in sorted(dir_.rglob("*.html")):
            new_text, messages = _rewrite_file(
                path, palette, min_ratio=min_ratio, verbose=not quiet
            )
            if not messages:
                continue
            rel = path.relative_to(theme_root).as_posix()
            if not quiet:
                print(f"{theme_root.name}/{rel}:")
                for msg in messages:
                    print(f"  - {msg}")
            original = path.read_text(encoding="utf-8", errors="replace")
            if new_text != original:
                total_changes += 1
                if not check_only:
                    path.write_text(new_text, encoding="utf-8")

    # Also fix CSS hover contrast in theme.json
    if fix_css:
        total_changes += _run_theme_css_contrast(
            theme_root, check_only=check_only, quiet=quiet, min_ratio=3.0
        )

    if total_changes == 0:
        if not quiet:
            print(f"{theme_root.name}: nothing to fix")
    else:
        verb = "would rewrite" if check_only else "rewrote"
        print(f"{theme_root.name}: {verb} {total_changes} file(s)")

    return total_changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme", nargs="?", default=None,
                        help="Theme directory name (or cwd if it has theme.json).")
    parser.add_argument("--all", action="store_true",
                        help="Run against every theme in the monorepo.")
    parser.add_argument("--check", action="store_true",
                        help="Dry-run: exit 1 if any file would change.")
    parser.add_argument("--quiet", action="store_true",
                        help="Only print a per-theme summary.")
    parser.add_argument("--min-ratio", type=float, default=4.5,
                        help="WCAG contrast floor. Default 4.5 (AA Normal).")
    args = parser.parse_args()

    if args.all:
        codes = []
        for theme_root in iter_themes():
            codes.append(_run_theme(
                theme_root,
                check_only=args.check,
                quiet=args.quiet,
                min_ratio=args.min_ratio,
            ))
        total = sum(codes)
        if args.check and total > 0:
            return 1
        return 0

    theme_root = resolve_theme_root(args.theme)
    changes = _run_theme(
        theme_root,
        check_only=args.check,
        quiet=args.quiet,
        min_ratio=args.min_ratio,
    )
    if args.check and changes > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
