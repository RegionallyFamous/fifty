"""Tests for bin/design_unblock.py.

These tests cover the static surface of the self-healing pipeline —
classification, fingerprinting, evidence-packet generation, progress
judgement, edit safety, and attempt-cap / streak bookkeeping. They
deliberately do not call the LLM; the agentic loop is exercised via
dry-run / no-API-key fallbacks.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_design_unblock_for_test", BIN_DIR / "design_unblock.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_design_unblock_for_test"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_classify_known_titles_hit_specific_categories():
    u = _load_module()
    assert (
        u._classify("Product photographs are visually distinct within a theme", "A ~ B")
        == "product-photo-duplicate"
    )
    assert (
        u._classify("Hover/focus states have legible text-vs-background contrast", "")
        == "hover-contrast"
    )
    assert (
        u._classify("Pattern + heading microcopy distinct across themes", "patterns/x.php")
        == "microcopy-duplicate"
    )
    assert (
        u._classify("All rendered text distinct across themes", "patterns/y.php")
        == "microcopy-duplicate"
    )
    assert (
        u._classify("Recent snaps carry no serious axe-core errors", "8 NEW severity:error")
        == "snap-a11y-color-contrast"
    )


def test_classify_unknown_title_returns_unknown():
    u = _load_module()
    assert u._classify("Some brand-new check we've never seen", "detail") == "unknown"


def test_known_categories_includes_all_primary_categories():
    u = _load_module()
    for expected in (
        "product-photo-duplicate",
        "hover-contrast",
        "microcopy-duplicate",
        "snap-a11y-color-contrast",
    ):
        assert expected in u.KNOWN_CATEGORIES


# ---------------------------------------------------------------------------
# Fingerprints (stable across rephrasing but change with the detail)
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_across_cosmetic_whitespace_changes():
    u = _load_module()
    detail_a = (
        "1 pair(s) of product photographs are perceptually near-identical: "
        "product-wo-bottled-morning.jpg ~ product-wo-forbidden-honey.jpg (Hamming 3/64)."
    )
    detail_b = "  product-wo-bottled-morning.jpg ~ product-wo-forbidden-honey.jpg  "
    fp_a = u.blocker_fingerprint("product-photo-duplicate", "agave", detail_a)
    fp_b = u.blocker_fingerprint("product-photo-duplicate", "agave", detail_b)
    assert fp_a == fp_b


def test_fingerprint_differs_when_files_change():
    u = _load_module()
    fp_a = u.blocker_fingerprint(
        "product-photo-duplicate",
        "agave",
        "product-wo-A.jpg ~ product-wo-B.jpg",
    )
    fp_b = u.blocker_fingerprint(
        "product-photo-duplicate",
        "agave",
        "product-wo-C.jpg ~ product-wo-D.jpg",
    )
    assert fp_a != fp_b


def test_fingerprint_is_namespaced_by_slug():
    u = _load_module()
    fp_agave = u.blocker_fingerprint("hover-contrast", "agave", ".button:hover")
    fp_obel = u.blocker_fingerprint("hover-contrast", "obel", ".button:hover")
    assert fp_agave != fp_obel
    assert fp_agave.startswith("hover-contrast:agave:")
    assert fp_obel.startswith("hover-contrast:obel:")


# ---------------------------------------------------------------------------
# Evidence-packet generation
# ---------------------------------------------------------------------------


def _write_summary(run_dir: Path, failures: list[dict], slug: str = "agave") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "run_id": run_dir.name,
                "command": ["python3", "bin/design.py"],
                "cwd": str(REPO_ROOT),
                "verdict": "blocked",
                "returncode": 1,
                "current_phase": "check",
                "elapsed_s": 1.0,
                "phase_durations": {},
                "snap": {
                    "completed_cells": 1,
                    "total_cells": 1,
                    "error_cells": 0,
                    "warn_cells": 0,
                },
                "check_failures": failures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_build_repair_plan_classifies_agave_style_summary(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Product photographs are visually distinct within a theme",
                "detail": (
                    "product-wo-bottled-morning.jpg ~ product-wo-forbidden-honey.jpg"
                ),
                "summary": "duplicate product photos",
                "next_action": "Regenerate",
            },
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": ".cart .single_add_to_cart_button:hover: 2.64:1",
                "summary": "low hover contrast",
                "next_action": "fix hover",
            },
            {
                "title": "Pattern + heading microcopy distinct across themes",
                "detail": "patterns/brand-story.php: ships microcopy verbatim",
                "summary": "copied microcopy",
                "next_action": "rewrite",
            },
        ],
    )
    # Don't let git-status leak real worktree drift into the plan.
    u._changed_files = lambda cwd: []  # type: ignore[assignment]
    plan = u.build_repair_plan(run_dir)
    assert plan.slug == "agave"
    cats = [b.category for b in plan.blockers]
    assert cats == [
        "product-photo-duplicate",
        "hover-contrast",
        "microcopy-duplicate",
    ]
    assert plan.resume_phase == "check"
    # Verification ladder should include at least one check per blocker
    # and NO snap command (no visual blockers present).
    ladder_cmds = [cmd for b in plan.blockers for cmd in b.verification]
    assert ladder_cmds, "every blocker should ship at least one verify command"
    assert not any("snap.py" in " ".join(cmd) for cmd in ladder_cmds)


def test_build_repair_plan_visual_blockers_force_snap_resume(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Recent snaps carry no serious axe-core errors",
                "detail": "8 NEW severity:error finding(s) across snap artifacts",
                "summary": "serious axe errors",
                "next_action": "fix",
            },
        ],
    )
    u._changed_files = lambda cwd: []  # type: ignore[assignment]
    u._snap_findings_for_blocker = lambda slug, limit=12: []  # type: ignore[assignment]
    plan = u.build_repair_plan(run_dir)
    assert plan.resume_phase == "snap"


def test_build_repair_plan_emits_and_reads_back(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": "anything",
                "summary": "",
                "next_action": "",
            }
        ],
    )
    u._changed_files = lambda cwd: []  # type: ignore[assignment]
    plan = u.build_repair_plan(run_dir)
    out = u.write_repair_plan(run_dir, plan)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["slug"] == "agave"
    assert isinstance(data["blockers"], list)
    assert data["blockers"][0]["category"] == "hover-contrast"


# ---------------------------------------------------------------------------
# Progress judge
# ---------------------------------------------------------------------------


def test_judge_progress_fixed_when_no_remaining_blockers(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)
    decision, _ = u._judge_progress(["a", "b"], [], slug="agave", snap_errors_before=0)
    assert decision == "fixed"


def test_judge_progress_improved_when_count_drops(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)
    decision, _ = u._judge_progress(["a", "b"], ["b"], slug="agave", snap_errors_before=0)
    assert decision == "improved"


def test_judge_progress_worse_when_new_blocker_appears(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)
    decision, reason = u._judge_progress(
        ["a"], ["a", "c"], slug="agave", snap_errors_before=0
    )
    assert decision == "worse"
    assert "1 new blocker" in reason


def test_judge_progress_worse_when_snap_error_cells_grow(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 12)
    decision, reason = u._judge_progress(
        ["a"], ["a"], slug="agave", snap_errors_before=8
    )
    assert decision == "worse"
    assert "8 to 12" in reason


def test_judge_progress_not_improved_when_unchanged(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)
    decision, _ = u._judge_progress(["a"], ["a"], slug="agave", snap_errors_before=0)
    assert decision == "not-improved"


# ---------------------------------------------------------------------------
# Edit safety (the core of "LLM can edit until green, safely")
# ---------------------------------------------------------------------------


def test_edit_allowed_inside_theme_dir():
    u = _load_module()
    ok, _ = u._edit_is_allowed("agave/theme.json", "agave")
    assert ok


def test_edit_rejected_outside_theme_dir():
    u = _load_module()
    for path in (
        "bin/check.py",
        "tests/visual-baseline/heuristics-allowlist.json",
        "tests/check-baseline-failures.json",
        "../etc/passwd",
        "obel/theme.json",
    ):
        ok, reason = u._edit_is_allowed(path, "agave")
        assert not ok, f"expected rejection for {path}, got: {reason}"


def test_edit_rejects_important_content():
    u = _load_module()
    ok, reason = u._content_is_allowed("body { color: red !important; }")
    assert not ok
    assert "!important" in reason


def test_edit_rejects_allowlist_paths_even_as_content():
    u = _load_module()
    ok, _ = u._content_is_allowed("entry for tests/check-baseline-failures.json added")
    assert not ok


def test_apply_edit_rejects_ambiguous_old_string(tmp_path, monkeypatch):
    u = _load_module()
    target = tmp_path / "target.txt"
    target.write_text("alpha alpha alpha", encoding="utf-8")
    ok, reason = u._apply_edit(target, "alpha", "beta")
    assert not ok
    assert "matches" in reason


def test_apply_edit_writes_unique_replacement(tmp_path):
    u = _load_module()
    target = tmp_path / "target.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    ok, _ = u._apply_edit(target, "two", "deux")
    assert ok
    assert target.read_text(encoding="utf-8") == "one\ndeux\nthree\n"


# ---------------------------------------------------------------------------
# Attempt-cap / non-improving streak bookkeeping
# ---------------------------------------------------------------------------


def _seed_attempts(run_dir: Path, decisions: list[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "repair-attempts.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i, d in enumerate(decisions, 1):
            fh.write(
                json.dumps({"attempt": i, "decision": d, "reason": ""}) + "\n"
            )


def test_non_improving_streak_counts_trailing_fails(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _seed_attempts(run_dir, ["improved", "not-improved", "not-improved"])
    assert u._non_improving_streak(run_dir) == 2
    _seed_attempts(run_dir, ["improved", "not-improved", "improved"])
    assert u._non_improving_streak(run_dir) == 0


def test_apply_verification_refuses_on_streak(tmp_path, monkeypatch):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": "irrelevant",
                "summary": "",
                "next_action": "",
            }
        ],
    )
    _seed_attempts(run_dir, ["not-improved", "not-improved", "not-improved"])
    # Prevent real command execution.
    u._run_cmd = lambda cmd, timeout=None: {  # type: ignore[assignment]
        "argv": cmd,
        "returncode": 0,
        "stdout_tail": "",
        "stderr_tail": "",
        "elapsed_s": 0.0,
        "timed_out": False,
    }
    u._changed_files = lambda cwd: []  # type: ignore[assignment]
    u._collect_fingerprints = lambda slug, cats: []  # type: ignore[assignment]
    u._snap_error_count = lambda slug: 0  # type: ignore[assignment]
    record = u.apply_verification(run_dir, max_non_improving=3)
    assert record.decision == "stopped"
    assert "streak" in record.reason.lower()


def test_apply_verification_refuses_after_cap(tmp_path, monkeypatch):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": "irrelevant",
                "summary": "",
                "next_action": "",
            }
        ],
    )
    _seed_attempts(run_dir, ["not-improved"] * 6)
    u._changed_files = lambda cwd: []  # type: ignore[assignment]
    record = u.apply_verification(run_dir, max_attempts=6)
    assert record.decision == "stopped"
    assert "max-attempts" in record.reason.lower()


# ---------------------------------------------------------------------------
# No unsafe git / fs operations
# ---------------------------------------------------------------------------


def test_module_never_imports_git_mutation_helpers():
    source = (BIN_DIR / "design_unblock.py").read_text(encoding="utf-8")
    # These are the operations we explicitly forbid in-module.
    for forbidden in (
        "git push",
        "git commit",
        "--amend",
        "--force",
        "git reset --hard",
        "shutil.rmtree",
    ):
        assert forbidden not in source, f"forbidden operation found: {forbidden}"


def test_refuse_apply_when_worktree_has_unrelated_files(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": "",
                "summary": "",
                "next_action": "",
            }
        ],
    )
    u._changed_files = lambda cwd: ["bin/check.py"]  # type: ignore[assignment]
    rc = u.main(
        [
            "--run-id",
            "test",
            "--run-dir",
            str(run_dir),
            "--apply",
        ]
    )
    assert rc == 2, "refusing should return exit code 2"


def test_agentic_dry_run_returns_5(tmp_path, monkeypatch):
    u = _load_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": "",
                "summary": "",
                "next_action": "",
            }
        ],
    )
    u._changed_files = lambda cwd: []  # type: ignore[assignment]
    rc = u.agentic_repair(run_dir, dry_run=True)
    assert rc == 5
    attempts_path = run_dir / "repair-attempts.jsonl"
    assert attempts_path.is_file()


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, str(BIN_DIR / "design_unblock.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--apply" in result.stdout
    assert "--agentic" in result.stdout
