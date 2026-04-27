# apiary — design intent

This file is the canonical design rubric for the **apiary** theme. It
is read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py)
and concatenated into the prompt for screenshot review.

## Voice

Small-batch-honey-artisan crossed with warm-indie-grocery. The shop
reads like a farmer's market stall run by an excellent beekeeper who
writes their own labels by hand: warm, direct, unhurried, no
exclamation marks. Respects the ingredient — no "delicious",
"yummy", or any other over-stated food-copy tic. Reaches for hive /
colony / harvest / honey / comb / queen / forage / pantry / jar /
batch vocabulary; references batch numbers and harvest dates where
a date fits.

## Palette

Butter-yellow and cream on warm oat-paper. Lower contrast than
chonk; the look is *warm and patient*, not loud.

- `base` `#F5EFE6` — oat-paper page background
- `surface` `#FFFFFF` — jar-label card front
- `subtle` `#F9F5F0` — gentle zone separation
- `muted` `#FCFAF8` — softest wash
- `border` `#B8B3AC` — warm-grey hairline dividers
- `tertiary` `#13100D` — near-black ink for eyebrows
- `secondary` `#191612` — body-copy ink
- `contrast` `#1F1B16` — display ink (never pure black)
- `accent` `#F0D88A` — butter-yellow harvest accent
- `accent-soft` `#F8EDCA` — honeycomb-wash hero background

**Forbidden uses**:
- Pure black (`#000`) anywhere — kills the honey-on-cream cast
- Cool greys — clash with the butter-yellow palette
- Drop-shadows on product cards
- Saturated colour accents (cyan, magenta, electric blue)
- Red or green warning pills — the only loud colour is the butter
  accent
- Multiple competing accents on the same viewport

## Typography

- `display` (Recoleta) — wordmark, section headlines, hero; soft
  humanist serif that carries the brand voice
- `sans` (Public Sans) — UI text, price, button labels, form inputs
- `mono` — SKU, batch number, order receipts only

**Forbidden**:
- Sans headings in hero / section openers (the serif IS the brand)
- Body copy above 1.4× base
- All-caps body paragraphs
- Outlined or stroked text
- Bold weight on running body copy (use italic for emphasis)
- Tight letter-spacing on display headings — apiary display wants
  air, not crowding

## Imagery

- Soft-focus editorial still life; jars photographed in warm
  backlight against chalk / oat / linen backdrops
- Hand-drawn bee / honeycomb / wildflower / cross-section-hive
  illustrations as decorative accents
- Every jar in the catalogue has its own photograph — no WC
  placeholder, no reused cartoons
- Butter-yellow wax seals, cloth twine, parchment labels

## Required patterns per route

- `home`: serif wordmark hero on honeycomb / cream wash, generous
  whitespace, single CTA ("Shop the harvest"); 3-up product grid
  below; batch-log provenance section with 2×2 specimen card
- `shop`: product cards on oat background; consistent card height;
  clear price + butter-coloured sale dot
- `product-simple` / `product-variable`: serif product title, ample
  whitespace around imagery, sans-serif tasting-note metadata
- `cart-empty`: branded "pantry is bare" empty state with two CTAs
- `checkout-filled`: form fields visible at desktop:1280, no
  horizontal overflow, hexagon required-field marker
- `journal-post`: editorial serif long-form, distinct from product
  pages

## Forbidden patterns (globally)

- Walls of unstyled paragraphs
- Headings occupying more than ~35% of the viewport on non-hero
  routes (the hero is allowed to breathe)
- Empty regions > 30% of viewport with no content (usually a broken
  layout)
- More than one `<h1>` per page
- Buttons styled as plain links
- Placeholder photography (uniform grey, broken-image icon,
  unedited stock cartoons from the seeder upgrade pass)
- Heavy black chonk borders — apiary borders are thin and warm

## Mockup

`docs/mockups/apiary.png` — the two-view hero with centered wordmark,
butter-yellow background, hand-drawn bee anatomy, and a 4-up jar
shelf (the shipped front page renders 3-up for rhythm with the
batch-log section below).

## Allowed exceptions

- **Hero serif heading on `home` may consume up to 50% of viewport
  height** at desktop and mobile. Hero is the brand-statement
  surface.
- **All-caps serif eyebrow** ("BATCH 04 · SPRING HARVEST") is
  allowed where it reads as label rather than body.
- **Shop / category section heading at ~1.5× base size** is fine;
  these pages don't ship a hero so the section opener carries
  weight.
- **Butter-yellow accent backgrounds** are allowed on up to two
  sections per front page (hero + one feature) provided the
  accent-soft token is used, not the full accent.
