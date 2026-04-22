"""Smoke tests for every `bin/*.py` script.

Checks the floor guarantee for all tooling scripts in one pass:

1. The script module imports without raising. Catches syntax errors,
   broken module-level code (e.g. a top-level `from foo import bar`
   that disappeared from `_lib`), and typos in constant tables.
2. `--help` exits 0. A non-zero `--help` means argparse is broken,
   which is how most CLI regressions show up.

Heavier integration tests for specific scripts live in dedicated
modules next to this one (test_clone.py, test_build_index.py,
test_append_wc_overrides.py, test_personalize_microcopy.py). This
module is the catch-all so renaming a flag or breaking an import in
any script we don't yet have a dedicated test for still surfaces in
CI.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


# Scripts whose CLI doesn't route `--help` through argparse, so running
# `--help` isn't a good smoke signal. We still verify these import.
_NO_ARGPARSE_HELP = frozenset(
    {
        "validate-theme-json.py",  # takes a positional theme path; `--help` → error
        "install-hooks.py",  # no argparse; runs actual install on invocation
        "snap_config.py",  # pure config module, no CLI
    }
)


def _script_names() -> list[str]:
    # Files starting with `_` are private library modules (e.g. `_lib.py`,
    # `_design_lib.py`), tested transitively via the scripts that import
    # them. They have no CLI of their own.
    return sorted(
        p.name for p in BIN_DIR.glob("*.py") if p.is_file() and not p.name.startswith("_")
    )


ALL_SCRIPTS = _script_names()


@pytest.mark.parametrize("script_name", ALL_SCRIPTS)
def test_script_imports(script_name: str) -> None:
    """Every bin/*.py imports without raising.

    `snap.py` pulls in Playwright at module scope, so we skip its
    import and rely on --help (which also imports, but lazily enough
    to give a clean argparse error if Playwright is missing).
    """
    if script_name in {"snap.py"}:
        pytest.skip("snap.py imports Playwright at module scope")
    module_name = script_name[:-3].replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, BIN_DIR / script_name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        # A handful of scripts call `sys.exit()` at module import
        # because they validate their environment (e.g. `php` being
        # on PATH). That's a valid behaviour — we only care that no
        # *unhandled* exception fires.
        pytest.skip(f"{script_name} called sys.exit() during import")


@pytest.mark.parametrize("script_name", sorted(set(ALL_SCRIPTS) - _NO_ARGPARSE_HELP))
def test_script_help_exits_zero(script_name: str) -> None:
    """`python3 bin/<script>.py --help` exits 0.

    This catches broken argparse wiring independently of what the
    script actually does. Scripts that require subcommands (e.g.
    `snap.py shoot <theme>`) still return 0 for the top-level
    `--help`.
    """
    cmd = [sys.executable, str(BIN_DIR / script_name), "--help"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
    )
    assert result.returncode == 0, (
        f"{script_name} --help exited {result.returncode}:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    # Argparse always prints a "usage:" line on --help. Verify we got
    # something shaped like one.
    output = (result.stdout + result.stderr).lower()
    assert "usage:" in output or "options:" in output or "positional" in output, (
        f"{script_name} --help output doesn't look like argparse help:\n{result.stdout[:500]}"
    )
