"""Tests for `bin/check.py:check_block_text_contrast`.

The guarded failure mode:

    <!-- wp:group {"backgroundColor":"accent","textColor":"base"} -->
        ...
    <!-- /wp:group -->

On a theme whose `accent` happens to be a saturated mid-tone
(agave's #d87e3a at 2.64:1 vs the cream #f5efe6 base, chonk's #FFE600
at 1.12:1, lysholm's #C9A97C at 2.04:1), the group paints
unreadable text. `check_bordered_group_text_has_explicit_color` PASSES
on this because the group DOES declare textColor (the author "thought
about the cascade"). That check isn't wrong — it catches a different
failure mode. This one catches the mathematically-bad pair.

Palette slugs the minimal_theme fixture ships:

    base     #FAFAF7  (cream)
    contrast #1A1916  (near-black)
    primary  #3A352B  (dark warm)
    border   #D9D6CC  (light warm grey)

The `base` / `contrast` pair is ~20:1 — passing.
The `primary` / `contrast` pair is ~1.2:1 — failing.
We inject low-contrast pairs into the minimal theme to drive the
check red/green.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _set_palette(theme_root: Path, palette: list[dict]) -> None:
    data = json.loads((theme_root / "theme.json").read_text(encoding="utf-8"))
    data["settings"]["color"]["palette"] = palette
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


def test_passes_when_no_bg_textcolor_pairs(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>Undecorated.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_block_text_contrast().passed


def test_passes_when_pair_meets_wcag(minimal_theme, bind_check_root):
    """contrast (#1A1916) on base (#FAFAF7) is ~20:1."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"base","textColor":"contrast","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-contrast-color has-base-background-color has-text-color has-background">
            <!-- wp:paragraph -->
            <p>Legible.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_block_text_contrast().passed


def test_fails_when_pair_is_low_contrast(minimal_theme, bind_check_root):
    """Simulate the agave wordmark-band regression: base on accent
    (mid-tone orange) is 2.64:1 — below AA Normal."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"accent","textColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-base-color has-accent-background-color has-text-color has-background">
            <!-- wp:paragraph -->
            <p class="wordmark-band__ledger">Est. 1873 · Members only · Quiet goods</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = check.check_block_text_contrast()
    assert not result.passed
    # Failure message names the offending pair + the ratio + autofix.
    joined = "\n".join(result.details)
    assert "base" in joined
    assert "accent" in joined
    assert "2." in joined  # ratio string contains 2.xx
    assert "autofix-contrast.py" in joined


def test_fails_when_child_inherits_bad_pair(minimal_theme, bind_check_root):
    """The group sets backgroundColor:accent; a child paragraph declares
    textColor:base. The pair is split across two blocks but the
    resolved (text, bg) still fails. Only the paragraph (which
    introduces the textColor) should be reported — the ancestor group
    isn't flagged."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"accent","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-accent-background-color has-background">
            <!-- wp:paragraph {"textColor":"base"} -->
            <p class="has-base-color has-text-color">Invisible.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert not check.check_block_text_contrast().passed


def test_skips_non_text_blocks(minimal_theme, bind_check_root):
    """A cover block with textColor/backgroundColor shouldn't be
    flagged — cover's overlay layer owns its own contrast story and
    we don't apply the text-contrast rule to it."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:cover {"backgroundColor":"accent","textColor":"base"} -->
        <div class="wp-block-cover">
            <div class="wp-block-cover__inner-container">
                <!-- wp:paragraph -->
                <p>Cover caption.</p>
                <!-- /wp:paragraph -->
            </div>
        </div>
        <!-- /wp:cover -->
        """,
    )
    assert check.check_block_text_contrast().passed


def test_respects_contrast_skip_json(minimal_theme, bind_check_root):
    """contrast-skip.json lets the designer opt out of a specific
    (fg, bg) pair they've signed off as AA-Large-only or otherwise
    acceptable."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    (minimal_theme / "contrast-skip.json").write_text(
        json.dumps([{"fg": "base", "bg": "accent", "reason": "decorative band"}])
    )
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"accent","textColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>Skipped pair.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_block_text_contrast().passed
