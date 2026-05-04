"""Unit tests for `bin/_design_lib.py`.

The lib module is pure functions (no I/O, no subprocess), which is exactly
the surface the agent will lean on when iterating a spec — so it's the
high-leverage place to invest in fast, exhaustive tests.

We test:
  * `validate_spec` — happy path + every documented error class.
  * `apply_palette` — slug match, slug add, idempotency, untouched siblings.
  * `apply_fonts` — fontFamily rewrite, fontFace registration toggle, idempotency.
  * `make_brief` — voice/palette/fonts surface in the markdown.
  * `serialize_theme_json` — round-trip preserves tab indent + trailing newline.
"""

from __future__ import annotations

import copy
import json

import pytest
from _design_lib import (
    allow_non_miles_spec_tools,
    apply_fonts,
    apply_palette,
    apply_token_patches,
    example_spec,
    make_brief,
    serialize_theme_json,
    validate_generation_safety,
    validate_spec,
)


def test_allow_non_miles_spec_tools_env_gate(monkeypatch):
    monkeypatch.delenv("FIFTY_ALLOW_NON_MILES_SPEC", raising=False)
    assert allow_non_miles_spec_tools() is False
    monkeypatch.setenv("FIFTY_ALLOW_NON_MILES_SPEC", "1")
    assert allow_non_miles_spec_tools() is True


# ---------------------------------------------------------------------------
# validate_spec
# ---------------------------------------------------------------------------


def test_validate_spec_accepts_example():
    errors, spec = validate_spec(example_spec())
    assert errors == []
    assert spec is not None
    assert spec.slug == "midcentury"
    assert spec.name == "Midcentury"
    assert spec.source == "obel"
    assert "base" in spec.palette
    assert "display" in spec.fonts
    assert spec.layout_hints  # non-empty


def test_validate_spec_minimal_only_slug_and_name():
    errors, spec = validate_spec({"slug": "tiny", "name": "Tiny"})
    assert errors == []
    assert spec is not None
    assert spec.slug == "tiny"
    assert spec.palette == {}
    assert spec.fonts == {}
    assert spec.layout_hints == []


@pytest.mark.parametrize(
    "raw, expected_path_substr",
    [
        ({"slug": "X bad", "name": "X"}, "$.slug"),
        ({"slug": "ok", "name": ""}, "$.name"),
        ({"slug": "1bad", "name": "X"}, "$.slug"),  # starts with digit
        ({"slug": "x", "name": "X"}, "$.slug"),  # too short
        ({"slug": "ok", "name": "Ok", "tagline": 42}, "$.tagline"),
        ({"slug": "ok", "name": "Ok", "voice": ["wrong"]}, "$.voice"),
        ({"slug": "ok", "name": "Ok", "source": "BAD CASE"}, "$.source"),
    ],
)
def test_validate_spec_rejects_basics(raw, expected_path_substr):
    errors, spec = validate_spec(raw)
    assert spec is None
    assert any(expected_path_substr in str(e) for e in errors), errors


def test_validate_spec_rejects_unknown_top_level_key():
    errors, spec = validate_spec({"slug": "ok", "name": "Ok", "MADE_UP_FIELD": 1})
    assert spec is None
    assert any("MADE_UP_FIELD" in str(e) for e in errors)


def test_validate_spec_rejects_unknown_palette_slug():
    errors, spec = validate_spec({"slug": "ok", "name": "Ok", "palette": {"acent": "#FF0000"}})
    assert spec is None
    assert any("$.palette.acent" in str(e) for e in errors)


@pytest.mark.parametrize(
    "bad_hex",
    ["red", "rgb(0,0,0)", "0xFF0000", "#GGGGGG", "#12", "12345", ""],
)
def test_validate_spec_rejects_bad_hex(bad_hex):
    errors, spec = validate_spec({"slug": "ok", "name": "Ok", "palette": {"base": bad_hex}})
    assert spec is None
    assert any("$.palette.base" in str(e) for e in errors)


@pytest.mark.parametrize(
    "good_hex",
    ["#FFF", "#000", "#FAFAF7", "#fafaf7", "#FFFFFFFF", "#FAFAF7CC"],
)
def test_validate_spec_accepts_valid_hex_forms(good_hex):
    errors, spec = validate_spec({"slug": "ok", "name": "Ok", "palette": {"base": good_hex}})
    assert errors == []
    assert spec is not None
    assert (
        spec.palette["base"].lower() == good_hex.lower()
        if len(good_hex) <= 7
        else spec.palette["base"]
    )


