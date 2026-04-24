"""Unit tests for the FIFTY_ALLOW_BASELINE_FAILURES mechanism.

Tests that `bin/check.py`'s `_demote_baseline_failures` helper behaves
correctly:

  - No env var set -> no-op, zero demotions even with a populated JSON.
  - Env var set but JSON missing or empty -> no-op, zero demotions.
  - Env var set, JSON lists a matching (theme, check-title) pair ->
    matching results flip `.demoted = True`, non-matching failures
    stay FAIL, passes/skips are untouched.
  - `run_checks_for` treats demoted failures as passing (exit 0) as
    long as there are NO additional un-demoted failures.

Why this lives in tests/
------------------------
The CI `tooling-tests` job runs `pytest tests/`. The demote logic is
on the critical path of every commit + push (see `.githooks/` and
`.github/workflows/check.yml`), so a regression here silently reverts
the repo to "every commit blocked by pre-existing debt". That's bad
enough that a fast pytest covering the happy + sad paths earns its
keep.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# conftest.py puts bin/ on sys.path.
import check  # noqa: E402  (import after sys.path tweak from conftest)


def _clear_env(monkeypatch):
    """Remove FIFTY_ALLOW_BASELINE_FAILURES for the duration of the test."""
    monkeypatch.delenv("FIFTY_ALLOW_BASELINE_FAILURES", raising=False)


def _make_fail(title: str) -> check.Result:
    r = check.Result(title)
    r.fail("synthetic failure for the test")
    return r


def _make_pass(title: str) -> check.Result:
    return check.Result(title)


def _make_skip(title: str) -> check.Result:
    r = check.Result(title)
    r.skip("synthetic skip for the test")
    return r


def test_demote_no_env_is_noop(tmp_path: Path, monkeypatch):
    """Without FIFTY_ALLOW_BASELINE_FAILURES=1 the helper returns 0 and
    leaves every Result untouched, even if the JSON would match."""
    _clear_env(monkeypatch)
    baseline = tmp_path / "check-baseline-failures.json"
    baseline.write_text(
        json.dumps({"failures": [{"theme": "obel", "check": "A"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "BASELINE_FAILURES_PATH", baseline)

    results = [_make_fail("A"), _make_pass("B")]
    demoted = check._demote_baseline_failures(results, "obel")
    assert demoted == 0
    assert results[0].demoted is False
    assert results[0].passed is False  # still failing; env var didn't flip it
    assert results[1].passed is True


def test_demote_env_set_missing_json_is_noop(tmp_path: Path, monkeypatch):
    """Env var on but JSON absent -> strict gate (zero demotions).
    Protects against the case where the baseline file is deleted
    accidentally and the hook would otherwise silently green-light
    any failure."""
    monkeypatch.setenv("FIFTY_ALLOW_BASELINE_FAILURES", "1")
    monkeypatch.setattr(check, "BASELINE_FAILURES_PATH", tmp_path / "does-not-exist.json")

    results = [_make_fail("A")]
    assert check._demote_baseline_failures(results, "obel") == 0
    assert results[0].demoted is False


def test_demote_env_set_matches(tmp_path: Path, monkeypatch):
    """Env var on, JSON matches -> the matching (theme, title) pair
    gets `.demoted = True`, everything else stays put."""
    monkeypatch.setenv("FIFTY_ALLOW_BASELINE_FAILURES", "1")
    baseline = tmp_path / "check-baseline-failures.json"
    baseline.write_text(
        json.dumps(
            {
                "failures": [
                    {"theme": "obel", "check": "known-debt"},
                    {"theme": "chonk", "check": "different-theme-same-name"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "BASELINE_FAILURES_PATH", baseline)

    results = [
        _make_fail("known-debt"),  # should be demoted
        _make_fail("brand-new-regression"),  # should stay FAIL
        _make_fail("different-theme-same-name"),  # wrong theme; stay FAIL
        _make_pass("happy-path"),  # untouched
        _make_skip("skipped-check"),  # untouched
    ]
    demoted = check._demote_baseline_failures(results, "obel")

    assert demoted == 1
    assert results[0].demoted is True
    assert results[0].passed is False  # demote doesn't flip passed/skipped
    assert results[1].demoted is False
    assert results[2].demoted is False  # theme mismatch -> still FAIL
    assert results[3].demoted is False
    assert results[4].demoted is False


def test_demote_preserves_render_label(tmp_path: Path, monkeypatch):
    """A demoted Result must render as WARN-BASELINE (not FAIL or PASS)
    so log scrapers + humans can tell pre-existing debt apart from new
    regressions. Strings are checked with `in` so the ANSI wrapper
    in `render()` is tolerated."""
    monkeypatch.setenv("FIFTY_ALLOW_BASELINE_FAILURES", "1")
    baseline = tmp_path / "check-baseline-failures.json"
    baseline.write_text(
        json.dumps({"failures": [{"theme": "obel", "check": "hover-contrast"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "BASELINE_FAILURES_PATH", baseline)

    r = _make_fail("hover-contrast")
    check._demote_baseline_failures([r], "obel")

    rendered = r.render()
    assert "WARN-BASELINE" in rendered
    assert "demoted to warning by tests/check-baseline-failures.json" in rendered


def test_save_baseline_failures_disables_env_var_during_scrape(monkeypatch):
    """`_save_baseline_failures` must strip FIFTY_ALLOW_BASELINE_FAILURES
    from os.environ for the duration of its scrape. Otherwise a
    pre-existing baseline could demote a failure, the scrape would
    miss it, and the regenerated file would silently erase that
    entry -- which in turn would un-demote the debt on every feature
    branch and block future commits. We verify by checking that the
    env var is cleaned up inside the function even when the scrape
    itself raises.

    Implementation check only; the full roundtrip (actually run the
    checks, read the JSON back, verify the gate stays green) is
    exercised by the hooks + CI in practice.
    """
    monkeypatch.setenv("FIFTY_ALLOW_BASELINE_FAILURES", "1")

    captured: list[str | None] = []
    original_build = check._build_results

    def fake_build(offline: bool):
        captured.append(os.environ.get("FIFTY_ALLOW_BASELINE_FAILURES"))
        raise RuntimeError("intentional: abort scrape early, we just want the env check")

    monkeypatch.setattr(check, "_build_results", fake_build)

    try:
        try:
            check._save_baseline_failures(offline=True)
        except RuntimeError:
            pass
    finally:
        monkeypatch.setattr(check, "_build_results", original_build)

    # During the scrape the env var must NOT have been "1" -- the
    # function is expected to pop it temporarily so the recorded
    # failure set reflects reality, not the already-demoted view.
    assert captured == [None], (
        f"_save_baseline_failures leaked the demote env var into its own "
        f"scrape pass. Captured values: {captured!r}"
    )

    # And it must have been restored afterwards (so unrelated callers
    # downstream keep the same environment they had).
    assert os.environ.get("FIFTY_ALLOW_BASELINE_FAILURES") == "1"
