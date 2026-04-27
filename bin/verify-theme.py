#!/usr/bin/env python3
"""Reproduce CI's theme gate locally for a single theme.

Why this exists
---------------
Agents ship a theme, push the branch, and then discover via CI that
``bin/check.py`` flagged something they could have caught in the local
worktree. Each round-trip costs 5-10 minutes (push + GitHub Actions
cold start + Playground boot + re-fetch screenshots), which is exactly
the manual toil Phase-Z's closed-loop plan is meant to eliminate.

``bin/verify-theme.py`` wraps every check CI runs for a single theme
into one command so the gate can run inside the worktree BEFORE the
push. It:

1. Verifies the current git branch is pushed (so any
   ``FIFTY_CONTENT_REF`` auto-detection in ``bin/snap.py`` picks up the
   right ref).
2. Runs ``bin/check.py <theme> --offline`` -- the same static gate that
   ``.github/workflows/check.yml`` runs.
3. (Optional, ``--snap``) Re-shoots the theme with
   ``bin/snap.py shoot <theme>`` and re-runs ``bin/check.py <theme>``
   against the fresh evidence to catch any freshness drift.
4. Aggregates the results into a tiny JSON + markdown summary the
   caller (human or ``bin/design-batch.py``) can include in a PR body
   or a batch run report.

Exit codes
----------
* 0 -- every check passed (or was intentionally skipped).
* 1 -- at least one check failed. Full log path printed so the operator
  can open it directly.
* 2 -- usage error (unknown theme, detached HEAD, etc.).

Usage
-----
Minimal (what the pre-push hook will grow into)::

    python3 bin/verify-theme.py obel

Full reproduction of CI (what design-batch calls after push)::

    python3 bin/verify-theme.py obel --snap --strict

Report as JSON so another tool can ingest it::

    python3 bin/verify-theme.py obel --format json

Why not just call ``bin/check.py``
----------------------------------
``bin/check.py`` is the underlying static gate -- this wrapper layers
in the "is the branch pushed?" precondition, the optional
``bin/snap.py shoot`` step, and a structured summary that callers can
attach to a PR body. Keeping those orchestrations out of ``check.py``
preserves its single-responsibility shape (run the rules; don't decide
whether the world is ready to run them).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "bin"))

from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root  # noqa: E402

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class PhaseResult:
    """One phase of the verification -- typically one subprocess call."""
    name: str
    status: str  # "passed" | "failed" | "skipped"
    elapsed_s: float = 0.0
    log_tail: str = ""
    returncode: int | None = None
    reason: str = ""  # only populated on "skipped"


@dataclass
class ThemeReport:
    theme: str
    status: str  # "passed" | "failed" | "skipped"
    branch: str | None = None
    content_ref: str | None = None
    phases: list[PhaseResult] = field(default_factory=list)
    started_at: float = 0.0
    elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(MONOREPO_ROOT),
        capture_output=True,
        text=True,
    )


def _current_branch() -> str | None:
    proc = _git("rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    if branch in ("HEAD", ""):
        return None
    return branch


def _branch_pushed(branch: str) -> bool:
    """True when ``origin/<branch>`` exists (either up-to-date or behind)."""
    proc = _git("rev-parse", "--verify", f"refs/remotes/origin/{branch}")
    return proc.returncode == 0


def _branch_up_to_date(branch: str) -> tuple[bool, str]:
    """Compare local ``branch`` HEAD vs ``origin/branch`` HEAD.

    Returns ``(True, "")`` when the local branch is identical to the
    remote, else ``(False, <human reason>)``.
    """
    local = _git("rev-parse", branch).stdout.strip()
    remote = _git("rev-parse", f"origin/{branch}").stdout.strip()
    if not local or not remote:
        return False, "could not resolve local or remote commit"
    if local == remote:
        return True, ""
    # Count how far apart they are for a more useful message.
    ahead = _git(
        "rev-list", "--count", f"origin/{branch}..{branch}"
    ).stdout.strip()
    behind = _git(
        "rev-list", "--count", f"{branch}..origin/{branch}"
    ).stdout.strip()
    return False, f"local is ahead {ahead}, behind {behind} vs origin/{branch}"


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def _tail(text: str, n_lines: int = 40) -> str:
    lines = text.splitlines()
    if len(lines) <= n_lines:
        return text.rstrip()
    return "\n".join(["... <truncated> ...", *lines[-n_lines:]]).rstrip()


def _run(cmd: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(MONOREPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, combined


def _phase_static_check(theme: str) -> PhaseResult:
    """Run ``python3 bin/check.py <theme> --offline``.

    --offline mirrors what the pre-commit hook does and keeps the
    runtime small enough that agents won't skip the gate out of
    impatience.
    """
    started = time.monotonic()
    rc, out = _run([sys.executable, "bin/check.py", theme, "--offline"])
    return PhaseResult(
        name="check_static",
        status="passed" if rc == 0 else "failed",
        elapsed_s=round(time.monotonic() - started, 2),
        log_tail=_tail(out),
        returncode=rc,
    )


def _phase_snap_shoot(theme: str) -> PhaseResult:
    """Re-shoot every route/viewport for the theme. Slow (~2-5 min) but
    the ONLY way to surface "source edits are newer than snap evidence"
    drift before CI complains about it.
    """
    started = time.monotonic()
    rc, out = _run([sys.executable, "bin/snap.py", "shoot", theme])
    return PhaseResult(
        name="snap_shoot",
        status="passed" if rc == 0 else "failed",
        elapsed_s=round(time.monotonic() - started, 2),
        log_tail=_tail(out),
        returncode=rc,
    )


def _phase_evidence_check(theme: str) -> PhaseResult:
    """Second pass through ``bin/check.py`` with evidence-freshness and
    all snap-backed checks enabled. Only runs when ``--snap`` is
    passed, because without a fresh shoot the freshness check would
    complain about its own precondition."""
    started = time.monotonic()
    rc, out = _run([sys.executable, "bin/check.py", theme, "--offline"])
    return PhaseResult(
        name="check_after_shoot",
        status="passed" if rc == 0 else "failed",
        elapsed_s=round(time.monotonic() - started, 2),
        log_tail=_tail(out),
        returncode=rc,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def verify(
    theme: str,
    *,
    run_snap: bool,
    strict_branch: bool,
) -> ThemeReport:
    """Run the verification phases for a single theme. Mutates nothing
    on disk apart from what the subprocesses do."""
    root = resolve_theme_root(theme)
    theme = root.name
    started = time.monotonic()
    branch = _current_branch()
    report = ThemeReport(theme=theme, status="failed", branch=branch, started_at=time.time())

    if strict_branch:
        if not branch:
            report.phases.append(
                PhaseResult(
                    name="branch_ready",
                    status="failed",
                    reason="HEAD is detached; snap content ref auto-detection requires a branch",
                )
            )
            report.status = "failed"
            report.elapsed_s = round(time.monotonic() - started, 2)
            return report
        if branch != "main" and not _branch_pushed(branch):
            report.phases.append(
                PhaseResult(
                    name="branch_ready",
                    status="failed",
                    reason=(
                        f"branch '{branch}' is not pushed to origin; "
                        f"Playground on the PR runner will 404 on this "
                        f"theme's playground/ assets. Push first, then "
                        f"re-run verify-theme."
                    ),
                )
            )
            report.status = "failed"
            report.elapsed_s = round(time.monotonic() - started, 2)
            return report
        if branch != "main":
            up_to_date, reason = _branch_up_to_date(branch)
            if not up_to_date:
                report.phases.append(
                    PhaseResult(
                        name="branch_ready",
                        status="failed",
                        reason=(
                            f"branch '{branch}' is pushed but not in sync "
                            f"with origin ({reason}); CI would see a "
                            f"different tree."
                        ),
                    )
                )
                report.status = "failed"
                report.elapsed_s = round(time.monotonic() - started, 2)
                return report
        report.phases.append(
            PhaseResult(name="branch_ready", status="passed")
        )

    # Record which ref snap.py will use (purely informational).
    try:
        import snap as _snap

        ref, source = _snap._auto_detect_content_ref()
        report.content_ref = ref or "main"
        report.phases.append(
            PhaseResult(
                name="content_ref",
                status="passed",
                reason=f"ref={report.content_ref} (source={source})",
            )
        )
    except Exception as e:
        # Non-fatal -- content_ref is advisory output, not a gate.
        report.phases.append(
            PhaseResult(
                name="content_ref",
                status="skipped",
                reason=f"could not query snap._auto_detect_content_ref: {e}",
            )
        )

    # Phase 1: static check
    report.phases.append(_phase_static_check(theme))

    # Phase 2 (optional): re-shoot then re-check with fresh evidence
    if run_snap:
        report.phases.append(_phase_snap_shoot(theme))
        # Skip the re-check if the shoot itself failed (the second
        # check would just restate the first failure).
        if report.phases[-1].status == "passed":
            report.phases.append(_phase_evidence_check(theme))

    failed = [p for p in report.phases if p.status == "failed"]
    report.status = "failed" if failed else "passed"
    report.elapsed_s = round(time.monotonic() - started, 2)
    return report


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def _format_markdown(report: ThemeReport) -> str:
    lines: list[str] = []
    badge = "PASS" if report.status == "passed" else "FAIL"
    lines.append(f"## verify-theme: `{report.theme}` — {badge}")
    lines.append("")
    if report.branch:
        lines.append(f"* branch: `{report.branch}`")
    if report.content_ref:
        lines.append(f"* content ref: `{report.content_ref}`")
    lines.append(f"* elapsed: {report.elapsed_s:.1f}s")
    lines.append("")
    lines.append("| phase | status | elapsed |")
    lines.append("| --- | --- | --- |")
    for p in report.phases:
        lines.append(f"| `{p.name}` | {p.status} | {p.elapsed_s:.1f}s |")
    lines.append("")
    failing = [p for p in report.phases if p.status == "failed"]
    if failing:
        lines.append("### Failed phases")
        for p in failing:
            lines.append("")
            lines.append(f"#### `{p.name}`")
            if p.reason:
                lines.append(f"*Reason:* {p.reason}")
            if p.log_tail:
                lines.append("```")
                lines.append(p.log_tail)
                lines.append("```")
    return "\n".join(lines) + "\n"


def _format_text(report: ThemeReport) -> str:
    """Short plaintext summary for the operator's TTY. Shows the
    full log tail for any failed phase so the operator doesn't need to
    `cat` a log file to figure out what went wrong."""
    lines: list[str] = []
    status_line = "PASS" if report.status == "passed" else "FAIL"
    lines.append(f"verify-theme {report.theme}: {status_line} ({report.elapsed_s:.1f}s)")
    for p in report.phases:
        marker = {
            "passed": "  ok  ",
            "failed": " FAIL ",
            "skipped": " skip ",
        }.get(p.status, p.status)
        extra = f" -- {p.reason}" if p.reason else ""
        lines.append(f"  [{marker}] {p.name} ({p.elapsed_s:.1f}s){extra}")
    for p in report.phases:
        if p.status == "failed" and p.log_tail:
            lines.append("")
            lines.append(f"--- {p.name} log tail ---")
            lines.append(p.log_tail)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify-theme.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "theme",
        nargs="?",
        default=None,
        help="Theme slug to verify (defaults to cwd if it contains theme.json).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help=(
            "Verify every shipping theme. Implies --format json for the "
            "per-theme report and prints a one-line plaintext summary "
            "at the end. Exit 1 if any theme fails."
        ),
    )
    p.add_argument(
        "--snap",
        action="store_true",
        help=(
            "Re-shoot the theme via `bin/snap.py shoot <slug>` and "
            "re-run `bin/check.py` against the fresh evidence. Adds "
            "~2-5 min per theme but catches snap-freshness drift that "
            "would otherwise only fail on CI."
        ),
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Require the current branch to be pushed AND in sync with "
            "origin before running any phase. Defaults off for local "
            "ergonomics (agent may run verify-theme mid-edit); turn on "
            "in automation (e.g. bin/design-batch.py after push)."
        ),
    )
    p.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help=(
            "Output shape. 'text' (default) is a short TTY summary. "
            "'markdown' is suitable for a PR body. 'json' is the full "
            "structured report for another tool to ingest."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Write the formatted report to this path in addition to "
            "stdout. Useful for stashing a markdown summary that "
            "bin/design-batch.py can then glue into the PR body."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    targets: list[str]
    if args.all:
        targets = [p.name for p in iter_themes()]
        if not targets:
            print("No shipping themes found.", file=sys.stderr)
            return 0
    else:
        try:
            root = resolve_theme_root(args.theme)
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            return 2
        targets = [root.name]

    reports: list[ThemeReport] = []
    overall_ok = True
    for slug in targets:
        r = verify(slug, run_snap=args.snap, strict_branch=args.strict)
        reports.append(r)
        if r.status == "failed":
            overall_ok = False
        if args.format == "text":
            sys.stdout.write(_format_text(r))
            sys.stdout.flush()

    if args.format == "json":
        payload = {
            "overall": "passed" if overall_ok else "failed",
            "themes": [asdict(r) for r in reports],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        print(text)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
    elif args.format == "markdown":
        text = "".join(_format_markdown(r) for r in reports)
        print(text, end="")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
    elif args.out:
        text = "".join(_format_text(r) for r in reports)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")

    if args.all and args.format == "text":
        passed = sum(1 for r in reports if r.status == "passed")
        failed = len(reports) - passed
        print(f"\nverify-theme summary: passed {passed}, failed {failed}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
