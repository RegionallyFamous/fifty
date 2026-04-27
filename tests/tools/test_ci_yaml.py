r"""Static guards for GitHub Actions workflow YAML.

These catch classes of bugs that would otherwise only surface on CI and
(when they fire on a skip-the-auto-label path like the 2026-04-27
vision-review.yml regression) silently break downstream automation
without any obvious error.

Covered bug classes:

1. **YAML-scalar line continuation bug.** A `run:` step written as a
   plain scalar with trailing `\` line continuations gets YAML-folded
   into a single line where `\<space>` survives as a literal
   backslash+space. Bash then interprets `\<space>` as an escaped
   literal space character INSIDE one argument — not a word separator —
   so argparse sees zero args and the step crashes with "missing
   required arguments". Fix: use `run: |` (literal block scalar) so
   each logical line is a real newline and `\` is a shell
   line-continuation, not a YAML escape. Documented in the comment
   block above the render step in `.github/workflows/vision-review.yml`.

2. **Missing `timeout-minutes`.** An unbounded step can hang a runner
   for the GH-default 360 minutes before the scheduler kills it,
   poisoning every subsequent PR. Every `jobs.<job>` must declare
   `timeout-minutes`.

Add new bug classes here as we find them. Each one is one ~10-line
test that runs in ~50ms and is impossible for a human to forget
(unlike a convention documented only in a PR description).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def _iter_steps(wf_path: Path):
    """Yield `(job_name, step_index, step_name, step_dict)` for every
    step in the workflow, in document order. Skips matrix/gate jobs
    that have no `steps` key."""
    data = yaml.safe_load(wf_path.read_text())
    if not isinstance(data, dict):
        return
    for job_name, job_def in (data.get("jobs") or {}).items():
        if not isinstance(job_def, dict):
            continue
        for idx, step in enumerate(job_def.get("steps") or []):
            if not isinstance(step, dict):
                continue
            yield job_name, idx, step.get("name", f"<step[{idx}]>"), step


@pytest.mark.parametrize("wf_path", WORKFLOWS, ids=lambda p: p.name)
def test_run_step_has_no_yaml_line_continuation_bug(wf_path: Path) -> None:
    r"""Every `run:` value must either be single-line OR a literal block
    scalar (whose parsed value contains real newlines). A plain scalar
    with trailing `\` on source lines gets folded into `"... \  ...
    \  ..."` — a one-line string with literal backslash-space
    sequences — and bash then eats the `\<space>` as an escaped space
    inside one argument. The fix is `run: |` (literal block scalar).

    Detection heuristic:
      - If the parsed `run` string contains a newline, it's a literal
        block scalar (or a folded `>` scalar spanning multiple lines).
        Either way, bash sees proper newlines + real `\` continuation,
        which is correct.
      - If it's a single line AND contains `\ ` (backslash followed
        by space), that's the bug: the `\` came from a trailing
        backslash in the source whose newline was then folded out.
    """
    offenders: list[str] = []
    for job, idx, name, step in _iter_steps(wf_path):
        run = step.get("run")
        if not isinstance(run, str):
            continue
        if "\n" in run:
            continue  # block scalar — fine
        if re.search(r"\\ ", run):
            offenders.append(
                f"{job}:step[{idx}]({name}) -> has `\\ ` "
                f"in single-line run: use `run: |` (literal block scalar) "
                f"for multi-line shell commands."
            )
    assert not offenders, (
        f"{wf_path.name} has run steps with the YAML-line-continuation bug.\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("wf_path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_timeout_minutes(wf_path: Path) -> None:
    """Every job must declare `timeout-minutes`. GH Actions defaults to
    360 minutes, so an unbounded step that hangs (Playwright stall,
    Playground boot race, network wedge) burns 6 hours of runner time
    AND silently poisons the scheduler until it finally times out.

    Reusable workflow calls (`uses:` at job level, no `steps:`) are
    exempt — their timeout is defined in the callee.
    """
    data = yaml.safe_load(wf_path.read_text())
    if not isinstance(data, dict):
        return
    missing: list[str] = []
    for job_name, job_def in (data.get("jobs") or {}).items():
        if not isinstance(job_def, dict):
            continue
        if "uses" in job_def and "steps" not in job_def:
            continue  # reusable workflow call
        if job_def.get("timeout-minutes") is None:
            missing.append(job_name)
    assert not missing, (
        f"{wf_path.name} has jobs without `timeout-minutes`: {', '.join(missing)}. "
        "Unbounded jobs can hang for the GH default 360 minutes."
    )
