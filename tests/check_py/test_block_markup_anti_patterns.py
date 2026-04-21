"""Tests for `check_block_markup_anti_patterns`.

Three invariants, each surfaced by a regex. Regression risk is high
because the regexes are hand-written and intentionally narrow (they
must NOT flood with false positives on a 2700-block theme).
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Invariant 1: core/group with border.color MUST render has-border-color.
# ---------------------------------------------------------------------------
def test_group_with_border_color_and_class_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "archive.html",
        """\
        <!-- wp:group {"style":{"border":{"color":"var:preset|color|border","width":"1px"}}} -->
        <div class="wp-block-group has-border-color" style="border-color:var(--wp--preset--color--border);border-width:1px">
            <!-- wp:paragraph --><p>Bordered</p><!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_group_with_border_color_missing_class_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "archive.html",
        """\
        <!-- wp:group {"style":{"border":{"color":"var:preset|color|border","width":"1px"}}} -->
        <div class="wp-block-group" style="border-color:var(--wp--preset--color--border);border-width:1px">
            <!-- wp:paragraph --><p>No class</p><!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any("has-border-color" in d for d in result.details)


def test_group_without_border_color_passes(minimal_theme, bind_check_root):
    """A plain group with no border.color in JSON must not be flagged."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "archive.html",
        """\
        <!-- wp:group -->
        <div class="wp-block-group">
            <!-- wp:paragraph --><p>Plain</p><!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


# ---------------------------------------------------------------------------
# Invariant 2: core/paragraph must not carry legacy wo-empty__* classes.
# ---------------------------------------------------------------------------
def test_paragraph_with_wo_empty_class_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "404.html",
        """\
        <!-- wp:paragraph {"className":"wo-empty__eyebrow"} -->
        <p class="wo-empty__eyebrow">Page missing</p>
        <!-- /wp:paragraph -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any("wo-empty__" in d for d in result.details)


def test_paragraph_with_normal_class_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "404.html",
        """\
        <!-- wp:paragraph -->
        <p>Page missing</p>
        <!-- /wp:paragraph -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


# ---------------------------------------------------------------------------
# Invariant 3: core/button box-shadow belongs on the inner <a>, not <div>.
# ---------------------------------------------------------------------------
def test_button_shadow_on_inner_anchor_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "cta.php",
        """\
        <?php /** Title: CTA */ ?>
        <!-- wp:buttons -->
        <div class="wp-block-buttons">
            <!-- wp:button -->
            <div class="wp-block-button">
                <a class="wp-block-button__link wp-element-button" style="box-shadow:0 2px 0 #000" href="/shop/">Shop</a>
            </div>
            <!-- /wp:button -->
        </div>
        <!-- /wp:buttons -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_button_shadow_on_outer_wrapper_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "cta.php",
        """\
        <?php /** Title: CTA */ ?>
        <!-- wp:buttons -->
        <div class="wp-block-buttons">
            <!-- wp:button -->
            <div class="wp-block-button" style="box-shadow:0 2px 0 #000">
                <a class="wp-block-button__link wp-element-button" href="/shop/">Shop</a>
            </div>
            <!-- /wp:button -->
        </div>
        <!-- /wp:buttons -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any("box-shadow" in d and "outer" in d for d in result.details)


def test_passes_with_completely_empty_theme(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    # The minimal_theme fixture already writes a plain index.html + header +
    # footer that don't trip any of the three invariants.
    assert check.check_block_markup_anti_patterns().passed
