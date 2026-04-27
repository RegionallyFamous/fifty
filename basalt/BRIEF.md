# Basalt — design brief

This file was emitted by `bin/design.py` after cloning `foundry` -> `basalt` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Mineral-grey ceramics with understated warmth

## Voice

Direct and unadorned, letting craft speak through restraint and material honesty.

Write this voice into the `// === BEGIN wc microcopy ===` block in `basalt/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- ASCII art hero with stark geometric letterforms
- Monospaced tagline beneath hero art
- Grid catalog layout with minimal product cards
- Black and white product photography
- Terminal-style product metadata display
- Text-file naming convention (.txt extensions)
- Brutalist navigation with bracketed labels
- High contrast typography on white

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#a0826d` |
| `accent-soft` | `#d4c4b8` |
| `base` | `#ffffff` |
| `border` | `#d1d1d1` |
| `contrast` | `#000000` |
| `muted` | `#9e9e9e` |
| `primary` | `#1a1a1a` |
| `primary-hover` | `#2e2e2e` |
| `secondary` | `#3d3d3d` |
| `subtle` | `#e8e8e8` |
| `surface` | `#f5f5f5` |
| `tertiary` | `#6b6b6b` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**System-stack font slots** (no asset work needed):

- `display`: Söhne
- `sans`: Söhne

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `basalt/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py basalt`.
6. Snap baseline: `python3 bin/snap.py shoot basalt && \
   python3 bin/snap.py baseline basalt`.
7. Verify: `python3 bin/check.py basalt --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for basalt by `bin/design.py`._
