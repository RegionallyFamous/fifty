# Ferment Co — design brief

This file was emitted by `bin/design.py` after cloning `obel` -> `ferment-co` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Crocks, cultures, and pantry fermentation.

## Voice

home cook with a crock: patient, recipe-grounded; cart is Pantry; sort by ferment type; sold-out reads as out of culture until Friday refresh; live cultures ship Mon-Wed

Write this voice into the `// === BEGIN wc microcopy ===` block in `ferment-co/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- From vibes/Concepts/47-ferment-co.yaml: rustic homestead, warm parchment base, two-column rhythm
- Hero: current featured ferment with recipe link; five category tiles: crocks, cultures, salt, tools, books, subscribe
- Footer: cultures-of-the-month signup persists; cart voice Pantry; checkout note for live cultures Mon-Wed

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#a85c2c` |
| `accent-soft` | `#e5c9a8` |
| `base` | `#f2ebd2` |
| `border` | `#5c2a14` |
| `contrast` | `#3a1f0e` |
| `muted` | `#c4b08a` |
| `primary` | `#3a1f0e` |
| `primary-hover` | `#5c2a14` |
| `secondary` | `#4d3018` |
| `subtle` | `#d9c8a4` |
| `surface` | `#fffaec` |
| `tertiary` | `#6b4a32` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `ferment-co/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `EB Garamond` (display, weights 600, 700)
- `Lora` (sans, weights 400, 500)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `ferment-co/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py ferment-co`.
6. Snap baseline: `python3 bin/snap.py shoot ferment-co && \
   python3 bin/snap.py baseline ferment-co`.
7. Verify: `python3 bin/check.py ferment-co --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for ferment-co by `bin/design.py`._
