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
from pathlib import Path

import pytest

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
        "php-syntax",
        "product-photo-duplicate",
        "hover-contrast",
        "microcopy-duplicate",
        "wc-microcopy-duplicate",
        "cross-theme-product-images",
        "hero-placeholders-duplicate",
        "screenshot-duplicate",
        "snap-a11y-color-contrast",
        "design-score-low",
    ):
        assert expected in u.KNOWN_CATEGORIES


def test_generated_docs_do_not_make_repair_plan_dirty():
    u = _load_module()

    dirty = u._unrelated_framework_files(
        "agitprop",
        [
            "docs/agitprop/index.html",
            "docs/concepts/index.html",
            "tests/visual-baseline/agitprop/mobile/home.png",
            "bin/check.py",
        ],
    )

    assert dirty == ["bin/check.py"]


def test_classify_common_static_failures():
    u = _load_module()
    assert (
        u._classify(
            "PHP syntax (functions.php + patterns/*.php)",
            'functions.php: PHP Parse error: unexpected token "-"',
        )
        == "php-syntax"
    )
    assert (
        u._classify(
            "WC microcopy maps are distinct across themes",
            "WC microcopy maps share translations across themes",
        )
        == "wc-microcopy-duplicate"
    )
    assert (
        u._classify(
            "Product photographs are unique across themes (no copy-paste leak)",
            "30 product-wo-*.jpg file(s) byte-identical across [new, obel]",
        )
        == "cross-theme-product-images"
    )
    assert (
        u._classify(
            "Hero placeholders are unique across themes (no copy-paste leak in wonders-page-*.png / wonders-post-*.png)",
            "24 hero placeholder(s) byte-identical across [basalt, new]",
        )
        == "hero-placeholders-duplicate"
    )
    assert (
        u._classify(
            "Theme screenshots distinct (no duplicate-bytes)",
            "new, obel share identical screenshot.png",
        )
        == "screenshot-duplicate"
    )


def test_classify_design_scorecard_failure():
    u = _load_module()
    assert (
        u._classify(
            "Design scorecard meets minimum",
            "hierarchy scored 52/70; weak findings recorded",
        )
        == "design-score-low"
    )


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
                "detail": ("product-wo-bottled-morning.jpg ~ product-wo-forbidden-honey.jpg"),
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
    u._changed_files = lambda cwd: []
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
    u._changed_files = lambda cwd: []
    u._snap_findings_for_blocker = lambda slug, limit=12: []
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
    u._changed_files = lambda cwd: []
    plan = u.build_repair_plan(run_dir)
    out = u.write_repair_plan(run_dir, plan)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["slug"] == "agave"
    assert isinstance(data["blockers"], list)
    assert data["blockers"][0]["category"] == "hover-contrast"


def test_successful_json_repair_emits_factory_defect_candidate(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": ".button:hover: 1.2:1",
                "summary": "low hover contrast",
                "next_action": "fix hover",
            }
        ],
    )
    u._changed_files = lambda cwd: []
    plan = u.build_repair_plan(run_dir)
    record = u.AttemptRecord(
        at=123.0,
        attempt=1,
        decision="fixed",
        reason="all blockers cleared",
        before=[plan.blockers[0].fingerprint],
        after=[],
        touched_files=["agave/theme.json"],
        commands=[["python3", "bin/check.py", "agave", "--quick"]],
        verification={"layer": "json-llm"},
    )

    u.append_attempt(run_dir, record)

    defects = [
        json.loads(line)
        for line in (run_dir / "factory-defects.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(defects) == 1
    assert defects[0]["schema_version"] == 1
    assert defects[0]["category"] == "hover-contrast"
    assert defects[0]["promotion_target"] == "design-phase"
    assert defects[0]["tooling_status"] == "needs-tooling"
    assert defects[0]["resolved_fingerprints"] == [plan.blockers[0].fingerprint]


def test_successful_recipe_repair_is_recorded_as_covered(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Product photographs are visually distinct within a theme",
                "detail": "product-wo-a.jpg ~ product-wo-b.jpg",
                "summary": "duplicate product photos",
                "next_action": "regenerate",
            }
        ],
    )
    u._changed_files = lambda cwd: []
    plan = u.build_repair_plan(run_dir)
    record = u.AttemptRecord(
        at=123.0,
        attempt=1,
        decision="improved",
        reason="one blocker cleared",
        before=[plan.blockers[0].fingerprint],
        after=[],
        touched_files=["agave/playground/images/product-wo-a.jpg"],
        commands=[["python3", "bin/generate-product-photos.py", "--theme", "agave"]],
        verification={"layer": "recipe", "recipes": ["generate_product_photos"]},
    )

    u.append_attempt(run_dir, record)

    defect = json.loads((run_dir / "factory-defects.jsonl").read_text(encoding="utf-8"))
    assert defect["tooling_status"] == "covered-by-recipe"
    assert defect["recipes"] == ["generate_product_photos"]