def test_validate_spec_rejects_unknown_font_slug():
    errors, spec = validate_spec(
        {"slug": "ok", "name": "Ok", "fonts": {"fancy": {"family": "Inter"}}}
    )
    assert spec is None
    assert any("$.fonts.fancy" in str(e) for e in errors)


def test_validate_spec_rejects_unknown_font_subkey():
    errors, spec = validate_spec(
        {
            "slug": "ok",
            "name": "Ok",
            "fonts": {"display": {"family": "Inter", "italic": True}},
        }
    )
    assert spec is None
    assert any("$.fonts.display.italic" in str(e) for e in errors)


@pytest.mark.parametrize("bad_weight", [450, 50, 1000, "400", -100])
def test_validate_spec_rejects_bad_font_weight(bad_weight):
    errors, spec = validate_spec(
        {
            "slug": "ok",
            "name": "Ok",
            "fonts": {"display": {"family": "Inter", "weights": [bad_weight]}},
        }
    )
    assert spec is None
    assert any("$.fonts.display.weights[0]" in str(e) for e in errors)


def test_validate_spec_rejects_non_object():
    errors, spec = validate_spec(["this", "is", "a", "list"])
    assert spec is None
    assert errors


def test_generation_safety_rejects_low_contrast_body_tokens():
    raw = example_spec()
    raw["palette"] = {
        "base": "#f5f1e8",
        "contrast": "#e9e0d1",
    }
    errors, spec = validate_spec(raw)

    assert errors == []
    assert spec is not None
    safety_errors = validate_generation_safety(spec)

    assert any("$.palette.contrast" in str(error) for error in safety_errors)


def test_generation_safety_rejects_primary_that_collapses_on_base():
    raw = example_spec()
    raw["palette"] = {
        "base": "#f5f1e8",
        "contrast": "#111111",
        "primary": "#fff1d2",
    }
    errors, spec = validate_spec(raw)

    assert errors == []
    assert spec is not None
    safety_errors = validate_generation_safety(spec)

    assert any("$.palette.primary" in str(error) for error in safety_errors)


def test_generation_safety_rejects_self_clone_source():
    errors, spec = validate_spec({"slug": "agitprop", "name": "Agitprop", "source": "agitprop"})

    assert errors == []
    assert spec is not None
    safety_errors = validate_generation_safety(spec)

    assert any("$.source" in str(error) for error in safety_errors)


# ---------------------------------------------------------------------------
# apply_palette
# ---------------------------------------------------------------------------


def _theme_json_fixture() -> dict:
    """Mirrors the relevant shape of a real theme.json, no need for the full thing."""
    return {
        "version": 3,
        "settings": {
            "color": {
                "palette": [
                    {"slug": "base", "name": "Base", "color": "#FFFFFF"},
                    {"slug": "contrast", "name": "Contrast", "color": "#000000"},
                    {"slug": "accent", "name": "Accent", "color": "#888888"},
                ],
            },
            "typography": {
                "fontFamilies": [
                    {"slug": "sans", "name": "Sans", "fontFamily": "system-ui"},
                    {"slug": "display", "name": "Display", "fontFamily": "Georgia, serif"},
                ],
            },
            "spacing": {
                "spacingSizes": [
                    {"slug": "sm", "name": "Small", "size": "1rem"},
                    {"slug": "md", "name": "Medium", "size": "2rem"},
                ],
            },
            "shadow": {
                "presets": [
                    {"slug": "md", "name": "Medium", "shadow": "0 1px 2px rgba(0,0,0,0.1)"}
                ],
            },
            "custom": {
                "radius": {"sm": "4px", "md": "8px", "lg": "16px"},
                "border": {"width": {"hairline": "1px", "thick": "2px"}},
            },
        },
        "styles": {"css": "/* preserved */"},
    }


def test_apply_palette_swaps_existing_slug():
    tj = _theme_json_fixture()
    apply_palette(tj, {"base": "#F5EFE6"})
    by_slug = {e["slug"]: e for e in tj["settings"]["color"]["palette"]}
    assert by_slug["base"]["color"] == "#F5EFE6"
    # Sibling slugs untouched.
    assert by_slug["contrast"]["color"] == "#000000"
    assert by_slug["accent"]["color"] == "#888888"


