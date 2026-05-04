#!/usr/bin/env python3
"""Turn a `bin/concept_seed.CONCEPTS[slug]` entry + its mockup PNG into a
validated `bin/design.py` spec JSON.

Why this script exists
----------------------
The pre-100-themes hardening plan identified "hand-authoring spec JSON
for each new concept" as one of the slower manual steps in shipping a
theme. `bin/spec-from-prompt.py` already covers the "arbitrary prompt"
case by calling an LLM. This script is its structured-input sibling:

  * The INPUT is already curated (controlled-vocab palette_tags,
    type_genre, era, hero_composition, plus a mockup PNG the operator
    already painted via `bin/paint-mockup.py`).
  * The OUTPUT is exactly the spec schema `bin/design.py --spec`
    consumes.

So the script is really a *structured translator* with two modes:

  `--no-llm` (deterministic)
      Pure mapping from controlled-vocab tokens to spec fields using
      the embedded lookup tables (PALETTE_TAG_TO_HEX, TYPE_GENRE_FONTS,
      HERO_COMPOSITION_HINTS). Produces a valid, reproducible spec
      without any API cost. Useful for:
        * unit tests
        * offline / budget-exhausted runs
        * "start here, then polish" workflow where the agent wants a
          known-good baseline spec before iterating with the LLM.

  `--llm` (default when ANTHROPIC_API_KEY is set)
      Calls `bin/_vision_lib.vision_completion` (the generic
      image+text primitive that shares HTTP/retry/ledger plumbing
      with the visual-regression reviewer) with a concept-to-spec
      system prompt. Sends the mockup + concept metadata to Claude
      and parses the returned JSON into a spec shaped like
      `_design_lib.example_spec()`. On validation failure the model
      is re-prompted once with the validator's per-field errors so
      it can self-correct; a second failure surfaces to the caller.

Both modes run `bin/_design_lib.validate_spec` on the result and exit
non-zero if the spec fails. The caller (`bin/design.py` or
`bin/design-batch.py --from-concepts`) can trust the output.

Typical usage
-------------
::

    # Deterministic sanity check:
    python3 bin/concept-to-spec.py --slug agave --no-llm

    # Normal operator flow (uses vision + mockup):
    python3 bin/concept-to-spec.py --slug agave

    # Pipe straight into design.py:
    python3 bin/concept-to-spec.py --slug agave --out tmp/specs/agave.json
    python3 bin/design.py --spec tmp/specs/agave.json

Design non-goals
----------------
This script does NOT do the judgment-heavy work (microcopy, hero copy,
front-page layout restructure). It produces a spec that produces a
starting theme, the way `bin/clone.py` produces a starting theme from
Obel. The human + vision-reviewer still polish afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from _design_lib import (  # noqa: E402
    KNOWN_FONT_SLUGS,
    validate_generation_safety,
    validate_spec,
)

# ---------------------------------------------------------------------------
# Deterministic lookups
# ---------------------------------------------------------------------------
#
# The hex values below are the canonical representation of each controlled-
# vocab palette token. They were sourced by averaging the swatches used in
# the six original themes (obel, chonk, selvedge, lysholm, aero, foundry)
# plus a round of color-picker sampling on the mockups. The goal is
# "readable across typical WC surface states" not "the most accurate
# terracotta you ever saw" -- the vision-review pass is where brand-
# specific color tuning happens.
#
# Every token in `concept_seed.PALETTE_TOKENS` MUST have a hex here; the
# `test_every_palette_token_maps_to_a_hex` test enforces that a new token
# added to the concept list also lands a default here.
PALETTE_TAG_TO_HEX: dict[str, str] = {
    # Neutrals
    "cream": "#F5EFE6",
    "paper": "#FAF7F1",
    "white": "#FFFFFF",
    "ink": "#1F1B16",
    "black": "#0A0A0A",
    "charcoal": "#2B2B2B",
    "slate": "#54606C",
    "monochrome": "#3A3A3A",
    "kraft": "#C9A97A",
    "tan": "#C8A97B",
    "brown": "#6B4F37",
    # Reds / oranges
    "rust": "#B65A3C",
    "ochre": "#C98A2D",
    "terracotta": "#D87E3A",
    "burgundy": "#6E2530",
    "oxblood": "#4A1A1F",
    "scarlet": "#C8281A",
    "coral": "#EC7D65",
    "peach": "#F3C9A4",
    # Pinks / magentas
    "pink": "#E8B7C0",
    "magenta": "#C02E6E",
    # Purples
    "lilac": "#C8A8D8",
    "lavender": "#B8A6D4",
    "purple": "#4E2D63",
    # Blues
    "navy": "#1B2A4E",
    "cobalt": "#2050A8",
    "prussian-blue": "#0B3B5C",
    "sky-blue": "#8FB8D8",
    "periwinkle": "#8C94D4",
    "turquoise": "#2AA198",
    # Greens
    "teal": "#1F6F6A",
    "sage": "#A8B49A",
    "olive": "#7A7645",
    "forest-green": "#2C4A34",
    "lime": "#A8C042",
    "pea-green": "#6E8B3D",
    # Yellows
    "mustard": "#D6A845",
    "butter": "#F0D88A",
    # Metallics / special
    "gold": "#BF9A56",
    "brass": "#B08A4F",
    "silver": "#BCC0C4",
    "chrome": "#C8CCD2",
    "neon": "#39FF14",
    "pastel": "#E8D6E5",
}

# Default font pair per type_genre. The google_font flag defaults to True
# because `_design_lib` will also emit a Google Fonts install step -- the
# two originals that use system fonts (obel/cream, chonk/black) are fine
# without it, but new themes spun up from concepts want a real typeface.
TYPE_GENRE_FONTS: dict[str, dict[str, dict]] = {
    "oldstyle-serif": {
        "display": {"family": "Cormorant Garamond"},
        "sans": {"family": "Inter"},
    },
    "transitional-serif": {
        "display": {"family": "Source Serif 4"},
        "sans": {"family": "Inter"},
    },
    "modern-serif": {
        "display": {"family": "Playfair Display"},
        "sans": {"family": "Inter"},
    },
    "slab-serif": {
        "display": {"family": "Roboto Slab"},
        "sans": {"family": "Inter"},
    },
    "wood-type": {
        "display": {"family": "Roboto Slab"},
        "sans": {"family": "Inter"},
    },
    "blackletter": {
        "display": {"family": "UnifrakturMaguntia"},
        "sans": {"family": "Inter"},
    },
    "art-deco": {
        "display": {"family": "Poiret One"},
        "sans": {"family": "Inter"},
    },
    "art-nouveau": {
        "display": {"family": "Cinzel Decorative"},
        "sans": {"family": "Inter"},
    },
    "geometric-sans": {
        "display": {"family": "Bebas Neue"},
        "sans": {"family": "Inter"},
    },
    "grotesk-sans": {
        "display": {"family": "Bricolage Grotesque"},
        "sans": {"family": "Inter"},
    },
    "humanist-sans": {
        "display": {"family": "Recoleta"},
        "sans": {"family": "Inter"},
    },
    "condensed-sans": {
        "display": {"family": "Oswald"},
        "sans": {"family": "Inter"},
    },
    "hand-script": {
        "display": {"family": "Caveat"},
        "sans": {"family": "Inter"},
    },
    "brush-script": {
        "display": {"family": "Kaushan Script"},
        "sans": {"family": "Inter"},
    },
    "hand-lettered": {
        "display": {"family": "Permanent Marker"},
        "sans": {"family": "Inter"},
    },
    "pixel": {
        "display": {"family": "Press Start 2P"},
        "sans": {"family": "Inter"},
    },
    "monospace": {
        "display": {"family": "JetBrains Mono"},
        "sans": {"family": "Inter"},
    },
    "chrome-deco": {
        "display": {"family": "Orbitron"},
        "sans": {"family": "Inter"},
    },
    "stencil": {
        "display": {"family": "Stardos Stencil"},
        "sans": {"family": "Inter"},
    },
    "comic": {
        "display": {"family": "Bangers"},
        "sans": {"family": "Inter"},
    },
    "ornamental": {
        "display": {"family": "Cinzel Decorative"},
        "sans": {"family": "Inter"},
    },
}

# Starter layout hints per hero composition. These are directions, not
# finished designs: the template-restructure pass that follows is where
# the operator + vision reviewer earn their keep.
HERO_COMPOSITION_HINTS: dict[str, list[str]] = {
    "type-led": [
        "oversized display wordmark anchored to the top-left",
        "thin rule beneath the hero",
        "three-up product grid below the hero",
    ],
    "illustration-led": [
        "hand-drawn illustration banded across the full hero width",
        "wordmark overlapping the illustration's lower third",
        "four-up product grid below",
    ],
    "photo-hero": [
        "full-bleed hero photograph with short overlaid tagline",
        "product category cards immediately below",
    ],
    "split-photo": [
        "50/50 split hero with image on one side and copy on the other",
        "three-up product grid below",
    ],
    "full-bleed": [
        "edge-to-edge hero graphic",
        "tight centered wordmark on top of the hero",
        "four-up product grid below",
    ],
    "diagram-led": [
        "labelled diagram as the hero centerpiece",
        "caption strip beneath the diagram",
        "three-up product grid below",
    ],
    "pattern-led": [
        "repeating pattern as the hero background",
        "centered wordmark + tagline over the pattern",
        "three-up product grid below",
    ],
    "multi-panel": [
        "hero composed of three distinct panels (poster / product / copy)",
        "product categories wrapping below as a 2x2 grid",
    ],
    "collage": [
        "layered collage hero with ragged-edged photo clippings",
        "text strip beneath the collage",
        "three-up product grid below",
    ],
    "specimen-grid": [
        "hero is a labelled 3-cell specimen grid",
        "wordmark band above the specimens",
        "product cards below echo the same grid rhythm",
    ],
}


# ---------------------------------------------------------------------------
# Deterministic concept -> spec mapping
# ---------------------------------------------------------------------------


class ConceptToSpecError(ValueError):
    """Raised when a concept record can't be mapped to a valid spec.

    Caller should format the message and exit non-zero; the error path
    is reserved for "this concept's metadata is broken", not "the LLM
    didn't respond" (that surfaces as a different exception from
    `_vision_lib`).
    """


def _parse_type_specimen(type_specimen: str) -> tuple[str, str]:
    """Parse "Display: <foo>. Body: <bar>." into (display_family, body_family).

    Tolerant of odd whitespace and trailing periods. Returns empty
    strings for any half that isn't found so the caller can fall back
    to TYPE_GENRE_FONTS defaults.
    """
    display, body = "", ""
    for segment in type_specimen.split("."):
        s = segment.strip()
        if not s:
            continue
        if s.lower().startswith("display:"):
            display = s.split(":", 1)[1].strip()
            # Trim "/" alternate listings and lowercase-body punctuation:
            # `Display: Eurostile / Bank Gothic` -> keep first option.
            display = display.split(" / ")[0].split(",")[0].strip()
        elif s.lower().startswith("body:"):
            body = s.split(":", 1)[1].strip()
            body = body.split(" / ")[0].split(",")[0].strip()
    return display, body


def build_palette(palette_tags: list[str]) -> dict[str, str]:
    """Build a `design.py` spec `palette` dict from the concept's tags.

    Strategy:
      * base/surface/subtle: the first neutral-family tag, then its two
        lightest siblings. If no neutral appears, default to cream/white.
      * contrast/primary:    first ink-family tag, default to ink.
      * accent:              first remaining color tag, default to the
                             concept's second-listed tag.
    """
    neutrals = [t for t in palette_tags if t in _NEUTRAL_TAGS]
    inks = [t for t in palette_tags if t in _INK_TAGS]
    accents = [t for t in palette_tags if t not in _NEUTRAL_TAGS and t not in _INK_TAGS]

    base_tag = neutrals[0] if neutrals else "cream"
    ink_tag = inks[0] if inks else "ink"
    accent_tag = accents[0] if accents else (palette_tags[0] if palette_tags else "terracotta")

    base = PALETTE_TAG_TO_HEX[base_tag]
    ink = PALETTE_TAG_TO_HEX[ink_tag]
    accent = PALETTE_TAG_TO_HEX[accent_tag]

    # Lighten subtle/muted/border mechanically from the base by shifting
    # toward #FFFFFF; good enough for a starting palette, hand-polished
    # by the vision review pass afterwards.
    subtle = _tint(base, 0.4)
    muted = _tint(base, 0.7)
    border = _shade(base, 0.25)
    tertiary = _shade(ink, 0.4)
    secondary = _shade(ink, 0.2)

    return {
        "base": base,
        "surface": PALETTE_TAG_TO_HEX.get("white", "#FFFFFF"),
        "subtle": subtle,
        "muted": muted,
        "border": border,
        "tertiary": tertiary,
        "secondary": secondary,
        "contrast": ink,
        "primary": ink,
        "primary-hover": _shade(ink, -0.2),
        "accent": accent,
        "accent-soft": _accent_soft_for_base(accent, base),
    }


_NEUTRAL_TAGS = {"cream", "paper", "white", "kraft", "tan"}
_INK_TAGS = {"ink", "black", "charcoal", "monochrome", "slate"}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _relative_luminance(h: str) -> float:
    r, g, b = (channel / 255 for channel in _hex_to_rgb(h))

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _tint(h: str, amount: float) -> str:
    """Blend `amount` fraction toward white. amount=0 returns h; 1 returns white."""
    r, g, b = _hex_to_rgb(h)
    return _rgb_to_hex(
        (
            r + (255 - r) * amount,
            g + (255 - g) * amount,
            b + (255 - b) * amount,
        )
    )


def _shade(h: str, amount: float) -> str:
    """Blend `amount` fraction toward black. amount<0 shades brighter
    (it mirrors tint for negative amounts) so callers can use a single
    knob for "go a little darker" / "go a little brighter"."""
    if amount < 0:
        return _tint(h, -amount)
    r, g, b = _hex_to_rgb(h)
    return _rgb_to_hex((r * (1 - amount), g * (1 - amount), b * (1 - amount)))


def _accent_soft_for_base(accent: str, base: str) -> str:
    """Return an accent-soft token on the same luminance side as base."""
    base_is_light = _relative_luminance(base) >= 0.5
    candidates = (
        (_tint(accent, amount) for amount in (0.65, 0.75, 0.85, 0.92, 1.0))
        if base_is_light
        else (_shade(accent, amount) for amount in (0.35, 0.5, 0.65, 0.8, 1.0))
    )
    for candidate in candidates:
        if (_relative_luminance(candidate) >= 0.5) == base_is_light:
            return candidate
    return "#FFFFFF" if base_is_light else "#000000"


def build_fonts(type_genre: str, type_specimen: str) -> dict[str, dict]:
    """Build the spec `fonts` dict from a type_specimen hint + type_genre fallback."""
    display_family, body_family = _parse_type_specimen(type_specimen)
    defaults = TYPE_GENRE_FONTS.get(type_genre, TYPE_GENRE_FONTS["humanist-sans"])

    display_slot = {
        "family": display_family or defaults["display"]["family"],
        "fallback": "Georgia, 'Times New Roman', serif",
        "google_font": True,
        "weights": [400, 700],
    }
    sans_slot = {
        "family": body_family or defaults["sans"]["family"],
        "fallback": "-apple-system, BlinkMacSystemFont, sans-serif",
        "google_font": True,
        "weights": [400, 600],
    }
    return {
        "display": display_slot,
        "sans": sans_slot,
    }


def build_layout_hints(hero_composition: str) -> list[str]:
    """Return a list of layout hints for the given hero composition.

    Falls back to the `type-led` hints if we've never seen this
    composition before (shouldn't happen because `concept_seed.py`
    enforces the controlled vocab, but better a generic hint than
    a crash).
    """
    return list(HERO_COMPOSITION_HINTS.get(hero_composition, HERO_COMPOSITION_HINTS["type-led"]))


def concept_to_spec(concept: dict) -> dict:
    """Deterministic (concept + tag lookups) -> spec dict.

    The result is NOT yet validated; call `_design_lib.validate_spec`
    on the return value. We separate "shape the dict" from "validate"
    so the LLM path can splice in a self-correction loop.

    Required concept keys (per `concept_seed.py` schema):
      slug, name, blurb, palette_tags, type_genre, era, sector,
      hero_composition, type_specimen.
    """
    for key in (
        "slug", "name", "blurb", "palette_tags",
        "type_genre", "type_specimen", "hero_composition",
    ):
        if key not in concept:
            raise ConceptToSpecError(f"concept missing required key: {key!r}")

    unknown_tags = [t for t in concept["palette_tags"] if t not in PALETTE_TAG_TO_HEX]
    if unknown_tags:
        raise ConceptToSpecError(
            f"concept {concept['slug']!r} references palette_tags not in "
            f"PALETTE_TAG_TO_HEX: {unknown_tags}. Add them to both "
            "concept_seed.PALETTE_TOKENS and PALETTE_TAG_TO_HEX."
        )

    palette = build_palette(concept["palette_tags"])
    fonts = build_fonts(concept["type_genre"], concept["type_specimen"])
    layout_hints = build_layout_hints(concept["hero_composition"])

    spec = {
        "slug": concept["slug"],
        "name": concept["name"],
        "tagline": concept["blurb"].split(":", 1)[-1].strip().rstrip("."),
        # Voice is a starter sentence; the LLM path rewrites it with the
        # mockup + brand context. In --no-llm mode we derive a workable
        # default from the sector + era so the spec validates and the
        # theme clones without a follow-up hand-edit.
        "voice": (
            f"{concept.get('era', 'contemporary')} {concept.get('sector', 'general')} "
            f"store: warm, direct, no exclamation marks."
        ),
        "source": _default_source_theme(concept),
        "palette": palette,
        "fonts": fonts,
        "layout_hints": layout_hints,
    }
    return spec


def _default_source_theme(concept: dict) -> str:
    """Pick an anchor theme to clone from based on the concept's
    controlled-vocab tags.

    `bin/clone.py` copies the theme at `--source=<anchor>` as the
    starting point before `design.py` applies the palette + fonts.
    Picking a closer anchor means fewer spec-level surprises later
    (e.g. a Y2K concept anchored on Aero inherits the chrome-deco
    scaffolding, not Obel's editorial one).
    """
    era = concept.get("era", "contemporary")
    hero = concept.get("hero_composition", "type-led")
    if era in ("y2k", "1990s"):
        return "aero"
    if hero in ("type-led", "multi-panel") and era == "pre-1950":
        return "chonk"
    if concept.get("sector") in ("workwear", "apparel", "footwear", "leather-goods"):
        return "selvedge"
    if concept.get("sector") in ("food", "bakery", "beverage", "coffee"):
        return "lysholm"
    return "obel"


def write_spec(spec: dict, out_path: Path) -> None:
    """Validate + write `spec` to `out_path` (pretty JSON, trailing newline).

    Raises `ConceptToSpecError` on validation failure, with every
    per-field error joined into the message so the caller doesn't
    need to know the SpecError shape.
    """
    errors, validated = validate_spec(spec)
    if errors:
        joined = "; ".join(f"{e.path}: {e.message}" for e in errors)
        raise ConceptToSpecError(f"spec failed validation: {joined}")
    assert validated is not None
    safety_errors = validate_generation_safety(validated)
    if safety_errors:
        joined = "; ".join(f"{e.path}: {e.message}" for e in safety_errors)
        raise ConceptToSpecError(f"spec failed generation safety validation: {joined}")
    # ValidatedSpec has a `.as_dict()` when validate_spec populates it;
    # but we already have a JSON-shaped dict and validation just
    # confirmed it. Write the source dict so the emitted file matches
    # what we constructed 1:1.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    out_path.write_text(payload, encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM-assisted mode (thin wrapper around _vision_lib)
# ---------------------------------------------------------------------------

LLM_SYSTEM_PROMPT = """You are a design translator. Given a curated concept entry
(name, palette_tags, type_genre, era, sector, hero_composition, type_specimen,
blurb) and a mockup PNG of the intended storefront, produce a JSON object
that conforms EXACTLY to the schema used by `bin/design.py --spec`. Do not
wrap the JSON in prose; your entire response MUST be the JSON object.

Schema (all fields required unless marked optional):

  slug          lower-kebab string, 2-39 chars (copy from the concept)
  name          display title (copy from the concept)
  tagline       short phrase, <= 72 chars, no trailing period
  voice         one sentence, microcopy guidance (optional but recommended)
  source        one of: obel, chonk, selvedge, lysholm, aero, foundry
  palette       object with keys: base, surface, subtle, muted, border,
                tertiary, secondary, contrast, primary, primary-hover,
                accent, accent-soft. Each value is a #RRGGBB hex string.
  fonts         object. MUST include `display` and `sans` keys; each is
                an object with `family` (string), `fallback` (string),
                `google_font` (bool), `weights` (list of ints).
  layout_hints  list of short phrases describing the hero / home layout.

Use the mockup to pick actual sampled hex values when the palette tags are
ambiguous. Use the concept's type_specimen as a strong signal for the
`display` font family; default `sans` to Inter unless the mockup clearly
indicates otherwise.
"""


def build_llm_user_prompt(concept: dict) -> str:
    """Prompt fragment describing the concept to send alongside the mockup."""
    fields = ", ".join(
        f"{k}={concept.get(k)!r}"
        for k in (
            "slug", "name", "palette_tags", "type_genre", "era",
            "sector", "hero_composition", "type_specimen", "blurb",
        )
    )
    return (
        f"Concept metadata: {fields}\n\n"
        f"Produce the JSON spec described in the system prompt. Output the "
        f"JSON object ONLY. No code fences, no commentary."
    )


def _parse_spec_json(raw_text: str) -> dict:
    """Extract a spec dict from the model's raw text response.

    Tolerates a stray ```json fence or prose prefix/suffix -- the
    system prompt says "no code fences" but models occasionally emit
    them anyway and the cost of one `str.strip()` here is lower than
    the cost of rerunning the call.
    """
    raw = (raw_text or "").strip()
    if not raw:
        raise ConceptToSpecError("LLM returned empty text; cannot parse spec")
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConceptToSpecError(
            f"LLM response was not valid JSON: {e}. Raw: {raw[:200]!r}"
        ) from e
    if not isinstance(data, dict):
        raise ConceptToSpecError("LLM response was not a JSON object")
    return data


def _validation_retry_prompt(concept: dict, previous: dict, errors: list) -> str:
    """Second-attempt prompt that feeds the validator's per-field errors
    back to the model so it can self-correct.

    Kept as a module-level helper so the test suite can assert its
    shape without monkey-patching the whole LLM path.
    """
    err_lines = "\n".join(f"  {e.path}: {e.message}" for e in errors)
    return (
        f"Your previous response for concept `{concept.get('slug')}` "
        f"failed spec validation. Here is the response you returned:\n\n"
        "```json\n"
        f"{json.dumps(previous, indent=2, ensure_ascii=False)}\n"
        "```\n\n"
        "The validator reported these errors (format is `$.field.path: "
        "reason`):\n\n"
        f"{err_lines}\n\n"
        "Return a corrected JSON object that fixes every listed error "
        "while keeping the rest of your design decisions intact. Output "
        "the JSON object ONLY. No code fences, no commentary."
    )


