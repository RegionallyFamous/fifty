"""Tests for `bin/concept-to-spec.py` (Tier 1.2, pre-100-themes hardening).

Coverage plan
-------------
The script has three layers:

  1. Pure helpers (`_parse_type_specimen`, `build_palette`, `build_fonts`,
     `build_layout_hints`, `_default_source_theme`). Unit-tested in isolation
     with hand-crafted concept dicts.

  2. Deterministic `concept_to_spec(concept)` orchestrator. Tested against
     every entry in `bin/concept_seed.CONCEPTS` to guarantee the full
     concept list produces validated specs without an LLM hop. This is
     the real test that catches controlled-vocab drift.

  3. CLI plumbing (`--slug`, `--no-llm`, `--print-only`, error exits).
     Exercised via `subprocess.run` so argparse wiring is verified.

The LLM path is NOT exercised live (tests stay offline). A lightweight
double ensures `concept_to_spec_llm(..., dry_run=True)` falls through to
the deterministic path so future refactors can't silently break the dry-
run smoke.

Every concept in `concept_seed.CONCEPTS` SHOULD yield a valid spec. If
this test fails, the most likely cause is (a) a typo in a new concept's
palette_tags, or (b) a new token added to `PALETTE_TOKENS` without a
matching entry in `PALETTE_TAG_TO_HEX`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bin" / "concept-to-spec.py"


# ---------------------------------------------------------------------------
# Module loading. The file has a hyphenated name, so we load it via a spec
# (the same pattern test_snap_signatures.py uses for bin/snap.py).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def c2s():
    """Load bin/concept-to-spec.py as a live module."""
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    spec = importlib.util.spec_from_file_location("concept_to_spec", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["concept_to_spec"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def concepts():
    """Return the raw CONCEPTS list from bin/concept_seed.py."""
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    from concept_seed import CONCEPTS

    return CONCEPTS


@pytest.fixture(scope="module")
def palette_tokens():
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    from concept_seed import PALETTE_TOKENS

    return PALETTE_TOKENS


# ---------------------------------------------------------------------------
# Controlled-vocab coverage. This is the contract test that catches new
# palette tokens added without a matching hex, or new type_genres added
# without a matching font pair.
# ---------------------------------------------------------------------------


def test_every_palette_token_has_a_hex(c2s, palette_tokens):
    """Every token in `concept_seed.PALETTE_TOKENS` MUST map to a hex.

    Adding a token to `PALETTE_TOKENS` without a hex here would mean
    the first concept using the new token silently crashes `bin/design-
    batch.py --from-concepts`. Catch that in CI instead.
    """
    missing = sorted(set(palette_tokens) - set(c2s.PALETTE_TAG_TO_HEX))
    assert not missing, (
        f"tokens declared in concept_seed.PALETTE_TOKENS but missing "
        f"from concept-to-spec.PALETTE_TAG_TO_HEX: {missing}"
    )


def test_every_type_genre_has_fonts(c2s):
    """Every concept type_genre SHOULD map to a font default."""
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    from concept_seed import TYPE_GENRES

    missing = sorted(set(TYPE_GENRES) - set(c2s.TYPE_GENRE_FONTS))
    assert not missing, f"type_genres missing from TYPE_GENRE_FONTS: {missing}"


def test_every_hero_composition_has_hints(c2s):
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    from concept_seed import HERO_COMPOSITIONS

    missing = sorted(set(HERO_COMPOSITIONS) - set(c2s.HERO_COMPOSITION_HINTS))
    assert not missing, f"hero_compositions missing from HERO_COMPOSITION_HINTS: {missing}"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_type_specimen_display_and_body(c2s):
    d, b = c2s._parse_type_specimen("Display: Recoleta. Body: Inter.")
    assert d == "Recoleta"
    assert b == "Inter"


def test_parse_type_specimen_keeps_first_option(c2s):
    """Specimens with `/` alternates keep the first, comma-lists keep the first."""
    d, _ = c2s._parse_type_specimen("Display: Eurostile / Bank Gothic. Body: Inter.")
    assert d == "Eurostile"
    d2, b2 = c2s._parse_type_specimen("Display: Futura Bold, Futura. Body: Inter, Helvetica.")
    assert d2 == "Futura Bold"
    assert b2 == "Inter"


def test_parse_type_specimen_missing_body(c2s):
    d, b = c2s._parse_type_specimen("Display: Whatever.")
    assert d == "Whatever"
    assert b == ""


def test_hex_to_rgb_roundtrip(c2s):
    r = c2s._hex_to_rgb("#D87E3A")
    assert r == (0xD8, 0x7E, 0x3A)
    assert c2s._rgb_to_hex(r) == "#D87E3A"


def test_tint_moves_toward_white(c2s):
    h = c2s._tint("#000000", 0.5)
    assert h == "#808080"
    assert c2s._tint("#FF0000", 1.0) == "#FFFFFF"
    assert c2s._tint("#123456", 0.0) == "#123456"


def test_shade_moves_toward_black(c2s):
    assert c2s._shade("#FFFFFF", 0.5) == "#808080"
    assert c2s._shade("#FFFFFF", 1.0) == "#000000"
    # Negative shade mirrors a tint so callers can use one knob.
    assert c2s._shade("#000000", -0.5) == "#808080"


def test_build_palette_picks_neutral_base(c2s):
    pal = c2s.build_palette(["cream", "terracotta", "ink"])
    assert pal["base"] == c2s.PALETTE_TAG_TO_HEX["cream"]
    assert pal["contrast"] == c2s.PALETTE_TAG_TO_HEX["ink"]
    assert pal["accent"] == c2s.PALETTE_TAG_TO_HEX["terracotta"]


def test_build_palette_falls_back_when_no_neutral(c2s):
    pal = c2s.build_palette(["scarlet", "black", "cream"])
    assert pal["base"] == c2s.PALETTE_TAG_TO_HEX["cream"]
    assert pal["contrast"] == c2s.PALETTE_TAG_TO_HEX["black"]
    assert pal["accent"] == c2s.PALETTE_TAG_TO_HEX["scarlet"]


def test_build_palette_non_neutral_only(c2s):
    """A concept of all-accent tags (no cream/ink) still produces a valid palette."""
    pal = c2s.build_palette(["lavender", "chrome", "lilac"])
    # No neutral -> default cream.
    assert pal["base"] == c2s.PALETTE_TAG_TO_HEX["cream"]
    # No ink -> default ink.
    assert pal["contrast"] == c2s.PALETTE_TAG_TO_HEX["ink"]
    # First accent.
    assert pal["accent"] == c2s.PALETTE_TAG_TO_HEX["lavender"]


def test_build_fonts_prefers_specimen(c2s):
    fonts = c2s.build_fonts("humanist-sans", "Display: Work Sans. Body: Lora.")
    assert fonts["display"]["family"] == "Work Sans"
    assert fonts["sans"]["family"] == "Lora"
    # Shape contract: every font slot has family/fallback/google_font/weights.
    for slot in ("display", "sans"):
        assert set(fonts[slot]) >= {"family", "fallback", "google_font", "weights"}


def test_build_fonts_falls_back_to_type_genre(c2s):
    """No display in specimen => TYPE_GENRE_FONTS default kicks in."""
    fonts = c2s.build_fonts("art-deco", "Body: Inter.")
    assert fonts["display"]["family"] == c2s.TYPE_GENRE_FONTS["art-deco"]["display"]["family"]
    assert fonts["sans"]["family"] == "Inter"


def test_build_layout_hints_returns_a_list(c2s):
    hints = c2s.build_layout_hints("specimen-grid")
    assert isinstance(hints, list)
    assert len(hints) >= 2
    assert all(isinstance(h, str) for h in hints)


def test_default_source_theme_branches(c2s):
    assert c2s._default_source_theme({"era": "y2k", "hero_composition": "full-bleed"}) == "aero"
    assert (
        c2s._default_source_theme(
            {"era": "pre-1950", "hero_composition": "type-led", "sector": "art-print"}
        )
        == "chonk"
    )
    assert (
        c2s._default_source_theme(
            {"era": "contemporary", "hero_composition": "photo-hero", "sector": "workwear"}
        )
        == "selvedge"
    )
    assert (
        c2s._default_source_theme(
            {"era": "contemporary", "hero_composition": "photo-hero", "sector": "food"}
        )
        == "lysholm"
    )
    assert (
        c2s._default_source_theme(
            {"era": "contemporary", "hero_composition": "illustration-led", "sector": "books"}
        )
        == "obel"
    )


# ---------------------------------------------------------------------------
# Full concept_to_spec on every concept in the live list. This is the
# real contract test -- if this breaks, the factory batch will break.
# ---------------------------------------------------------------------------


def test_every_concept_produces_valid_spec(c2s, concepts):
    """Every row in `concept_seed.CONCEPTS` must yield a spec that
    `_design_lib.validate_spec` accepts.
    """
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    from _design_lib import validate_spec

    failures: list[tuple[str, list[str]]] = []
    for concept in concepts:
        spec = c2s.concept_to_spec(concept)
        errors, _ = validate_spec(spec)
        if errors:
            failures.append((concept["slug"], [f"{e.path}: {e.message}" for e in errors]))
    assert not failures, f"concepts that failed validation: {failures[:5]}"


def test_concept_to_spec_rejects_missing_required_key(c2s):
    with pytest.raises(c2s.ConceptToSpecError, match="required key"):
        c2s.concept_to_spec({"slug": "x", "name": "X"})


def test_concept_to_spec_rejects_unknown_palette_tag(c2s):
    bad = {
        "slug": "bad",
        "name": "Bad",
        "blurb": "Test blurb.",
        "palette_tags": ["cream", "not-a-real-token"],
        "type_genre": "humanist-sans",
        "era": "contemporary",
        "sector": "general",
        "hero_composition": "type-led",
        "type_specimen": "Display: Inter. Body: Inter.",
    }
    with pytest.raises(c2s.ConceptToSpecError, match="not-a-real-token"):
        c2s.concept_to_spec(bad)


def test_concept_to_spec_llm_dry_run_equals_deterministic(c2s, concepts):
    """`concept_to_spec_llm(dry_run=True)` is a thin wrapper around the
    deterministic path. If this ever diverges, the test catches it."""
    agave = next(c for c in concepts if c["slug"] == "agave")
    mockup = REPO_ROOT / "docs" / "mockups" / "agave.png"
    got = c2s.concept_to_spec_llm(agave, mockup, dry_run=True)
    expected = c2s.concept_to_spec(agave)
    assert got == expected


def test_concept_to_spec_llm_parses_valid_json_response(c2s, concepts, monkeypatch):
    """The fixed LLM path calls `_vision_lib.vision_completion` (not
    `review_image`) and parses its raw text as a spec JSON. Regression
    guard for the bug where the findings-rubric prompt forced the
    model to emit `{"findings": []}` and fail spec validation.
    """
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    import _vision_lib as vl

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    agave = next(c for c in concepts if c["slug"] == "agave")
    # Use the deterministic spec as a plausible "model response" so we
    # know it validates; the test is about the wiring, not the prompt.
    canned = json.dumps(c2s.concept_to_spec(agave))

    captured: dict = {}

    def fake_vc(**kwargs):
        captured.update(kwargs)
        return vl.VisionResponse(
            findings=[],
            raw_text=canned,
            model=kwargs.get("model", "m"),
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            elapsed_s=0.1,
            dry_run=False,
        )

    monkeypatch.setattr(vl, "vision_completion", fake_vc)

    mockup = REPO_ROOT / "docs" / "mockups" / "agave.png"
    got = c2s.concept_to_spec_llm(agave, mockup, dry_run=False)
    assert got["slug"] == "agave"
    assert "palette" in got
    # The fix: the system prompt must be concept-to-spec, NOT the
    # visual-regression findings rubric. If someone reinstates the
    # old `review_image` call, the system prompt starts with "You are
    # a senior product designer" and this assertion fires.
    assert captured["system_prompt"].startswith("You are a design translator")
    assert "findings" not in captured["system_prompt"].lower()


def test_concept_to_spec_llm_retries_once_on_validation_failure(c2s, concepts, monkeypatch):
    """If the first response fails validation, the LLM is re-prompted
    once with the errors spelled out. If the second response validates,
    we return it; otherwise we raise `ConceptToSpecError` rather than
    burn budget on further retries.
    """
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    import _vision_lib as vl

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    agave = next(c for c in concepts if c["slug"] == "agave")
    good = c2s.concept_to_spec(agave)
    bad_first_response = json.dumps({"findings": []})
    good_second_response = json.dumps(good)

    call_count = {"n": 0}
    captured_prompts: list[str] = []

    def fake_vc(**kwargs):
        call_count["n"] += 1
        captured_prompts.append(kwargs["user_prompt"])
        text = bad_first_response if call_count["n"] == 1 else good_second_response
        return vl.VisionResponse(
            findings=[],
            raw_text=text,
            model="m",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            elapsed_s=0.1,
            dry_run=False,
        )

    monkeypatch.setattr(vl, "vision_completion", fake_vc)

    mockup = REPO_ROOT / "docs" / "mockups" / "agave.png"
    got = c2s.concept_to_spec_llm(agave, mockup, dry_run=False)
    assert got == good
    assert call_count["n"] == 2
    # The retry prompt must mention the validator's errors -- that's
    # the whole point of the self-correct pass. Concrete contract: the
    # word "failed spec validation" plus at least one `$.<path>:`
    # error line.
    retry_prompt = captured_prompts[1]
    assert "failed spec validation" in retry_prompt
    assert "$." in retry_prompt


def test_concept_to_spec_llm_raises_after_second_validation_failure(c2s, concepts, monkeypatch):
    """Two validation failures in a row => raise, don't loop forever."""
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    import _vision_lib as vl

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    agave = next(c for c in concepts if c["slug"] == "agave")
    bad = json.dumps({"findings": []})

    def fake_vc(**kwargs):
        return vl.VisionResponse(
            findings=[],
            raw_text=bad,
            model="m",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            elapsed_s=0.1,
            dry_run=False,
        )

    monkeypatch.setattr(vl, "vision_completion", fake_vc)

    mockup = REPO_ROOT / "docs" / "mockups" / "agave.png"
    with pytest.raises(c2s.ConceptToSpecError, match="self-correction"):
        c2s.concept_to_spec_llm(agave, mockup, dry_run=False)