def test_unsuccessful_repair_does_not_emit_factory_defect(tmp_path):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Hover/focus states have legible text-vs-background contrast",
                "detail": ".button:hover: 1.2:1",
                "summary": "low hover contrast",
                "next_action": "fix hover",
            }
        ],
    )
    u._changed_files = lambda cwd: []
    plan = u.build_repair_plan(run_dir)
    record = u.AttemptRecord(
        at=123.0,
        attempt=1,
        decision="not-improved",
        reason="unchanged",
        before=[plan.blockers[0].fingerprint],
        after=[plan.blockers[0].fingerprint],
        touched_files=[],
        commands=[],
        verification={"layer": "json-llm"},
    )

    u.append_attempt(run_dir, record)

    assert not (run_dir / "factory-defects.jsonl").exists()


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
    decision, reason = u._judge_progress(["a"], ["a", "c"], slug="agave", snap_errors_before=0)
    assert decision == "worse"
    assert "1 new blocker" in reason


def test_judge_progress_worse_when_snap_error_cells_grow(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 12)
    decision, reason = u._judge_progress(["a"], ["a"], slug="agave", snap_errors_before=8)
    assert decision == "worse"
    assert "8 to 12" in reason


def test_judge_progress_not_improved_when_unchanged(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)
    decision, _ = u._judge_progress(["a"], ["a"], slug="agave", snap_errors_before=0)
    assert decision == "not-improved"


def test_judge_progress_not_fixed_when_verification_failed_without_fingerprints(monkeypatch):
    u = _load_module()
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)
    decision, reason = u._judge_progress(
        ["a"],
        [],
        slug="agave",
        snap_errors_before=0,
        verification_failed=True,
    )
    assert decision == "not-improved"
    assert "Verification failed" in reason


def test_parse_check_failures_accepts_indented_fail_lines():
    u = _load_module()
    failures = u._parse_check_failures(
        "  [FAIL] [structural] No unpushed commits on current branch\n"
        "         1 unpushed commit on origin/main\n"
    )

    assert failures == [
        (
            "No unpushed commits on current branch",
            "1 unpushed commit on origin/main",
        )
    ]


def test_collect_fingerprints_reruns_full_check_for_unknown(monkeypatch):
    u = _load_module()

    class Proc:
        returncode = 1
        stdout = (
            "[FAIL] [agave] PHP syntax (functions.php + patterns/*.php)\n"
            "         functions.php: PHP Parse error: unexpected token\n"
        )

    monkeypatch.setattr(u.subprocess, "run", lambda *args, **kwargs: Proc())

    fps = u._collect_fingerprints("agave", ["unknown"])

    assert fps
    assert fps[0].startswith("php-syntax:agave:")


