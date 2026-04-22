#!/usr/bin/env python3
"""Create / list / finish per-agent git worktrees under ~/.cursor/worktrees/.

AGENTS.md hard rule #20 requires long-running agent tasks to live in
their own worktree so a parallel agent's `git reset --hard` from the
shared monorepo root cannot wipe in-flight edits. This script is the
canonical front door for creating those worktrees and (optionally) for
the `cursor-app-control` MCP's `move_agent_to_root` flow that
auto-relocates the active Cursor agent into the new directory.

Subcommands
-----------
    new <slug> [--from <ref>]       Create ~/.cursor/worktrees/<slug>
                                     on a new branch agent/<slug>.
                                     Prints the path so the caller can
                                     pipe it into `move_agent_to_root`.
    list                             Show all worktrees with their
                                     branches, status, last commit.
    finish <slug> [--keep] [--push]  Push the branch (if --push), open
                                     a PR (gh), and (unless --keep)
                                     `git worktree remove` it.
    warn-if-racing                    Soft warning used by .githooks/
                                     pre-commit: prints to stderr if
                                     CWD is the shared root AND any
                                     agent/* worktrees are active.

Examples
--------
    # Create a worktree for the closed-loop work and move into it.
    python3 bin/agent-worktree.py new closed-loop-phases23

    # See what tasks are in flight across the laptop.
    python3 bin/agent-worktree.py list

    # When the task is done:
    python3 bin/agent-worktree.py finish closed-loop-phases23 --push

The script is intentionally NOT a wrapper around `move_agent_to_root`
itself -- that is an MCP tool and must be invoked by the LLM, not by
a Python subprocess. `new` prints a JSON line (`{"path": "...", ...}`)
that the LLM reads and then calls `move_agent_to_root` with
``rootPath`` set to the printed path.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKTREES_ROOT = Path.home() / ".cursor" / "worktrees"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def _git(*args: str, cwd: Path | None = None, check: bool = True,
         capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture,
        text=True,
    )


def _shared_root() -> Path:
    """Return the monorepo's main worktree (the one with .git/ as a dir,
    not a .git file pointing at a worktree's gitdir)."""
    common_dir = _git("rev-parse", "--git-common-dir").stdout.strip()
    common = Path(common_dir).resolve()
    if common.name == ".git":
        return common.parent
    return common


def _list_worktrees() -> list[dict]:
    """Return every worktree git knows about, parsed from porcelain output."""
    out = _git("worktree", "list", "--porcelain").stdout
    entries: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if not line:
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur["path"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):]
        elif line == "bare":
            cur["bare"] = True
        elif line == "detached":
            cur["detached"] = True
    if cur:
        entries.append(cur)
    return entries


def _agent_worktrees() -> list[dict]:
    """Subset of _list_worktrees() that this script is responsible for:
    paths under ~/.cursor/worktrees/, branches matching agent/*."""
    out: list[dict] = []
    for w in _list_worktrees():
        path = Path(w.get("path", ""))
        try:
            path.relative_to(WORKTREES_ROOT)
        except ValueError:
            continue
        out.append(w)
    return out


