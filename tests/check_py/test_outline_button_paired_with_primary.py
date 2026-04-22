"""Tests for `check_outline_button_paired_with_primary`.

WP core's stock `is-style-outline` button variation paints with a 1px
hairline border and inherits whatever radius the variation declares —
which is independent of `styles.elements.button.border.radius`. Two
silent regressions follow:

  * primary + outline disagree on corner shape (one pill, one square),
    so a paired CTA reads as two design systems mashed together;
  * outline ships at 1px while the primary sits at a thick token, so
    the outline reads as a faint suggestion instead of a real button
    (exactly the failure mode in the user's screenshot).

The check enforces that any declared outline variation matches the
primary's `border.radius` and uses a border-width that isn't a 1px /
0px hairline (or a token reference, which is assumed token-validated
elsewhere).
"""

from __future__ import annotations

import json
from typing import Any


def _set_button_styles(
    theme_root,
    *,
    primary_radius: str | None = None,
    outline_border: dict[str, Any] | None = None,
    outline_color: dict[str, Any] | None = None,
    drop_outline: bool = False,
) -> None:
    """Mutate the theme's `styles.elements.button` and
    `styles.blocks.core/button.variations.outline` to whatever the test
    needs, then write it back."""
    tj = theme_root / "theme.json"
    data = json.loads(tj.read_text(encoding="utf-8"))
    styles = data.setdefault("styles", {})
    elements = styles.setdefault("elements", {})
    button = elements.setdefault("button", {})
    if primary_radius is not None:
        button.setdefault("border", {})["radius"] = primary_radius

    blocks = styles.setdefault("blocks", {})
    core_button = blocks.setdefault("core/button", {})
    if drop_outline:
        core_button.pop("variations", None)
    else:
        variations = core_button.setdefault("variations", {})
        outline = variations.setdefault("outline", {})
        outline["color"] = outline_color or {
            "background": "transparent",
            "text": "var(--wp--preset--color--contrast)",
        }
        outline["border"] = outline_border or {
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": primary_radius or "0",
        }

    tj.write_text(json.dumps(data, indent="\t") + "\n", encoding="utf-8")


def test_passes_when_outline_matches_primary(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="9999px",
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": "9999px",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert result.passed, result.details


def test_fails_when_radius_mismatches_primary(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="0",
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": "9999px",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert not result.passed
    assert any("border.radius" in d for d in result.details)


def test_fails_when_border_width_is_one_pixel(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="0",
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "1px",
            "radius": "0",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert not result.passed
    assert any("border.width" in d for d in result.details)


def test_fails_when_border_width_is_zero(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="0",
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "0",
            "radius": "0",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert not result.passed
    assert any("too thin" in d for d in result.details)


def test_fails_when_border_style_is_none(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="0",
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "none",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": "0",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert not result.passed
    assert any("border-style" in d for d in result.details)


def test_fails_when_outline_paints_solid_background(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="0",
        outline_color={
            "background": "var(--wp--preset--color--accent)",
            "text": "var(--wp--preset--color--base)",
        },
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": "0",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert not result.passed
    assert any("transparent" in d for d in result.details)


def test_passes_when_token_reference_used_for_width(minimal_theme, bind_check_root):
    """Token references like `var(--wp--custom--border--width--thick)` are
    accepted on faith — the per-theme distinct-chrome / token checks
    elsewhere in the suite verify the token resolves to ≥ 2px."""
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        primary_radius="9999px",
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": "9999px",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert result.passed, result.details


def test_skips_when_no_outline_variation_declared(minimal_theme, bind_check_root):
    """Themes that don't ship an outline variation have nothing to
    enforce — the check should skip cleanly."""
    check = bind_check_root(minimal_theme)
    _set_button_styles(minimal_theme, drop_outline=True)
    result = check.check_outline_button_paired_with_primary()
    assert result.skipped, result.details


def test_passes_when_primary_has_no_radius_constraint(minimal_theme, bind_check_root):
    """If the primary doesn't declare a border-radius, the outline's
    radius is unconstrained — both fall back to WP's UA default."""
    check = bind_check_root(minimal_theme)
    _set_button_styles(
        minimal_theme,
        outline_border={
            "color": "var(--wp--preset--color--contrast)",
            "style": "solid",
            "width": "var(--wp--custom--border--width--thick)",
            "radius": "9999px",
        },
    )
    result = check.check_outline_button_paired_with_primary()
    assert result.passed, result.details