def test_affected_files_include_static_failure_sources():
    u = _load_module()
    assert "agave/functions.php" in u._affected_files_for_category(
        "php-syntax",
        "agave",
        'functions.php: PHP Parse error: unexpected token "-"',
        [],
    )
    assert "agave/templates/order-confirmation.html" in u._affected_files_for_category(
        "microcopy-duplicate",
        "agave",
        'templates/order-confirmation.html: ships rendered text "01 — confirmation"',
        [],
    )
    assert "agave/functions.php" in u._affected_files_for_category(
        "wc-microcopy-duplicate",
        "agave",
        "WC microcopy maps share translations across themes",
        [],
    )
    assert "agave/playground/images/" in u._affected_files_for_category(
        "cross-theme-product-images",
        "agave",
        "30 product-wo-*.jpg file(s) byte-identical across [agave, obel]",
        [],
    )
    assert "agave/screenshot.png" in u._affected_files_for_category(
        "screenshot-duplicate",
        "agave",
        "agave, obel share identical screenshot.png",
        [],
    )


def test_line_focused_source_snippets_for_php_failure(tmp_path, monkeypatch):
    u = _load_module()
    root = tmp_path
    theme = root / "agave"
    theme.mkdir()
    lines = [f"<?php // line {i}" for i in range(1, 90)]
    (theme / "functions.php").write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(u, "ROOT", root)

    snippets = u._source_snippets_for_blocker(
        "php-syntax",
        "agave",
        "functions.php: PHP Parse error on line 42",
        ["agave/functions.php"],
    )

    assert snippets
    assert "### agave/functions.php:42" in snippets[0]
    assert "42|<?php // line 42" in snippets[0]


def test_repair_plan_records_recipes_and_allowed_commands(tmp_path, monkeypatch):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Product photographs are unique across themes (no copy-paste leak)",
                "detail": "30 product-wo-*.jpg file(s) byte-identical across [agave, obel]",
                "summary": "copy leak",
                "next_action": "regenerate",
            },
            {
                "title": "Theme screenshots distinct (no duplicate-bytes)",
                "detail": "agave, obel share identical screenshot.png",
                "summary": "duplicate screenshot",
                "next_action": "rebuild",
            },
        ],
    )
    monkeypatch.setattr(u, "_changed_files", lambda cwd: [])
    plan = u.build_repair_plan(run_dir)

    assert "generate_product_photos" in plan.recommended_recipes
    assert "build_screenshot" in plan.recommended_recipes
    assert "generate_product_photos" in plan.allowed_commands
    assert "build_screenshot" in plan.allowed_commands
    assert str(run_dir / "repair-plan.json") in plan.artifact_paths


def test_full_verification_ladder_uses_positional_snap_report():
    u = _load_module()
    ladder = u._full_verification_ladder("agave", ["placeholder-images"])
    report_cmd = next(cmd for cmd in ladder if "snap.py" in cmd[1] and "report" in cmd)
    assert report_cmd[-2:] == ["report", "agave"]
    assert "--theme" not in report_cmd


def test_command_broker_allows_only_declared_actions():
    u = _load_module()
    argv = u.broker_action_to_argv("agave", "check_only", {"only": ["php_syntax"]})
    assert argv[-2:] == ["--only", "php_syntax"]
    with pytest.raises(ValueError):
        u.broker_action_to_argv("agave", "shell", {"cmd": "git reset --hard"})
    with pytest.raises(ValueError):
        u.broker_action_to_argv("agave", "php_lint", {"path": "../bin/check.py"})
    with pytest.raises(ValueError):
        u.broker_action_to_argv("agave", "check_only", {"only": ["--no-verify"]})


