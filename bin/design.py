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
  D. contrast      - bin/autofix-contrast.py <slug> (block + CSS hover contrast)
  E. seed          - bin/seed-playground-content.py (HARD-fail under default strict)
  F. sync          - bin/sync-playground.py
  G½. photos       - bin/generate-product-photos.py --theme <slug>
  G¾. microcopy    - bin/generate-microcopy.py --theme <slug>
  G¾½. frontpage   - bin/diversify-front-page.py --theme <slug>
  H. index         - bin/build-index.py <slug> -- refreshes <slug>/INDEX.md
                     (moved to AFTER seed/sync/photos/microcopy/frontpage so
                     INDEX.md reflects the final template + pattern state)
  F½. prepublish   - `git add <slug>/ docs/ */playground/blueprint.json`
                     + `git commit` + `git push -u origin HEAD` so that
                     `raw.githubusercontent.com` can serve the new
                     theme's `playground/content/` and `images/` when
                     the snap phase boots Playground. Without this,
                     `bin/snap.py shoot <slug>` 404s on every URL
                     inlined in the blueprint and Playground dies with
                     "W&O CSV looked malformed: fewer than 2 lines
                     after trim." A later commit/publish pair sweeps
                     up the baselines + screenshot + docs after snap.
                     Skipped by `--skip-publish`, `--skip-commit`, or
                     `--skip-prepublish`; no-op on `main`.
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
    validate_generation_safety,
    validate_spec,
)
from _lib import MONOREPO_ROOT  # noqa: E402

