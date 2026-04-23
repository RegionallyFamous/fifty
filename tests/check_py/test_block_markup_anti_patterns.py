"""Tests for `check_block_markup_anti_patterns`.

Five invariants, each surfaced by a regex. Regression risk is high
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
# Invariant 2: core/paragraph may only carry legacy `wo-empty__*` classes
# when they are declared via the `className` block attribute. Raw classes
# inlined into `<p class="...">` without a matching `className` get
# scrubbed by core/paragraph save() on the next editor round-trip; the
# `className` attribute is the canonical custom-class store and is
# faithfully re-emitted, so the same class survives. The cart-page.php
# pattern relies on this: the empty-cart-block's eyebrow / lede paragraphs
# carry `"className":"wo-empty__eyebrow"` etc. so the per-theme empty-cart
# CSS hooks are stable.
# ---------------------------------------------------------------------------
def test_paragraph_with_raw_wo_empty_class_fails(minimal_theme, bind_check_root):
    """Class on `<p>` but NOT in `className` -> dropped on round-trip -> fail."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "404.html",
        """\
        <!-- wp:paragraph {"align":"center"} -->
        <p class="has-text-align-center wo-empty__eyebrow">Page missing</p>
        <!-- /wp:paragraph -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any("wo-empty__" in d for d in result.details)


def test_paragraph_with_wo_empty_in_className_attr_passes(minimal_theme, bind_check_root):
    """`className` declares the class -> preserved on round-trip -> pass."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "404.html",
        """\
        <!-- wp:paragraph {"className":"wo-empty__eyebrow"} -->
        <p class="wo-empty__eyebrow">Page missing</p>
        <!-- /wp:paragraph -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


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


# ---------------------------------------------------------------------------
# Invariant 4: core/accordion wrapper must declare role="group".
# ---------------------------------------------------------------------------
def test_accordion_with_role_group_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:accordion -->
        <div role="group" class="wp-block-accordion">
            <!-- wp:accordion-item -->
            <div class="wp-block-accordion-item"></div>
            <!-- /wp:accordion-item -->
        </div>
        <!-- /wp:accordion -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_accordion_missing_role_group_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:accordion -->
        <div class="wp-block-accordion">
            <!-- wp:accordion-item -->
            <div class="wp-block-accordion-item"></div>
            <!-- /wp:accordion-item -->
        </div>
        <!-- /wp:accordion -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any('role="group"' in d for d in result.details)


def test_accordion_item_without_role_group_passes(minimal_theme, bind_check_root):
    """Only the outer .wp-block-accordion wrapper needs role=group; child
    .wp-block-accordion-item / -panel / -heading must NOT trip the rule."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:accordion -->
        <div role="group" class="wp-block-accordion">
            <!-- wp:accordion-item -->
            <div class="wp-block-accordion-item">
                <!-- wp:accordion-heading -->
                <h3 class="wp-block-accordion-heading"></h3>
                <!-- /wp:accordion-heading -->
            </div>
            <!-- /wp:accordion-item -->
        </div>
        <!-- /wp:accordion -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


# ---------------------------------------------------------------------------
# Invariant 5: <button> tags must declare an explicit type=.
# ---------------------------------------------------------------------------
def test_button_with_explicit_type_button_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:html -->
        <button type="button" class="toggle">More</button>
        <!-- /wp:html -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_button_with_explicit_type_submit_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "form.php",
        """\
        <?php /** Title: Form */ ?>
        <!-- wp:html -->
        <form><button type="submit">Send</button></form>
        <!-- /wp:html -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_button_without_type_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:html -->
        <button class="toggle">More</button>
        <!-- /wp:html -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any("type=" in d for d in result.details)


def test_bare_button_without_attrs_fails(minimal_theme, bind_check_root):
    """`<button>` with zero attributes is the worst offender -- defaults
    to type=submit and would post any surrounding form on click."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:html -->
        <button>Click</button>
        <!-- /wp:html -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any("type=" in d for d in result.details)


