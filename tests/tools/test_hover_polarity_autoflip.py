"""Tests for Phase FF (hover-polarity autoflip) and Phase GG
(universal header flex-wrap) in `bin/append-wc-overrides.py`.

Phase FF reads each on-disk theme's palette at script startup and emits
per-theme `body.theme-<slug>.theme-<slug> <surface>:hover` overrides for
any theme whose `contrast`-on-`accent` contrast sits below WCAG 3:1
AA-Large while `base`-on-`accent` clears the same floor. The overrides
flip the hover foreground from `contrast` to `base` so the text
remains legible.

Phase GG replaces Phase T's enumerated
`body.theme-{selvedge,chonk,lysholm}` header flex-wrap rule with a
universal selector rooted at `.wp-site-blocks header.wp-block-group.
alignfull`. A no-op for themes whose header content already fits the
tablet breakpoint; a real fix for themes whose brand + nav + utility
row exceeds it.

These tests lock in the invariants so a future change to the flip
logic, the surface list, or the specificity shape is loudly flagged.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def awc():
    """Load `bin/append-wc-overrides.py` as a module (hyphenated name,
    so normal `import` doesn't work). Matches the fixture shape already
    used by `test_append_wc_overrides.py`."""
    bin_dir = Path(__file__).resolve().parent.parent.parent / "bin"
    spec = importlib.util.spec_from_file_location(
        "append_wc_overrides", bin_dir / "append-wc-overrides.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# _wcag_luminance_hex + _wcag_contrast_hex
# ---------------------------------------------------------------------------


def test_wcag_luminance_pure_white(awc):
    assert awc._wcag_luminance_hex("#ffffff") == pytest.approx(1.0, abs=1e-4)


def test_wcag_luminance_pure_black(awc):
    assert awc._wcag_luminance_hex("#000000") == pytest.approx(0.0, abs=1e-4)


def test_wcag_luminance_handles_hash_prefix(awc):
    with_hash = awc._wcag_luminance_hex("#808080")
    no_hash = awc._wcag_luminance_hex("808080")
    assert with_hash == no_hash


def test_wcag_luminance_rejects_malformed(awc):
    assert awc._wcag_luminance_hex("not-a-color") is None
    assert awc._wcag_luminance_hex("#xyz") is None
    assert awc._wcag_luminance_hex("#12345") is None


def test_wcag_contrast_black_on_white_is_21(awc):
    assert awc._wcag_contrast_hex("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)


def test_wcag_contrast_symmetric(awc):
    a = awc._wcag_contrast_hex("#1a1a1a", "#fafaf7")
    b = awc._wcag_contrast_hex("#fafaf7", "#1a1a1a")
    assert a == b


def test_wcag_contrast_returns_none_on_bad_input(awc):
    assert awc._wcag_contrast_hex("bogus", "#000000") is None
    assert awc._wcag_contrast_hex("#000000", "bogus") is None


# ---------------------------------------------------------------------------
# _HOVER_ACCENT_FLIP_THEMES and CSS_PHASE_FF composition
# ---------------------------------------------------------------------------


def test_flip_themes_is_a_tuple_of_slugs(awc):
    """Script startup evaluates `_hover_accent_flip_themes()` once and
    caches the result as a tuple. Downstream code relies on the tuple
    being iterable and sortable — if a future change drops it to a
    set or generator, `_build_phase_ff_css` emits rules in
    non-deterministic order and every theme.json diff becomes noisy."""
    assert isinstance(awc._HOVER_ACCENT_FLIP_THEMES, tuple)
    for slug in awc._HOVER_ACCENT_FLIP_THEMES:
        assert isinstance(slug, str)
        assert slug.islower()


def test_flip_themes_includes_foundry(awc):
    """Foundry's palette (`base #f5eed8`, `contrast #1c1711`,
    `accent #8b2f1f`) produces contrast-on-accent = 2.14:1 (fails 3:1
    floor) and base-on-accent = 7.17:1 (passes). It has been the
    canonical `needs flip` case since it shipped — if the logic ever
    excludes it, either the palette moved or the threshold moved, and
    we want to know."""
    assert "foundry" in awc._HOVER_ACCENT_FLIP_THEMES


def test_flip_themes_excludes_obel_and_chonk(awc):
    """obel and chonk sit on opposite base polarities with saturated
    accents that give contrast-on-accent > 3:1 comfortably (obel
    4.74:1, chonk 16.57:1). Both must stay on the default baseline
    — flipping them to `base` would silently break their hover
    visibility."""
    assert "obel" not in awc._HOVER_ACCENT_FLIP_THEMES
    assert "chonk" not in awc._HOVER_ACCENT_FLIP_THEMES


def test_phase_ff_contains_doubled_class_for_specificity(awc):
    """The doubled `.theme-<slug>.theme-<slug>` selector is required
    to beat WC Blocks's `.wp-block-woocommerce-product-details ul
    .wc-tabs li a:hover` at (0,3,3) specificity. A single
    `body.theme-<slug>` tops out at (0,3,2) and loses the cascade —
    `check_wc_overrides_styled` fails loudly when that happens."""
    for slug in awc._HOVER_ACCENT_FLIP_THEMES:
        assert f"body.theme-{slug}.theme-{slug}" in awc.CSS_PHASE_FF, (
            f"Phase FF must use doubled-class `body.theme-{slug}.theme-{slug}` "
            f"for {slug} to beat WC Blocks specificity."
        )


def test_phase_ff_covers_every_known_accent_hover_surface(awc):
    """The baseline Phase A-D hover rules paint `{background: accent;
    color: contrast}` on exactly these 12 surfaces. Phase FF's
    surface list must stay in sync — if a new accent-hover surface
    ships in a later phase without being added here, the flip
    doesn't reach it and the hover check fires on the new surface."""
    expected = {
        ".wc-block-mini-cart__footer-actions a",
        ".wc-block-mini-cart__footer-actions .wc-block-components-button",
        ".wc-block-components-totals-coupon__button",
        ".wc-block-components-totals-coupon button",
        ".wc-block-cart__submit-container .wc-block-components-checkout-place-order-button",
        ".wc-block-cart__submit-container a.wc-block-cart__submit-button",
        ".wc-block-components-checkout-place-order-button",
        ".wp-block-woocommerce-order-confirmation-downloads .button",
        ".woocommerce-MyAccount-content form .button",
        ".woocommerce-orders-table .button",
        ".wo-empty__cta--primary",
        ".selvedge-footer__newsletter-submit",
    }
    assert set(awc._HOVER_ACCENT_SURFACES) == expected


def test_phase_ff_flips_foreground_to_base(awc):
    """The emitted rule body must set `color: var(--wp--preset--color--
    base)` — not `contrast`, not `on-accent`, not some raw hex. This
    is the whole point of the phase."""
    if not awc._HOVER_ACCENT_FLIP_THEMES:
        pytest.skip("no themes need the flip — nothing to assert")
    assert "color:var(--wp--preset--color--base)" in awc.CSS_PHASE_FF


def test_phase_ff_emits_empty_body_when_no_flips_needed(awc, monkeypatch):
    """When no theme needs the flip, Phase FF's body is empty but the
    sentinels remain so the chunk stays idempotent and
    `SENTINEL_CLOSE_PHASE_FF` is still a valid anchor for Phase GG."""
    monkeypatch.setattr(awc, "_HOVER_ACCENT_FLIP_THEMES", ())
    css = awc._build_phase_ff_css()
    assert awc.SENTINEL_OPEN_PHASE_FF in css
    assert awc.SENTINEL_CLOSE_PHASE_FF in css
    # Strip the sentinels and any whitespace — the middle should be empty.
    middle = (
        css.replace(awc.SENTINEL_OPEN_PHASE_FF, "").replace(awc.SENTINEL_CLOSE_PHASE_FF, "").strip()
    )
    assert middle == ""


def test_phase_ff_surfaces_match_phase_a_through_d_rules(awc):
    """Every surface in `_HOVER_ACCENT_SURFACES` must actually appear
    in the baseline `{background:var(--wp--preset--color--accent);
    color:var(--wp--preset--color--contrast);...}` rule set that Phase
    FF is correcting. Drift between the two means Phase FF paints a
    flip on a surface that doesn't have the problem (harmless but
    misleading) or misses one that does (silent miss).

    We scan the combined body of CSS_PHASE_A through CSS_PHASE_D plus
    the base CSS block for each surface — at least one occurrence is
    required for each, in a rule that also sets `background: var(
    --wp--preset--color--accent)`."""
    baseline_sources = [awc.CSS, awc.CSS_PHASE_A, awc.CSS_PHASE_D, awc.CSS_PHASE_D_FOOTER]
    # The baseline text we'll grep. Phase A-D chunks are single-lined
    # already; rules are `sel{body}` tokens separated by `}` or `\n`.
    for surface in awc._HOVER_ACCENT_SURFACES:
        token = f"{surface}:hover"
        matched = False
        for src in baseline_sources:
            if token in src and "var(--wp--preset--color--accent)" in src:
                matched = True
                break
        assert matched, (
            f"surface {surface!r} in _HOVER_ACCENT_SURFACES but no matching "
            f"`{token}` + accent background rule found in Phase A-D baselines"
        )


# ---------------------------------------------------------------------------
# CSS_PHASE_M — generated disabled add-to-cart coverage
# ---------------------------------------------------------------------------


def test_phase_m_disabled_button_rule_covers_dynamic_theme(awc, monkeypatch):
    """Incubating themes must get the disabled PDP button contrast rule.

    This used to be an enumerated list of shipped theme slugs, so a
    fresh `design.py build` of a new dark theme failed
    `check_disabled_button_contrast_per_theme` until someone hand-added
    the slug. Phase M should discover every on-disk theme when the chunk
    is built.
    """
    monkeypatch.setattr(awc, "discover_themes", lambda stages=(): ["obel", "nocturne"])
    css = awc._build_phase_m_css()
    assert "body.theme-nocturne .single_add_to_cart_button.disabled" in css
    assert "body.theme-nocturne .single_add_to_cart_button:disabled" in css
    assert "body.theme-nocturne .single_add_to_cart_button.wc-variation-selection-needed" in css


def test_phase_m_disabled_button_rule_uses_tokens(awc):
    """The disabled-state fix must stay tokenised, not hardcoded."""
    assert "background:var(--wp--preset--color--contrast)" in awc.CSS_PHASE_M
    assert "color:var(--wp--preset--color--base)" in awc.CSS_PHASE_M
    assert "opacity:1" in awc.CSS_PHASE_M


# ---------------------------------------------------------------------------
# CSS_PHASE_GG — universal header flex-wrap
# ---------------------------------------------------------------------------


def test_phase_gg_uses_universal_selector(awc):
    """Phase GG must NOT enumerate themes by slug. That was Phase T's
    mistake — every new theme had to be added to the list or its
    tablet header overflowed. The universal
    `.wp-site-blocks header.wp-block-group.alignfull` selector covers
    every current and future theme for free."""
    assert "body.theme-" not in awc.CSS_PHASE_GG, (
        "Phase GG's selector is enumerated by theme slug. Use the "
        "universal `.wp-site-blocks header.wp-block-group.alignfull` "
        "selector so new themes don't need to be hand-added."
    )
    assert ".wp-site-blocks header.wp-block-group.alignfull" in awc.CSS_PHASE_GG


def test_phase_gg_scoped_to_tablet_breakpoint(awc):
    """Wrapping the header nav on desktop (>=782px) would visibly break
    every theme's header layout. The rule MUST be scoped to the
    existing `max-width:781px` tablet+mobile breakpoint that Phase T
    used."""
    assert "@media (max-width:781px)" in awc.CSS_PHASE_GG


def test_phase_t_no_longer_holds_header_rule(awc):
    """Phase T used to own the enumerated header flex-wrap rule; Phase
    GG now owns the universal version. If Phase T regrows the
    enumerated rule, we'll have two rules fighting the same cascade."""
    assert "body.theme-selvedge" not in awc.CSS_PHASE_T
    assert "body.theme-chonk" not in awc.CSS_PHASE_T
    assert "body.theme-lysholm" not in awc.CSS_PHASE_T


# ---------------------------------------------------------------------------
# Integration: chunks list wiring
# ---------------------------------------------------------------------------


def test_phase_ff_registered_before_phase_gg(awc):
    """Phase FF's close sentinel is Phase GG's anchor — reverse the
    order and the splicer can't find the anchor on a fresh theme and
    refuses to install Phase GG. Lock the order in place."""
    sentinels = [open_ for (open_, _, _, _) in awc.CHUNKS]
    assert sentinels.index(awc.SENTINEL_OPEN_PHASE_FF) < sentinels.index(awc.SENTINEL_OPEN_PHASE_GG)


def test_phase_gg_anchor_is_phase_ff_close_sentinel(awc):
    for open_, _close, _css, anchor in awc.CHUNKS:
        if open_ == awc.SENTINEL_OPEN_PHASE_GG:
            assert anchor == awc.SENTINEL_CLOSE_PHASE_FF
            return
    pytest.fail("Phase GG not registered in CHUNKS")
