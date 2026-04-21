#!/usr/bin/env python3
"""One-time bootstrap that points this clone's git hooks at .githooks/.

Why this exists
---------------
Git ignores any directory of hooks unless `core.hooksPath` is set; the
default `.git/hooks/` is per-clone and not committed to the repo, so a
contributor's local hooks live nowhere and a fresh `git clone` ships
zero protection. We keep our hooks in `.githooks/` (committed,
versioned, code-reviewed) and ask every contributor + every coding
agent to run this script once after cloning.

What it does
------------
1. Sets `git config core.hooksPath .githooks` so `git commit` and
   `git push` will run the scripts in `.githooks/`.
2. Verifies every hook in `.githooks/` is executable (chmod +x);
   fixes the bit if it's missing (a common drift mode on macOS +
   case-insensitive filesystems).
3. Smokes the pre-commit hook by running its main payload
   (`bin/check.py --all --offline`) so you find out NOW if the gate
   already fails on this clone.

Idempotent. Safe to re-run any time you suspect drift.

Usage
-----
    python3 bin/install-hooks.py

That's it. After this point, every `git commit` runs the pre-commit
hook and every `git push` runs the pre-push hook.

To opt out (don't)
------------------
    git config --unset core.hooksPath
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / ".githooks"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess with stdout + stderr surfaced to the user."""
    return subprocess.run(cmd, cwd=REPO_ROOT, check=False, **kwargs)


def configure_hooks_path() -> None:
    """Point this clone's git at .githooks/ instead of .git/hooks/."""
    target = ".githooks"
    current = run(
        ["git", "config", "--get", "core.hooksPath"],
        capture_output=True, text=True,
    ).stdout.strip()
    if current == target:
        print(f"  ✓ git config core.hooksPath already = {target}")
        return
    if current:
        print(f"  ! git config core.hooksPath was {current!r}; overwriting")
    result = run(["git", "config", "core.hooksPath", target])
    if result.returncode != 0:
        print("  ✘ failed to set git config core.hooksPath", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"  ✓ set git config core.hooksPath = {target}")


def ensure_executable() -> None:
    """Make sure every hook in .githooks/ has the executable bit set."""
    if not HOOKS_DIR.is_dir():
        print(f"  ✘ {HOOKS_DIR.relative_to(REPO_ROOT)}/ does not exist", file=sys.stderr)
        sys.exit(1)
    fixed = 0
    found = 0
    for entry in sorted(HOOKS_DIR.iterdir()):
        if entry.is_file() and not entry.name.startswith("."):
            found += 1
            mode = entry.stat().st_mode
            wanted = mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            if mode != wanted:
                entry.chmod(wanted)
                fixed += 1
                print(f"  ✓ chmod +x .githooks/{entry.name}")
    if found == 0:
        print(f"  ! no hook scripts in {HOOKS_DIR.relative_to(REPO_ROOT)}/")
    elif fixed == 0:
        print(f"  ✓ {found} hook(s) already executable")


def smoke_check() -> None:
    """Run the gate the hooks are about to enforce, so the user finds
    out NOW if the working tree is already in a state that would block
    their next commit."""
    print("\n▸ Smoke test: running `bin/check.py --all --offline`")
    print("  (this is what the pre-commit hook will run on every commit)\n")
    result = run(["python3", "bin/check.py", "--all", "--offline"])
    if result.returncode == 0:
        print("\n✓ Smoke test passed. Your hooks are wired and the gate is green.")
        print("  Future `git commit` + `git push` will block on regressions.")
    else:
        print(
            "\n! Smoke test FAILED. The hooks are installed, but the working\n"
            "  tree is already in a state that would block your next commit.\n"
            "  Fix the failures above before doing more work.\n"
        )
        sys.exit(result.returncode)


def main() -> int:
    print("Installing fifty git hooks…")
    configure_hooks_path()
    ensure_executable()
    smoke_check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
