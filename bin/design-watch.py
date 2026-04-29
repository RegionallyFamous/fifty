#!/usr/bin/env python3
"""Human-friendly progress runner for ``bin/design.py``.

The design pipeline is intentionally thorough, but raw logs make long runs
feel opaque. This wrapper keeps the underlying command unchanged while adding
plain-language heartbeats, stall notices, and a machine-readable run summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

VIEWPORTS = {"mobile", "tablet", "desktop", "wide"}

PHASE_LABELS = {
    "validate": "checking the theme plan",
    "clone": "creating the theme files",
    "apply": "applying colors, fonts, and layout notes",
    "contrast": "checking that text stays readable",
    "seed": "copying demo content and product data",
    "sync": "refreshing the Playground setup",
    "photos": "creating product and category images",
    "microcopy": "rewriting store wording for this theme",
    "frontpage": "making the homepage layout distinct",
    "index": "updating the theme file map",
    "prepublish": "publishing demo content so screenshots can load it",
    "snap": "capturing screenshots",
    "vision-review": "reviewing screenshots",
    "baseline": "saving screenshot baselines",
    "screenshot": "building the WordPress admin preview image",
    "check": "running quality checks",
    "report": "summarizing screenshot findings",
    "redirects": "updating demo links",
    "commit": "committing results",
    "publish": "pushing the branch",
}

FAILURE_MESSAGES: list[tuple[str, str, str]] = [
    (
        "placeholder",
        "Some product/category images are missing, so WooCommerce is showing grey placeholder tiles.",
        "Check the theme's playground/content image maps and playground/images files.",
    ),
    (
        "Product photographs are visually distinct",
        "Two product photos look too similar; shoppers may think they are the same item.",
        "Regenerate or replace the named duplicate product photo.",
    ),
    (
        "Hover/focus states have legible",
        "Some text becomes too hard to read when a shopper hovers or focuses it.",
        "Adjust the hover/focus text or background color in theme.json styles.css.",
    ),
    (
        "color-contrast",
        "Some text is too hard to read against its background.",
        "Use a higher-contrast palette token for the affected text or background.",
    ),
    (
        "Pattern + heading microcopy distinct",
        "This theme still contains copied headings or pattern wording from another theme.",
        "Rewrite the named pattern/template text in this theme's voice.",
    ),
    (
        "All rendered text distinct",
        "This theme still contains copied storefront wording from another theme.",
        "Rewrite the named text fragments or add a real wayfinding allowlist only if appropriate.",
    ),
    (
        "Snap evidence is fresh",
        "The source files changed after the latest screenshot evidence.",
        "Re-run the screenshot step so checks read current evidence.",
    ),
    (
        "Recent snaps carry no serious",
        "Recent screenshots found serious page issues.",
        "Open the reported snap review and fix the listed route/viewport cells.",
    ),
]


@dataclass
class CheckFailure:
    title: str
    detail: str = ""
    summary: str = ""
    next_action: str = ""


@dataclass
class WatchState:
    run_id: str
    started_at: float
    command: list[str]
    cwd: str
    slug: str = "theme"
    phases: list[str] = field(default_factory=list)
    current_phase: str = "starting"
    phase_started_at: float = 0.0
    phase_durations: dict[str, float] = field(default_factory=dict)
    total_cells: int = 0
    completed_cells: int = 0
    snap_error_cells: int = 0
    snap_warn_cells: int = 0
    vision_total: int = 0
    vision_completed: int = 0
    vision_cached: int = 0
    vision_prefiltered: int = 0
    vision_errored: int = 0
    vision_current: str = ""
    vision_last: str = ""
    vision_findings: int = 0
    check_failures: list[CheckFailure] = field(default_factory=list)
    no_strict: bool = False
    saw_no_strict_warning: bool = False
    final_status: str | None = None
    returncode: int | None = None
    last_line: str = ""
    last_output_at: float = 0.0
    last_heartbeat_at: float = 0.0
    last_stall_at: float = 0.0
    last_status_label: str = "Working"
    last_status_message: str = "Starting pipeline run."
    repair_attempts: list[dict[str, Any]] = field(default_factory=list)
    factory_defects: list[dict[str, Any]] = field(default_factory=list)
    repair_active: bool = False
    repair_round: int = 0
    repair_last_layer: str = ""
    repair_last_decision: str = ""
    repair_last_reason: str = ""
    repair_last_touched: list[str] = field(default_factory=list)
    repair_stop_reason: str = ""


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def titlecase_slug(slug: str) -> str:
    if not slug or slug == "theme":
        return "The theme"
    return slug.replace("-", " ").title()


def phase_index(state: WatchState) -> str:
    if state.current_phase in state.phases:
        return f"{state.phases.index(state.current_phase) + 1}/{len(state.phases)}"
    if state.phases:
        return f"?/{len(state.phases)}"
    return "?"


def explain_failure(title: str, detail: str = "") -> tuple[str, str]:
    haystack = f"{title}\n{detail}"
    for needle, summary, next_action in FAILURE_MESSAGES:
        if needle.lower() in haystack.lower():
            return summary, next_action
    return title, "Open the check output above for the affected file or route."


def start_phase(state: WatchState, phase: str, now: float) -> bool:
    if phase == state.current_phase:
        return False
    if state.current_phase and state.current_phase != "starting" and state.phase_started_at:
        state.phase_durations[state.current_phase] = state.phase_durations.get(
            state.current_phase, 0.0
        ) + max(0.0, now - state.phase_started_at)
    state.current_phase = phase
    state.phase_started_at = now
    return True


def parse_line(state: WatchState, line: str, now: float) -> list[dict[str, Any]]:
    """Update state from one output line and return structured events."""
    events: list[dict[str, Any]] = []
    clean = line.rstrip("\n")
    state.last_line = clean
    state.last_output_at = now

    m = re.search(r"design\.py: running phases (.+) for `([^`]+)`", clean)
    if m:
        state.phases = [part.strip() for part in m.group(1).split("->")]
        state.slug = m.group(2)
        if state.phases and start_phase(state, state.phases[0], now):
            events.append({"type": "phase_start", "phase": state.current_phase})
        events.append({"type": "run_plan", "phases": state.phases, "slug": state.slug})
        return events

    m = re.match(r"\s*\[([a-z0-9-]+)\]\s+", clean)
    if m:
        phase = m.group(1)
        if phase not in PHASE_LABELS:
            return events
        if start_phase(state, phase, now):
            events.append({"type": "phase_start", "phase": phase})
        return events

    m = re.search(r"Shooting \d+ theme\(s\) across \d+ viewport\(s\) = (\d+) screenshot", clean)
    if m:
        state.total_cells = int(m.group(1))
        if start_phase(state, "snap", now):
            events.append({"type": "phase_start", "phase": "snap"})
        events.append({"type": "snap_total", "total": state.total_cells})
        return events

    m = re.search(r"== reviewing (\d+) PNGs for ([a-z0-9-]+)", clean)
    if m:
        state.vision_total = int(m.group(1))
        state.slug = m.group(2)
        if start_phase(state, "vision-review", now):
            events.append({"type": "phase_start", "phase": "vision-review"})
        events.append({"type": "vision_total", "total": state.vision_total})
        return events

    m = re.match(r">>\s+reviewing\s+(\d+)/(\d+)\s+([a-z]+)/([a-z0-9][a-z0-9.-]*)", clean)
    if m:
        state.vision_completed = max(0, int(m.group(1)) - 1)
        state.vision_total = int(m.group(2))
        state.vision_current = f"{m.group(3)}/{m.group(4)}"
        if start_phase(state, "vision-review", now):
            events.append({"type": "phase_start", "phase": "vision-review"})
        events.append(
            {
                "type": "vision_cell_start",
                "current": state.vision_current,
                "completed": state.vision_completed,
                "total": state.vision_total,
            }
        )
        return events

    m = re.match(
        r"\s*(?:=|\.\.|!!|-)?\s*([a-z]+)/([a-z0-9][a-z0-9.-]*)\s+"
        r"\[(reviewed|cached|prefiltered|errored|skipped)\]\s+(\d+)\s+findings",
        clean,
    )
    if m:
        status = m.group(3)
        state.vision_completed += 1
        state.vision_last = f"{m.group(1)}/{m.group(2)} [{status}]"
        state.vision_findings += int(m.group(4))
        if status == "cached":
            state.vision_cached += 1
        elif status == "prefiltered":
            state.vision_prefiltered += 1
        elif status == "errored":
            state.vision_errored += 1
        if start_phase(state, "vision-review", now):
            events.append({"type": "phase_start", "phase": "vision-review"})
        events.append(
            {
                "type": "vision_cell_done",
                "cell": state.vision_last,
                "status": status,
                "completed": state.vision_completed,
                "total": state.vision_total,
                "findings": int(m.group(4)),
            }
        )
        return events

    m = re.match(r"\s*(mobile|tablet|desktop|wide)\s+([a-z0-9][a-z0-9.-]*)\s+", clean)
    if m:
        state.completed_cells += 1
        events.append(
            {
                "type": "snap_cell",
                "viewport": m.group(1),
                "route": m.group(2),
                "completed": state.completed_cells,
                "total": state.total_cells,
            }
        )
        return events

    m = re.search(r"flags:\s+(\d+)\s+error\s+/\s+(\d+)\s+warn", clean)
    if m:
        errors = int(m.group(1))
        warns = int(m.group(2))
        if errors:
            state.snap_error_cells += 1
        elif warns:
            state.snap_warn_cells += 1
        events.append({"type": "snap_flags", "errors": errors, "warnings": warns})
        return events

    m = re.search(r"\[FAIL\]\s+\[[^\]]+\]\s+(.+)", clean)
    if m:
        title = m.group(1).strip()
        summary, next_action = explain_failure(title)
        failure = CheckFailure(title=title, summary=summary, next_action=next_action)
        state.check_failures.append(failure)
        events.append({"type": "check_fail", **asdict(failure)})
        return events

    if state.check_failures and clean.startswith("         "):
        latest = state.check_failures[-1]
        if not latest.detail:
            latest.detail = clean.strip()
            latest.summary, latest.next_action = explain_failure(latest.title, latest.detail)
            events.append({"type": "check_fail_detail", **asdict(latest)})
        return events

    if "Running checks for " in clean:
        if start_phase(state, "check", now):
            events.append({"type": "phase_start", "phase": "check"})
        return events

    if "Running under --no-strict" in clean:
        state.saw_no_strict_warning = True
        events.append({"type": "no_strict_warning"})
        return events

    m = re.search(r"STATUS:\s+(PASS|FAIL)(?:\s+\(phase ([^)]+)\))?", clean)
    if m:
        state.final_status = m.group(1).lower()
        if m.group(2):
            start_phase(state, m.group(2), now)
        events.append({"type": "final_status", "status": state.final_status})
        return events

    return events


def plain_status(
    state: WatchState, *, stalled: bool = False, final: bool = False
) -> tuple[str, str]:
    elapsed = format_elapsed(time.time() - state.started_at)
    name = titlecase_slug(state.slug)
    if final:
        verdict = classify_verdict(state)
        if verdict == "ship-pass":
            return "Working", f"[{elapsed}] {name} is ready to ship. All required checks passed."
        if verdict == "prototype-pass":
            if not state.check_failures:
                return (
                    "Needs attention",
                    f"[{elapsed}] {name} passed this rehearsal run. "
                    "Because it used a relaxed mode, treat it as a review signal, not a ship signal.",
                )
            return (
                "Needs attention",
                f"[{elapsed}] {name} is usable for review, but not ready to ship. "
                f"{len(state.check_failures)} issue(s) still need attention.",
            )
        return (
            "Blocked",
            f"[{elapsed}] {name} stopped before it was ready. {len(state.check_failures)} issue(s) were found.",
        )

    if stalled:
        quiet_for = format_elapsed(time.time() - state.last_output_at)
        phase_label = PHASE_LABELS.get(state.current_phase, state.current_phase)
        return (
            "Quiet",
            f"[{elapsed}] {name} has been quiet for {quiet_for} while {phase_label}. "
            "This may still be normal, but it is worth watching.",
        )

    if state.current_phase == "snap" and state.total_cells:
        attention = state.snap_error_cells + state.snap_warn_cells
        suffix = (
            f" {attention} page(s) need attention."
            if attention
            else " No screenshot issues seen so far."
        )
        return (
            "Working",
            f"[{elapsed}] {name} is checking screenshots. "
            f"{state.completed_cells} of {state.total_cells} pages captured.{suffix}",
        )

    if state.current_phase == "vision-review" and state.vision_total:
        current = f" Current: {state.vision_current}." if state.vision_current else ""
        return (
            "Working",
            f"[{elapsed}] {name} is reviewing screenshots. "
            f"{state.vision_completed} of {state.vision_total} reviewed."
            f"{current}",
        )

    if state.current_phase == "check" and state.check_failures:
        return (
            "Needs attention",
            f"[{elapsed}] {name} is running quality checks. "
            f"{len(state.check_failures)} issue(s) found so far.",
        )

    phase_label = PHASE_LABELS.get(state.current_phase, state.current_phase)
    return (
        "Working",
        f"[{elapsed}] {name} is {phase_label}. Step {phase_index(state)}.",
    )


def classify_verdict(state: WatchState) -> str:
    if state.returncode == 0 and not state.no_strict and not state.check_failures:
        return "ship-pass"
    if state.returncode == 0:
        return "prototype-pass" if state.no_strict or state.saw_no_strict_warning else "ship-pass"
    return "blocked"


def _runtime_guard_fired(state: WatchState) -> bool:
    return any(
        failure.title in {"Factory timeout guard", "Factory stall guard"}
        for failure in state.check_failures
    )


def emit_status(
    state: WatchState,
    *,
    stalled: bool = False,
    final: bool = False,
    status_path: Path | None = None,
    event_path: Path | None = None,
    summary_path: Path | None = None,
) -> None:
    label, message = plain_status(state, stalled=stalled, final=final)
    state.last_status_label = label
    state.last_status_message = message
    print(f"{label}: {message}", flush=True)
    if stalled and state.last_line:
        print(f"        detail: last output was: {state.last_line[:180]}", flush=True)
    if final and state.check_failures:
        for summary, failures in grouped_failures(state.check_failures)[:5]:
            if len(failures) == 1:
                print(f"        issue: {summary}", flush=True)
            else:
                affected = affected_names(failures)
                suffix = f": {', '.join(affected)}" if affected else ""
                print(f"        issue: {summary} ({len(failures)} times{suffix})", flush=True)
            print(f"        next: {failures[0].next_action}", flush=True)
    if status_path is not None:
        write_status(status_path, state, event_path=event_path, summary_path=summary_path)


def grouped_failures(failures: list[CheckFailure]) -> list[tuple[str, list[CheckFailure]]]:
    groups: dict[str, list[CheckFailure]] = {}
    for failure in failures:
        groups.setdefault(failure.summary or failure.title, []).append(failure)
    return sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)


def affected_names(failures: list[CheckFailure]) -> list[str]:
    names: list[str] = []
    for failure in failures:
        match = re.search(r"\bin ([a-z0-9-]+)\b", failure.detail)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names[:8]


def display_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_status(
    path: Path,
    state: WatchState,
    *,
    event_path: Path | None = None,
    summary_path: Path | None = None,
) -> None:
    """Write the live human dashboard that the user can keep open in Cursor."""
    elapsed = format_elapsed(time.time() - state.started_at)
    phase_label = PHASE_LABELS.get(state.current_phase, state.current_phase)
    progress = "Not started"
    if state.current_phase == "snap" and state.total_cells:
        progress = f"{state.completed_cells}/{state.total_cells} screenshots captured"
    elif state.current_phase == "vision-review" and state.vision_total:
        progress = f"{state.vision_completed}/{state.vision_total} screenshots reviewed"
    elif state.phases:
        progress = f"Step {phase_index(state)}"

    lines = [
        f"# {titlecase_slug(state.slug)} Pipeline Status",
        "",
        f"**Status:** {state.last_status_label}",
        f"**Message:** {state.last_status_message}",
        f"**Elapsed:** {elapsed}",
        f"**Current step:** {phase_label}",
        f"**Progress:** {progress}",
        f"**Updated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Next Action",
    ]
    if state.repair_stop_reason:
        lines.append(
            f"Auto-unblock stopped: {state.repair_stop_reason} "
            "Open the Auto-Unblock section below, then fix the first blocker by hand."
        )
    elif state.check_failures:
        _, failures = grouped_failures(state.check_failures)[0]
        lines.append(failures[0].next_action)
    elif state.returncode is None:
        lines.append("Keep watching. The run is still active.")
    elif classify_verdict(state) == "ship-pass":
        lines.append("Review the generated summary, then proceed with the normal shipping flow.")
    elif classify_verdict(state) == "prototype-pass":
        lines.append("Use this as a rehearsal result; run without relaxed flags before shipping.")
    else:
        lines.append("Open the issue list below and fix the first blocker.")

    lines.extend(["", "## Issues"])
    if state.check_failures:
        for summary, failures in grouped_failures(state.check_failures)[:8]:
            affected = affected_names(failures)
            suffix = (
                f" ({len(failures)} times: {', '.join(affected)})"
                if len(failures) > 1 and affected
                else ""
            )
            lines.append(f"- **{summary}**{suffix}")
            lines.append(f"  Next: {failures[0].next_action}")
    else:
        lines.append("- None reported yet.")

    if state.repair_attempts or state.repair_active:
        lines.extend(["", "## Auto-Unblock"])
        lines.append(f"- Active: {'yes' if state.repair_active else 'no'}")
        lines.append(f"- Rounds: {state.repair_round}")
        if state.repair_last_decision:
            lines.append(
                f"- Last decision: {state.repair_last_decision} — {state.repair_last_reason}"
            )
        if state.repair_last_layer:
            lines.append(f"- Last layer: {state.repair_last_layer}")
        if state.repair_last_touched:
            lines.append("- Files touched (most recent):")
            for touched in state.repair_last_touched[:10]:
                lines.append(f"  - {touched}")
        if state.repair_stop_reason:
            lines.append(f"- Stop reason: {state.repair_stop_reason}")
        if state.repair_attempts:
            lines.append("- History:")
            for rec in state.repair_attempts[-5:]:
                lines.append(
                    f"  - attempt {rec.get('attempt')}: {rec.get('decision')} "
                    f"({rec.get('reason', '')[:120]})"
                )
    if state.factory_defects:
        needs_tooling = sum(
            1 for defect in state.factory_defects if defect.get("tooling_status") == "needs-tooling"
        )
        lines.extend(["", "## Factory Defects"])
        lines.append(f"- Candidates: {len(state.factory_defects)}")
        lines.append(f"- Need deterministic tooling: {needs_tooling}")
        lines.append("- Latest:")
        for defect in state.factory_defects[-5:]:
            title = defect.get("title") or defect.get("category") or "unknown"
            lines.append(
                f"  - `{defect.get('tooling_status')}` "
                f"{title} -> `{defect.get('promotion_target')}`"
            )
            suggested = defect.get("suggested_files") or []
            if suggested:
                lines.append(f"    Suggested: {', '.join(f'`{path}`' for path in suggested[:4])}")
    lines.extend(
        [
            "",
            "## Screenshot Progress",
            f"- Captured: {state.completed_cells}/{state.total_cells or 0}",
            f"- Pages with errors: {state.snap_error_cells}",
            f"- Pages with warnings: {state.snap_warn_cells}",
            "",
            "## Vision Review Progress",
            f"- Reviewed: {state.vision_completed}/{state.vision_total or 0}",
            f"- Current: {state.vision_current or 'n/a'}",
            f"- Last completed: {state.vision_last or 'n/a'}",
            f"- Cached: {state.vision_cached}",
            f"- Prefiltered: {state.vision_prefiltered}",
            f"- Errored: {state.vision_errored}",
            f"- Findings so far: {state.vision_findings}",
            "",
            "## Files",
            f"- Events: `{display_path(event_path)}`",
            f"- Summary: `{display_path(summary_path)}`",
            "",
            "## Last Output",
            f"```text\n{state.last_line[-1000:] if state.last_line else 'No output yet.'}\n```",
            "",
            "## Command",
            "```sh",
            " ".join(state.command),
            "```",
            "",
            "<!-- This file is generated by bin/design-watch.py. -->",
        ]
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_event(path: Path, event: dict[str, Any]) -> None:
    event = {"at": time.time(), **event}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def write_summary(path: Path, state: WatchState) -> None:
    summary = {
        "run_id": state.run_id,
        "slug": state.slug,
        "command": state.command,
        "cwd": state.cwd,
        "elapsed_s": round(time.time() - state.started_at, 3),
        "returncode": state.returncode,
        "verdict": classify_verdict(state),
        "current_phase": state.current_phase,
        "phase_durations": {k: round(v, 3) for k, v in state.phase_durations.items()},
        "snap": {
            "completed_cells": state.completed_cells,
            "total_cells": state.total_cells,
            "error_cells": state.snap_error_cells,
            "warn_cells": state.snap_warn_cells,
        },
        "vision_review": {
            "completed": state.vision_completed,
            "total": state.vision_total,
            "current": state.vision_current,
            "last": state.vision_last,
            "cached": state.vision_cached,
            "prefiltered": state.vision_prefiltered,
            "errored": state.vision_errored,
            "findings": state.vision_findings,
        },
        "factory_defects": {
            "total": len(state.factory_defects),
            "needs_tooling": sum(
                1
                for defect in state.factory_defects
                if defect.get("tooling_status") == "needs-tooling"
            ),
            "manual_review": sum(
                1
                for defect in state.factory_defects
                if defect.get("tooling_status") == "manual-review"
            ),
            "covered": sum(
                1
                for defect in state.factory_defects
                if defect.get("tooling_status") == "covered-by-recipe"
            ),
            "items": state.factory_defects,
        },
        "check_failures": [asdict(failure) for failure in state.check_failures],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def infer_slug(design_args: list[str]) -> str:
    if "dress" in design_args:
        idx = design_args.index("dress")
        if idx + 1 < len(design_args):
            return design_args[idx + 1]
    for flag in ("--spec", "--prompt"):
        if flag in design_args:
            idx = design_args.index(flag)
            if idx + 1 < len(design_args):
                value = design_args[idx + 1]
                if flag == "--spec":
                    return Path(value).stem
                return "theme"
    return "theme"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bin/design.py with human-friendly progress updates.",
        add_help=True,
    )
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--stall-seconds", type=float, default=120.0)
    parser.add_argument(
        "--kill-stall-seconds",
        type=float,
        default=300.0,
        help=(
            "Hard-stop the child process after this many seconds with no output "
            "(default 300). Use <=0 to disable."
        ),
    )
    parser.add_argument(
        "--max-elapsed-seconds",
        type=float,
        default=1200.0,
        help=(
            "Hard-stop the child process after this many seconds total "
            "(default 1200 / 20 minutes). Use <=0 to disable."
        ),
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--jsonl", type=Path, default=None, help="Override event JSONL path.")
    parser.add_argument("--summary", type=Path, default=None, help="Override summary JSON path.")
    parser.add_argument("--status", type=Path, default=None, help="Override live STATUS.md path.")
    parser.add_argument("--verbose", action="store_true", help="Also echo raw design.py output.")
    parser.add_argument(
        "--replay-transcript",
        type=Path,
        default=None,
        help="Parse an existing transcript instead of running design.py (for tests/debugging).",
    )
    parser.add_argument(
        "--auto-unblock",
        action="store_true",
        default=True,
        help=(
            "When the run blocks on a known-fixable category, invoke "
            "`bin/design_unblock.py --apply --agentic` to let the LLM "
            "edit toward green, then resume the pipeline from the "
            "smallest safe phase. Bounded by --max-repair-rounds and "
            "the unblocker's own attempt caps. Default: on."
        ),
    )
    parser.add_argument(
        "--no-auto-unblock",
        dest="auto_unblock",
        action="store_false",
        help=(
            "Disable the default self-healing loop and only write the run summary/status artifacts."
        ),
    )
    parser.add_argument(
        "--max-repair-rounds",
        type=int,
        default=3,
        help="How many times --auto-unblock may re-enter the loop (default 3).",
    )
    parser.add_argument(
        "--unblock-dry-run",
        action="store_true",
        help=(
            "Run the unblocker in dry-run mode: emit the repair packet "
            "into STATUS.md and stop, without calling the LLM."
        ),
    )
    parser.add_argument(
        "--no-recipes", action="store_true", help="Skip deterministic repair recipes."
    )
    parser.add_argument(
        "--no-json-repair", action="store_true", help="Skip the JSON edit repair layer."
    )
    parser.add_argument(
        "--no-tool-rescue", action="store_true", help="Skip bounded tool-rescue repair."
    )
    return parser


def parse_watch_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = build_parser()
    args, design_args = parser.parse_known_args(argv)
    if design_args and design_args[0] == "--":
        design_args = design_args[1:]
    if not design_args and not args.replay_transcript:
        parser.error(
            "pass design.py arguments after watch options, e.g. --spec tmp/specs/agave.json"
        )
    return args, design_args


def process_output_line(
    state: WatchState,
    event_path: Path,
    status_path: Path,
    summary_path: Path,
    line: str,
    *,
    verbose: bool,
) -> None:
    now = time.time()
    if verbose:
        print(f"        raw: {line.rstrip()}", flush=True)
    for event in parse_line(state, line, now):
        write_event(event_path, event)
        if event["type"] in {"phase_start", "snap_total"}:
            emit_status(
                state,
                status_path=status_path,
                event_path=event_path,
                summary_path=summary_path,
            )
        else:
            write_status(status_path, state, event_path=event_path, summary_path=summary_path)


def run_replay(
    state: WatchState,
    transcript: Path,
    event_path: Path,
    status_path: Path,
    summary_path: Path,
    verbose: bool,
) -> int:
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        process_output_line(
            state,
            event_path,
            status_path,
            summary_path,
            line + "\n",
            verbose=verbose,
        )
    return 0


def run_subprocess(
    state: WatchState,
    event_path: Path,
    status_path: Path,
    summary_path: Path,
    heartbeat_seconds: float,
    stall_seconds: float,
    kill_stall_seconds: float,
    max_elapsed_seconds: float,
    verbose: bool,
) -> int:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["FIFTY_DESIGN_RUN_ID"] = state.run_id
    proc = subprocess.Popen(
        state.command,
        cwd=state.cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        start_new_session=True,
    )
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)

    while proc.poll() is None:
        ready = selector.select(timeout=1.0)
        if ready:
            line = proc.stdout.readline()
            if line:
                process_output_line(
                    state,
                    event_path,
                    status_path,
                    summary_path,
                    line,
                    verbose=verbose,
                )

        now = time.time()
        if now - state.last_heartbeat_at >= heartbeat_seconds:
            emit_status(
                state,
                status_path=status_path,
                event_path=event_path,
                summary_path=summary_path,
            )
            state.last_heartbeat_at = now
            write_event(event_path, {"type": "heartbeat", "phase": state.current_phase})
        if (
            stall_seconds > 0
            and now - state.last_output_at >= stall_seconds
            and now - state.last_stall_at >= stall_seconds
        ):
            emit_status(
                state,
                stalled=True,
                status_path=status_path,
                event_path=event_path,
                summary_path=summary_path,
            )
            state.last_stall_at = now
            write_event(event_path, {"type": "stall", "phase": state.current_phase})
        if max_elapsed_seconds > 0 and now - state.started_at >= max_elapsed_seconds:
            elapsed = format_elapsed(now - state.started_at)
            reason = (
                f"Factory timeout: run exceeded {format_elapsed(max_elapsed_seconds)} "
                f"total while {PHASE_LABELS.get(state.current_phase, state.current_phase)}."
            )
            _terminate_child(proc, reason=reason)
            state.check_failures.append(
                CheckFailure(
                    title="Factory timeout guard",
                    detail=reason,
                    summary=(
                        f"The run took {elapsed}, over the 20 minute safety cap. "
                        "The factory stopped it instead of letting it burn the queue."
                    ),
                    next_action=(
                        "Inspect the current STATUS.md and fix the slow or wedged phase "
                        "before resuming the batch."
                    ),
                )
            )
            write_event(
                event_path,
                {
                    "type": "timeout_kill",
                    "kind": "max_elapsed",
                    "phase": state.current_phase,
                    "elapsed_s": round(now - state.started_at, 3),
                    "reason": reason,
                },
            )
            emit_status(
                state,
                status_path=status_path,
                event_path=event_path,
                summary_path=summary_path,
            )
            selector.close()
            proc.stdout.close()
            return 124
        if kill_stall_seconds > 0 and now - state.last_output_at >= kill_stall_seconds:
            quiet_for = format_elapsed(now - state.last_output_at)
            reason = (
                f"Factory stall guard: no output for {quiet_for} while "
                f"{PHASE_LABELS.get(state.current_phase, state.current_phase)}."
            )
            _terminate_child(proc, reason=reason)
            state.check_failures.append(
                CheckFailure(
                    title="Factory stall guard",
                    detail=reason,
                    summary=(
                        f"The run produced no output for {quiet_for}. "
                        "The factory stopped it instead of waiting indefinitely."
                    ),
                    next_action=(
                        "Inspect the child phase logs and make the stalled phase fail fast "
                        "or emit progress before resuming the batch."
                    ),
                )
            )
            write_event(
                event_path,
                {
                    "type": "timeout_kill",
                    "kind": "stall",
                    "phase": state.current_phase,
                    "quiet_s": round(now - state.last_output_at, 3),
                    "reason": reason,
                },
            )
            emit_status(
                state,
                status_path=status_path,
                event_path=event_path,
                summary_path=summary_path,
            )
            selector.close()
            proc.stdout.close()
            return 124

    for line in proc.stdout:
        process_output_line(
            state,
            event_path,
            status_path,
            summary_path,
            line,
            verbose=verbose,
        )
    selector.close()
    proc.stdout.close()
    return int(proc.returncode or 0)


def _terminate_child(proc: subprocess.Popen[str], *, reason: str) -> None:
    """Terminate the child process group, escalating if it ignores SIGTERM."""
    sys.stderr.write(f"[design-watch] WARN: {reason} Sending SIGTERM.\n")
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        sys.stderr.write("[design-watch] WARN: child ignored SIGTERM; sending SIGKILL.\n")
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _resume_design_args(design_args: list[str], from_phase: str) -> list[str]:
    """Return a copy of design_args with `--from <phase>` set.

    Strips an existing --from / --only pair so the resume actually runs
    from where the unblocker decided the pipeline should restart.
    """
    out: list[str] = []
    skip_next = False
    for tok in design_args:
        if skip_next:
            skip_next = False
            continue
        if tok == "--from" or tok == "--only":
            skip_next = True
            continue
        if tok.startswith("--from=") or tok.startswith("--only="):
            continue
        out.append(tok)
    out.extend(["--from", from_phase])
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _read_attempts(run_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(run_dir / "repair-attempts.jsonl")


def _read_factory_defects(run_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(run_dir / "factory-defects.jsonl")


def run_auto_unblock_round(
    state: WatchState,
    run_dir: Path,
    *,
    layer: str,
    dry_run: bool = False,
) -> tuple[int, str]:
    """Invoke one design_unblock repair layer once.

    Returns (returncode, resume_phase). The caller decides whether to
    re-enter `run_subprocess` with the resume phase.
    """
    state.repair_active = True
    state.repair_round += 1
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "bin" / "design_unblock.py"),
        "--run-id",
        state.run_id,
    ]
    if layer == "recipes":
        cmd.append("--recipes")
    elif layer == "json-llm" and dry_run:
        cmd.extend(["--agentic", "--agentic-dry-run"])
    elif layer == "json-llm":
        cmd.extend(["--apply", "--agentic"])
    elif layer == "tool-rescue" and dry_run:
        cmd.extend(["--tool-rescue", "--tool-rescue-dry-run"])
    elif layer == "tool-rescue":
        cmd.append("--tool-rescue")
    else:
        raise ValueError(f"unknown repair layer: {layer}")
    print(
        f"Working: Auto-unblock round {state.repair_round} ({layer}): {' '.join(cmd)}",
        flush=True,
    )
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    # Read the attempt record that was just appended.
    attempts = _read_attempts(run_dir)
    state.repair_attempts = attempts
    state.factory_defects = _read_factory_defects(run_dir)
    resume_phase = "check"
    if attempts:
        last = attempts[-1]
        state.repair_last_decision = str(last.get("decision") or "")
        state.repair_last_reason = str(last.get("reason") or "")
        state.repair_last_touched = list(last.get("touched_files") or [])
        verification = last.get("verification") or {}
        if isinstance(verification, dict):
            state.repair_last_layer = str(verification.get("layer") or layer)
        # Load the plan to learn the recommended resume phase.
        plan_path = run_dir / "repair-plan.json"
        if plan_path.is_file():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                resume_phase = str(plan.get("resume_phase") or "check") or "check"
            except json.JSONDecodeError:
                pass
    state.repair_active = False
    return proc.returncode, resume_phase


def main(argv: list[str] | None = None) -> int:
    watch_args, design_args = parse_watch_args(argv or sys.argv[1:])
    run_id = watch_args.run_id or time.strftime("design-%Y%m%d-%H%M%S")
    run_dir = ROOT / "tmp" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    event_path = watch_args.jsonl or (run_dir / "events.jsonl")
    summary_path = watch_args.summary or (run_dir / "summary.json")
    status_path = watch_args.status or (run_dir / "STATUS.md")
    event_path.write_text("", encoding="utf-8")

    command = [sys.executable, "-u", str(ROOT / "bin" / "design.py"), *design_args]
    now = time.time()
    state = WatchState(
        run_id=run_id,
        started_at=now,
        command=command,
        cwd=str(ROOT),
        slug=infer_slug(design_args),
        phase_started_at=now,
        last_output_at=now,
        last_heartbeat_at=now,
        no_strict="--no-strict" in design_args,
    )
    write_event(event_path, {"type": "run_start", "command": command, "cwd": str(ROOT)})
    state.last_status_label = "Working"
    state.last_status_message = f"Starting {titlecase_slug(state.slug)} pipeline run."
    write_status(status_path, state, event_path=event_path, summary_path=summary_path)

    print(f"Working: Starting {titlecase_slug(state.slug)} pipeline run.", flush=True)
    print(f"        detail: run_id={run_id} cwd={ROOT}", flush=True)
    print(f"        detail: status={display_path(status_path)}", flush=True)
    try:
        if watch_args.replay_transcript:
            rc = run_replay(
                state,
                watch_args.replay_transcript,
                event_path,
                status_path,
                summary_path,
                watch_args.verbose,
            )
        else:
            rc = run_subprocess(
                state,
                event_path,
                status_path,
                summary_path,
                watch_args.heartbeat_seconds,
                watch_args.stall_seconds,
                watch_args.kill_stall_seconds,
                watch_args.max_elapsed_seconds,
                watch_args.verbose,
            )
    finally:
        if state.current_phase and state.phase_started_at:
            state.phase_durations[state.current_phase] = state.phase_durations.get(
                state.current_phase, 0.0
            ) + max(0.0, time.time() - state.phase_started_at)

    state.returncode = rc
    write_event(event_path, {"type": "process_exit", "returncode": rc})
    # Write summary first so the unblocker (which reads summary.json)
    # has the final blocker list even if auto-unblock kicks in.
    write_summary(summary_path, state)

    if watch_args.auto_unblock and classify_verdict(state) == "blocked" and state.check_failures:
        repair_layers: list[str]
        if _runtime_guard_fired(state):
            repair_layers = [] if watch_args.no_tool_rescue else ["tool-rescue"]
        else:
            repair_layers = []
            if not watch_args.no_recipes:
                repair_layers.append("recipes")
            if not watch_args.no_json_repair:
                repair_layers.append("json-llm")
            if not watch_args.no_tool_rescue:
                repair_layers.append("tool-rescue")
        while state.repair_round < watch_args.max_repair_rounds:
            rc_unblock = 4
            resume_phase = "check"
            layer_used = ""
            for layer in repair_layers:
                if state.repair_round >= watch_args.max_repair_rounds:
                    break
                rc_unblock, resume_phase = run_auto_unblock_round(
                    state,
                    run_dir,
                    layer=layer,
                    dry_run=watch_args.unblock_dry_run,
                )
                layer_used = layer
                write_status(status_path, state, event_path=event_path, summary_path=summary_path)
                # Exit codes from design_unblock.py:
                #   0 = fixed / improved, resume OK
                #   2 = worktree dirty, stop
                #   3 = worse, stop
                #   4 = stopped (cap or streak), try next layer
                #   5 = dry-run / API missing, try next layer unless dry-run
                if rc_unblock == 0:
                    break
                if rc_unblock in (2, 3) or watch_args.unblock_dry_run:
                    break
                # A non-improving JSON pass should fall through to the
                # stronger tool-rescue layer; the final layer handles
                # escalation below.
            if rc_unblock != 0:
                state.repair_stop_reason = {
                    2: "Worktree has unrelated framework changes.",
                    3: "Repair attempt made verification worse.",
                    4: "Repair cap or non-improving streak reached.",
                    5: "LLM unavailable or dry-run; handoff to a human boundary.",
                }.get(rc_unblock, f"Repair halted after {layer_used or 'no layer'}.")
                break

            # Prepare a resume: reset per-run artifacts the next child run
            # will repopulate, then re-enter run_subprocess.
            state.check_failures = []
            state.snap_error_cells = 0
            state.snap_warn_cells = 0
            state.completed_cells = 0
            state.total_cells = 0
            state.final_status = None
            resume_args = _resume_design_args(design_args, resume_phase)
            state.command = [
                sys.executable,
                "-u",
                str(ROOT / "bin" / "design.py"),
                *resume_args,
            ]
            state.current_phase = resume_phase
            state.phase_started_at = time.time()
            state.last_output_at = time.time()
            print(
                f"Working: Resuming pipeline at `{resume_phase}` "
                f"(round {state.repair_round} cleared a repair).",
                flush=True,
            )
            write_event(
                event_path,
                {
                    "type": "auto_unblock_resume",
                    "round": state.repair_round,
                    "resume_phase": resume_phase,
                },
            )
            try:
                rc = run_subprocess(
                    state,
                    event_path,
                    status_path,
                    summary_path,
                    watch_args.heartbeat_seconds,
                    watch_args.stall_seconds,
                    watch_args.kill_stall_seconds,
                    watch_args.max_elapsed_seconds,
                    watch_args.verbose,
                )
            finally:
                if state.current_phase and state.phase_started_at:
                    state.phase_durations[state.current_phase] = state.phase_durations.get(
                        state.current_phase, 0.0
                    ) + max(0.0, time.time() - state.phase_started_at)
            state.returncode = rc
            write_event(event_path, {"type": "process_exit", "returncode": rc})
            write_summary(summary_path, state)
            if classify_verdict(state) != "blocked":
                break
        else:
            state.repair_stop_reason = (
                f"Max repair rounds ({watch_args.max_repair_rounds}) reached."
            )

    emit_status(
        state,
        final=True,
        status_path=status_path,
        event_path=event_path,
        summary_path=summary_path,
    )
    write_summary(summary_path, state)
    write_status(status_path, state, event_path=event_path, summary_path=summary_path)
    print(
        "        detail: "
        f"status={display_path(status_path)} "
        f"events={display_path(event_path)} "
        f"summary={display_path(summary_path)}"
    )
    return state.returncode if state.returncode is not None else rc


if __name__ == "__main__":
    raise SystemExit(main())
