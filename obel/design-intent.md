# obel — design intent

This file is the canonical design rubric for the **obel** theme. It is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and concatenated into the prompt that asks Claude to review every screenshot. Anything stated here becomes a thing the reviewer will flag when violated.

## Voice

Quiet, considered, editorial. The "default" reference theme that every other variant clones from. Reads like a thoughtful indie shop — not minimalist for its own sake, but unhurried.

## Palette

Neutral, paper-toned. Every value is a near-neutral; saturated color appears only at the accent.

- `base` `#FAFAF7` — page background
- `surface` `#FFFFFF` — cards, panels
- `subtle` `#F2F1EC` — gentle dividers
- `contrast` (ink) — body text
- `accent` — CTAs and selection state ONLY

**Forbidden uses**:
- Accent applied to decorative elements (borders, dividers, icon fills) — accent is reserved for "this is the action"
- Hard black (`#000`) anywhere except SVG strokes; use the contrast preset
- Drop-shadows on anything except active form states
- Gradients
- Off-palette colors anywhere

## Typography

- `display` (font-family preset) — section openers + hero only
- `serif` — long-form body in journal, product description
- `sans` — UI surface text (price, button label, form input)
- `mono` — only for SKU / order number / debug-style metadata

**Forbidden**:
- Display font on body copy (turns the page into noise)
- Body copy at greater than 1.4× base size — long lines should never feel oversized
- All-caps body copy
- Outlined or stroked text
- Letter-spacing > 0.05em on body text

## Required patterns per route

- `home`: hero with a clear primary CTA visible above the fold at desktop:1280
- `shop`: product grid with consistent card heights; no orphan card on a row by itself
- `product-simple` / `product-variable`: gallery + price + add-to-cart all visible in the desktop:1280 viewport without scrolling
- `cart-empty`: friendly empty-state copy, NOT raw WC defaults ("Your cart is currently empty.")
- `cart-filled`: line items visible without scroll at desktop:1280
- `checkout-filled`: form fields visible at desktop:1280, no horizontal overflow
- `journal`: editorial typography distinct from product pages
- `journal-post`: comment template renders with separators between commenters

## Forbidden patterns (globally)

- Walls of unstyled paragraphs (signal that CSS didn't load or a block didn't render)
- Headings consuming more than ~40% of the viewport height
- Empty regions taking >25% of the viewport with no media, content, or background distinction (the "lysholm void" bug class)
- More than one `<h1>` per page
- Buttons styled as plain links (CTA must read AS a button)
- Photography that is clearly a placeholder (uniform gray, "image" text, broken-image icon)

## Mockup

None. Obel is the canonical reference itself.
