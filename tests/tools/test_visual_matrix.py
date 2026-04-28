"""Tests for bin/visual-matrix.py.

Focused on the Tier 2.3 pre-100-themes hardening additions: the
`new_themes` / `is_new_theme` outputs that the vision-review gate in
.github/workflows/check.yml reads to require a `vision-reviewed`
label on PRs that add a brand-new theme.

These tests stub `_new_themes` (and snap helpers already imported at
module-import time) so we never touch the real git tree -- keeps the
test deterministic under every working-copy state.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest


@pytest.fixture
def vm():
    """Import bin/visual-matrix.py under an alias.

    The dash in the filename prevents a regular `import`, so we go
    through spec_from_file_location the same way the smoke test does.
    """
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "visual_matrix_under_test",
        root / "bin" / "visual-matrix.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------- Scope defaults ----------------


def test_scope_default_new_themes_is_empty_list(vm):
    s = vm.Scope(mode="check-changed", themes=["aero"], do_full_shoot=False, base_ref="origin/main")
    assert s.new_themes == []


# ---------------- compute() threads new_themes through every branch ----------------


def test_compute_check_changed_surfaces_new_themes(vm, monkeypatch):
    monkeypatch.setattr(vm, "_new_themes", lambda base: ["fresh"])
    monkeypatch.setattr(vm, "_changed_themes", lambda base: ["fresh"])
    monkeypatch.setattr(vm, "discover_themes", lambda: ["aero", "fresh"])
    scope = vm.compute(event="pull_request", input_mode="", input_themes="", base_ref="origin/main")
    assert scope.mode == "check-changed"
    assert scope.base_ref == "origin/main"
    assert scope.new_themes == ["fresh"]


def test_compute_push_threads_event_before_base_to_shoot_jobs(vm, monkeypatch):
    """Push-to-main visual setup diffs against github.event.before.

    The setup job already used that base to choose a non-empty matrix,
    but the shoot job used to hardcode `origin/main` for route
    narrowing. Once the runner checks out the pushed HEAD, `origin/main`
    also points at HEAD, so every shoot job found an empty diff,
    uploaded no artifacts, and the aggregate job failed with "No snaps
    to report." Preserve the exact base ref on Scope so visual.yml can
    pass it through to `snap.py shoot --changed-base`.
    """
    monkeypatch.setattr(vm, "_new_themes", lambda base: [])
    monkeypatch.setattr(vm, "_changed_themes", lambda base: ["aero"])
    monkeypatch.setattr(vm, "discover_themes", lambda: ["aero"])
    scope = vm.compute(
        event="push",
        input_mode="",
        input_themes="",
        base_ref="deadbeef-before-sha",
    )
    assert scope.mode == "check-changed"
    assert scope.themes == ["aero"]
    assert scope.base_ref == "deadbeef-before-sha"


def test_compute_regenerate_gallery_still_sets_new_themes(vm, monkeypatch):
    monkeypatch.setattr(vm, "_new_themes", lambda base: ["fresh"])
    monkeypatch.setattr(vm, "discover_themes", lambda: ["aero", "fresh"])
    scope = vm.compute(
        event="workflow_dispatch",
        input_mode="regenerate-gallery",
        input_themes="",
        base_ref="origin/main",
    )
    assert scope.mode == "regenerate-gallery"
    assert scope.new_themes == ["fresh"]


def test_compute_no_new_themes_yields_empty_list(vm, monkeypatch):
    monkeypatch.setattr(vm, "_new_themes", lambda base: [])
    monkeypatch.setattr(vm, "_changed_themes", lambda base: ["aero"])
    monkeypatch.setattr(vm, "discover_themes", lambda: ["aero"])
    scope = vm.compute(event="pull_request", input_mode="", input_themes="", base_ref="origin/main")
    assert scope.new_themes == []


# ---------------- emit() surfaces new_themes + is_new_theme ----------------


def test_emit_prints_new_themes_and_is_new_theme_true(vm):
    scope = vm.Scope(
        mode="check-changed",
        themes=["fresh"],
        do_full_shoot=False,
        base_ref="origin/main",
        new_themes=["fresh"],
    )
    buf = io.StringIO()
    vm.emit(scope, buf, None)
    text = buf.getvalue()
    assert 'new_themes=["fresh"]' in text
    assert "is_new_theme=true" in text


def test_emit_prints_is_new_theme_false_when_empty(vm):
    scope = vm.Scope(
        mode="check-changed",
        themes=["aero"],
        do_full_shoot=False,
        base_ref="origin/main",
        new_themes=[],
    )
    buf = io.StringIO()
    vm.emit(scope, buf, None)
    text = buf.getvalue()
    assert "new_themes=[]" in text
    assert "is_new_theme=false" in text


def test_emit_writes_all_lines_to_github_output(vm, tmp_path):
    scope = vm.Scope(
        mode="check-changed",
        themes=["fresh"],
        do_full_shoot=False,
        base_ref="origin/main",
        new_themes=["fresh"],
    )
    out_path = tmp_path / "github_output.txt"
    vm.emit(scope, io.StringIO(), str(out_path))
    content = out_path.read_text(encoding="utf-8")
    # Every key the consuming workflow reads -- keep them wired here
    # so a rename doesn't silently break check.yml's vision gate.
    for expected in (
        "mode=",
        "themes=",
        "do_full_shoot=",
        "base_ref=",
        "has_themes=",
        "new_themes=",
        "is_new_theme=",
    ):
        assert expected in content


# ---------------- _new_themes git integration ----------------


def test_new_themes_returns_empty_without_base_ref(vm):
    """Empty base_ref = "nothing to compare against"; result is []."""
    assert vm._new_themes("") == []


def test_new_themes_flags_theme_missing_on_base_ref(vm, monkeypatch):
    """Themes whose theme.json doesn't exist at base_ref are 'new'."""

    class FakeCompleted:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = ""
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        # cmd shape: ["git", "cat-file", "-e", f"{base_ref}:{slug}/theme.json"]
        target = cmd[-1]
        if target.endswith(":fresh/theme.json"):
            return FakeCompleted(128)  # missing on base
        return FakeCompleted(0)  # present on base

    monkeypatch.setattr(vm, "discover_themes", lambda stages=None: ["aero", "fresh"])
    monkeypatch.setattr(vm.subprocess, "run", fake_run)
    assert vm._new_themes("origin/main") == ["fresh"]


def test_new_themes_returns_empty_when_git_unavailable(vm, monkeypatch):
    def raises(*a, **kw):
        raise FileNotFoundError("git not installed")

    monkeypatch.setattr(vm, "discover_themes", lambda stages=None: ["aero"])
    monkeypatch.setattr(vm.subprocess, "run", raises)
    assert vm._new_themes("origin/main") == []
