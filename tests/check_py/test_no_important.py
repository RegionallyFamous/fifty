"""Tests for `check_no_important`.

The check scans `.json`, `.php`, `.html`, `.css` files in the theme for
`!important`, excluding rule docs (AGENTS.md, README.md, …) and
sentinel-bracketed chunks inside `theme.json`.
"""

from __future__ import annotations


def test_minimal_theme_has_no_important(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_important().passed


def test_fails_when_important_in_html_template(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        '<!-- wp:paragraph --><p style="color:red !important">x</p><!-- /wp:paragraph -->\n',
        encoding="utf-8",
    )
    result = check.check_no_important()
    assert not result.passed
    assert any("page.html" in d for d in result.details)


def test_fails_when_important_in_inlined_theme_json_css(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    import json

    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["css"] = ".btn { color: red !important; }"
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    assert not check.check_no_important().passed


def test_important_allowed_inside_sentinel_block(minimal_theme, bind_check_root):
    """Sentinel-bracketed WC override chunks legitimately need !important."""
    check = bind_check_root(minimal_theme)
    import json

    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["css"] = (
        "/* wc-tells-phase-a-premium */"
        ".something { color: red !important; }"
        "/* /wc-tells-phase-a-premium */"
    )
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    assert check.check_no_important().passed
