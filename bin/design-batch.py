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
3. Runs `bin/design.py build` inside the worktree and opens a draft PR
   as soon as a runnable branch exists.
4. Runs `bin/design.py dress` on the same branch so content-fit,
   vision-review, and repair commits layer onto the draft.
5. On success: verifies the branch, marks the draft ready, and arms
   auto-merge when allowed.
6. On failure: leaves the draft PR/worktree intact, records the reason
   in the run report, moves on to the next theme.
7. Honors `FIFTY_VISION_DAILY_BUDGET` *before* starting each theme so
   the run halts cleanly when the cap is reached, not mid-pipeline.
8. Is **resumable**: re-running with the same `--run-id` skips themes
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
      "model": "claude-sonnet-4-6"
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
BATCH_VISION_LEDGER = ROOT / "tmp" / "vision-spend.jsonl"
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
TOP_WATCH_ENV = "FIFTY_BATCH_TOP_WATCH"
THEME_WATCH_MAX_ELAPSED_SECONDS = 90 * 60


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
    design_run_id: str | None = None
    design_status_path: str | None = None
    next_action: str | None = None
    rescue_used: bool = False
    recipes_used: list[str] = field(default_factory=list)
    json_repair_used: bool = False
    tool_rescue_used: bool = False
    human_required: bool = False
    human_boundary: str | None = None
    rescue_attempts: int = 0
    rescue_artifacts: list[str] = field(default_factory=list)
    factory_defects: list[dict[str, Any]] = field(default_factory=list)
    factory_defect_artifacts: list[str] = field(default_factory=list)
    needs_tooling_count: int = 0
    prevention_groups: dict[str, int] = field(default_factory=dict)


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
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "budget_capped": 0,
            "vision_cost_usd": 0.0,
            "elapsed_s": 0.0,
            "prevention_groups": {},
        }
        for t in self.themes:
            if t.status in totals:
                totals[t.status] += 1
            totals["vision_cost_usd"] += t.vision_cost_usd
            totals["elapsed_s"] += t.elapsed_s
            groups = totals["prevention_groups"]
            for layer, count in t.prevention_groups.items():
                groups[layer] = groups.get(layer, 0) + count
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
        raise SystemExit('error: manifest must be {"themes": [...]}')
    entries: list[ManifestEntry] = []
    for i, row in enumerate(raw.get("themes") or []):
        if not isinstance(row, dict):
            raise SystemExit(f"error: themes[{i}] is not an object")
        prompt = row.get("prompt")
        spec = row.get("spec")
        if bool(prompt) == bool(spec):
            raise SystemExit(f"error: themes[{i}] must set exactly one of 'prompt' or 'spec'")
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
    # Run `bin/verify-theme.py --snap` so the post-push verification
    # also re-shoots the theme and runs every snap-backed gate
    # (placeholder images, my-account dashboard layout, vision review,
    # axe). Adds ~2-5 minutes per theme but is the only way to catch
    # the regression class that already shipped twice (Chonk's empty
    # hero and the my-account column collapse). Default True so the
    # batch shipping path matches what CI would run; flip off via
    # --no-verify-snap when iterating quickly on the orchestrator.
    run_verify_snap: bool = True
    # Arm GitHub auto-merge (squash) immediately after `gh pr create`
    # so a green PR lands on main without a human click. When False,
    # the PR opens with auto-merge OFF and a human must enable it.
    # Default True because the whole point of this runner is
    # hands-off batch shipping; disable it when you want to eyeball
    # each PR before letting it merge.
    #
    # NOTE: arming auto-merge is also gated on the verify bundle's
    # status. If `verify_status != "passed"` we open the PR but leave
    # auto-merge OFF so a human reviewer is forced to look at the
    # failing gate before the change lands. See `_commit_and_push`
    # below for the gating logic.
    arm_auto_merge: bool = True
    # Allow auto-merge even when verify-theme failed. Default False
    # (closed-loop: a failing snap or static gate blocks auto-merge
    # at orchestration time, not just at branch-protection time). Flip
    # to True only for explicit one-off rescue runs.
    arm_auto_merge_on_failure: bool = False
    # Run each theme through bin/design-watch.py, which records
    # tmp/runs/<run-id>/STATUS.md and invokes design_unblock.py by
    # default on known repairable blockers. This is the default because
    # the batch runner's promise is "walk away, come back to PRs", not
    # "watch design.py fail and manually resume it."
    self_heal: bool = True
    max_repair_rounds: int = 3
    unblock_dry_run: bool = False
    # Progressive mode splits generation into `design.py build` followed
    # by `design.py dress`. The build step commits + pushes a structurally
    # sound draft first, then the slower content/vision work lands as
    # follow-up commits on the same branch. If the later phase stalls or
    # fails, the run still leaves a reviewable PR instead of only a local
    # worktree.
    progressive: bool = True
    # --no-resume means "fresh proof", not just "ignore the old JSON
    # report." Reusing a failed child worktree leaves the theme directory
    # in place and design.py aborts during clone.
    fresh_worktree: bool = False
    # Successful JSON/tool-rescue fixes indicate that the factory built
    # something it later had to repair. Keep the PR draft and do not
    # arm auto-merge until those fixes have deterministic coverage,
    # unless this explicit escape hatch is set.
    allow_unpromoted_factory_defects: bool = False


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


def _delete_fresh_remote_batch_branch(branch: str, opts: RunnerOptions) -> None:
    """Drop stale generated remotes when --no-resume asks for a fresh proof.

    The branch name is produced by this runner, but keep the prefix guard so a
    future caller cannot accidentally delete a human-owned remote branch.
    """
    if opts.dry_run or not opts.fresh_worktree or not branch.startswith("agent/batch-"):
        return

    remote_ref = f"refs/heads/{branch}"
    exists = _git("ls-remote", "--exit-code", "origin", remote_ref, check=False)
    if exists.returncode == 0:
        _git("push", "origin", "--delete", branch)