def concept_to_spec_llm(
    concept: dict,
    mockup_png: Path,
    *,
    dry_run: bool = False,
    model: str | None = None,
) -> dict:
    """LLM-assisted spec: sends the mockup + concept metadata to Claude
    and parses the returned JSON into a validated spec.

    In `dry_run` mode we short-circuit to the deterministic
    `concept_to_spec` so a caller can smoke-test the wiring without
    an API key. That keeps the test surface sane (tests never hit
    the network) while still exercising the `--llm` code path.

    On validation failure after the first call, the model is
    re-prompted once with the validator's per-field errors so it can
    self-correct. A second failure surfaces the errors to the caller
    (who then either edits the spec by hand, switches to `--no-llm`,
    or opens a prompt issue).

    This function was previously a thin adapter over
    `_vision_lib.review_image`, but that helper hard-codes a
    findings-rubric system prompt; the model dutifully returned
    `{"findings": []}` instead of a spec. The fix is to call
    `_vision_lib.vision_completion` (the generic primitive that takes
    caller-supplied system + user prompts) with the concept-to-spec
    system prompt.
    """
    if dry_run:
        return concept_to_spec(concept)

    # Import lazily so tests + the --no-llm path don't pay the
    # _vision_lib import weight (it pulls urllib + PIL at module level).
    from _vision_lib import (
        DEFAULT_MODEL,
        ApiKeyMissingError,
        vision_completion,
    )

    if not mockup_png.is_file():
        raise ConceptToSpecError(
            f"mockup not found: {mockup_png}. Run `python3 bin/paint-mockup.py "
            f"{concept.get('slug')}` first, or pass --no-llm for the "
            "deterministic fallback."
        )

    slug = concept.get("slug", "")
    chosen_model = model or DEFAULT_MODEL
    user_prompt = build_llm_user_prompt(concept)

    def _call(prompt: str) -> dict:
        try:
            resp = vision_completion(
                png_path=mockup_png,
                system_prompt=LLM_SYSTEM_PROMPT,
                user_prompt=prompt,
                theme=slug,
                route="concept-to-spec",
                viewport="mockup",
                model=chosen_model,
                dry_run=False,
            )
        except ApiKeyMissingError as e:
            raise ConceptToSpecError(str(e)) from e
        return _parse_spec_json(resp.raw_text)

    data = _call(user_prompt)
    errors, _ = validate_spec(data)
    if not errors:
        return data

    # Self-correct once. If the model can't fix its own JSON with the
    # errors spelled out, a second attempt almost never helps -- surface
    # to the caller instead of burning more budget.
    retry_prompt = _validation_retry_prompt(concept, data, errors)
    data = _call(retry_prompt)
    errors, _ = validate_spec(data)
    if errors:
        joined = "; ".join(f"{e.path}: {e.message}" for e in errors)
        raise ConceptToSpecError(
            f"LLM spec still failed validation after one self-correction "
            f"pass: {joined}. Re-run with --no-llm for the deterministic "
            f"fallback, or author tmp/specs/{slug}.json by hand."
        )
    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_concept(slug: str) -> dict:
    """Return the CONCEPTS[slug] entry or raise a clear error."""
    from concept_seed import CONCEPTS

    for c in CONCEPTS:
        if c.get("slug") == slug:
            return c
    raise ConceptToSpecError(f"concept {slug!r} not found in bin/concept_seed.py CONCEPTS")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Translate a concept_seed entry + its mockup PNG into a "
        "design.py spec JSON.",
    )
    p.add_argument(
        "--slug", required=True,
        help="Concept slug (must exist in bin/concept_seed.CONCEPTS).",
    )
    p.add_argument(
        "--out", default=None, type=Path,
        help="Where to write the validated spec (default: tmp/specs/<slug>.json).",
    )
    p.add_argument(
        "--no-llm", action="store_true",
        help=(
            "Skip the vision model; derive the spec entirely from the "
            "concept's controlled-vocab tags + the lookup tables in this "
            "script. Deterministic, reproducible, free. Good for tests and "
            "a known-good baseline before an LLM iteration pass."
        ),
    )
    p.add_argument(
        "--mockup", default=None, type=Path,
        help="Path to the concept mockup PNG (default: docs/mockups/<slug>.png).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Pretend to call the LLM but actually fall through to --no-llm "
             "semantics (useful in CI where no API key is configured).",
    )
    p.add_argument(
        "--print-only", action="store_true",
        help="Print the validated spec to stdout instead of writing a file.",
    )
    args = p.parse_args(argv)

    try:
        concept = _load_concept(args.slug)
    except ConceptToSpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    mockup = args.mockup or (ROOT / "docs" / "mockups" / f"{args.slug}.png")

    try:
        if args.no_llm or args.dry_run:
            spec = concept_to_spec(concept)
        else:
            spec = concept_to_spec_llm(concept, mockup, dry_run=False)
    except ConceptToSpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    errors, validated = validate_spec(spec)
    if errors:
        print("spec failed validation after generation:", file=sys.stderr)
        for err in errors:
            print(f"  {err.path}: {err.message}", file=sys.stderr)
        return 1
    assert validated is not None
    safety_errors = validate_generation_safety(validated)
    if safety_errors:
        print("spec failed generation safety validation after generation:", file=sys.stderr)
        for err in safety_errors:
            print(f"  {err.path}: {err.message}", file=sys.stderr)
        return 1

    if args.print_only:
        print(json.dumps(spec, indent=2, ensure_ascii=False))
        return 0

    out = args.out or (ROOT / "tmp" / "specs" / f"{args.slug}.json")
    try:
        write_spec(spec, out)
    except ConceptToSpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Re-export for callers that import this module directly (e.g. tests
# or `bin/design-batch.py --from-concepts`) so they don't need to know
# about KNOWN_FONT_SLUGS (it's asserted here in case the design_lib
# contract evolves in a way that would silently invalidate our fonts
# dict shape).
assert "display" in KNOWN_FONT_SLUGS and "sans" in KNOWN_FONT_SLUGS, (
    "concept-to-spec assumes `display` + `sans` are KNOWN_FONT_SLUGS; "
    "_design_lib's contract has drifted."
)
