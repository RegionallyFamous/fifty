from __future__ import annotations

import importlib.util
import os
import signal
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


def test_parser_tracks_vision_review_progress():
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

    watch.parse_line(state, "== reviewing 52 PNGs for apiary (model=claude, dry_run=False)", now)
    watch.parse_line(state, ">> reviewing 7/52 mobile/my-account", now)
    watch.parse_line(state, "     mobile/my-account [reviewed] 6 findings  2235in/1248out", now)

    assert state.current_phase == "vision-review"
    assert state.slug == "apiary"
    assert state.vision_total == 52
    assert state.vision_completed == 7
    assert state.vision_current == "mobile/my-account"
    assert state.vision_last == "mobile/my-account [reviewed]"
    assert state.vision_findings == 6


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


def test_parser_tracks_batch_child_status_path_and_phase():
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="batch",
        started_at=now,
        command=["python3", "bin/design-batch.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=now,
        last_output_at=now,
    )

    watch.parse_line(
        state,
        "[batch] active child run=batch-canary-agave-dress status=/tmp/work/tree/tmp/runs/batch-canary-agave-dress/STATUS.md",
        now,
    )
    watch.parse_line(
        state,
        "Working: [03:12] Agave is checking screenshots. 4 of 52 pages captured.",
        now,
    )

    assert state.active_child_run_id == "batch-canary-agave-dress"
    assert state.active_child_status_path.endswith("STATUS.md")
    assert state.slug == "agave"
    assert state.current_phase == "snap"


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
        factory_defects=[
            {
                "category": "hover-contrast",
                "title": "Hover/focus states have legible text-vs-background contrast",
                "promotion_target": "design-phase",
                "tooling_status": "needs-tooling",
                "suggested_files": ["bin/autofix-contrast.py", "bin/design.py"],
            }
        ],
        active_child_run_id="batch-demo-dress",
        active_child_status_path="/tmp/worktree/tmp/runs/batch-demo-dress/STATUS.md",
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
    assert "## Factory Defects" in body
    assert "Need deterministic tooling: 1" in body
    assert "## What To Watch Now" in body
    assert "batch-demo-dress" in body
    assert "## Vision Review Progress" in body
    assert "## Last Output" in body
    watch.write_summary(tmp_path / "summary.json", state)
    summary = (tmp_path / "summary.json").read_text(encoding="utf-8")
    assert '"needs_tooling": 1' in summary


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
    defaults, _ = parser.parse_known_args(["--", "--spec", "tmp/specs/agave.json"])
    assert defaults.max_elapsed_seconds == 1200.0
    assert defaults.kill_stall_seconds == 300.0


def test_watch_parser_can_supervise_batch_script():
    watch = load_design_watch()
    parser = watch.build_parser()
    args, batch_args = parser.parse_known_args(
        [
            "--script",
            "bin/design-batch.py",
            "--no-auto-unblock",
            "--",
            "--from-concepts",
            "--limit",
            "1",
        ]
    )

    assert str(args.script) == "bin/design-batch.py"
    assert args.auto_unblock is False
    assert batch_args == ["--", "--from-concepts", "--limit", "1"]


def test_run_subprocess_kills_overlong_child(tmp_path):
    watch = load_design_watch()
    now = time.time()
    state = watch.WatchState(
        run_id="timeout-demo",
        started_at=now,
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=str(REPO_ROOT),
        slug="timeout-demo",
        phase_started_at=now,
        last_output_at=now,
        last_heartbeat_at=now,
    )

    rc = watch.run_subprocess(
        state,
        event_path=tmp_path / "events.jsonl",
        status_path=tmp_path / "STATUS.md",
        summary_path=tmp_path / "summary.json",
        heartbeat_seconds=60.0,
        stall_seconds=60.0,
        kill_stall_seconds=60.0,
        max_elapsed_seconds=0.2,
        verbose=False,
    )

    assert rc == 124
    assert state.check_failures
    assert state.check_failures[0].title == "Factory timeout guard"
    assert watch._runtime_guard_fired(state) is True


def test_design_watch_forwards_external_sigterm_to_child(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    child_script = tmp_path / "child_sleep.py"
    child_script.write_text(
        "import os\n"
        "import pathlib\n"
        "import time\n"
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            str(BIN_DIR / "design-watch.py"),
            "--run-id",
            "sigterm-demo",
            "--heartbeat-seconds",
            "60",
            "--stall-seconds",
            "60",
            "--kill-stall-seconds",
            "60",
            "--max-elapsed-seconds",
            "0",
            "--script",
            str(child_script),
            "--",
            "ignored-arg",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 5
        while not child_pid_path.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert child_pid_path.exists(), "child process did not start"
        child_pid = int(child_pid_path.read_text())

        proc.terminate()
        _stdout, stderr = proc.communicate(timeout=10)

        assert proc.returncode == 128 + signal.SIGTERM
        assert "Received SIGTERM; forwarding to child process group" in stderr
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError(f"child process {child_pid} survived design-watch SIGTERM")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


def test_repair_command_emits_heartbeat_while_silent(tmp_path, capsys):
    watch = load_design_watch()
    sleeper = tmp_path / "silent_repair.py"
    sleeper.write_text("import time\ntime.sleep(0.4)\nprint('done')\n")
    now = time.time()
    state = watch.WatchState(
        run_id="repair-demo",
        started_at=now,
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=now,
        last_output_at=now,
        last_heartbeat_at=now,
        repair_round=2,
    )

    rc = watch._run_repair_command(
        [sys.executable, str(sleeper)],
        cwd=tmp_path,
        state=state,
        layer="json-llm",
        heartbeat_seconds=0.1,
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Auto-unblock round 2 (json-llm) is still repairing" in out
    assert "done" in out


def test_runtime_guard_fired_false_for_normal_check_failure():
    watch = load_design_watch()
    state = watch.WatchState(
        run_id="normal",
        started_at=time.time(),
        command=["python3", "bin/design.py"],
        cwd=str(REPO_ROOT),
        phase_started_at=time.time(),
        last_output_at=time.time(),
        check_failures=[
            watch.CheckFailure(
                title="Recent snaps carry no serious axe-core errors",
                detail="1 NEW severity:error",
                summary="Recent screenshots found serious page issues.",
                next_action="Fix the snap finding.",
            )
        ],
    )
    assert watch._runtime_guard_fired(state) is False


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
