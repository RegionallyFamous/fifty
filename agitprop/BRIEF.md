# Agitprop — design brief

This file was emitted by `bin/design.py` after cloning `obel` -> `agitprop` and applying the spec's palette + font choices. Read it before you do anything else; it captures the design intent the spec encoded so you can write the per-theme microcopy block, restyle the templates that need it, and brief any product photography in the same voice.

## Tagline

> Soviet constructivist storefront: scarlet and black editions, diagonal blocks, type as weapon.

## Voice

urgent constructivist print shop: clipped campaign language, edition numbers, workshop dispatches, red-label CTAs, no softness or lifestyle phrasing.

Write this voice into the `// === BEGIN wc microcopy ===` block in `agitprop/functions.php`. Every theme's microcopy must read distinctly from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` enforces it. Crib the structure from any sibling theme's microcopy block, then rewrite every literal string in this voice.

## Layout hints

- type-led hero with enormous condensed slogan and red CTA slab
- constructivist diagonal red and black blocks behind featured product art
- shop grid as edition posters in rigid framed tiles
- hard black borders, scarlet labels, asymmetric columns, no rounded corners
- footer should feel like a print colophon, not a lifestyle brand footer

These hints came from the spec. Restructure `templates/front-page.html` and any sibling templates whose composition needs to change. Token swaps alone are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6.

## Palette applied

| Slug | Hex |
|------|-----|
| `accent` | `#be2428` |
| `base` | `#e7dcc2` |
| `border` | `#110e07` |
| `contrast` | `#110e07` |
| `muted` | `#726c5e` |
| `primary` | `#be2428` |
| `secondary` | `#726c5e` |
| `surface` | `#f1e8cc` |
| `tertiary` | `#aea894` |

Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking the palette. Verify every pairing in the WCAG table at `.claude/skills/build-block-theme-variant/SKILL.md` step 5.

## Fonts registered

**Google Fonts to download as `.woff2`** (the `fontFace` entries already
point at `agitprop/assets/fonts/<slug>-<weight>.woff2` — drop the files there):

- `Bebas Neue` (display, weights 400)
- `Roboto Condensed` (sans, weights 400, 700)

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
