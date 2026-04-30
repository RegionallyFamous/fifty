# xerox — design intent

This file is the canonical design rubric for the **xerox** theme. It is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and concatenated into the prompt for screenshot review.

## Voice

Loud, blocky, confident. Heavy weights, hard borders, big type. Reads like a screen-printed zine in product form — uses "ugly on purpose" punk-zine language without becoming actually ugly.

## Palette

Warm cream with HARD black borders. Black is structural here, not decorative.

- `base` `#F5F1E8` — warm cream page background
- `surface` `#FFFFFF` — content card background
- `subtle` `#EDE7D6` — minor zone separation
- `border` `#000000` — true black, used heavily for hard outlines and dividers
- `tertiary` `#5C5A52` — secondary text
- `contrast` — near-black ink
- `accent` — saturated single hot color (the xerox "scream" color)

**Forbidden uses**:
- Soft borders (color only) — xerox uses 2px+ hard black borders by default; "subtle border" defeats the brand
- Drop-shadows replacing borders (xerox uses HARD edges, not soft depth)
- Gradients
- Pastels of the accent (the accent is loud or it's not there)
- Off-palette colors (more than one accent on screen at once)

## Typography

- `display` — heavy/black weight, used at LARGE sizes for hero and section openers (this is the xerox signature)
- `sans` — body and UI
- `mono` — eyebrow labels, metadata, ALL-CAPS small captions are OK here (this is the one theme where all-caps small text fits the voice)
- `serif` — long-form journal copy

**Forbidden**:
- Display weight set in light/regular (defeats the xerox voice)
- Heading sizes < 2× base in heroes (xerox hero typography is loud or it's broken)
- Stroke/outline text without a solid version present
- Letter-spacing < 0 on display copy (already heavy; tight tracking turns into mush)

## Required patterns per route

- `home`: hero must read LOUD — large display type, visible CTA, accent color used at least once
- `shop`: product card with visible black border; image area on white surface; price prominent
- `product-simple`: add-to-cart button must be visually dominant, accent-colored
- `cart-empty`: friendly empty-state copy, not WC defaults
- `checkout-filled`: form fields visible at desktop:1280, hard borders on inputs

## Forbidden patterns (globally)

- "Quiet" sections — xerox doesn't have quiet space, it has loud space and louder space
- Headings smaller than the body text in the same region (hierarchy must be obvious at a glance)
- Empty regions taking >25% of the viewport with no media, content, or border treatment
- More than one `<h1>` per page
- More than one accent color region per viewport (xerox picks one loud color per screen)
- Walls of unstyled paragraphs

## Mockup

`mockups/mockup-xerox.png` — concept mockup used as the visual reference for automated layout selection, token tuning, and mockup-divergence review.

## Allowed exceptions (calibrated 2026-04-23)

These document deliberate decisions in the shipped xerox theme that
override the generic rules above. The vision reviewer should treat them
as intent, not regressions.

- **WooCommerce default product cards (no hard border)** are acceptable
  on `shop`, `category`, and "featured products" blocks. The hard-black
  border rule applies to xerox's *own* card and zone treatments
  (featured-product banners, callout sections), not to every WC block.
- **Coloured zone backgrounds (warm yellow `#F2D44A`, pink `#FFB7C5`,
  warm cream `#F5F1E8`) may appear simultaneously on a single viewport**
  when each is structurally separate (hero strip + featured-product
  card + footer). The "one accent color region per viewport" rule
  applies to overlapping or adjacent same-colour blocks, not to vertical
  page sections.
- **`SHOP` page heading at ~1.6× base size is acceptable** when it is a
  utility section header rather than a hero. The "loud or broken" hero
  rule applies to home and product detail heroes, not category index
  page titles.
- **Sale badges may use the warm yellow accent on white surfaces
  without a hard black border** because the saturated yellow on white
  already creates sufficient edge contrast.