def _ensure_worktree(slug: str, opts: RunnerOptions) -> tuple[Path, str]:
    """Create `<worktree_parent>/fifty-batch-<slug>` on a new branch
    `agent/batch-<run-id>-<slug>` rooted at `opts.base_branch`. If the
    worktree exists already, leave it alone so resumability works."""
    branch = f"agent/batch-{opts.run_id}-{slug}"
    target = opts.worktree_parent / f"fifty-batch-{slug}"
    if target.is_dir():
        if opts.fresh_worktree and not opts.dry_run:
            _git("worktree", "remove", "--force", str(target))
        else:
            return target, branch
    if _git("branch", "--list", branch).stdout.strip() and not opts.dry_run:
        _git("branch", "-D", branch)
    _delete_fresh_remote_batch_branch(branch, opts)
    if target.is_dir():
        return target, branch
    if opts.dry_run:
        return target, branch
    # `git worktree add -b <branch> <path> <base>` checks out a fresh
    # branch from base in a new working tree.
    _git("worktree", "add", "-b", branch, str(target), opts.base_branch)
    return target, branch


def _run_design_cmd(
    design_cmd: list[str],
    *,
    worktree: Path,
    opts: RunnerOptions,
    design_run_id: str,
) -> subprocess.CompletedProcess:
    """Invoke `bin/design.py` (or the self-healing wrapper) in a worktree."""
    if opts.self_heal:
        cmd = [
            sys.executable,
            "bin/design-watch.py",
            "--run-id",
            design_run_id,
            "--max-elapsed-seconds",
            str(THEME_WATCH_MAX_ELAPSED_SECONDS),
            "--max-repair-rounds",
            str(opts.max_repair_rounds),
        ]
        if opts.unblock_dry_run:
            cmd.append("--unblock-dry-run")
        cmd.extend(["--", *design_cmd])
    else:
        cmd = [sys.executable, "bin/design.py", *design_cmd]

    env = os.environ.copy()
    # Each worker gets its own Playground port so concurrency doesn't
    # collide. The port-base var is read by bin/snap.py; if it's not
    # honored (older snap.py versions), concurrency=1 still works.
    env["FIFTY_PLAYGROUND_PORT_BASE"] = str(opts.port_base)
    # Share one ledger across child worktrees so the batch-level budget
    # probe includes real API calls from every theme. Without this each
    # worktree writes tmp/vision-spend.jsonl under its own root and the
    # orchestrator incorrectly sees $0 spent.
    env["FIFTY_VISION_LEDGER"] = str(BATCH_VISION_LEDGER)
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


def _entry_design_args(entry: ManifestEntry) -> list[str]:
    design_cmd: list[str] = []
    if entry.prompt:
        design_cmd.extend(["--prompt", entry.prompt])
    elif entry.spec_path:
        design_cmd.extend(["--spec", str(entry.spec_path)])
    return design_cmd


def _run_design(
    entry: ManifestEntry,
    worktree: Path,
    opts: RunnerOptions,
    pre_slug: str,
) -> subprocess.CompletedProcess:
    """Invoke the legacy all-in-one `bin/design.py` path."""
    return _run_design_cmd(
        [*_entry_design_args(entry), *opts.extra_design_args],
        worktree=worktree,
        opts=opts,
        design_run_id=f"batch-{opts.run_id}-{pre_slug}",
    )


def _run_design_stage(
    stage: str,
    design_cmd: list[str],
    *,
    worktree: Path,
    opts: RunnerOptions,
    pre_slug: str,
) -> subprocess.CompletedProcess:
    """Run one progressive stage (`build` or `dress`) with its own STATUS.md."""
    return _run_design_cmd(
        [stage, *design_cmd, *opts.extra_design_args],
        worktree=worktree,
        opts=opts,
        design_run_id=f"batch-{opts.run_id}-{pre_slug}-{stage}",
    )


def _resolve_slug_after_design(entry: ManifestEntry, worktree: Path, fallback: str) -> str:
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


