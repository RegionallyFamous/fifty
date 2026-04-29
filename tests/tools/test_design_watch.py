from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def load_design_watch():
    spec = importlib.util.spec_from_file_location(
        "_design_watch_for_test", BIN_DIR / "design-watch.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_design_watch_for_test"] = module
    spec.loader.exec_module(module)
    return module


def test_parser_tracks_design_phases_and_slug():
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="test",
        started_at=now,
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=now,
        last_output_at=now,
    )

    events = watch.parse_line(
        state,
        "design.py: running phases validate -> clone -> snap -> check for `agave`",
        now,
    )

    assert state.slug == "agave"
    assert state.phases == ["validate", "clone", "snap", "check"]
    assert state.current_phase == "validate"
    assert {"type": "run_plan", "phases": state.phases, "slug": "agave"} in events


def test_parser_tracks_snap_cells_and_flags():
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="test",
        started_at=now,
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=now,
        last_output_at=now,
    )

    watch.parse_line(state, "Shooting 1 theme(s) across 4 viewport(s) = 52 screenshot(s)", now)
    watch.parse_line(state, "  mobile  home               -> http://127.0.0.1:9400/", now)
    watch.parse_line(state, "    flags: 1 error / 0 warn (journal)", now)

    assert state.current_phase == "snap"
    assert state.total_cells == 52
    assert state.completed_cells == 1
    assert state.snap_error_cells == 1


def test_parser_ignores_check_theme_headers_as_phases():
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="test",
        started_at=now,
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        current_phase="check",
        phase_started_at=now,
        last_output_at=now,
    )

    events = watch.parse_line(state, "[apiary] Running static checks", now)

    assert events == []
    assert state.current_phase == "check"


def test_parser_translates_known_check_failures():
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="test",
        started_at=now,
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=now,
        last_output_at=now,
    )

    watch.parse_line(
        state,
        "  [FAIL] [content] Product photographs are visually distinct within a theme",
        now,
    )
    watch.parse_line(
        state,
        "         product-wo-a.jpg ~ product-wo-b.jpg (Hamming 3/64)",
        now,
    )

    assert len(state.check_failures) == 1
    failure = state.check_failures[0]
    assert "look too similar" in failure.summary
    assert "Regenerate" in failure.next_action
    assert "Hamming" in failure.detail


def test_grouped_failures_extracts_affected_theme_names():
    watch = load_design_watch()
    failures = [
        watch.CheckFailure(
            title="Snap evidence is fresh",
            detail="1 uncommitted source file(s) in aero but no snap evidence exists.",
            summary="The source files changed after the latest screenshot evidence.",
            next_action="Re-run the screenshot step.",
        ),
        watch.CheckFailure(
            title="Snap evidence is fresh",
            detail="1 uncommitted source file(s) in basalt but no snap evidence exists.",
            summary="The source files changed after the latest screenshot evidence.",
            next_action="Re-run the screenshot step.",
        ),
    ]

    grouped = watch.grouped_failures(failures)

    assert grouped == [("The source files changed after the latest screenshot evidence.", failures)]
    assert watch.affected_names(failures) == ["aero", "basalt"]


def test_write_status_creates_live_markdown_dashboard(tmp_path):
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="demo",
        started_at=now,
        command=["python3", "bin/design.py", "--spec", "tmp/specs/demo.json"],
        cwd=str(REPO_ROOT),
        slug="demo",
        phases=["validate", "check"],
        current_phase="check",
        phase_started_at=now,
        last_output_at=now,
        last_status_label="Needs attention",
        last_status_message="[00:02] Demo is running quality checks. 1 issue found so far.",
        check_failures=[
            watch.CheckFailure(
                title="Product photographs are visually distinct within a theme",
                detail="product-wo-a.jpg ~ product-wo-b.jpg",
                summary="Two product photos look too similar; shoppers may think they are the same item.",
                next_action="Regenerate or replace the named duplicate product photo.",
            )
        ],
    )
    status_path = tmp_path / "STATUS.md"

    watch.write_status(
        status_path,
        state,
        event_path=tmp_path / "events.jsonl",
        summary_path=tmp_path / "summary.json",
    )

    body = status_path.read_text(encoding="utf-8")
    assert "# Demo Pipeline Status" in body
    assert "**Status:** Needs attention" in body
    assert "Regenerate or replace the named duplicate product photo." in body
    assert "## Last Output" in body


def test_design_watch_help_smoke():
    proc = subprocess.run(
        [sys.executable, str(BIN_DIR / "design-watch.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "human-friendly progress" in proc.stdout.lower()


def test_watch_parser_exposes_auto_unblock_flags():
    watch = load_design_watch()
    parser = watch.build_parser()
    args, _ = parser.parse_known_args(
        [
            "--auto-unblock",
            "--max-repair-rounds",
            "2",
            "--unblock-dry-run",
            "--no-recipes",
            "--no-json-repair",
            "--no-tool-rescue",
            "--",
            "--spec",
            "tmp/specs/agave.json",
        ]
    )
    assert args.auto_unblock is True
    assert args.max_repair_rounds == 2
    assert args.unblock_dry_run is True
    assert args.no_recipes is True
    assert args.no_json_repair is True
    assert args.no_tool_rescue is True


def test_resume_design_args_replaces_from():
    watch = load_design_watch()
    resumed = watch._resume_design_args(
        ["--spec", "tmp/specs/agave.json", "--from", "validate", "--no-strict"],
        "check",
    )
    # --from validate should have been stripped; --from check should be present.
    assert "--from" in resumed
    idx = resumed.index("--from")
    assert resumed[idx + 1] == "check"
    # --spec and --no-strict should still be present.
    assert "--spec" in resumed
    assert "--no-strict" in resumed


def test_resume_design_args_strips_only_flag():
    watch = load_design_watch()
    resumed = watch._resume_design_args(
        ["--spec", "foo.json", "--only", "check"],
        "check",
    )
    assert "--only" not in resumed
    assert resumed[-2:] == ["--from", "check"]


def test_write_status_emits_auto_unblock_section(tmp_path):
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="test",
        started_at=now,
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=now,
        last_output_at=now,
        slug="agave",
    )
    state.repair_round = 1
    state.repair_last_decision = "not-improved"
    state.repair_last_layer = "tool-rescue"
    state.repair_last_reason = "Blocker set unchanged after repair attempt."
    state.repair_last_touched = ["agave/theme.json"]
    state.repair_attempts = [{"attempt": 1, "decision": "not-improved", "reason": "unchanged"}]
    state.repair_stop_reason = "Repair cap or non-improving streak reached."
    status_path = tmp_path / "STATUS.md"
    watch.write_status(status_path, state)
    body = status_path.read_text(encoding="utf-8")
    assert "## Auto-Unblock" in body
    assert "not-improved" in body
    assert "tool-rescue" in body
    assert "agave/theme.json" in body
    assert "Auto-unblock stopped:" in body
