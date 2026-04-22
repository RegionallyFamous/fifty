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
The pipeline has named phases A-F. Every phase is idempotent and can be
retried:

  A. validate     - parse + validate the spec (always runs, dry-run stops here)
  B. clone        - bin/clone.py (skipped if --skip-clone or theme exists)
  C. apply        - palette + fonts written to <slug>/theme.json + BRIEF.md
  D. seed         - bin/seed-playground-content.py
  E. sync         - bin/sync-playground.py
  F. check        - bin/check.py <slug> --quick (informational; --strict to fail)

Use `--from PHASE` to start mid-pipeline (e.g. you tweaked the spec and
only want to re-run phases C+D+E+F without re-cloning), or `--only PHASE`
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

PHASES = ("validate", "clone", "apply", "seed", "sync", "check")


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
        "--strict",
        action="store_true",
        help=(
            "Make the final check phase block on any check.py failure (default is "
            "informational so you can read BRIEF.md and fix issues iteratively)."
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
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.print_example_spec:
        json.dump(example_spec(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if not args.spec:
        print("error: --spec PATH is required (or pass --print-example-spec)", file=sys.stderr)
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


def _phase_seed(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/seed-playground-content.py --theme <slug>` to populate
    `<slug>/playground/content/` and `<slug>/playground/images/`. Soft-fails
    (warns and continues) so a missing optional dep doesn't block the rest
    of the pipeline -- the user can re-run seed manually after fixing."""
    cmd = [sys.executable, str(ROOT / "bin" / "seed-playground-content.py"), "--theme", spec.slug]
    print(f"  [seed] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        print(f"  [seed] WARN: bin/seed-playground-content.py exited {rc}; continuing.")


def _phase_sync(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/sync-playground.py` to refresh inlined mu-plugin payloads in
    every theme's blueprint (the script touches all themes; the new one
    becomes part of the set automatically)."""
    cmd = [sys.executable, str(ROOT / "bin" / "sync-playground.py")]
    print(f"  [sync] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc != 0:
        raise PhaseError("sync", f"bin/sync-playground.py exited {rc}")


def _phase_check(spec: ValidatedSpec, dest: Path, args: argparse.Namespace) -> None:
    """Run `bin/check.py <slug> --quick` for a fast static gate. With
    `--strict`, propagate failures; otherwise print a hint and continue.

    `--quick` skips the network-dependent block-name validator so this
    works in airgapped environments. The full gate (with `check.py --all
    --offline`) runs in CI on push."""
    cmd = [sys.executable, str(ROOT / "bin" / "check.py"), spec.slug, "--quick"]
    print(f"  [check] {' '.join(cmd[1:])}")
    rc = subprocess.call(cmd, cwd=str(MONOREPO_ROOT))
    if rc == 0:
        return
    if args.strict:
        raise PhaseError("check", f"bin/check.py exited {rc} (--strict)")
    print(
        f"  [check] WARN: bin/check.py exited {rc}. This is informational under "
        "the default policy -- read BRIEF.md, fix issues, then re-run "
        f"`python3 bin/check.py {spec.slug} --quick` until green before committing."
    )


_PHASE_HANDLERS = {
    "validate": _phase_validate,
    "clone": _phase_clone,
    "apply": _phase_apply,
    "seed": _phase_seed,
    "sync": _phase_sync,
    "check": _phase_check,
}


if __name__ == "__main__":
    sys.exit(main())
