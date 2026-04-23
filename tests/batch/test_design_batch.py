"""CLI-level tests for `bin/design-batch.py`.

These tests exercise the planning surface (manifest parsing, slug
derivation, dry-run report) without ever creating worktrees, calling
design.py, or hitting the network. The live path is exercised by the
operator running the manifest end-to-end (and by CI when a real PR
demands it).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bin" / "design-batch.py"
EXAMPLE_MANIFEST = REPO_ROOT / "specs" / "batch-example.json"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        timeout=60,
    )


def test_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "design-batch.py" in r.stdout
    assert "--manifest" in r.stdout
    assert "--dry-run" in r.stdout
    assert "--concurrency" in r.stdout


def test_example_manifest_parses_and_dry_run_succeeds(tmp_path: Path):
    """The shipped example manifest must always plan cleanly. If a
    future change breaks the manifest schema, this catches it."""
    assert EXAMPLE_MANIFEST.is_file(), "specs/batch-example.json missing"
    out_dir = tmp_path / "wt"
    r = _run(
        [
            "--manifest",
            str(EXAMPLE_MANIFEST),
            "--dry-run",
            "--no-pr",
            "--run-id",
            "test-example",
            "--worktree-parent",
            str(out_dir),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    report = REPO_ROOT / "tmp" / "batch-test-example.json"
    assert report.is_file(), "dry-run should still write a report"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["run_id"] == "test-example"
    assert data["totals"]["passed"] == 3
    assert data["totals"]["failed"] == 0
    slugs = {t["slug"] for t in data["themes"]}
    assert slugs == {"midcentury", "japandi", "risozine"}
    report.unlink()


def test_dry_run_with_inline_manifest(tmp_path: Path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "themes": [
                    {"prompt": "warm coastal california surf shop"},
                    {"prompt": "brutalist concrete furniture catalog", "slug_hint": "brutalist"},
                ]
            }
        ),
        encoding="utf-8",
    )
    r = _run(
        [
            "--manifest",
            str(manifest),
            "--dry-run",
            "--no-pr",
            "--run-id",
            "test-inline",
            "--worktree-parent",
            str(tmp_path / "wt"),
        ]
    )
    assert r.returncode == 0, r.stderr + r.stdout
    report = REPO_ROOT / "tmp" / "batch-test-inline.json"
    assert report.is_file()
    data = json.loads(report.read_text(encoding="utf-8"))
    slugs = [t["slug"] for t in data["themes"]]
    # Slug derivation: first uses the prompt's first 3 tokens,
    # second uses the explicit slug_hint.
    assert "brutalist" in slugs
    assert any(s.startswith("warm-coastal") for s in slugs)
    report.unlink()


def test_manifest_must_set_exactly_one_of_prompt_or_spec(tmp_path: Path):
    manifest = tmp_path / "bad.json"
    manifest.write_text(
        json.dumps({"themes": [{"prompt": "x", "spec": "y.json"}]}),
        encoding="utf-8",
    )
    r = _run(
        [
            "--manifest",
            str(manifest),
            "--dry-run",
            "--run-id",
            "test-bad-1",
        ]
    )
    assert r.returncode != 0
    assert "exactly one" in r.stderr


def test_manifest_must_have_themes_key(tmp_path: Path):
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps({"hello": []}), encoding="utf-8")
    r = _run(
        [
            "--manifest",
            str(manifest),
            "--dry-run",
            "--run-id",
            "test-bad-2",
        ]
    )
    assert r.returncode != 0
    assert "themes" in r.stderr


def test_concurrency_clamped_to_hard_cap(tmp_path: Path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"themes": [{"prompt": "x"}]}),
        encoding="utf-8",
    )
    r = _run(
        [
            "--manifest",
            str(manifest),
            "--dry-run",
            "--concurrency",
            "99",
            "--run-id",
            "test-clamp",
            "--worktree-parent",
            str(tmp_path / "wt"),
        ]
    )
    assert r.returncode == 0, r.stderr
    assert "clamping" in r.stderr.lower()
    (REPO_ROOT / "tmp" / "batch-test-clamp.json").unlink(missing_ok=True)


def test_resume_skips_already_passed(tmp_path: Path):
    """Running a manifest twice with the same run-id should not
    re-attempt themes already marked passed."""
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "themes": [
                    {"prompt": "first theme", "slug_hint": "first"},
                    {"prompt": "second theme", "slug_hint": "second"},
                ]
            }
        ),
        encoding="utf-8",
    )
    args = [
        "--manifest",
        str(manifest),
        "--dry-run",
        "--no-pr",
        "--run-id",
        "test-resume",
        "--worktree-parent",
        str(tmp_path / "wt"),
    ]
    r1 = _run(args)
    assert r1.returncode == 0, r1.stderr
    report = REPO_ROOT / "tmp" / "batch-test-resume.json"
    data1 = json.loads(report.read_text(encoding="utf-8"))
    assert data1["totals"]["passed"] == 2
    r2 = _run(args)
    assert r2.returncode == 0, r2.stderr
    data2 = json.loads(report.read_text(encoding="utf-8"))
    # Both themes still 'passed' after the second run; resumability
    # didn't double-count or downgrade them.
    assert data2["totals"]["passed"] == 2
    assert {t["slug"] for t in data2["themes"]} == {"first", "second"}
    report.unlink()


def test_missing_manifest_errors_clearly():
    r = _run(
        [
            "--manifest",
            "/does/not/exist.json",
            "--dry-run",
            "--run-id",
            "test-missing",
        ]
    )
    assert r.returncode != 0
    assert "manifest not found" in r.stderr
