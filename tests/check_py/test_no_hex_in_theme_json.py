"""Tests for `check_no_hex_in_theme_json`.

Raw hex allowed ONLY inside palette / gradients / duotone. Anywhere else
(inline CSS, shadow presets, block-level styles) must use tokens.
"""

from __future__ import annotations

import json


def test_passes_on_minimal_theme(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_hex_in_theme_json().passed


def test_hex_in_styles_css_string_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["css"] = ".x { color: #abcdef; }"
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    result = check.check_no_hex_in_theme_json()
    assert not result.passed
    assert any("#abcdef" in d for d in result.details)


def test_hex_in_block_level_styles_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["blocks"] = {
        "core/button": {"color": {"background": "#123456"}},
    }
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    assert not check.check_no_hex_in_theme_json().passed


def test_hex_in_palette_is_allowed(minimal_theme, bind_check_root):
    """The palette is literally where hex values belong."""
    check = bind_check_root(minimal_theme)
    # minimal_theme.json already declares #FAFAF7 etc. in palette
    assert check.check_no_hex_in_theme_json().passed
