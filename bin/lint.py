#!/usr/bin/env python3
"""Local wrapper for the tooling lint + format + type gate.

Runs the same checks the CI `.github/workflows/check.yml` lint job does,
in the same order, so a green local run implies a green CI run for this
job:

    1. ruff check bin/ tests/            — pyflakes + bugbear + import-sort + pyupgrade
    2. ruff format --check tests/        — formatter drift in test files only
                                           (bin/ has years of hand-authored style
                                            and is NOT auto-formatted)
    3. mypy bin/ tests/                  — type check (permissive baseline; see pyproject.toml)
    4. node --check bin/blocks-validator/check-blocks.mjs
                                         — JS syntax check (no deps required)
    5. npx eslint bin/blocks-validator/  — optional; skipped if eslint isn't installed

Usage:
    python3 bin/lint.py           # run all steps, exit non-zero on any failure
    python3 bin/lint.py --fast    # skip mypy (~10× faster; useful in hooks)
    python3 bin/lint.py --fix     # let ruff auto-fix what it can, then re-check

This script has no third-party dependencies. The checks it runs do:
install them via `pip install -r requirements-dev.txt`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
TESTS = ROOT / "tests"
VALIDATOR = BIN / "blocks-validator" / "check-blocks.mjs"


def _run(argv: list[str], *, label: str, required: bool = True) -> bool:
    """Run a single check. Returns True on success."""
    print(f"\n>> {label}")
    print(f"   $ {' '.join(argv)}")
    try:
        result = subprocess.run(argv, cwd=str(ROOT))
    except FileNotFoundError:
        if required:
            print(f"   FAIL — {argv[0]!r} not on PATH", file=sys.stderr)
            return False
        print(f"   skip — {argv[0]!r} not on PATH (optional)")
        return True
    ok = result.returncode == 0
    if ok:
        print("   ok")
    elif required:
        print(f"   FAIL — exit {result.returncode}", file=sys.stderr)
    else:
        print(f"   skip — exit {result.returncode} (optional)")
        ok = True
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip mypy (the slowest step). Hooks run the full suite anyway.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Run `ruff check --fix` and `ruff format` before the gate.",
    )
    args = parser.parse_args()

    python = sys.executable

    if args.fix:
        subprocess.run([python, "-m", "ruff", "check", "--fix", str(BIN), str(TESTS)])
        subprocess.run([python, "-m", "ruff", "format", str(TESTS)])

    ok = True

    ok &= _run(
        [python, "-m", "ruff", "check", str(BIN), str(TESTS)],
        label="ruff check",
    )
    ok &= _run(
        [python, "-m", "ruff", "format", "--check", str(TESTS)],
        label="ruff format --check tests/",
    )
    if not args.fast:
        ok &= _run(
            [python, "-m", "mypy", str(BIN), str(TESTS)],
            label="mypy",
        )

    if shutil.which("node"):
        ok &= _run(
            ["node", "--check", str(VALIDATOR)],
            label="node --check blocks-validator",
        )
    else:
        print("\n>> node --check blocks-validator\n   skip — node not on PATH")

    # ESLint is optional: we don't commit a config file yet (the validator
    # is one 400-line .mjs and gets by on `node --check`). If a future
    # revision adds an .eslintrc and installs eslint, this will start
    # running automatically.
    eslint_config_present = any(
        (VALIDATOR.parent / name).exists()
        for name in (".eslintrc.json", ".eslintrc.cjs", "eslint.config.js")
    )
    if eslint_config_present and shutil.which("npx"):
        ok &= _run(
            ["npx", "--prefix", str(VALIDATOR.parent), "eslint", str(VALIDATOR)],
            label="eslint blocks-validator",
            required=False,
        )

    if ok:
        print("\nAll lint checks passed.")
        return 0
    print("\nOne or more lint checks failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
