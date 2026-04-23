# selvedge — design intent

This file is the canonical design rubric for the **selvedge** theme. It is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and concatenated into the prompt for screenshot review.

## Voice

Dark, considered, hand-finished. Selvedge denim aesthetic — durable, slightly raw, lived-in. Editorial heft over decoration; think a small-batch shop with a serious workshop behind it.

## Palette

DARK theme. Background is near-black, foreground is warm tan/cream.

- `base` `#160F08` — page background (essentially black, slight warm cast)
- `surface` `#1F1610` — cards, raised surfaces
- `subtle` / `muted` `#2C2016` — gentle separation between zones
- `border` `#7A6248` — warm tan dividers
- `tertiary` `#A89068` — secondary text, eyebrow labels
- `contrast` — warm cream body text
- `accent` — CTA + selection state ONLY (warm rust/copper tone)

**Forbidden uses**:
- Pure white (`#FFFFFF`) backgrounds — kills the dark mood and feels like an unstyled fallback
- Cool grays (anything truly neutral) — the warm cast is part of the brand
- Drop-shadows of any kind (dark theme makes them invisible or weird)
- Gradients
- Bright/saturated accent colors outside the warm-rust/copper family

## Typography

- `display` (Caveat Brush + Archivo Black per current build) — hero/section openers ONLY
- `sans` (Inter or similar) — body, UI, forms
- `serif` — pull quotes, journal long-form
- `mono` — SKU / order number ONLY

**Forbidden**:
- Brush-script display font on body copy (becomes illegible against the dark background)
- Body copy at greater than 1.5× base size
- All-caps body copy
- Outlined or stroked text (already a high-contrast theme; outlines double the visual noise)
- Light-weight body text (under 400) — too thin against dark backgrounds

## Required patterns per route

- `home`: hero with visible "shop" CTA above the fold; warm-rust accent should be the brightest thing on screen
- `shop`: product cards readable against dark background; image areas should not blend into surface color
- `product-simple` / `product-variable`: gallery, price, add-to-cart all visible at desktop:1280 without scrolling
- `cart-empty`: friendly empty-state with the brand's voice ("Nothing in the bag yet."); not raw WC defaults
- `checkout-filled`: form fields visible at desktop:1280, no horizontal overflow, label/input contrast must be readable on dark surface
- `journal-post`: comment list visible with separators between commenters (this is selvedge's "show off the typography" route)

## Forbidden patterns (globally)

- Walls of unstyled paragraphs (CSS didn't load against dark background)
- Headings consuming more than ~40% of the viewport height
- Empty regions taking >25% of the viewport with no media, content, or background distinction
- More than one `<h1>` per page
- Buttons styled as plain underlined text — CTAs must be visually distinct given the dark theme
- Form inputs with insufficient contrast (label or value text barely readable on dark surface — common with WC defaults bleeding through)
- Photography on a uniform gray placeholder background — clashes badly with the warm dark palette

## Mockup

None.
