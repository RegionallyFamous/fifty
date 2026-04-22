"""Tests for `check_wc_notices_styled`.

Phase L (`wc-tells-phase-l-notices`) is the chunk that restyles every WC
notice surface (modern banner + variant signal, per-field validation
error, snackbar, store-notices wrapper, classic message/error/info) using
each theme's existing `info` / `success` / `warning` / `error` palette
tokens. The check enforces presence of the chunk + its canonical surface
selectors so a hand-edit can't silently revert the storefront's notices
to WC's plugin-default voice.
"""

from __future__ import annotations

import json

# Minimal Phase L block: enough to satisfy every "required selector"
# probe in the check, in the same minified one-line shape that
# `bin/append-wc-overrides.py` emits.
PHASE_L_OK = (
    "/* wc-tells-phase-l-notices */"
    " body .wc-block-components-notice-banner{padding:1rem;}"
    " body .wc-block-components-notice-banner.is-info{}"
    " body .wc-block-components-notice-banner.is-success{}"
    " body .wc-block-components-notice-banner.is-warning{}"
    " body .wc-block-components-notice-banner.is-error{}"
    " body .wc-block-components-validation-error{color:red;}"
    " body .wc-block-components-notices__snackbar{position:fixed;}"
    " body .woocommerce-message,body .woocommerce-error,body .woocommerce-info{padding:1rem;}"
    " /* /wc-tells-phase-l-notices */"
)


def _set_styles_css(theme_root, css: str) -> None:
    tj = theme_root / "theme.json"
    data = json.loads(tj.read_text(encoding="utf-8"))
    data["styles"]["css"] = css
    tj.write_text(json.dumps(data), encoding="utf-8")


def test_passes_when_phase_l_block_present(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_styles_css(minimal_theme, PHASE_L_OK)
    result = check.check_wc_notices_styled()
    assert result.passed, result.details


def test_fails_when_sentinel_block_missing(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_styles_css(minimal_theme, ".unrelated-rule{color:red;}")
    result = check.check_wc_notices_styled()
    assert not result.passed
    assert any("wc-tells-phase-l-notices" in d for d in result.details)


def test_fails_when_phase_l_block_is_empty(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_styles_css(
        minimal_theme,
        "/* wc-tells-phase-l-notices */ /* /wc-tells-phase-l-notices */",
    )
    result = check.check_wc_notices_styled()
    assert not result.passed
    assert any("missing canonical" in d for d in result.details)


def test_fails_when_variant_selector_missing(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    # Drop the .is-error variant — every other surface present.
    broken = PHASE_L_OK.replace(" body .wc-block-components-notice-banner.is-error{}", "")
    _set_styles_css(minimal_theme, broken)
    result = check.check_wc_notices_styled()
    assert not result.passed
    assert any("error variant" in d for d in result.details)


def test_fails_when_snackbar_selector_missing(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    broken = PHASE_L_OK.replace(" body .wc-block-components-notices__snackbar{position:fixed;}", "")
    _set_styles_css(minimal_theme, broken)
    result = check.check_wc_notices_styled()
    assert not result.passed
    assert any("snackbar" in d for d in result.details)


def test_accepts_alternative_snackbar_selector(minimal_theme, bind_check_root):
    """Phase L allows EITHER snackbar selector to satisfy the check."""
    check = bind_check_root(minimal_theme)
    swapped = PHASE_L_OK.replace(
        " body .wc-block-components-notices__snackbar{position:fixed;}",
        " body .wc-block-components-notice-snackbar-list{position:fixed;}",
    )
    _set_styles_css(minimal_theme, swapped)
    result = check.check_wc_notices_styled()
    assert result.passed, result.details


def test_skips_on_empty_styles_css(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _set_styles_css(minimal_theme, "")
    result = check.check_wc_notices_styled()
    assert result.skipped, result.details