def test_apply_recipes_runs_brokered_actions_and_records_attempt(tmp_path, monkeypatch):
    u = _load_module()
    run_dir = tmp_path / "runs" / "test"
    _write_summary(
        run_dir,
        [
            {
                "title": "Theme screenshots distinct (no duplicate-bytes)",
                "detail": "agave, obel share identical screenshot.png",
                "summary": "duplicate screenshot",
                "next_action": "rebuild screenshot",
            },
        ],
    )
    monkeypatch.setattr(u, "_changed_files", lambda cwd: [])
    monkeypatch.setattr(u, "_collect_fingerprints", lambda slug, categories: [])
    monkeypatch.setattr(u, "_snap_error_count", lambda slug: 0)

    seen_actions: list[str] = []

    def fake_run_broker_action(slug, action, payload=None, *, timeout=30 * 60):
        seen_actions.append(action)
        return {
            "argv": ["python3", action],
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "elapsed_s": 0.0,
            "timed_out": False,
            "action": action,
            "payload": payload or {},
        }

    monkeypatch.setattr(u, "run_broker_action", fake_run_broker_action)
    monkeypatch.setattr(
        u,
        "_run_cmd",
        lambda cmd, timeout=None: {
            "argv": cmd,
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "elapsed_s": 0.0,
            "timed_out": False,
        },
    )

    record = u.apply_recipes(run_dir)

    assert record.decision == "fixed"
    assert "snap_routes" in seen_actions
    assert "build_screenshot" in seen_actions
    assert record.verification["layer"] == "recipe"


def test_tool_rescue_parser_accepts_actions_and_human_boundary():
    u = _load_module()
    parsed = u._parse_tool_rescue_response(
        json.dumps(
            {
                "rationale": "need screenshots",
                "done": False,
                "human_boundary": None,
                "actions": [{"action": "snap_routes", "payload": {"routes": ["home"]}}],
                "edits": [],
            }
        )
    )

    assert parsed["actions"][0]["action"] == "snap_routes"
    assert parsed["human_boundary"] is None


def test_run_rescue_actions_rejects_disallowed_broker_action(monkeypatch):
    u = _load_module()
    called = False

    def fake_run_broker_action(slug, action, payload=None, *, timeout=30 * 60):
        nonlocal called
        called = True
        return {"argv": ["python3", action], "returncode": 0}

    monkeypatch.setattr(u, "run_broker_action", fake_run_broker_action)
    results, rejected = u._run_rescue_actions(
        "agave",
        ["check_quick"],
        [{"action": "generate_product_photos", "payload": {}}],
    )

    assert results == []
    assert rejected
    assert not called


