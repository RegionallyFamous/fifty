# Xerox — design brief

This file was emitted by `bin/design.py` after cloning `chonk` -> `xerox` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> kill yr product grid — everything is for sale, sorry

## Voice

Write like you're scrawling on a flyer at 2am — blunt, lowercase, no fluff.

Write this voice into the `// === BEGIN wc microcopy ===` block in `xerox/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- Full-bleed grainy halftone hero image left, product polaroid grid right
- Torn paper and tape textures as section dividers
- Ransom-note mixed-size headline spanning full width
- Product cards styled as Polaroid photos with paperclip accents
- Hand-drawn circle and safety-pin SVG annotations over hero image
- Black ink stamp CTA buttons with border-only style
- Footer banner uses typewriter ticker with sliding-scale pricing copy
- Navigation set in all-caps with double-slash separators

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#e8400a` |
| `accent-soft` | `#f5c4b0` |
| `base` | `#e8e4d8` |
| `border` | `#1a1a18` |
| `contrast` | `#0d0d0b` |
| `muted` | `#a09a8e` |
| `primary` | `#0d0d0b` |
| `primary-hover` | `#2e2c28` |
| `secondary` | `#2e2c28` |
| `subtle` | `#d6d1c4` |
| `surface` | `#f0ecdf` |
| `tertiary` | `#6b6760` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `xerox/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Courier Prime` (display, weights 400, 700)
- `Courier Prime` (sans, weights 400, 700)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `xerox/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py xerox`.
6. Snap baseline: `python3 bin/snap.py shoot xerox && \
   python3 bin/snap.py baseline xerox`.
7. Verify: `python3 bin/check.py xerox --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for xerox by `bin/design.py`._
