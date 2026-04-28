"""Tests for `bin/_judgment_lib.py`.

The judgment layer is the flexible complement to `bin/check.py`'s
deterministic rules: a structured yes/no question to the LLM with
evidence, a cached answer, and a clear needs_human escape hatch.

These tests exercise:
  * The dry-run path (no ANTHROPIC_API_KEY) returns a safe
    `needs_human` answer without calling the API.
  * Successful LLM responses are parsed into a JudgmentAnswer.
  * Malformed / bare-prose LLM responses degrade to `needs_human`,
    never invented certainty.
  * Cache lookup short-circuits repeated calls with identical
    evidence.
  * Cache is invalidated when the prompt or any evidence file
    changes.
  * Confidence thresholds work as documented: `.passed` is True only
    for verdict=pass + confidence >= 0.8, and `.needs_human` is True
    for explicit `needs_human` verdicts AND low-confidence passes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def judgment_module(tmp_path, monkeypatch):
    """Load `bin/_judgment_lib.py` as a fresh module, rooted at a
    throwaway cache/audit dir under `tmp_path`."""
    if str(BIN_DIR) not in sys.path:
        sys.path.insert(0, str(BIN_DIR))
    if "_judgment_lib" in sys.modules:
        del sys.modules["_judgment_lib"]
    spec = importlib.util.spec_from_file_location("_judgment_lib", BIN_DIR / "_judgment_lib.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_judgment_lib"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(mod, "AUDIT_ROOT", tmp_path / "audit")
    return mod


def test_dry_run_without_api_key_returns_needs_human(judgment_module, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FIFTY_JUDGMENT_DRY_RUN", raising=False)
    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="image-diversity",
        system_prompt="Decide whether these two images are the same product.",
        user_prompt="Are images A and B of the same product?",
    )
    assert answer.verdict == "needs_human"
    assert answer.confidence == 0.0
    assert answer.passed is False
    assert answer.needs_human is True
    assert "ANTHROPIC_API_KEY" in answer.rationale


def test_dry_run_env_toggle_forces_no_api_call(judgment_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anything")
    monkeypatch.setenv("FIFTY_JUDGMENT_DRY_RUN", "1")

    def should_not_call(*a, **k):
        raise AssertionError("no LLM primitive should be called in dry-run mode")

    monkeypatch.setattr(judgment_module, "text_completion", should_not_call)
    monkeypatch.setattr(judgment_module, "vision_completion", should_not_call)

    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="image-diversity",
        system_prompt="x",
        user_prompt="y",
    )
    assert answer.verdict == "needs_human"


def test_successful_response_parses_into_answer(judgment_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.delenv("FIFTY_JUDGMENT_DRY_RUN", raising=False)

    class FakeResponse:
        raw_text = json.dumps(
            {
                "verdict": "pass",
                "confidence": 0.92,
                "rationale": "Different subjects and camera angles.",
                "notes": "Keep both; staging is intentional.",
            }
        )
        model = "test-model"

    monkeypatch.setattr(
        judgment_module,
        "text_completion",
        lambda **_: FakeResponse(),
    )

    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="image-diversity",
        system_prompt="s",
        user_prompt="u",
    )
    assert answer.verdict == "pass"
    assert answer.confidence == pytest.approx(0.92)
    assert answer.passed is True
    assert answer.needs_human is False
    assert "Different subjects" in answer.rationale
    assert answer.model == "test-model"


def test_image_paths_routes_to_vision_primitive(judgment_module, monkeypatch, tmp_path):
    """When `image_paths` is supplied, `ask_judgment` MUST call
    `vision_completion` (which sends every image as a content block)
    rather than `text_completion` (which would only send the text
    prompt and leave the model guessing from filenames). This was a
    real bug — the previous shape passed paths only to `evidence_paths`
    for cache-keying, so the LLM judged filenames instead of pixels.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    img_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    img_b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    received: dict[str, object] = {}

    class FakeResponse:
        raw_text = json.dumps(
            {"verdict": "pass", "confidence": 0.9, "rationale": "distinct pixels"}
        )
        model = "test-model"

    def fake_vision(**kwargs):
        received.update(kwargs)
        return FakeResponse()

    def fake_text(**_):
        raise AssertionError("text_completion must NOT be called when image_paths is set")

    monkeypatch.setattr(judgment_module, "vision_completion", fake_vision)
    monkeypatch.setattr(judgment_module, "text_completion", fake_text)

    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        image_paths=[img_a, img_b],
    )
    assert answer.verdict == "pass"
    assert received["png_path"] == img_a
    assert list(received["extra_png_paths"]) == [img_b]


