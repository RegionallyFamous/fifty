"""Tests for `bin/check.py:check_bordered_group_text_has_explicit_color`.

Guards against the failure mode that shipped on
`agent/batch-20260427-4d9c9b-basalt`: a `wp:group` with
`backgroundColor:surface` + a border, containing a `<p>` with no
`textColor` attr. On basalt the paragraph inherited the page's
ambient `contrast` color while the group painted a `surface`
background, which sank the paragraph below the 4.5:1 AA contrast
floor. The issue was invisible to the static gate (no `!important`,
no hard-coded hex, no hard-coded class) and only surfaced on the
axe-core pass after a full snap + dispatch. The new check pulls
that detection left to pre-commit so the roundtrip is measured in
milliseconds, not minutes.

Eight fixtures cover the expected pass/fail boundary:
1. No decoration → pass (the usual body-of-page group).
2. backgroundColor:base (ambient) → pass (no context change).
3. Decorated, but child is non-text (image, button, nested group).
4. Decorated, child has textColor attr → pass.
5. Decorated, child has style.color.text → pass.
6. Decorated, parent group has textColor (inheritance) → pass.
7. backgroundColor:surface + child without textColor → fail (basalt).
8. style.border.top.color + child without textColor → pass (border
   alone doesn't change the contrast context; inside children still
   render on the page's ambient base).
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_passes_when_no_decoration(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>Plain undecorated text.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_passes_with_ambient_base_background(minimal_theme, bind_check_root):
    """`backgroundColor:base` is the page's ambient color -- children
    inherit text color from the page normally and the contrast math
    is unchanged. Don't flag."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-base-background-color has-background">
            <!-- wp:paragraph -->
            <p>Body text on ambient background.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_passes_when_child_has_explicit_text_color(minimal_theme, bind_check_root):
    """Child paragraph sets `textColor:"secondary"` -- the canonical
    basalt-fix pattern. Passes."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"surface","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-surface-background-color has-background">
            <!-- wp:paragraph {"textColor":"secondary"} -->
            <p class="has-secondary-color has-text-color">Stoneware clay.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_passes_when_child_has_style_color_text(minimal_theme, bind_check_root):
    """Child paragraph sets `style.color.text` (custom hex / var form).
    Still counts as "explicit" since the author declared intent."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"surface","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-surface-background-color has-background">
            <!-- wp:paragraph {"style":{"color":{"text":"var(--wp--preset--color--secondary)"}}} -->
            <p>Explicit custom color.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_passes_when_parent_has_text_color(minimal_theme, bind_check_root):
    """The chonk/announcement-bar pattern: parent group declares
    `textColor:"accent"`, children inherit that known color. No
    per-child textColor needed."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "parts" / "announcement-bar.html",
        """\
        <!-- wp:group {"backgroundColor":"contrast","textColor":"accent","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-accent-color has-contrast-background-color has-text-color has-background">
            <!-- wp:paragraph -->
            <p>FREE SHIPPING on orders over $50</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_passes_when_only_non_text_children(minimal_theme, bind_check_root):
    """Decorated group containing only image/button children has no
    text to worry about. Shouldn't fire."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"surface","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-surface-background-color has-background">
            <!-- wp:image {"id":1} -->
            <figure class="wp-block-image"><img src="/hero.jpg" alt=""/></figure>
            <!-- /wp:image -->
            <!-- wp:buttons -->
            <div class="wp-block-buttons">
                <!-- wp:button -->
                <div class="wp-block-button"><a class="wp-block-button__link wp-element-button">Shop</a></div>
                <!-- /wp:button -->
            </div>
            <!-- /wp:buttons -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_passes_when_only_border_without_background(minimal_theme, bind_check_root):
    """Border alone doesn't change the contrast context for children --
    children still render on the page's ambient background. This was
    the false-positive shape on obel/templates/order-confirmation.html
    that the first draft of the check incorrectly flagged."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "order-confirmation.html",
        """\
        <!-- wp:group {"align":"wide","style":{"spacing":{},"border":{"top":{"color":"var:preset|color|border","width":"1px","style":"solid"},"bottom":{"color":"var:preset|color|border","width":"1px","style":"solid"}}},"layout":{"type":"constrained"}} -->
        <div class="wp-block-group alignwide">
            <!-- wp:heading {"textAlign":"center","level":2} -->
            <h2 class="wp-block-heading has-text-align-center">What happens next</h2>
            <!-- /wp:heading -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed


def test_fails_on_basalt_regression(minimal_theme, bind_check_root):
    """The exact shape that shipped on basalt: backgroundColor:surface
    + border.top.color + child paragraph without textColor. This is
    the failure mode the check exists to prevent."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"align":"full","className":"basalt-materials-row","style":{"spacing":{},"border":{"top":{"color":"var:preset|color|contrast","width":"1px","style":"solid"}}},"backgroundColor":"surface","layout":{"type":"constrained"}} -->
        <div class="wp-block-group alignfull basalt-materials-row has-border-color has-surface-background-color has-background" style="border-top-color:var(--wp--preset--color--contrast);border-top-style:solid;border-top-width:1px">
            <!-- wp:paragraph {"align":"center","fontSize":"xs"} -->
            <p class="has-text-align-center has-xs-font-size">basalt studio · kilnyard 7 · est. 2024</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = check.check_bordered_group_text_has_explicit_color()
    assert not result.passed
    rendered = " ".join(result.details)
    assert "front-page.html" in rendered
    assert "paragraph" in rendered
    assert "backgroundColor:surface" in rendered


def test_fails_on_list_child_without_text_color(minimal_theme, bind_check_root):
    """Lists inside decorated groups hit the same cascade trap as
    paragraphs -- the basalt materials row had both. `wp:list` should
    be flagged identically to `wp:paragraph`."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"secondary-accent","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-secondary-accent-background-color has-background">
            <!-- wp:list -->
            <ul class="wp-block-list">
                <li>Item one</li>
                <li>Item two</li>
            </ul>
            <!-- /wp:list -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = check.check_bordered_group_text_has_explicit_color()
    assert not result.passed
    assert "list" in " ".join(result.details)


def test_fails_on_gradient_background(minimal_theme, bind_check_root):
    """Gradient backgrounds change the contrast context too -- child
    text needs an explicit textColor to pass."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"gradient":"vivid-purple","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-vivid-purple-gradient-background has-background">
            <!-- wp:paragraph -->
            <p>On a gradient, contrast is extremely fragile.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = check.check_bordered_group_text_has_explicit_color()
    assert not result.passed
    assert "gradient" in " ".join(result.details)


def test_only_immediate_text_children_flagged(minimal_theme, bind_check_root):
    """Inner groups that own their own paint should NOT cascade
    further -- only direct text children of the outer decorated group
    should be flagged. An inner group interposes a new color context
    and the designer declares textColor on it instead."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"surface","layout":{"type":"constrained"}} -->
        <div class="wp-block-group has-surface-background-color has-background">
            <!-- wp:group {"textColor":"contrast"} -->
            <div class="wp-block-group has-contrast-color has-text-color">
                <!-- wp:paragraph -->
                <p>Inner text inherits from inner group, not outer.</p>
                <!-- /wp:paragraph -->
            </div>
            <!-- /wp:group -->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_bordered_group_text_has_explicit_color().passed
