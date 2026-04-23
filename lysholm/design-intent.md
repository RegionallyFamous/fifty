# lysholm — design intent

This file is the canonical design rubric for the **lysholm** theme. It is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and concatenated into the prompt for screenshot review.

## Voice

Refined, classical, restrained. Lysholm aquavit — heritage, stillness, precision. The most "luxurious" of the variants; relies on whitespace and typographic detail rather than ornament.

## Palette

Warm cream + warm tan + restrained warm-brown ink. Lower contrast than obel; the look is *quiet*, not high-contrast.

- `base` `#F7F5F1` — warm cream page background
- `surface` `#FCFAF6` — slightly lighter cards
- `subtle` `#EFEAE2` — gentle zone separation
- `muted` `#E3D9C8` — warm tan zones
- `border` `#D6CFC2` — soft tan dividers
- `tertiary` `#605C56` — warm gray secondary text
- `contrast` — warm-toned ink (NOT black)
- `accent` — single restrained warm tone, used SPARINGLY

**Forbidden uses**:
- Pure black anywhere — kills the warm cast
- Cool grays — clashes with the warm palette
- Drop-shadows
- Gradients
- Heavy borders (lysholm uses thin, soft borders or no borders)
- Multiple accents on the same viewport

## Typography

- `serif` — heroes, section openers, journal long-form (this is the lysholm signature; serif is the brand voice)
- `sans` — UI surface text only (price, button label, form input)
- `display` — restrained use; if it's there, it's serif-like or italic, never brush
- `mono` — only for SKU / order number / debug-style metadata

**Forbidden**:
- Sans-serif headings in hero/section openers (defeats the lysholm voice)
- Body copy at greater than 1.4× base size
- All-caps body copy
- Outlined or stroked text
- Tight letter-spacing on display (lysholm wants air around its letters)
- Bold weight on body copy (use serif italics for emphasis instead)

## Required patterns per route

- `home`: serif hero, generous whitespace above and below; CTA visible but understated
- `shop`: product cards on warm-cream surface; consistent card heights; restrained type
- `product-simple` / `product-variable`: serif product title, ample whitespace around imagery, sans-serif metadata
- `cart-empty`: friendly empty-state copy in the brand's voice; serif heading, sans body
- `checkout-filled`: form fields visible at desktop:1280, no horizontal overflow, restrained label/input styling
- `journal-post`: editorial typography distinct from product pages; long-form serif body

## Forbidden patterns (globally)

- Walls of unstyled paragraphs
- Headings consuming more than ~35% of the viewport height (lysholm prefers smaller, more refined display)
- Empty regions taking >30% of the viewport with no content (lysholm SHOULD have generous whitespace, but a >30% void usually signals broken layout)
- More than one `<h1>` per page
- Buttons styled as plain links
- Placeholder photography (uniform gray, broken-image icon)
- Heavy "Chonk-style" hard black borders anywhere

## Mockup

None.