def test_non_improving_streak_can_be_layer_scoped(tmp_path: Path):
    u = _load_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    records = [
        {"decision": "not-improved", "verification": {"layer": "recipe"}},
        {"decision": "not-improved", "verification": {"layer": "json-llm"}},
        {"decision": "not-improved", "verification": {"layer": "json-llm"}},
    ]
    (run_dir / "repair-attempts.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    assert u._non_improving_streak(run_dir) == 3
    assert u._non_improving_streak(run_dir, layer="json-llm") == 2
    assert u._non_improving_streak(run_dir, layer="tool-rescue") == 0


def test_api_rate_limit_exception_maps_to_external_boundary():
    u = _load_module()
    exc = RuntimeError(
        "Anthropic call failed after 3 attempts: <HTTPError 429: 'Too Many Requests'>"
    )

    assert u._human_boundary_from_exception(exc) == "external-rate-limit"


def test_exception_boundary_metadata_preserves_retry_headers():
    u = _load_module()

    class Exc(Exception):
        status = 429
        retry_after_seconds = 12.0
        rate_limit_headers = {"retry-after": "12"}

    metadata = u._exception_boundary_metadata(Exc("rate limited"))

    assert metadata["retry_after_seconds"] == 12.0
    assert metadata["rate_limit_headers"]["retry-after"] == "12"


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
            fh.write(json.dumps({"attempt": i, "decision": d, "reason": ""}) + "\n")


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
    u._run_cmd = lambda cmd, timeout=None: {
        "argv": cmd,
        "returncode": 0,
        "stdout_tail": "",
        "stderr_tail": "",
        "elapsed_s": 0.0,
        "timed_out": False,
    }
    u._changed_files = lambda cwd: []
    u._collect_fingerprints = lambda slug, cats: []
    u._snap_error_count = lambda slug: 0
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
    u._changed_files = lambda cwd: []
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
    u._changed_files = lambda cwd: ["bin/check.py"]
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
    u._changed_files = lambda cwd: []
    rc = u.agentic_repair(run_dir, dry_run=True)
    assert rc == 5
    attempts_path = run_dir / "repair-attempts.jsonl"
    assert attempts_path.is_file()


# ---------------------------------------------------------------------------
# LLM response parsing — regression tests for real failure modes
# ---------------------------------------------------------------------------


def test_parse_llm_edits_accepts_bare_json():
    u = _load_module()
    raw = '{"rationale": "x", "done": false, "edits": []}'
    data = u._parse_llm_edits(raw)
    assert data["done"] is False
    assert data["edits"] == []


def test_parse_llm_edits_strips_json_code_fence():
    u = _load_module()
    raw = '```json\n{"rationale": "x", "done": true, "edits": []}\n```'
    data = u._parse_llm_edits(raw)
    assert data["done"] is True


def test_parse_llm_edits_strips_bare_code_fence():
    u = _load_module()
    raw = '```\n{"rationale": "x", "done": false, "edits": []}\n```'
    data = u._parse_llm_edits(raw)
    assert data["rationale"] == "x"


def test_parse_llm_edits_handles_prose_before_json():
    """Regression: the model wraps its JSON in an explanation paragraph.

    This is the actual failure the Agave rehearsal hit — the parser
    must still extract the JSON rather than bailing with
    ``Expecting value: line 1 column 1``.
    """
    u = _load_module()
    raw = (
        "Looking at the blockers:\n"
        "\n"
        "1. hover-contrast — needs color change.\n"
        "2. microcopy-duplicate — needs rewrite.\n"
        "\n"
        "Here is the JSON:\n"
        "\n"
        '{"rationale": "fix hover", "done": false, "edits": '
        '[{"path": "agave/theme.json", "old_string": "a", "new_string": "b"}]}'
    )
    data = u._parse_llm_edits(raw)
    assert data["edits"] == [{"path": "agave/theme.json", "old_string": "a", "new_string": "b"}]
    assert "fix hover" in data["rationale"]


def test_parse_llm_edits_handles_prose_wrapped_fenced_json():
    """Prose before AND a ```json fence around the payload — common."""
    u = _load_module()
    raw = (
        "I will fix two blockers.\n"
        "\n"
        "```json\n"
        '{"rationale": "two fixes", "done": false, "edits": []}\n'
        "```\n"
        "\n"
        "Let me know if that works."
    )
    data = u._parse_llm_edits(raw)
    assert data["rationale"] == "two fixes"


def test_parse_llm_edits_handles_nested_braces_in_strings():
    """Balanced-brace scan must skip `{` / `}` inside JSON strings."""
    u = _load_module()
    raw = 'Here you go:\n{"rationale": "rewrite `${var}` to `{{var}}`", "done": false, "edits": []}'
    data = u._parse_llm_edits(raw)
    assert "var" in data["rationale"]


def test_parse_llm_edits_rejects_truncated_json():
    """When the model hits max_tokens mid-JSON the parser must error

    cleanly rather than silently returning a half-formed object. The
    Agave rehearsal hit this before we raised max_output_tokens; the
    regression test locks in the clean-error behaviour.
    """
    u = _load_module()
    raw = (
        "Here is the plan:\n"
        '{"rationale": "partial", "done": false, "edits": [\n'
        '  {"path": "agave/theme.json", "old_string": "foo'
    )
    try:
        u._parse_llm_edits(raw)
    except ValueError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("expected ValueError for truncated JSON")


def test_extract_json_object_returns_longest_balanced_object():
    u = _load_module()
    raw = 'prefix {"a": 1} suffix {"b": 2}'
    extracted = u._extract_json_object(raw)
    assert extracted == '{"a": 1}'


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