def _read_rescue_summary(worktree: Path, run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {
            "recipes_used": [],
            "json_repair_used": False,
            "tool_rescue_used": False,
            "human_required": False,
            "human_boundary": None,
            "rescue_attempts": 0,
            "rescue_artifacts": [],
            "factory_defects": [],
            "factory_defect_artifacts": [],
            "needs_tooling_count": 0,
            "prevention_groups": {},
        }
    run_dir = worktree / "tmp" / "runs" / run_id
    attempts_path = run_dir / "repair-attempts.jsonl"
    defects_path = run_dir / "factory-defects.jsonl"
    attempts: list[dict[str, Any]] = []
    if attempts_path.is_file():
        for line in attempts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                attempts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    defects: list[dict[str, Any]] = []
    if defects_path.is_file():
        for line in defects_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                defects.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    layers: list[str] = []
    recipes: set[str] = set()
    human_boundary: str | None = None
    for attempt in attempts:
        verification = attempt.get("verification") or {}
        if not isinstance(verification, dict):
            continue
        layer = str(verification.get("layer") or "")
        if layer:
            layers.append(layer)
        for recipe in verification.get("recipes") or []:
            recipes.add(str(recipe))
        boundary = verification.get("human_boundary")
        if boundary:
            human_boundary = str(boundary)
    artifacts = [
        str(path)
        for path in (
            run_dir / "STATUS.md",
            run_dir / "summary.json",
            run_dir / "repair-plan.json",
            attempts_path,
            defects_path,
        )
        if path.exists()
    ]
    defect_artifacts = [str(defects_path)] if defects_path.exists() else []
    needs_tooling_count = sum(
        1 for defect in defects if defect.get("tooling_status") == "needs-tooling"
    )
    prevention_groups: dict[str, int] = {}
    for defect in defects:
        key = str(defect.get("prevention_layer") or defect.get("promotion_target") or "unknown")
        prevention_groups[key] = prevention_groups.get(key, 0) + 1
    if human_boundary is None:
        status_path = run_dir / "STATUS.md"
        status_text = (
            status_path.read_text(encoding="utf-8", errors="replace")
            if status_path.is_file()
            else ""
        )
        if "Too Many Requests" in status_text or "HTTPError 429" in status_text:
            human_boundary = "external-rate-limit"
        elif "ApiKeyMissingError" in status_text or "ANTHROPIC_API_KEY" in status_text:
            human_boundary = "missing-api-key"
    return {
        "recipes_used": sorted(recipes),
        "json_repair_used": "json-llm" in layers
        or any(
            "llm_rationale" in (a.get("verification") or {})
            and (a.get("verification") or {}).get("layer") != "tool-rescue"
            for a in attempts
        ),
        "tool_rescue_used": "tool-rescue" in layers,
        "human_required": human_boundary is not None,
        "human_boundary": human_boundary,
        "rescue_attempts": len(attempts),
        "rescue_artifacts": artifacts,
        "factory_defects": defects,
        "factory_defect_artifacts": defect_artifacts,
        "needs_tooling_count": needs_tooling_count,
        "prevention_groups": prevention_groups,
    }


def _combine_rescue_summaries(*summaries: dict[str, Any]) -> dict[str, Any]:
    recipes: set[str] = set()
    defects: list[dict[str, Any]] = []
    defect_artifacts: list[str] = []
    rescue_artifacts: list[str] = []
    prevention_groups: dict[str, int] = {}
    for summary in summaries:
        recipes.update(str(recipe) for recipe in summary.get("recipes_used") or [])
        defects.extend(summary.get("factory_defects") or [])
        defect_artifacts.extend(summary.get("factory_defect_artifacts") or [])
        rescue_artifacts.extend(summary.get("rescue_artifacts") or [])
        for layer, count in (summary.get("prevention_groups") or {}).items():
            key = str(layer)
            prevention_groups[key] = prevention_groups.get(key, 0) + int(count)
    human_boundary = next(
        (
            summary.get("human_boundary")
            for summary in reversed(summaries)
            if summary.get("human_boundary")
        ),
        None,
    )
    return {
        "recipes_used": sorted(recipes),
        "json_repair_used": any(bool(summary.get("json_repair_used")) for summary in summaries),
        "tool_rescue_used": any(bool(summary.get("tool_rescue_used")) for summary in summaries),
        "human_required": any(bool(summary.get("human_required")) for summary in summaries),
        "human_boundary": human_boundary,
        "rescue_attempts": sum(int(summary.get("rescue_attempts") or 0) for summary in summaries),
        "rescue_artifacts": sorted(set(rescue_artifacts)),
        "factory_defects": defects,
        "factory_defect_artifacts": sorted(set(defect_artifacts)),
        "needs_tooling_count": sum(
            1 for defect in defects if defect.get("tooling_status") == "needs-tooling"
        ),
        "prevention_groups": prevention_groups,
    }


def _apply_rescue_summary(outcome: ThemeOutcome, summary: dict[str, Any]) -> None:
    outcome.recipes_used = list(summary["recipes_used"])
    outcome.json_repair_used = bool(summary["json_repair_used"])
    outcome.tool_rescue_used = bool(summary["tool_rescue_used"])
    outcome.human_required = bool(summary["human_required"])
    outcome.human_boundary = summary["human_boundary"]
    outcome.rescue_attempts = int(summary["rescue_attempts"])
    outcome.rescue_artifacts = list(summary["rescue_artifacts"])
    outcome.factory_defects = list(summary.get("factory_defects") or [])
    outcome.factory_defect_artifacts = list(summary.get("factory_defect_artifacts") or [])
    outcome.needs_tooling_count = int(summary.get("needs_tooling_count") or 0)
    outcome.prevention_groups = dict(summary.get("prevention_groups") or {})


def _commit_and_push(
    worktree: Path,
    branch: str,
    slug: str,
    opts: RunnerOptions,
    rescue_summary: dict[str, Any] | None = None,
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
        f"Generated by `bin/design-batch.py` (run-id: `{opts.run_id}`).\n\nWorktree: `{worktree}`\n"
    )
    if verify_md:
        body += "\n---\n\n" + verify_md
    pr = _run_gh_pr_create(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"feat({slug}): bootstrap from batch {opts.run_id}",
            "--body",
            body,
            *label_args,
        ],
        cwd=worktree,
    )
    if pr.returncode != 0:
        stderr = _process_text(pr.stderr).strip()
        raise RuntimeError(f"gh pr create failed (rc={pr.returncode}): {stderr}")
    stdout = _process_text(pr.stdout).strip()
    pr_url = stdout.splitlines()[-1] if stdout else None
    _post_pr_status_comment(
        worktree=worktree,
        pr_url=pr_url,
        slug=slug,
        opts=opts,
        phase="opened",
        verify_status=verify_status,
        verify_report_path=verify_path,
        rescue_summary=rescue_summary,
    )

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
    # Auto-merge is gated on a CLEAN verify bundle. A failed snap, a
    # blocked static check, or an errored verify run all suppress
    # auto-merge so a human reviewer is forced to look at the
    # findings before the PR lands. The `arm_auto_merge_on_failure`
    # escape hatch exists only for explicit rescue runs.
    needs_tooling_count = (
        int(rescue_summary.get("needs_tooling_count") or 0) if rescue_summary else 0
    )
    auto_merge_blocked = bool(
        (verify_status and verify_status != "passed" and not opts.arm_auto_merge_on_failure)
        or (needs_tooling_count and not opts.allow_unpromoted_factory_defects)
    )
    if opts.arm_auto_merge and pr_url and auto_merge_blocked:
        sys.stderr.write(
            f"[batch] merge blocked on {slug}: verify={verify_status or 'pending'}, "
            f"needs-tooling={needs_tooling_count}. "
            f"auto-merge NOT armed on {pr_url}. The PR is open with the "
            f"failure summary in the body so a reviewer can decide "
            f"whether to fix-and-merge or close.\n"
        )
    elif opts.arm_auto_merge and pr_url:
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


