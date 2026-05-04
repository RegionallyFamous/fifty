"""CLI-level tests for `bin/spec-from-prompt.py`.

These tests exercise the dry-run path (which does not call Anthropic),
arg validation, and the output-path resolution. The live API path is
covered by direct CLI runs (legacy `design.py --prompt` is gated; use
`FIFTY_ALLOW_NON_MILES_SPEC=1` if wiring an end-to-end smoke with a real key).
present; here we keep tests offline-only and free.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bin" / "spec-from-prompt.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )


def test_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "spec-from-prompt.py" in r.stdout
    assert "--prompt" in r.stdout
    assert "--dry-run" in r.stdout


def test_dry_run_writes_valid_spec(tmp_path: Path):
    out = tmp_path / "demo.json"
    r = _run(
        [
            "--prompt",
            "warm midcentury department store",
            "--dry-run",
            "--slug-hint",
            "midcentury",
            "--out",
            str(out),
        ]
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(out)
    assert out.is_file()
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert spec["slug"] == "midcentury"
    assert "name" in spec and spec["name"]
    assert "palette" in spec


def test_dry_run_default_path_uses_slug_hint(tmp_path: Path):
    out_dir = tmp_path / "specs"
    r = _run(
        [
            "--prompt",
            "anything",
            "--dry-run",
            "--slug-hint",
            "demo-spec",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert r.returncode == 0, r.stderr
    expected = out_dir / "demo-spec.json"
    assert expected.is_file()
    assert r.stdout.strip() == str(expected)


def test_rejects_empty_prompt():
    r = _run(["--prompt", "  "])
    assert r.returncode == 2
    assert "non-empty" in r.stderr


def test_rejects_invalid_slug_hint(tmp_path: Path):
    r = _run(
        [
            "--prompt",
            "x",
            "--dry-run",
            "--slug-hint",
            "Not A Slug",
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert r.returncode == 2
    assert "not a valid theme slug" in r.stderr


def test_out_and_out_dir_are_mutually_exclusive(tmp_path: Path):
    r = _run(
        [
            "--prompt",
            "x",
            "--dry-run",
            "--out",
            str(tmp_path / "a.json"),
            "--out-dir",
            str(tmp_path / "d"),
        ]
    )
    assert r.returncode != 0
    assert "mutually exclusive" in r.stderr


def test_dry_run_spec_passes_design_validate(tmp_path: Path):
    """Round-trip: dry-run output must be a spec that `design.py
    --dry-run` accepts. Catches drift between this script's example
    spec and `validate_spec`."""
    out = tmp_path / "demo.json"
    r = _run(
        [
            "--prompt",
            "x",
            "--dry-run",
            "--slug-hint",
            "demo",
            "--out",
            str(out),
        ]
    )
    assert r.returncode == 0, r.stderr
    design_py = REPO_ROOT / "bin" / "design.py"
    r2 = subprocess.run(
        [sys.executable, str(design_py), "--spec", str(out), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    assert "OK: spec is valid" in r2.stdout
