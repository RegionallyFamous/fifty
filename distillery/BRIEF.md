# Distillery — design brief

This file was emitted by `bin/design.py` after cloning `obel` -> `distillery` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Small-batch spirits, hand-labelled bottles, copper still.

## Voice

A small-batch distillery with a long history and longer patience. Copy feels like handwritten cellar notes and copper-plate labels — precise, unhurried, proud of craft. Quantities are 'casks' and 'batches', orders are 'reservations', the cart is 'your selection'. Nothing is rushed; everything is considered. Tone sits between a Victorian apothecary and a serious whisky bar: authoritative but not stuffy, warm but never folksy.

Write this voice into the `// === BEGIN wc microcopy ===` block in `distillery/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- full-bleed amber bottle photography hero with overlay label text
- copper-still product-feature section below hero
- product grid labelled like a tasting menu — vintage year + batch number
- editorial journal section for distillery notes and process writing

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#b8741a` |
| `base` | `#f4edd8` |
| `border` | `#c9b98a` |
| `contrast` | `#120a00` |
| `muted` | `#d9ccaa` |
| `primary` | `#7b3d1e` |
| `secondary` | `#5c4a30` |
| `surface` | `#ede0c4` |
| `tertiary` | `#8c8272` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `distillery/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Crimson Pro` (serif, weights 400, 600)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

**System-stack font slots** (no asset work needed):

- `display`: Roslindale

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `distillery/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py distillery`.
6. Snap baseline: `python3 bin/snap.py shoot distillery && \
   python3 bin/snap.py baseline distillery`.
7. Verify: `python3 bin/check.py distillery --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for distillery by `bin/design.py`._