def test_apply_palette_appends_new_slug():
    tj = _theme_json_fixture()
    apply_palette(tj, {"primary": "#1F1B16"})
    by_slug = {e["slug"]: e for e in tj["settings"]["color"]["palette"]}
    assert "primary" in by_slug
    assert by_slug["primary"]["color"] == "#1F1B16"
    assert by_slug["primary"]["name"] == "Primary"


def test_apply_palette_appends_compound_slug_with_titlecased_name():
    tj = _theme_json_fixture()
    apply_palette(tj, {"primary-hover": "#403828"})
    by_slug = {e["slug"]: e for e in tj["settings"]["color"]["palette"]}
    assert by_slug["primary-hover"]["name"] == "Primary Hover"


def test_apply_palette_idempotent():
    tj1 = _theme_json_fixture()
    tj2 = copy.deepcopy(tj1)
    apply_palette(tj1, {"base": "#F5EFE6", "accent": "#D87E3A"})
    apply_palette(tj2, {"base": "#F5EFE6", "accent": "#D87E3A"})
    apply_palette(tj2, {"base": "#F5EFE6", "accent": "#D87E3A"})  # twice
    assert tj1 == tj2


def test_apply_palette_preserves_styles_css_blob():
    tj = _theme_json_fixture()
    apply_palette(tj, {"base": "#F5EFE6"})
    assert tj["styles"]["css"] == "/* preserved */"


def test_apply_palette_empty_dict_is_no_op():
    tj = _theme_json_fixture()
    snapshot = copy.deepcopy(tj)
    apply_palette(tj, {})
    assert tj == snapshot


# ---------------------------------------------------------------------------
# apply_fonts
# ---------------------------------------------------------------------------


def test_apply_fonts_rewrites_existing_slot():
    tj = _theme_json_fixture()
    apply_fonts(
        tj,
        {
            "display": {
                "family": "Bricolage Grotesque",
                "fallback": "Helvetica, Arial, sans-serif",
                "google_font": False,
                "weights": [400],
            }
        },
    )
    families = {e["slug"]: e for e in tj["settings"]["typography"]["fontFamilies"]}
    assert (
        families["display"]["fontFamily"] == '"Bricolage Grotesque", Helvetica, Arial, sans-serif'
    )


def test_apply_fonts_single_word_family_not_quoted():
    tj = _theme_json_fixture()
    apply_fonts(
        tj,
        {
            "sans": {
                "family": "Inter",
                "fallback": "system-ui",
                "google_font": False,
                "weights": [400],
            }
        },
    )
    families = {e["slug"]: e for e in tj["settings"]["typography"]["fontFamilies"]}
    assert families["sans"]["fontFamily"] == "Inter, system-ui"


def test_apply_fonts_registers_fontface_when_google_font():
    tj = _theme_json_fixture()
    apply_fonts(
        tj,
        {
            "display": {
                "family": "Bricolage Grotesque",
                "fallback": "Helvetica, Arial, sans-serif",
                "google_font": True,
                "weights": [400, 700],
            }
        },
    )
    families = {e["slug"]: e for e in tj["settings"]["typography"]["fontFamilies"]}
    face = families["display"].get("fontFace")
    assert face is not None
    assert len(face) == 2
    weights_seen = sorted(int(f["fontWeight"]) for f in face)
    assert weights_seen == [400, 700]
    for f in face:
        assert f["fontDisplay"] == "swap"
        assert f["src"][0].startswith("file:./assets/fonts/display-")
        assert f["src"][0].endswith(".woff2")


def test_apply_fonts_drops_fontface_when_switching_back_to_system():
    tj = _theme_json_fixture()
    apply_fonts(
        tj,
        {
            "display": {
                "family": "Bricolage Grotesque",
                "fallback": "",
                "google_font": True,
                "weights": [400],
            }
        },
    )
    apply_fonts(
        tj,
        {
            "display": {
                "family": "Georgia",
                "fallback": "serif",
                "google_font": False,
                "weights": [400],
            }
        },
    )
    families = {e["slug"]: e for e in tj["settings"]["typography"]["fontFamilies"]}
    assert "fontFace" not in families["display"]


def test_apply_fonts_appends_new_slot():
    tj = _theme_json_fixture()
    # `mono` not in fixture initially.
    apply_fonts(
        tj,
        {
            "mono": {
                "family": "JetBrains Mono",
                "fallback": "monospace",
                "google_font": False,
                "weights": [400],
            }
        },
    )
    families = {e["slug"]: e for e in tj["settings"]["typography"]["fontFamilies"]}
    assert "mono" in families
    assert families["mono"]["name"] == "Mono"


