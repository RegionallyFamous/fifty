"""Tests for `check_no_remote_fonts`.

Self-hosted Google Fonts only; every `fontFace.src` MUST start with
`file:./assets/fonts/...`. Any reference to a font CDN is forbidden
in theme.json strings AND in templates/parts/patterns/*.php.
"""

from __future__ import annotations

import json


def test_minimal_has_no_font_faces(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_remote_fonts().passed


def test_file_scheme_src_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["settings"]["typography"]["fontFamilies"][0]["fontFace"] = [
        {"src": "file:./assets/fonts/test.woff2", "fontWeight": "400"}
    ]
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    assert check.check_no_remote_fonts().passed


def test_remote_src_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["settings"]["typography"]["fontFamilies"][0]["fontFace"] = [
        {"src": "https://fonts.gstatic.com/s/test.woff2", "fontWeight": "400"}
    ]
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    result = check.check_no_remote_fonts()
    assert not result.passed


def test_google_fonts_mention_in_functions_php_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "functions.php").write_text(
        "<?php wp_enqueue_style( 'g', 'https://fonts.googleapis.com/css' );\n",
        encoding="utf-8",
    )
    assert not check.check_no_remote_fonts().passed


def test_typekit_in_template_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "index.html").write_text(
        '<!-- wp:html --><link rel="stylesheet" href="https://use.typekit.net/abc.css"><!-- /wp:html -->\n',
        encoding="utf-8",
    )
    assert not check.check_no_remote_fonts().passed