def test_concept_to_spec_llm_tolerates_code_fence(c2s, concepts, monkeypatch):
    """Models occasionally wrap their JSON in ```json ... ``` despite
    being told not to. The parser strips a single wrapping fence."""
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    import _vision_lib as vl

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    agave = next(c for c in concepts if c["slug"] == "agave")
    good = c2s.concept_to_spec(agave)
    wrapped = "```json\n" + json.dumps(good) + "\n```"

    def fake_vc(**kwargs):
        return vl.VisionResponse(
            findings=[],
            raw_text=wrapped,
            model="m",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            elapsed_s=0.1,
            dry_run=False,
        )

    monkeypatch.setattr(vl, "vision_completion", fake_vc)

    mockup = REPO_ROOT / "docs" / "mockups" / "agave.png"
    got = c2s.concept_to_spec_llm(agave, mockup, dry_run=False)
    assert got == good


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )


def test_cli_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "concept-to-spec" in r.stdout.lower() or "concept" in r.stdout.lower()
    assert "--slug" in r.stdout


def test_cli_print_only_no_llm_emits_valid_spec():
    r = _run(["--slug", "agave", "--no-llm", "--print-only"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["slug"] == "agave"
    assert "palette" in data and "fonts" in data


def test_cli_unknown_slug_exits_nonzero():
    r = _run(["--slug", "this-slug-does-not-exist", "--no-llm", "--print-only"])
    assert r.returncode != 0
    assert "not found" in r.stderr


def test_cli_writes_to_out_path(tmp_path: Path):
    out = tmp_path / "agave.json"
    r = _run(["--slug", "agave", "--no-llm", "--out", str(out)])
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert spec["slug"] == "agave"
