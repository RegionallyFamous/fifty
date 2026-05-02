# Lab Decant — design brief

This file was emitted by `bin/design.py` after cloning `obel` -> `lab-decant` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Niche fragrance samples by the millilitre.

## Voice

Technician who measures in mL — neutral, batch-and-lot specific, never perfume-review florals. Cart: Tray. Sort: By mL price / by house. Sold-out: Bottle exhausted — awaiting fresh source.

Write this voice into the `// === BEGIN wc microcopy ===` block in `lab-decant/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- From vibes/Concepts/46-lab-decant.yaml: lab-data dense, search-led, monospace display for mL and batch language
- Hero stays light: search-by-house bar energy without breaking block-theme constraints
- Category story: by house / by perfumer / by size / sample sets / library subscription / about decanting

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#1f66b5` |
| `accent-soft` | `#d4e4f5` |
| `base` | `#ffffff` |
| `border` | `#c4c4bc` |
| `contrast` | `#0f0f12` |
| `muted` | `#9a9a94` |
| `primary` | `#0f0f12` |
| `primary-hover` | `#1a1a22` |
| `secondary` | `#2a2a28` |
| `subtle` | `#e2e2dc` |
| `surface` | `#f8f8f4` |
| `tertiary` | `#5a5a58` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `lab-decant/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `JetBrains Mono` (display, weights 400, 700)
- `IBM Plex Sans` (sans, weights 400, 500, 600)
- `JetBrains Mono` (mono, weights 400, 600)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `lab-decant/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py lab-decant`.
6. Snap baseline: `python3 bin/snap.py shoot lab-decant && \
   python3 bin/snap.py baseline lab-decant`.
7. Verify: `python3 bin/check.py lab-decant --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for lab-decant by `bin/design.py`._