def _label_args(opts: RunnerOptions) -> list[str]:
    label_args: list[str] = ["--label", "design"]
    if opts.label_run_id:
        label_args.extend(["--label", f"batch-{opts.run_id}"])
    return label_args


def _current_pr_url(worktree: Path, branch: str) -> str | None:
    """Return an existing open PR URL for branch, if GitHub knows one."""
    proc = subprocess.run(
        ["gh", "pr", "view", branch, "--json", "url", "-q", ".url"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    return url or None


def _ensure_batch_label(run_id: str) -> None:
    """Create the `batch-<run_id>` PR label if it doesn't exist.

    Best-effort: if `gh label create` fails for any reason (auth, rate
    limit, network), the batch continues and `_run_gh_pr_create`'s
    retry-without-labels path remains as a safety net.
    """
    label = f"batch-{run_id}"
    # `gh label create` exits non-zero if the label already exists,
    # which is fine. We check for existence first to avoid a noisy
    # stderr spam on every re-run.
    listing = subprocess.run(
        ["gh", "label", "list", "--search", label, "--json", "name", "--limit", "50"],
        capture_output=True,
        text=True,
    )
    if listing.returncode == 0:
        try:
            hits = json.loads(listing.stdout or "[]")
        except json.JSONDecodeError:
            hits = []
        if any(h.get("name") == label for h in hits):
            return
    create = subprocess.run(
        [
            "gh",
            "label",
            "create",
            label,
            "--color",
            "4A90E2",  # steel blue, distinct from `design` (7b61ff)
            "--description",
            f"PR created by bin/design-batch.py run-id {run_id}",
        ],
        capture_output=True,
        text=True,
    )
    if create.returncode != 0 and "already exists" not in (create.stderr or ""):
        sys.stderr.write(
            f"[batch] WARN: could not pre-create label '{label}' "
            f"(rc={create.returncode}); relying on retry fallback. "
            f"stderr: {(create.stderr or '').strip()[:200]}\n"
        )


def _run_gh_pr_create(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[Any]:
    """Create a PR, retrying without labels if GitHub lacks one."""
    pr = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    original_output = "\n".join(
        part for part in (_process_text(pr.stdout), _process_text(pr.stderr)) if part
    )
    if pr.returncode == 0 or "could not add label" not in original_output:
        return pr

    stripped: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--label":
            skip_next = True
            continue
        stripped.append(arg)

    retry = subprocess.run(stripped, cwd=str(cwd), capture_output=True, text=True)
    if retry.returncode == 0:
        sys.stderr.write(
            "[batch] WARN: gh pr create label fallback used; "
            f"original output: {original_output.strip()}\n"
        )
    return retry


def _process_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _open_progressive_pr(
    *,
    worktree: Path,
    branch: str,
    slug: str,
    opts: RunnerOptions,
    phase: str,
    body_extra: str = "",
) -> str | None:
    """Open (or return) the draft PR that represents the first artifact.

    The key distinction from `_commit_and_push` is that `design.py build`
    already committed and pushed the branch. This helper only exposes that
    branch to reviewers, as a draft, before the expensive dress/vision
    phases run.
    """
    if opts.dry_run:
        return f"https://example.test/dry-run/{slug}"
    if not opts.open_prs:
        return None

    existing = _current_pr_url(worktree, branch)
    if existing:
        return existing

    # Snap regenerates `tests/visual-baseline/heuristics-allowlist.json`
    # during `design.py build` -- which sometimes lands AFTER the
    # build's own commit has closed. Restore those tracked mutations
    # before handing the worktree to `gh pr create`, otherwise gh
    # emits `Warning: 1 uncommitted change` and (on some label error
    # paths, see below) refuses to create the PR.
    _restore_verify_mutations(worktree)

    body = (
        f"Generated by `bin/design-batch.py` progressive mode "
        f"(run-id: `{opts.run_id}`).\n\n"
        f"Worktree: `{worktree}`\n\n"
        "This draft was opened after the structural build produced a "
        "runnable branch. The content-fit, vision-review, and verification "
        "passes continue as follow-up commits on the same PR.\n"
    )
    if body_extra:
        body += f"\n---\n\n{body_extra}\n"
    # Route through `_run_gh_pr_create` so the label-not-found retry
    # kicks in when the dynamically-named `batch-<run_id>` label
    # doesn't exist on the repo yet. Without this, gh exits non-zero
    # when `--label batch-<run_id>` can't be resolved, we'd raise
    # below, and the theme is marked failed even though the branch
    # was already pushed and the theme itself was shippable.
    pr = _run_gh_pr_create(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            f"feat({slug}): bootstrap from batch {opts.run_id}",
            "--body",
            body,
            *_label_args(opts),
        ],
        cwd=worktree,
    )
    if pr.returncode != 0:
        stderr = _process_text(pr.stderr).strip()
        raise RuntimeError(f"gh pr create failed (rc={pr.returncode}): {stderr}")
    stdout = _process_text(pr.stdout).strip()
    pr_url = stdout.splitlines()[-1] if stdout else None
    _post_pr_status_comment(
        worktree=worktree,
        pr_url=pr_url,
        slug=slug,
        opts=opts,
        phase=phase,
        verify_status="pending",
        next_action="Content-fit and verification are still running on this branch.",
    )
    return pr_url


def _finalize_progressive_pr(
    *,
    worktree: Path,
    pr_url: str | None,
    slug: str,
    opts: RunnerOptions,
    verify_status: str | None,
    verify_report_path: str | None,
    rescue_summary: dict[str, Any] | None,
) -> None:
    """Move a progressive PR from draft artifact to merge candidate."""
    needs_tooling_count = (
        int(rescue_summary.get("needs_tooling_count") or 0) if rescue_summary else 0
    )
    _post_pr_status_comment(
        worktree=worktree,
        pr_url=pr_url,
        slug=slug,
        opts=opts,
        phase="verified",
        verify_status=verify_status,
        verify_report_path=verify_report_path,
        rescue_summary=rescue_summary,
        next_action=(
            "Self-healing fixed this branch, but deterministic tooling still needs "
            "to absorb the repair; PR remains draft."
            if needs_tooling_count and not opts.allow_unpromoted_factory_defects
            else (
                "Verification passed; PR marked ready and auto-merge is armed if allowed."
                if verify_status == "passed"
                else (
                    "Fix the verification failures on this PR branch; it remains draft."
                    if verify_status
                    else "Verification was skipped; PR marked ready without auto-merge proof."
                )
            )
        ),
    )
    if opts.dry_run:
        return
    if needs_tooling_count and not opts.allow_unpromoted_factory_defects:
        if pr_url:
            sys.stderr.write(
                f"[batch] {slug} has {needs_tooling_count} self-healing "
                f"factory defect(s) needing deterministic tooling; leaving "
                f"draft PR open for promotion work: {pr_url}\n"
            )
        return
    if not pr_url or (verify_status and verify_status != "passed"):
        if pr_url and verify_status and verify_status != "passed":
            sys.stderr.write(
                f"[batch] verify-theme reported '{verify_status}' on {slug}; "
                f"leaving draft PR open for fixes: {pr_url}\n"
            )
        return

    ready = subprocess.run(
        ["gh", "pr", "ready", pr_url],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    )
    if ready.returncode != 0:
        sys.stderr.write(
            f"[batch] WARN: failed to mark {pr_url} ready "
            f"(rc={ready.returncode}): {ready.stderr.strip()}\n"
        )
        return

    if not opts.arm_auto_merge:
        return
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
            "The PR is ready; a human will need to enable auto-merge "
            "or merge manually once checks are green.\n"
        )


def _post_pr_status_comment(
    *,
    worktree: Path,
    pr_url: str | None,
    slug: str,
    opts: RunnerOptions,
    phase: str,
    verify_status: str | None = None,
    verify_report_path: str | None = None,
    human_required: bool = False,
    next_action: str | None = None,
    rescue_summary: dict[str, Any] | None = None,
) -> None:
    """Best-effort visible run status for autonomous PRs.

    The batch report is machine-readable, but a reviewer usually lands on
    the PR first. Keep a compact breadcrumb there: current phase, repair
    mode, verify status, rescue usage, and the next action. This is
    intentionally non-fatal; PR creation succeeded, so a comment outage
    must not abort the batch.
    """
    if not pr_url or not opts.open_prs or opts.dry_run:
        return
    body = (
        "## Autonomous Theme Factory\n\n"
        f"- Theme: `{slug}`\n"
        f"- Run: `{opts.run_id}`\n"
        f"- Phase: `{phase}`\n"
        f"- Self-healing: `{'on' if opts.self_heal else 'off'}` "
        f"(max rounds: `{opts.max_repair_rounds}`)\n"
        f"- Verify status: `{verify_status or 'pending'}`\n"
        f"- Human input required: `{'yes' if human_required else 'no'}`\n"
        f"- Agent rescue used: `{'yes' if os.environ.get('FIFTY_AGENT_RESCUE') else 'no'}`\n"
    )
    if rescue_summary:
        needs_tooling_count = int(rescue_summary.get("needs_tooling_count") or 0)
        body += (
            f"- Recipes used: `{', '.join(rescue_summary.get('recipes_used') or []) or 'none'}`\n"
            f"- JSON repair used: `{'yes' if rescue_summary.get('json_repair_used') else 'no'}`\n"
            f"- Tool rescue used: `{'yes' if rescue_summary.get('tool_rescue_used') else 'no'}`\n"
            f"- Rescue attempts: `{rescue_summary.get('rescue_attempts') or 0}`\n"
            f"- Factory defects: `{len(rescue_summary.get('factory_defects') or [])}`\n"
            f"- Need deterministic tooling: `{needs_tooling_count}`\n"
        )
        if rescue_summary.get("human_boundary"):
            body += f"- Human boundary: `{rescue_summary['human_boundary']}`\n"
        if needs_tooling_count:
            body += "\nFactory defects needing promotion:\n"
            for defect in (rescue_summary.get("factory_defects") or [])[:5]:
                if defect.get("tooling_status") != "needs-tooling":
                    continue
                body += (
                    f"- `{defect.get('category')}` via `{defect.get('layer')}` "
                    f"-> `{defect.get('promotion_target')}`"
                )
                suggested = defect.get("suggested_files") or []
                if suggested:
                    body += f" ({', '.join(f'`{path}`' for path in suggested[:3])})"
                body += "\n"
    if verify_report_path:
        body += f"- Verify report: `{verify_report_path}`\n"
    if next_action:
        body += f"- Next action: {next_action}\n"
    subprocess.run(
        ["gh", "pr", "comment", pr_url, "--body", body],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        check=False,
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


_VERIFY_MUTABLE_FILES = ("tests/visual-baseline/heuristics-allowlist.json",)


def _restore_verify_mutations(worktree: Path) -> None:
    """Post-push verification is evidence, not a source mutation phase."""
    subprocess.run(
        ["git", "checkout", "--", *_VERIFY_MUTABLE_FILES],
        cwd=str(worktree),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _run_verify_after_push(
    worktree: Path,
    slug: str,
    opts: RunnerOptions,
) -> _VerifyBundle:
    """Invoke `bin/verify-theme.py <slug> --strict [--snap] --format markdown`
    inside the worktree after push, plus a JSON pass for a
    machine-readable record. Never raises -- verification failures are
    surfaced through the returned bundle so the caller can still finish
    opening the PR (with the failure summary in the body).

    `--snap` is on by default (gated by `opts.run_verify_snap`); see
    the rationale on `RunnerOptions.run_verify_snap`. The snap pass is
    what catches the regression class that already shipped twice on
    main (Chonk's empty hero, the my-account column collapse).
    """
    json_path = worktree / "tmp" / f"verify-{opts.run_id}-{slug}.json"
    base_args = [
        sys.executable,
        "bin/verify-theme.py",
        slug,
        "--strict",
    ]
    if opts.run_verify_snap:
        base_args.append("--snap")
    try:
        _run = subprocess.run(
            [*base_args, "--format", "json", "--out", str(json_path)],
            cwd=str(worktree),
            capture_output=True,
            text=True,
        )
    except Exception as e:
        _restore_verify_mutations(worktree)
        return _VerifyBundle(
            status="errored",
            md=f"### verify-theme: errored\n\n`{type(e).__name__}: {e}`\n",
        )
    # A non-zero rc just means "at least one phase failed" -- the
    # stdout still contains a valid JSON report in that case. Only
    # treat "no stdout at all" as a hard error.
    raw = _run.stdout.strip()
    if not raw:
        _restore_verify_mutations(worktree)
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
        _restore_verify_mutations(worktree)
        return _VerifyBundle(
            status="errored",
            md=(
                "### verify-theme: errored\n\n"
                f"Output was not JSON. stderr:\n```\n{_run.stderr.strip()}\n```\n"
            ),
        )
    overall = data.get("overall", "failed")
    md_run = subprocess.run(
        [*base_args, "--format", "markdown"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    )
    _restore_verify_mutations(worktree)
    md = md_run.stdout if md_run.stdout else ""
    return _VerifyBundle(status=overall, md=md, json_path=str(json_path))


# ---------------------------------------------------------------------------
# Budget probe (cheap, runs before each theme)
# ---------------------------------------------------------------------------


def _budget_remaining(cap_usd: float) -> float:
    """Return remaining USD before the daily cap is breached. Negative
    means we're already over."""
    spent = _vision_lib().today_spend_usd(path=BATCH_VISION_LEDGER)
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
    pre_spend = _vision_lib().today_spend_usd(path=BATCH_VISION_LEDGER)
    try:
        worktree, branch = _ensure_worktree(pre_slug, opts)
        outcome.worktree = str(worktree)
        outcome.branch = branch
        outcome.rescue_used = bool(os.environ.get("FIFTY_AGENT_RESCUE"))
        outcome.design_run_id = f"batch-{opts.run_id}-{pre_slug}"
        outcome.design_status_path = str(
            worktree / "tmp" / "runs" / outcome.design_run_id / "STATUS.md"
        )
        if opts.progressive:
            build_run_id = f"batch-{opts.run_id}-{pre_slug}-build"
            outcome.design_run_id = build_run_id
            outcome.design_status_path = str(worktree / "tmp" / "runs" / build_run_id / "STATUS.md")
            build_proc = _run_design_stage(
                "build",
                _entry_design_args(entry),
                worktree=worktree,
                opts=opts,
                pre_slug=pre_slug,
            )
            build_rescue = _read_rescue_summary(worktree, build_run_id)
            if build_proc.returncode != 0:
                slug = _resolve_slug_after_design(entry, worktree, pre_slug)
                outcome.slug = slug
                # If build reached prepublish/publish, expose the partial
                # artifact as a draft instead of leaving the operator to
                # discover a pushed-but-hidden branch.
                if opts.open_prs:
                    try:
                        outcome.pr_url = _open_progressive_pr(
                            worktree=worktree,
                            branch=branch,
                            slug=slug,
                            opts=opts,
                            phase="build-failed",
                            body_extra=(
                                "The structural build stopped before it was "
                                "green. The branch is intentionally preserved "
                                "for repair instead of being discarded."
                            ),
                        )
                    except Exception as e:
                        sys.stderr.write(
                            f"[batch] WARN: failed to open draft PR for "
                            f"{slug} after build failure: {e}\n"
                        )
                _apply_rescue_summary(outcome, build_rescue)
                outcome.status = "failed"
                outcome.error = (
                    f"bin/design.py build exited {build_proc.returncode}; "
                    f"worktree left intact at {worktree} for inspection."
                )
                outcome.next_action = (
                    f"Open `{outcome.design_status_path}` and repair the "
                    "structural build blocker on the draft branch."
                )
                return outcome

            slug = _resolve_slug_after_design(entry, worktree, pre_slug)
            outcome.slug = slug
            outcome.pr_url = _open_progressive_pr(
                worktree=worktree,
                branch=branch,
                slug=slug,
                opts=opts,
                phase="build-published",
            )

            dress_run_id = f"batch-{opts.run_id}-{pre_slug}-dress"
            outcome.design_run_id = dress_run_id
            outcome.design_status_path = str(worktree / "tmp" / "runs" / dress_run_id / "STATUS.md")
            dress_proc = _run_design_stage(
                "dress",
                [slug],
                worktree=worktree,
                opts=opts,
                pre_slug=pre_slug,
            )
            build_summary = _read_rescue_summary(worktree, build_run_id)
            dress_summary = _read_rescue_summary(worktree, dress_run_id)
            rescue_summary = _combine_rescue_summaries(build_summary, dress_summary)
            _apply_rescue_summary(outcome, rescue_summary)
            if dress_proc.returncode != 0:
                outcome.status = "failed"
                outcome.error = (
                    f"bin/design.py dress exited {dress_proc.returncode}; "
                    f"draft PR remains open at {outcome.pr_url or '<no-pr>'}."
                )
                outcome.next_action = (
                    f"Open `{outcome.design_status_path}` and push fixes to "
                    "the existing draft PR branch."
                )
                _post_pr_status_comment(
                    worktree=worktree,
                    pr_url=outcome.pr_url,
                    slug=slug,
                    opts=opts,
                    phase="dress-failed",
                    human_required=outcome.human_required,
                    next_action=outcome.next_action,
                    rescue_summary=rescue_summary,
                )
                return outcome

            verify_status: str | None = None
            verify_path: str | None = None
            if opts.run_verify and not opts.dry_run:
                bundle = _run_verify_after_push(worktree, slug, opts)
                verify_status = bundle.status
                verify_path = bundle.json_path
            outcome.verify_status = verify_status
            outcome.verify_report_path = verify_path
            _finalize_progressive_pr(
                worktree=worktree,
                pr_url=outcome.pr_url,
                slug=slug,
                opts=opts,
                verify_status=verify_status,
                verify_report_path=verify_path,
                rescue_summary=rescue_summary,
            )
            if outcome.needs_tooling_count and not opts.allow_unpromoted_factory_defects:
                outcome.status = "failed"
                outcome.error = (
                    f"{outcome.needs_tooling_count} self-healing factory defect(s) "
                    "need deterministic tooling before this PR can be marked ready."
                )
                outcome.next_action = (
                    "Promote the recorded factory defects into a check, generator, "
                    "design phase, or recipe; then rerun verification."
                )
            elif verify_status and verify_status != "passed":
                outcome.status = "failed"
                outcome.error = (
                    "bin/verify-theme.py reported failures after dress; "
                    f"see {verify_path or '<no report>'}."
                )
                outcome.next_action = (
                    "Fix the verify-theme failures on the draft PR branch, then rerun "
                    f"`python3 bin/verify-theme.py {slug} --strict --snap`."
                )
            else:
                outcome.status = "passed"
                outcome.next_action = (
                    "Draft PR was marked ready; auto-merge is armed if allowed."
                    if opts.arm_auto_merge
                    else "Review the ready PR and merge when required checks are green."
                )
            return outcome

        proc = _run_design(entry, worktree, opts, pre_slug)
        rescue_summary = _read_rescue_summary(worktree, outcome.design_run_id)
        _apply_rescue_summary(outcome, rescue_summary)
        if proc.returncode != 0:
            outcome.status = "failed"
            outcome.error = (
                f"bin/design.py exited {proc.returncode}; worktree "
                f"left intact at {worktree} for inspection."
            )
            outcome.next_action = (
                f"Open `{outcome.design_status_path}` and resume the worktree "
                "after the reported blocker is repaired."
            )
            if outcome.human_boundary:
                outcome.next_action = (
                    f"Human boundary `{outcome.human_boundary}` reached; "
                    f"open `{outcome.design_status_path}` for the recorded rescue artifact."
                )
            return outcome
        slug = _resolve_slug_after_design(entry, worktree, pre_slug)
        outcome.slug = slug
        result = _commit_and_push(worktree, branch, slug, opts, rescue_summary)
        outcome.pr_url = result.pr_url
        outcome.verify_status = result.verify_status
        outcome.verify_report_path = result.verify_report_path
        # A failing verify-theme blocks the PR from being tagged
        # "passed" in the run report. The PR still opens (with the
        # failure summary in the body) so reviewers can push fixups
        # without re-running the batch.
        if outcome.needs_tooling_count and not opts.allow_unpromoted_factory_defects:
            outcome.status = "failed"
            outcome.error = (
                f"{outcome.needs_tooling_count} self-healing factory defect(s) "
                "need deterministic tooling before this PR can be marked ready."
            )
            outcome.next_action = (
                "Promote the recorded factory defects into a check, generator, "
                "design phase, or recipe; then rerun verification."
            )
        elif result.verify_status == "failed":
            outcome.status = "failed"
            outcome.error = (
                "bin/verify-theme.py reported failures after push; "
                f"see {result.verify_report_path or '<no report>'}."
            )
            outcome.next_action = (
                "Fix the verify-theme failures on the PR branch, then rerun "
                f"`python3 bin/verify-theme.py {slug} --strict --snap`."
            )
        else:
            outcome.status = "passed"
            outcome.next_action = (
                "Wait for required GitHub checks; auto-merge is armed if allowed."
                if opts.arm_auto_merge
                else "Review the PR and merge when required checks are green."
            )
        return outcome
    except Exception as e:
        outcome.status = "failed"
        outcome.error = f"{type(e).__name__}: {e}"
        outcome.next_action = (
            "Inspect the worktree and batch report; rerun with --retry-failed "
            "after the blocker is resolved."
        )
        return outcome
    finally:
        outcome.elapsed_s = round(time.monotonic() - started, 1)
        outcome.vision_cost_usd = round(
            _vision_lib().today_spend_usd(path=BATCH_VISION_LEDGER) - pre_spend,
            4,
        )
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
        "--no-verify-snap",
        action="store_true",
        help=(
            "Run the post-push `bin/verify-theme.py` WITHOUT --snap. "
            "Default is to include --snap so the verify pass re-shoots "
            "the theme and runs every snap-backed gate (placeholder "
            "images, my-account dashboard layout, vision review). "
            "Disable for fast iteration on the batch orchestrator only "
            "-- the regression class --snap catches has shipped twice."
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
        "--arm-auto-merge-on-failure",
        action="store_true",
        help=(
            "Arm GitHub auto-merge even when verify-theme reports "
            "failures or errors. Default behaviour leaves auto-merge "
            "OFF on a non-passing verify so a human reviewer is forced "
            "to look at the failing gate before the PR can land. Only "
            "use this for explicit rescue runs where you've already "
            "decided the failures are acceptable."
        ),
    )
    p.add_argument(
        "--allow-unpromoted-factory-defects",
        action="store_true",
        help=(
            "Do not keep draft PRs blocked when self-healing fixed a "
            "theme with JSON/tool rescue but the fix has not yet been "
            "promoted into deterministic tooling. Default is to block "
            "ready/auto-merge so recurring defects are added to the "
            "factory before shipping."
        ),
    )
    p.add_argument(
        "--no-self-heal",
        action="store_true",
        help=(
            "Call bin/design.py directly instead of the default "
            "bin/design-watch.py self-healing wrapper. Use only when "
            "debugging the watcher itself."
        ),
    )
    p.add_argument(
        "--single-shot",
        action="store_true",
        help=(
            "Use the legacy all-in-one design.py run and open the PR only "
            "after every phase succeeds. Default is progressive mode: "
            "`design.py build` opens a draft PR first, then `design.py dress` "
            "adds content/vision fixes on the same branch."
        ),
    )
    p.add_argument(
        "--max-repair-rounds",
        type=int,
        default=3,
        help=(
            "Maximum design_unblock.py repair/resume rounds per theme "
            "when self-healing is enabled. Default: 3."
        ),
    )
    p.add_argument(
        "--unblock-dry-run",
        action="store_true",
        help=(
            "Let design-watch.py emit repair packets but stop before "
            "calling the LLM. Useful for rehearsal runs without API spend."
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


def _maybe_reexec_under_top_watch(
    argv: list[str],
    *,
    args: argparse.Namespace,
    run_id: str,
) -> None:
    """Put real batch runs under design-watch's top-level kill/stall guard.

    Per-theme work already goes through design-watch, but launching
    design-batch.py directly used to leave the batch orchestrator itself
    unsupervised. This re-exec makes the safe path the default CLI path
    while preserving in-process tests and dry-run planning.
    """
    if args.dry_run or os.environ.get(TOP_WATCH_ENV) == "1":
        return

    forwarded = list(argv)
    if not args.run_id:
        forwarded.extend(["--run-id", run_id])

    env = os.environ.copy()
    env[TOP_WATCH_ENV] = "1"
    cmd = [
        sys.executable,
        str(ROOT / "bin" / "design-watch.py"),
        "--run-id",
        f"batch-{run_id}-watch",
        "--no-auto-unblock",
        "--max-elapsed-seconds",
        str(_top_watch_max_elapsed_seconds(args)),
        "--script",
        str(ROOT / "bin" / "design-batch.py"),
        "--",
        *forwarded,
    ]
    os.execve(sys.executable, cmd, env)


def _top_watch_max_elapsed_seconds(args: argparse.Namespace) -> int:
    """Return a batch-sized wall-clock cap for the top-level watchdog.

    Per-theme design-watch children keep the tight stall guard. The
    parent batch watcher needs a larger wall-clock budget because a
    single theme can legitimately spend 20+ minutes in screenshot and
    vision review while still emitting progress.
    """

    theme_count = 1
    concept_slugs = getattr(args, "concept_slugs", "") or ""
    if concept_slugs:
        theme_count = len([slug for slug in concept_slugs.split(",") if slug.strip()])
    elif getattr(args, "limit", None):
        theme_count = max(1, int(args.limit))
    elif getattr(args, "manifest", None):
        try:
            raw = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            theme_count = max(1, len(raw.get("themes") or []))
        except (OSError, json.JSONDecodeError, TypeError):
            theme_count = 1

    concurrency = max(1, min(int(getattr(args, "concurrency", 1) or 1), HARD_CONCURRENCY_CAP))
    waves = max(1, (theme_count + concurrency - 1) // concurrency)
    return min(8 * 60 * 60, max(90 * 60, waves * 90 * 60 + 15 * 60))


def _resolve_concurrency(cli: int | None, manifest: dict[str, Any]) -> int:
    raw = cli if cli is not None else int(manifest.get("concurrency", 1))
    if raw < 1:
        raise SystemExit("error: concurrency must be >= 1")
    if raw > HARD_CONCURRENCY_CAP:
        print(
            f"warn: concurrency {raw} exceeds hard cap {HARD_CONCURRENCY_CAP}; clamping.",
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
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(raw_argv)
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
    run_id = _resolve_run_id(args.run_id)
    if argv is None:
        _maybe_reexec_under_top_watch(raw_argv, args=args, run_id=run_id)

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

    concurrency = _resolve_concurrency(args.concurrency, manifest_opts)
    daily_cap = args.budget_usd if args.budget_usd is not None else _vision_default_budget()
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
        run_verify_snap=not args.no_verify_snap,
        arm_auto_merge=not args.no_auto_merge,
        arm_auto_merge_on_failure=args.arm_auto_merge_on_failure,
        self_heal=not args.no_self_heal,
        max_repair_rounds=args.max_repair_rounds,
        unblock_dry_run=args.unblock_dry_run,
        progressive=not args.single_shot,
        fresh_worktree=args.no_resume,
        allow_unpromoted_factory_defects=args.allow_unpromoted_factory_defects,
    )

    print(
        f"[batch] run-id={run_id} themes={len(entries)} "
        f"concurrency={concurrency} daily-cap=${daily_cap:.2f} "
        f"worktree-parent={worktree_parent} dry-run={args.dry_run} "
        f"self-heal={not args.no_self_heal} "
        f"mode={'progressive' if not args.single_shot else 'single-shot'}",
        file=sys.stderr,
    )

    # Pre-create the per-run PR label so `gh pr create --label
    # batch-<run_id>` doesn't fail the first N-1 PRs with
    # `could not add label: '...' not found`. The retry path in
    # `_run_gh_pr_create` strips the label on failure -- which works
    # but loses every label on the PR (including the `design` label
    # that `.github/workflows/vision-review.yml` gates on). Creating
    # the label up-front means the first PR gets the right labels AND
    # the retry path only fires for genuine gh outages, not a
    # configuration gap. Best-effort; label creation failures just log.
    if opts.open_prs and opts.label_run_id and not opts.dry_run:
        _ensure_batch_label(run_id)

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
        f"[batch] done. report: {report_path}\n[batch] totals: {json.dumps(report.totals)}",
        file=sys.stderr,
    )
    # Exit non-zero if any theme failed so CI/cron can notice.
    if report.totals.get("failed", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