def test_button_with_type_late_in_attribute_list_passes(minimal_theme, bind_check_root):
    """`type=` doesn't have to be the first attribute -- any position
    counts as long as it's present before the closing >."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "faq.php",
        """\
        <?php /** Title: FAQ */ ?>
        <!-- wp:html -->
        <button class="toggle" data-foo="bar" type="button">More</button>
        <!-- /wp:html -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_passes_with_completely_empty_theme(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    # The minimal_theme fixture already writes a plain index.html + header +
    # footer that don't trip any of the five invariants.
    assert check.check_block_markup_anti_patterns().passed


# ---------------------------------------------------------------------------
# Invariant 8: wide/full wp:query + constrained inner layout (no contentSize
# override) + grid post-template == post grid silently squeezed to the
# theme's default contentSize. Past incident: obel/templates/front-page.html
# "From the journal" rendered three ~225px cards in the left half of the
# section because the wp:query layout fell through to 720px contentSize even
# though `align:"wide"` was set on the query block.
# ---------------------------------------------------------------------------
def test_wide_query_with_default_layout_and_grid_post_template_passes(
    minimal_theme, bind_check_root
):
    """The canonical fix: `layout:{"type":"default"}` lets the grid
    post-template fill the alignwide width."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "home.html",
        """\
        <!-- wp:query {"queryId":0,"query":{"perPage":3,"postType":"post"},"align":"wide","layout":{"type":"default"}} -->
        <div class="wp-block-query alignwide">
            <!-- wp:post-template {"layout":{"type":"grid","columnCount":3,"minimumColumnWidth":null}} -->
                <!-- wp:post-title /-->
            <!-- /wp:post-template -->
        </div>
        <!-- /wp:query -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_wide_query_with_explicit_contentsize_override_passes(
    minimal_theme, bind_check_root
):
    """An explicit `contentSize` on the constrained layout is also a valid
    fix: the author chose the width deliberately, so don't flag it."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "home.html",
        """\
        <!-- wp:query {"queryId":0,"query":{"perPage":3,"postType":"post"},"align":"wide","layout":{"type":"constrained","contentSize":"var(--wp--style--global--wide-size)"}} -->
        <div class="wp-block-query alignwide">
            <!-- wp:post-template {"layout":{"type":"grid","columnCount":3,"minimumColumnWidth":null}} -->
                <!-- wp:post-title /-->
            <!-- /wp:post-template -->
        </div>
        <!-- /wp:query -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_wide_query_with_constrained_default_and_grid_post_template_fails(
    minimal_theme, bind_check_root
):
    """The exact obel front-page bug: align=wide + constrained layout (no
    contentSize) + grid post-template -> grid squeezed to 720px contentSize."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "home.html",
        """\
        <!-- wp:query {"queryId":0,"query":{"perPage":3,"postType":"post"},"align":"wide","layout":{"type":"constrained"}} -->
        <div class="wp-block-query alignwide">
            <!-- wp:post-template {"layout":{"type":"grid","columnCount":3,"minimumColumnWidth":null}} -->
                <!-- wp:post-title /-->
            <!-- /wp:post-template -->
        </div>
        <!-- /wp:query -->
        """,
    )
    result = check.check_block_markup_anti_patterns()
    assert not result.passed
    assert any(
        "wp:query" in d and "constrained" in d and "post-template" in d
        for d in result.details
    )


def test_full_query_with_constrained_default_and_grid_post_template_fails(
    minimal_theme, bind_check_root
):
    """`align:"full"` has the same problem -- the constrained layout still
    constrains children to contentSize regardless of the query's outer width."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "home.html",
        """\
        <!-- wp:query {"queryId":0,"query":{"perPage":3,"postType":"post"},"align":"full","layout":{"type":"constrained"}} -->
        <div class="wp-block-query alignfull">
            <!-- wp:post-template {"layout":{"type":"grid","columnCount":3,"minimumColumnWidth":null}} -->
                <!-- wp:post-title /-->
            <!-- /wp:post-template -->
        </div>
        <!-- /wp:query -->
        """,
    )
    assert not check.check_block_markup_anti_patterns().passed


def test_unaligned_query_with_constrained_layout_passes(minimal_theme, bind_check_root):
    """Without align:wide|full, contentSize squeeze is the EXPECTED behaviour
    -- the author wants their post grid in the content column."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "home.html",
        """\
        <!-- wp:query {"queryId":0,"query":{"perPage":3,"postType":"post"},"layout":{"type":"constrained"}} -->
        <div class="wp-block-query">
            <!-- wp:post-template {"layout":{"type":"grid","columnCount":3,"minimumColumnWidth":null}} -->
                <!-- wp:post-title /-->
            <!-- /wp:post-template -->
        </div>
        <!-- /wp:query -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed


def test_wide_query_with_non_grid_post_template_passes(minimal_theme, bind_check_root):
    """A single-column (default-layout) post-template inside a constrained
    wide query is a different visual: a vertical list at content-size width.
    That's a legitimate design choice; don't flag it."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "home.html",
        """\
        <!-- wp:query {"queryId":0,"query":{"perPage":3,"postType":"post"},"align":"wide","layout":{"type":"constrained"}} -->
        <div class="wp-block-query alignwide">
            <!-- wp:post-template -->
                <!-- wp:post-title /-->
            <!-- /wp:post-template -->
        </div>
        <!-- /wp:query -->
        """,
    )
    assert check.check_block_markup_anti_patterns().passed
