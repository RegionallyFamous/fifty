#!/usr/bin/env python3
"""Emit the canonical two-view (home + shop) image-generation prompt for
a concept, derived from its ``mockups/<slug>.meta.json``.

Why this script exists
----------------------
The Bauhaus mockup (``mockups/mockup-bauhaus.png``) sets the composition
standard for every concept on the bench: two desktop browser windows
shown side-by-side, the LEFT window painting the home page (header +
hero + featured products + footer), the RIGHT window painting the shop
grid (header + 3-4 column product card grid + footer). Every other
concept ships its own brand voice (palette, typography, era), but the
*structure* of the mockup is fixed so the queue browses as a single,
coherent visual library rather than an unrelated bag of design
sketches.

Without this helper the prompt drifts every time someone (a human or an
agent) generates a new concept mockup — one batch comes back as full-
bleed editorial photographs, the next as abstract patterns, the next
as exploded-axonometric product diagrams. Forcing every regeneration
through one canonical prompt template is the single cheapest way to
keep the queue on-brief without enforcement at PNG-inspection time.

Usage
-----

    # Print the canonical prompt for one concept to stdout
    python3 bin/paint-mockup.py bauhaus

    # Emit a JSON envelope (prompt + filename + dims + reference) so an
    # agent runtime can feed it straight into an image-generation tool.
    python3 bin/paint-mockup.py bauhaus --json

    # Walk every concept and emit one prompt envelope per slug, suitable
    # for batched regeneration.
    python3 bin/paint-mockup.py --all --json > /tmp/regen.jsonl

Output contract
---------------
The prompt itself is a single self-contained string that:

* Names the layout shape (two browser windows, side-by-side, neutral
  backdrop, no devices).
* Describes the LEFT window (home page) and RIGHT window (shop grid)
  with concrete element lists so the generator knows what to paint.
* Pins the palette to the concept's ``palette_hex`` and the typography
  to its ``type_specimen``.
* Calls out the era / sector / hero_composition tags so the brand
  voice stays on-brief.
* Asks for the canonical 1376x768 landscape framing (matches every
  existing PNG in ``mockups/``).

The script does NOT call any image-generation API itself. The repo's
tooling is stdlib-only by convention (see ``bin/_vision_lib.py`` for
the one exception: the Anthropic-vision REVIEWER, used by
``bin/snap-vision-review.py``). Image *generation* is intentionally
left to the calling agent's own image tool (or a human pasting into
Midjourney / ChatGPT / Imagen) — the script's job is to produce the
deterministic prompt those tools should be handed.

Idempotency
-----------
Running the script never writes anything to disk. Re-running with the
same ``concept_seed.py`` + ``mockups/<slug>.meta.json`` always emits
byte-identical prompts.

See also
--------
* ``mockups/README.md`` — workflow documentation, including the
  two-view convention this script enforces by template.
* ``bin/concept_seed.py`` — source-of-truth metadata for each concept.
* ``bin/build-concept-meta.py`` — generates the per-concept JSON this
  script reads.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT

MOCKUPS_DIR = MONOREPO_ROOT / "mockups"

# Canonical output dimensions. Every existing mockup is 1376x768
# (~1.79:1 landscape). Keeping new generations at the same shape means
# the docs/concepts/ gallery, the audit grid, and the queue card layout
# don't have to deal with mixed aspect ratios.
CANONICAL_WIDTH = 1376
CANONICAL_HEIGHT = 768

# The reference image we hand the generator alongside the prompt.
# Bauhaus is the canonical two-view example — using it as a structural
# reference keeps every regeneration in the same composition family
# even when the brand voice (palette, type, era) is wildly different.
REFERENCE_SLUG = "bauhaus"


def _read_meta(slug: str) -> dict:
    meta_path = MOCKUPS_DIR / f"{slug}.meta.json"
    if not meta_path.is_file():
        raise SystemExit(
            f"missing {meta_path.relative_to(MONOREPO_ROOT)} — run "
            f"`python3 bin/build-concept-meta.py --slug {slug}` first"
        )
    return json.loads(meta_path.read_text())


def build_prompt(meta: dict) -> str:
    """Compose the canonical two-view prompt for one concept.

    Pure function on the meta dict so the script is trivially testable
    and the prompt template can evolve in one place. Kept as a single
    triple-quoted string with explicit interpolation rather than a
    multi-step f-string assembly so a reader can hold the entire
    instruction in their head at once.
    """
    name = meta["name"]
    slug = meta["slug"]
    blurb = meta["blurb"]
    tags = meta.get("tags") or {}
    palette_tokens = tags.get("palette") or []
    type_genre = tags.get("type") or "sans"
    era = tags.get("era") or "contemporary"
    sector = tags.get("sector") or "general retail"
    hero = tags.get("hero") or "type-led"
    palette_hex = meta.get("palette_hex") or []
    type_specimen = meta.get("type_specimen") or "Display: a brand-appropriate display face. Body: Inter."

    palette_line = ", ".join(palette_hex) if palette_hex else "(none recorded)"
    palette_token_line = ", ".join(palette_tokens) if palette_tokens else "(none recorded)"

    return f"""\