def cmd_new(args: argparse.Namespace) -> int:
    slug = args.slug
    if not SLUG_RE.match(slug):
        print(
            f"slug {slug!r} must match {SLUG_RE.pattern} "
            f"(lowercase letters, digits, hyphens; 2-64 chars).",
            file=sys.stderr,
        )
        return 2
    target = WORKTREES_ROOT / slug
    if target.exists():
        print(f"worktree {target} already exists.", file=sys.stderr)
        return 1
    branch = f"agent/{slug}"
    base = args.from_ or "HEAD"

    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Creating worktree at {target} on branch {branch} (from {base})...")
    res = _git("worktree", "add", "-b", branch, str(target), base, check=False)
    if res.returncode != 0:
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return res.returncode

    payload = {
        "ok": True,
        "path": str(target),
        "branch": branch,
        "shared_root": str(_shared_root()),
        "next_steps": [
            "1. The chat agent: call cursor-app-control move_agent_to_root "
            f"with rootPath={target}",
            "2. Inside the worktree, re-run `npm install` if Playground is "
            "needed (rule #20: node_modules/ is per-worktree)",
            "3. Edit, commit, push from the worktree.",
            "4. When done: python3 bin/agent-worktree.py finish "
            f"{slug} --push",
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    entries = _agent_worktrees()
    if not entries:
        print("(no agent worktrees under ~/.cursor/worktrees/)")
        return 0
    print(f"{'BRANCH':40s}  {'STATE':12s}  PATH")
    print("-" * 90)
    for w in entries:
        path = Path(w["path"])
        branch = (w.get("branch") or "(detached)").removeprefix("refs/heads/")
        state = "ok"
        try:
            status = _git("status", "--short", cwd=path).stdout
            if status.strip():
                state = f"dirty({len(status.splitlines())})"
        except subprocess.CalledProcessError:
            state = "err"
        print(f"{branch:40s}  {state:12s}  {path}")
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    slug = args.slug
    if not SLUG_RE.match(slug):
        print(f"slug {slug!r} is invalid.", file=sys.stderr)
        return 2
    target = WORKTREES_ROOT / slug
    if not target.exists():
        print(f"worktree {target} does not exist.", file=sys.stderr)
        return 1
    branch = f"agent/{slug}"

    if args.push:
        print(f"Pushing {branch} to origin...")
        res = _git("push", "-u", "origin", branch, cwd=target, check=False)
        if res.returncode != 0:
            print(res.stdout, file=sys.stderr)
            print(res.stderr, file=sys.stderr)
            return res.returncode
        if shutil.which("gh"):
            title = args.title or slug.replace("-", " ").capitalize()
            print(f"Opening PR via gh ({title!r})...")
            pr_res = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--title", title,
                    "--body", args.body or
                    f"Agent worktree branch {branch}.\n\n"
                    "(opened by `bin/agent-worktree.py finish`)",
                ],
                cwd=str(target),
                check=False,
            )
            if pr_res.returncode != 0:
                print("gh pr create failed; you can create the PR manually.",
                      file=sys.stderr)
        else:
            print(
                "gh CLI not on $PATH; skipping `gh pr create`. "
                f"Open the PR for {branch} manually.",
                file=sys.stderr,
            )

    if args.keep:
        print(f"--keep: leaving worktree at {target} on disk.")
        return 0

    print(f"Removing worktree at {target}...")
    rm_res = _git("worktree", "remove", str(target), check=False)
    if rm_res.returncode != 0:
        # Likely uncommitted edits or in-use directory; surface the
        # error and leave the tree in place so the user can recover.
        print(rm_res.stdout, file=sys.stderr)
        print(rm_res.stderr, file=sys.stderr)
        print(
            "Worktree NOT removed. Re-run with --keep to silence this, "
            "or `git worktree remove --force` if you've already saved "
            "everything you need.",
            file=sys.stderr,
        )
        return rm_res.returncode
    print("done.")
    return 0


def cmd_warn_if_racing(args: argparse.Namespace) -> int:
    """Soft warning used by .githooks/pre-commit (rule #20).

    Always exits 0 (warnings only); .githooks/pre-commit calls this
    after the static gate so a "may be racing" notice surfaces in the
    same place as the gate output without blocking the commit.
    """
    try:
        cwd_root = Path(_git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
    except subprocess.CalledProcessError:
        return 0
    shared = _shared_root().resolve()
    if cwd_root != shared:
        # Already in a worktree; nothing to warn about.
        return 0
    others = [
        w for w in _agent_worktrees()
        if (w.get("branch") or "").removeprefix("refs/heads/").startswith("agent/")
    ]
    if not others:
        return 0
    print(
        "\033[33mwarning:\033[0m you are committing from the shared monorepo "
        f"root ({shared}) while {len(others)} agent worktree(s) are active:",
        file=sys.stderr,
    )
    for w in others:
        branch = (w.get("branch") or "(detached)").removeprefix("refs/heads/")
        print(f"  - {branch}  ({w['path']})", file=sys.stderr)
    print(
        "  AGENTS.md rule #20: long-running tasks should run in their "
        "own worktree to avoid `git reset --hard` blast radius. "
        "Use `python3 bin/agent-worktree.py new <slug>` to relocate.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new", help="Create a new agent worktree.")
    sp.add_argument("slug")
    sp.add_argument("--from", dest="from_", default=None,
                    help="Branch / commit to fork from (default: HEAD).")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("list", help="List active agent worktrees.")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("finish", help="Push branch (optional) + remove worktree.")
    sp.add_argument("slug")
    sp.add_argument("--keep", action="store_true",
                    help="Don't remove the worktree from disk after pushing.")
    sp.add_argument("--push", action="store_true",
                    help="Run `git push -u origin agent/<slug>` and "
                         "`gh pr create` (if gh is on PATH).")
    sp.add_argument("--title", default=None,
                    help="PR title (default: slug, hyphens -> spaces, capitalised).")
    sp.add_argument("--body", default=None,
                    help="PR body markdown (default: a one-liner mentioning the branch).")
    sp.set_defaults(func=cmd_finish)

    sp = sub.add_parser("warn-if-racing",
                        help="(internal) soft warning for the pre-commit hook.")
    sp.set_defaults(func=cmd_warn_if_racing)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
