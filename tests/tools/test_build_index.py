"""Integration + determinism tests for `bin/build-index.py`.

The contract:

1. `build-index.py <theme>` writes an `INDEX.md` at the theme root.
2. Re-running against the same theme produces byte-identical output
   (deterministic — no timestamps, no dict-ordering drift).
3. `build-index.py <theme> --check` exits 0 when `INDEX.md` is in sync
   and non-zero when it's stale.

Why this matters: a drifted `INDEX.md` silently breaks the `bin/check.py`
`check_index_in_sync` gate, and non-determinism would produce noisy
PR diffs every time someone runs the script on a different machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _run_build_index(theme_root: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke build-index.py with cwd=theme_root.

    build-index.py's `ROOT = Path.cwd()` means the theme path is the
    current working directory by default. Passing no positional means
    "this directory", which keeps the test hermetic.
    """
    cmd = [sys.executable, str(BIN_DIR / "build-index.py"), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(theme_root),
        env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
    )


def test_build_index_writes_index_md(minimal_theme: Path) -> None:
    """Running the script produces an INDEX.md at the theme root."""
    assert not (minimal_theme / "INDEX.md").exists()

    result = _run_build_index(minimal_theme)
    assert result.returncode == 0, (
        f"build-index.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    index = minimal_theme / "INDEX.md"
    assert index.is_file()
    text = index.read_text(encoding="utf-8")
    assert "# " in text, "INDEX.md is missing any Markdown heading"


def test_build_index_is_deterministic(minimal_theme: Path) -> None:
    """Running build-index.py twice produces identical output.

    Any non-determinism (timestamps, dict ordering) would cause
    check_index_in_sync to flap in CI.

    Note: the tree section self-references `INDEX.md`, so the first
    write and the second write differ by exactly one line (the
    newly-created INDEX.md appears in the tree on the second run).
    From run #2 onward output is stable. That's what we verify —
    runs #2 and #3 must be byte-identical.
    """
    assert _run_build_index(minimal_theme).returncode == 0
    assert _run_build_index(minimal_theme).returncode == 0
    second = (minimal_theme / "INDEX.md").read_bytes()

    assert _run_build_index(minimal_theme).returncode == 0
    third = (minimal_theme / "INDEX.md").read_bytes()

    assert second == third, (
        "build-index.py produced different output on back-to-back runs "
        "after warm-up; this will make check_index_in_sync flap in CI"
    )


def test_build_index_check_passes_when_in_sync(minimal_theme: Path) -> None:
    """`--check` exits 0 when INDEX.md is fully in sync.

    We run the generator twice first so the tree self-reference
    stabilises (see note in test_build_index_is_deterministic).
    """
    assert _run_build_index(minimal_theme).returncode == 0
    assert _run_build_index(minimal_theme).returncode == 0
    result = _run_build_index(minimal_theme, "--check")
    assert result.returncode == 0, f"--check should be 0 after two warm-up writes:\n{result.stderr}"


def test_build_index_check_fails_when_stale(minimal_theme: Path) -> None:
    """Tampering with INDEX.md after a write trips `--check`."""
    assert _run_build_index(minimal_theme).returncode == 0
    (minimal_theme / "INDEX.md").write_text("stale content\n", encoding="utf-8")
    result = _run_build_index(minimal_theme, "--check")
    assert result.returncode != 0
    assert "out of date" in (result.stdout + result.stderr).lower()


def test_build_index_check_fails_when_missing(minimal_theme: Path) -> None:
    """`--check` on a theme with no INDEX.md exits non-zero."""
    result = _run_build_index(minimal_theme, "--check")
    assert result.returncode != 0, "--check should fail when INDEX.md is missing"