Two-view mockup of a fictional WordPress storefront concept named "{name}". Output dimensions {CANONICAL_WIDTH}x{CANONICAL_HEIGHT} pixels (landscape, ~16:9). Composition: TWO desktop browser windows shown side-by-side on a neutral light-grey backdrop with a small gap between them. Both windows must look like real screenshots of two pages of the SAME fictional storefront — same brand mark, same navigation, same palette, same typography, same chrome — not two unrelated designs.

LEFT WINDOW — HOME PAGE (address bar reads `{slug}.example/`):
- Browser chrome at the top (traffic-light dots, address bar, tab strip).
- Persistent site header inside the page: brand wordmark on the left, primary navigation links on the right (Home, Shop, About, Cart or equivalent in the brand voice).
- Hero section that captures the brand idea — bold headline typography, ONE confident hero element (illustration, product still-life, pattern, or photograph as appropriate to the era + hero_composition tag), and one primary CTA button below.
- Featured products row underneath the hero: 3 or 4 product cards in a single row, each with a square product image, product name, price, and small add-to-cart pill button.
- Slim site footer at the bottom: copyright line + 2-3 secondary links.

RIGHT WINDOW — SHOP / CATEGORY GRID PAGE (address bar reads `{slug}.example/shop/`):
- Same browser chrome.
- IDENTICAL persistent site header (same wordmark, same nav). This is critical — the two windows must read as two pages of the same shop.
- A short page heading at the top of the content area ("Shop", "Catalog", "Press", "Atelier", "Apothecary" — choose what fits the brand voice).
- A product card grid: 4 columns x 3 rows = 12 product cards. Each card shows a square product photo, product name, price, and a small "ADD TO CART" / "ORDER" / "BOTTLE ONE" / equivalent label appropriate to the brand voice.
- Same slim site footer at the bottom.

BRAND BRIEF
-----------
Concept blurb: {blurb}
Palette tokens: {palette_token_line}
Palette hex (use ONLY these colors for ink, surfaces, accents, and product chrome): {palette_line}
Typography: {type_specimen}
Type genre: {type_genre}
Era / sensibility: {era}
Sector: {sector}
Hero composition style: {hero}

REQUIREMENTS
------------
1. Both windows must use the SAME palette, the SAME typography, and the SAME header chrome. The mockup is one fictional storefront seen across two pages, not two themes side-by-side.
2. Show full chrome on each window (header, content, footer) — no half-pages, no zoomed-in product detail, no devices/laptops/desks/people in frame.
3. The grid on the right must be a real product card grid (4 cols x 3 rows). Do not paint a single hero image, an editorial spread, or a pattern in the right window.
4. The left window must clearly read as a HOME page, not a single product detail page. Hero + featured row + footer.
5. The mockup MUST evoke the era and sector tags above. Reference the Bauhaus mockup at the same path for the structural standard — match its TWO-WINDOW composition, not its colors or typography.
6. No text gibberish in product names — short plausible names (1-3 words, in the brand voice).
7. Backdrop between/around the two browser windows is neutral light grey (#e6e6e6 to #f0f0f0). No drop shadows, no gradients, no mockup props.
"""


def build_envelope(meta: dict) -> dict:
    """Return a JSON-serialisable envelope an agent runtime can feed
    straight into an image-generation tool. Includes the canonical
    output filename and the reference image path (the Bauhaus PNG) so
    the call site doesn't need to re-derive either.
    """
    slug = meta["slug"]
    return {
        "slug": slug,
        "name": meta["name"],
        "filename": f"mockup-{slug}.png",
        "destination": str((MOCKUPS_DIR / f"mockup-{slug}.png").relative_to(MONOREPO_ROOT)),
        "width": CANONICAL_WIDTH,
        "height": CANONICAL_HEIGHT,
        "reference_image": str((MOCKUPS_DIR / f"mockup-{REFERENCE_SLUG}.png").relative_to(MONOREPO_ROOT)),
        "prompt": build_prompt(meta),
    }


def _iter_slugs() -> list[str]:
    return sorted(p.name.removesuffix(".meta.json") for p in MOCKUPS_DIR.glob("*.meta.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the canonical two-view image-generation prompt for one concept."
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="Concept slug (e.g. `bauhaus`). Required unless --all is set.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Emit prompts for every concept that has a `mockups/<slug>.meta.json`.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON envelope (one per line if --all). Default is the prompt text only.",
    )
    args = parser.parse_args(argv)

    if not args.slug and not args.all:
        parser.error("provide a slug or pass --all")

    slugs = _iter_slugs() if args.all else [args.slug]
    for slug in slugs:
        meta = _read_meta(slug)
        if args.json:
            print(json.dumps(build_envelope(meta)))
        else:
            if args.all:
                print(f"\n# === {slug} ===\n")
            print(build_prompt(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
