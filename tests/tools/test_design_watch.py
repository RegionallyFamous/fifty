from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def load_design_watch():
    spec = importlib.util.spec_from_file_location("_design_watch_for_test", BIN_DIR / "design-watch.py")
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
