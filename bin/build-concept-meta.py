#!/usr/bin/env python3
"""Generate ``mockups/<slug>.meta.json`` for every concept in
``bin/concept_seed.py``.

This is the bridge between the human-curated source-of-truth at
``bin/concept_seed.py`` (which carries blurbs, controlled-vocabulary
tags, and type specimens) and the runtime-consumed JSON files under
``mockups/`` (which the static-site renderer at ``bin/build-redirects.py``
reads — no Python deps, no Pillow at render time).

What it writes per concept:

* All eight tag/blurb/specimen fields, copied verbatim from
  ``concept_seed.CONCEPTS`` (re-shaped: tags collapse into a
  ``tags`` sub-object so the JSON file is closer to its on-disk
  identity than to the Python dict's flat shape).
* ``palette_hex``: 5 dominant hex colors auto-extracted from the
  matching mockup PNG via ``bin/extract-palette.py``.

Idempotency:
    The script regenerates every ``.meta.json`` from scratch on each
    run. If the seed entry is unchanged AND the mockup PNG hasn't been
    touched, the resulting file is byte-identical to the previous
    run, so it's safe to wire into pre-commit.

Usage:
    python3 bin/build-concept-meta.py             # write all 102 files
    python3 bin/build-concept-meta.py --check     # diff-only mode (CI)
    python3 bin/build-concept-meta.py --slug cobbler  # single concept
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module

from _lib import MONOREPO_ROOT
from concept_seed import CONCEPTS, CONCEPTS_BY_SLUG, validate

# extract-palette.py has a hyphen in the filename so we can't `import`
# it directly. importlib.import_module handles the rewrite.
_extract_palette_mod = import_module("extract-palette")
extract_palette = _extract_palette_mod.extract_palette

MOCKUPS_DIR = MONOREPO_ROOT / "mockups"


def _resolve_mockup_path(slug: str) -> Path | None:
    """Look up the source PNG, supporting both the single-image and the
    directory layouts documented in ``mockups/README.md``.

    Returns ``None`` if neither form exists (the audit + queue still
    list the concept, but ``palette_hex`` will fall back to ``[]``).
    """
    single = MOCKUPS_DIR / f"mockup-{slug}.png"
    if single.is_file():
        return single
    multi_home = MOCKUPS_DIR / slug / "home.png"
    if multi_home.is_file():
        return multi_home
    return None


def _build_meta(concept: dict) -> dict:
    """Shape a CONCEPTS entry into its on-disk JSON form."""
    slug = concept["slug"]
    mockup_path = _resolve_mockup_path(slug)
    palette_hex: list[str] = []
    if mockup_path is not None:
        try:
            palette_hex = extract_palette(mockup_path, count=5)
        except Exception as e:  # pragma: no cover  (Pillow IO can be flaky on bad PNGs)
            print(f"WARN: palette extraction failed for {slug}: {e}", file=sys.stderr)
    return {
        "slug": slug,
        "name": concept["name"],
        "blurb": concept["blurb"],
        "tags": {
            "palette": list(concept["palette_tags"]),
            "type": concept["type_genre"],
            "era": concept["era"],
            "sector": concept["sector"],
            "hero": concept["hero_composition"],
        },
        "palette_hex": palette_hex,
        "type_specimen": concept["type_specimen"],
    }


def _write_meta(meta: dict) -> tuple[Path, bool]:
    """Write meta.json; return (path, changed).

    ``changed`` is True when the on-disk file did not previously exist
    or its content differs from what we just generated. Used by --check
    to surface drift without rewriting.
    """
    out_path = MOCKUPS_DIR / f"{meta['slug']}.meta.json"
    serialized = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
    if out_path.is_file() and out_path.read_text(encoding="utf-8") == serialized:
        return out_path, False
    return out_path, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill mockups/<slug>.meta.json from concept_seed."
    )
    parser.add_argument("--slug", help="Only regenerate this slug (default: all).")
    parser.add_argument(
        "--check", action="store_true", help="Don't write — exit non-zero if any file would change."
    )
    args = parser.parse_args()

    errors = validate()
    if errors:
        print("concept_seed validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    targets = [CONCEPTS_BY_SLUG[args.slug]] if args.slug else CONCEPTS
    if args.slug and args.slug not in CONCEPTS_BY_SLUG:
        print(f"ERROR: no concept named '{args.slug}' in concept_seed.py", file=sys.stderr)
        return 1

    drifted: list[str] = []
    written: list[str] = []
    for concept in targets:
        meta = _build_meta(concept)
        out_path, changed = _write_meta(meta)
        if not changed:
            continue
        if args.check:
            drifted.append(concept["slug"])
        else:
            serialized = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
            out_path.write_text(serialized, encoding="utf-8")
            written.append(concept["slug"])

    if args.check:
        if drifted:
            print(
                f"DRIFT: {len(drifted)} meta files would change: {', '.join(drifted)}",
                file=sys.stderr,
            )
            print("Run `python3 bin/build-concept-meta.py` and commit the result.", file=sys.stderr)
            return 1
        print(f"OK: all {len(targets)} meta files match concept_seed + extracted palettes.")
        return 0

    print(
        f"wrote {len(written)} of {len(targets)} meta files "
        f"({len(targets) - len(written)} unchanged)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