def test_apply_fonts_idempotent():
    tj1 = _theme_json_fixture()
    tj2 = copy.deepcopy(tj1)
    payload = {
        "display": {
            "family": "Bricolage Grotesque",
            "fallback": "Helvetica, sans-serif",
            "google_font": True,
            "weights": [400, 700],
        }
    }
    apply_fonts(tj1, payload)
    apply_fonts(tj2, payload)
    apply_fonts(tj2, payload)
    assert tj1 == tj2


# ---------------------------------------------------------------------------
# apply_token_patches
# ---------------------------------------------------------------------------


def test_apply_token_patches_updates_allowed_tokens_and_css():
    tj = _theme_json_fixture()
    updated = apply_token_patches(
        tj,
        {
            "schema": 1,
            "spacing_sizes": [{"slug": "sm", "size": "0.5rem"}],
            "shadow_presets": [{"slug": "md", "shadow": "0 2px 8px rgba(0,0,0,0.2)"}],
            "custom_radius": {"sm": "0", "md": "0"},
            "custom_border_width": {"thick": "3px"},
            "styles_css_append": ".wp-block-button__link { border-radius: 0; }",
        },
    )

    assert tj["settings"]["spacing"]["spacingSizes"][0]["size"] == "1rem"
    by_spacing = {e["slug"]: e for e in updated["settings"]["spacing"]["spacingSizes"]}
    by_shadow = {e["slug"]: e for e in updated["settings"]["shadow"]["presets"]}
    assert by_spacing["sm"]["size"] == "0.5rem"
    assert by_shadow["md"]["shadow"] == "0 2px 8px rgba(0,0,0,0.2)"
    assert updated["settings"]["custom"]["radius"]["sm"] == "0"
    assert updated["settings"]["custom"]["border"]["width"]["thick"] == "3px"
    assert ".wp-block-button__link" in updated["styles"]["css"]


def test_apply_token_patches_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown token patch"):
        apply_token_patches(_theme_json_fixture(), {"palette": {"base": "#000000"}})


def test_apply_token_patches_idempotent():
    tj = _theme_json_fixture()
    patch = {
        "spacing_sizes": [{"slug": "sm", "size": "0.5rem"}],
        "styles_css_append": ".wp-block-button__link { border-radius: 0; }",
    }
    once = apply_token_patches(tj, patch)
    twice = apply_token_patches(once, patch)
    assert once == twice


# ---------------------------------------------------------------------------
# make_brief
# ---------------------------------------------------------------------------


def test_make_brief_includes_voice_and_layout(tmp_path):
    _, spec = validate_spec(example_spec())
    assert spec is not None
    brief = make_brief(spec, tmp_path / "midcentury")
    assert "Midcentury" in brief
    assert "department store" in brief  # voice keyword
    assert "asymmetric hero" in brief  # layout hint
    # Palette table.
    assert "| `base` |" in brief
    # Google Font instruction surfaces.
    assert "Bricolage Grotesque" in brief
    assert "gwfh.mranftl.com" in brief
    # Numbered next steps surface.
    assert "Next steps" in brief
    assert "snap baseline" in brief.lower() or "snap.py shoot" in brief


def test_make_brief_minimal_spec_still_well_formed(tmp_path):
    _, spec = validate_spec({"slug": "tiny", "name": "Tiny"})
    assert spec is not None
    brief = make_brief(spec, tmp_path / "tiny")
    assert brief.startswith("# Tiny — design brief")
    assert "Next steps" in brief


# ---------------------------------------------------------------------------
# serialize_theme_json
# ---------------------------------------------------------------------------


def test_serialize_theme_json_uses_tabs_and_trailing_newline():
    tj = {"version": 3, "settings": {"color": {"palette": [{"slug": "base", "color": "#FFF"}]}}}
    out = serialize_theme_json(tj)
    assert out.endswith("\n")
    # First indent level should be a single tab.
    assert '\n\t"settings":' in out


def test_serialize_theme_json_round_trip_stable():
    tj = {"version": 3, "settings": {"color": {"palette": [{"slug": "base", "color": "#FFF"}]}}}
    once = serialize_theme_json(tj)
    twice = serialize_theme_json(json.loads(once))
    assert once == twice
