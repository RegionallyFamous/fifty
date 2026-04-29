# Butcher — design brief

This file was emitted by `bin/design.py` after cloning `lysholm` -> `butcher` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> white tile, oxblood, butcher paper, bone-handle knives

## Voice

pre-1950 food store: warm, direct, no exclamation marks.

Write this voice into the `// === BEGIN wc microcopy ===` block in `butcher/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- full-bleed hero photograph with short overlaid tagline
- product category cards immediately below

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#4a1a1f` |
| `accent-soft` | `#d2c6c7` |
| `base` | `#ffffff` |
| `border` | `#bfbfbf` |
| `contrast` | `#1f1b16` |
| `muted` | `#ffffff` |
| `primary` | `#1f1b16` |
| `primary-hover` | `#4c4945` |
| `secondary` | `#191612` |
| `subtle` | `#ffffff` |
| `surface` | `#ffffff` |
| `tertiary` | `#13100d` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `butcher/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Caslon Antique` (display, weights 400, 700)
- `Inter` (sans, weights 400, 600)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `butcher/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py butcher`.
6. Snap baseline: `python3 bin/snap.py shoot butcher && \
   python3 bin/snap.py baseline butcher`.
7. Verify: `python3 bin/check.py butcher --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for butcher by `bin/design.py`._
