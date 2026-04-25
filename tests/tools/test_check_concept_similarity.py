"""Contract tests for `bin/check-concept-similarity.py`.

These exercise the tag-overlap pass + the perceptual-hash pass against
a synthetic mockups/ tree so the gate stays predictable as the real
queue churns. The tests intentionally avoid loading the production
mockups/ data — that would couple regression behaviour to whatever
overlaps the queue has on a given day.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sim(monkeypatch, tmp_path: Path):
    """Load the hyphenated script as a module, swapping MOCKUPS_DIR and
    ALLOWLIST_PATH so each test runs against a clean tmp tree."""
    spec = importlib.util.spec_from_file_location(
        "check_concept_similarity", ROOT / "bin" / "check-concept-similarity.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "MOCKUPS_DIR", tmp_path)
    monkeypatch.setattr(module, "ALLOWLIST_PATH", tmp_path / "allowlist.json")
    return module


def _write_meta(dir_: Path, slug: str, tags: dict) -> None:
    """Minimal helper: only the fields run_check actually reads."""
    (dir_ / f"{slug}.meta.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "name": slug.title(),
                "blurb": f"{slug} fixture",
                "tags": tags,
            }
        )
    )


def test_skips_when_fewer_than_two_metas(sim, tmp_path) -> None:
    """A new repo / fresh checkout with one (or zero) concepts has
    nothing to compare. The check must SKIP, not FAIL — failing
    would block any greenfield work."""
    _write_meta(
        tmp_path,
        "only",
        {
            "palette": ["cream"],
            "type": "geometric-sans",
            "era": "contemporary",
            "sector": "general",
            "hero": "type-led",
        },
    )
    r = sim.run_check()
    assert r.skipped, r.details


def test_5_axis_overlap_fails_without_allowlist(sim, tmp_path) -> None:
    """Two metas with identical tags on every axis must fail the gate.
    This is the 'you re-shipped the same concept under two slugs'
    case — it shouldn't be possible to commit through the gate."""
    tags = {
        "palette": ["cream", "ink"],
        "type": "geometric-sans",
        "era": "contemporary",
        "sector": "general",
        "hero": "type-led",
    }
    _write_meta(tmp_path, "alpha", tags)
    _write_meta(tmp_path, "beta", tags)
    r = sim.run_check()
    assert not r.passed
    assert any("alpha" in d and "beta" in d and "duplicate" in d for d in r.details)


def test_allowlist_silences_5_axis_pair(sim, tmp_path) -> None:
    """Allowlisting a flagged pair must remove BOTH the fail and the
    detail line. The Proprietor escape hatch — without it the gate
    would block forever on a deliberately-kept overlap."""
    tags = {
        "palette": ["cream", "ink"],
        "type": "geometric-sans",
        "era": "contemporary",
        "sector": "general",
        "hero": "type-led",
    }
    _write_meta(tmp_path, "alpha", tags)
    _write_meta(tmp_path, "beta", tags)
    sim.ALLOWLIST_PATH.write_text(json.dumps({"pairs": [["alpha", "beta"]]}))
    r = sim.run_check()
    assert r.passed, r.details
    assert all("alpha" not in d for d in r.details)


def test_4_axis_overlap_warns_but_does_not_fail(sim, tmp_path) -> None:
    """Pairs at the collision threshold (4/5 axes) are surfaced as
    warnings only — the overlap is iterative debt, not a duplicate."""
    base = {
        "palette": ["cream", "ink"],
        "type": "geometric-sans",
        "era": "contemporary",
        "sector": "general",
        "hero": "type-led",
    }
    _write_meta(tmp_path, "alpha", base)
    diverged = dict(base, hero="photo-hero")  # one axis differs
    _write_meta(tmp_path, "beta", diverged)
    r = sim.run_check()
    assert r.passed
    assert any("alpha" in d and "beta" in d and "4/5" in d for d in r.details)


def test_low_overlap_emits_no_pair_messages(sim, tmp_path) -> None:
    """Two completely orthogonal concepts must NOT show up in the
    details list. Only pairs at >=3 axis overlap produce a message."""
    _write_meta(
        tmp_path,
        "alpha",
        {
            "palette": ["cream", "ink"],
            "type": "geometric-sans",
            "era": "contemporary",
            "sector": "general",
            "hero": "type-led",
        },
    )
    _write_meta(
        tmp_path,
        "gamma",
        {
            "palette": ["scarlet", "cobalt"],
            "type": "wood-type",
            "era": "pre-1900",
            "sector": "music",
            "hero": "illustration-led",
        },
    )
    r = sim.run_check()
    pair_msgs = [d for d in r.details if "alpha" in d and "gamma" in d]
    assert pair_msgs == []


def test_phash_pass_skipped_gracefully_without_pillow(sim, tmp_path, monkeypatch) -> None:
    """If Pillow is missing the perceptual-hash pass must degrade to a
    single warning detail, not crash the whole check. The tag-overlap
    pass should still run normally."""
    _write_meta(
        tmp_path,
        "alpha",
        {
            "palette": ["cream", "ink"],
            "type": "geometric-sans",
            "era": "contemporary",
            "sector": "general",
            "hero": "type-led",
        },
    )
    _write_meta(
        tmp_path,
        "beta",
        {
            "palette": ["cream", "ink"],
            "type": "geometric-sans",
            "era": "contemporary",
            "sector": "general",
            "hero": "type-led",
        },
    )
    # Force the pHash helper to behave as though Pillow isn't available.
    monkeypatch.setattr(sim, "_avg_phash", lambda _path: None)
    # Provide PNGs so _resolve_mockup_for_phash returns something.
    (tmp_path / "mockup-alpha.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "mockup-beta.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    r = sim.run_check()
    # Tag-overlap still finds the duplicate.
    assert not r.passed
    assert any("Pillow not installed" in d for d in r.details)


def test_palette_signature_uses_first_two_tokens(sim) -> None:
    """The palette match logic considers only the dominant pair so a
    concept's tertiary accent doesn't count for/against similarity.
    Mirrors the audit script's same-named function."""
    a = {
        "tags": {
            "palette": ["cream", "ink", "scarlet"],
            "type": "x",
            "era": "y",
            "sector": "z",
            "hero": "w",
        }
    }
    b = {
        "tags": {
            "palette": ["cream", "ink", "cobalt"],
            "type": "x",
            "era": "y",
            "sector": "z",
            "hero": "w",
        }
    }
    shared = sim._shared_axes(a, b)
    assert "palette" in shared
    c = {
        "tags": {
            "palette": ["scarlet", "cobalt"],
            "type": "x",
            "era": "y",
            "sector": "z",
            "hero": "w",
        }
    }
    shared_ac = sim._shared_axes(a, c)
    assert "palette" not in shared_ac


def test_hamming_handles_python_3_9_runtime(sim) -> None:
    """The shim around int.bit_count() (3.10+) keeps the pHash pass
    runnable on the project's declared 3.9 minimum."""
    assert sim._hamming(0, 0) == 0
    assert sim._hamming(0b1111, 0b0000) == 4
    assert sim._hamming(0xFF_00_FF_00, 0x00_FF_00_FF) == 32
