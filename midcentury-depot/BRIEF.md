# Midcentury Depot — design brief

This file was emitted by `bin/design.py` after cloning `obel` -> `midcentury-depot` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Postwar charm, modern goods.

## Voice

warm midcentury department store: 'parcel' for order, 'register' for checkout, 'kindly' on prompts, '·' as the required-field marker, 'browse the floor' for shop, 'your parcel awaits' on order confirmation

Write this voice into the `// === BEGIN wc microcopy ===` block in `midcentury-depot/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- full-bleed warm-cream hero with offset burnt-orange product image and hand-stamped badge
- tiled 3x2 department category grid with label overlays
- horizontal marquee announcement strip above header
- editorial split-panel feature section alternating text and image
- footer with retro column layout and parcel-tracking callout

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#c96a28` |
| `accent-soft` | `#f2d4b0` |
| `base` | `#f5efe6` |
| `border` | `#c8b99f` |
| `contrast` | `#1f1a13` |
| `error` | `#b03a2e` |
| `info` | `#3a6b8a` |
| `muted` | `#d9ccba` |
| `primary` | `#1f1a13` |
| `primary-hover` | `#3d3322` |
| `secondary` | `#5c4f3a` |
| `subtle` | `#ede4d6` |
| `success` | `#4a7c59` |
| `surface` | `#ffffff` |
| `tertiary` | `#7a6a54` |
| `warning` | `#c97b28` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `midcentury-depot/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Bricolage Grotesque` (display, weights 400, 600, 700)
- `Inter` (sans, weights 400, 500, 600)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `midcentury-depot/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py midcentury-depot`.
6. Snap baseline: `python3 bin/snap.py shoot midcentury-depot && \
   python3 bin/snap.py baseline midcentury-depot`.
7. Verify: `python3 bin/check.py midcentury-depot --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for midcentury-depot by `bin/design.py`._
