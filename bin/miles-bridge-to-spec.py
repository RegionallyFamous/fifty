#!/usr/bin/env python3
"""Validate a Miles-exported Fifty spec JSON and copy it to `tmp/specs/`.

**No Claude / Anthropic.** Miles must produce the spec JSON (or the operator
places a file Miles exported). This script only:

1. Reads `miles-ready.json` in the artifact directory (proves a Miles session
   completed). Skipped when ``--dry-run``.
2. Loads the spec JSON path named there (or `spec.json` in the same dir).
3. Runs `validate_spec` + `validate_generation_safety`.
4. Verifies `--slug` / `--name` match the file (clone target alignment).
5. Writes `--out` (default `tmp/specs/<slug>.json`).

Artifact directory layout::

    <dir>/miles-ready.json     # required: {\"site_ready\": true, \"spec\": \"spec.json\"}
    <dir>/spec.json            # ValidatedSpec JSON from Miles (\"spec\" path is relative)

`site_ready` must be JSON true or the script exits 2.

Typical flow::

    python3 bin/miles-bridge-to-spec.py \\
      --slug ferment-co --name \"Ferment Co\" \\
      --artifacts-dir tmp/miles-handoff/ferment-co

    python3 bin/design.py --miles-artifacts tmp/miles-handoff/ferment-co \\
      --miles-slug ferment-co --miles-name \"Ferment Co\" build

CI / tests without Miles: use ``--dry-run`` (writes `example_spec()` with the
given slug/name; skips `miles-ready.json`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _design_lib import (  # noqa: E402
    SLUG_PATTERN,
    validate_generation_safety,
    validate_spec,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="miles-bridge-to-spec.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--slug", required=True, help="Theme slug (must match spec JSON and clone target).")
    p.add_argument("--name", required=True, help='Display name (must match spec JSON "name").')
    p.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing miles-ready.json and the Miles spec JSON. "
            "Omit with --dry-run (tests only)."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output spec path (default: tmp/specs/<slug>.json).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Write example_spec() with forced slug/name; no miles-ready.json (tests only).",
    )
    args = p.parse_args(argv)
    if not args.dry_run and args.artifacts_dir is None:
        p.error("the following arguments are required: --artifacts-dir (unless --dry-run)")

    slug = args.slug.strip().lower()
    if not SLUG_PATTERN.match(slug):
        print(f"error: invalid --slug {slug!r}", file=sys.stderr)
        return 2
    name = args.name.strip()
    if not name:
        print("error: --name must be non-empty", file=sys.stderr)
        return 2

    out_path = args.out or (ROOT / "tmp" / "specs" / f"{slug}.json")

    if args.dry_run:
        from _design_lib import example_spec

        spec = dict(example_spec())
        spec["slug"] = slug
        spec["name"] = name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        print(str(out_path))
        return 0

    art = args.artifacts_dir
    if not art.is_dir():
        print(f"error: --artifacts-dir is not a directory: {art}", file=sys.stderr)
        return 2

    ready_path = art / "miles-ready.json"
    if not ready_path.is_file():
        print(
            f"error: missing {ready_path.name} — Miles-led builds require a Miles handoff manifest.",
            file=sys.stderr,
        )
        return 2

    try:
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON in {ready_path}: {e}", file=sys.stderr)
        return 2
    if not isinstance(ready, dict):
        print("error: miles-ready.json must be a JSON object", file=sys.stderr)
        return 2
    if ready.get("site_ready") is not True:
        print(
            "error: miles-ready.json must set \"site_ready\": true before Fifty ingest.",
            file=sys.stderr,
        )
        return 2

    spec_rel = ready.get("spec")
    if not isinstance(spec_rel, str) or not spec_rel.strip():
        spec_rel = "spec.json"
    spec_path = (art / spec_rel).resolve()
    try:
        spec_path.relative_to(art.resolve())
    except ValueError:
        print(f"error: spec path must stay inside artifact dir: {spec_rel!r}", file=sys.stderr)
        return 2
    if not spec_path.is_file():
        print(f"error: Miles spec file not found: {spec_path}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON in {spec_path}: {e}", file=sys.stderr)
        return 2
    if not isinstance(raw, dict):
        print(f"error: Miles spec must be a JSON object: {spec_path}", file=sys.stderr)
        return 2

    errs, validated = validate_spec(raw)
    if errs or validated is None:
        print("error: spec failed validation:", file=sys.stderr)
        for err in errs:
            print(f"  {err}", file=sys.stderr)
        return 2

    if validated.slug != slug:
        print(
            f"error: spec slug {validated.slug!r} does not match --slug {slug!r}",
            file=sys.stderr,
        )
        return 2
    if validated.name != name:
        print(
            f"error: spec name {validated.name!r} does not match --name {name!r}",
            file=sys.stderr,
        )
        return 2

    safety = validate_generation_safety(validated)
    if safety:
        print("error: spec failed generation safety validation:", file=sys.stderr)
        for err in safety:
            print(f"  {err}", file=sys.stderr)
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"miles-bridge: validated Miles spec → {out_path}", file=sys.stderr)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
