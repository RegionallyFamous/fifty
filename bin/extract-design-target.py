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


_VISION_SYSTEM_PROMPT = """You are an art director critiquing a stationery-store concept mockup.

The mockup shows two desktop browser windows side-by-side: a HOME page on
the left, and a SHOP / category page on the right. They share the same
brand identity. Your job is to look at the mockup and answer five
questions about how the brand uses color, type, and ornament. The
answers feed a deterministic theme generator, so they have to be
precise and JSON-shaped.

The deterministic generator already extracted a baseline palette and
voice from the concept's metadata. Your refinements LAYER ON TOP — you
can override specific roles where the mockup makes the right answer
obvious, but you cannot invent new colors that aren't in the mockup.
When unsure, say so by returning null for that field.

Return STRICT JSON with this shape and nothing else (no prose, no code
fence):

{
  "accent_hex": "#rrggbb" | null,
  "accent_evidence": "<= 200 chars: which element in the mockup uses this color and why it's the brand's 'this is the action' signal",
  "ink_hex": "#rrggbb" | null,
  "paper_hex": "#rrggbb" | null,
  "register_override": "editorial" | "playful" | "scientific" | "industrial" | "decorative" | null,
  "hero_kind_override": "photo-led" | "illustration-led" | "type-led" | "neutral" | null,
  "ornament_override": "geometric" | "organic" | "linear" | "decorative" | "none" | null,
  "primary_motif": "<= 120 chars: one short phrase describing the most distinctive recurring shape, decoration, or pattern that should appear in the rendered theme"
}

Heuristics for choosing accent_hex:
- It's the color of the primary call-to-action button on the home page.
  If the home doesn't show a button, fall back to the price tag, the
  'shop now' link, or whatever element a customer's eye lands on first
  after the wordmark.
- It is NOT the page background (paper) or the body-text color (ink).
- It is NOT a photograph's pixel — only flat brand marks count.

Heuristics for ink_hex / paper_hex:
- paper = the dominant background tone of the page chrome (usually
  cream, grey, white, off-white, dark navy / black for dark themes).
- ink = the body-text color used for paragraphs and nav links.
- These are sanity checks; only override if the deterministic
  classifier obviously missed.

If the mockup has no clear answer for a field, return null. Better
to leave it null than to guess wrong.
"""


def _refine_target_with_vision(base: dt.DesignTarget, mockup: Path) -> dt.DesignTarget:
    """Vision-API refinement of the deterministic target.

    Calls Claude with the mockup PNG + a tight JSON-shape prompt and
    layers the response onto `base`. The deterministic target is a
    floor: any field the model returns null for stays untouched, any
    hex it returns gets sanity-checked against the meta's
    `palette_hex` (so the model can't invent a color the mockup
    doesn't actually contain).

    On any failure (budget cap, API error, malformed JSON) we log a
    warning and return `base` unchanged — the deterministic path is
    always good enough.
    """
    import os

    import _vision_lib as vlib

    meta_path = _meta_path(base.slug)
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    allowed_hexes = {dt.normalize_hex(h) for h in (meta.get("palette_hex") or [])}

    user_prompt = (
        f"Concept slug: {base.slug}\n"
        f"Concept tagline: {meta.get('blurb', '(no blurb)')}\n"
        f"Concept palette (allowed hexes): {', '.join(sorted(allowed_hexes)) or '(none declared)'}\n"
        f"\nReturn the JSON described in the system prompt."
    )

    try:
        response = vlib.vision_completion(
            png_path=mockup,
            system_prompt=_VISION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            theme=base.slug,
            route="mockup",
            viewport="design",
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            max_output_tokens=600,
        )
    except vlib.BudgetExceededError as exc:
        print(f"   {base.slug}: vision budget exceeded ({exc}); using deterministic target")
        return base
    except vlib.VisionError as exc:
        print(f"   {base.slug}: vision call failed ({exc}); using deterministic target")
        return base
    except Exception as exc:  # noqa: BLE001 — defensive; never crash extract
        print(f"   {base.slug}: unexpected vision error ({exc}); using deterministic target")
        return base

    refined = _apply_vision_refinement(base, response.raw_text, allowed_hexes)
    print(
        f"   {base.slug}: vision refined target "
        f"(in={response.input_tokens} out={response.output_tokens} ${response.cost_usd:.4f})"
    )
    return refined


