# Stellar Sextant — design brief

This file was emitted by `bin/design.py` after cloning `obel` -> `stellar-sextant` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Celestial navigation, harbor charts, and brass you can trust at sea.

## Voice

Measured hydrographic-office tone: call orders a 'ledger', the cart a 'manifest', checkout 'close the manifest', password link 'recover your ledger key', sort menu 'order of bearing', result counts 'entries sighted', totals ' reckonings', proceed button 'sign the manifest and sail on'. Use '·' as the required-field marker. No exclamation marks in customer-facing UI.

Write this voice into the `// === BEGIN wc microcopy ===` block in `stellar-sextant/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- night-sky hero with a single brass instrument still-life and one chart texture
- narrow editorial column for shop story above a wide product rail
- footer with three columns: voyages (journal), instruments (categories), signals (social)

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#d4a437` |
| `accent-soft` | `#2a2412` |
| `base` | `#0a1020` |
| `border` | `#5a6d8f` |
| `contrast` | `#f6f1e8` |
| `error` | `#c44c4c` |
| `info` | `#4a7dbd` |
| `muted` | `#3d4f6f` |
| `primary` | `#f6f1e8` |
| `primary-hover` | `#dcd6c8` |
| `secondary` | `#c5d0e3` |
| `subtle` | `#1a2438` |
| `success` | `#3d8b6a` |
| `surface` | `#121a2e` |
| `tertiary` | `#8fa3c2` |
| `warning` | `#c98a2e` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `stellar-sextant/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Libre Baskerville` (display, weights 400, 700)
- `Source Sans 3` (sans, weights 400, 600)

Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm no remote URLs slipped in.

## Next steps

1. Open `theme.json` and confirm the palette / font slots match your intent.
2. Drop product photographs as `stellar-sextant/playground/images/product-wo-*.jpg` 
   (one per product). Generate them so they read as this theme's voice;
   `bin/check.py check_product_images_unique_across_themes` will reject any
   byte-shared with a sibling theme.
3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match
   the voice above.
4. Restructure `templates/front-page.html` per the layout hints; every theme's
   homepage must be structurally distinct (`check_front_page_unique_layout`).
5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py stellar-sextant`.
6. Snap baseline: `python3 bin/snap.py shoot stellar-sextant && \
   python3 bin/snap.py baseline stellar-sextant`.
7. Verify: `python3 bin/check.py stellar-sextant --quick` — fix every failure before
   committing. Don't suppress with `--no-verify`.
8. Commit + push everything (theme dir, blueprint, content, baselines).

`BRIEF.md` is committed alongside the theme so future agents (and the next
human reading the repo a year from now) can see the design intent that
seeded the theme without spelunking the original prompt.

_Brief auto-generated for stellar-sextant by `bin/design.py`._
