#!/usr/bin/env python3
"""Watch theme sources, auto-dispatch overrides + snap, write state.

The closed-loop dispatcher Phase 2 from the
"closed loop theme building" plan. Replaces the five-step manual
loop ("edit -> remember to run append-wc-overrides --update -> remember
to snap -> remember to read findings -> remember to read PNG ->
edit again") with one continuously-running daemon. The agent's next
turn always opens with `tmp/dispatch-state.json` + the freshest
findings; no "let me run snap and check..." preamble.

What it watches
---------------
* `bin/append-wc-overrides.py` (touch -> dispatch overrides into
  every theme then snap whichever themes have follow-on edits).
* For every theme in the monorepo:
    - `theme.json`
    - `functions.php`
    - `styles/**`
    - `templates/**`
    - `parts/**`
    - `patterns/**`
    - `playground/blueprint.json`
  Any of those changing -> the theme is queued for re-snap.

What it runs
------------
1. `python3 bin/append-wc-overrides.py --update` (idempotent;
   only runs when `bin/append-wc-overrides.py` itself changed, or
   on the first dispatch after startup).
2. Snap each queued theme. Tries the warm Playground server first
   (Phase 2's `bin/snap.py serve --shoot-on-demand` if it's running)
   and falls back to a cold `python3 bin/snap.py shoot <theme>` if
   the warm endpoint isn't reachable.

What it writes
--------------
`tmp/dispatch-state.json` after every dispatch (see
`.cursor/rules/dispatch-state.mdc` for the full schema).

Usage
-----
    python3 bin/dispatch-watch.py                # watch every theme
    python3 bin/dispatch-watch.py --theme selvedge --theme chonk
    python3 bin/dispatch-watch.py --once         # one pass, no daemon
    python3 bin/dispatch-watch.py --debounce 1.5 # custom debounce in seconds
    python3 bin/dispatch-watch.py --no-snap      # only run override generator
    python3 bin/dispatch-watch.py --warm-shoot http://127.0.0.1:9501/shoot

Stdlib-only on purpose: we don't want a `watchdog` dep that drags
in libuv, and mtime polling is plenty for human-edit cadence (the
agent's CSS edits land seconds apart, not microseconds).
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes

TMP_DIR = MONOREPO_ROOT / "tmp"
STATE_PATH = TMP_DIR / "dispatch-state.json"
DISPATCHER_LOG = TMP_DIR / "dispatch-watch.log"

THEME_SOURCE_GLOBS = (
    "theme.json",
    "functions.php",
    "styles/**/*",
    "templates/**/*",
    "parts/**/*",
    "patterns/**/*",
    "playground/blueprint.json",
)

DISPATCH_SCRIPTS = (
    MONOREPO_ROOT / "bin" / "append-wc-overrides.py",
)

WARM_HEALTH_DEFAULT = "http://127.0.0.1:9501/health"
WARM_SHOOT_DEFAULT = "http://127.0.0.1:9501/shoot"


# ---------------------------------------------------------------------------
# Mtime probe
# ---------------------------------------------------------------------------


def safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def theme_source_files(theme_root: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in THEME_SOURCE_GLOBS:
        if "**" in pattern:
            out.extend(p for p in theme_root.glob(pattern) if p.is_file())
        else:
            p = theme_root / pattern
            if p.is_file():
                out.append(p)
    return out


def snapshot_mtimes(themes: list[Path]) -> dict[str, float]:
    snap: dict[str, float] = {}
    for script in DISPATCH_SCRIPTS:
        snap[str(script)] = safe_mtime(script)
    for theme in themes:
        for f in theme_source_files(theme):
            snap[str(f)] = safe_mtime(f)
    return snap


def diff_snapshots(
    prev: dict[str, float], curr: dict[str, float], themes: list[Path]
) -> tuple[set[str], bool]:
    """Return (changed_theme_slugs, dispatcher_changed)."""
    changed_themes: set[str] = set()
    dispatcher_changed = False
    for path_str, mtime in curr.items():
        if prev.get(path_str, 0.0) >= mtime:
            continue
        path = Path(path_str)
        if any(path == script for script in DISPATCH_SCRIPTS):
            dispatcher_changed = True
            continue
        for theme in themes:
            try:
                path.relative_to(theme)
            except ValueError:
                continue
            changed_themes.add(theme.name)
            break
    return changed_themes, dispatcher_changed


# ---------------------------------------------------------------------------
# Dispatch primitives
# ---------------------------------------------------------------------------


def run_logged(cmd: list[str], log_to: Path) -> int:
    with log_to.open("a", encoding="utf-8") as fh:
        fh.write(f"\n$ {' '.join(cmd)}\n")
        fh.flush()
        proc = subprocess.run(cmd, cwd=str(MONOREPO_ROOT), capture_output=True, text=True)
        fh.write(proc.stdout)
        if proc.stderr:
            fh.write("\n--- stderr ---\n")
            fh.write(proc.stderr)
        fh.write(f"\n[exit={proc.returncode}]\n")
    return proc.returncode


def dispatch_overrides(log_to: Path) -> int:
    return run_logged(
        ["python3", str(MONOREPO_ROOT / "bin" / "append-wc-overrides.py"), "--update"],
        log_to,
    )


def warm_endpoint_alive(health_url: str) -> bool:
    try:
        with urllib.request.urlopen(health_url, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def warm_shoot(shoot_url: str, theme: str, log_to: Path, timeout_s: int = 240) -> int:
    body = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        shoot_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with log_to.open("a", encoding="utf-8") as fh:
        fh.write(f"\n$ POST {shoot_url} (theme={theme}, warm)\n")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = resp.read().decode("utf-8")
                fh.write(payload[:4000])
                fh.write(f"\n[exit=0 status={resp.status}]\n")
                return 0 if resp.status == 200 else 1
        except (urllib.error.URLError, OSError) as e:
            fh.write(f"\n[exit=1 warm shoot failed: {e}]\n")
            return 1


def cold_shoot(theme: str, log_to: Path) -> int:
    return run_logged(
        ["python3", str(MONOREPO_ROOT / "bin" / "snap.py"), "shoot", theme],
        log_to,
    )


def snap_themes(
    theme_slugs: list[str],
    log_to: Path,
    *,
    warm_health: str,
    warm_shoot_url: str,
) -> dict[str, int]:
    """Snap one theme at a time. Parallel boots reliably hit the
    `PHP instance already acquired` race that Phase 3 hardens."""
    rcs: dict[str, int] = {}
    warm = warm_endpoint_alive(warm_health)
    for slug in theme_slugs:
        if warm:
            rcs[slug] = warm_shoot(warm_shoot_url, slug, log_to)
            if rcs[slug] != 0:
                # Warm shoot failed -- fall back to a cold boot for
                # this theme. Don't disable warm globally; the
                # supervisor (phase3-warm-supervisor) will restart it.
                rcs[slug] = cold_shoot(slug, log_to)
        else:
            rcs[slug] = cold_shoot(slug, log_to)
    return rcs


# ---------------------------------------------------------------------------
# State writer
# ---------------------------------------------------------------------------


def collect_findings_for(theme_slug: str) -> list[dict]:
    out: list[dict] = []
    base = TMP_DIR / "snaps" / theme_slug
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
            out.append(
                {
                    "theme": theme_slug,
                    "route": route,
                    "viewport": viewport,
                    "kind": finding.get("kind"),
                    "severity": finding.get("severity"),
                    "message": (finding.get("message") or "")[:300],
                    "axe_help_url": finding.get("axe_help_url"),
                    "selector": (finding.get("selector") or "")[:200],
                }
            )
    return out


def load_remedies() -> list[dict]:
    path = MONOREPO_ROOT / "bin" / "finding_remedies.json"
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("remedies") or []
    except (OSError, json.JSONDecodeError):
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


def write_state(
    *,
    started_at: float,
    last_dispatch_kind: str,
    themes_dispatched: list[str],
    themes_snapped: list[str],
    state_path: Path,
) -> None:
    remedies = load_remedies()
    errors_by_rv: dict[str, list[dict]] = {}
    suggested_fixes: list[dict] = []
    for slug in themes_snapped:
        for finding in collect_findings_for(slug):
            key = f"{slug}:{finding['route']}:{finding['viewport']}"
            errors_by_rv.setdefault(key, []).append(finding)
            if finding.get("severity") == "error":
                remedy = match_remedy(finding, remedies)
                if remedy:
                    suggested_fixes.append(
                        {
                            "theme": slug,
                            "route": finding["route"],
                            "viewport": finding["viewport"],
                            "axe_rule": finding.get("kind"),
                            "selector": finding.get("selector"),
                            "remedy_id": remedy.get("id"),
                            "file": remedy.get("file"),
                            "strategy": remedy.get("strategy"),
                            "example_diff": remedy.get("example_diff"),
                        }
                    )

    next_actions: list[str] = []
    if suggested_fixes:
        for fx in suggested_fixes[:5]:
            next_actions.append(
                f"{fx['theme']} {fx['route']}/{fx['viewport']}: "
                f"{fx.get('axe_rule')} -> {fx.get('strategy', 'see remedy')}"
            )
    elif any(
        f.get("severity") == "error"
        for findings in errors_by_rv.values()
        for f in findings
    ):
        next_actions.append(
            "axe-core errors present without a matched remedy; extend "
            "bin/finding_remedies.json"
        )

    payload = {
        "schema": 1,
        "started_at": int(started_at),
        "last_run_at": int(time.time()),
        "last_dispatch_kind": last_dispatch_kind,
        "themes_dispatched": sorted(themes_dispatched),
        "themes_snapped": sorted(themes_snapped),
        "errors_by_route_viewport": errors_by_rv,
        "suggested_fixes": suggested_fixes,
        "next_actions": next_actions,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", action="append", default=None)
    parser.add_argument("--debounce", type=float, default=0.5)
    parser.add_argument("--poll", type=float, default=0.4)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--log", default=str(DISPATCHER_LOG))
    parser.add_argument("--no-snap", action="store_true")
    parser.add_argument("--warm-health", default=WARM_HEALTH_DEFAULT)
    parser.add_argument("--warm-shoot", default=WARM_SHOOT_DEFAULT)
    args = parser.parse_args(argv)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if args.theme:
        themes = []
        for slug in args.theme:
            t = MONOREPO_ROOT / slug
            if not (t / "theme.json").is_file():
                print(f"unknown theme: {slug}", file=sys.stderr)
                return 2
            themes.append(t)
    else:
        themes = list(iter_themes())

    started_at = time.time()
    print(
        f"dispatch-watch: tracking {len(themes)} theme(s) "
        f"({', '.join(t.name for t in themes)}). "
        f"state={state_path.relative_to(MONOREPO_ROOT)} "
        f"log={log_path.relative_to(MONOREPO_ROOT)} "
        f"warm-health={args.warm_health}",
        flush=True,
    )

    write_state(
        started_at=started_at,
        last_dispatch_kind="noop",
        themes_dispatched=[],
        themes_snapped=[],
        state_path=state_path,
    )

    prev_snapshot = snapshot_mtimes(themes)
    quiet_since: float | None = None
    pending_themes: set[str] = set()
    pending_dispatcher = False

    def graceful_exit(_signum, _frame):
        print("dispatch-watch: shutting down.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    while True:
        time.sleep(args.poll)
        curr_snapshot = snapshot_mtimes(themes)
        new_themes, dispatcher_changed = diff_snapshots(
            prev_snapshot, curr_snapshot, themes
        )

        if new_themes or dispatcher_changed:
            pending_themes |= new_themes
            pending_dispatcher = pending_dispatcher or dispatcher_changed
            quiet_since = time.time()
            prev_snapshot = curr_snapshot
            print(
                f"dispatch-watch: queued "
                f"({sorted(pending_themes)}, dispatcher={pending_dispatcher}); "
                f"debouncing {args.debounce}s",
                flush=True,
            )

        elif quiet_since is not None and (time.time() - quiet_since) >= args.debounce:
            kind = "noop"
            if pending_dispatcher:
                kind = "overrides+snap"
                rc = dispatch_overrides(log_path)
                if rc != 0:
                    print(
                        f"dispatch-watch: append-wc-overrides FAILED "
                        f"(rc={rc}); see {log_path.relative_to(MONOREPO_ROOT)}",
                        flush=True,
                    )
                # Re-snapshot so the script's own theme.json edits don't
                # bounce back into pending_themes.
                prev_snapshot = snapshot_mtimes(themes)
            elif pending_themes:
                kind = "snap-only"

            snapped: list[str] = []
            if not args.no_snap and pending_themes:
                target_slugs = sorted(pending_themes)
                print(f"dispatch-watch: snapping {target_slugs}", flush=True)
                rcs = snap_themes(
                    target_slugs,
                    log_path,
                    warm_health=args.warm_health,
                    warm_shoot_url=args.warm_shoot,
                )
                snapped = sorted(rcs.keys())
                bad = [slug for slug, rc in rcs.items() if rc != 0]
                if bad:
                    print(
                        f"dispatch-watch: snap FAILED for {bad}; see "
                        f"{log_path.relative_to(MONOREPO_ROOT)}",
                        flush=True,
                    )

            write_state(
                started_at=started_at,
                last_dispatch_kind=kind,
                themes_dispatched=sorted(pending_themes),
                themes_snapped=snapped,
                state_path=state_path,
            )

            print(
                f"dispatch-watch: state -> {state_path.relative_to(MONOREPO_ROOT)} "
                f"(kind={kind})",
                flush=True,
            )

            pending_themes.clear()
            pending_dispatcher = False
            quiet_since = None

            if args.once:
                return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