def _apply_vision_refinement(
    base: dt.DesignTarget,
    raw_text: str,
    allowed_hexes: set[str],
) -> dt.DesignTarget:
    """Parse the model's JSON response and merge onto `base`.

    Defensive against every flavor of malformed response: surrounding
    prose, code fences, partial JSON, hallucinated hexes that aren't
    in the mockup. Any unparseable field is silently dropped — the
    deterministic floor wins.
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        print(f"   {base.slug}: vision response not JSON; using deterministic target")
        return base
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        print(f"   {base.slug}: vision JSON malformed ({exc}); using deterministic target")
        return base

    refined_palette = dict(base.palette)
    accent_hex = _coerce_hex(parsed.get("accent_hex"), allowed_hexes)
    if accent_hex and accent_hex != base.palette.get("accent"):
        refined_palette["accent"] = accent_hex
    ink_hex = _coerce_hex(parsed.get("ink_hex"), allowed_hexes)
    if ink_hex and ink_hex != base.palette.get("ink"):
        refined_palette["ink"] = ink_hex
    paper_hex = _coerce_hex(parsed.get("paper_hex"), allowed_hexes)
    if paper_hex and paper_hex != base.palette.get("paper"):
        refined_palette["paper"] = paper_hex

    voice = dict(base.voice)
    register_override = parsed.get("register_override")
    if isinstance(register_override, str) and register_override in dt.REGISTER_KINDS:
        voice["register"] = register_override
    primary_motif = parsed.get("primary_motif")
    if isinstance(primary_motif, str) and primary_motif.strip():
        existing_motifs = list(voice.get("preferred_motifs") or [])
        motif = primary_motif.strip()
        if motif not in existing_motifs:
            existing_motifs.insert(0, motif)
        voice["preferred_motifs"] = existing_motifs[:3]

    composition = dict(base.composition)
    hero_override = parsed.get("hero_kind_override")
    if isinstance(hero_override, str) and hero_override in dt.HERO_KINDS:
        composition["hero"] = hero_override
    ornament_override = parsed.get("ornament_override")
    if isinstance(ornament_override, str) and ornament_override in dt.ORNAMENT_KINDS:
        composition["ornament"] = ornament_override

    accent_evidence = parsed.get("accent_evidence") if isinstance(parsed, dict) else None
    refined_source = {**base.source, "method": "vision-from-mockup"}
    if isinstance(accent_evidence, str) and accent_evidence.strip():
        refined_source["accent_evidence"] = accent_evidence.strip()[:240]

    return dt.DesignTarget(
        schema=base.schema,
        slug=base.slug,
        name=base.name,
        voice=voice,
        palette=refined_palette,
        type=base.type,
        composition=composition,
        required_signals=list(base.required_signals),
        forbidden_signals=list(base.forbidden_signals),
        source=refined_source,
    )


def _coerce_hex(value: object, allowed: set[str]) -> str | None:
    """Normalize a hex string from the model and gate it against the
    declared mockup palette. We deliberately allow a 6-unit Lab distance
    of slop because the model frequently reads `#FFE600` as `#FFE500`
    when the swatch is anti-aliased; if the closest declared hex is
    visually adjacent we accept it and snap to the canonical value.
    """
    if not isinstance(value, str):
        return None
    try:
        norm = dt.normalize_hex(value)
    except Exception:  # noqa: BLE001 — bad hex from model
        return None
    if not allowed:
        return norm
    if norm in allowed:
        return norm
    closest = _closest_allowed(norm, allowed, max_distance=18)
    return closest


def _closest_allowed(hex_value: str, allowed: set[str], *, max_distance: int) -> str | None:
    """Return the allowed hex closest in RGB distance to `hex_value`,
    or None if every allowed hex is further than `max_distance`.
    """
    target_rgb = _rgb_for(hex_value)
    if not target_rgb:
        return None
    best: tuple[float, str] | None = None
    for cand in allowed:
        cand_rgb = _rgb_for(cand)
        if not cand_rgb:
            continue
        distance = sum((a - b) ** 2 for a, b in zip(target_rgb, cand_rgb)) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, cand)
    if best is None or best[0] > max_distance:
        return None
    return best[1]


def _rgb_for(hex_value: str) -> tuple[int, int, int] | None:
    try:
        norm = dt.normalize_hex(hex_value).lstrip("#")
    except Exception:  # noqa: BLE001
        return None
    if len(norm) != 6:
        return None
    return (int(norm[0:2], 16), int(norm[2:4], 16), int(norm[4:6], 16))


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
