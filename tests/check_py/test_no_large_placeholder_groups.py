"""Tests for `bin/check.py:check_no_large_placeholder_groups`.

Guards against the Chonk hero failure mode: a large bordered/padded
`wp:group` whose only visible content is a decorative glyph paragraph
and a sticker label, with no image, pattern, or media block. Renders as
an empty card with a single Unicode character.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_skips_when_no_front_page(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "front-page.html").unlink(missing_ok=True)
    result = check.check_no_large_placeholder_groups()
    assert result.skipped


def test_passes_when_card_contains_image(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"className":"hero","style":{"shadow":"var:preset|shadow|primary","spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"}}}} -->
        <div class="wp-block-group hero">
            <!-- wp:image {"sizeSlug":"large"} -->
            <figure class="wp-block-image"><img src="/img/hero.jpg" alt="hero"/></figure>
            <!-- /wp:image -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_no_large_placeholder_groups().passed


def test_passes_when_card_contains_pattern(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"className":"hero","style":{"shadow":"var:preset|shadow|primary","spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"}}}} -->
        <div class="wp-block-group hero">
            <!-- wp:pattern {"slug":"scratch/hero-image"} /-->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_no_large_placeholder_groups().passed


def test_passes_when_group_is_layout_wrapper(minimal_theme, bind_check_root):
    """A small `wp:group` without padding/shadow/border is not a card --
    it's a layout wrapper. Even with no image it shouldn't fail."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph --><p>Just a small intro paragraph.</p><!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_no_large_placeholder_groups().passed


def test_fails_on_chonk_glyph_hero_shape(minimal_theme, bind_check_root):
    """The exact shape that shipped on chonk's front-page hero: a
    bordered/padded card whose only visible content is a sticker label
    and a giant glyph paragraph -- no image, pattern, or media block."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"className":"chonk-hero__photo","style":{"border":{"width":"var:custom|border|width|thick","color":"var:preset|color|contrast"},"shadow":"var:preset|shadow|tertiary-accent","spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"}}}} -->
        <div class="wp-block-group chonk-hero__photo">
            <!-- wp:paragraph {"className":"chonk-hero__sticker"} --><p>New</p><!-- /wp:paragraph -->
            <!-- wp:paragraph {"className":"chonk-hero__icon"} --><p>\u25f3</p><!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = check.check_no_large_placeholder_groups()
    assert not result.passed
    rendered = " ".join(result.details)
    assert "front-page.html" in rendered
