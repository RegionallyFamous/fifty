# azulejo — design intent

This file is the canonical design rubric for the **azulejo** theme. It is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and concatenated into the prompt for screenshot review.

## Voice

Iberian heritage-craft. A third-generation tile atelier in Lisbon — reverent, deliberate, steeped in centuries of ceramic practice. Copy is measured and long-sentenced, hand-lettered in feeling, unafraid of Portuguese loanwords used sparingly (`oficina`, `artesão`, `azulejaria`, `feito à mão`). Dates and batches read like museum placards ("oficina no. III, 2026"); every piece notes the hand that painted it.

Distinctness: basalt speaks present-tense honesty about stone and mineral; azulejo speaks centuries-tense reverence about glaze, cobalt oxide, and the stencil a grandmother cut in 1962. Obel is quiet editorial contemporary; azulejo is quiet editorial historical. Selvedge is Japanese workwear craft; azulejo is Iberian ceramic craft.

## Palette

Cobalt blue on cream tin glaze with a gold ochre secondary — the signature azulejaria combination. Warm and slightly sun-bleached, never high-contrast cold.

- `base` `#fef3c7` — cream tin-glaze page background
- `surface` `#fdf8e1` — slightly paler card surface
- `muted` `#ede0b0` — soft ochre zones and pattern fills
- `border` `#d9c77e` — gold-ochre hairline dividers
- `contrast` `#1e2d5c` — deep cobalt ink for body
- `primary` `#1e40af` — cobalt, the signature colour
- `accent` `#ca8a04` — gold ochre, for placards and small accents
- `tertiary` `#6b6649` — warm secondary text

**Forbidden uses**:
- Cool greys / true black — collides with the sun-warmed palette
- Drop shadows — glaze reflects light; it does not drop it
- Pure white — reads as printer paper, not tin glaze
- More than one accent per viewport
- Neon or saturated non-heritage colours (lime, hot pink, electric purple)

## Typography

- `display` — Cormorant Garamond: hero, section openers, product titles. Thin weight, generous letter-spacing; reads like a placard.
- `serif` — Cormorant Garamond: long-form body, journal entries, firing log prose.
- `sans` — Lora (treated as editorial secondary): UI labels, form inputs, microcopy that must stay compact.
- `mono` — used only for SKU, order number, provenance codes.

**Forbidden**:
- Brush / handwritten display faces — the atelier signs in a controlled hand, not a casual scrawl
- Condensed / compressed type — glaze needs breathing room around each letter
- All-caps body copy
- Tight (<0) letter-spacing on display
- Bold weight on body copy (use italic Cormorant for emphasis)
- Sans-serif on heroes or section openers

## Required patterns per route

- `home`: two-column hero with a large tile-mosaic image and a centred serif headline + tagline. Decorative tile-pattern frame around the entire page.
- `shop`: product cards that showcase individual tile patterns; tile-grid feel; cobalt-on-cream hierarchy.
- `product-simple` / `product-variable`: serif product title, provenance paragraph ("painted in oficina no. III, 2026"), firing log in a `core/details`.
- `cart-empty`: heritage-craft empty state ("Nothing set aside yet") with an ochre pill CTA back to the oficina.
- `checkout-filled`: inputs with cream fills and cobalt-ink labels; fit at desktop 1280 without overflow.
- `journal-post`: editorial long-form Cormorant; fuller leading than product pages.

## Forbidden patterns (globally)

- Walls of unstyled paragraphs
- Headings consuming more than ~55% of the viewport height (hero excepted below)
- Empty regions taking >30% of the viewport with no content
- More than one `<h1>` per page
- Buttons styled as plain links
- Placeholder / cartoon photography on the front page or hero
- "Chonk-style" hard black borders anywhere
- Modern startup phrasing ("get yours now", "while supplies last", "limited drop")

## Mockup

`docs/mockups/azulejo.png` — two-column hero with a 4×4 tile mosaic on the left and a centred Cormorant Garamond headline + tagline on the right, the full page framed by a repeating cobalt-on-cream tile border.

## Allowed exceptions (calibrated 2026-04-27)

These document deliberate decisions in the shipped azulejo theme that override the generic rules above.

- **Hero serif headings on `home` may consume up to 55% of viewport height** at desktop and mobile. The hero is a brand placard and is allowed to breathe.
- **Portuguese loanwords** (`oficina`, `atelier`, `azulejaria`, `feito à mão`, `olá`) are allowed in both display and body copy — they are the voice, not ornament.
- **Decorative tile-pattern frames** (repeating cobalt geometry at top and bottom of the page, or full border) are required on the front page and allowed everywhere else. This is the only ornament azulejo accepts.
- **Ochre hairlines** (1px `#d9c77e`) are preferred over grey dividers; treat them as part of the typographic system rather than decoration.
