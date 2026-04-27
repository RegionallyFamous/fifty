"""Static-inspection tests for `bin/design-batch.py`.

The script shells out to `git`, `gh`, and `bin/design.py`, which makes
full end-to-end tests prohibitively expensive and flaky. Instead, we
inspect the source text for the specific wiring that lands new themes
hands-off on `main`. Each assertion corresponds to a documented bug
class that previously required a human click.

### Bug class #1: batch PRs open without auto-merge armed.

Before 2026-04-27 the batch runner called `gh pr create` and stopped.
Every PR opened with auto-merge OFF, so even after the static gate,
vision review, and first-baseline all went green, the PR sat at
MERGEABLE forever until someone clicked "enable auto-merge" N times
(once per theme in the batch). That defeats the whole "walk away"
premise of `--from-concepts --count N`. The fix is a post-create
`gh pr merge <url> --auto --squash` call so each PR lands the moment
it's fully green. We squash-merge to keep main linear
(`setup-branch-protection.sh` enforces `required_linear_history: true`;
a merge-commit here would be rejected by branch protection).

### Bug class #2: the opt-out must still exist.

An agent debugging the pipeline, or a Proprietor who wants to eyeball
each theme before it ships, still needs a way to open PRs without
arming auto-merge. The `--no-auto-merge` flag + `arm_auto_merge`
option are that escape hatch. The default is ON because the whole
point of the batch runner is hands-off operation.

### Bug class #3: a transient `gh` failure must not fail the PR.

If `gh pr merge --auto` fails (auto-merge disabled at the repo level,
transient rate limit, etc.) the PR itself is still valid — only the
auto-merge arming is degraded. The call site must print a warning
and return the PR URL, NOT raise. A human can then arm auto-merge
manually; the alternative (raising) would abort the batch mid-run and
leave the remaining N-1 themes unshipped over a cosmetic failure.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bin" / "design-batch.py"


@pytest.fixture(scope="module")
def script_text() -> str:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Bug class #1 — gh pr merge --auto --squash is called after gh pr create
# ---------------------------------------------------------------------------


def test_runner_options_has_arm_auto_merge_field(script_text: str) -> None:
    """`RunnerOptions.arm_auto_merge` must exist and default to True.

    If the field is missing, the default-ON behavior the batch runner
    advertises is not wired through. If it defaults to False, the
    default batch invocation silently degrades to manual click-to-merge
    (exactly the behavior this test exists to prevent).
    """
    assert "arm_auto_merge: bool = True" in script_text, (
        "RunnerOptions.arm_auto_merge is missing or doesn't default to True. "
        "Without the default the 'walk away' batch mode falls back to "
        "per-PR human clicks even when FIFTY_AUTO_PAT + branch protection "
        "are configured correctly."
    )


def test_commit_and_push_calls_gh_pr_merge_auto_squash(script_text: str) -> None:
    """After `gh pr create`, the runner MUST attempt to arm auto-merge.

    We assert three things together so the three-way invariant is
    expressed in one failure message rather than in three overlapping
    tests that would all fire from the same regression:

      * The literal call `gh`, `pr`, `merge` appears in the source.
      * `--auto` is passed (so GitHub auto-merges on green).
      * `--squash` is passed (so main stays linear — branch protection
        sets `required_linear_history: true`; a merge commit would be
        rejected, stalling the PR at MERGEABLE).

    We also sanity-check that the call uses the PR URL returned from
    `gh pr create` (variable `pr_url`), not a hardcoded placeholder.
    """
    pattern = re.compile(
        r'"gh",\s*"pr",\s*"merge",\s*pr_url,\s*"--auto",\s*"--squash"',
        re.MULTILINE,
    )
    assert pattern.search(script_text), (
        "bin/design-batch.py does not call "
        "`gh pr merge <pr_url> --auto --squash` after `gh pr create`. "
        "Without this, every batch PR opens with auto-merge OFF and "
        "stalls at MERGEABLE until a human clicks `Enable auto-merge` "
        "N times. The call must pass --auto (so GitHub fires the merge "
        "on green) AND --squash (so main's history stays linear per "
        "setup-branch-protection.sh)."
    )


def test_auto_merge_is_guarded_by_arm_auto_merge_flag(script_text: str) -> None:
    """The arm step MUST be behind `if opts.arm_auto_merge and pr_url:`.

    Two reasons:

      * `--no-auto-merge` must be able to disable it (otherwise the
        escape hatch isn't actually wired).

      * `pr_url` can be None (e.g. if `gh pr create` produced empty
        stdout on a flaky network call). Calling `gh pr merge None`
        would crash the subprocess and abort the batch mid-run.
    """
    assert "if opts.arm_auto_merge and pr_url:" in script_text, (
        "The auto-merge arming block must be guarded by "
        "`if opts.arm_auto_merge and pr_url:`. Without the opt-out "
        "guard, `--no-auto-merge` has no effect. Without the `pr_url` "
        "guard, a flaky `gh pr create` stdout raises inside `subprocess.run` "
        "and aborts the whole batch."
    )


# ---------------------------------------------------------------------------
# Bug class #2 — --no-auto-merge CLI flag is wired end-to-end
# ---------------------------------------------------------------------------


def test_cli_exposes_no_auto_merge_flag() -> None:
    """`--help` must advertise the `--no-auto-merge` flag.

    Running `--help` exercises the argparse wiring end-to-end (flag
    declared, help text present, no import errors in the script). A
    flag that's declared but not included in --help output is a flag
    the user can't discover.
    """
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "--no-auto-merge" in r.stdout, (
        "`design-batch.py --help` does not mention `--no-auto-merge`. "
        "Either the argparse flag is missing or it has no help text; "
        "either way, operators cannot discover the escape hatch."
    )


def test_cli_flag_is_plumbed_to_runner_options(script_text: str) -> None:
    """The CLI `--no-auto-merge` must flip `arm_auto_merge` to False.

    A flag that parses but isn't wired into `RunnerOptions` is dead
    code — argparse accepts it, the user thinks it's off, but the
    runner still arms auto-merge. We check both halves of the
    plumbing:

      * `args.no_auto_merge` materializes from argparse.
      * It's inverted into `arm_auto_merge=not args.no_auto_merge`
        when building RunnerOptions.
    """
    assert "arm_auto_merge=not args.no_auto_merge" in script_text, (
        "`--no-auto-merge` is declared but not wired into RunnerOptions. "
        "The batch runner will advertise the flag in --help but ignore it "
        "at runtime — every PR will still arm auto-merge. Wire it as "
        "`arm_auto_merge=not args.no_auto_merge` in the RunnerOptions "
        "constructor."
    )


# ---------------------------------------------------------------------------
# Bug class #3 — gh pr merge failure must warn, not raise
# ---------------------------------------------------------------------------


def test_auto_merge_failure_is_best_effort(script_text: str) -> None:
    """A non-zero `gh pr merge` exit MUST print a warning, not raise.

    Failure modes we need to tolerate without aborting the batch:

      * Auto-merge disabled at the repo level (the `gh` call fails
        with `GraphQL: Pull request auto-merge is not allowed`).
      * Transient rate limit or network blip.
      * Missing `gh` auth context (degrades to a clear error message
        rather than silently opening zero PRs).

    In all three cases the PR itself was created successfully; only
    the arming step failed. Raising here would leave the remaining
    themes in the batch unprocessed over a cosmetic problem. We
    assert the code writes a warning to stderr and continues by
    checking for the `WARN:` prefix and the absence of `raise` in the
    same block.
    """
    # Isolate the auto-merge block — from the guard to the next
    # `return _CommitAndPushResult(...)`.
    m = re.search(
        r"if opts\.arm_auto_merge and pr_url:(.*?)return _CommitAndPushResult\(",
        script_text,
        re.DOTALL,
    )
    assert m, (
        "Can't locate the auto-merge block in bin/design-batch.py. "
        "Either the guard wording changed or the block was deleted."
    )
    block = m.group(1)
    assert "WARN" in block, (
        "The auto-merge failure path must emit a `WARN:` diagnostic to "
        "stderr so the operator sees what went wrong. Silent degradation "
        "looks like the arm succeeded, and the Proprietor spends 10 "
        "minutes wondering why auto-merge isn't firing."
    )
    assert "raise" not in block, (
        "The auto-merge block must NOT raise on `gh pr merge` failure. "
        "A transient `gh` failure or a repo with auto-merge disabled "
        "would abort the batch mid-run over a cosmetic problem — the "
        "PR itself is still valid. Log a warning and continue."
    )
