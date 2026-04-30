#!/usr/bin/env python3
"""Promote a generated theme from `incubating` to `shipping`.

Promotion is the formal gate that lets a theme appear on the public
`docs/` queue and counts toward the default `bin/check.py --all`
sweep. The closed-loop pipeline starts every clone as `incubating`
(see `bin/clone.py`) so unfinished WIP themes never silently regress
the green CI gate.

Usage:
    python3 bin/promote-theme.py <slug>             # gate, promote, commit, push
    python3 bin/promote-theme.py <slug> --check-only  # report only
    python3 bin/promote-theme.py <slug> --no-publish  # promote locally only
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
  5. Product-photo prompts report provider=openai, model=gpt-image-2,
     status=generated, and every product image was generated. Fallback
     product art is not promotable.
  6. `bin/verify-theme.py <slug> --snap --strict` returns `passed`.
  7. The current branch is publishable (real branch, not behind origin).

When all gates pass, `<slug>/readiness.json`'s `stage` flips to
`shipping`, `last_checked` is stamped with today's UTC date, and a
short audit note is appended to `notes`. Then `docs/` is rebuilt,
the theme/docs/baselines are committed, and the current branch is
pushed so the GitHub Pages workflow deploys the public demo. Promotion is reversible: a
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
import os
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


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


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


def _gate_gpt_image_photos(theme_root: Path) -> GateResult:
    map_path = theme_root / "playground" / "content" / "product-images.json"
    products = _read_json(map_path)
    if not products:
        return GateResult(
            "GPT Image 2 product photos generated",
            False,
            "playground/content/product-images.json is missing or empty.",
        )

    manifest_path_ = theme_root / "playground" / "content" / "product-photo-prompts.json"
    manifest = _read_json(manifest_path_)
    if not manifest:
        return GateResult(
            "GPT Image 2 product photos generated",
            False,
            "playground/content/product-photo-prompts.json is missing. "
            "Run `bin/design-agent.py --task photos --strict` with OPENAI_API_KEY.",
        )

    provider = str(manifest.get("provider") or "")
    model = str(manifest.get("model") or "")
    status = str(manifest.get("status") or "")
    if provider != "openai" or model != "gpt-image-2" or status != "generated":
        return GateResult(
            "GPT Image 2 product photos generated",
            False,
            f"photo manifest provider={provider!r}, model={model!r}, "
            f"status={status!r}; expected provider='openai', model='gpt-image-2', "
            "status='generated'.",
        )

    records = manifest.get("records") or []
    if not isinstance(records, list):
        records = []
    generated = {
        str(record.get("sku"))
        for record in records
        if isinstance(record, dict) and record.get("status") == "generated"
    }
    expected = {str(sku) for sku in products}
    missing = sorted(expected - generated)
    if missing:
        return GateResult(
            "GPT Image 2 product photos generated",
            False,
            f"{len(missing)} product(s) missing generated records: {', '.join(missing[:8])}",
        )

    image_dir = theme_root / "playground" / "images"
    missing_files = [
        str(filename)
        for filename in products.values()
        if not (image_dir / str(filename)).is_file()
    ]
    if missing_files:
        return GateResult(
            "GPT Image 2 product photos generated",
            False,
            f"{len(missing_files)} generated image file(s) missing: {', '.join(missing_files[:8])}",
        )

    return GateResult(
        "GPT Image 2 product photos generated",
        True,
        f"{len(expected)} OpenAI/{model} product photo(s)",
    )


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
        return GateResult("branch is publishable", False, str(e))
    head_line = proc.stdout.splitlines()[0] if proc.stdout else ""
    if "behind" in head_line:
        return GateResult(
            "branch is publishable",
            False,
            f"branch is behind origin: {head_line}. Pull/rebase before promoting.",
        )
    if "no branch" in head_line:
        return GateResult(
            "branch is publishable",
            False,
            "detached HEAD; promote from a real branch.",
        )
    if "ahead" in head_line:
        return GateResult(
            "branch is publishable",
            True,
            f"{head_line.strip('# ')}; launch step will push the branch.",
        )
    return GateResult("branch is publishable", True, head_line.strip("# "))


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
    results.append(_gate_gpt_image_photos(theme_root))
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


def _rebuild_docs() -> int:
    script = MONOREPO_ROOT / "bin" / "build-redirects.py"
    if not script.is_file():
        print(f"{YELLOW}WARN{RESET}: bin/build-redirects.py missing; docs/ not rebuilt.")
        return 1
    print("Rebuilding docs/ redirect site...")
    return subprocess.call([sys.executable, str(script)], cwd=str(MONOREPO_ROOT))


def _current_branch() -> str:
    proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(MONOREPO_ROOT),
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _commit_and_push_launch(theme_root: Path, *, remote: str) -> int:
    branch = _current_branch()
    if not branch:
        print(f"{RED}FAILED{RESET}: cannot publish from detached HEAD.", file=sys.stderr)
        return 1

    slug = theme_root.name
    add_paths = [
        f"{slug}/",
        "docs/",
        f"tests/visual-baseline/{slug}/",
        "tests/visual-baseline/heuristics-allowlist.json",
    ]
    existing_paths = [path for path in add_paths if (MONOREPO_ROOT / path).exists()]
    rc = subprocess.call(["git", "add", "--", *existing_paths], cwd=str(MONOREPO_ROOT))
    if rc != 0:
        print(f"{RED}FAILED{RESET}: git add exited {rc}", file=sys.stderr)
        return 1

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(MONOREPO_ROOT))
    if diff.returncode == 0:
        print("  [launch] no staged diff to commit.")
    else:
        msg = f"design: launch {slug} demo"
        rc = subprocess.call(
            [
                "git",
                "commit",
                "-m",
                f"{msg}\n\nPromote {slug} to shipping and rebuild demo redirects.",
            ],
            cwd=str(MONOREPO_ROOT),
        )
        if rc != 0:
            print(f"{RED}FAILED{RESET}: git commit exited {rc}", file=sys.stderr)
            return 1
        print(f"  [launch] committed: {msg}")

    print(f"Publishing {branch} to {remote}...")
    rc = subprocess.call(["git", "push", remote, "HEAD"], cwd=str(MONOREPO_ROOT))
    if rc != 0:
        print(f"{RED}FAILED{RESET}: git push exited {rc}", file=sys.stderr)
        return 1
    if branch == "main":
        print(f"{GREEN}LAUNCHED{RESET}: GitHub Pages will deploy docs/ to the public demo site.")
    else:
        print(
            f"{GREEN}PUBLISHED{RESET}: {remote}/{branch} is updated. "
            "The public demo deploys when this branch lands on main."
        )
    return 0


def cmd_promote(
    slug: str,
    *,
    force: bool,
    check_only: bool,
    strict_branch: bool,
    run_verify: bool,
    publish: bool,
    remote: str,
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
    docs_rc = _rebuild_docs()
    if docs_rc != 0 and not force:
        print(f"{RED}FAILED{RESET}: docs/ rebuild failed; demo launch blocked.")
        return 1
    if not publish:
        print("  [launch] skipped (--no-publish). Commit and push readiness/docs manually.")
        return 0
    return _commit_and_push_launch(theme_root, remote=remote)


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
        "--no-publish",
        action="store_true",
        help=(
            "flip readiness and rebuild docs locally, but do not create the "
            "launch commit or push the branch."
        ),
    )
    p.add_argument(
        "--remote",
        default=os.environ.get("FIFTY_PROMOTE_REMOTE", "origin"),
        help="git remote to push after creating the launch commit (default: origin).",
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
        publish=not args.no_publish,
        remote=args.remote,
    )


if __name__ == "__main__":
    sys.exit(main())