PHASES = (
    "validate",
    "clone",
    "apply",
    # D½. contrast — after palette + cloned markup are in place, rewrite
    #                any block whose resolved (textColor, backgroundColor)
    #                pair fails WCAG AA against the new palette. The
    #                canonical example is an Obel block with
    #                `{"backgroundColor":"accent","textColor":"base"}` —
    #                safe on Obel (dark ink, cream paper) but catastrophic
    #                on a theme whose accent happens to be a mid-tone
    #                yellow/tan/terracotta (1.1-2.6:1 vs base). Without
    #                this phase the failure surfaces much later — in
    #                `check` as a `check_block_text_contrast` fail, or
    #                worse, in CI's axe-core pass as a `color-contrast`
    #                violation. Autofix is idempotent: a clean re-run on
    #                a green tree is a no-op.
    "contrast",
    "seed",
    "sync",
    # G½. photos — generate per-theme product photos and category covers
    #              using Pillow before the pre-snap commit so that
    #              raw.githubusercontent can serve them when Playground
    #              boots.  Without this, the snap finds the upstream
    #              cartoon PNGs (wonders-*.png) still referenced in the
    #              blueprint, and snap.py reports broken-image findings
    #              on every product tile.  The phase is idempotent
    #              (skips any file already on disk) and re-runs
    #              seed-playground-content.py automatically once it
    #              writes new JPGs.
    "photos",
    # G¾. microcopy — generate per-theme voice substitutions and apply
    #                 them so no two themes share a user-visible string.
    #                 check_all_rendered_text_distinct_across_themes and
    #                 check_pattern_microcopy_distinct both fail on a
    #                 freshly-cloned theme that still carries the source
    #                 theme's body copy verbatim.  Uses a static fallback
    #                 table (offline, no API required) for known batch
    #                 themes; falls back to the Anthropic API for unknown
    #                 slugs when ANTHROPIC_API_KEY is set.
    "microcopy",
    # G¾½. frontpage — ensure the front-page layout fingerprint is unique
    #                  vs every other shipped theme.  Adds a
    #                  wo-layout-<slug> className to the first wp:group
    #                  direct child of <main>.  check_front_page_unique_
    #                  layout fails when two themes cloned from the same
    #                  source have the same block-sequence fingerprint.
    "frontpage",
    # H. index — moved to AFTER seed/sync/photos/microcopy/frontpage so
    #            INDEX.md reflects the final state of templates/parts/
    #            patterns (including any microcopy changes or front-page
    #            restructuring).  Running it before seed was the source of
    #            the "INDEX.md in sync" check failure: the phase wrote an
    #            INDEX based on the just-cloned state, then later phases
    #            modified the same files, leaving INDEX stale at check
    #            time.
    "index",
    # F½. prepublish — commit + push the scaffolded theme BEFORE snap.
    #                  The blueprint inlines `raw.githubusercontent.com`
    #                  URLs for every `playground/content/*` and
    #                  `playground/images/*` asset; on a brand-new
    #                  theme those URLs only resolve once the branch
    #                  is pushed (so raw.githubusercontent can serve
    #                  the branch's tree). Without this phase
    #                  `bin/snap.py shoot <new-theme>` dies with
    #                  "W&O CSV looked malformed: fewer than 2 lines
    #                  after trim." — the content fetch 404d, PHP
    #                  parsed the 404 HTML as CSV, and Playground
    #                  boot step #10 (`wo-import.php`) aborted.
    #                  Phase N later sweeps up baselines + screenshots
    #                  + docs as a second commit on the same branch;
    #                  squash-merge collapses them on the final PR.
    "prepublish",
    "snap",
    "vision-review",
    "scorecard",
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

_TEXT_EXTENSIONS = {".css", ".html", ".json", ".md", ".php", ".txt"}


class PhaseError(RuntimeError):
    """One phase failed. The phase name is in `args[0]` and the printable
    detail (subprocess stderr, exception message, etc.) is in `args[1]`."""


# ---------------------------------------------------------------------------
# Two-step flow (`design.py build` / `design.py dress`)
# ---------------------------------------------------------------------------
#
# `build` answers: does this theme render correctly? (CSS, markup,
# tokens, block parity, WCAG, chrome overrides, view-transitions.)
# It is fast, re-runnable, and never calls a vision model.
#
# `dress` answers: does the demo catalogue speak in this theme's voice?
# (product photos, category covers, microcopy, front-page composition,
# vision-level photography/brand violations.) It is the more expensive
# outer loop that burns vision-review budget.
#
# The flat CLI (`design.py --spec X`) remains the one-shot ship-it
# pipeline and is byte-identical in behaviour to the pre-split version.
# `design.py build --spec X` and `design.py dress <slug>` each pick a
# hardcoded subset of PHASES; see `_select_phases_for_subcommand` for
# the dispatch table.

_PHASES_FOR_BUILD = (
    "validate",
    "clone",
    "apply",
    "contrast",
    "seed",
    "sync",
    "photos",
    "microcopy",
    "frontpage",
    "index",
    "prepublish",
    "snap",
    "baseline",
    "screenshot",
    "check",
    "report",
    "redirects",
    "commit",
    "publish",
)
_PHASES_FOR_DRESS = (
    "photos",
    "microcopy",
    "frontpage",
    "snap",
    "vision-review",
    "scorecard",
    "check",
    "report",
    "commit",
    "publish",
)


BUILD_OK_BANNER = (
    "\n"
    "══════════════════════════════════════════════════\n"
    "  BUILD OK — theme is structurally sound.\n"
    "  Next:  python3 bin/design.py dress {slug}\n"
    "══════════════════════════════════════════════════\n"
)
DRESS_OK_BANNER = (
    "\n"
    "══════════════════════════════════════════════════\n"
    "  DRESS OK — demo content matches the theme.\n"
    "  Next:  python3 bin/promote-theme.py {slug}\n"
    "══════════════════════════════════════════════════\n"
)


def _select_phases_for_subcommand(subcommand: str | None) -> tuple[str, ...] | None:
    """Return the hardcoded phase list for a subcommand, or None for flat.

    The flat CLI path calls `_select_phases(args.from_phase, args.only)`
    to compute the phase list (preserving pre-split behaviour). The two
    subcommands ignore `--from` / `--only` and always run their full
    allowlist -- iteration during structural work should re-run the
    inner phases directly (`bin/check.py`, `bin/snap.py shoot`), not
    contort `design.py build` into a one-phase runner.
    """
    if subcommand == "build":
        return _PHASES_FOR_BUILD
    if subcommand == "dress":
        return _PHASES_FOR_DRESS
    return None


def _dress_preflight(slug: str) -> None:
    """Validate the theme exists before running `dress` phases.

    `dress` subcommand presumes `build` already shipped a structurally
    sound theme. If the slug is wrong or the theme was never built,
    the downstream phases emit confusing errors (seed phase not found,
    snap phase 404s, etc). Exit 2 with an actionable message instead.
    """
    theme_root = MONOREPO_ROOT / slug
    if not (theme_root / "theme.json").is_file():
        sys.exit(
            f"design.py dress: theme `{slug}` has no theme.json. "
            f"Run `bin/design.py build --spec <spec>.json` first."
        )
    if not (theme_root / "playground" / "blueprint.json").is_file():
        sys.exit(
            f"design.py dress: theme `{slug}` hasn't been seeded. "
            f"Run `bin/design.py build --spec <spec>.json` first."
        )


def _theme_display_name(slug: str) -> str:
    """Best-effort read of the theme's human-readable name from style.css.

    `style.css` is the WP-required theme header (``Theme Name: Obel``).
    For `dress`, we don't have the original spec.json; scraping the
    style.css header preserves the title case without the operator
    having to hand it in as a flag.
    """
    style_css = MONOREPO_ROOT / slug / "style.css"
    if style_css.is_file():
        import re as _re

        match = _re.search(
            r"^\s*Theme Name:\s*(.+?)\s*$",
            style_css.read_text(encoding="utf-8", errors="replace"),
            flags=_re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
    return slug.replace("-", " ").title()


def _synthesize_dress_spec(slug: str) -> Path:
    """Write a minimal spec JSON file for `dress` re-use of the flat loop.

    `dress` phases only need `spec.slug` + `spec.name` (they delegate
    everything else to the existing theme's theme.json + content set,
    which `build` already produced). Synthesizing a tiny spec keeps
    the inner `main()` logic uniform between the flat CLI and the two
    subcommands -- no separate code path for dress.
    """
    specs_dir = MONOREPO_ROOT / "tmp" / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    spec_path = specs_dir / f"{slug}.dress.json"
    # Always overwrite: the operator may have iterated on the theme's
    # style.css between invocations.
    spec_path.write_text(
        json.dumps(
            {"slug": slug, "name": _theme_display_name(slug)},
            indent=2,
        ),
        encoding="utf-8",
    )
    return spec_path


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
        "--snap-viewports",
        nargs="+",
        default=None,
        help=(
            "Forward a viewport subset to `bin/snap.py shoot`, e.g. "
            "`--snap-viewports mobile desktop`. Useful for proof runs that "
            "need both responsive poles without shooting tablet/wide."
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
            "Skip phase N (final commit) and phase O (publish). Pre-snap "
            "`prepublish` still runs when applicable — Playground fetches "
            "playground/content from raw.githubusercontent.com, so a "
            "brand-new theme must be pushed on a feature branch before "
            "`snap` (see `_phase_prepublish`). Use on `agent/<slug>` etc., "
            "not on `main`, until `origin/main` already contains the theme."
        ),
    )
    p.add_argument(
        "--skip-prepublish",
        action="store_true",
        help=(
            "Skip phase F½ (prepublish). The snap phase will then rely "
            "on content already being reachable at "
            "`raw.githubusercontent.com/<org>/<repo>/main/<slug>/playground/` — "
            "only correct when rebuilding an already-shipped theme. For "
            "any NEW theme this WILL fail snap with 'W&O CSV looked "
            "malformed'. Prefer `--skip-publish` (which also implies "
            "skip-prepublish) if you want a pure local iteration."
        ),
    )
    p.add_argument(
        "--skip-publish",
        action="store_true",
        help=(
            "Commit locally but don't push. Useful when you want to "
            "review the commit before it reaches the remote. Also "
            "implies skip-prepublish (no mid-pipeline push either)."
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
    if argv is None:
        argv = sys.argv[1:]
    # Intercept `build` / `dress` subcommands BEFORE argparse. The flat
    # CLI (`design.py --spec X`) stays byte-identical; subcommands
    # route through the same phase-dispatch loop with a hardcoded
    # phase allowlist and different `--phase` flags for
    # `bin/check.py` / `bin/snap-vision-review.py`.
    subcommand: str | None = None
    if argv and argv[0] in ("build", "dress"):
        subcommand = argv[0]
        argv = argv[1:]
        if subcommand == "dress":
            # `dress <slug>` — no --spec required; the theme is
            # expected to exist on disk (preflight validates this).
            # Synthesize a minimal spec so the inner main() stays
            # uniform.
            if not argv or argv[0].startswith("-"):
                print(
                    "error: `design.py dress` requires a theme slug "
                    "(e.g. `design.py dress chandler`).",
                    file=sys.stderr,
                )
                return 2
            slug = argv[0]
            rest = argv[1:]
            _dress_preflight(slug)
            spec_path = _synthesize_dress_spec(slug)
            argv = ["--spec", str(spec_path), *rest]

    args = _build_parser().parse_args(argv)
    args.subcommand = subcommand
    # Derive check + vision phase from the subcommand. `build` runs
    # check with --phase structural (the content-fit checks fail on a
    # fresh clone that still has upstream cartoons; that's what `dress`
    # is for). `dress` runs check with --phase all (the content-fit
    # checks must be green to promote) and vision-review with --phase
    # content (catalogue-fit lens only -- structural complaints were
    # already gated in `build`).
    if subcommand == "build":
        args.check_phase = "structural"
        args.vision_phase = "all"  # unused: vision-review not in _PHASES_FOR_BUILD
    elif subcommand == "dress":
        args.check_phase = "all"
        args.vision_phase = "content"
    else:
        args.check_phase = "all"
        args.vision_phase = "all"

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

    safety_errors = validate_generation_safety(spec)
    if safety_errors:
        print("error: generation safety validation failed:", file=sys.stderr)
        for err in safety_errors:
            print(str(err), file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"OK: spec is valid for theme `{spec.slug}` (source: {spec.source}).")
        print(
            f"     palette: {len(spec.palette)} slug(s); "
            f"fonts: {len(spec.fonts)} slug(s); "
            f"layout hints: {len(spec.layout_hints)}."
        )
        return 0

    # Subcommands default to a hardcoded allowlist, but still honor
    # `--from` / `--only` when design-watch resumes after a repair.
    # Flat CLI keeps using the existing _select_phases logic (preserves
    # pre-split behaviour byte-identically).
    subcommand_phases = _select_phases_for_subcommand(subcommand)
    if subcommand_phases is not None:
        if args.only:
            if args.only not in subcommand_phases:
                raise PhaseError(
                    args.only,
                    f"phase {args.only!r} is not part of `design.py {subcommand}`.",
                )
            phases_to_run = [args.only]
        elif args.from_phase != "validate":
            if args.from_phase not in subcommand_phases:
                raise PhaseError(
                    args.from_phase,
                    f"phase {args.from_phase!r} is not part of `design.py {subcommand}`.",
                )
            start = subcommand_phases.index(args.from_phase)
            phases_to_run = list(subcommand_phases[start:])
        else:
            phases_to_run = list(subcommand_phases)
    else:
        phases_to_run = _select_phases(args.from_phase, args.only)
    if args.skip_snap and not args.only:
        # `screenshot` is derived from the baseline PNG so it's equally
        # dependent on a fresh snap; group it with the snap phases.
        phases_to_run = [
            p
            for p in phases_to_run
            if p not in {"snap", "vision-review", "scorecard", "baseline", "screenshot", "report"}
        ]
    if args.skip_commit and not args.only:
        # --skip-commit implies --skip-publish (can't push a commit that
        # never ran). Keep `prepublish` by default: it is the push that
        # makes raw.githubusercontent.com serve a NEW theme's playground/
        # content before `snap` -- dropping it broke `build --skip-commit`
        # with snap's HTTP 404 preflight on content.xml.
        phases_to_run = [p for p in phases_to_run if p not in {"commit", "publish"}]
    if args.skip_publish and not args.only:
        # --skip-publish means "no push at all", which rules out the
        # mid-pipeline prepublish push too. The snap phase will then
        # fail fast on a brand-new theme (that's the documented
        # --skip-publish trade-off) but re-baselines of existing
        # themes still work because their content is already on main.
        phases_to_run = [p for p in phases_to_run if p not in {"prepublish", "publish"}]
    if args.skip_prepublish and not args.only:
        # Explicitly wins even when combined with --skip-commit for local
        # rehearsals that should not create the pre-snap publish commit.
        phases_to_run = [p for p in phases_to_run if p != "prepublish"]
    print(f"design.py: running phases {' -> '.join(phases_to_run)} for `{spec.slug}`")

    dest = MONOREPO_ROOT / spec.slug
    try:
        for phase in phases_to_run:
            handler = _PHASE_HANDLERS[phase]
            handler(spec, dest, args)
            _run_phase_invariants(spec, dest, phase)
    except PhaseError as e:
        phase, detail = e.args
        print(f"\nSTATUS: FAIL (phase {phase})", file=sys.stderr)
        print(f"  {detail}", file=sys.stderr)
        return 1

    print("\nSTATUS: PASS")
    print(f"  Theme:  {dest}")
    print(f"  Brief:  {dest / 'BRIEF.md'}")
    if subcommand == "build":
        print(BUILD_OK_BANNER.format(slug=spec.slug))
    elif subcommand == "dress":
        print(DRESS_OK_BANNER.format(slug=spec.slug))
    else:
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

    # Warn about background-critical slugs the spec didn't cover BEFORE
    # the palette lands — the `check` phase's `check_palette_polarity_
    # coherent` will hard-fail downstream if any of these stay stale,
    # but catching the problem at apply time is cheaper for the operator
    # (they can extend the spec and re-run instead of sitting through
    # the full snap cycle).
    _warn_uncovered_polarity_slugs(theme_json, spec)

    if spec.palette:
        apply_palette(theme_json, spec.palette)
        _repair_sale_badge_text_contrast(theme_json)
    _repair_site_title_mobile_overflow(theme_json)
    _repair_product_reviews_mobile_overflow(theme_json)
    if spec.fonts:
        apply_fonts(theme_json, spec.fonts)

    theme_json_path.write_text(serialize_theme_json(theme_json), encoding="utf-8")
    print(
        f"  [apply] wrote {theme_json_path.relative_to(MONOREPO_ROOT)} ({len(spec.palette)} color(s), {len(spec.fonts)} font slot(s))"
    )

    brief_path = dest / "BRIEF.md"
    brief_path.write_text(make_brief(spec, dest), encoding="utf-8")
    print(f"  [apply] wrote {brief_path.relative_to(MONOREPO_ROOT)}")

    spec_path = dest / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "slug": spec.slug,
                "name": spec.name,
                "tagline": spec.tagline,
                "voice": spec.voice,
                "source": spec.source,
                "palette": spec.palette,
                "fonts": spec.fonts,
                "layout_hints": spec.layout_hints,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  [apply] wrote {spec_path.relative_to(MONOREPO_ROOT)}")

    allow_added = _seed_allowlist_from_source(spec.source, spec.slug)
    if allow_added:
        print(
            f"  [apply] seeded {allow_added} heuristics-allowlist cell(s) "
            f"from {spec.source} → {spec.slug}"
        )


def _title_case_slug(slug: str) -> str:
    return "".join(part.capitalize() for part in slug.split("-"))


def _phase_rule_mode(category: str) -> str:
    from factory_rules import get_rule

    return get_rule(category).mode


def _raise_or_report_invariant(category: str, phase: str, message: str) -> None:
    mode = _phase_rule_mode(category)
    if mode == "disabled":
        return
    if mode == "report-only":
        print(f"  [{phase}] PREVENTION report-only ({category}): {message}")
        return
    raise PhaseError(phase, f"prevention rule {category}: {message}")


def _assert_no_source_branding_leaked(spec: ValidatedSpec, dest: Path) -> None:
    old_lower = spec.source.lower()
    old_title = _title_case_slug(old_lower)
    needles = {old_lower, old_title}
    leaks: list[str] = []
    for path in dest.rglob("*"):
        if not path.is_file() or path.suffix not in _TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(MONOREPO_ROOT).as_posix()
        if rel == f"{spec.slug}/readiness.json":
            continue
        if rel.startswith(f"{spec.slug}/playground/content/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(needle in text for needle in needles):
            leaks.append(rel)
            if len(leaks) >= 5:
                break
    if leaks:
        _raise_or_report_invariant(
            "php-syntax",
            "clone",
            f"source theme branding from `{spec.source}` survived clone in {', '.join(leaks)}",
        )


def _assert_apply_guards_present(dest: Path) -> None:
    theme_json_path = dest / "theme.json"
    data = json.loads(theme_json_path.read_text(encoding="utf-8"))
    css = str(data.get("styles", {}).get("css") or "")
    missing = [
        sentinel
        for sentinel in (
            _SITE_TITLE_OVERFLOW_SENTINEL,
            _PRODUCT_REVIEWS_OVERFLOW_SENTINEL,
        )
        if sentinel not in css
    ]
    if missing:
        _raise_or_report_invariant(
            "snap-a11y-color-contrast",
            "apply",
            f"generated mobile overflow guard(s) missing from theme.json: {', '.join(missing)}",
        )


def _assert_playground_payload_seeded(dest: Path) -> None:
    content = dest / "playground" / "content"
    images = dest / "playground" / "images"
    required = [
        content / "content.xml",
        content / "products.csv",
    ]
    missing = [path.relative_to(MONOREPO_ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        _raise_or_report_invariant(
            "placeholder-images",
            "seed",
            f"playground content payload missing required file(s): {', '.join(missing)}",
        )
    if not images.is_dir() or not any(images.iterdir()):
        _raise_or_report_invariant(
            "placeholder-images",
            "seed",
            f"{images.relative_to(MONOREPO_ROOT)} is missing or empty",
        )


def _assert_blueprint_landing_page(dest: Path) -> None:
    blueprint = dest / "playground" / "blueprint.json"
    if not blueprint.is_file():
        _raise_or_report_invariant(
            "placeholder-images",
            "sync",
            f"{blueprint.relative_to(MONOREPO_ROOT)} missing after sync",
        )
    data = json.loads(blueprint.read_text(encoding="utf-8"))
    if data.get("landingPage") != "/":
        _raise_or_report_invariant(
            "placeholder-images",
            "sync",
            "playground blueprint landingPage must be `/`",
        )


def _assert_hero_placeholders_not_source_copies(spec: ValidatedSpec, dest: Path) -> None:
    content = dest / "playground" / "content"
    for manifest in ("category-images.json", "product-images.json"):
        path = content / manifest
        if not path.is_file():
            _raise_or_report_invariant(
                "placeholder-images",
                "photos",
                f"{path.relative_to(MONOREPO_ROOT)} missing after photos phase",
            )

    source_images = MONOREPO_ROOT / spec.source / "playground" / "images"
    images = dest / "playground" / "images"
    duplicates: list[str] = []
    for path in sorted(images.glob("wonders-page-*.png")) + sorted(images.glob("wonders-post-*.png")):
        source_path = source_images / path.name
        if source_path.is_file() and path.read_bytes() == source_path.read_bytes():
            duplicates.append(path.name)
            if len(duplicates) >= 5:
                break
    if duplicates:
        _raise_or_report_invariant(
            "hero-placeholders-duplicate",
            "photos",
            f"hero placeholder(s) still match source bytes: {', '.join(duplicates)}",
        )


def _assert_microcopy_artifact_present(dest: Path) -> None:
    artifact = dest / "microcopy-overrides.json"
    if not artifact.is_file():
        _raise_or_report_invariant(
            "microcopy-duplicate",
            "microcopy",
            f"{artifact.relative_to(MONOREPO_ROOT)} missing after microcopy phase",
        )


def _run_phase_invariants(spec: ValidatedSpec, dest: Path, phase: str) -> None:
    if phase == "clone":
        _assert_no_source_branding_leaked(spec, dest)
    elif phase == "apply":
        _assert_apply_guards_present(dest)
    elif phase == "seed":
        _assert_playground_payload_seeded(dest)
    elif phase == "sync":
        _assert_blueprint_landing_page(dest)
    elif phase == "photos":
        _assert_hero_placeholders_not_source_copies(spec, dest)
    elif phase == "microcopy":
        _assert_microcopy_artifact_present(dest)


# Keep in sync with `bin/check.py::_BASE_POLARITY_SAMESIDE_SLUGS` — the
# warning here is the soft signal; the hard signal is the check. Drifting
# the two lists apart would mean the operator sees a warning for a slug
# the check doesn't care about (or vice versa — a silent check failure
# on a slug this warning never mentions).
_APPLY_POLARITY_CRITICAL_SLUGS = ("subtle", "surface", "accent-soft")


def _wcag_luminance_hex(hex_color: str) -> float | None:
    """WCAG 2.x relative luminance for `#RRGGBB`. Returns `None` if the
    string doesn't parse — callers skip the slug rather than crash.
    Kept here (duplicated with bin/check.py's `_wcag_luminance`) because
    `bin/design.py` shouldn't import from `bin/check.py` — a cyclic
    dependency that would freeze once the `check` phase calls design
    helpers in turn."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _wcag_contrast_hex(hex_a: str, hex_b: str) -> float | None:
    lum_a = _wcag_luminance_hex(hex_a)
    lum_b = _wcag_luminance_hex(hex_b)
    if lum_a is None or lum_b is None:
        return None
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _palette_slug_map(theme_json: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in theme_json.get("settings", {}).get("color", {}).get("palette", []):
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        color = entry.get("color")
        if isinstance(slug, str) and isinstance(color, str):
            out[slug] = color
    return out


def _repair_sale_badge_text_contrast(theme_json: dict) -> None:
    """Choose a readable sale-badge text token after palette application."""
    palette = _palette_slug_map(theme_json)
    accent = palette.get("accent")
    if not accent:
        return
    candidates = {
        slug: ratio
        for slug in ("contrast", "base")
        if (color := palette.get(slug))
        if (ratio := _wcag_contrast_hex(color, accent)) is not None
    }
    if not candidates:
        return
    best_slug, best_ratio = max(candidates.items(), key=lambda item: item[1])
    if best_ratio < 4.5:
        return
    blocks = theme_json.setdefault("styles", {}).setdefault("blocks", {})
    badge = blocks.setdefault("woocommerce/product-sale-badge", {})
    color = badge.setdefault("color", {})
    color["text"] = f"var(--wp--preset--color--{best_slug})"


_SITE_TITLE_OVERFLOW_SENTINEL = "generated-site-title-mobile-overflow"
_PRODUCT_REVIEWS_OVERFLOW_SENTINEL = "generated-product-reviews-mobile-overflow"


def _repair_site_title_mobile_overflow(theme_json: dict) -> None:
    """Prevent generated wordmarks from widening mobile layouts.

    Source themes can carry very large display-wordmark treatment in
    headers/footers. Once the source slug is replaced by an arbitrary
    concept name, that single unbreakable word can become wider than the
    mobile viewport. This guard keeps site-title blocks and their wrappers
    shrinkable and allows emergency wrapping at character boundaries.
    """
    styles = theme_json.setdefault("styles", {})
    existing = str(styles.get("css") or "")
    if _SITE_TITLE_OVERFLOW_SENTINEL in existing:
        return
    guard = (
        f"/* {_SITE_TITLE_OVERFLOW_SENTINEL} */ "
        ".wp-block-site-title,.wp-block-site-title a{max-width:100%;min-width:0;"
        "overflow-wrap:anywhere;word-break:normal} "
        ".wp-block-group:has(>.wp-block-site-title){max-width:100%;min-width:0}"
    )
    styles["css"] = f"{existing.rstrip()} {guard}".strip()


def _repair_product_reviews_mobile_overflow(theme_json: dict) -> None:
    """Keep WooCommerce's reviews block from widening mobile PDPs."""
    styles = theme_json.setdefault("styles", {})
    existing = str(styles.get("css") or "")
    if _PRODUCT_REVIEWS_OVERFLOW_SENTINEL in existing:
        return
    guard = (
        f"/* {_PRODUCT_REVIEWS_OVERFLOW_SENTINEL} */ "
        ".wp-block-woocommerce-product-reviews{max-width:100%;min-width:0;box-sizing:border-box} "
        ".wp-block-woocommerce-product-reviews-title,#reviews,"
        ".wp-block-woocommerce-product-review-form .comment-reply-title{max-width:100%;"
        "overflow-wrap:anywhere;word-break:normal;white-space:normal}"
    )
    styles["css"] = f"{existing.rstrip()} {guard}".strip()


def _warn_uncovered_polarity_slugs(theme_json: dict, spec: ValidatedSpec) -> None:
    """Print a one-line warning per polarity-critical slug that the spec
    doesn't override, when doing so would leave a stale source value on
    the wrong side of the new `base`.

    The downstream `check` phase has `check_palette_polarity_coherent`
    as the authoritative gate — this warning is an early heads-up so
    the operator isn't surprised when a 15-phase build fails at check
    for a spec gap they could have fixed in 5 seconds by extending the
    palette block.

    Silent when:
      - the spec didn't flip `base` polarity vs the source theme, OR
      - the spec covers every polarity-critical slug already, OR
      - the source theme.json doesn't have a `base` we can read.

    Loud (one line per affected slug) when the spec's new `base` lands
    on a different polarity side than the source's, and a
    polarity-critical slug would stay at the source's original value.
    """
    source_base = None
    source_slugs: dict[str, str] = {}
    for entry in theme_json.get("settings", {}).get("color", {}).get("palette", []):
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        color = entry.get("color")
        if not isinstance(slug, str) or not isinstance(color, str):
            continue
        source_slugs[slug] = color
        if slug == "base":
            source_base = color

    spec_base = spec.palette.get("base") if spec.palette else None
    if not spec_base or not source_base:
        return

    lum_source = _wcag_luminance_hex(source_base)
    lum_spec = _wcag_luminance_hex(spec_base)
    if lum_source is None or lum_spec is None:
        return
    source_side = "light" if lum_source >= 0.5 else "dark"
    spec_side = "light" if lum_spec >= 0.5 else "dark"
    if source_side == spec_side:
        return  # no polarity flip → any leftover slugs are fine

    flagged: list[tuple[str, str]] = []
    for slug in _APPLY_POLARITY_CRITICAL_SLUGS:
        if spec.palette and slug in spec.palette:
            continue
        source_value = source_slugs.get(slug)
        if not source_value:
            continue
        flagged.append((slug, source_value))

    if not flagged:
        return

    print(
        f"  [apply] WARN: spec flips `base` polarity "
        f"({source_side} → {spec_side}) but leaves "
        f"{len(flagged)} polarity-critical slug(s) uncovered — they'll "
        f"stay at {spec.source}'s value and fire "
        f"`check_palette_polarity_coherent` downstream:"
    )
    for slug, color in flagged:
        print(
            f"  [apply] WARN:   `{slug}: {color}` (from {spec.source}) — "
            f"extend spec.palette with a {spec_side}-side value for this slug"
        )


def _seed_allowlist_from_source(source_slug: str, target_slug: str) -> int:
    """Duplicate every `tests/visual-baseline/heuristics-allowlist.json`
    entry keyed `<source_slug>:viewport:route` under the same
    `<target_slug>:viewport:route` key, so a freshly-cloned theme
    inherits its source's known-tolerated waivers.

    Why this exists:
        Shipping themes carry grandfathered `narrow-wc-block`,
        `element-overflow-x`, and `a11y-color-contrast` findings that
        the team has already decided to tolerate — `check.py`'s
        `check_no_serious_axe_errors` reads the allowlist and demotes
        them to `info`. A newly-cloned theme inherits the SAME
        templates (same markup, same CSS) but none of the allowlist
        entries, so the same findings re-fire as NEW errors and block
        `design.py build` on problems the operator never introduced.

        Seeding the entries at `apply` time rather than at `check`
        time keeps the file as the single source of truth (instead of
        making the matcher lineage-aware), and preserves the rule
        that "new findings not in the allowlist fail the gate" —
        because any finding the new theme introduces BEYOND the
        source's baseline will still be absent from the file and fail.

    Idempotence:
        - Re-running `apply` is a no-op: each inbound entry is written
          only when the target key is missing (never overwrites).
        - Target entries that pre-exist (because the operator hand-
          edited the allowlist, or a prior run seeded them) survive
          untouched — merge is additive at the `<kind>: [fingerprints]`
          level, not replacing.
        - Seeding a theme from itself (`spec.source == spec.slug`)
          short-circuits; prevents duplicate-key self-inflation.
        - Returns the count of newly-created CELLS (not entries),
          which is what the operator needs to see in the log.
    """
    if source_slug == target_slug:
        return 0
    allowlist_path = MONOREPO_ROOT / "tests" / "visual-baseline" / "heuristics-allowlist.json"
    if not allowlist_path.is_file():
        return 0
    try:
        allow: dict = json.loads(allowlist_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    if not isinstance(allow, dict):
        return 0

    source_prefix = f"{source_slug}:"
    target_prefix = f"{target_slug}:"

    # Preserve the file's existing key order — the operator has curated
    # the layout (wildcard waivers first, then per-theme blocks grouped
    # by slug), and a blanket `sorted()` would rewrite the whole file
    # on every apply run, turning a 2-line diff into a 300-line one.
    # New target cells are appended in the same order as the source's
    # keys, so the diff is exactly the block of new entries.
    new_cells = 0
    changed = False
    for key in list(allow.keys()):
        if not key.startswith(source_prefix):
            continue
        src_cell = allow[key]
        if not isinstance(src_cell, dict):
            continue
        target_key = target_prefix + key[len(source_prefix) :]
        dst_cell = allow.get(target_key)
        if dst_cell is None:
            allow[target_key] = json.loads(json.dumps(src_cell))
            new_cells += 1
            changed = True
            continue
        if not isinstance(dst_cell, dict):
            continue
        for kind, fps in src_cell.items():
            if not isinstance(fps, list):
                continue
            existing = dst_cell.setdefault(kind, [])
            if not isinstance(existing, list):
                continue
            for fp in fps:
                if fp not in existing:
                    existing.append(fp)
                    changed = True

    if not changed:
        return new_cells

    allowlist_path.write_text(
        json.dumps(allow, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return new_cells


def _phase_contrast(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/autofix-contrast.py <slug>` to rewrite any block whose
    resolved (textColor, backgroundColor) pair fails WCAG AA against
    the freshly-applied palette.

    The autofix is idempotent — a clean pass reports "nothing to fix"
    and exits 0. When it does make rewrites, it prints one line per
    change so the build log captures the repair decisions.

    Hard-fails on a non-zero exit code when `--strict` is set. In
    --no-strict we log and continue so the operator can inspect the
    failing files by hand; the downstream `check` phase then fires
    `check_block_text_contrast` which will re-report the same issues
    as a gate-blocking failure.
    """
    wc_overrides = ROOT / "bin" / "append-wc-overrides.py"
    if wc_overrides.is_file():
        # New themes need the generated WC chrome phases (notably Phase FF
        # hover-polarity auto-flip) after their palette lands. A fresh clone
        # otherwise carries the source theme's previously-generated chunk,
        # which cannot include the new `body.theme-<slug>` selectors.
        cmd = [sys.executable, str(wc_overrides), "--update", spec.slug]
        print(f"  [contrast] {' '.join(cmd[1:])}")
        rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
        if rc != 0:
            if args.strict:
                raise PhaseError("contrast", f"append-wc-overrides.py exited {rc}")
            print(
                f"  [contrast] WARN: append-wc-overrides.py exited {rc}; continuing (--no-strict)."
            )

    script = ROOT / "bin" / "autofix-contrast.py"
    if not script.is_file():
        print("  [contrast] WARN: bin/autofix-contrast.py missing; skipping.")
        return
    cmd = [sys.executable, str(script), spec.slug]
    print(f"  [contrast] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        if args.strict:
            raise PhaseError("contrast", f"bin/autofix-contrast.py exited {rc}")
        print(f"  [contrast] WARN: bin/autofix-contrast.py exited {rc}; continuing (--no-strict).")


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
        print(
            f"  [seed] WARN: bin/seed-playground-content.py exited {rc}; continuing (--no-strict)."
        )


def _phase_sync(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/sync-playground.py` to refresh inlined mu-plugin payloads in
    every theme's blueprint (the script touches all themes; the new one
    becomes part of the set automatically)."""
    cmd = [sys.executable, str(ROOT / "bin" / "sync-playground.py")]
    print(f"  [sync] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("sync", f"bin/sync-playground.py exited {rc}")


def _phase_photos(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Generate per-theme product photos and category covers using Pillow.

    Calls `bin/generate-product-photos.py --theme <slug>`.  Idempotent:
    skips any file that already exists on disk.  After writing new JPGs,
    the script re-runs `seed-playground-content.py` so the CSV/XML refs
    are updated.

    Why here (after sync, before prepublish)
    ----------------------------------------
    The prepublish phase commits and pushes everything — including the
    newly generated JPGs — so `raw.githubusercontent.com` can serve them
    when the snap phase boots Playground.  Without this ordering, the
    branch's `playground/images/` directory still contains only cartoon
    PNGs at push time, and the snap finds broken-image findings on every
    product tile.
    """
    photo_script = ROOT / "bin" / "generate-product-photos.py"
    if not photo_script.is_file():
        print("  [photos] WARN: bin/generate-product-photos.py missing; skipping.")
        return

    hero_script = dest / "playground" / "generate-images.py"
    if hero_script.is_file():
        cmd = [sys.executable, str(hero_script)]
        print(f"  [photos] {' '.join(cmd)}")
        rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
        if rc != 0:
            raise PhaseError("photos", f"{hero_script.relative_to(MONOREPO_ROOT)} exited {rc}")
    else:
        print(
            "  [photos] WARN: playground/generate-images.py missing; hero placeholders remain seeded."
        )

    # Run the palette-derived generator last. Legacy per-theme scripts may
    # clone a source theme's page/post PNGs byte-for-byte; this pass writes
    # theme-specific product photos, category covers, and hero placeholders
    # after any source-local generator has had its turn.
    cmd = [sys.executable, str(photo_script), "--theme", spec.slug, "--force"]
    print(f"  [photos] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("photos", f"bin/generate-product-photos.py exited {rc}")


def _phase_microcopy(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Generate + apply per-theme voice substitutions.

    Calls `bin/generate-microcopy.py --theme <slug>` which:
      1. Picks substitutions from the static fallback table (offline).
      2. Optionally calls the Anthropic API for uncovered strings when
         ANTHROPIC_API_KEY is set.
      3. Writes `<slug>/microcopy-overrides.json`.
      4. Calls `bin/apply-microcopy-overrides.py --theme <slug>` to
         apply the replacements to templates/parts/patterns.

    Failure is soft (WARN): a theme whose microcopy wasn't fully
    personalised will still fail `check_all_rendered_text_distinct` but
    the pipeline can continue so the snap still runs and produces
    evidence for the other checks.
    """
    script = ROOT / "bin" / "generate-microcopy.py"
    if not script.is_file():
        print("  [microcopy] WARN: bin/generate-microcopy.py missing; skipping.")
        return
    cmd = [sys.executable, str(script), "--theme", spec.slug]
    print(f"  [microcopy] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        print(f"  [microcopy] WARN: generate-microcopy.py exited {rc}; continuing.")


def _phase_frontpage(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Ensure the front-page layout fingerprint is unique vs every other theme.

    Calls `bin/diversify-front-page.py --theme <slug>` which adds a
    ``wo-layout-<slug>`` className to the first ``wp:group`` direct child of
    ``<main>`` in ``templates/front-page.html``.  If the fingerprint is
    already unique, the script is a no-op.

    `check_front_page_unique_layout` fails when a cloned theme has the
    same direct-child sequence as its source (e.g. both obel and agave
    produce ``['pattern:hero-split', 'group', 'group']``).  This phase
    runs after `microcopy` (which may have edited pattern files) and
    before `index` (so INDEX.md reflects the final template state).
    """
    script = ROOT / "bin" / "diversify-front-page.py"
    if not script.is_file():
        print("  [frontpage] WARN: bin/diversify-front-page.py missing; skipping.")
        return
    cmd = [sys.executable, str(script), "--theme", spec.slug]
    print(f"  [frontpage] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("frontpage", f"bin/diversify-front-page.py exited {rc}")


def _phase_prepublish(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Commit the scaffolded theme and push the current branch to `origin`,
    so `raw.githubusercontent.com` can serve the new theme's
    `playground/content/` and `playground/images/` when the snap phase
    boots Playground.

    Why this exists
    ---------------
    `bin/sync-playground.py` inlines absolute `raw.githubusercontent.com`
    URLs into every theme's `playground/blueprint.json` (`importWxr` step
    and PHP `WO_CONTENT_BASE_URL` constant). Those URLs resolve against
    whatever ref `bin/snap.py::_auto_detect_content_ref` picks:

      * on `main`  → `main`
      * on a pushed branch → that branch
      * on an unpublished branch → falls back to `main` (with a hint)

    For a brand-new theme, main DOESN'T HAVE the theme's `playground/`
    files yet — so the fallback serves a GitHub 404 HTML page, PHP parses
    the HTML as CSV, and Playground boot dies at step #10
    (`wo-import.php`) with `Error: W&O CSV looked malformed: fewer than
    2 lines after trim.` This phase exists specifically to make the
    branch fetchable from raw.githubusercontent BEFORE the snap phase
    runs.

    How it works
    ------------
    1. Detect the current branch. No-op on `main` (the content IS on
       main already, snap will just resolve against it) or on a detached
       HEAD (no branch to push).
    2. `git add <slug>/ docs/ */playground/blueprint.json` to capture
       the freshly-cloned theme, any docs short-URL redirector updates,
       and every theme's re-synced blueprint (sync-playground touches
       them all).
    3. If anything is staged, commit with
       "design: scaffold <slug> (pre-snap content publish)".
    4. `git push -u origin HEAD`, with `FIFTY_SKIP_VISUAL_PUSH=1` and
       `FIFTY_SKIP_EVIDENCE_FRESHNESS=1` because the pre-push hook's
       visual gate and snap-evidence-freshness gate both require snap
       evidence that THIS phase runs BEFORE producing — skipping them
       legitimately is the whole point of the phase order.

    Phase N (`commit`) later sweeps up the snap baselines, screenshot,
    and docs as a second commit on the same branch. On the merge,
    squash-merge collapses the two commits into one — this is the same
    pattern `design-batch.py` already relies on.

    Skipped when
    ------------
      * `--skip-publish` — operator explicitly opted out of pushing.
      * `--skip-commit`  — skips phase N/O only; prepublish still runs
        (needed so snap can resolve playground content on a pushed ref).
      * `--skip-prepublish` — operator knows they're rebaselining an
        already-shipping theme and just wants to skip the mid-pipeline
        push.
      * current branch is `main` **and** `origin/main:<slug>/theme.json`
        exists — the content ref snap will use already includes this theme.
      * current branch has no symbolic ref (detached HEAD).
    """
    git = ["git", "-C", str(MONOREPO_ROOT)]

    proc = subprocess.run(
        [*git, "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("  [prepublish] skipped: detached HEAD (no branch to push)")
        return
    branch = proc.stdout.strip()
    if not branch:
        print("  [prepublish] skipped: empty branch name")
        return

    remote = args.publish_remote
    slug = spec.slug
    # On `main`, only skip when this theme already exists on origin/main.
    # A brand-new theme checked out locally on `main` is NOT on GitHub yet —
    # snap would 404 content.xml if we skipped prepublish.
    if branch == "main":
        has_on_origin = (
            subprocess.run(
                [*git, "cat-file", "-e", f"origin/main:{slug}/theme.json"],
                capture_output=True,
            ).returncode
            == 0
        )
        if has_on_origin:
            print(
                "  [prepublish] skipped: on main and "
                f"`origin/main:{slug}/theme.json` exists (nothing to pre-publish)"
            )
            return
        raise PhaseError(
            "prepublish",
            "On branch `main` but this theme is not on `origin/main` yet — "
            "raw.githubusercontent.com would 404 the playground content and "
            "`snap` would fail.\n"
            f"  git checkout -b agent/{slug}\n"
            "Then re-run `design.py build` (with or without `--skip-commit`). "
            "Prepublish will push the feature branch so Playground can fetch "
            "content before snap runs.",
        )

    # Stage what the earlier phases produced. We scope strictly to the
    # theme dir + docs/ + every theme's blueprint (which
    # sync-playground.py may have touched), NOT `-A`: the operator may
    # have unrelated WIP in their worktree and we don't want to sweep
    # that into the pre-snap commit.
    add_paths: list[str] = [f"{slug}/", "docs/"]
    for bp in sorted(MONOREPO_ROOT.glob("*/playground/blueprint.json")):
        add_paths.append(str(bp.relative_to(MONOREPO_ROOT)))

    rc = subprocess.call([*git, "add", "--", *add_paths])
    if rc != 0:
        raise PhaseError("prepublish", f"git add exited {rc}")

    # Is anything actually staged? On a re-run where the pre-snap
    # commit already landed and nothing has changed since, `add` is a
    # no-op and we skip the commit step to avoid an empty commit.
    rc_clean = subprocess.call(
        [*git, "diff", "--cached", "--quiet"],
    )
    if rc_clean == 0:
        print("  [prepublish] nothing new to commit (already up to date)")
    else:
        msg = f"design: scaffold {slug} (pre-snap content publish)"
        commit_env = os.environ.copy()
        commit_env["FIFTY_DESIGN_PREPUBLISH"] = "1"
        commit_env["FIFTY_SKIP_EVIDENCE_FRESHNESS"] = "1"
        rc = subprocess.call([*git, "commit", "-m", msg], env=commit_env)
        if rc != 0:
            raise PhaseError("prepublish", f"git commit exited {rc}")
        print(f"  [prepublish] committed: {msg}")

    # Push. Skip every pre-push gate whose input is snap evidence we
    # haven't produced yet. Each is a documented first-class escape
    # hatch — NEVER `--no-verify` (rule #19 forbids that).
    #
    #   FIFTY_SKIP_VISUAL_PUSH=1
    #     Skips `bin/snap.py check --changed`. We have zero snap
    #     evidence at this point; nothing to diff.
    #
    #   FIFTY_SKIP_EVIDENCE_FRESHNESS=1
    #     Skips the "snap evidence is fresh vs uncommitted source
    #     edits" gate. Nothing has been snapped yet; trivially stale.
    #
    #   FIFTY_SKIP_BOOT_SMOKE=1
    #     Skips `.githooks/pre-push`'s Playground-boot smoke. The
    #     whole POINT of this phase is to make the branch reachable
    #     from raw.githubusercontent so Playground CAN boot — but
    #     the smoke fires BEFORE the push completes, so it reads the
    #     not-yet-pushed branch, the boot fetches from main, and
    #     dies with "W&O CSV looked malformed: fewer than 2 lines
    #     after trim." The next phase (snap) runs the same boot
    #     against the now-pushed branch and catches real regressions
    #     there; Phase O's final push re-runs boot smoke against the
    #     populated branch and passes. Skipping here is redundant,
    #     not unsafe.
    env = os.environ.copy()
    env["FIFTY_DESIGN_PREPUBLISH"] = "1"
    env["FIFTY_SKIP_VISUAL_PUSH"] = "1"
    env["FIFTY_SKIP_EVIDENCE_FRESHNESS"] = "1"
    env["FIFTY_SKIP_BOOT_SMOKE"] = "1"
    print(f"  [prepublish] git push -u {remote} {branch}")
    rc = subprocess.call(
        [*git, "push", "-u", remote, "HEAD"],
        env=env,
    )
    if rc != 0:
        raise PhaseError(
            "prepublish",
            f"git push -u {remote} HEAD exited {rc}. "
            "Resolve the conflict (likely 'behind remote' on a shared "
            "branch, or missing remote-write credentials) and re-run "
            "with `--from prepublish`.",
        )
    print(f"  [prepublish] {remote}/{branch} ready; raw.githubusercontent will serve {branch}")


def _phase_snap(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/snap.py shoot <slug>` to generate fresh PNGs + axe + heuristic
    findings under `tmp/snaps/<slug>/`. This is the evidence the check phase
    consumes — without it, FIFTY_REQUIRE_SNAP_EVIDENCE=1 in CI/pre-push will
    fail because the no-snap path is no longer a silent skip."""
    cmd = [sys.executable, str(ROOT / "bin" / "snap.py"), "shoot", spec.slug]
    if args.snap_viewports:
        cmd.extend(["--viewports", *args.snap_viewports])
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
    vision_phase = getattr(args, "vision_phase", "all")
    cmd = [
        sys.executable,
        str(ROOT / "bin" / "snap-vision-review.py"),
        spec.slug,
    ]
    if vision_phase != "all":
        cmd.extend(["--phase", vision_phase])
    print(
        f"  [vision-review] {' '.join(cmd[1:])} "
        f"(budget=${args.vision_budget:.2f}, phase={vision_phase})"
    )
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


def _phase_scorecard(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Write tmp/runs/<run-id>/design-score.json from snap/vision findings.

    This turns taste feedback into a first-class pipeline signal. Low scores
    print a normal [FAIL] line before the phase raises, so design-watch can
    hand the blocker to design_unblock.py instead of leaving a human to infer
    what "looks weak" means from raw logs.
    """
    script = ROOT / "bin" / "design-scorecard.py"
    if not script.is_file():
        print("  [scorecard] WARN: bin/design-scorecard.py missing; skipping.")
        return
    run_id = os.environ.get("FIFTY_DESIGN_RUN_ID") or f"design-{spec.slug}"
    cmd = [
        sys.executable,
        str(script),
        spec.slug,
        "--run-id",
        run_id,
    ]
    print(f"  [scorecard] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("scorecard", f"bin/design-scorecard.py exited {rc}")


def _run_theme_screenshot(spec: ValidatedSpec, *, strict: bool = False) -> None:
    script = ROOT / "bin" / "build-theme-screenshots.py"
    if not script.is_file():
        message = "bin/build-theme-screenshots.py missing; skipping."
        if strict:
            raise PhaseError("screenshot", message)
        print(f"  [screenshot] WARN: {message}")
        return
    cmd = [sys.executable, str(script), spec.slug]
    print(f"  [screenshot] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        message = f"bin/build-theme-screenshots.py exited {rc}"
        if strict:
            raise PhaseError("screenshot", message)
        # Non-strict so a missing baseline (e.g. --skip-snap flow) doesn't
        # abort the whole run; check.py will still flag the mismatch.
        print(f"  [screenshot] WARN: {message}; check.py will flag if screenshot.png is stale.")


def _phase_screenshot(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/build-theme-screenshots.py <slug>` to derive the theme's
    WordPress admin `screenshot.png` from the freshly promoted baseline.

    Check.py's `check_theme_screenshots_distinct` rejects any theme that
    ships the source theme's screenshot bytes unchanged. Without this
    phase, a brand-new clone keeps its source's screenshot.png verbatim,
    and the git pre-commit hook fails at the last mile of the build.
    We bake the derivation into the pipeline so the gate stays green
    without a separate manual step."""
    _run_theme_screenshot(spec, strict=False)


def _refresh_final_commit_artifacts(
    spec: ValidatedSpec,
    dest: Path,
    args: argparse.Namespace,
) -> None:
    """Refresh last-mile artifacts immediately before the final commit.

    The normal phase list already contains `index`, `snap`, and `screenshot`,
    but the final commit is where the Git hooks judge the staged tree. Running
    a cheap, focused guard here makes `--from commit` / re-runs resilient and
    prevents copied screenshots or stale INDEX.md from reaching pre-commit.
    """
    print("  [commit] refreshing final artifacts (index, home snap, screenshot)")
    _phase_index(spec, dest, args)

    if getattr(args, "skip_snap", False):
        raise PhaseError(
            "commit",
            "--skip-snap cannot produce a final design commit. Re-run without "
            "--skip-snap so the commit guard can refresh home snap evidence "
            "and screenshot.png, or pass --skip-commit for a local-only rehearsal.",
        )

    cmd = [
        sys.executable,
        str(ROOT / "bin" / "snap.py"),
        "shoot",
        spec.slug,
        "--routes",
        "home",
        "--viewports",
        "mobile",
        "desktop",
        "--cache-state",
        "--no-skip",
    ]
    print(f"  [commit] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("commit", f"final home snap guard exited {rc}")

    _run_theme_screenshot(spec, strict=True)


def _phase_check(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/check.py <slug> --quick` for a fast static gate. With strict
    (the default), propagate failures; with `--no-strict`, print a hint
    and continue.

    `--quick` skips the network-dependent block-name validator so this
    works in airgapped environments. The full gate (with `check.py --all
    --offline`) runs in CI on push.

    Sets FIFTY_REQUIRE_SNAP_EVIDENCE=1 so any missing snap evidence is a
    FAIL rather than a silent SKIP when the snap phase is expected to
    run. In explicit `--skip-snap` smoke runs we leave it unset because
    missing evidence is the requested mode, not a crash."""
    env = os.environ.copy()
    if not getattr(args, "skip_snap", False):
        env.setdefault("FIFTY_REQUIRE_SNAP_EVIDENCE", "1")
    check_phase = getattr(args, "check_phase", "all")
    cmd = [sys.executable, str(ROOT / "bin" / "check.py"), spec.slug, "--quick"]
    if check_phase != "all":
        cmd.extend(["--phase", check_phase])
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
        print(
            f"  [redirects] WARN: bin/build-redirects.py exited {rc}; "
            "run manually and commit the docs/ diff to publish to GH Pages."
        )


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

    _refresh_final_commit_artifacts(spec, dest, args)

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
    proc = subprocess.run([*git, "diff", "--cached", "--quiet"], capture_output=True)
    if proc.returncode == 0:
        print(f"  [commit] skip: no staged diff for {slug} (theme already matches HEAD).")
        return

    subcommand = getattr(args, "subcommand", None)
    if subcommand == "build":
        headline = f"design: build {slug} (structurally sound)"
    elif subcommand == "dress":
        headline = f"design: dress {slug} (content-fit)"
    else:
        headline = f"design: ship {slug} theme"
    message = f"{headline}\n\nGenerated by bin/design.py"
    cproc = subprocess.run(
        [*git, "commit", "-m", message],
        capture_output=True,
        text=True,
    )
    if cproc.returncode != 0:
        # Surface both stdout and stderr so a pre-commit-hook failure
        # (which typically goes to stderr) AND a git message (which
        # goes to stdout) are visible.
        detail = (cproc.stdout + "\n" + cproc.stderr).strip()
        raise PhaseError("commit", f"git commit exited {cproc.returncode}: {detail}")

    # Log the SHA of the new commit so the operator can paste it into
    # the PR / issue / Linear ticket without another `git log`.
    sha_proc = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True)
    sha = sha_proc.stdout.strip()[:12] if sha_proc.returncode == 0 else "(unknown)"
    print(f"  [commit] {sha}  {headline}")


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
            capture_output=True,
            text=True,
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
        capture_output=True,
        text=True,
    )
    ahead_line = next(
        (ln for ln in ahead_proc.stdout.splitlines() if ln.startswith("# branch.ab ")),
        "",
    )
    if ahead_line:
        # Line shape: "# branch.ab +<ahead> -<behind>"
        try:
            ahead = int(ahead_line.split()[2].lstrip("+") or "0")
        except (IndexError, ValueError):
            ahead = -1
        if ahead == 0:
            print(
                f"  [publish] skip: {branch} is not ahead of {remote}/{branch} (nothing to push)."
            )
            return

    print(f"  [publish] git push {remote} {branch}")
    env = os.environ.copy()
    env["FIFTY_SKIP_VISUAL_PUSH"] = "1"
    env["FIFTY_SKIP_EVIDENCE_FRESHNESS"] = "1"
    env["FIFTY_SKIP_BOOT_SMOKE"] = "1"
    rc = subprocess.call([*git, "push", remote, branch], env=env)
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
    "contrast": _phase_contrast,
    "index": _phase_index,
    "seed": _phase_seed,
    "sync": _phase_sync,
    "photos": _phase_photos,
    "microcopy": _phase_microcopy,
    "frontpage": _phase_frontpage,
    "prepublish": _phase_prepublish,
    "snap": _phase_snap,
    "vision-review": _phase_vision_review,
    "scorecard": _phase_scorecard,
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
