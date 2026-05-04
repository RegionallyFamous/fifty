"""CLI-level tests for `bin/design.py`.

These tests run `bin/design.py` as a subprocess so they cover the argparse
wiring, exit codes, and the `--print-example-spec` / `--dry-run` paths
without needing to actually clone/seed/sync (those phases shell out to
other bin tools and are exercised end-to-end in CI when a real theme is
authored).

The unit-level tests for the pure transforms live in
`tests/tools/test_design_lib.py`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_PY = REPO_ROOT / "bin" / "design.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DESIGN_PY), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        timeout=30,
    )


def test_design_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0, r.stderr
    assert "design.py" in r.stdout
    assert "--spec" in r.stdout
    assert "--print-example-spec" in r.stdout


def test_design_print_example_spec_outputs_valid_json_that_validates(tmp_path):
    r = _run(["--print-example-spec"])
    assert r.returncode == 0, r.stderr
    parsed = json.loads(r.stdout)
    # Round-trip the example through dry-run validation to catch drift
    # between `example_spec()` and `validate_spec()`.
    spec_file = tmp_path / "example.json"
    spec_file.write_text(json.dumps(parsed), encoding="utf-8")
    r2 = _run(["--spec", str(spec_file), "--dry-run"])
    assert r2.returncode == 0, r2.stderr + r2.stdout
    assert "OK: spec is valid" in r2.stdout


def test_design_dry_run_reports_summary(tmp_path):
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        json.dumps(
            {
                "slug": "tinydemo",
                "name": "Tinydemo",
                "palette": {"base": "#FFFFFF", "accent": "#FF0000"},
                "fonts": {"display": {"family": "Inter", "google_font": False, "weights": [400]}},
            }
        ),
        encoding="utf-8",
    )
    r = _run(["--spec", str(spec_file), "--dry-run"])
    assert r.returncode == 0, r.stderr
    assert "tinydemo" in r.stdout
    assert "palette: 2 slug" in r.stdout
    assert "fonts: 1 slug" in r.stdout


def test_design_rejects_missing_spec_file(tmp_path):
    r = _run(["--spec", str(tmp_path / "does-not-exist.json"), "--dry-run"])
    assert r.returncode == 2
    assert "spec file not found" in r.stderr


def test_design_rejects_invalid_json(tmp_path):
    spec_file = tmp_path / "bad.json"
    spec_file.write_text("{not json", encoding="utf-8")
    r = _run(["--spec", str(spec_file), "--dry-run"])
    assert r.returncode == 2
    assert "not valid JSON" in r.stderr


def test_design_rejects_invalid_spec(tmp_path):
    spec_file = tmp_path / "invalid.json"
    spec_file.write_text(
        json.dumps({"slug": "Bad Slug With Spaces", "name": ""}),
        encoding="utf-8",
    )
    r = _run(["--spec", str(spec_file), "--dry-run"])
    assert r.returncode == 2
    assert "spec validation failed" in r.stderr
    # Both errors enumerated.
    assert "$.slug" in r.stderr
    assert "$.name" in r.stderr


def test_design_requires_spec_when_not_printing_example():
    r = _run([])
    assert r.returncode == 2
    assert "--spec" in r.stderr
    assert "miles-artifacts" in r.stderr or "--miles-artifacts" in r.stderr


def test_design_rejects_prompt_without_escape_hatch():
    r = _run(["--prompt", "a midcentury surf shop", "--dry-run"])
    assert r.returncode == 2
    assert "FIFTY_ALLOW_NON_MILES_SPEC" in r.stderr


def test_design_rejects_spec_and_prompt_together(tmp_path):
    spec_file = tmp_path / "spec.json"
    spec_file.write_text("{}", encoding="utf-8")
    r = _run(["--spec", str(spec_file), "--prompt", "midcentury surf shop"])
    assert r.returncode == 2
    assert "mutually exclusive" in r.stderr


@pytest.mark.parametrize(
    "phase",
    [
        "validate",
        "clone",
        "apply",
        "seed",
        "sync",
        "snap",
        "vision-review",
        "baseline",
        "check",
        "report",
    ],
)
def test_design_help_lists_every_phase(phase):
    r = _run(["--help"])
    assert r.returncode == 0
    assert phase in r.stdout
