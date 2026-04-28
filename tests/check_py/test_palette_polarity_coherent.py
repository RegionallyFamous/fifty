"""Tests for `check_palette_polarity_coherent`.

The check asserts that palette slugs semantically used as `base`-adjacent
backgrounds (`subtle`, `surface`, `accent-soft`) share the luminance
side of `base`, and that `contrast` lands on the opposite side. It
catches the "partial spec left source palette slugs stale" footgun
that cratered cipher's `design.py build` smoke on 2026-04-28: every
shipping theme coincidentally had a polarity-coherent palette, but a
hand-authored spec under-covering the source palette produced a
`base: dark` theme carrying obel's `subtle: #F2F1EC` (near-white),
which painted the child theme's cream `--contrast` on an obel-left-
over near-white at 1.17:1 across 70+ axe nodes per page.

This test suite covers:
  * the shipping-theme shape (polarity-coherent, passes)
  * the cipher shape (base flipped, subtle left stale → fails)
  * the inverse (dark source, new light base, dark subtle left stale
    → still fails, symmetric)
  * absence of palette slug (skipped cleanly rather than crashing)
  * malformed base (skipped rather than false-positive)
  * `contrast` same-side as base (fails — text would be invisible)
"""

from __future__ import annotations

import json


def _set_palette(theme_root, slugs: dict[str, str]) -> None:
    data = json.loads((theme_root / "theme.json").read_text(encoding="utf-8"))
    data["settings"]["color"]["palette"] = [
        {"slug": slug, "name": slug.title(), "color": color} for slug, color in slugs.items()
    ]
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


def test_light_base_with_light_subtle_passes(minimal_theme, bind_check_root):
    """Obel / chonk / foundry / lysholm / basalt / aero shape: light base
    with light-leaning subtle / surface / accent-soft. The 6 shipping
    light-base themes' palettes were the primary verification target
    while designing the check."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {
            "base": "#FAFAF7",
            "contrast": "#1A1A1A",
            "subtle": "#F2F1EC",
            "surface": "#FFFFFF",
            "accent-soft": "#EFD9C3",
        },
    )
    assert check.check_palette_polarity_coherent().passed


def test_dark_base_with_dark_subtle_passes(minimal_theme, bind_check_root):
    """Selvedge shape: dark base with dark subtle / surface / accent-soft.
    The only currently-shipping dark-base theme; verifying we don't
    false-positive on its palette is as important as verifying we
    catch cipher."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {
            "base": "#160F08",
            "contrast": "#EDE3CE",
            "subtle": "#2C2016",
            "surface": "#1F1610",
            "accent-soft": "#2A1608",
        },
    )
    assert check.check_palette_polarity_coherent().passed


def test_cipher_shape_dark_base_stale_light_subtle_fails(minimal_theme, bind_check_root):
    """The canonical failure mode the check exists to name: `base` is
    dark (cipher's `#0F1622`) but `subtle` is stale obel near-white
    (`#F2F1EC`). axe flags 20-29 nodes per page in production; the
    check should fire with a diagnostic naming the slug and its
    luminance."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {
            "base": "#0F1622",
            "contrast": "#E5DFCE",
            "subtle": "#F2F1EC",  # stale obel leftover — the bug
            "surface": "#18212F",
            "accent-soft": "#EFD9C3",  # also stale obel leftover
        },
    )
    result = check.check_palette_polarity_coherent()
    assert not result.passed
    detail_blob = "\n".join(result.details)
    assert "subtle" in detail_blob
    assert "#F2F1EC" in detail_blob or "#f2f1ec" in detail_blob.lower()
    assert "accent-soft" in detail_blob
    # Diagnostic should explicitly name the base-side and the mismatched
    # slug-side so the operator can see the polarity inversion at a glance.
    assert "dark-side" in detail_blob
    assert "light-side" in detail_blob


def test_inverse_light_base_stale_dark_subtle_fails(minimal_theme, bind_check_root):
    """Symmetric case: a theme whose spec flipped `base` from dark to
    light but left a dark-source `subtle` behind. The check is
    polarity-agnostic — both flip directions must fail."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {
            "base": "#FAFAF7",
            "contrast": "#1A1A1A",
            "subtle": "#2C2016",  # stale from a dark-theme source
            "surface": "#FFFFFF",
            "accent-soft": "#EFD9C3",
        },
    )
    result = check.check_palette_polarity_coherent()
    assert not result.passed
    assert any("subtle" in d for d in result.details)


def test_contrast_same_side_as_base_fails(minimal_theme, bind_check_root):
    """`contrast` is the body text token — it MUST land on the opposite
    luminance side as `base`, or body text is invisible. The check
    enforces this as the inverse of the same-side rule."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {
            "base": "#FAFAF7",
            "contrast": "#F0EEE8",  # also light — fails
            "subtle": "#F2F1EC",
            "surface": "#FFFFFF",
            "accent-soft": "#EFD9C3",
        },
    )
    result = check.check_palette_polarity_coherent()
    assert not result.passed
    detail_blob = "\n".join(result.details)
    assert "contrast" in detail_blob
    assert "shares a side" in detail_blob


def test_missing_subtle_is_skipped_gracefully(minimal_theme, bind_check_root):
    """A theme that doesn't declare `subtle` at all — the check can't
    assess a slug that isn't there, so it skips rather than false-
    positives. A future theme that's deliberately minimal about its
    palette (e.g. contrast-only) should not be punished here."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {"base": "#0F1622", "contrast": "#E5DFCE"},
    )
    result = check.check_palette_polarity_coherent()
    assert result.passed
    # Details should report 1 slug checked (contrast) to prove the check
    # actually ran, rather than silently passing because it found zero.
    assert any("polarity-significant" in d or "correct side" in d for d in result.details)


def test_missing_base_skips_entire_check(minimal_theme, bind_check_root):
    """If there's no `base`, we can't establish polarity at all — the
    check gracefully skips rather than crashing on a bad palette."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {"contrast": "#1A1A1A", "subtle": "#2C2016"},
    )
    result = check.check_palette_polarity_coherent()
    assert result.skipped


def test_malformed_base_hex_skips_check(minimal_theme, bind_check_root):
    """`base` present but not a valid `#RRGGBB` hex (e.g. a CSS
    variable, a named color, a malformed string) — skip rather than
    crash. `check_json_validity` already fails loudly on truly
    unparseable JSON, so this check shouldn't duplicate that surface."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {"base": "not-a-hex", "contrast": "#1A1A1A", "subtle": "#F2F1EC"},
    )
    result = check.check_palette_polarity_coherent()
    assert result.skipped


def test_muted_mid_gray_does_not_false_positive(minimal_theme, bind_check_root):
    """basalt ships `muted: #9e9e9e` — a legitimate medium-gray tone
    for muted text. The check intentionally excludes `muted` from its
    sameside set because basalt's snaps don't show any real failure
    on muted surfaces (axe confirms actual `muted`-painted elements
    clear AA). This test locks that design decision in."""
    check = bind_check_root(minimal_theme)
    _set_palette(
        minimal_theme,
        {
            "base": "#FFFFFF",
            "contrast": "#1A1A1A",
            "muted": "#9E9E9E",  # dark-side gray on a light base — IGNORED
            "subtle": "#E8E8E8",  # light-side — OK
            "surface": "#F5F5F5",
            "accent-soft": "#D4C4B8",
        },
    )
    assert check.check_palette_polarity_coherent().passed
