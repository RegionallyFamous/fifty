"""Static-ish tests for `bin/design.py::_warn_uncovered_polarity_slugs`
and its companion helper `_wcag_luminance_hex`.

The warning is the soft signal that the `check` phase's
`check_palette_polarity_coherent` is the hard signal for. Keeping it
catches the cipher bug-class at apply time (10 seconds of pipeline
work) rather than at check time (~8 minutes of snap + check), which
matters for an LLM-driven spec authoring loop where the operator is
iterating on the spec under their own time pressure.

The test shape mirrors `tests/tools/test_design_phases.py` — static
inspection plus a direct call where the helper is pure enough to run
without Playground.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import design  # noqa: E402
from _design_lib import ValidatedSpec  # noqa: E402


def _theme_json_with(base: str, slugs: dict[str, str]) -> dict:
    """Build a minimal theme.json payload with a given `base` and
    extra palette entries. Matches the shape `_phase_apply` passes
    to `_warn_uncovered_polarity_slugs` (the already-loaded dict,
    pre-palette-mutation)."""
    entries = [{"slug": "base", "name": "Base", "color": base}]
    for slug, color in slugs.items():
        entries.append({"slug": slug, "name": slug.title(), "color": color})
    return {"settings": {"color": {"palette": entries}}}


def _spec(palette: dict[str, str], source: str = "obel") -> ValidatedSpec:
    return ValidatedSpec(slug="childtheme", name="Child Theme", source=source, palette=palette)


# ---------------------------------------------------------------------------
# Luminance helper
# ---------------------------------------------------------------------------


def test_luminance_returns_zero_for_pure_black():
    assert design._wcag_luminance_hex("#000000") == 0.0


def test_luminance_returns_one_for_pure_white():
    # Floating-point tolerance — the formula produces 1.0 within 1e-12.
    result = design._wcag_luminance_hex("#FFFFFF")
    assert result is not None
    assert abs(result - 1.0) < 1e-9


def test_luminance_handles_no_leading_hash():
    assert design._wcag_luminance_hex("FFFFFF") is not None


def test_luminance_returns_none_for_malformed_hex():
    assert design._wcag_luminance_hex("not-a-hex") is None
    assert design._wcag_luminance_hex("#ZZZZZZ") is None
    assert design._wcag_luminance_hex("#FFF") is None  # short form not supported


# ---------------------------------------------------------------------------
# Silence conditions (no warning fires)
# ---------------------------------------------------------------------------


def test_warn_silent_when_base_polarity_unchanged():
    """Obel (light) → a new light-base theme that also covers `subtle`
    etc. No polarity flip means stale slugs are on the right side
    already; no warning needed."""
    theme_json = _theme_json_with("#FAFAF7", {"subtle": "#F2F1EC", "surface": "#FFFFFF"})
    spec = _spec({"base": "#F5F1E8"})  # also light

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    assert buf.getvalue() == ""


def test_warn_silent_when_spec_covers_every_critical_slug():
    """Dark-base spec that DOES enumerate `subtle`/`surface`/`accent-soft`
    — apply will overwrite them, nothing stale remains, no warning."""
    theme_json = _theme_json_with(
        "#FAFAF7",
        {"subtle": "#F2F1EC", "surface": "#FFFFFF", "accent-soft": "#EFD9C3"},
    )
    spec = _spec(
        {
            "base": "#0F1622",
            "subtle": "#18212F",
            "surface": "#18212F",
            "accent-soft": "#2A1608",
        }
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    assert buf.getvalue() == ""


def test_warn_silent_when_source_has_no_base():
    """Degenerate source theme.json — helper just returns, no crash."""
    theme_json = {"settings": {"color": {"palette": []}}}
    spec = _spec({"base": "#0F1622"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    assert buf.getvalue() == ""


def test_warn_silent_when_spec_has_no_base():
    """Spec that rewrites palette slugs but leaves `base` alone — no
    polarity flip is possible, so the helper returns silently."""
    theme_json = _theme_json_with("#FAFAF7", {"subtle": "#F2F1EC"})
    spec = _spec({"accent": "#C07241"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# Warning fires (the cipher-shape case)
# ---------------------------------------------------------------------------


def test_warn_fires_on_cipher_shape():
    """The canonical case. Obel (light base) → cipher (dark base), spec
    covers only the 7 core tokens so `subtle` / `surface` / `accent-soft`
    would stay at obel's light values. The warning names each one
    plus its stale hex and the polarity direction."""
    theme_json = _theme_json_with(
        "#FAFAF7",
        {
            "subtle": "#F2F1EC",
            "surface": "#FFFFFF",
            "accent-soft": "#EFD9C3",
        },
    )
    spec = _spec({"base": "#0F1622", "contrast": "#E5DFCE"})  # no subtle/surface/accent-soft

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    output = buf.getvalue()
    assert "WARN" in output
    assert "light → dark" in output
    assert "subtle" in output
    assert "surface" in output
    assert "accent-soft" in output
    assert "#F2F1EC" in output
    assert "3 polarity-critical slug(s)" in output


def test_warn_fires_on_dark_to_light_flip():
    """Symmetric case. Selvedge-style (dark) source → a new light-base
    spec that leaves `subtle` and `surface` as dark leftovers."""
    theme_json = _theme_json_with(
        "#160F08",
        {"subtle": "#2C2016", "surface": "#1F1610", "accent-soft": "#2A1608"},
    )
    spec = _spec({"base": "#FFFFFF"}, source="selvedge")

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    output = buf.getvalue()
    assert "WARN" in output
    assert "dark → light" in output
    assert "subtle" in output
    assert "from selvedge" in output


def test_warn_enumerates_only_the_slugs_actually_missing_from_spec():
    """Spec that partially covers the critical slugs — warning mentions
    only the ones still missing. If the operator fixed `subtle` but
    not `surface`, they should see a one-slug warning, not a three-
    slug one."""
    theme_json = _theme_json_with(
        "#FAFAF7",
        {"subtle": "#F2F1EC", "surface": "#FFFFFF", "accent-soft": "#EFD9C3"},
    )
    spec = _spec(
        {
            "base": "#0F1622",
            "subtle": "#18212F",  # covered
            # surface, accent-soft still uncovered
        }
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        design._warn_uncovered_polarity_slugs(theme_json, spec)

    output = buf.getvalue()
    assert "2 polarity-critical slug(s)" in output
    assert "surface" in output
    assert "accent-soft" in output
    # `subtle` was covered by the spec — shouldn't appear in the warning.
    lines = [ln for ln in output.splitlines() if ln.strip().startswith("[apply] WARN:   ")]
    assert not any("`subtle:" in ln for ln in lines), (
        "subtle was in spec.palette; it should not appear in the uncovered list"
    )


# ---------------------------------------------------------------------------
# Drift check with bin/check.py
# ---------------------------------------------------------------------------


def test_apply_warning_slug_list_matches_check_list():
    """The warning list and the check's sameside-slug set must stay in
    lockstep. Divergence would mean either: (a) the operator sees a
    warning for a slug the check doesn't gate on, creating wasted
    spec iteration, or (b) the check fails on a slug the warning
    never mentioned, leaving the operator blindsided mid-pipeline.

    Import the frozenset from `bin/check.py` (readonly, no side
    effects) and compare sets."""
    import check  # noqa: E402

    warn_slugs = set(design._APPLY_POLARITY_CRITICAL_SLUGS)
    gate_slugs = set(check._BASE_POLARITY_SAMESIDE_SLUGS)
    assert warn_slugs == gate_slugs, (
        f"drift between design.py warning ({sorted(warn_slugs)}) "
        f"and check.py gate ({sorted(gate_slugs)}) — keep them in sync"
    )
