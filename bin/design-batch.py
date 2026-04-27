#!/usr/bin/env python3
"""Run `bin/design.py` for N themes unattended, one isolated git
worktree per theme.

Why this exists
---------------
`bin/design.py --prompt "..."` ships one theme. The user's mental model
for the 50-theme push is "one manifest, walk away, come back to N PRs."
This script is that walker. It:

1. Reads a manifest JSON listing themes (each a `prompt:` or `spec:`).
2. For each entry, materializes a fresh `git worktree` rooted on
   `origin/main` so cross-theme failures stay isolated and humans can
   `cd` into a worktree to inspect.
3. Runs `bin/design.py` inside the worktree (strict-by-default thanks
   to PR beta, so any phase failure surfaces immediately).
4. On success: commits + pushes + opens a PR (unless `--no-pr`).
5. On failure: leaves the worktree intact, records the reason in the
   run report, moves on to the next theme.
6. Honors `FIFTY_VISION_DAILY_BUDGET` *before* starting each theme so
   the run halts cleanly when the cap is reached, not mid-pipeline.
7. Is **resumable**: re-running with the same `--run-id` skips themes
   already marked `passed` in the run report.

Run report
----------
Every run writes `tmp/batch-<run-id>.json`:

    {
      "run_id": "...",
      "started_at": "2026-04-23T12:00:00Z",
      "manifest": "specs/batch-example.json",
      "themes": [
        {
          "slug": "midcentury",
          "status": "passed" | "failed" | "skipped" | "budget_capped",
          "elapsed_s": 213.4,
          "vision_cost_usd": 0.42,
          "worktree": "/abs/path/to/worktree",
          "branch": "agent/batch-<run-id>-midcentury",
          "pr_url": "https://github.com/.../pull/123",
          "error": null | "..."
        },
        ...
      ],
      "totals": {"passed": N, "failed": N, "skipped": N, "budget_capped": N,
                 "vision_cost_usd": X, "elapsed_s": Y}
    }

Concurrency
-----------
Default 1 (Playground holds a port, sequential is the safe baseline).
With `--concurrency N`, themes run in parallel using a thread pool;
each worker bumps the Playground port via `FIFTY_PLAYGROUND_PORT_BASE`
so they don't collide. Hard-capped at 4 to stay polite to Anthropic
rate limits.

Manifest format
---------------
::

    {
      "themes": [
        {"prompt": "midcentury department store with warm cream + burnt orange"},
        {"prompt": "japandi tea ceremony shop, monochrome cypress"},
        {"spec": "specs/aerocoastal.json"}
      ],
      "concurrency": 1,
      "model": "claude-sonnet-4-5-20250929"
    }

CLI flags override manifest values.

Examples
--------
Plan a batch (no shell-out, just print what would happen)::

    python3 bin/design-batch.py --manifest specs/batch-example.json --dry-run

Run a real batch (default concurrency 1, opens PRs)::

    python3 bin/design-batch.py --manifest specs/batch-example.json \\
        --run-id 2026-04-23-spring

Resume after a budget cap or crash (skips already-passed themes)::

    python3 bin/design-batch.py --manifest specs/batch-example.json \\
        --run-id 2026-04-23-spring

Re-attempt failed themes only::

    python3 bin/design-batch.py --manifest specs/batch-example.json \\
        --run-id 2026-04-23-spring --retry-failed
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# `datetime.UTC` is the 3.11+ alias; fall back to `timezone.utc` for
# Python 3.9/3.10 local envs. (Same pattern as bin/_vision_lib.py.)
UTC = getattr(dt, "UTC", dt.timezone.utc)  # noqa: UP017

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

# Imported for budget probe + spec validation. Keep this import lazy
# so `--help` doesn't fail when ANTHROPIC_API_KEY isn't set or the
# vision lib is otherwise unhappy.
def _vision_lib():
    import _vision_lib as v

    return v


def _design_lib():
    import _design_lib as d

    return d


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,38}$")
HARD_CONCURRENCY_CAP = 4
DEFAULT_RUN_DIR = ROOT / "tmp"
DEFAULT_WORKTREE_PARENT = ROOT.parent  # alongside the main repo dir


# ---------------------------------------------------------------------------
# Run-report types
# ---------------------------------------------------------------------------


@dataclass
class ThemeOutcome:
    """One row in the run report. Mutated as the pipeline progresses;
    serialized at the end of every theme so a crash mid-batch leaves a
    readable artifact on disk."""
    slug: str
    source: str
    status: str = "pending"  # pending|passed|failed|skipped|budget_capped
    elapsed_s: float = 0.0
    vision_cost_usd: float = 0.0
    worktree: str | None = None
    branch: str | None = None
    pr_url: str | None = None
    error: str | None = None
    spec_path: str | None = None
    # Post-push verification. ``verify_status`` is one of
    # "passed" | "failed" | "skipped" (not run by this batch) | None
    # (the field was added after a pre-existing run, so the entry
    # predates verification). ``verify_report_path`` points at the
    # JSON written by `bin/verify-theme.py` when we have it.
    verify_status: str | None = None
    verify_report_path: str | None = None


@dataclass
class RunReport:
    run_id: str
    started_at: str
    manifest: str
    themes: list[ThemeOutcome] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def recompute_totals(self) -> None:
        totals: dict[str, Any] = {
            "passed": 0, "failed": 0, "skipped": 0,
            "budget_capped": 0, "vision_cost_usd": 0.0, "elapsed_s": 0.0,
        }
        for t in self.themes:
            if t.status in totals:
                totals[t.status] += 1
            totals["vision_cost_usd"] += t.vision_cost_usd
            totals["elapsed_s"] += t.elapsed_s
        self.totals = totals


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


@dataclass
class ManifestEntry:
    """One theme to attempt. Either prompt or spec_path is set, not both."""
    prompt: str | None
    spec_path: Path | None
    slug_hint: str | None  # only used as a name for the worktree pre-design

    def source_label(self) -> str:
        if self.prompt:
            return f"prompt: {self.prompt[:60]}"
        return f"spec: {self.spec_path}"


def load_manifest(path: Path) -> tuple[list[ManifestEntry], dict[str, Any]]:
    """Return (entries, top-level options). The options dict carries
    `concurrency` and `model` if the manifest sets them; CLI flags
    override these."""
    if not path.is_file():
        raise SystemExit(f"error: manifest not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: manifest is not valid JSON: {e}") from e
    if not isinstance(raw, dict) or "themes" not in raw:
        raise SystemExit("error: manifest must be {\"themes\": [...]}")
    entries: list[ManifestEntry] = []
    for i, row in enumerate(raw.get("themes") or []):
        if not isinstance(row, dict):
            raise SystemExit(f"error: themes[{i}] is not an object")
        prompt = row.get("prompt")
        spec = row.get("spec")
        if bool(prompt) == bool(spec):
            raise SystemExit(
                f"error: themes[{i}] must set exactly one of "
                "'prompt' or 'spec'"
            )
        spec_path = Path(spec) if spec else None
        if spec_path is not None and not spec_path.is_absolute():
            spec_path = (ROOT / spec_path).resolve()
        entries.append(
            ManifestEntry(
                prompt=prompt,
                spec_path=spec_path,
                slug_hint=row.get("slug_hint"),
            )
        )
    opts = {k: v for k, v in raw.items() if k != "themes"}
    return entries, opts


# ---------------------------------------------------------------------------
# Slug derivation (used to name the worktree before `design.py` runs).
# We never persist this slug into the spec; the spec's own slug field
# wins. This is just a worktree placeholder so logs read sensibly.
# ---------------------------------------------------------------------------


def derive_pre_slug(entry: ManifestEntry, idx: int) -> str:
    """Pick a placeholder slug so the worktree path reads sensibly.
    Order: explicit slug_hint > spec.slug > sanitized prompt > index."""
    if entry.slug_hint and SLUG_PATTERN.match(entry.slug_hint):
        return entry.slug_hint
    if entry.spec_path and entry.spec_path.is_file():
        try:
            data = json.loads(entry.spec_path.read_text(encoding="utf-8"))
            slug = str(data.get("slug") or "")
            if SLUG_PATTERN.match(slug):
                return slug
        except (OSError, json.JSONDecodeError):
            pass
    if entry.prompt:
        # First 3 lowercased word-ish tokens, joined.
        tokens = re.findall(r"[a-z0-9]+", entry.prompt.lower())[:3]
        joined = "-".join(tokens)
        if SLUG_PATTERN.match(joined):
            return joined
    return f"batch-{idx:03d}"


# ---------------------------------------------------------------------------
# Per-theme runner
# ---------------------------------------------------------------------------


@dataclass
class RunnerOptions:
    run_id: str
    worktree_parent: Path
    base_branch: str  # e.g. "origin/main"
    open_prs: bool
    dry_run: bool
    extra_design_args: list[str]
    port_base: int  # FIFTY_PLAYGROUND_PORT_BASE for this worker
    label_run_id: bool
    # Post-push verification hook. When True (default), bin/verify-theme.py
    # runs inside the worktree after the push so any static-gate
    # regression a theme introduces surfaces in the batch run report
    # before we wait on CI. --no-verify disables it for agents doing
    # quick turns where the extra ~5-15s/theme isn't worth it.
    run_verify: bool = True
    # Arm GitHub auto-merge (squash) immediately after `gh pr create`
    # so a green PR lands on main without a human click. When False,
    # the PR opens with auto-merge OFF and a human must enable it.
    # Default True because the whole point of this runner is
    # hands-off batch shipping; disable it when you want to eyeball
    # each PR before letting it merge.
    arm_auto_merge: bool = True


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def _ensure_worktree(slug: str, opts: RunnerOptions) -> tuple[Path, str]:
    """Create `<worktree_parent>/fifty-batch-<slug>` on a new branch
    `agent/batch-<run-id>-<slug>` rooted at `opts.base_branch`. If the
    worktree exists already, leave it alone so resumability works."""
    branch = f"agent/batch-{opts.run_id}-{slug}"
    target = opts.worktree_parent / f"fifty-batch-{slug}"
    if target.is_dir():
        return target, branch
    if opts.dry_run:
        return target, branch
    # `git worktree add -b <branch> <path> <base>` checks out a fresh
    # branch from base in a new working tree.
    _git("worktree", "add", "-b", branch, str(target), opts.base_branch)
    return target, branch


def _run_design(
    entry: ManifestEntry,
    worktree: Path,
    opts: RunnerOptions,
) -> subprocess.CompletedProcess:
    """Invoke `bin/design.py` inside the worktree. Returns the
    completed process (caller inspects rc + stdout/stderr)."""
    cmd: list[str] = [sys.executable, "bin/design.py"]
    if entry.prompt:
        cmd.extend(["--prompt", entry.prompt])
    elif entry.spec_path:
        cmd.extend(["--spec", str(entry.spec_path)])
    cmd.extend(opts.extra_design_args)
    env = os.environ.copy()
    # Each worker gets its own Playground port so concurrency doesn't
    # collide. The port-base var is read by bin/snap.py; if it's not
    # honored (older snap.py versions), concurrency=1 still works.
    env["FIFTY_PLAYGROUND_PORT_BASE"] = str(opts.port_base)
    if opts.dry_run:
        # Simulate without shelling out. Return a successful process.
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=f"[dry-run] would run: {' '.join(shlex.quote(x) for x in cmd)} (cwd={worktree})\n",
            stderr="",
        )
    return subprocess.run(
        cmd,
        cwd=str(worktree),
        capture_output=False,  # stream to console so the operator sees progress
        text=True,
        env=env,
    )


def _resolve_slug_after_design(
    entry: ManifestEntry, worktree: Path, fallback: str
) -> str:
    """Find the slug `design.py` actually used. design.py mutates the
    spec's slug into the new theme dir name; the simplest way to read
    it back is to look at what new top-level dir appeared in the
    worktree. Falls back to the pre-derived slug if detection fails."""
    if entry.spec_path and entry.spec_path.is_file():
        try:
            data = json.loads(entry.spec_path.read_text(encoding="utf-8"))
            if SLUG_PATTERN.match(str(data.get("slug") or "")):
                return data["slug"]
        except (OSError, json.JSONDecodeError):
            pass
    # For --prompt mode, the spec was written to tmp/specs/<slug>.json
    # inside the worktree. Read it back if present.
    specs_dir = worktree / "tmp" / "specs"
    if specs_dir.is_dir():
        candidates = sorted(specs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if candidates:
            try:
                data = json.loads(candidates[-1].read_text(encoding="utf-8"))
                if SLUG_PATTERN.match(str(data.get("slug") or "")):
                    return data["slug"]
            except (OSError, json.JSONDecodeError):
                pass
    return fallback


@dataclass
class _CommitAndPushResult:
    pr_url: str | None
    pushed: bool
    verify_status: str | None = None
    verify_report_path: str | None = None


def _commit_and_push(
    worktree: Path,
    branch: str,
    slug: str,
    opts: RunnerOptions,
) -> _CommitAndPushResult:
    """Stage everything, commit, push, run verify-theme, open a PR.

    Returns a bundle with:
        * ``pr_url``: URL from ``gh pr create`` (None when --no-pr).
        * ``pushed``: True when ``git push`` ran.
        * ``verify_status``: "passed" | "failed" | "errored" | None when
          verification was skipped (``--no-verify`` or --no-pr).
        * ``verify_report_path``: JSON report on disk when we have it.
    """
    if opts.dry_run:
        return _CommitAndPushResult(
            pr_url=f"https://example.test/dry-run/{slug}",
            pushed=True,
            verify_status="skipped",
        )
    _git("add", "-A", cwd=worktree)
    status = _git("status", "--porcelain", cwd=worktree).stdout
    if not status.strip():
        # Nothing to commit -- design.py shouldn't usually leave a
        # clean tree, but if it does, fail loudly.
        raise RuntimeError(
            "design.py ran but produced no file changes; refusing to commit empty PR."
        )
    msg = (
        f"feat({slug}): bootstrap from batch {opts.run_id}\n\n"
        f"Generated by bin/design-batch.py.\nrun-id: {opts.run_id}\n"
    )
    _git("commit", "-m", msg, cwd=worktree)
    if not opts.open_prs:
        return _CommitAndPushResult(pr_url=None, pushed=False)
    _git("push", "-u", "origin", branch, cwd=worktree)

    verify_md = ""
    verify_status: str | None = None
    verify_path: str | None = None
    if opts.run_verify:
        # Run the in-worktree preflight so the PR body tells reviewers
        # whether CI's static gate would pass or fail. We capture both
        # the markdown (for the PR body) and the JSON (for the batch
        # report path) so humans and machines see the same picture.
        bundle = _run_verify_after_push(worktree, slug, opts)
        verify_md = bundle.md
        verify_status = bundle.status
        verify_path = bundle.json_path

    label_args: list[str] = ["--label", "design"]
    if opts.label_run_id:
        label_args.extend(["--label", f"batch-{opts.run_id}"])
    body = (
        f"Generated by `bin/design-batch.py` "
        f"(run-id: `{opts.run_id}`).\n\n"
        f"Worktree: `{worktree}`\n"
    )
    if verify_md:
        body += "\n---\n\n" + verify_md
    pr = subprocess.run(
        [
            "gh", "pr", "create",
            "--title", f"feat({slug}): bootstrap from batch {opts.run_id}",
            "--body", body,
            *label_args,
        ],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    )
    if pr.returncode != 0:
        raise RuntimeError(
            f"gh pr create failed (rc={pr.returncode}): {pr.stderr.strip()}"
        )
    pr_url = pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else None

    # Arm auto-merge so the PR lands the moment all required checks
    # pass -- without this, the batch produces N open PRs that each
    # need a human click even when the static gate + vision review +
    # first-baseline all go green. We squash-merge to keep main's
    # history linear (setup-branch-protection.sh enforces
    # required_linear_history: true). The call is best-effort: a
    # transient gh failure, auto-merge being disabled at the repo
    # level, or a missing pr_url just prints a warning and returns
    # the PR URL anyway -- the PR itself is still valid; only the
    # auto-merge arming is degraded.
    if opts.arm_auto_merge and pr_url:
        arm = subprocess.run(
            ["gh", "pr", "merge", pr_url, "--auto", "--squash"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
        )
        if arm.returncode != 0:
            sys.stderr.write(
                f"[batch] WARN: failed to arm auto-merge on {pr_url} "
                f"(rc={arm.returncode}): {arm.stderr.strip()}. "
                f"The PR is open; a human will need to enable "
                f"auto-merge (or merge manually) once checks are "
                f"green.\n"
            )

    return _CommitAndPushResult(
        pr_url=pr_url,
        pushed=True,
        verify_status=verify_status,
        verify_report_path=verify_path,
    )


@dataclass
class _VerifyBundle:
    """Structured return from the post-push verification shell-out.

    Fields:
        status: "passed" | "failed" | "errored"
        md: markdown fragment suitable for gluing into a PR body
        json_path: path to the full JSON report (may be None on error)
    """
    status: str
    md: str = ""
    json_path: str | None = None


def _run_verify_after_push(
    worktree: Path,
    slug: str,
    opts: RunnerOptions,
) -> _VerifyBundle:
    """Invoke `bin/verify-theme.py <slug> --strict --format markdown`
    inside the worktree after push, plus a JSON pass for a
    machine-readable record. Never raises -- verification failures are
    surfaced through the returned bundle so the caller can still finish
    opening the PR (with the failure summary in the body)."""
    json_path = worktree / "tmp" / f"verify-{opts.run_id}-{slug}.json"
    try:
        _run = subprocess.run(
            [
                sys.executable,
                "bin/verify-theme.py",
                slug,
                "--strict",
                "--format", "json",
                "--out", str(json_path),
            ],
            cwd=str(worktree),
            capture_output=True,
            text=True,
        )
    except Exception as e:
        return _VerifyBundle(
            status="errored",
            md=f"### verify-theme: errored\n\n`{type(e).__name__}: {e}`\n",
        )
    # A non-zero rc just means "at least one phase failed" -- the
    # stdout still contains a valid JSON report in that case. Only
    # treat "no stdout at all" as a hard error.
    raw = _run.stdout.strip()
    if not raw:
        return _VerifyBundle(
            status="errored",
            md=(
                "### verify-theme: errored\n\n"
                f"No output. stderr:\n```\n{_run.stderr.strip()}\n```\n"
            ),
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _VerifyBundle(
            status="errored",
            md=(
                "### verify-theme: errored\n\n"
                f"Output was not JSON. stderr:\n```\n{_run.stderr.strip()}\n```\n"
            ),
        )
    overall = data.get("overall", "failed")
    md_run = subprocess.run(
        [
            sys.executable,
            "bin/verify-theme.py",
            slug,
            "--strict",
            "--format", "markdown",
        ],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    )
    md = md_run.stdout if md_run.stdout else ""
    return _VerifyBundle(status=overall, md=md, json_path=str(json_path))


# ---------------------------------------------------------------------------
# Budget probe (cheap, runs before each theme)
# ---------------------------------------------------------------------------


def _budget_remaining(cap_usd: float) -> float:
    """Return remaining USD before the daily cap is breached. Negative
    means we're already over."""
    spent = _vision_lib().today_spend_usd()
    return cap_usd - spent


