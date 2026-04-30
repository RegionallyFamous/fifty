"""Unit tests for `bin/_design_target_lib.py` and the two CLIs.

The target lib is the new deterministic shoulder of the design factory:
mockups/<slug>.meta.json (concept queue) → DesignTarget → expanded
16-slug palette + per-theme design-intent.md. We test it ruthlessly
because every other phase downstream consumes its output verbatim.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


@pytest.fixture(autouse=True)
def _import_lib():
    """Re-import the lib for every test so monkeypatched globals leak nowhere."""
    if "_design_target_lib" in sys.modules:
        del sys.modules["_design_target_lib"]
    import _design_target_lib  # noqa: F401  (imported for side effects)


def _meta(**overrides):
    base = {
        "slug": "agitprop",
        "name": "Agitprop",
        "blurb": "Soviet constructivist storefront.",
        "tags": {
            "palette": ["scarlet", "black", "cream"],
            "type": "geometric-sans",
            "era": "pre-1950",
            "sector": "art-print",
            "hero": "type-led",
        },
        "palette_hex": ["#e7dcc2", "#be2428", "#110e07", "#aea894", "#726c5e"],
        "type_specimen": "Display: Bebas Neue. Body: Roboto Condensed.",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Color helpers                                                                #
# --------------------------------------------------------------------------- #
def test_normalize_hex_lowercases_and_prefixes():
    import _design_target_lib as dt

    assert dt.normalize_hex("FAFAF7") == "#fafaf7"
    assert dt.normalize_hex("#FAFAF7") == "#fafaf7"
    assert dt.normalize_hex(" #FaFaF7 ") == "#fafaf7"
    with pytest.raises(ValueError):
        dt.normalize_hex("not-a-hex")
    with pytest.raises(ValueError):
        dt.normalize_hex("#fff")  # 3-digit shorthand not accepted


def test_contrast_ratio_paper_vs_ink_is_high():
    import _design_target_lib as dt

    assert dt.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, rel=0.01)
    # WCAG threshold cases
    assert dt.contrast_ratio("#fafaf7", "#1a1916") > 12.0


# --------------------------------------------------------------------------- #
# Palette classifier                                                           #
# --------------------------------------------------------------------------- #
def test_classify_palette_picks_paper_ink_accent_chrome():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    assert target.palette["paper"] == "#e7dcc2"  # lightest
    assert target.palette["ink"] == "#110e07"  # darkest
    assert target.palette["accent"] == "#be2428"  # most saturated non-paper-ink
    # The two remaining hexes get sorted lightest-first into chrome_warm/chrome_cool
    assert target.palette["chrome_warm"] == "#aea894"
    assert target.palette["chrome_cool"] == "#726c5e"


def test_classify_palette_handles_short_palette():
    import _design_target_lib as dt

    meta = _meta(palette_hex=["#fafaf7", "#1a1916", "#3a352b"])  # only 3 hexes
    target = dt.derive_target_from_meta("obel", meta)
    assert target.palette["paper"] == "#fafaf7"
    assert target.palette["ink"] == "#1a1916"
    # Accent picked from the remaining hex
    assert target.palette["accent"] == "#3a352b"
    # Chrome slugs are derived (or absent and filled by the expander later)
    assert "chrome_warm" not in target.palette


# --------------------------------------------------------------------------- #
# Palette expansion                                                            #
# --------------------------------------------------------------------------- #
def test_expand_palette_fills_every_canonical_slug():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    expanded = dt.expand_palette(target)
    expected = {
        "base",
        "surface",
        "subtle",
        "accent-soft",
        "muted",
        "secondary",
        "tertiary",
        "contrast",
        "border",
        "primary",
        "primary-hover",
        "accent",
        "success",
        "warning",
        "error",
        "info",
    }
    assert set(expanded) == expected
    # Every value is a valid lowercase hex
    for slug, hex_value in expanded.items():
        assert hex_value.startswith("#"), slug
        assert hex_value == hex_value.lower(), slug
        assert len(hex_value) == 7, slug


def test_expand_palette_secondary_clears_aa_normal_on_paper():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    expanded = dt.expand_palette(target)
    # secondary is used as paragraph text in patterns; must clear 4.5:1
    assert dt.contrast_ratio(expanded["secondary"], expanded["base"]) >= 4.5
    assert dt.contrast_ratio(expanded["tertiary"], expanded["base"]) >= 4.5
    # muted is for icon fills; AA-Large (3:1) is enough
    assert dt.contrast_ratio(expanded["muted"], expanded["base"]) >= 3.0


def test_expand_palette_primary_hover_is_distinct_from_primary():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    expanded = dt.expand_palette(target)
    assert expanded["primary"] != expanded["primary-hover"], (
        "primary-hover must visibly differ from primary so the hover state reads"
    )


def test_expand_palette_alerts_are_not_obel_defaults():
    """Pre-target, every theme inherited Obel's success/warning/error/info
    (#2F7A4D / #B58231 / #B33A3A / #3A6FB3). The whole point of the
    deterministic expander is to produce per-theme alerts on a non-Obel
    palette. This test enforces that specifically.
    """
    import _design_target_lib as dt

    obel_alerts = {"#2f7a4d", "#b58231", "#b33a3a", "#3a6fb3"}
    target = dt.derive_target_from_meta("agitprop", _meta())
    expanded = dt.expand_palette(target)
    for slug in ("success", "warning", "error", "info"):
        assert expanded[slug] not in obel_alerts, (
            f"{slug}={expanded[slug]} regressed to an Obel default"
        )


def test_expand_palette_explicit_slug_wins_over_derivation():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    target.palette["primary_hover"] = "#deadbe"
    expanded = dt.expand_palette(target)
    assert expanded["primary-hover"] == "#deadbe"


def test_expand_palette_handles_dark_paper():
    """A theme whose paper is actually dark (Selvedge-style) must still
    produce a coherent ladder. Surface lifts toward ink (which is lighter
    than paper in this case, since paper IS the darkest tone) and accent
    stays brand-correct.
    """
    import _design_target_lib as dt

    meta = _meta(palette_hex=["#1a1208", "#ede3ce", "#d06030"])
    target = dt.derive_target_from_meta("selvedge-test", meta)
    # The classifier should pick the lightest as ink (because paper must
    # be dark in this case → flip is fine, the expander still works).
    expanded = dt.expand_palette(target)
    assert all(v.startswith("#") and len(v) == 7 for v in expanded.values())


# --------------------------------------------------------------------------- #
# Composition / signals                                                        #
# --------------------------------------------------------------------------- #
def test_derive_target_from_meta_picks_manifesto_register_for_art_print():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    assert target.voice["register"] == "manifesto"
    # And manifesto register should add an "imperative microcopy" required signal
    assert any("Imperative microcopy" in s for s in target.required_signals)


def test_derive_target_from_meta_picks_diagonal_ornament_for_art_print():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    assert target.composition["ornament"] == "diagonal"
    assert target.composition["hero"] == "type-led"
    assert target.composition["borders"] == "hard"


def test_signals_for_photo_led_hero_are_different():
    import _design_target_lib as dt

    meta = _meta(
        tags={
            "palette": ["sand"],
            "type": "modern-serif",
            "sector": "florist",
            "hero": "photo-led",
        },
    )
    target = dt.derive_target_from_meta("test-photo", meta)
    assert target.composition["hero"] == "photo-led"
    assert any("Photographic hero" in s for s in target.required_signals)
    assert any("All-caps" in s for s in target.forbidden_signals)


# --------------------------------------------------------------------------- #
# Round-trip                                                                   #
# --------------------------------------------------------------------------- #
def test_target_roundtrips_through_json(tmp_path):
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    out = tmp_path / "design-target.json"
    dt.write_target(target, out)
    loaded = dt.read_target(out)
    assert loaded.palette == target.palette
    assert loaded.composition == target.composition
    assert loaded.required_signals == target.required_signals


def test_target_from_dict_rejects_missing_palette():
    import _design_target_lib as dt

    with pytest.raises(ValueError, match="paper"):
        dt.DesignTarget.from_dict(
            {
                "schema": 1,
                "slug": "x",
                "name": "X",
                "palette": {"accent": "#ff0000"},
                "type": {},
                "voice": {},
                "composition": {},
                "required_signals": [],
                "forbidden_signals": [],
            }
        )


def test_target_from_dict_rejects_unknown_schema():
    import _design_target_lib as dt

    with pytest.raises(ValueError, match="schema"):
        dt.DesignTarget.from_dict(
            {
                "schema": 99,
                "slug": "x",
                "name": "X",
                "palette": {"paper": "#fff", "ink": "#000", "accent": "#f00"},
                "type": {},
                "voice": {},
                "composition": {},
                "required_signals": [],
                "forbidden_signals": [],
            }
        )


# --------------------------------------------------------------------------- #
# design-intent.md rendering                                                   #
# --------------------------------------------------------------------------- #
def test_render_design_intent_md_is_per_theme():
    """Two themes must produce two different rubrics. Pre-target, every
    theme cloned Obel's verbatim — this test pins the new behavior."""
    import _design_target_lib as dt

    agitprop = dt.derive_target_from_meta("agitprop", _meta())
    distillery_meta = _meta(
        slug="distillery",
        name="Distillery",
        blurb="Engraved spirits label, etched ornament, deep amber.",
        tags={
            "palette": ["amber"],
            "type": "engraved",
            "era": "1900s",
            "sector": "distillery",
            "hero": "engraved-led",
        },
        palette_hex=["#1a0d04", "#d8b677", "#52371a", "#867159", "#352011"],
        type_specimen="Display: Cormorant Garamond. Body: Inter.",
    )
    distillery = dt.derive_target_from_meta("distillery", distillery_meta)

    a_rubric = dt.render_design_intent_md(agitprop)
    d_rubric = dt.render_design_intent_md(distillery)

    assert a_rubric != d_rubric
    assert "agitprop" in a_rubric.lower()
    assert "distillery" in d_rubric.lower()
    # The two themes have different registers + ornaments → both should
    # be visible in the generated rubric body.
    assert "manifesto" in a_rubric
    assert "workshop" in d_rubric
    assert "diagonal" in a_rubric.lower()
    assert "etched" in d_rubric.lower()


def test_render_design_intent_md_includes_full_palette_table():
    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    rubric = dt.render_design_intent_md(target)
    # Every primary slug must be cited in the rubric
    for slug in ("base", "surface", "subtle", "contrast", "accent", "primary", "primary-hover"):
        assert f"`{slug}`" in rubric, slug


# --------------------------------------------------------------------------- #
# Renderer (writes theme.json + design-intent.md)                              #
# --------------------------------------------------------------------------- #
def test_render_design_target_cli_round_trip(tmp_path, monkeypatch):
    """Drive the renderer against a fake monorepo and assert the
    theme.json palette + design-intent.md actually change shape.
    """
    # Build a minimal theme tree
    root = tmp_path / "fake-monorepo"
    theme_dir = root / "agitprop"
    theme_dir.mkdir(parents=True)

    base_theme = {
        "$schema": "https://schemas.wp.org/trunk/theme.json",
        "version": 3,
        "settings": {
            "color": {
                "palette": [
                    {"slug": "base", "name": "Base", "color": "#FAFAF7"},  # Obel default
                    {"slug": "contrast", "name": "Contrast", "color": "#1A1916"},
                    {"slug": "primary", "name": "Primary", "color": "#3A352B"},
                    {"slug": "primary-hover", "name": "Primary Hover", "color": "#3D3D3D"},
                    {"slug": "accent", "name": "Accent", "color": "#C07241"},
                    {"slug": "success", "name": "Success", "color": "#2F7A4D"},
                ],
            },
            "typography": {"fontFamilies": []},
        },
        "styles": {"css": ""},
    }
    (theme_dir / "theme.json").write_text(json.dumps(base_theme, indent=2), encoding="utf-8")

    import _design_target_lib as dt

    target = dt.derive_target_from_meta("agitprop", _meta())
    (theme_dir / "design-target.json").write_text(
        json.dumps(target.to_dict(), indent=2), encoding="utf-8"
    )

    # Patch MONOREPO_ROOT in the renderer module
    import _lib

    monkeypatch.setattr(_lib, "MONOREPO_ROOT", root)
    if "render_design_target" in sys.modules:
        del sys.modules["render_design_target"]
    sys.path.insert(0, str(BIN_DIR))
    import importlib

    spec = importlib.util.spec_from_file_location(
        "render_design_target", BIN_DIR / "render-design-target.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(module, "MONOREPO_ROOT", root, raising=False)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "MONOREPO_ROOT", root)
    rc = module.main(["agitprop"])
    assert rc == 0

    new_theme = json.loads((theme_dir / "theme.json").read_text(encoding="utf-8"))
    by_slug = {
        entry["slug"]: entry["color"].lower() for entry in new_theme["settings"]["color"]["palette"]
    }
    # Obel's success #2F7A4D MUST be gone now — the deterministic alert
    # retoner replaced it with something derived from agitprop's
    # paper+ink anchors.
    assert by_slug["success"] != "#2f7a4d"
    # primary-hover must no longer be the grey #3D3D3D
    assert by_slug["primary-hover"] != "#3d3d3d"
    # base should be agitprop paper, not Obel paper
    assert by_slug["base"] == "#e7dcc2"

    intent = (theme_dir / "design-intent.md").read_text(encoding="utf-8")
    assert "agitprop" in intent.lower()
    assert "manifesto" in intent
    # And critically: NOT "quiet, considered, editorial" (Obel's voice)
    assert "quiet, considered" not in intent
