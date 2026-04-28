"""Tests for `check_hover_state_legibility`.

Walks the CSS string inside `theme.json`, resolves each `:hover` /
`:focus` / `:active` rule's text + background to palette hex values, and
computes WCAG contrast. Anything below 3:1 fails.

Chose real-world values so the ratios we assert match what the
production rule catches on Chonk / Lysholm cart pages.
"""

from __future__ import annotations

import json


def _set_css(theme_root, css: str) -> None:
    data = json.loads((theme_root / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["css"] = css
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


def test_minimal_theme_has_no_hover_rules(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    result = check.check_hover_state_legibility()
    # Minimal theme has no inlined styles.css, so the check skips.
    assert result.passed or result.skipped


def test_legible_hover_passes(minimal_theme, bind_check_root):
    """contrast (dark text) on base (cream) is >= 3:1."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover { color: var(--wp--preset--color--contrast); "
        "background: var(--wp--preset--color--base); }",
    )
    assert check.check_hover_state_legibility().passed


def test_illegible_hover_fails(minimal_theme, bind_check_root):
    """base (cream) text on base (cream) background is ~1:1."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover { color: var(--wp--preset--color--base); "
        "background: var(--wp--preset--color--base); }",
    )
    result = check.check_hover_state_legibility()
    assert not result.passed


def test_hover_with_non_palette_bg_is_skipped(minimal_theme, bind_check_root):
    """Rule sets a gradient background the check can't reason about — skipped."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover { color: var(--wp--preset--color--base); "
        "background: linear-gradient(0deg, red, blue); }",
    )
    # Passing is fine: the rule sets a non-palette background, so the
    # check bails out rather than fail on an unreasonable-to-compute
    # contrast ratio.
    assert check.check_hover_state_legibility().passed


def test_hover_parses_var_fallback_chain(minimal_theme, bind_check_root):
    """The WC override boilerplate uses a `var(--X, var(--Y))` fallback
    chain; the old regex couldn't parse it and the check silently
    passed unpalatable hover colours. The new regex treats `)` AND `,`
    as the slug terminator so the primary slug is captured correctly.

    This fixture declares a hover rule where the primary slug is
    `primary` (#3A352B, dark warm) and the fallback is `contrast`.
    primary-on-base is ~7.8:1 so this passes — the test is confirming
    we don't CRASH / misparse (the old behavior was to never match the
    rule at all, letting bad combos through). A separate fixture
    below asserts that a bad primary slug is caught."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover{"
        "color:var(--wp--preset--color--primary,var(--wp--preset--color--contrast));"
        "background:var(--wp--preset--color--base);}",
    )
    assert check.check_hover_state_legibility().passed


def test_hover_catches_bad_primary_slug_in_fallback_chain(minimal_theme, bind_check_root):
    """Same fallback-chain shape, but this time the primary slug is
    `base` — cream on cream = ~1:1. The check must flag the primary
    (what the browser actually paints), not the fallback."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover{"
        "color:var(--wp--preset--color--base,var(--wp--preset--color--contrast));"
        "background:var(--wp--preset--color--base);}",
    )
    assert not check.check_hover_state_legibility().passed


def test_hover_skips_other_theme_prefixed_rule_after_comment(minimal_theme, bind_check_root):
    """`body.theme-<other-slug>` rules are inert at runtime in the
    current theme's cascade — the body class isn't on the <html> /
    <body> of this theme, so the rule never matches. The check has
    always tried to skip them, but when a theme.json's styles.css
    string places a CSS comment immediately before such a rule (which
    `bin/append-wc-overrides.py`'s Phase FF does, intentionally, to
    document the sentinel), the top-level rule regex `[^{}]+\\{...\\}`
    greedily consumes the comment into the `sels` group. The old code
    took `sels.split(",")[0]` to find the first selector — but with a
    leading `/* wc-tells-phase-ff-... */`, `first_sel` started with
    `/*` and the `^body\\.theme-(...)` prefix match silently failed,
    so the other-theme rule WAS evaluated against the current theme's
    palette, producing a bogus failure.

    This test repro's exactly that shape: a comment-leading rule
    scoped to `body.theme-cipher` in a theme whose palette happens to
    make the rule look like a contrast violation when mis-parsed. The
    check must still skip the rule because the first non-comment
    selector starts with `body.theme-cipher`, not the theme we're
    auditing. The minimal-theme palette has `base #FAFAF7` and
    `accent #C07241`; `base`-on-`accent` is 3.51:1 (passes) so the
    mis-parse only fires when the palette flips. We use chonk-ish
    yellow as the accent to reproduce the 1.12:1 failure case.

    If this test fails, the comment-stripping step in
    `check_hover_state_legibility` has regressed and cross-theme
    rules will once again trip the gate on themes that don't own
    them."""
    check = bind_check_root(minimal_theme)
    # Rewrite the minimal theme's palette so `base`-on-`accent` fails
    # the 3:1 floor. Mimics chonk: cream base + electric-yellow accent.
    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    for entry in data["settings"]["color"]["palette"]:
        if entry["slug"] == "accent":
            entry["color"] = "#FFE600"
    # The rule is scoped to `body.theme-cipher`, preceded by a sentinel
    # comment — exactly the shape Phase FF produces. Even though the
    # rule LOOKS like `background:accent;color:base` (which fails 1.12:1
    # on this palette), it must NOT be evaluated because the body
    # class `.theme-cipher` won't match on this theme.
    data["styles"]["css"] = (
        "/* wc-tells-phase-ff-hover-polarity-autoflip */"
        "body.theme-cipher.theme-cipher .btn:hover{"
        "background:var(--wp--preset--color--accent);"
        "color:var(--wp--preset--color--base);}"
    )
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    result = check.check_hover_state_legibility()
    assert result.passed, (
        f"Rule scoped to `body.theme-cipher` was evaluated against "
        f"the current theme's palette: {result.details}"
    )