# ---------------------------------------------------------------------------
# Per-theme orchestrator
# ---------------------------------------------------------------------------


def _spend_so_far_in_run(report_lock: threading.Lock, report: RunReport) -> float:
    with report_lock:
        return sum(t.vision_cost_usd for t in report.themes)


def run_theme(
    entry: ManifestEntry,
    idx: int,
    *,
    opts: RunnerOptions,
    daily_cap_usd: float,
    report: RunReport,
    report_lock: threading.Lock,
    report_path: Path,
    skip_passed: bool,
    skip_failed: bool,
) -> ThemeOutcome:
    """Run one theme end-to-end. Mutates `report` in place and writes
    it to disk after each phase boundary so a crash leaves a useful
    artifact behind."""
    pre_slug = derive_pre_slug(entry, idx)
    outcome = ThemeOutcome(
        slug=pre_slug,
        source=entry.source_label(),
        spec_path=str(entry.spec_path) if entry.spec_path else None,
    )

    with report_lock:
        # Resumability: if a prior outcome with this pre-slug already
        # passed, skip; if it failed and we're not retrying, skip too.
        existing = next((t for t in report.themes if t.slug == pre_slug), None)
        if existing and existing.status == "passed" and skip_passed:
            existing.status = "skipped" if not skip_passed else "passed"
            return existing
        if existing and existing.status == "failed" and skip_failed:
            return existing
        if existing:
            # Replace the prior row so a retry shows fresh data.
            report.themes = [t for t in report.themes if t.slug != pre_slug]
        report.themes.append(outcome)
        report.recompute_totals()
        report.write(report_path)

    # Budget probe -- refuse to start if we're already over the cap.
    remaining = _budget_remaining(daily_cap_usd)
    if remaining <= 0:
        outcome.status = "budget_capped"
        outcome.error = (
            f"Daily vision budget already exhausted "
            f"(${daily_cap_usd - remaining:.2f} > ${daily_cap_usd:.2f})."
        )
        with report_lock:
            report.recompute_totals()
            report.write(report_path)
        return outcome

    started = time.monotonic()
    pre_spend = _vision_lib().today_spend_usd()
    try:
        worktree, branch = _ensure_worktree(pre_slug, opts)
        outcome.worktree = str(worktree)
        outcome.branch = branch
        proc = _run_design(entry, worktree, opts)
        if proc.returncode != 0:
            outcome.status = "failed"
            outcome.error = (
                f"bin/design.py exited {proc.returncode}; worktree "
                f"left intact at {worktree} for inspection."
            )
            return outcome
        slug = _resolve_slug_after_design(entry, worktree, pre_slug)
        outcome.slug = slug
        result = _commit_and_push(worktree, branch, slug, opts)
        outcome.pr_url = result.pr_url
        outcome.verify_status = result.verify_status
        outcome.verify_report_path = result.verify_report_path
        # A failing verify-theme blocks the PR from being tagged
        # "passed" in the run report. The PR still opens (with the
        # failure summary in the body) so reviewers can push fixups
        # without re-running the batch.
        if result.verify_status == "failed":
            outcome.status = "failed"
            outcome.error = (
                "bin/verify-theme.py reported failures after push; "
                f"see {result.verify_report_path or '<no report>'}."
            )
        else:
            outcome.status = "passed"
        return outcome
    except Exception as e:
        outcome.status = "failed"
        outcome.error = f"{type(e).__name__}: {e}"
        return outcome
    finally:
        outcome.elapsed_s = round(time.monotonic() - started, 1)
        outcome.vision_cost_usd = round(_vision_lib().today_spend_usd() - pre_spend, 4)
        with report_lock:
            report.recompute_totals()
            report.write(report_path)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="design-batch.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--manifest",
        required=False,
        type=Path,
        default=None,
        help=(
            "Path to manifest JSON listing themes to design. Mutually "
            "exclusive with --from-concepts: one source of entries is "
            "required."
        ),
    )
    p.add_argument(
        "--from-concepts",
        action="store_true",
        help=(
            "Synthesize a manifest from bin/concept_seed.CONCEPTS -- every "
            "concept that has a mockup PNG under docs/mockups/ but no theme "
            "directory yet. Uses bin/concept-to-spec.py to generate one "
            "spec JSON per concept into tmp/specs/<slug>.json before "
            "handing off to the normal worktree-per-theme loop. "
            "Combine with --limit to batch N at a time, or "
            "--concept-slugs a,b,c to scope to specific concepts."
        ),
    )
    p.add_argument(
        "--concept-slugs",
        default=None,
        help=(
            "Comma-separated concept slugs to include (overrides "
            "--from-concepts's default of 'all concepts without a theme "
            "dir'). Slugs MUST exist in bin/concept_seed.CONCEPTS. "
            "Useful for re-driving a specific set after a failed batch."
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "When used with --from-concepts, cap the number of themes "
            "attempted this run. Ignored when --manifest is used (the "
            "manifest size is the cap). Recommended for first runs: "
            "--limit 5 matches the Day-0 smoke-batch shape."
        ),
    )
    p.add_argument(
        "--concept-spec-mode",
        choices=("llm", "no-llm"),
        default="no-llm",
        help=(
            "How --from-concepts should build each spec. 'no-llm' "
            "(default) uses the deterministic controlled-vocab mapping "
            "from bin/concept-to-spec.py -- free, offline-safe, "
            "reproducible. 'llm' sends the mockup PNG + concept metadata "
            "to the vision model for a polished spec. Use 'no-llm' for "
            "first rehearsal runs so the batch halt condition is 'spec "
            "failed to validate', not 'ran out of vision budget'."
        ),
    )
    p.add_argument(
        "--run-id",
        default=None,
        help=(
            "Stable identifier for this run (used in branch names, "
            "PR labels, and tmp/batch-<run-id>.json). Default: "
            "today's date + a short random suffix. Re-using a run-id "
            "skips themes already marked passed (resumability)."
        ),
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=(
            f"Run N themes in parallel. Default: 1. Hard-capped at "
            f"{HARD_CONCURRENCY_CAP} to stay polite to Anthropic and "
            "Playground. Manifest can also set `concurrency`; CLI wins."
        ),
    )
    p.add_argument(
        "--budget-usd",
        type=float,
        default=None,
        help=(
            "Daily vision budget cap (USD). Default: read from "
            "FIFTY_VISION_DAILY_BUDGET (currently "
            f"${_vision_default_budget():.2f}). Probed BEFORE each "
            "theme so the run halts cleanly when the cap is reached."
        ),
    )
    p.add_argument(
        "--worktree-parent",
        type=Path,
        default=None,
        help=(
            "Directory in which to create per-theme worktrees. "
            f"Default: {DEFAULT_WORKTREE_PARENT} (alongside this repo). "
            "Each worktree lands at `<parent>/fifty-batch-<slug>`."
        ),
    )
    p.add_argument(
        "--base-branch",
        default="origin/main",
        help="Branch to root each worktree on. Default: origin/main.",
    )
    p.add_argument(
        "--no-pr",
        action="store_true",
        help=(
            "Do everything except push and `gh pr create`. Useful for "
            "local rehearsal before burning real PRs."
        ),
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help=(
            "Skip the post-push `bin/verify-theme.py --strict` run. "
            "Default is to run it so the batch run report flags any "
            "theme whose CI gate would fail before the reviewer waits "
            "on GitHub Actions. Use sparingly; --dry-run implies this."
        ),
    )
    p.add_argument(
        "--no-auto-merge",
        action="store_true",
        help=(
            "Open each PR without arming GitHub auto-merge. Default is "
            "to arm `--auto --squash` immediately after `gh pr create` "
            "so a green PR lands hands-off. Use this when you want to "
            "eyeball each PR before it merges (e.g. when debugging the "
            "pipeline, or on a one-off batch you plan to hand-review)."
        ),
    )
    p.add_argument(
        "--retry-failed",
        action="store_true",
        help=(
            "Re-attempt themes whose status in the existing run report "
            "is 'failed'. Default behaviour skips them (assumes the "
            "operator will inspect first)."
        ),
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "Treat this as a fresh run even if a report at "
            "tmp/batch-<run-id>.json exists. Overwrites the report."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Plan the batch without creating worktrees, calling "
            "design.py, or opening PRs. Writes a planning report to "
            "tmp/batch-<run-id>.json so the operator can confirm the "
            "shape before committing."
        ),
    )
    p.add_argument(
        "--port-base",
        type=int,
        default=9400,
        help=(
            "First Playground port to allocate. Workers get "
            "port_base + worker_index. Default: 9400."
        ),
    )
    p.add_argument(
        "--design-arg",
        action="append",
        default=[],
        metavar="ARG",
        help=(
            "Extra argument to forward to `bin/design.py`. May be "
            "repeated. Example: --design-arg --skip-snap."
        ),
    )
    return p


