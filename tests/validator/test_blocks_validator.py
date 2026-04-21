"""Smoke tests for the Node editor-parity block validator.

`bin/blocks-validator/check-blocks.mjs` is the authoritative gate for
"is this markup something the WordPress editor would accept without
silently rewriting it." If the validator regresses (upgrades of
`@wordpress/blocks`, stub drift, jsdom changes), every theme's
invalid-markup errors start shipping again.

These tests shell out to the real `node` binary against a pair of
tiny fixture themes under `tests/validator/fixtures/`:

* `good/`              — valid save() output across templates / parts /
                         patterns. Validator exits 0.
* `bad/`               — a paragraph with `fontSize:"large"` but no
                         matching `has-large-font-size` class. The
                         editor's deprecation pipeline silently rewrites
                         it on load — the validator must surface this
                         as a "silent deprecation" failure.
* `bad_invalid_group/` — a `core/group` with `borderColor` set but no
                         `has-border-color` + `has-*-border-color`
                         classes on the outer element. Same failure
                         mode, different block.
* `bad_missing/`       — a theme root that simply doesn't exist.
                         Validator must exit 2 (setup error).

The tests are skipped when:
* `node` isn't on `$PATH` (CI runners without Node).
* `bin/blocks-validator/node_modules` isn't installed (fresh clone
  before `npm ci`).
* `php` isn't on `$PATH` (pattern rendering requires it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VALIDATOR = REPO_ROOT / "bin" / "blocks-validator" / "check-blocks.mjs"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _skip_if_env_missing() -> None:
    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH")
    if shutil.which("php") is None:
        pytest.skip("php binary not on PATH (needed to render pattern PHP)")
    if not (VALIDATOR.parent / "node_modules").is_dir():
        pytest.skip(
            "bin/blocks-validator/node_modules not installed — "
            "run `npm --prefix bin/blocks-validator ci`"
        )


def _run_validator(*roots: Path, timeout: float = 60) -> subprocess.CompletedProcess:
    cmd = ["node", str(VALIDATOR), *[str(r) for r in roots]]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def test_good_fixture_exits_zero() -> None:
    """A theme whose save() output is editor-clean exits 0."""
    _skip_if_env_missing()
    result = _run_validator(FIXTURES / "good")
    assert result.returncode == 0, (
        f"validator rejected the good fixture:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Validated" in (result.stdout + result.stderr), (
        "expected the validator's success banner in the output"
    )


def test_bad_paragraph_missing_class_exits_one() -> None:
    """A paragraph block missing its has-large-font-size class is a
    silent-deprecation — the validator must fail on it (exit 1)."""
    _skip_if_env_missing()
    result = _run_validator(FIXTURES / "bad")
    assert result.returncode == 1, (
        f"validator accepted the bad paragraph fixture (rc={result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "core/paragraph" in combined
    assert "silent deprecation" in combined.lower() or "block validation" in combined.lower()


def test_bad_group_missing_border_classes_exits_one() -> None:
    """A group block with borderColor set but no has-border-color classes
    round-trips through the editor's deprecation pipeline. Must fail."""
    _skip_if_env_missing()
    result = _run_validator(FIXTURES / "bad_invalid_group")
    assert result.returncode == 1
    assert "core/group" in (result.stdout + result.stderr)


def test_missing_theme_root_exits_two(tmp_path: Path) -> None:
    """Nonexistent theme root is a setup error (exit 2), not a
    validation failure — the caller can tell them apart by rc."""
    _skip_if_env_missing()
    missing = tmp_path / "does-not-exist"
    result = _run_validator(missing)
    assert result.returncode == 2, (
        f"expected exit 2 on missing root, got {result.returncode}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # The validator currently silences `console.error` at module scope,
    # so the "Theme root not found" message lands in /dev/null. We
    # only assert the exit code here; if a future revision restores
    # the error output, tighten this assertion.


def test_good_and_bad_fixtures_together_fail_loud() -> None:
    """Passing multiple theme roots aggregates failures."""
    _skip_if_env_missing()
    result = _run_validator(FIXTURES / "good", FIXTURES / "bad")
    assert result.returncode == 1, (
        "validator must fail when ANY root has validation issues, "
        f"even if others pass (rc={result.returncode})"
    )
    combined = result.stdout + result.stderr
    assert "bad/templates/index.html" in combined, (
        "expected a per-file reference to the bad fixture in the output"
    )
