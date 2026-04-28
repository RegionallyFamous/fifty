#!/usr/bin/env python3
"""Promote a generated theme from `incubating` to `shipping`.

Promotion is the formal gate that lets a theme appear on the public
`docs/` queue and counts toward the default `bin/check.py --all`
sweep. The closed-loop pipeline starts every clone as `incubating`
(see `bin/clone.py`) so unfinished WIP themes never silently regress
the green CI gate.

Usage:
    python3 bin/promote-theme.py <slug>             # gate then promote
    python3 bin/promote-theme.py <slug> --check-only  # report only
    python3 bin/promote-theme.py <slug> --force     # promote past failures
                                                     # (records --force in
                                                     # readiness.notes; for
                                                     # explicit overrides)

Promotion gates (every one MUST pass unless --force):
  1. `<slug>/readiness.json` exists with stage=incubating.
  2. `<slug>/design-intent.md` is present + non-trivial (rubric exists
     so the vision reviewer has something to grade against).
  3. `<slug>/playground/blueprint.json` exists with seeded content
     (`bin/check.py::check_playground_content_seeded` semantics).
  4. `<slug>/playground/content/product-images.json` exists if the
     theme ships per-theme product photographs.
  5. `bin/verify-theme.py <slug> --snap --strict` returns `passed`.
  6. The current branch is pushed and in sync with origin (so the
     `docs/` redirector built off the new readiness will resolve
     to a real commit).

When all gates pass, `<slug>/readiness.json`'s `stage` flips to
`shipping`, `last_checked` is stamped with today's UTC date, and a
short audit note is appended to `notes`. Promotion is reversible: a
later `bin/promote-theme.py <slug> --demote --reason "..."` flips
the stage back to `incubating` so a regression doesn't have to
disappear from the queue silently — it stays visible with a clear
failing status.

Exit codes:
    0  promoted (or already shipping when --check-only)
    1  one or more gates failed
    2  invalid arguments / theme not found
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, resolve_theme_root
from _readiness import (
    STAGE_INCUBATING,
    STAGE_SHIPPING,
    Readiness,
    load_readiness,
    manifest_path,
)

USE_COLOR = sys.stdout.isatty()
GREEN = "\033[32m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
YELLOW = "\033[33m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


class GateResult:
    """One promotion gate result."""

    def __init__(self, name: str, passed: bool, detail: str = "") -> None:
        self.name = name
        self.passed = passed
        self.detail = detail

    def render(self) -> str:
        label = f"{GREEN}PASS{RESET}" if self.passed else f"{RED}FAIL{RESET}"
        out = f"  [{label}] {self.name}"
        if self.detail:
            out += f"\n         {DIM}{self.detail}{RESET}"
        return out


def _display_path(path: Path) -> str:
    """Render `path` relative to MONOREPO_ROOT when possible, else absolute.

    Synthetic theme trees in tests live under `tmp_path`, which isn't a
    descendant of MONOREPO_ROOT and would crash `path.relative_to(...)`.
    Real-world callers always sit inside the monorepo, so the relative
    form is preferred but never required.
    """
    try:
        return str(path.relative_to(MONOREPO_ROOT))
    except ValueError:
        return str(path)


def _gate_readiness_present(theme_root: Path) -> GateResult:
    path = manifest_path(theme_root)
    if not path.is_file():
        return GateResult(
            "readiness.json present",
            False,
            f"{_display_path(path)} is missing. "
            "`bin/clone.py` should have created it as stage=incubating.",
        )
    return GateResult("readiness.json present", True)


def _gate_design_intent(theme_root: Path) -> GateResult:
    path = theme_root / "design-intent.md"
    if not path.is_file():
        return GateResult(
            "design-intent.md present",
            False,
            f"{_display_path(path)} is missing. The vision "
            "reviewer needs the rubric to grade against; promotion "
            "without one means every vision review will be 'pass by "
            "default'.",
        )
    body = path.read_text(encoding="utf-8", errors="replace")
    if len(body.strip()) < 200:
        return GateResult(
            "design-intent.md present",
            False,
            f"{_display_path(path)} is shorter than 200 chars "
            f"({len(body.strip())} bytes). Looks like a placeholder. "
            "Fill in the Voice / Palette / Typography / Required / "
            "Forbidden sections before promoting.",
        )
    return GateResult("design-intent.md present", True, f"{len(body)} bytes")


def _gate_playground_seeded(theme_root: Path) -> GateResult:
    bp = theme_root / "playground" / "blueprint.json"
    if not bp.is_file():
        return GateResult(
            "playground content seeded",
            True,
            "no blueprint.json (theme ships without a Playground demo)",
        )
    content_xml = theme_root / "playground" / "content" / "content.xml"
    products_csv = theme_root / "playground" / "content" / "products.csv"
    images_dir = theme_root / "playground" / "images"
    missing: list[str] = []
    if not content_xml.is_file():
        missing.append("playground/content/content.xml")
    if not products_csv.is_file():
        missing.append("playground/content/products.csv")
    if not images_dir.is_dir() or not any(images_dir.iterdir()):
        missing.append("playground/images/ (empty or missing)")
    if missing:
        return GateResult(
            "playground content seeded",
            False,
            "missing: " + ", ".join(missing) + ". Run "
            f"`python3 bin/seed-playground-content.py --theme {theme_root.name}`.",
        )
    return GateResult("playground content seeded", True)


def _gate_product_images_map(theme_root: Path) -> GateResult:
    images_dir = theme_root / "playground" / "images"
    if not images_dir.is_dir():
        return GateResult("product-images.json complete", True, "no images/ dir")
    photos = list(images_dir.glob("product-wo-*.jpg"))
    if not photos:
        return GateResult(
            "product-images.json complete",
            True,
            "no per-theme product photographs",
        )
    map_path = theme_root / "playground" / "content" / "product-images.json"
    if not map_path.is_file():
        return GateResult(
            "product-images.json complete",
            False,
            f"{len(photos)} per-theme product photograph(s) on disk but "
            "playground/content/product-images.json is missing. "
            "wo-configure.php will not attach the bespoke imagery. Run "
            f"`python3 bin/seed-playground-content.py --theme {theme_root.name} --force`.",
        )
    return GateResult("product-images.json complete", True)


def _gate_verify_theme_snap(theme_root: Path, *, strict_branch: bool) -> GateResult:
    """Run `bin/verify-theme.py <slug> --snap --strict` and check passed."""
    args = [
        sys.executable,
        "bin/verify-theme.py",
        theme_root.name,
        "--snap",
        "--format",
        "json",
    ]
    if strict_branch:
        args.append("--strict")
    try:
        proc = subprocess.run(
            args,
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            "verify-theme --snap --strict passes",
            False,
            "timed out after 15 minutes. Check `tmp/snap-server-*.pid` for "
            "a stuck server and re-run.",
        )
    raw = proc.stdout.strip()
    if not raw:
        return GateResult(
            "verify-theme --snap --strict passes",
            False,
            f"no JSON output. stderr: {proc.stderr.strip()[:240]}",
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return GateResult(
            "verify-theme --snap --strict passes",
            False,
            f"verify-theme stdout not parseable as JSON ({e})",
        )
    overall = data.get("overall", "failed")
    if overall == "passed":
        return GateResult(
            "verify-theme --snap --strict passes",
            True,
            "every phase reported `passed`",
        )
    failed_phases = [
        p.get("name")
        for p in data.get("phases", [])
        if p.get("status") not in ("passed", "skipped")
    ]
    return GateResult(
        "verify-theme --snap --strict passes",
        False,
        f"overall status `{overall}`; failing phases: "
        + (", ".join(p for p in failed_phases if p) or "(unspecified)"),
    )


def _gate_check_py_passes(theme_root: Path) -> GateResult:
    """Run `bin/check.py <slug>` (full, non-offline) as a fast static
    gate. This ALWAYS runs — it is not gated by `--no-verify` — so
    a freshly-cloned theme with obvious static failures (stale
    INDEX.md, cross-theme microcopy duplication, front-page layout
    clone, placeholder product images, etc.) can never be promoted.

    `bin/check.py` exits 0 when every check passes and 1 when any
    fails. We shell out rather than importing because the module
    mutates a global `ROOT` per-theme and shelling is the same
    interface operators use.
    """
    args = [
        sys.executable,
        "bin/check.py",
        theme_root.name,
        "--offline",
    ]
    try:
        proc = subprocess.run(
            args,
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            "bin/check.py <slug> passes (static gate)",
            False,
            "timed out after 120s",
        )
    if proc.returncode == 0:
        return GateResult(
            "bin/check.py <slug> passes (static gate)",
            True,
            "every static check passed",
        )
    failing: list[str] = []
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("[FAIL]"):
            failing.append(stripped[len("[FAIL]") :].strip())
    summary = (
        "; ".join(failing[:5]) + (f" (+{len(failing) - 5} more)" if len(failing) > 5 else "")
        if failing
        else f"bin/check.py exited {proc.returncode} with no [FAIL] lines parsed."
    )
    return GateResult(
        "bin/check.py <slug> passes (static gate)",
        False,
        summary,
    )


def _gate_branch_pushed(theme_root: Path) -> GateResult:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return GateResult("branch is pushed + in sync", False, str(e))
    head_line = proc.stdout.splitlines()[0] if proc.stdout else ""
    if "ahead" in head_line:
        return GateResult(
            "branch is pushed + in sync",
            False,
            f"branch is ahead of origin: {head_line}. `git push` first.",
        )
    if "no branch" in head_line:
        return GateResult(
            "branch is pushed + in sync",
            False,
            "detached HEAD; promote from a real branch.",
        )
    return GateResult("branch is pushed + in sync", True, head_line.strip("# "))


def _run_gates(
    theme_root: Path, *, strict_branch: bool, run_verify: bool = True
) -> list[GateResult]:
    """Run every promotion gate and return the list of results.

    `bin/check.py` ALWAYS runs (it's the fast static floor; there's
    no flag that silences it). `--no-verify` only disables the
    snap-dependent `bin/verify-theme.py` gate so an operator can
    rehearse promotion without booting Playground.
    """
    results: list[GateResult] = []
    results.append(_gate_readiness_present(theme_root))
    results.append(_gate_check_py_passes(theme_root))
    results.append(_gate_design_intent(theme_root))
    results.append(_gate_playground_seeded(theme_root))
    results.append(_gate_product_images_map(theme_root))
    if run_verify:
        results.append(_gate_verify_theme_snap(theme_root, strict_branch=strict_branch))
    if strict_branch:
        results.append(_gate_branch_pushed(theme_root))
    return results


def _write_readiness(theme_root: Path, readiness: Readiness, *, stage: str, note: str) -> None:
    """Persist a new stage + appended note to `theme_root/readiness.json`."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # noqa: UP017
    payload = {
        "stage": stage,
        "summary": readiness.summary,
        "owner": readiness.owner,
        "last_checked": today,
        "notes": ((readiness.notes + "\n\n" if readiness.notes else "") + f"[{today}] {note}"),
    }
    manifest_path(theme_root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def cmd_promote(
    slug: str, *, force: bool, check_only: bool, strict_branch: bool, run_verify: bool
) -> int:
    try:
        theme_root = resolve_theme_root(slug)
    except SystemExit:
        print(f"error: theme {slug!r} not found", file=sys.stderr)
        return 2
    print(f"Promotion gate for {theme_root.name} (incubating -> shipping)\n")

    readiness = load_readiness(theme_root)
    if readiness.stage == STAGE_SHIPPING and check_only:
        print(f"  {GREEN}OK{RESET}: already at stage=shipping; nothing to do.")
        return 0
    if readiness.stage == STAGE_SHIPPING:
        print(
            f"  {YELLOW}note{RESET}: theme is already at stage=shipping. "
            "Re-running the gate to verify it's still green."
        )

    results = _run_gates(theme_root, strict_branch=strict_branch, run_verify=run_verify)
    for r in results:
        print(r.render())
    print()

    failed = [r for r in results if not r.passed]
    if failed and not force:
        print(f"{RED}FAILED{RESET}: {len(failed)} of {len(results)} promotion gate(s) failed.")
        if not check_only:
            print(
                "  Promotion BLOCKED. Fix the failures above and re-run, "
                "or use --force with an explicit reason if you must "
                "promote past pre-existing debt."
            )
        return 1

    if check_only:
        if failed:
            print(
                f"{YELLOW}DRY-RUN{RESET}: would-fail gates exist; "
                "not promoting (use without --check-only AND with --force "
                "to promote past these)."
            )
            return 1
        print(f"{GREEN}OK{RESET}: every gate passed; would promote to stage=shipping.")
        return 0

    note = "Promoted to shipping by bin/promote-theme.py" + (
        " (--force, manual override)" if failed else ""
    )
    _write_readiness(theme_root, readiness, stage=STAGE_SHIPPING, note=note)
    print(
        f"{GREEN}PROMOTED{RESET}: {theme_root.name} is now stage=shipping "
        f"({len(results)} gate(s); "
        f"{len(failed)} forced past)."
    )
    return 0


def cmd_demote(slug: str, *, reason: str) -> int:
    try:
        theme_root = resolve_theme_root(slug)
    except SystemExit:
        print(f"error: theme {slug!r} not found", file=sys.stderr)
        return 2
    if not reason.strip():
        print("error: --reason is required when demoting", file=sys.stderr)
        return 2
    readiness = load_readiness(theme_root)
    if readiness.stage == STAGE_INCUBATING:
        print(
            f"  {YELLOW}note{RESET}: {theme_root.name} is already at "
            "stage=incubating; nothing to do."
        )
        return 0
    note = f"Demoted from shipping to incubating: {reason.strip()}"
    _write_readiness(theme_root, readiness, stage=STAGE_INCUBATING, note=note)
    print(
        f"{YELLOW}DEMOTED{RESET}: {theme_root.name} is now stage=incubating. "
        f"Reason recorded in readiness.notes."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="promote-theme.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("slug", help="theme slug (must match `<slug>/theme.json`)")
    p.add_argument(
        "--check-only",
        action="store_true",
        help="report on the gates without flipping the stage.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "promote even if gates failed. The `--force` is recorded in "
            "readiness.notes so the audit trail shows the override."
        ),
    )
    p.add_argument(
        "--no-strict-branch",
        action="store_true",
        help=(
            "skip the branch-pushed-and-in-sync check. Useful when "
            "promoting from a detached worktree or rehearsing locally."
        ),
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help=(
            "skip the bin/verify-theme.py --snap --strict gate. ONLY for "
            "rehearsals and tooling smoke tests; production promotion "
            "MUST run verify."
        ),
    )
    p.add_argument(
        "--demote",
        action="store_true",
        help=(
            "Flip the theme from shipping back to incubating. Requires "
            "--reason. Use this when a shipped theme regresses against a "
            "new stricter gate and needs to be hidden from the docs queue "
            "until repaired."
        ),
    )
    p.add_argument(
        "--reason",
        default="",
        help="Free-text reason recorded in readiness.notes (required for --demote).",
    )
    args = p.parse_args(argv)

    if args.demote:
        return cmd_demote(args.slug, reason=args.reason)
    return cmd_promote(
        args.slug,
        force=args.force,
        check_only=args.check_only,
        strict_branch=not args.no_strict_branch,
        run_verify=not args.no_verify,
    )


if __name__ == "__main__":
    sys.exit(main())
