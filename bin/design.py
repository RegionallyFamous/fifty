#!/usr/bin/env python3
"""Designer-agent orchestrator: spec.json -> cloned + tokenized + seeded theme.

Why this script exists
----------------------
Building a new theme used to be a manual sequence of:

  1. `bin/clone.py` to scaffold from Obel
  2. Hand-edit `theme.json` to swap palette + fonts
  3. `bin/seed-playground-content.py` to populate `playground/content/` and
     `playground/images/`
  4. `bin/sync-playground.py` to inline shared mu-plugins into the blueprint
  5. `bin/check.py --quick` to confirm the result is structurally sound

Steps 1, 3, 4, and 5 are entirely deterministic (the same inputs always
produce the same output). Step 2 is mostly deterministic IF you know the
palette and font choices up front. This script collapses 1-5 into a single
spec-driven invocation:

    python3 bin/design.py --spec midcentury.json

The spec captures every input that wants to be authored once and applied
mechanically: slug, name, palette hexes, font families, voice keyword,
layout hints. The script does steps 1+3+4+5 by shelling out to the existing
bin/ tools, and does step 2 in-process by parse-mutate-write on the cloned
`theme.json`.

What this script DOES NOT do
----------------------------
The judgment-heavy work stays out of scope on purpose:

  * Writing the per-theme `// === BEGIN wc microcopy ===` block in
    `functions.php` (intricate WP-hook PHP that needs LLM judgment).
  * Generating product photographs (image generation is an LLM/agent step;
    `BRIEF.md` records the expected paths and naming).
  * Restructuring `templates/front-page.html` per the layout hints
    (every theme's homepage must be structurally distinct, which is
    exactly the kind of design judgment a deterministic script shouldn't
    pretend to make).

After this script finishes, read the emitted `BRIEF.md` and continue with
the `.claude/skills/design-theme` flow (or `build-block-theme-variant` for
the long-form judgment work).

Phase model
-----------
The pipeline has named phases A-O. Every phase is idempotent and can be
retried, every phase failure exits 1 by default (use `--no-strict` to
get the legacy informational behaviour for the check phase).

  A. validate      - parse + validate the spec (always runs, dry-run stops here)
  B. clone         - bin/clone.py (skipped if --skip-clone or theme exists)
  C. apply         - palette + fonts written to <slug>/theme.json + BRIEF.md
  D. index         - bin/build-index.py <slug> -- refreshes <slug>/INDEX.md
  E. seed          - bin/seed-playground-content.py (HARD-fail under default strict)
  F. sync          - bin/sync-playground.py
  G. snap          - bin/snap.py shoot <slug> -- generates tmp/snaps/<slug>/...
  H. vision-review - bin/snap-vision-review.py <slug> (skipped without ANTHROPIC_API_KEY)
  I. baseline      - promote baselines for routes that have none yet (no-op if all
                     baselines already exist; pass --rebaseline to force)
  J. screenshot    - bin/build-theme-screenshots.py <slug> -- derives screenshot.png
                     from the baseline so check_theme_screenshots_distinct passes
  K. check         - bin/check.py <slug> --quick -- runs against fresh evidence
  L. report        - bin/snap.py report <slug> -- writes tmp/snaps/<slug>/review.md
  M. redirects     - bin/build-redirects.py -- regenerates docs/ so the new theme
                     shows up at demo.regionallyfamous.com/<slug>/...
  N. commit        - `git add <slug>/ docs/ tests/visual-baseline/<slug>/`
                     + `git commit -m "design: ship <slug> theme"`. Pre-commit
                     hooks run normally (no --no-verify). Skipped via
                     --skip-commit.
  O. publish       - `git push origin <current-branch>`. GH Pages picks up
                     docs/ automatically, so the theme is live at
                     demo.regionallyfamous.com/<slug>/ within minutes.
                     Skipped via --skip-publish.

Use `--from PHASE` to start mid-pipeline (e.g. you tweaked the spec and
only want to re-run phases C onward without re-cloning), or `--only PHASE`
to run a single phase (e.g. just re-emit the brief after editing the spec).

Output
------
On success: prints a STATUS: PASS line and the path to BRIEF.md.
On failure: prints STATUS: FAIL with the failing phase named, exits 1.

Examples
--------
Print an example spec to stand up your first build::

    python3 bin/design.py --print-example-spec > tmp/midcentury.json

Validate a spec without touching the filesystem::

    python3 bin/design.py --spec tmp/midcentury.json --dry-run

Run the full pipeline::

    python3 bin/design.py --spec tmp/midcentury.json

Re-run only the apply phase (after editing the spec's palette)::

    python3 bin/design.py --spec tmp/midcentury.json --only apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _design_lib import (  # noqa: E402
    ValidatedSpec,
    apply_fonts,
    apply_palette,
    example_spec,
    make_brief,
    serialize_theme_json,
    validate_spec,
)
from _lib import MONOREPO_ROOT  # noqa: E402

PHASES = (
    "validate",
    "clone",
    "apply",
    "index",
    "seed",
    "sync",
    "snap",
    "vision-review",
    "baseline",
    "screenshot",
    "check",
    "report",
    "redirects",
    # N. commit — stages the theme directory + generated artifacts and
    #             creates one "design: ship <slug>" commit on the
    #             current branch. Runs only if every earlier phase was
    #             green (PhaseError in any preceding handler aborts
    #             before we reach here). Pre-commit hooks run normally;
    #             --no-verify is never used.
    "commit",
    # O. publish — `git push` of the freshly-created commit. Existing
    #              GitHub Pages workflow picks up docs/ automatically,
    #              so the new theme (or its freshly-re-baselined chrome)
    #              is live at demo.regionallyfamous.com within minutes.
    "publish",
)


class PhaseError(RuntimeError):
    """One phase failed. The phase name is in `args[0]` and the printable
    detail (subprocess stderr, exception message, etc.) is in `args[1]`."""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="design.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--spec",
        type=Path,
        help="Path to a spec JSON file (see --print-example-spec for the shape).",
    )
    p.add_argument(
        "--prompt",
        type=str,
        default=None,
        help=(
            "Natural-language theme description; resolved to a spec.json by "
            "`bin/spec-from-prompt.py` before phase dispatch. Mutually exclusive "
            "with --spec. The resolved spec is written to "
            "tmp/specs/<slug>.json so subsequent phases (or re-runs) can use "
            "--spec on it directly."
        ),
    )
    p.add_argument(
        "--print-example-spec",
        action="store_true",
        help=(
            "Dump the canonical example spec to stdout and exit 0. Pipe to a file, "
            "edit, then re-run with `--spec <file>`."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the spec only; touch nothing on disk and exit.",
    )
    p.add_argument(
        "--from",
        dest="from_phase",
        choices=PHASES,
        default="validate",
        help="Start the pipeline at this phase (skips earlier phases). Default: validate.",
    )
    p.add_argument(
        "--only",
        choices=PHASES,
        default=None,
        help="Run exactly one phase and stop (overrides --from).",
    )
    p.add_argument(
        "--skip-clone",
        action="store_true",
        help=(
            "Don't fail if the destination theme directory already exists. "
            "Useful when iterating on a spec for a theme you already cloned."
        ),
    )
    p.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        default=True,
        help=(
            "Demote the check phase from FAIL to WARN. Use only when iterating "
            "on a spec and you want to read BRIEF.md before fixing every issue. "
            "Default is strict (any phase failure exits 1) because a 50-theme "
            "batch run cannot babysit individual themes."
        ),
    )
    p.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        help=argparse.SUPPRESS,  # legacy alias; default is now strict.
    )
    p.add_argument(
        "--rebaseline",
        action="store_true",
        help=(
            "In the baseline phase, re-baseline EVERY route (not just the ones "
            "with no existing baseline). Use after an intentional visual change."
        ),
    )
    p.add_argument(
        "--skip-snap",
        action="store_true",
        help=(
            "Skip the snap, vision-review, baseline, and report phases. Useful "
            "for rapid spec iteration where Playground boot (~30-60s) dominates "
            "the loop. The next un-skipped run will catch up."
        ),
    )
    p.add_argument(
        "--vision-budget",
        type=float,
        default=2.0,
        help=(
            "Per-theme vision-review budget cap in USD (default: 2.0). Forwards "
            "to FIFTY_VISION_DAILY_BUDGET so the daily ledger still applies."
        ),
    )
    p.add_argument(
        "--source",
        default=None,
        help=(
            "Override the spec's `source` theme (default: spec.source, then 'obel'). "
            "Mostly useful for tests cloning from a fixture theme."
        ),
    )
    p.add_argument(
        "--skip-commit",
        action="store_true",
        help=(
            "Skip phase N (commit) and phase O (publish). Use for local "
            "iteration where you want to eyeball the theme and BRIEF.md "
            "before anything lands in git. Default is commit + publish — "
            "a design.py run that goes green SHOULD ship, because the "
            "gates already prove every theme invariant holds."
        ),
    )
    p.add_argument(
        "--skip-publish",
        action="store_true",
        help=(
            "Commit locally but don't push. Useful when you want to "
            "review the commit before it reaches the remote."
        ),
    )
    p.add_argument(
        "--publish-remote",
        default="origin",
        help="Git remote to push to in phase O. Default: origin.",
    )
    p.add_argument(
        "--publish-branch",
        default=None,
        help=(
            "Branch to push in phase O. Default: whichever branch "
            "HEAD currently points at (i.e. the branch you're working "
            "on). Explicit override is there for CI scenarios."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.print_example_spec:
        json.dump(example_spec(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if args.prompt and args.spec:
        print(
            "error: --prompt and --spec are mutually exclusive (pick one input source)",
            file=sys.stderr,
        )
        return 2

    if args.prompt:
        try:
            args.spec = _resolve_prompt_to_spec(args.prompt)
        except PhaseError as e:
            print(f"\nSTATUS: FAIL (phase {e.args[0]})", file=sys.stderr)
            print(f"  {e.args[1]}", file=sys.stderr)
            return 1
        print(f"design.py: prompt resolved to spec at {args.spec}")

    if not args.spec:
        print(
            "error: provide --spec PATH or --prompt STR (or --print-example-spec)",
            file=sys.stderr,
        )
        return 2

    if not args.spec.is_file():
        print(f"error: spec file not found: {args.spec}", file=sys.stderr)
        return 2

    try:
        raw_spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: spec is not valid JSON: {e}", file=sys.stderr)
        return 2

    errors, spec = validate_spec(raw_spec)
    if errors or spec is None:
        print("error: spec validation failed:", file=sys.stderr)
        for err in errors:
            print(str(err), file=sys.stderr)
        return 2

    if args.source:
        spec.source = args.source

    if args.dry_run:
        print(f"OK: spec is valid for theme `{spec.slug}` (source: {spec.source}).")
        print(
            f"     palette: {len(spec.palette)} slug(s); "
            f"fonts: {len(spec.fonts)} slug(s); "
            f"layout hints: {len(spec.layout_hints)}."
        )
        return 0

    phases_to_run = _select_phases(args.from_phase, args.only)
    if args.skip_snap and not args.only:
        # `screenshot` is derived from the baseline PNG so it's equally
        # dependent on a fresh snap; group it with the snap phases.
        phases_to_run = [
            p for p in phases_to_run
            if p not in {"snap", "vision-review", "baseline",
                         "screenshot", "report"}
        ]
    if args.skip_commit and not args.only:
        # --skip-commit also implies --skip-publish: you can't publish a
        # commit that doesn't exist. Drop both.
        phases_to_run = [p for p in phases_to_run
                         if p not in {"commit", "publish"}]
    elif args.skip_publish and not args.only:
        phases_to_run = [p for p in phases_to_run if p != "publish"]
    print(f"design.py: running phases {' -> '.join(phases_to_run)} for `{spec.slug}`")

    dest = MONOREPO_ROOT / spec.slug
    try:
        for phase in phases_to_run:
            handler = _PHASE_HANDLERS[phase]
            handler(spec, dest, args)
    except PhaseError as e:
        phase, detail = e.args
        print(f"\nSTATUS: FAIL (phase {phase})", file=sys.stderr)
        print(f"  {detail}", file=sys.stderr)
        return 1

    print("\nSTATUS: PASS")
    print(f"  Theme:  {dest}")
    print(f"  Brief:  {dest / 'BRIEF.md'}")
    print("  Next:   read BRIEF.md, then continue with .claude/skills/design-theme.")
    return 0


def _select_phases(from_phase: str, only: str | None) -> list[str]:
    if only:
        return [only]
    start = PHASES.index(from_phase)
    return list(PHASES[start:])


def _phase_validate(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """No-op at runtime — validation already happened before phase dispatch.
    Present in PHASES so `--only validate` and `--from validate` are
    self-consistent with the rest."""
    return


def _phase_clone(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/clone.py <slug> --source <source>` if `dest` doesn't exist
    yet. With `--skip-clone`, accept an existing dest (useful when iterating
    on the spec without re-cloning)."""
    if dest.exists():
        if args.skip_clone:
            print(f"  [clone] skipping: {dest} already exists (--skip-clone)")
            return
        raise PhaseError(
            "clone",
            f"{dest} already exists. Pass --skip-clone to operate on it in place, "
            "or delete it first.",
        )

    source_dir = MONOREPO_ROOT / spec.source
    if not source_dir.is_dir():
        raise PhaseError("clone", f"source theme `{spec.source}` not found at {source_dir}")

    cmd = [
        sys.executable,
        str(ROOT / "bin" / "clone.py"),
        spec.slug,
        "--source",
        str(source_dir),
    ]
    print(f"  [clone] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("clone", f"bin/clone.py exited {rc}")


def _phase_apply(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Apply palette + fonts to `<slug>/theme.json`, write `<slug>/BRIEF.md`."""
    theme_json_path = dest / "theme.json"
    if not theme_json_path.is_file():
        raise PhaseError("apply", f"{theme_json_path} not found (did clone phase run?)")

    try:
        theme_json = json.loads(theme_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PhaseError("apply", f"{theme_json_path} is not valid JSON: {e}") from e

    if spec.palette:
        apply_palette(theme_json, spec.palette)
    if spec.fonts:
        apply_fonts(theme_json, spec.fonts)

    theme_json_path.write_text(serialize_theme_json(theme_json), encoding="utf-8")
    print(f"  [apply] wrote {theme_json_path.relative_to(MONOREPO_ROOT)} ({len(spec.palette)} color(s), {len(spec.fonts)} font slot(s))")

    brief_path = dest / "BRIEF.md"
    brief_path.write_text(make_brief(spec, dest), encoding="utf-8")
    print(f"  [apply] wrote {brief_path.relative_to(MONOREPO_ROOT)}")


def _phase_index(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/build-index.py <slug>` so the theme's INDEX.md reflects the
    newly cloned + palette-applied surface before the `check` phase runs
    `check_index_in_sync`. Without this, a brand-new theme ships without
    an INDEX.md (or with the source theme's) and check.py hard-fails. Soft
    warnings only; the check phase below is the authoritative gate."""
    script = ROOT / "bin" / "build-index.py"
    if not script.is_file():
        print("  [index] WARN: bin/build-index.py missing; skipping.")
        return
    cmd = [sys.executable, str(script), spec.slug]
    print(f"  [index] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("index", f"bin/build-index.py exited {rc}")


def _phase_seed(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/seed-playground-content.py --theme <slug>` to populate
    `<slug>/playground/content/` and `<slug>/playground/images/`.

    Hard-fails on a non-zero exit: a theme without seeded playground
    content can't be shot, can't be vision-reviewed, and will silently
    pass downstream gates by skipping them (the loophole that made
    50-theme batch runs unreliable). Use `--no-strict` only when you're
    iterating manually and intend to fix seed errors yourself.
    """
    cmd = [sys.executable, str(ROOT / "bin" / "seed-playground-content.py"), "--theme", spec.slug]
    print(f"  [seed] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        if args.strict:
            raise PhaseError("seed", f"bin/seed-playground-content.py exited {rc}")
        print(f"  [seed] WARN: bin/seed-playground-content.py exited {rc}; continuing (--no-strict).")


def _phase_sync(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/sync-playground.py` to refresh inlined mu-plugin payloads in
    every theme's blueprint (the script touches all themes; the new one
    becomes part of the set automatically)."""
    cmd = [sys.executable, str(ROOT / "bin" / "sync-playground.py")]
    print(f"  [sync] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("sync", f"bin/sync-playground.py exited {rc}")


def _phase_snap(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/snap.py shoot <slug>` to generate fresh PNGs + axe + heuristic
    findings under `tmp/snaps/<slug>/`. This is the evidence the check phase
    consumes — without it, FIFTY_REQUIRE_SNAP_EVIDENCE=1 in CI/pre-push will
    fail because the no-snap path is no longer a silent skip."""
    cmd = [sys.executable, str(ROOT / "bin" / "snap.py"), "shoot", spec.slug]
    print(f"  [snap] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("snap", f"bin/snap.py shoot exited {rc}")


def _phase_vision_review(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/snap-vision-review.py <slug>` against the freshly shot PNGs.
    Skipped (with a warning) when ANTHROPIC_API_KEY is unset so airgapped /
    fixture runs don't fail; CI sets the key.

    Forwards `--vision-budget` as FIFTY_VISION_BUDGET_USD (the per-invocation
    cap); the daily ledger at FIFTY_VISION_DAILY_BUDGET still applies on top.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [vision-review] WARN: ANTHROPIC_API_KEY unset; skipping vision review.")
        return

    env = os.environ.copy()
    env["FIFTY_VISION_BUDGET_USD"] = f"{args.vision_budget:.4f}"
    cmd = [
        sys.executable,
        str(ROOT / "bin" / "snap-vision-review.py"),
        spec.slug,
    ]
    print(f"  [vision-review] {' '.join(cmd[1:])} (budget=${args.vision_budget:.2f})")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT), env=env)
    if rc != 0:
        raise PhaseError("vision-review", f"bin/snap-vision-review.py exited {rc}")


def _phase_baseline(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Promote freshly shot PNGs to `tests/visual-baseline/<slug>/` for any
    route that has no baseline yet. With `--rebaseline`, refresh every
    route. This phase is a no-op once every route has a committed baseline,
    so re-running design.py on an existing theme won't churn baselines."""
    cmd = [sys.executable, str(ROOT / "bin" / "snap.py"), "baseline", spec.slug]
    if args.rebaseline:
        cmd.append("--rebaseline")
    else:
        cmd.append("--missing-only")
    print(f"  [baseline] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("baseline", f"bin/snap.py baseline exited {rc}")


def _phase_screenshot(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/build-theme-screenshots.py <slug>` to derive the theme's
    WordPress admin `screenshot.png` from the freshly promoted baseline.

    Check.py's `check_theme_screenshots_distinct` rejects any theme that
    ships the source theme's screenshot bytes unchanged. Without this
    phase, a brand-new clone keeps its source's screenshot.png verbatim,
    and the git pre-commit hook fails at the last mile of the build.
    We bake the derivation into the pipeline so the gate stays green
    without a separate manual step."""
    script = ROOT / "bin" / "build-theme-screenshots.py"
    if not script.is_file():
        print("  [screenshot] WARN: bin/build-theme-screenshots.py missing; skipping.")
        return
    cmd = [sys.executable, str(script), spec.slug]
    print(f"  [screenshot] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        # Non-strict so a missing baseline (e.g. --skip-snap flow) doesn't
        # abort the whole run; check.py will still flag the mismatch.
        print(f"  [screenshot] WARN: bin/build-theme-screenshots.py exited {rc}; "
              "check.py will flag if screenshot.png is stale.")


def _phase_check(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/check.py <slug> --quick` for a fast static gate. With strict
    (the default), propagate failures; with `--no-strict`, print a hint
    and continue.

    `--quick` skips the network-dependent block-name validator so this
    works in airgapped environments. The full gate (with `check.py --all
    --offline`) runs in CI on push.

    Sets FIFTY_REQUIRE_SNAP_EVIDENCE=1 so any missing snap evidence is a
    FAIL rather than a silent SKIP — the snap phase already ran above,
    so absence here means snap.py crashed without raising."""
    env = os.environ.copy()
    env.setdefault("FIFTY_REQUIRE_SNAP_EVIDENCE", "1")
    cmd = [sys.executable, str(ROOT / "bin" / "check.py"), spec.slug, "--quick"]
    print(f"  [check] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT), env=env)
    if rc == 0:
        return
    if args.strict:
        raise PhaseError("check", f"bin/check.py exited {rc}")
    print(
        f"  [check] WARN: bin/check.py exited {rc}. Running under --no-strict so "
        "this is informational -- read BRIEF.md, fix issues, then re-run "
        f"`python3 bin/check.py {spec.slug} --quick` until green before committing."
    )


def _phase_report(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/snap.py report <slug>` to write the human-readable
    `tmp/snaps/<slug>/review.md` summarising findings + cost. Soft-fails
    with a warning so a missing report doesn't undo a green check."""
    cmd = [sys.executable, str(ROOT / "bin" / "snap.py"), "report", spec.slug]
    print(f"  [report] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        print(f"  [report] WARN: bin/snap.py report exited {rc}; theme is still green.")


def _phase_redirects(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/build-redirects.py` so the new theme's short URLs appear
    on `demo.regionallyfamous.com` and the landing page lists it.

    This was a missing step in the Foundry build: the theme shipped and
    merged but the Pages site didn't list it until a manual follow-up
    commit. build-redirects.py regenerates every theme's docs/ entries
    from scratch each run so it's safe to re-invoke on every design.py
    run — incremental is a no-op. Soft-fails with a warning so a docs
    regen glitch never blocks a theme landing."""
    script = ROOT / "bin" / "build-redirects.py"
    if not script.is_file():
        print("  [redirects] WARN: bin/build-redirects.py missing; skipping.")
        return
    cmd = [sys.executable, str(script)]
    print(f"  [redirects] {' '.join(cmd)}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        print(f"  [redirects] WARN: bin/build-redirects.py exited {rc}; "
              "run manually and commit the docs/ diff to publish to GH Pages.")


def _phase_commit(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Stage the theme's files + generated artifacts and create one
    "design: ship <slug>" commit on the current branch.

    Why this phase exists
    ---------------------
    Before Phase N existed, a green `design.py` run ended with the
    theme sitting in an unstaged working tree. Every real run required
    a follow-up `git add -A` / `git commit` cycle by the operator.
    That cycle was the source of the Foundry "theme merged but demo
    site never listed it" bug — nobody remembered to commit
    `docs/` after the build, so GitHub Pages never rebuilt and the
    live demo showed four themes for two weeks. Phase N + Phase O
    together make "design.py green" mean "the theme is on the remote
    and on its way to production."

    Safety rails
    ------------
      * Runs only if every earlier phase succeeded. Any `PhaseError`
        raised upstream short-circuits `main()` before it reaches us.
      * Honours pre-commit hooks (NEVER uses `--no-verify`). If the
        hook edits files (autoformatter) and wants to re-stage, the
        operator resolves that on their own next iteration; we never
        amend or re-commit automatically, because that hides signals.
      * If `git status --porcelain` is empty (nothing to commit — e.g.
        someone already committed the theme between runs), we skip
        with an info line instead of failing. Rerunnable by design.
      * If the commit exits non-zero we raise `PhaseError("commit",
        …)` so the operator sees a STATUS: FAIL with the phase name
        and the git output.
    """
    slug = spec.slug
    # `git -C <repo-root>` is explicit about WHERE the ops run, even
    # though MONOREPO_ROOT is always the cwd for other phase
    # subprocesses. The extra clarity is worth a few characters.
    git = ["git", "-C", str(MONOREPO_ROOT)]

    # Scope the stage to the directories we actually wrote. A blanket
    # `git add -A` would sweep unrelated WIP in the operator's working
    # tree into our commit — a hostile move in a monorepo where many
    # branches share the checkout. Named paths only.
    paths = [
        f"{slug}/",
        f"tests/visual-baseline/{slug}/",
        "docs/",
        # The two shared-tooling scripts that this phase touches via
        # append-wc-overrides.py / sync-playground.py chains. Not
        # strictly our outputs, but if they changed as a side effect
        # of design.py they need to ride along or the next run sees
        # a dirty tree.
        "bin/append-wc-overrides.py",
    ]
    existing = [p for p in paths if (MONOREPO_ROOT / p).exists()]
    if not existing:
        print(f"  [commit] WARN: none of {paths!r} exist; nothing to commit.")
        return

    rc = subprocess.call([*git, "add", "--", *existing])
    if rc != 0:
        raise PhaseError("commit", f"git add exited {rc}")

    # Is there anything actually staged? A repeat run where the theme
    # already matches HEAD will have `git add` succeed with 0 paths,
    # and a commit with no diff will fail loudly — we'd rather print
    # "nothing to commit" and move on.
    proc = subprocess.run(
        [*git, "diff", "--cached", "--quiet"], capture_output=True
    )
    if proc.returncode == 0:
        print(f"  [commit] skip: no staged diff for {slug} "
              "(theme already matches HEAD).")
        return

    message = f"design: ship {slug} theme\n\nGenerated by bin/design.py"
    cproc = subprocess.run(
        [*git, "commit", "-m", message],
        capture_output=True, text=True,
    )
    if cproc.returncode != 0:
        # Surface both stdout and stderr so a pre-commit-hook failure
        # (which typically goes to stderr) AND a git message (which
        # goes to stdout) are visible.
        detail = (cproc.stdout + "\n" + cproc.stderr).strip()
        raise PhaseError("commit", f"git commit exited {cproc.returncode}: {detail}")

    # Log the SHA of the new commit so the operator can paste it into
    # the PR / issue / Linear ticket without another `git log`.
    sha_proc = subprocess.run(
        [*git, "rev-parse", "HEAD"], capture_output=True, text=True
    )
    sha = sha_proc.stdout.strip()[:12] if sha_proc.returncode == 0 else "(unknown)"
    print(f"  [commit] {sha}  design: ship {slug} theme")


def _phase_publish(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Push the current branch to `--publish-remote` (default: origin).

    Runs only if Phase N produced a commit (or the branch was already
    ahead of the remote from an earlier run) and every earlier phase
    was green. The existing GitHub Pages workflow picks up any diff
    under `docs/` automatically, so the new theme's short URL
    (`demo.regionallyfamous.com/<slug>/`) goes live within minutes.

    Safety rails
    ------------
      * Never `--force`. A rejected push is a signal that the local
        branch is behind the remote; the operator resolves that
        manually so we never overwrite someone else's work.
      * Pushes the branch HEAD is on, not a hardcoded `main`. In CI
        this is main; in a day-to-day operator checkout it's the
        feature branch the design lives on.
      * If `git push` fails (wrong creds, behind remote, network),
        raise `PhaseError("publish", …)` so STATUS: FAIL names the
        phase and the git output. Never swallowed.
    """
    git = ["git", "-C", str(MONOREPO_ROOT)]
    remote = args.publish_remote

    branch = args.publish_branch
    if not branch:
        # Detect the branch the operator is working on. `symbolic-ref`
        # over `rev-parse --abbrev-ref HEAD` because the former fails
        # cleanly on a detached HEAD (which is what we want — refuse
        # to publish from a detached state), whereas `rev-parse` would
        # return `HEAD` verbatim.
        proc = subprocess.run(
            [*git, "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise PhaseError(
                "publish",
                "HEAD is detached; pass --publish-branch <name> or "
                "check out a branch before running phase O.",
            )
        branch = proc.stdout.strip()
        if not branch:
            raise PhaseError(
                "publish",
                "could not determine current branch; pass --publish-branch.",
            )

    # Is the local branch actually ahead of the remote tracking? If
    # not, there's nothing to push and the phase is a no-op. This
    # handles two cases cleanly: (a) Phase N skipped because theme
    # was already committed, AND (b) the operator already pushed
    # this branch in an earlier run.
    ahead_proc = subprocess.run(
        [*git, "status", "--porcelain=2", "--branch"],
        capture_output=True, text=True,
    )
    ahead_line = next(
        (ln for ln in ahead_proc.stdout.splitlines()
         if ln.startswith("# branch.ab ")),
        "",
    )
    if ahead_line:
        # Line shape: "# branch.ab +<ahead> -<behind>"
        try:
            ahead = int(ahead_line.split()[2].lstrip("+") or "0")
        except (IndexError, ValueError):
            ahead = -1
        if ahead == 0:
            print(f"  [publish] skip: {branch} is not ahead of "
                  f"{remote}/{branch} (nothing to push).")
            return

    print(f"  [publish] git push {remote} {branch}")
    rc = subprocess.call([*git, "push", remote, branch])
    if rc != 0:
        raise PhaseError(
            "publish",
            f"git push {remote} {branch} exited {rc}. Resolve "
            "the conflict (likely 'behind remote'), then re-run "
            "`python3 bin/design.py --spec <spec> --only publish`.",
        )
    demo_url = f"https://demo.regionallyfamous.com/{spec.slug}/"
    print(f"  [publish] {spec.slug} pushed to {remote}/{branch}")
    print(f"  [publish] demo: {demo_url} (live within ~2 min of GH Pages rebuild)")


def _resolve_prompt_to_spec(prompt: str) -> Path:
    """Invoke `bin/spec-from-prompt.py` to turn `prompt` into a spec.json,
    write it to `tmp/specs/<slug>.json`, and return the path. Raises
    PhaseError("prompt", ...) on any failure so the caller can render a
    consistent STATUS: FAIL line."""
    helper = ROOT / "bin" / "spec-from-prompt.py"
    if not helper.is_file():
        raise PhaseError(
            "prompt",
            f"bin/spec-from-prompt.py not found at {helper}; install PR gamma "
            "or pass --spec instead.",
        )
    out_dir = MONOREPO_ROOT / "tmp" / "specs"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(helper), "--prompt", prompt, "--out-dir", str(out_dir)]
    proc = subprocess.run(cmd, cwd=str(MONOREPO_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise PhaseError(
            "prompt",
            f"bin/spec-from-prompt.py exited {proc.returncode}: {proc.stderr.strip()}",
        )
    out_path_str = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    out_path = Path(out_path_str)
    if not out_path.is_file():
        raise PhaseError(
            "prompt",
            f"bin/spec-from-prompt.py did not write a spec file (got: {out_path_str!r})",
        )
    return out_path


_PHASE_HANDLERS = {
    "validate": _phase_validate,
    "clone": _phase_clone,
    "apply": _phase_apply,
    "index": _phase_index,
    "seed": _phase_seed,
    "sync": _phase_sync,
    "snap": _phase_snap,
    "vision-review": _phase_vision_review,
    "baseline": _phase_baseline,
    "screenshot": _phase_screenshot,
    "check": _phase_check,
    "report": _phase_report,
    "redirects": _phase_redirects,
    "commit": _phase_commit,
    "publish": _phase_publish,
}


if __name__ == "__main__":
    sys.exit(main())
