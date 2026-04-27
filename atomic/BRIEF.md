# Atomic — design brief

This file was emitted by `bin/design.py` after cloning `foundry` -> `atomic` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Mid-century modern gifts for the space-age collector

## Voice

Playful yet sophisticated, celebrating atomic-age optimism with a wink to vintage futurism.

Write this voice into the `// === BEGIN wc microcopy ===` block in `atomic/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- centered hero with large geometric illustration
- hand-drawn atomic-age iconography (starburst, rocket, boomerang)
- bold display headline with tagline beneath
- product grid with rounded corners and image cards
- warm cream background with teal and mustard accents
- vintage-inspired badge-style CTA buttons

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#d4a558` |
| `accent-soft` | `#e8d4b0` |
| `base` | `#f5f1e8` |
| `border` | `#b8b3a7` |
| `contrast` | `#1a1a1a` |
| `muted` | `#d4cfc3` |
| `primary` | `#5a8f8f` |
| `primary-hover` | `#487070` |
| `secondary` | `#3a3a3a` |
| `subtle` | `#ebe7dd` |
| `surface` | `#fefdfb` |
| `tertiary` | `#8a8575` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**System-stack font slots** (no asset work needed):

- `display`: Futura
- `sans`: Futura

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `atomic/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py atomic`.
6. Snap baseline: `python3 bin/snap.py shoot atomic && \
   python3 bin/snap.py baseline atomic`.
7. Verify: `python3 bin/check.py atomic --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for atomic by `bin/design.py`._