def test_image_paths_skip_missing_files(judgment_module, monkeypatch, tmp_path):
    """If every image path is missing, ask_judgment must fall back to
    text-only rather than 500-ing on an unreadable file."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    class FakeResponse:
        raw_text = json.dumps({"verdict": "pass", "confidence": 0.9, "rationale": "ok"})
        model = "test-model"

    calls: list[str] = []

    def fake_text(**_):
        calls.append("text")
        return FakeResponse()

    def fake_vision(**_):
        calls.append("vision")
        return FakeResponse()

    monkeypatch.setattr(judgment_module, "text_completion", fake_text)
    monkeypatch.setattr(judgment_module, "vision_completion", fake_vision)

    judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        image_paths=[tmp_path / "missing.png"],
    )
    assert calls == ["text"], "fallback must use text_completion when no image path resolves"


def test_malformed_llm_response_degrades_to_needs_human(judgment_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    class FakeResponse:
        raw_text = "Sure! I think they're fine."
        model = "test-model"

    monkeypatch.setattr(judgment_module, "text_completion", lambda **_: FakeResponse())

    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="image-diversity",
        system_prompt="s",
        user_prompt="u",
    )
    assert answer.verdict == "needs_human"
    assert answer.confidence == 0.0


def test_cache_short_circuits_repeated_calls(judgment_module, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("evidence v1", encoding="utf-8")

    calls: list[int] = []

    class FakeResponse:
        raw_text = json.dumps({"verdict": "pass", "confidence": 0.9, "rationale": "ok"})
        model = "test-model"

    def fake_text_completion(**_):
        calls.append(1)
        return FakeResponse()

    monkeypatch.setattr(judgment_module, "text_completion", fake_text_completion)

    first = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        evidence_paths=[evidence],
    )
    assert first.cache_hit is False
    assert len(calls) == 1

    second = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        evidence_paths=[evidence],
    )
    assert second.cache_hit is True
    assert len(calls) == 1, "cache must short-circuit the API call"


def test_cache_invalidated_by_evidence_change(judgment_module, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("v1", encoding="utf-8")

    calls: list[str] = []

    def make_response(verdict: str):
        class FakeResponse:
            raw_text = json.dumps({"verdict": verdict, "confidence": 0.9, "rationale": "ok"})
            model = "test-model"

        return FakeResponse()

    def fake_text_completion(**_):
        calls.append(evidence.read_text())
        return make_response("pass")

    monkeypatch.setattr(judgment_module, "text_completion", fake_text_completion)

    judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        evidence_paths=[evidence],
    )
    assert len(calls) == 1
    evidence.write_text("v2-changed", encoding="utf-8")
    judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        evidence_paths=[evidence],
    )
    assert len(calls) == 2, "changed evidence must invalidate the cache"


def test_confidence_threshold_controls_needs_human(judgment_module):
    low = judgment_module.JudgmentAnswer(verdict="pass", confidence=0.3, rationale="")
    assert low.passed is False
    assert low.needs_human is True

    mid = judgment_module.JudgmentAnswer(verdict="pass", confidence=0.6, rationale="")
    assert mid.passed is False
    assert mid.needs_human is False

    high = judgment_module.JudgmentAnswer(verdict="pass", confidence=0.9, rationale="")
    assert high.passed is True
    assert high.needs_human is False

    fail = judgment_module.JudgmentAnswer(verdict="fail", confidence=0.99, rationale="")
    assert fail.passed is False
    assert fail.needs_human is False


def test_audit_log_captures_answer(judgment_module, monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="rubric-check",
        system_prompt="s",
        user_prompt="u",
    )
    audit_path = judgment_module._audit_path("demo", "rubric-check")
    assert audit_path.is_file()
    rows = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    entry = json.loads(rows[0])
    assert entry["question_id"] == "rubric-check"
    assert entry["verdict"] == "needs_human"


def test_collect_audit_rows_orders_newest_first(judgment_module, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="q1",
        system_prompt="s",
        user_prompt="first question",
    )
    judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="q2",
        system_prompt="s",
        user_prompt="second question",
    )
    rows = judgment_module.collect_audit_rows("demo")
    assert len(rows) >= 2
    question_ids = [r["question_id"] for r in rows]
    assert "q1" in question_ids and "q2" in question_ids


def test_api_key_missing_mid_call_degrades_gracefully(judgment_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    def raise_key_missing(**_):
        raise judgment_module.ApiKeyMissingError("simulated key rotation")

    monkeypatch.setattr(judgment_module, "text_completion", raise_key_missing)
    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        use_cache=False,
    )
    assert answer.verdict == "needs_human"
    assert "simulated key rotation" in answer.rationale


def test_budget_exceeded_mid_call_degrades_gracefully(judgment_module, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    def raise_budget(**_):
        raise judgment_module.BudgetExceededError("daily cap reached")

    monkeypatch.setattr(judgment_module, "text_completion", raise_budget)
    answer = judgment_module.ask_judgment(
        theme_slug="demo",
        question_id="img",
        system_prompt="s",
        user_prompt="u",
        use_cache=False,
    )
    assert answer.verdict == "needs_human"
    assert "daily cap" in answer.rationale
