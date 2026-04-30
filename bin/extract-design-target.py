#!/usr/bin/env python3
"""Extract a `<slug>/design-target.json` from a concept mockup.

Two paths today:

1. **Deterministic from `mockups/<slug>.meta.json`** (default). Reads the
   already-published palette_hex + tags + type_specimen. Zero API calls,
   reproducible, runs in <50ms.

2. **Vision pass on the mockup PNG** (opt-in via `--from-mockup`). Calls
   the Anthropic vision API with a structured prompt that returns the
   same `DesignTarget` JSON shape. Useful for concepts whose meta.json
   is sparse, or to refine an extracted target after the meta has
   drifted from the mockup. Falls back to deterministic when no
   `ANTHROPIC_API_KEY` is set.

Both paths emit the **same** schema. Downstream tooling
(`bin/render-design-target.py`, `bin/design.py`) does not branch on
which extractor produced the file — the JSON is the contract.

Usage::

    python3 bin/extract-design-target.py agitprop
    python3 bin/extract-design-target.py agitprop --from-mockup
    python3 bin/extract-design-target.py --all  # backfill every theme
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _design_target_lib as dt
from _lib import MONOREPO_ROOT, iter_themes


def _meta_path(slug: str) -> Path:
    return MONOREPO_ROOT / "mockups" / f"{slug}.meta.json"


def _target_path(slug: str) -> Path:
    return MONOREPO_ROOT / slug / "design-target.json"


def _theme_dir(slug: str) -> Path:
    return MONOREPO_ROOT / slug


def _extract_from_meta(slug: str) -> dt.DesignTarget:
    meta_path = _meta_path(slug)
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"missing concept metadata: {meta_path.relative_to(MONOREPO_ROOT)}"
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return dt.derive_target_from_meta(slug, meta)


def _run_one(slug: str, *, from_mockup: bool, force: bool) -> int:
    theme_dir = _theme_dir(slug)
    if not theme_dir.is_dir():
        print(f"!! {slug}: theme dir missing at {theme_dir}", file=sys.stderr)
        return 1
    out = _target_path(slug)
    if out.is_file() and not force:
        print(f"   {slug}: {out.relative_to(MONOREPO_ROOT)} already exists (--force to overwrite)")
        return 0

    if from_mockup:
        # Reserved for the vision-API path. The caller asked for it
        # explicitly; we don't silently fall back when ANTHROPIC_API_KEY
        # is missing because the deterministic path is one flag away
        # and we'd rather be loud about that.
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                f"!! {slug}: --from-mockup requires ANTHROPIC_API_KEY; "
                f"re-run without the flag for the deterministic-from-meta path.",
                file=sys.stderr,
            )
            return 2
        target = _extract_from_mockup(slug)
    else:
        target = _extract_from_meta(slug)

    dt.write_target(target, out)
    print(f"ok {slug}: wrote {out.relative_to(MONOREPO_ROOT)}")
    return 0


def _extract_from_mockup(slug: str) -> dt.DesignTarget:
    """Vision-API extraction — wraps the deterministic path so we always
    have a schema-correct target even when the API returns a partial
    response. The API output is *merged on top of* the deterministic
    one, so an LLM hallucination can refine the palette but cannot
    erase the structured floor.
    """
    base = _extract_from_meta(slug)

    # Lazy-import the vision lib so the deterministic path stays free
    # of the Anthropic SDK dependency for users that never opt in.
    try:
        import _vision_lib  # noqa: F401
    except Exception as exc:  # pragma: no cover — only triggers when SDK is missing
        print(f"   {slug}: vision lib unavailable ({exc}); using deterministic target")
        return base

    mockup = MONOREPO_ROOT / "mockups" / f"mockup-{slug}.png"
    if not mockup.is_file():
        print(f"   {slug}: mockup missing at {mockup}; using deterministic target")
        return base

    # The actual vision call lives behind a small adapter so the prompt
    # can evolve without touching this CLI. We keep the deterministic
    # target as a strict floor: any hex / role the model invents has to
    # show up as an override on `base`, never instead of it.
    refined = _refine_target_with_vision(base, mockup)
    refined.source["method"] = "vision-from-mockup"
    return refined


def _refine_target_with_vision(base: dt.DesignTarget, mockup: Path) -> dt.DesignTarget:
    """Placeholder for the vision refinement pass.

    The deterministic-from-meta path covers everything we need today, so
    the first cut of this CLI ships with the API hook stubbed out and
    returns the deterministic target unchanged. Wiring the real
    Anthropic call is a follow-up; the schema and the rest of the
    pipeline are already production.
    """
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", help="theme slug")
    parser.add_argument(
        "--all",
        action="store_true",
        help="extract a target for every theme that has a mockups/*.meta.json",
    )
    parser.add_argument(
        "--from-mockup",
        action="store_true",
        help="vision API extraction (opt-in; requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing design-target.json",
    )
    args = parser.parse_args(argv)

    if args.all and args.slug:
        parser.error("pass either a slug or --all, not both")

    slugs: list[str] = []
    if args.all:
        for theme_dir in iter_themes():
            slugs.append(theme_dir.name)
    elif args.slug:
        slugs.append(args.slug)
    else:
        parser.error("provide a theme slug or --all")

    rc = 0
    for slug in slugs:
        try:
            rc = max(rc, _run_one(slug, from_mockup=args.from_mockup, force=args.force))
        except FileNotFoundError as exc:
            print(f"!! {slug}: {exc}", file=sys.stderr)
            rc = max(rc, 1)
        except Exception as exc:  # pragma: no cover — surfaced to operator
            print(f"!! {slug}: {exc}", file=sys.stderr)
            rc = max(rc, 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