def _vision_default_budget() -> float:
    try:
        return _vision_lib().DEFAULT_DAILY_BUDGET_USD
    except Exception:
        return 20.0


def _resolve_run_id(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    return f"{dt.datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def _resolve_concurrency(cli: int | None, manifest: dict[str, Any]) -> int:
    raw = cli if cli is not None else int(manifest.get("concurrency", 1))
    if raw < 1:
        raise SystemExit("error: concurrency must be >= 1")
    if raw > HARD_CONCURRENCY_CAP:
        print(
            f"warn: concurrency {raw} exceeds hard cap "
            f"{HARD_CONCURRENCY_CAP}; clamping.",
            file=sys.stderr,
        )
        raw = HARD_CONCURRENCY_CAP
    return raw


def _load_existing_report(path: Path) -> RunReport | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    themes = [ThemeOutcome(**t) for t in raw.get("themes") or []]
    return RunReport(
        run_id=raw.get("run_id", ""),
        started_at=raw.get("started_at", ""),
        manifest=raw.get("manifest", ""),
        themes=themes,
        totals=raw.get("totals", {}),
    )


def _synthesize_from_concepts(
    *,
    concept_slugs: str | None,
    limit: int | None,
    spec_mode: str,
) -> tuple[list[ManifestEntry], dict[str, Any]]:
    """Build a manifest's worth of ManifestEntry rows from concept_seed.

    Produces one `tmp/specs/<slug>.json` per selected concept via
    `bin/concept-to-spec.py`'s in-process entry points, then returns
    the list of `ManifestEntry(spec_path=...)`. This keeps the rest
    of the batch machinery (worktrees, resumability, PR opening)
    identical whether the batch came from a manifest or from concepts.

    Selection rules:
      * If `concept_slugs` is set, use that comma-separated list.
      * Otherwise, pick every concept that:
          (a) has an entry in `concept_seed.CONCEPTS`,
          (b) has a mockup PNG at `docs/mockups/<slug>.png`, AND
          (c) does NOT yet have a theme directory `./<slug>/theme.json`.
      * Then apply `limit` (if set).

    The function exits with a non-zero SystemExit on bad input (unknown
    slug, missing mockup, spec fails validation). The caller does not
    swallow these: a broken concept list should halt the batch before
    any worktree is created.
    """
    # Lazy imports so `design-batch.py --manifest ...` (the legacy
    # path) doesn't pay the concept-to-spec import cost when it's not
    # needed. And so `--help` still works if concept_seed is broken.
    spec = importlib.util.spec_from_file_location(
        "concept_to_spec", ROOT / "bin" / "concept-to-spec.py"
    )
    if spec is None or spec.loader is None:
        raise SystemExit("error: could not load bin/concept-to-spec.py")
    c2s = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("concept_to_spec", c2s)
    spec.loader.exec_module(c2s)

    from concept_seed import CONCEPTS

    by_slug = {c["slug"]: c for c in CONCEPTS}

    if concept_slugs:
        wanted = [s.strip() for s in concept_slugs.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in by_slug]
        if unknown:
            raise SystemExit(
                f"error: --concept-slugs references unknown concepts: {unknown}. "
                "All slugs must exist in bin/concept_seed.CONCEPTS."
            )
        picked = wanted
    else:
        picked = []
        for s, c in by_slug.items():
            mockup = ROOT / "docs" / "mockups" / f"{s}.png"
            theme_dir = ROOT / s / "theme.json"
            if mockup.is_file() and not theme_dir.exists():
                picked.append(s)
        # Stable sort so `--limit N` is reproducible across runs.
        picked.sort()

    if limit is not None:
        picked = picked[: max(0, limit)]

    if not picked:
        raise SystemExit(
            "error: --from-concepts found no candidates. Every concept "
            "with a mockup already has a theme directory, or the mockup "
            "PNGs are missing. Use --concept-slugs to force a specific set."
        )

    specs_dir = ROOT / "tmp" / "specs"
    entries: list[ManifestEntry] = []
    for slug in picked:
        out = specs_dir / f"{slug}.json"
        concept = by_slug[slug]
        mockup = ROOT / "docs" / "mockups" / f"{slug}.png"
        try:
            if spec_mode == "no-llm":
                payload = c2s.concept_to_spec(concept)
            else:
                payload = c2s.concept_to_spec_llm(concept, mockup, dry_run=False)
            c2s.write_spec(payload, out)
        except c2s.ConceptToSpecError as e:
            raise SystemExit(f"error: concept {slug!r}: {e}") from e
        entries.append(
            ManifestEntry(
                prompt=None,
                spec_path=out.resolve(),
                slug_hint=slug,
            )
        )
        print(f"[batch] concept-to-spec wrote {out}", file=sys.stderr)
    return entries, {}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.from_concepts and args.manifest is not None:
        print(
            "error: --from-concepts and --manifest are mutually exclusive; "
            "pick one source of entries.",
            file=sys.stderr,
        )
        return 2
    if not args.from_concepts and args.manifest is None:
        print(
            "error: exactly one of --manifest or --from-concepts is required.",
            file=sys.stderr,
        )
        return 2
    if args.from_concepts:
        entries, manifest_opts = _synthesize_from_concepts(
            concept_slugs=args.concept_slugs,
            limit=args.limit,
            spec_mode=args.concept_spec_mode,
        )
    else:
        entries, manifest_opts = load_manifest(args.manifest)
    if not entries:
        print("error: no themes to run", file=sys.stderr)
        return 2

    run_id = _resolve_run_id(args.run_id)
    concurrency = _resolve_concurrency(args.concurrency, manifest_opts)
    daily_cap = (
        args.budget_usd
        if args.budget_usd is not None
        else _vision_default_budget()
    )
    worktree_parent = (args.worktree_parent or DEFAULT_WORKTREE_PARENT).resolve()
    worktree_parent.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_RUN_DIR / f"batch-{run_id}.json"

    existing = None if args.no_resume else _load_existing_report(report_path)
    if existing is not None:
        report = existing
        print(
            f"[batch] resuming run {run_id}: "
            f"{report.totals.get('passed', 0)} passed, "
            f"{report.totals.get('failed', 0)} failed in prior pass.",
            file=sys.stderr,
        )
    else:
        report = RunReport(
            run_id=run_id,
            started_at=dt.datetime.now(UTC).isoformat(),
            manifest=str(args.manifest),
        )

    opts = RunnerOptions(
        run_id=run_id,
        worktree_parent=worktree_parent,
        base_branch=args.base_branch,
        open_prs=not args.no_pr,
        dry_run=args.dry_run,
        extra_design_args=list(args.design_arg or []),
        port_base=args.port_base,
        label_run_id=True,
        run_verify=not args.no_verify,
        arm_auto_merge=not args.no_auto_merge,
    )

    print(
        f"[batch] run-id={run_id} themes={len(entries)} "
        f"concurrency={concurrency} daily-cap=${daily_cap:.2f} "
        f"worktree-parent={worktree_parent} dry-run={args.dry_run}",
        file=sys.stderr,
    )

    report_lock = threading.Lock()

    def _one(idx_entry: tuple[int, ManifestEntry]) -> ThemeOutcome:
        idx, entry = idx_entry
        # Allocate a unique port per worker by mixing the entry index
        # with the base. Single-worker runs always use port_base.
        local_opts = RunnerOptions(**{**asdict(opts), "port_base": opts.port_base + idx})
        return run_theme(
            entry,
            idx,
            opts=local_opts,
            daily_cap_usd=daily_cap,
            report=report,
            report_lock=report_lock,
            report_path=report_path,
            skip_passed=True,
            skip_failed=not args.retry_failed,
        )

    if concurrency == 1:
        for pair in enumerate(entries):
            outcome = _one(pair)
            print(
                f"[batch] {outcome.slug}: {outcome.status} "
                f"({outcome.elapsed_s:.0f}s, ${outcome.vision_cost_usd:.2f})",
                file=sys.stderr,
            )
            if outcome.status == "budget_capped":
                print(
                    "[batch] daily cap reached; stopping. Re-run with "
                    "the same --run-id tomorrow to resume.",
                    file=sys.stderr,
                )
                break
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_one, pair): pair for pair in enumerate(entries)}
            for fut in as_completed(futures):
                outcome = fut.result()
                print(
                    f"[batch] {outcome.slug}: {outcome.status} "
                    f"({outcome.elapsed_s:.0f}s, ${outcome.vision_cost_usd:.2f})",
                    file=sys.stderr,
                )

    report.recompute_totals()
    report.write(report_path)

    print(
        f"[batch] done. report: {report_path}\n"
        f"[batch] totals: {json.dumps(report.totals)}",
        file=sys.stderr,
    )
    # Exit non-zero if any theme failed so CI/cron can notice.
    if report.totals.get("failed", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
