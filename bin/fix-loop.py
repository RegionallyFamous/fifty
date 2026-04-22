#!/usr/bin/env python3
"""Fix-loop harness: iterate snap -> remedy -> verify until green or max attempts.

Phase 2 (closed-loop dispatcher) deliverable -- intentionally
*optional*. The watcher (`bin/dispatch-watch.py`) and the cursor rule
(`.cursor/rules/dispatch-state.mdc`) get the agent 80% of the way to
autonomous fixing: the agent's next turn opens with fresh findings +
suggested remedies. This script is the remaining 20% -- a non-AI
state machine that brackets the agent's attempts so a long-running
"fix everything" pass has a hard cap and a structured failure report
instead of looping forever.

Loop
----
For each --theme passed in:

1. Snap the theme (warm endpoint if available, cold boot if not).
2. Read tmp/snaps/<theme>/**/findings.json, build a list of
   error-severity findings.
3. If empty -> theme is green; print success summary and continue.
4. Otherwise look up each finding in bin/finding_remedies.json. Print
   the matched remedy (file, strategy, example_diff). Findings without
   a matching remedy are escalated as "needs human / needs new entry"
   and abort the loop for this theme.
5. *Hand control back to the agent* by pausing for --hold-seconds
   (default 120s) or until tmp/fix-loop-go.<theme> is touched. The
   intent: the supervising agent reads the printed remedies, edits the
   files, then either touches the go-file or just lets the timer
   expire. We never call out to a model from here -- this script is
   the harness, the agent is the operator.
6. Re-snap, recompute findings.
7. If the count of error-severity findings dropped, count it as
   forward progress. If it rose or stayed flat, count it as a wasted
   attempt. After --max wasted attempts (default 3), bail loudly
   with the remaining findings + the diff of what changed across
   attempts.

Output
------
- Streams a human-readable progress log to stdout.
- Writes tmp/fix-loop-<theme>.json after every iteration:
    {
      "theme": "selvedge",
      "started_at": ...,
      "attempts": [
        {"n": 1, "errors_before": 3, "errors_after": 1,
         "remedies_applied_by_agent": [...],
         "fix_made_progress": true,
         "elapsed_s": 47.2}
      ],
      "final_status": "green" | "stuck" | "no_remedy" | "running"
    }

Usage
-----
    # Auto-fix one theme, hold 60s for the agent each iteration:
    python3 bin/fix-loop.py --theme selvedge --hold-seconds 60

    # Multi-theme nightly run with default 3-attempt cap:
    python3 bin/fix-loop.py --theme selvedge --theme chonk

    # Dry-run: print remedies and bail without snapping:
    python3 bin/fix-loop.py --theme selvedge --plan-only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT  # noqa: E402

TMP_DIR = MONOREPO_ROOT / "tmp"
SNAPS_DIR = TMP_DIR / "snaps"
REMEDIES_PATH = MONOREPO_ROOT / "bin" / "finding_remedies.json"
WARM_HEALTH_DEFAULT = "http://127.0.0.1:9501/health"
WARM_SHOOT_DEFAULT = "http://127.0.0.1:9501/shoot"


def load_remedies() -> list[dict]:
    if not REMEDIES_PATH.is_file():
        return []
    try:
        return json.loads(REMEDIES_PATH.read_text(encoding="utf-8")).get("remedies") or []
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARN: failed to parse {REMEDIES_PATH}: {e}", file=sys.stderr)
        return []


def match_remedy(finding: dict, remedies: list[dict]) -> dict | None:
    sel = (finding.get("selector") or "").lower()
    rule = (finding.get("kind") or "").lower()
    for remedy in remedies:
        rule_pat = (remedy.get("axe_rule") or "").lower()
        if rule_pat and rule_pat != rule:
            continue
        sel_pat = (remedy.get("selector_pattern") or "").lower()
        if sel_pat and sel_pat not in sel:
            continue
        return remedy
    return None


def collect_error_findings(theme: str) -> list[dict]:
    out: list[dict] = []
    base = SNAPS_DIR / theme
    if not base.is_dir():
        return out
    for fp in sorted(base.rglob("*.findings.json")):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        viewport = fp.parent.name
        route = fp.stem.removesuffix(".findings")
        for finding in payload.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            if finding.get("severity") != "error":
                continue
            out.append(
                {
                    "theme": theme,
                    "route": route,
                    "viewport": viewport,
                    "kind": finding.get("kind"),
                    "severity": finding.get("severity"),
                    "message": (finding.get("message") or "")[:300],
                    "selector": (finding.get("selector") or "")[:200],
                    "axe_help_url": finding.get("axe_help_url"),
                    "_source": str(fp.relative_to(MONOREPO_ROOT)),
                }
            )
    return out


def warm_endpoint_alive(health_url: str) -> bool:
    try:
        with urllib.request.urlopen(health_url, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def shoot_warm(shoot_url: str, theme: str, timeout_s: int = 240) -> bool:
    body = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        shoot_url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError) as e:
        print(f"WARN: warm shoot failed ({e}); falling back to cold.", file=sys.stderr)
        return False


def shoot_cold(theme: str) -> bool:
    print(f"  cold-boot snap of {theme} (this takes ~2 min)...", flush=True)
    proc = subprocess.run(
        ["python3", str(MONOREPO_ROOT / "bin" / "snap.py"), "shoot", theme],
        cwd=str(MONOREPO_ROOT),
    )
    return proc.returncode == 0


def snap_theme(theme: str, warm_health: str, warm_shoot: str) -> bool:
    if warm_endpoint_alive(warm_health):
        print(f"  using warm endpoint at {warm_shoot}", flush=True)
        return shoot_warm(warm_shoot, theme)
    return shoot_cold(theme)


def state_path_for(theme: str) -> Path:
    return TMP_DIR / f"fix-loop-{theme}.json"


def go_signal_path_for(theme: str) -> Path:
    return TMP_DIR / f"fix-loop-go.{theme}"


def write_state(theme: str, payload: dict) -> None:
    p = state_path_for(theme)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def hold_for_agent(theme: str, hold_seconds: float) -> None:
    """Block until the supervising agent touches the go-file or the
    hold-window expires. Prints a heartbeat every 15s so the
    operator (human OR agent) knows the script is waiting on them
    and not wedged."""
    go = go_signal_path_for(theme)
    if go.exists():
        go.unlink()
    deadline = time.time() + hold_seconds
    print(
        f"  holding {hold_seconds:.0f}s for agent edits "
        f"(touch {go.relative_to(MONOREPO_ROOT)} to skip remaining hold)",
        flush=True,
    )
    next_beat = time.time() + 15
    while time.time() < deadline:
        if go.exists():
            go.unlink()
            print("  go-file detected; resuming.", flush=True)
            return
        if time.time() >= next_beat:
            remaining = int(deadline - time.time())
            print(f"  ...still holding ({remaining}s left)", flush=True)
            next_beat = time.time() + 15
        time.sleep(1.0)
    print("  hold-window expired; resuming.", flush=True)


def run_for_theme(
    *,
    theme: str,
    max_attempts: int,
    hold_seconds: float,
    warm_health: str,
    warm_shoot: str,
    plan_only: bool,
) -> str:
    """Returns one of: green, stuck, no_remedy, snap_failed."""
    remedies = load_remedies()
    started = time.time()
    attempts: list[dict] = []
    wasted = 0

    def persist(status: str) -> None:
        write_state(
            theme,
            {
                "schema": 1,
                "theme": theme,
                "started_at": int(started),
                "last_run_at": int(time.time()),
                "attempts": attempts,
                "final_status": status,
            },
        )

    persist("running")

    if plan_only:
        errors = collect_error_findings(theme)
        print(f"=== {theme} (plan-only) ===")
        if not errors:
            print("  no error-severity findings; nothing to plan.")
            persist("green")
            return "green"
        for f in errors:
            r = match_remedy(f, remedies)
            label = f"{f['route']}/{f['viewport']} [{f['kind']}] {f['selector']}"
            if r is None:
                print(f"  NO REMEDY  {label}")
            else:
                print(
                    f"  REMEDY {r['id']:24s} {label}\n"
                    f"      file: {r.get('file')}\n"
                    f"      strategy: {r.get('strategy')}"
                )
        persist("running")
        return "running"

    for attempt_n in range(1, max_attempts + 1):
        print(f"\n=== {theme}: attempt {attempt_n}/{max_attempts} ===")
        t0 = time.time()
        errors_before = collect_error_findings(theme)
        print(f"  {len(errors_before)} error-severity finding(s) before snap")

        ok = snap_theme(theme, warm_health, warm_shoot)
        if not ok:
            attempts.append(
                {
                    "n": attempt_n,
                    "errors_before": len(errors_before),
                    "errors_after": None,
                    "snap_failed": True,
                    "elapsed_s": round(time.time() - t0, 1),
                }
            )
            persist("snap_failed")
            print(f"  snap FAILED for {theme}; aborting.")
            return "snap_failed"

        errors_after = collect_error_findings(theme)
        print(f"  {len(errors_after)} error-severity finding(s) after snap")

        if not errors_after:
            attempts.append(
                {
                    "n": attempt_n,
                    "errors_before": len(errors_before),
                    "errors_after": 0,
                    "elapsed_s": round(time.time() - t0, 1),
                }
            )
            persist("green")
            print(f"  {theme} is GREEN. ({len(attempts)} attempt(s).)")
            return "green"

        applied: list[dict] = []
        unmatched: list[dict] = []
        for f in errors_after:
            r = match_remedy(f, remedies)
            label = f"{f['route']}/{f['viewport']} [{f['kind']}] {f['selector']}"
            if r is None:
                unmatched.append(f)
                print(f"  NO REMEDY: {label}")
                continue
            applied.append(
                {
                    "remedy_id": r["id"],
                    "finding": label,
                    "file": r.get("file"),
                    "strategy": r.get("strategy"),
                    "example_diff": r.get("example_diff"),
                }
            )
            print(f"  REMEDY {r['id']}: {label}")
            print(f"      file: {r.get('file')}")
            print(f"      strategy: {r.get('strategy')}")
            if r.get("example_diff"):
                print(f"      example_diff: {r['example_diff']}")

        progress = len(errors_after) < len(errors_before)
        if not progress:
            wasted += 1

        attempts.append(
            {
                "n": attempt_n,
                "errors_before": len(errors_before),
                "errors_after": len(errors_after),
                "remedies_to_apply": applied,
                "unmatched_findings": unmatched,
                "fix_made_progress": progress,
                "wasted_attempts_so_far": wasted,
                "elapsed_s": round(time.time() - t0, 1),
            }
        )
        persist("running")

        if unmatched:
            persist("no_remedy")
            print(
                f"  {theme} aborted: {len(unmatched)} finding(s) have no remedy in "
                f"{REMEDIES_PATH.relative_to(MONOREPO_ROOT)}. "
                "Add an entry there before re-running."
            )
            return "no_remedy"

        if attempt_n == max_attempts:
            persist("stuck")
            print(
                f"  {theme} STUCK after {max_attempts} attempt(s); "
                f"see {state_path_for(theme).relative_to(MONOREPO_ROOT)}."
            )
            return "stuck"

        hold_for_agent(theme, hold_seconds)

    persist("stuck")
    return "stuck"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", action="append", required=True, help="Theme slug; repeat to fix multiple themes.")
    parser.add_argument("--max", type=int, default=3, dest="max_attempts", help="Max snap iterations per theme (default: 3).")
    parser.add_argument("--hold-seconds", type=float, default=120.0, help="Seconds to wait between snap iterations for the agent to apply remedies (default: 120).")
    parser.add_argument("--warm-health", default=WARM_HEALTH_DEFAULT, help=f"Warm-server health URL (default: {WARM_HEALTH_DEFAULT}).")
    parser.add_argument("--warm-shoot", default=WARM_SHOOT_DEFAULT, help=f"Warm-server shoot URL (default: {WARM_SHOOT_DEFAULT}).")
    parser.add_argument("--plan-only", action="store_true", help="Print remedies for the current findings and exit (no snap, no hold).")
    parser.add_argument("--iterate", action="store_true", help="Compatibility flag (current default behavior). Future use: enables a sub-agent dispatcher.")
    args = parser.parse_args(argv)

    if args.iterate:
        # Reserved for a future Cursor subagent dispatcher; the
        # script is intentionally usable without it (the supervising
        # agent in chat IS the dispatcher today).
        pass

    statuses: dict[str, str] = {}
    for theme in args.theme:
        if not (MONOREPO_ROOT / theme / "theme.json").is_file():
            print(f"unknown theme: {theme}", file=sys.stderr)
            statuses[theme] = "unknown"
            continue
        statuses[theme] = run_for_theme(
            theme=theme,
            max_attempts=args.max_attempts,
            hold_seconds=args.hold_seconds,
            warm_health=args.warm_health,
            warm_shoot=args.warm_shoot,
            plan_only=args.plan_only,
        )

    print("\n=== fix-loop summary ===")
    for theme, status in statuses.items():
        print(f"  {theme:20s} {status}")
    bad = [t for t, s in statuses.items() if s not in ("green", "running")]
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
