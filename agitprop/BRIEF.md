# Agitprop — design brief

This file was emitted by `bin/design.py` after cloning `chonk` -> `agitprop` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> scarlet + black, slabs of geometric type, diagonal blocks

## Voice

pre-1950 art-print store: warm, direct, no exclamation marks.

Write this voice into the `// === BEGIN wc microcopy ===` block in `agitprop/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- oversized display wordmark anchored to the top-left
- thin rule beneath the hero
- three-up product grid below the hero

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#c8281a` |
| `accent-soft` | `#ecb4af` |
| `base` | `#f5efe6` |
| `border` | `#b8b3ac` |
| `contrast` | `#0a0a0a` |
| `muted` | `#fcfaf8` |
| `primary` | `#0a0a0a` |
| `primary-hover` | `#3b3b3b` |
| `secondary` | `#080808` |
| `subtle` | `#f9f5f0` |
| `surface` | `#ffffff` |
| `tertiary` | `#060606` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `agitprop/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Rodchenko` (display, weights 400, 700)
- `Roboto Condensed` (sans, weights 400, 600)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `agitprop/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py agitprop`.
6. Snap baseline: `python3 bin/snap.py shoot agitprop && \
   python3 bin/snap.py baseline agitprop`.
7. Verify: `python3 bin/check.py agitprop --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for agitprop by `bin/design.py`._
