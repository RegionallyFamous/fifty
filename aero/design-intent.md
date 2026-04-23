# aero — design intent

This file is the canonical design rubric for the **aero** theme. It is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and concatenated into the prompt for screenshot review.

## Voice

Bright, soft, modern-pastel. Aero pushes the variant family toward "light and breezy" — pastel lilac/lavender base, soft pink mid-tones, deep purple accents. Reads young, optimistic, tactile. Not "candy-pastel" — closer to interior-design pastels with body to them.

## Palette

Pastel base. Cool-warm — mostly cool lavender with warm pink accents.

- `base` `#F5EEFF` — soft lilac page background
- `surface` `#FFFFFF` — clean white cards on the lilac
- `subtle` `#FFEEF7` — pale-pink zone separation
- `muted` `#E5DCFF` — slightly deeper lavender for muted regions
- `border` `#D4C4F2` — soft lavender dividers
- `tertiary` `#6B5FA8` — deep purple secondary text
- `contrast` — deep purple ink (NOT black)
- `accent` — saturated purple for CTA + selection state ONLY

**Forbidden uses**:
- Pure black anywhere — fights the soft palette and creates harsh edges
- Cool industrial grays — clash with the lilac warmth
- Drop-shadows on anything except active form states
- Hard 2px+ black borders (Chonk's signature; wrong for aero)
- Off-palette colors — saturated reds, oranges, true blues all break the brand

## Typography

- `display` — used at hero scale; light-to-medium weight (NOT black/heavy — the palette is soft, the type should match)
- `sans` — body and UI
- `serif` — only for journal long-form
- `mono` — SKU / order number / debug-style metadata

**Forbidden**:
- Heavy/black display weights (they fight the soft palette)
- Body copy at greater than 1.4× base size
- All-caps body copy
- Outlined/stroked text
- High-contrast pure-black text on white (use the deep-purple contrast preset instead)

## Required patterns per route

- `home`: hero on the soft-lilac background; CTA in saturated purple, clearly readable
- `shop`: product cards on white surfaces against lilac base — surface/base contrast must be visible (avoid white card on near-white background)
- `product-simple` / `product-variable`: gallery, price, add-to-cart all visible at desktop:1280
- `cart-empty`: friendly empty-state copy in the brand's voice
- `checkout-filled`: form fields visible at desktop:1280; lavender input borders, deep-purple labels readable on white surface

## Forbidden patterns (globally)

- Walls of unstyled paragraphs
- Headings consuming more than ~40% of the viewport height
- Empty regions taking >25% of the viewport with no content or background distinction
- More than one `<h1>` per page
- Buttons styled as plain links — CTAs need visual weight
- Photography that introduces colors outside the palette family (e.g. orange/red product shots) — picks should be pastel-friendly
- "Quiet" cool gray UI chrome — the chrome should pick up the lilac/lavender warmth

## Mockup

None.

## Allowed exceptions (calibrated 2026-04-23)

These are deliberate decisions in the shipped theme that override the
generic rules above. The vision reviewer should treat them as intent,
not regressions.

- **Hero headings on `home` / `shop` may consume up to 55% of viewport
  height** at the desktop and mobile breakpoints. The "40% viewport" rule
  applies elsewhere; the hero is the brand-statement surface and gets
  more room.
- **Hero display type may use medium-bold weight** (not just light/medium).
  The "no heavy/black weights" rule still applies to non-hero copy.
- **Top utility banner uses deep purple (`tertiary`) on the lavender
  base.** Contrast is intentional; the banner is a chrome surface, not
  body copy, so the standard contrast preset doesn't apply.
- **Pure black is acceptable as a single-pixel border / focus outline**
  where the deep purple would read as a hover-state ambiguity.
  Everywhere else, deep purple is the contrast color.
- **Sale badges and accent buttons may use the saturated purple accent
  with white type** even when this differs from the surrounding pastel
  palette -- the accent is supposed to pop.
