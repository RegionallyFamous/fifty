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

3. **Label-event self-retrigger loop.** A workflow that triggers on
   `pull_request.types: [labeled, ...]` AND itself adds a label
   (e.g., `vision-reviewed` by `vision-review.yml`) will re-run on
   the label it just added unless its gate job filters by
   `github.event.label.name`. On 2026-04-27 this drove vision-
   review.yml to a steady 2-runs-per-push state, and dragged
   check.yml along because check.yml also listens on `labeled`
   without job-level skips. The fix is to filter label events
   explicitly:
     * vision-review.yml gate: `if: action != 'labeled' || label.name == 'design'`
     * check.yml heavy jobs:   `if: action != 'labeled'` (they're label-independent)
   This test enforces that any workflow whose `on.pull_request.types`
   includes `labeled` has at least one job-level `if:` that mentions
   `github.event.action` or `github.event.label.name`. A workflow
   that listens on `labeled` but runs every job unconditionally is
   the exact shape of the bug.

4. **Broken clean-critique label contract.** `vision-review.yml`'s
   "clean critique" labelling step MUST add BOTH `vision-reviewed`
   (satisfies `check.yml.vision-review-gate`) AND `ready-for-baseline`
   (triggers `first-baseline.yml`, which generates
   `tests/visual-baseline/<theme>/` and flips `readiness.stage` to
   `shipping`). Dropping `ready-for-baseline` is the exact shape of
   the 2026-04-27 end-to-end automation stall: vision pass goes green,
   check.yml's vision-gate passes, but no one tells `first-baseline.yml`
   to do its job, and the PR sits at `stage: incubating` forever
   waiting on a human label click. Dropping `vision-reviewed` is the
   symmetric failure that blocked basalt for the first batch. Both
   labels must land atomically.

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


@pytest.mark.parametrize("wf_path", WORKFLOWS, ids=lambda p: p.name)
def test_labeled_trigger_has_label_name_filter(wf_path: Path) -> None:
    """If the workflow listens on `pull_request.types: [labeled, ...]`
    AND any job in that workflow adds a label (via `gh pr edit
    --add-label` or `actions/github-script`), at least one job-level
    `if:` must reference `github.event.action` or
    `github.event.label.name`. Otherwise the workflow re-triggers
    itself whenever it labels a PR, producing the 2-runs-per-push
    loop that drove the 2026-04-27 CI-looping regression.

    We approximate the "adds a label" check with a regex scan for
    `add-label` or `addLabels` anywhere in the workflow body; that
    catches both `gh pr edit --add-label` and the JS-API form used by
    some actions. If the workflow has neither of those strings, it
    can't self-trigger via labels and this rule doesn't apply.
    """
    raw = wf_path.read_text()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        return
    triggers = data.get(True) or data.get("on") or {}
    pr_trigger = triggers.get("pull_request") if isinstance(triggers, dict) else None
    if not isinstance(pr_trigger, dict):
        return
    types = pr_trigger.get("types") or []
    if "labeled" not in types:
        return  # doesn't listen on label events; rule is inapplicable
    if "add-label" not in raw and "addLabels" not in raw:
        return  # doesn't add labels; no self-trigger loop possible
    # This workflow both listens on label events AND adds labels.
    # It must have a job-level filter that inspects the event action
    # or the label name.
    has_filter = False
    for _job_name, job_def in (data.get("jobs") or {}).items():
        if not isinstance(job_def, dict):
            continue
        cond = job_def.get("if")
        if isinstance(cond, str) and (
            "github.event.action" in cond or "github.event.label.name" in cond
        ):
            has_filter = True
            break
    assert has_filter, (
        f"{wf_path.name} listens on `pull_request.types: [labeled, ...]` AND adds "
        "labels, but no job uses `if:` with `github.event.action` or "
        "`github.event.label.name` to filter out self-triggers. Without this "
        "filter the workflow re-runs every time it labels a PR."
    )


def test_vision_review_adds_both_labels_atomically() -> None:
    """`vision-review.yml`'s clean-critique labelling step must add
    BOTH `vision-reviewed` and `ready-for-baseline`.

    `vision-reviewed` satisfies `check.yml.vision-review-gate` (the
    required check that blocks new-theme PRs until a design pass has
    happened). `ready-for-baseline` is the label
    `first-baseline.yml` listens for — it's what kicks off the
    automated baseline generation + `readiness.stage → shipping`
    flip. Adding only one half gets the PR stuck: either the gate
    stays red (missing `vision-reviewed`) or the gate clears but
    baselines never generate (missing `ready-for-baseline`).

    We assert both label names appear inside a single `gh pr edit
    ... --add-label ...` command so the labels land in ONE webhook
    write. Splitting them across two `gh pr edit` calls would
    technically work but doubles the `labeled`-event fan-out; one
    atomic command is both cheaper AND the shape the downstream
    filters in vision-review.yml's gate and first-baseline.yml's
    setup expect.
    """
    wf = REPO_ROOT / ".github" / "workflows" / "vision-review.yml"
    raw = wf.read_text()
    # Find every `gh pr edit ... --add-label ...` invocation, reading
    # forward across shell line-continuations (trailing `\` on a line
    # joins it with the next). Returning the joined text so a regex
    # test on it sees both labels when they're split across lines by
    # a `run: |` block scalar.
    joined_cmds: list[str] = []
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith("gh pr edit"):
            # Accumulate continuations.
            buf = [lines[i].rstrip()]
            while buf[-1].endswith("\\"):
                buf[-1] = buf[-1][:-1]  # strip trailing `\`
                i += 1
                if i >= len(lines):
                    break
                buf.append(lines[i].rstrip())
            joined_cmds.append(" ".join(buf))
        i += 1
    found_pair = any(
        "--add-label vision-reviewed" in c and "--add-label ready-for-baseline" in c
        for c in joined_cmds
    )
    assert found_pair, (
        "vision-review.yml must add BOTH `vision-reviewed` AND "
        "`ready-for-baseline` in a single `gh pr edit --add-label ...` "
        "call. Adding only one half stalls the new-theme automation: "
        "either check.yml's vision-review-gate stays red or "
        "first-baseline.yml never runs. "
        f"Observed `gh pr edit` invocations: {joined_cmds!r}"
    )
    # Belt-and-suspenders: also confirm the step body still keys off
    # the vision-review.exit files (i.e. we don't blanket-label every
    # run — the labels are gated on a clean critique). Without this
    # guard a well-intended refactor could move the labelling out of
    # the exit-code-checking block and start labelling failed
    # critiques, which would freeze a broken design into the
    # baseline set.
    assert "vision-review.exit" in raw, (
        "vision-review.yml must gate labelling on `vision-review.exit` "
        "files (zero exit = clean critique). A blanket label on every "
        "run would freeze broken designs into the baseline tree."
    )
