"""Tests for `bin/check.py:check_no_empty_cover_blocks`.

Guards against `wp:cover` blocks that paint nothing -- the failure mode
that shipped on Lysholm's front-page lookbook hero from `969b7f6` through
`94dface`: a 720px-tall cover with `"url":""` and `dimRatio:0` painted as
a transparent base-on-base box above the headline. The text inside it
rendered correctly so axe-core didn't flag it; the gate exists because
no other static check catches "cover that paints nothing".

Three escape hatches are documented in the function docstring and
exercised here:

1. A non-empty static `url` (image-backed cover).
2. `dimRatio >= 30` (deliberately-painted color block; 30 is WP's
   "noticeable tint" threshold).
3. PHP expressions in `url` (the `<?php echo esc_url(get_theme_file_uri(…)) ?>`
   shape used by `lysholm/patterns/hero-lookbook.php`).
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_passes_when_no_cover_blocks_exist(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "no-cover.php",
        """\
        <?php
        /**
         * Title: No cover
         * Slug: scratch/no-cover
         */
        ?>
        <!-- wp:paragraph --><p>Just text.</p><!-- /wp:paragraph -->
        """,
    )
    assert check.check_no_empty_cover_blocks().passed


def test_passes_with_image_backed_cover(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "image-hero.php",
        """\
        <?php
        /**
         * Title: Image hero
         * Slug: scratch/image-hero
         */
        ?>
        <!-- wp:cover {"url":"https://example.com/hero.jpg","dimRatio":40,"minHeight":640,"minHeightUnit":"px"} -->
        <div class="wp-block-cover" style="min-height:640px"><img class="wp-block-cover__image-background" alt="" src="https://example.com/hero.jpg" data-object-fit="cover"/><span aria-hidden="true" class="wp-block-cover__background has-background-dim-40 has-background-dim"></span>
            <div class="wp-block-cover__inner-container">
                <!-- wp:heading --><h1>Hero text</h1><!-- /wp:heading -->
            </div>
        </div>
        <!-- /wp:cover -->
        """,
    )
    assert check.check_no_empty_cover_blocks().passed


def test_passes_with_high_dim_ratio_color_block(minimal_theme, bind_check_root):
    """`dimRatio >= 30` with no `url` is the deliberately-painted color
    block shape used by selvedge's category cards. Allowed."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:cover {"overlayColor":"contrast","dimRatio":40,"contentPosition":"bottom left"} -->
        <div class="wp-block-cover has-custom-content-position is-position-bottom-left"><span aria-hidden="true" class="wp-block-cover__background has-contrast-background-color has-background-dim-40 has-background-dim"></span>
            <div class="wp-block-cover__inner-container">
                <!-- wp:heading --><h2>Color block hero</h2><!-- /wp:heading -->
            </div>
        </div>
        <!-- /wp:cover -->
        """,
    )
    assert check.check_no_empty_cover_blocks().passed


def test_passes_with_php_resolved_url(minimal_theme, bind_check_root):
    """Lysholm's `hero-lookbook.php` shape: `url` is a PHP expression
    that resolves to a real path at render time. The static text is
    `<?php echo esc_url(...); ?>` -- the gate explicitly accepts that."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "php-hero.php",
        """\
        <?php
        /**
         * Title: PHP hero
         * Slug: scratch/php-hero
         */
        ?>
        <!-- wp:cover {"url":"<?php echo esc_url( get_theme_file_uri( 'playground/images/hero.jpg' ) ); ?>","dimRatio":0,"minHeight":720,"minHeightUnit":"px"} -->
        <div class="wp-block-cover" style="min-height:720px"></div>
        <!-- /wp:cover -->
        """,
    )
    assert check.check_no_empty_cover_blocks().passed


def test_fails_on_empty_url_with_zero_dim_ratio(minimal_theme, bind_check_root):
    """The exact shape that shipped on Lysholm's front-page from 969b7f6
    through 94dface: empty `url`, `dimRatio:0`, 720px transparent void."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:cover {"url":"","minHeight":720,"minHeightUnit":"px","overlayColor":"base","dimRatio":0,"contentPosition":"bottom left"} -->
        <div class="wp-block-cover is-light has-custom-content-position is-position-bottom-left" style="min-height:720px"><span aria-hidden="true" class="wp-block-cover__background has-base-background-color has-background-dim-0 has-background-dim"></span>
            <div class="wp-block-cover__inner-container">
                <!-- wp:heading --><h1>Quiet objects, slow days.</h1><!-- /wp:heading -->
            </div>
        </div>
        <!-- /wp:cover -->
        """,
    )
    result = check.check_no_empty_cover_blocks()
    assert not result.passed
    rendered = " ".join(result.details)
    assert "front-page.html" in rendered
    assert "720px" in rendered
    assert "transparent" in rendered


def test_fails_on_missing_url_attribute(minimal_theme, bind_check_root):
    """Missing `url` (omitted entirely) is treated identically to empty."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "missing-url.php",
        """\
        <?php
        /**
         * Title: Missing URL
         * Slug: scratch/missing-url
         */
        ?>
        <!-- wp:cover {"minHeight":480,"minHeightUnit":"px","overlayColor":"base","dimRatio":10} -->
        <div class="wp-block-cover" style="min-height:480px"></div>
        <!-- /wp:cover -->
        """,
    )
    result = check.check_no_empty_cover_blocks()
    assert not result.passed
    assert "missing-url.php" in " ".join(result.details)


def test_fails_with_low_dim_ratio_and_no_url(minimal_theme, bind_check_root):
    """`dimRatio:20` is below the 30 threshold -- the overlay is mostly
    transparent, so without an image the block paints nothing."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "low-dim.php",
        """\
        <?php
        /**
         * Title: Low dim
         * Slug: scratch/low-dim
         */
        ?>
        <!-- wp:cover {"url":"","minHeight":600,"minHeightUnit":"px","overlayColor":"contrast","dimRatio":20} -->
        <div class="wp-block-cover" style="min-height:600px"></div>
        <!-- /wp:cover -->
        """,
    )
    result = check.check_no_empty_cover_blocks()
    assert not result.passed
    assert "dimRatio=20" in " ".join(result.details)
