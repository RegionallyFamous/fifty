---
name: build-block-theme-variant
description: Build a complete, opinionated visual variant of an Obel-derived WordPress block theme (Chonk-style flow). Use when the user asks to "make a [style] variant of obel", "create a new theme like obel but [style]", "rebuild this theme as [style]", "restyle to look like [mockup]", or hands over a mockup image and asks to match it. Forces a single upfront question pass, faithful mockup-to-block translation, dynamic content via core blocks, and zero hand-holding.
---

# Build a Block Theme Variant (Obel-style)

The agent's job is to deliver a finished, opinionated, mockup-faithful theme variant in one pass. No incremental "what about the footer?" loops. Front-load the design decisions, respect the base theme's hard rules, then execute end-to-end.

## When to read this skill

Read this **before** running `bin/clone.py` or touching any files, the moment the user says any of:

- "make a [style] variant of obel" / "clone obel as [style]"
- "create a new theme called X with [style]"
- "rebuild [theme] in a [style] style"
- "restyle this to look like [mockup/image]"
- hands over a mockup image and asks to match it

## The non-negotiable workflow

```
 1. PREFLIGHT       → read base theme rules + tooling
 2. PIN INTENT      → mockup + 4-question briefing (one round, batched)
 3. PLAN TOKENS     → full design system on paper before writing code
 4. CLONE           → bin/clone.py
 5. TOKENS FIRST    → theme.json palette, type, spacing, shadow, radius, borders, fontFace
 6. STRUCTURE       → restyle templates/parts to match mockup composition
 7. DYNAMIC         → swap hardcoded content for core/terms-query, core/query, core/navigation, core/site-*
 8. SEED DATA       → ensure menus, pages, categories exist in the DB so dynamic blocks render real content
 9. PLAYGROUND      → bin/seed-playground-content.py + bin/sync-playground.py, then load the new theme's blueprint URL and walk the surface checklist
10. VERIFY          → check.py + screenshots at mobile/tablet/desktop
11. REPORT          → ship a single summary, not a back-and-forth
```

Skipping any step is what causes the "you held my hand too much" failure mode.

**Step 9 is non-optional.** Every theme in this monorepo must ship a working `<theme>/playground/blueprint.json` AND a self-contained per-theme content set under `<theme>/playground/content/` and `<theme>/playground/images/`.

The shared scaffolding (`playground/wo-*.php`) stays theme-agnostic and reads three constants — `WO_THEME_NAME`, `WO_THEME_SLUG`, `WO_CONTENT_BASE_URL` — that `bin/sync-playground.py` prepends to each inlined script body. Per-theme content (CSV catalogue, WXR pages/posts, every product/page/post/category image) lives under that theme's own `playground/content/` and `playground/images/`, with all image URLs inside the CSV/XML pointing at `https://raw.githubusercontent.com/<org>/<repo>/main/<theme>/playground/images/`. Each theme is free to diverge — different products, different copy, different artwork that matches the theme.

The pipeline:

1. `bin/clone.py` copied obel's blueprint and rewrote `obel`→`<new>` / `Obel`→`<New>`. It deliberately did NOT copy obel's `playground/content/` or `playground/images/` (text substitution doesn't touch CSV/XML, so copying would leave you pointing at obel's image URLs).
2. `bin/seed-playground-content.py` populates the new theme's content + assets from the canonical W&O source, rewriting every image URL to point at the new theme's own `images/` folder.
3. `bin/sync-playground.py` auto-discovers every theme via `_lib.iter_themes()`, re-inlines the shared `playground/*.php` helpers (with the per-theme constants prepended), and rewrites the `importWxr` URL to point at the per-theme `content.xml`.
4. Open the deeplink (`https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/<org>/<repo>/main/<theme>/playground/blueprint.json`) and click through front page → shop → single product → cart → checkout → blog post → 404 once. If any pretty URL 404s, the blueprint is broken — see "Playground gotchas" below. If product or page imagery looks like every other theme's, the seed step was skipped.

---

## HARD RULE: modern blocks only — no escape hatches

**Forbidden in any template, part, pattern, or `wp_navigation` post:**

| Block | Why forbidden |
|---|---|
| `core/freeform` (the "Classic" block) | Wraps legacy editor HTML; bypasses the block tree, can't be styled by `theme.json`, defeats Site Editor visual editing |
| `core/html` | Lets raw HTML escape the block system; can't inherit tokens, breaks the design system, lets contributors smuggle in arbitrary CSS/JS |
| `core/shortcode` | Renders an opaque shortcode whose output is invisible to the block style engine; the visual result depends on whatever PHP plugin defined the shortcode |
| Any `[woocommerce_*]` shortcode (`[woocommerce_cart]`, `[woocommerce_checkout]`, `[woocommerce_my_account]`, `[products]`, etc.) | These are the legacy WC path. The modern equivalents are first-class blocks (`woocommerce/cart`, `woocommerce/checkout`, `woocommerce/customer-account-content`, `woocommerce/product-collection`) — use them. |
| Any other shortcode emitted via `core/shortcode` | Same reasons. If a plugin only ships shortcodes, file an issue with the plugin or build a pattern that uses the plugin's actual blocks. |

**Why this rule exists:** the entire premise of this theme is that `theme.json` is the single source of truth for styling. Every one of the blocks above renders content that `theme.json` cannot reach. A single `core/html` block in a template can render a button that ignores every token in your design system.

**The right replacement for each common temptation:**

| If you're tempted to reach for… | Use instead |
|---|---|
| `core/html` to drop in a custom SVG icon | `core/image` with the SVG uploaded to media library, or inline the SVG inside a `core/group` only when truly unavoidable (icons in patterns are the one narrow legitimate case — see "SVG escape" below) |
| `core/html` for a Mailchimp/Klaviyo embed | The plugin's own block (every major email provider ships one); if the plugin literally only ships a shortcode, raise it before adding an exception |
| `core/shortcode` for `[gallery]` | `core/gallery` |
| `core/shortcode` for `[woocommerce_cart]` etc. | The matching `woocommerce/*` block (full mapping below) |
| `core/freeform` because you pasted in old content | Convert it via the editor's "Convert to Blocks" action, or rewrite block-first |
| `core/html` for a CSS hack | `theme.json` `styles.blocks.<name>.css` (used sparingly per the existing escape-hatch rule, capped at 2-3 unfixable cases) |
| `core/html` for an iframe (video, map) | `core/embed` (handles oEmbed for YouTube, Vimeo, Spotify, Twitter, etc.) or the dedicated `core/video` |
| `core/html` for analytics / tracking pixels | `wp_head` / `wp_footer` via `functions.php`, never in a template |

**The `[woocommerce_*]` → `woocommerce/*` block migration map:**

| Legacy shortcode | Modern block |
|---|---|
| `[woocommerce_cart]` | `woocommerce/cart` |
| `[woocommerce_checkout]` | `woocommerce/checkout` |
| `[woocommerce_my_account]` | `woocommerce/customer-account-content` (inside a layout) |
| `[woocommerce_order_tracking]` | `woocommerce/order-confirmation-summary` (or the dedicated tracking block depending on WC version) |
| `[products]` / `[product_category]` / `[recent_products]` / `[featured_products]` / `[sale_products]` / `[best_selling_products]` / `[top_rated_products]` | `woocommerce/product-collection` with the appropriate `query` and collection preset |
| `[product_page]` | `woocommerce/single-product` |
| `[add_to_cart]` / `[add_to_cart_url]` | `woocommerce/add-to-cart-form` (or `add-to-cart-with-options` once the cloned theme tracks WC trunk) |
| `[shop_messages]` | `woocommerce/store-notices` |

**Templates that historically use legacy shortcodes** — verify these were converted during step 6 and contain no shortcode blocks. (Obel-style themes name these `page-cart.html` / `page-checkout.html` because cart/checkout are page slugs; vanilla block themes name them `cart.html` / `checkout.html`. Check both.)

- `templates/page-cart.html` (or `cart.html`) — must use `woocommerce/cart` or `woocommerce/page-content-wrapper {"page":"cart"}`, not `<!-- wp:shortcode -->[woocommerce_cart]`
- `templates/page-checkout.html` (or `checkout.html`) — must use `woocommerce/checkout` or `woocommerce/page-content-wrapper {"page":"checkout"}`
- `templates/page-my-account.html` (or wherever the my-account surface lives) — must use `woocommerce/customer-account-content`
- `templates/order-confirmation.html` — must use `woocommerce/order-confirmation-*` blocks

**Validation grep — run this before declaring done:**

```bash
# Should return ZERO matches across templates/, parts/, patterns/, and wp_navigation posts
grep -rE '<!-- wp:(html|shortcode|freeform)' templates parts patterns 2>/dev/null
grep -rE '\[woocommerce_(cart|checkout|my_account|order_tracking)' templates parts patterns 2>/dev/null
grep -rE '\[(products|product_category|recent_products|featured_products|sale_products|product_page|add_to_cart|shop_messages)' templates parts patterns 2>/dev/null

# Also scan the database for forbidden blocks in stored content (wp_navigation posts, reusable blocks, pages used as templates)
wp post list --post_type=wp_navigation --field=ID | xargs -I{} wp post get {} --field=post_content | grep -E '<!-- wp:(html|shortcode|freeform)'
```

If any of those return a match, fix it before continuing — there is no "we'll address it later" path. The whole no-static, fully-tokenized, every-surface-designed pyramid collapses if a single `core/html` block exists in the tree.

### SVG escape (the one narrow exception)

Inline SVG inside a `core/html` block is sometimes the only way to ship a tiny purely-decorative icon (e.g. a chair silhouette inside a category tile) without adding a media-library round trip for the user. This is acceptable only when:

1. The SVG is decorative (`role="img"` with empty `aria-label`, or `aria-hidden="true"`)
2. It uses `currentColor` for fill so it inherits the parent block's text color (token-aware)
3. It's inside a pattern (`patterns/`), not a template (`templates/`) or part (`parts/`)
4. There is no equivalent dashicon / icon block that would do the job

If all four conditions don't hold, it doesn't qualify for the escape and must be solved differently.

---

## HARD RULE: nothing static

**Any hardcoded list of links, list of products, list of categories, or piece of site data in a template or part is a bug.** The user's CMS is the source of truth, not the template file.

This rule is more important than visual polish. A beautiful theme with hardcoded links is worse than an ugly theme with real menus, because the moment the user adds a page in the admin it stops working.

### What "nothing static" means in practice

| If you're tempted to write… | Use this instead |
|---|---|
| `<ul><li><a href="/about">About</a></li>…</ul>` for a footer column | `core/navigation` block referencing a real `wp_navigation` post |
| `<a href="/shop">Shop</a>` in the header | `core/navigation` with the primary menu ref |
| Hardcoded category tiles ("Curiosities", "Moods", …) | `core/terms-query` + `core/term-template` + `core/term-name` + `core/term-count` |
| Hardcoded product cards | `core/query` with `query.postType:"product"` + `core/post-template` |
| `<h1>My Store</h1>` | `core/site-title` |
| `<p>Beautiful objects since 2020.</p>` as a tagline | `core/site-tagline` |
| `<img src="/logo.png">` | `core/site-logo` |
| `<p>© 2026 Acme Co. All rights reserved.</p>` | `core/site-title` (level:0) inline + a paragraph reading just `© All rights reserved.` (or use the wiki-documented copyright pattern) |
| Breadcrumb trail | `woocommerce/breadcrumbs` (on shop pages) or `core/post-navigation-link` |
| "Latest from the blog" section | `core/query` with `query.postType:"post"` |
| "Featured products" carousel | `core/query` with `query.postType:"product"` and a category filter |
| Search box | `core/search` |
| Cart link in header | `woocommerce/mini-cart` |
| Account link in header | `woocommerce/customer-account` |
| Author bio under a post | `core/post-author-biography` + `core/post-author-name` |
| Date on a post | `core/post-date` |
| Comment count | `core/comments-count` |

### The only things allowed to be hardcoded in templates/parts

- **Structural section labels** that describe the role of a region, not its content (e.g. an `<h6>SHOP</h6>` heading above a `core/navigation` block). These are theme furniture, not content.
- **Skip-to-content link** (`Skip to main content`) — this is an a11y primitive.
- **Block placeholder text** that the user is expected to replace via Site Editor (e.g. button copy in patterns under `_examples/`). Templates and parts that ship active should not need this.

If in doubt: ask "if the user changes this in the admin, will the template update?" If the answer is no, it's wrong.

### Menus specifically

A menu is **never** a `<ul>` of `<li><a>` tags. Always `core/navigation`.

- If the menu doesn't exist yet in the DB, the `core/navigation` block will fall back to a "create menu" placeholder in the editor, and on the front-end will silently render an unstyled page list. This is acceptable as a starting state.
- For a polished out-of-box experience, **seed the menus during step 8** (see below).
- Each region needs its own menu ref. Don't reuse the primary menu ref for footer columns — it'll spam every column with the same items.

### Why this matters more than it looks

The Chonk theme currently has hardcoded `<li><a href="/about">About</a></li>` lists in the footer. Every one of those links is dead because there's no `/about` page in the DB. The site looks finished but is a Potemkin village. The fix is one `core/navigation` block per column plus `wp menu create` seeding.

---

## Step 1 — Preflight (read before writing)

Always read these in this order, from the **base theme** being cloned (usually `obel`):

1. `AGENTS.md` — the hard rules. Internalize them. Common ones:
   - No `!important` anywhere
   - No `<style>` tags or `.css` files (only `theme.json`)
   - No custom blocks (only `core/*` and `woocommerce/*`)
   - No hardcoded colors / pixel values — always design tokens
   - The `css` escape hatch in `theme.json` is for ≤ 2-3 unfixable cases
2. `INDEX.md` — the auto-generated map of every template, part, pattern, and token
3. `theme.json` — skim the existing token vocabulary so the variant reuses slugs

**Bin tools that must be used (don't reinvent):**

| Tool | Purpose |
|---|---|
| `python3 bin/clone.py NEW_NAME` | Clone the base theme into `../NEW_NAME` with all identifiers renamed |
| `python3 bin/build-index.py` | Regenerate `INDEX.md` after token/template edits |
| `python3 bin/check.py --quick` | Run before declaring done (catches `!important`, hardcoded colors, stray CSS, fingerprints, etc.) |
| `python3 bin/list-tokens.py` | Print every token slug |

If any of these scripts are missing, stop and tell the user — don't improvise alternatives.

---

## Step 2 — Pin design intent in ONE batched question pass

Generate a mockup image **first** with `GenerateImage`, then ask **all** of these in a single `AskQuestion` call. Do not start building until answered.

**The four questions that always matter:**

```
1. NAME            → confirm the new theme slug (lowercase, no spaces)
2. PALETTE         → which 4-6 colors anchor it? (hex or "use the mockup")
3. TYPE            → display font intent (e.g. "condensed brutal poster",
                     "high-contrast didone", "neutral grotesk"). If the
                     intent calls for a non-system family, it MUST be a
                     Google Fonts family self-hosted via fontFace (see
                     "Fonts" hard rule below). Never link Google Fonts CDN.
4. SHAPE           → page composition keywords (asymmetric / centered / grid /
                     editorial / dense) and which sections need radical restyle
                     vs. light retheme
```

Bundle them. Never drip-feed.

If the user provided a mockup image already, infer answers and **confirm** in one ask, don't re-derive from scratch.

---

## Step 3 — Plan the full token system on paper

Before opening `theme.json`, write out (in chat or a scratch comment) the full token map:

```
COLORS    base / contrast / surface / subtle / border / accent / accent-2 / muted / ...
TYPE      sans + display fontFamily, fontFace registration, full font-size scale,
          font-weights (regular/medium/semibold/bold), letter-spacing scale
          (tighter/tight/normal/wide/wider/widest), line-heights
SPACING   2-xs/xs/sm/md/lg/xl/2-xl/3-xl
SHADOW    sm/md/lg (and whether they're soft or hard offset)
RADIUS    sm/md/lg (zero for brutal, generous for soft)
BORDERS   hairline/thick/chunky widths
ELEMENTS  heading + h1/h2 overrides, button (border + shadow), link
```

This prevents the "I'll patch it later" loop. The tokens are the design system; if they're wrong, every block will look wrong.

---

## Step 4 — Clone

```bash
cd path/to/base/theme
python3 bin/clone.py NEW_NAME
```

`clone.py` handles renaming text-domain, function prefixes, README, etc. Don't manually copy files.

After cloning, immediately:
- Read the cloned `AGENTS.md` (it's a copy of the base's — the hard rules still apply)
- `cd ../NEW_NAME && python3 bin/check.py --quick` to confirm it starts green

---

## Step 5 — Tokens first

Edit only `theme.json`. Do not touch a template until the tokens are right.

### Plan contrast pairs at design-system time

Before finalizing the palette, write out every text-on-background pairing the theme will use, and check each against WCAG AA (4.5:1 for body text, 3:1 for large text ≥18pt or ≥14pt bold, 3:1 for UI components and meaningful graphical objects).

Required pairings to verify before you commit the palette:

| Foreground | Background | Required ratio | Where it appears |
|---|---|---|---|
| `contrast` | `base` | ≥ 4.5:1 | Body text on page background |
| `contrast` | `surface` | ≥ 4.5:1 | Body text on cards / hero blocks |
| `contrast` | `subtle` | ≥ 4.5:1 | Body text on alt sections / muted strips |
| `contrast` | `accent` | ≥ 4.5:1 | Body text on accent panels / announcement bar (if reversed) |
| `contrast` | `accent-2` | ≥ 4.5:1 | Same, second accent |
| `accent` | `contrast` | ≥ 4.5:1 | Yellow text on black (announcement bar pattern) |
| `base` | `contrast` | ≥ 4.5:1 | Reversed footer / dark sections |
| `secondary` / `tertiary` | `base` | ≥ 4.5:1 | Captions, taglines, meta text |
| `secondary` / `tertiary` | `surface` | ≥ 4.5:1 | Same on cards |
| `border` | `base` | ≥ 3:1 | Borders, dividers, outlines |
| Button label | Button background | ≥ 4.5:1 | Primary, secondary, ghost button states |
| Link | Surrounding text background | ≥ 4.5:1 | Inline links in body copy |
| Focus ring | Adjacent background | ≥ 3:1 | Keyboard focus indicators |

**Use the contrast-check script to verify before locking the palette:**

```bash
python3 bin/check-contrast.py
```

If `bin/check-contrast.py` doesn't exist in the base theme, **create it once** in your first variant build (it's reusable). It should parse `theme.json` palette + the pairing table above and exit non-zero on any AA failure. A reference implementation lives in this skill at `scripts/check-contrast.py` — copy it to `bin/` of the cloned theme on first use.

**If a pairing fails AA**, you have three options, in order of preference:
1. Adjust the offending color slug (usually `secondary`/`tertiary` need to darken, or `accent` needs more saturation against white)
2. Pair the text with a different background slug (don't put `tertiary` on `subtle` — too low contrast almost always)
3. Bump the type size into the "large text" tier so 3:1 is sufficient (only acceptable for genuinely large display text, not as a workaround for small body text)

**Never** lower the contrast target. WCAG AA is the floor, not a goal.

### Letter-spacing rule of thumb (matters more than people think)

| Display font character | tighter | tight | normal | wider |
|---|---|---|---|---|
| Condensed brutal (Anton, Impact) | -0.01em | 0 | 0.01em | 0.08em |
| Geometric sans (Inter, Helvetica) | -0.02em | -0.01em | 0 | 0.06em |
| Serif display (Playfair, Didone) | -0.03em | -0.02em | -0.01em | 0.04em |

Wrong letter-spacing makes a Anton/Impact headline look broken. Always recalibrate when swapping the display fontFamily.

**Slug gotcha:** WordPress normalizes any digit-letter slug like `6xl` to `6-xl` in the generated CSS variable. Always use the dashed form (`6-xl`, `4-xl`, `2-xs`) in slugs and class names. If you see a headline rendering tiny, this is almost always the cause.

**Fonts: self-hosted Google Fonts only (hard rule).**

System font stacks are always allowed and are the default. If the variant calls for a non-system family, it **must** be a Google Fonts family **downloaded as `.woff2`** into `assets/fonts/` and registered via `theme.json` `fontFace`. There are no other allowed sources.

Forbidden — any of these is a hard-rule violation that `bin/check.py` (`check_no_remote_fonts`) catches:

- `https://fonts.googleapis.com/...` (the Google Fonts CSS API)
- `https://fonts.gstatic.com/...` (Google Fonts asset CDN)
- `<link rel="preconnect" href="https://fonts...">` in any template / part / pattern / `functions.php`
- `@import url('https://fonts...')` anywhere in `theme.json` styles or PHP-emitted CSS
- Adobe Typekit (`use.typekit.net`), Bunny Fonts, Fontshare, custom CDN font URLs
- `fontFace[*].src` containing anything other than a `file:./...` path

Why: privacy (no third-party requests on first paint), performance (no extra DNS / TLS hop blocking critical fonts), license clarity (Google Fonts ship under the SIL OFL — clean for clones; arbitrary CDNs are a license unknown), offline editability (the Site Editor must render correctly on a plane).

**How to add one (the only correct path):**

1. Pick the Google Font you want (e.g. Anton, Inter, Playfair Display).
2. Download the `.woff2` files for the weights you actually use. Two safe sources:
   - The official Google Fonts download zip → extract the static `.ttf`s and convert to `.woff2` (`woff2_compress` from the `woff2` package), or
   - `https://gwfh.mranftl.com/fonts` (mirrors the official files as `.woff2` directly)
3. Drop the files into `assets/fonts/<family>-<weight>.woff2`. One file per weight + style combo.
4. Register them in `theme.json`:

```json
{
  "slug": "display",
  "name": "Display",
  "fontFamily": "\"Anton\", Impact, sans-serif",
  "fontFace": [{
    "fontFamily": "Anton",
    "fontWeight": "400",
    "fontStyle": "normal",
    "fontDisplay": "swap",
    "src": ["file:./assets/fonts/anton-regular.woff2"]
  }]
}
```

5. Always `"fontDisplay":"swap"` (system stack renders first, custom font swaps in when ready — no FOIT).
6. Always include a system fallback in `fontFamily` (the comma-separated stack after the custom name).
7. Run `python3 bin/check.py --quick` — `check_no_remote_fonts` will fail loudly if anything slipped in via a remote URL.

---

## Step 6 — Design every surface (not just the homepage)

**Token swaps alone are never enough.** If the mockup has an asymmetric hero, you must restructure `templates/front-page.html` into asymmetric columns. The "looks nothing like the image" failure mode comes from skipping this step.

**Equally important:** restyling only the homepage and shipping is the #1 cause of "the cart looks broken / 404 looks generic / search results have no styling" follow-ups. Every surface a user can land on must be designed.

### The mandatory surface checklist

The moment you start step 6, create a `TodoWrite` list with **one todo per surface below**, marked `pending`. Mark each `in_progress` when you start it, `completed` only after you've (1) restyled it, (2) loaded it in the browser, and (3) confirmed it visually matches the variant's design language.

**Templates (page-level layouts):**

| Todo | File | What to design |
|---|---|---|
| Front page | `templates/front-page.html` | Hero, value proposition, dynamic category tiles, dynamic product grid, manifesto/about strip, newsletter, anything else the mockup specifies |
| Home / blog index | `templates/home.html` (or `index.html`) | Post list layout, post card style, pagination |
| Generic index fallback | `templates/index.html` | Catch-all archive layout — must work standalone |
| Single post | `templates/single.html` | Title, meta, content typography, author bio, related posts, comments |
| Single page | `templates/page.html` | Title, content typography, no post meta |
| Date/category/tag archive | `templates/archive.html` | Archive header, post grid, pagination |
| Author archive | `templates/author.html` | Author bio header + post list (only if differentiated from `archive.html`) |
| Search results | `templates/search.html` | Search form prominence, results list, no-results state |
| 404 | `templates/404.html` | Branded error message, search box, links back to key sections |
| Password protected | `templates/password-protected.html` | Branded password entry form |
| **WooCommerce →** | | |
| Shop archive | `templates/archive-product.html` | Filter sidebar/bar, product grid, sort controls, pagination |
| Product category | `templates/taxonomy-product_cat.html` | Category header, product grid (often inherits from archive-product) |
| Product tag | `templates/taxonomy-product_tag.html` | Tag header, product grid |
| Single product | `templates/single-product.html` | Gallery, title, price, add-to-cart, tabs/description, related products |
| Cart | `templates/cart.html` | Line items, totals, cross-sells, checkout CTA, empty state |
| Checkout | `templates/checkout.html` | Form layout, order summary sidebar, payment methods, place-order CTA |
| Order received | `templates/order-confirmation.html` | Thank-you state, order details, next-steps CTA |
| My account | `templates/page-my-account.html` (or via WC default) | Dashboard, order history, addresses, account details |

**Parts (reusable regions):**

| Todo | File | What to design |
|---|---|---|
| Header | `parts/header.html` | Brand, primary nav (`core/navigation` ref), search, account, mini-cart |
| Footer | `parts/footer.html` | Brand, dynamic category list, real `core/navigation` menus per column, legal nav, social |
| Announcement bar | `parts/announcement-bar.html` | Full-bleed promo strip; **lift out of header** so `align:full` works |
| Sidebar (if used) | `parts/sidebar.html` | Widget area styling, used on archives if the design calls for it |
| Comments | `parts/comments.html` | Comment list typography, response form |
| Mini cart drawer | `parts/mini-cart.html` (if applicable) | Drawer styling consistent with header/cart |

### Rules of engagement for the surface pass

1. **Every surface is treated as a first-class design problem**, not a "the framework will handle it" assumption. WooCommerce's defaults look generic; if you don't override them, your variant will look like a generic WC site on every shop/cart/checkout page.
2. **Don't delete WooCommerce template files** even if they look fine with global token inheritance. Open each one, confirm it picks up the variant's tokens correctly, and add per-block overrides where the design demands them (cart line items, checkout form fields, mini-cart drawer all have specific block-level styling needs).
3. **For each surface, decide between three levels of intervention** before touching it:
   - **Inherit only** — global tokens carry it (rare, only for surfaces that are pure typography like a single page)
   - **Restyle in `theme.json`** under `styles.blocks.<woocommerce/...>` (preferred)
   - **Restructure the template** because the default block tree doesn't match the mockup (e.g. cart wants a 2-column layout with summary sidebar)
4. **For each surface, populate or simulate real data before screenshotting:**
   - Shop / single product → seeded products (use the WC sample data importer if needed: `wp wc tool run install_pages` and `wp wc importer ...`)
   - Cart → `wp wc cart add-item ...` or manually add via UI before screenshotting
   - Checkout → must view as a guest with a non-empty cart
   - Search results → real search query that returns 1+ result, plus a no-results state
   - 404 → a deliberately bad URL
   - My account → log in as a test customer
   - Order confirmation → place a real test order or use `wp post list --post_type=shop_order` and view one
5. **No surface is "done" without a screenshot taken at the desktop viewport** with real content visible. Empty-state screenshots count separately (cart-empty, search-no-results, 404).

### Common structural patterns

| Mockup feature | Block recipe |
|---|---|
| Asymmetric hero (60/40) | `core/columns` with explicit `width:"60%"` + `width:"40%"` and a CSS rule forcing `flex-wrap:nowrap` at ≥782px |
| Full-bleed top announcement bar | Lift `parts/announcement-bar.html` OUT of `parts/header.html` and include it directly in templates with `align:"full"` |
| Category tile grid | `core/terms-query` with `taxonomy:"product_cat"`, `showNested:true`, `orderBy:"count"`, then `core/term-template` with grid layout |
| Product grid | `core/query` with `query.postType:"product"`, then `core/post-template` |
| Chunky photo placeholder | `core/group` with thick border + hard offset shadow + a centered glyph, no `core/image` |
| Rotated "NEW" sticker | `core/group` absolutely positioned via the `css` escape hatch (one of the few legit uses) |
| Cart line items | `woocommerce/cart-items-block` — restyle via `styles.blocks.woocommerce/cart-items-block` |
| Checkout form fields | Inherit from `core/search` and form element styles in `styles.elements.input` (declare these in tokens step) |
| My-account dashboard nav | `woocommerce/customer-account-content` — style its child blocks individually |

### Which surface = which URL

So you can verify quickly:

```
Front page                  /
Blog index                  /blog (or /?paged=1 if no blog page set)
Single post                 /YYYY/MM/DD/slug or /?p=N
Single page                 /about (or any seeded page)
Date archive                /YYYY
Category archive            /category/slug
Author archive              /author/slug
Search results              /?s=query
No-results search           /?s=zzzzzznoresults
404                         /this-page-does-not-exist
Shop                        /shop
Product category            /product-category/slug
Single product              /product/slug
Cart                        /cart
Checkout                    /checkout (with non-empty cart)
Order received              /checkout/order-received/N (or after a test order)
My account                  /my-account (logged in)
My account login            /my-account (logged out)
Password protected          any post with a password set
```

If a URL doesn't resolve, you're looking at a missing template or a missing data seed — either way, fix it before declaring the surface done.

---

## Step 7 — Make everything dynamic via built-in core blocks

The user's content should drive the theme, not the other way around. **No shortcodes. No custom blocks.** Use core/woocommerce blocks only.

| Need dynamic… | Use |
|---|---|
| Site name in footer/header | `core/site-title` (`level:0` for paragraph, with `isLink:true`) |
| Site tagline | `core/site-tagline` |
| Logo | `core/site-logo` |
| Product categories | `core/terms-query` + `core/term-template` + `core/term-name` + `core/term-count` |
| Recent products | `core/query` with `postType:"product"` + `core/post-template` |
| Recent posts | `core/query` + `core/post-template` |
| Author meta | `core/post-author-name` / `core/post-date` |

**`core/terms-query` gotchas:**
- Set `showNested:true` to surface child terms (without it you only get top-level "Shop" with count 0)
- `orderBy:"count"` + `order:"desc"` + `perPage:N` will push popular categories to the top and quietly drop the empty parent
- After editing, bust the page cache (`?cb=N`) — WordPress caches term queries hard

---

## Step 8 — Seed real data so dynamic blocks have something to render

A theme that uses `core/navigation` and `core/terms-query` everywhere is correct in principle, but if the DB has no menus, no pages, and one default category, the front-end will look broken. Seed the data so the dynamic blocks have real content to show.

**Required seed pass (use WP-CLI):**

```bash
# Pages the theme references (about, journal, contact, shipping, returns, faq, privacy, terms, cookies, stockists)
for slug in about journal stockists contact shipping returns faq privacy terms cookies; do
  wp --path=PATH post create --post_type=page --post_status=publish \
    --post_title="$(echo $slug | awk '{print toupper(substr($0,1,1)) substr($0,2)}')" \
    --post_name="$slug"
done

# Menus the templates reference
wp --path=PATH menu create "Primary"
wp --path=PATH menu create "Footer Shop"      # often replaced by core/terms-query
wp --path=PATH menu create "Footer Company"
wp --path=PATH menu create "Footer Help"
wp --path=PATH menu create "Footer Legal"

# Populate menus with the seeded pages
wp --path=PATH menu item add-post footer-company $(wp --path=PATH post list --post_type=page --name=about --field=ID)
# …repeat per menu/page combination, or script it

# Convert classic menus to wp_navigation block menus (so core/navigation can ref them)
wp --path=PATH eval 'foreach (wp_get_nav_menus() as $m) { wp_classic_to_block_menu_converter($m->term_id); }'
```

**Then wire `core/navigation` blocks to the seeded menus:**

```bash
# Get the wp_navigation post IDs
wp --path=PATH post list --post_type=wp_navigation --fields=ID,post_title
```

Use the returned IDs as the `ref` attribute in `core/navigation`:

```html
<!-- wp:navigation {"ref":42,"overlayMenu":"never","layout":{"type":"flex","orientation":"vertical"}} /-->
```

**If seeding is out of scope** (e.g. user explicitly says "don't seed, I'll do it"), use unrefenced `core/navigation` blocks and document in the report that the user needs to wire menus via Site Editor → Navigation. **Do not** fall back to hardcoded `<ul>` lists.

For product categories specifically, the user almost always already has terms via WooCommerce — `core/terms-query` will pick those up automatically without seeding.

---

## Step 9 — Ship a working Playground blueprint

**Every theme in this monorepo must ship a working `<theme>/playground/blueprint.json` AND a self-contained per-theme content set under `<theme>/playground/{content,images}/`.** It is part of the deliverable, not an extra. A theme without a working blueprint is incomplete — there's no other way for a reviewer to load it without a full local WP + WC install. A theme that boots but renders the same product imagery as every other variant defeats the purpose of building variants.

### What you don't have to do

`bin/clone.py` already copied `obel/playground/blueprint.json` into your new theme and rewrote `obel`→`<new>` and `Obel`→`<New>` in the JSON. That handles `installTheme.path`, `installTheme.options.targetFolderName`, `setSiteOptions.blogname`, and the meta `title`/`description`. Don't recreate the blueprint by hand.

`bin/clone.py` did NOT copy `obel/playground/content/` or `obel/playground/images/` — that's intentional. Those folders hold per-theme content with image URLs that bake in the theme slug, and clone.py's text substitution doesn't touch CSV/XML. Run the seed script next:

```bash
python3 bin/seed-playground-content.py
```

This auto-discovers themes that don't yet have `playground/content/`, fetches the canonical CSV / WXR / asset bundle from `RegionallyFamous/wonders-oddities` (cached at `/tmp/wonders-oddities-source` between runs), and writes them into `<theme>/playground/content/` and `<theme>/playground/images/` with every image URL inside the CSV/XML rewritten to point at this theme's own `images/` folder. Idempotent — re-runs are no-ops. Pass `--force` only when you intentionally want to re-pull from the upstream source (the per-theme files are the canonical source for that theme after the initial seed).

Once both content and blueprint are in place, sync the shared helpers:

### What you must do

```bash
python3 bin/sync-playground.py
```

This auto-discovers every theme in the monorepo (via `_lib.iter_themes()`) and re-inlines the latest `playground/*.php` bodies into each blueprint, prepending the per-theme constants block (`WO_THEME_NAME` from `theme.json` `title`, `WO_THEME_SLUG` and `WO_CONTENT_BASE_URL` from the directory name) and rewriting the `importWxr` step's URL to point at this theme's own `content/content.xml`. There is no hardcoded theme list — adding a new theme is automatic. Run it once after cloning + seeding, and again any time `playground/wo-import.php`, `playground/wo-configure.php`, or `playground/wo-cart-mu.php` change.

Per-theme content edits (replacing artwork, rewriting copy, swapping SKUs) do NOT require re-syncing — those URLs are fetched live by the blueprint and importer at boot. The sync script only matters when the shared scaffolding or the per-theme constants need to change inside the inlined PHP bodies.

Then load the deeplink and walk the surface checklist:

```
https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/<org>/<repo>/main/<theme>/playground/blueprint.json
```

Append `&url=/<path>/` to deep-link into a specific surface. Walk these at minimum, in order:

```
&url=/                            front page
&url=/shop/                       shop archive
&url=/product/bottled-morning/    single product
&url=/cart/?demo=cart             cart (pre-filled by the mu-plugin)
&url=/checkout/?demo=cart         checkout
&url=/journal/                    blog index
&url=/welcome-to-wonders-and-oddities/   single post
&url=/this-route-does-not-exist/  404
```

If **any** pretty URL 404s, the blueprint is broken — almost certainly the permalink-flush gotcha (see below). Don't ship until every URL above resolves to a designed page.

### Playground gotchas

**Permalink flush in `wp eval-file` context.** This is the bug that ate hours and shipped a broken demo for both obel and chonk. The naive pattern

```php
update_option( 'permalink_structure', '/%postname%/' );
flush_rewrite_rules( true );
```

does **not** work. The global `$wp_rewrite` was constructed at WP boot from the previous (default = empty) structure; `update_option()` doesn't touch it. `flush_rewrite_rules()` then regenerates the `rewrite_rules` option from that stale property, producing rules for the default URL scheme. Every pretty post / page / product URL 404s as a result.

The correct pattern (already in `playground/wo-configure.php`) is:

```php
global $wp_rewrite;
$wp_rewrite->set_permalink_structure( '/%postname%/' );
$wp_rewrite->set_category_base( '' );
$wp_rewrite->set_tag_base( '' );
$wp_rewrite->flush_rules( true );
delete_option( 'rewrite_rules' );  // belt + suspenders for lazy rebuild
```

Don't "simplify" it back. If you do, you're reintroducing the bug.

**Don't use `{ resource: url }` for the `writeFile` data field.** Playground caches URL fetches across boots, and `raw.githubusercontent.com` ships `cache-control: max-age=300`. A pushed change to the script can take 5+ minutes to surface, and Playground will run the previous version against the new blueprint. The whole point of `bin/sync-playground.py` is to inline the script body so there's only one URL to invalidate. Keep it inlined.

**Playground's `wp-cli` step has no shell.** The command string is parsed into args and handed straight to WP-CLI; there is no `&&`, no `||`, no `;`, no `$(…)`, no pipes. Use a `runPHP` step (with `require_once '/wordpress/wp-load.php';` at the top) or a `wp eval-file` against a `writeFile`'d script for anything more complex than a single command.

**Test in a fresh browser / incognito.** Playground persists each scope's WP install in the browser's OPFS, so loading a deeplink with an existing scope replays the previously-booted state — bug fixes in the blueprint won't take effect until a fresh scope boots. When verifying a fix, always use a brand-new browser context.

---

## Step 10 — Verify

Run, in order:

```bash
python3 bin/build-index.py            # regenerate INDEX.md
python3 bin/check.py --quick          # catches !important, stray CSS, hardcoded colors
```

If `check.py` flags `!important` or hardcoded colors, **fix them** — don't suppress. Those are hard-rule violations.

Then visual verification — **three passes, all required**:

```bash
wp --path=PATH theme activate NEW_NAME
wp --path=PATH cache flush
python3 bin/check-contrast.py        # palette-level WCAG audit, must exit 0
```

### Pass A — every surface at desktop (≥1280 px), with real content

Walk the URL list from step 6 in order. For each, navigate (with `?cb=N` cache-bust), screenshot, and confirm:

- The variant's tokens (color, type, spacing, shadow) are visibly applied
- No surface renders with default WP/WC styling that contradicts the mockup
- Real content is visible (cart has items, search returns results, my-account shows a logged-in dashboard)
- Any `core/navigation`, `core/terms-query`, `core/query` blocks have a real `ref` or wired data — none are showing empty states or "Add a menu" placeholders

If a surface is broken, **fix it now before moving on** — don't batch fixes for the end. Each surface often surfaces a per-block override you also need to apply elsewhere.

### Pass B — every surface at three viewports

This is the part that catches "looks great on my big screen, broken on a phone" failures, which are universal.

For **every surface in the step 6 checklist** (not just the homepage), capture screenshots at:

| Viewport | Width | What to verify |
|---|---|---|
| Mobile  | ~390 px  | Columns stack cleanly, no horizontal scroll, tap targets ≥ 44 px, hamburger nav opens, mini-cart drawer fits |
| Tablet  | ~768 px  | Asymmetric layouts hold or gracefully reflow, multi-column grids transition sensibly |
| Desktop | ~1280 px | Full composition matches mockup, max content width is respected, gutters are consistent |

Browser MCP-specific note: it often defaults to ~660 px even after `browser_resize`. Always issue `browser_resize` immediately before each screenshot pass and confirm the snapshot metadata reflects the requested width.

For each viewport pass, scroll to header, main content, mid-page, and **footer** before declaring the surface done. Footer regressions remain the most common miss.

**Acceptable shortcut:** if a surface inherits its layout entirely from another (e.g. `taxonomy-product_cat.html` from `archive-product.html`, or `archive.html` from `index.html`), one viewport pass on the parent + a desktop spot-check on the child is enough.

### Pass C-zero — structural defect scan (do this BEFORE contrast)

**This pass exists because "looks ok at a glance" is the failure mode that ships broken layouts.** Contrast and design-language checks assume the layout is structurally sound. If it isn't, you're auditing the wrong thing.

For **every** screenshot (every surface, every viewport), run through this fixed triage list. The point is to look for *specific defect classes*, not to "see if anything looks weird".

**The fixed triage list — apply to every screenshot:**

1. **Empty grid/flex cells.** For every list, grid, or row of cards, count visible items vs. expected items from the data. If the grid has 4 cells and you see 2 cards + 2 blank slots, **stop**. Don't move on. This is almost always one of:
   - WooCommerce's clearfix `::before`/`::after` pseudo-elements becoming grid items (see WC integration gotchas below)
   - Legacy WC `width: 22.05% / 30.79% / 48%` percentage widths leaking into grid cells
   - `clear: both` on `nth-child(Nn)` in a flex/grid context displacing items
   - A query block returning fewer items than `perPage` because the data is thin (legitimate; verify by counting from `wp post list`)

2. **Orphaned items.** Item in column 2 with column 1 empty. Item in row 2 column 1 with row 1 column 2 empty. Either pattern means the parent grid has more cells than there are real children — see (1).

3. **Ghost overlay menus.** A `core/navigation` block rendering as a hamburger overlay when the markup says `overlayMenu:"never"`. Open the page in DOM inspector — if there's a `wp-block-navigation__responsive-container` you didn't ask for, the nav is suffering from the multi-nav-rendering bug (see WC integration gotchas).

4. **Default WC/WP styling leaking through.** Scan for: purple `--wc-primary` buttons, default WC sale-badge styling, default cart line-item table, default checkout form field padding, default WP `.wp-block-button` styles. If any of these appear, the variant's per-block override is missing in `theme.json styles.blocks.<block>`.

5. **Collapsed dimensions.** A region that should have height has 0 (or near-0) height. A button that should have padding has none. A card with no inner spacing. Almost always: a per-block style overriding a token, or a missing token where the block expected one.

6. **Hover/focus states unstyled.** Hover the primary CTA. Tab to it. If hover/focus look identical to default, the per-block hover styling is missing. Tab through three interactive elements per surface — every one must show a focus ring at ≥ 3:1 contrast.

7. **Item-count mismatch.** Use the page snapshot accessibility tree: count `listitem` roles in a `list`, count cards in a `region`. Compare to what the data layer says exists. Mismatch means rendering is dropping items silently.

8. **Off-canvas / clipped content.** A card whose right edge is cut by `overflow:hidden`. A heading that wraps unexpectedly. A button label truncated mid-word. Almost always: a `width` or `max-width` token that didn't account for the variant's display-font width.

**How to actually run this scan:**

For each screenshot, walk the 8 items above and write a one-line yes/no in your scratch notes. Don't move to the next surface until every item is "no defect" or has a tracked fix. **"Looks fine" is not an answer to any of these — they all demand a structural verification.**

If a defect is found, fix it before continuing. If the same defect class appears on more than one surface, write it up as a new entry in the WC integration gotchas table (below) so future passes catch it at lint time, not visual time.

### Pass C — per-surface contrast audit

Palette-level contrast (`bin/check-contrast.py`) catches token pairings that fail in theory. Per-surface contrast catches what actually happens once blocks render — overlay text on images, button hover states, focus rings, links inside cards, badge labels on accent backgrounds.

For each rendered surface, scan visually for:

- **Body text on every background it sits on** (page bg, cards, banner strips, alternate sections) — must hit ≥ 4.5:1 ratio
- **Meta text** (prices, dates, captions) on the same — also ≥ 4.5:1, and these are the most common regressions because designers reach for `secondary`/`tertiary` slugs that sit too close to the background
- **Buttons** — label vs. background ≥ 4.5:1 in default, hover, and disabled states
- **Links inline in body copy** — the link color vs. the surrounding background ≥ 4.5:1
- **Focus rings on every interactive element** — ≥ 3:1 vs. adjacent background, never just `outline:none`
- **Form fields** — placeholder text and value text both readable; field border ≥ 3:1 vs. page bg
- **Overlay text on images** (hero image with text on top) — needs scrim/overlay or font weight/color combo that hits 4.5:1 against the worst-case pixel
- **Status colors** (sale price, "out of stock", success/error) — these almost always fail because they default to red/green that nobody recalibrated

When in doubt, test the rendered pixel. Open DevTools, pick the foreground text element, and use the inspector's contrast ratio panel. If unavailable, eyeball the screenshot at 100% zoom in indirect light — if you have to lean in, it fails.

Fix every contrast failure immediately. Common fixes:
- Add a `styles.blocks.<block>.color.text` override pointing to `contrast` instead of `secondary`
- Darken the offending palette slug in `theme.json` (re-run `bin/check-contrast.py` after)
- Add an explicit hover background to buttons so the label-on-bg ratio doesn't degrade on hover
- Add a scrim group (`core/group` with semi-opaque `contrast` background) under hero overlay text

---

## Step 11 — Report once

Send the user a single summary message containing:

- Theme slug + activation status
- A bullet list of what changed (tokens, templates, parts, dynamic blocks added)
- Any deliberate deviations from the mockup with one-sentence rationale
- A note about what they own next (writing menu items, uploading product images, etc.)

**Do not** ask "want me to also do the footer?" / "should I update the 404?" — those are part of the job. Either do them or list them as deliberate skips.

---

## Anti-patterns from past failures

These are real mistakes from the Chonk build. Don't repeat them.

| Mistake | Fix |
|---|---|
| Used `!important` in the `theme.json` `css` field to override block styles | Use proper element/block-level styles in `theme.json`. `!important` is a hard-rule violation. |
| Hardcoded `#000000` in shadow definitions | Use `var(--wp--preset--color--contrast)` |
| Reached for the `css` escape hatch ≥ 5 times | Cap it at 2-3 unfixable cases (sticker positioning, asymmetric flex-wrap override). Anything more means the design tokens are wrong. |
| Built homepage faithfully but left the footer as the cloned default | Audit every template + part in step 6. The user will notice. |
| Used hardcoded category names in nav menus | Use `core/terms-query` so it auto-updates when the user adds categories |
| Asked "should I make X dynamic?" mid-build | Default is yes, always, via core blocks. Only ask if there's no core block for it. |
| Slug `6xl` → CSS class `has-6xl-font-size` rendered tiny | Always use dashed form `6-xl` to match WordPress's CSS variable normalization |
| Announcement bar inside `parts/header.html` didn't go full-width | Lift it out as its own template part; include directly in templates with `align:"full"` |
| Took screenshots only at the default viewport | Screenshot at mobile + tablet + desktop. The browser MCP often defaults to ~660 px which masks desktop-only layout bugs. |
| Adopted a condensed display font (Anton/Impact) without recalibrating letter-spacing | Use the letter-spacing table in step 5. Default `tighter:-0.04em` strangles condensed fonts. |
| Footer columns built as `<ul><li><a href="/about">About</a></li>…</ul>` because "the menus aren't set up yet" | `core/navigation` block always. If the menu doesn't exist, seed it in step 8 via `wp menu create`. Hardcoded link lists are dead links the moment the user changes their site structure. |
| Hardcoded "© 2026 Site Title" copyright text | `core/site-title` for the name, current year via a real WP block (or accept "© All rights reserved." with no year — never invent a year that will be wrong in 9 months). |
| Used hardcoded category names anywhere outside a structural label | `core/terms-query` always |
| Verified responsiveness only on the homepage | Three-viewport screenshot pass required for **every** surface in step 10 Pass B (with the parent-inheritance shortcut). Cart layout almost always breaks at mobile in ways the homepage doesn't. |
| Used `secondary` / `tertiary` text color slugs without checking contrast on every background they land on | Plan contrast pairs in step 5 and run `bin/check-contrast.py`. Per-surface, audit body/meta/buttons/links/focus/form fields against WCAG AA in step 10 Pass C. |
| Shipped a theme variant without ever loading its Playground blueprint | Step 9 is non-optional. Every theme must have a working `<theme>/playground/blueprint.json`, which `bin/clone.py` creates and `bin/sync-playground.py` keeps in sync automatically. Walk the deeplink surface checklist before declaring done. |
| Skipped `bin/seed-playground-content.py` after cloning, so the new theme's Playground booted with no products / blank pages OR — worse — with image URLs pointing at obel's `playground/images/` because someone "fixed" clone.py to copy `playground/content/` over | clone.py deliberately skips per-theme `playground/content/` and `playground/images/`. Those folders bake the theme slug into every image URL inside the CSV and XML, and clone.py's text substitution doesn't touch CSV/XML. Always run `python3 bin/seed-playground-content.py` after `bin/clone.py` so the new theme's content/ is seeded fresh with image URLs rewritten to its own slug. |
| Hardcoded an image URL or theme name inside `playground/wo-import.php` or `playground/wo-configure.php` | Those scripts are SHARED across every theme — they must stay theme-agnostic and read URLs/names from the three constants `WO_THEME_NAME`, `WO_THEME_SLUG`, `WO_CONTENT_BASE_URL`. `bin/sync-playground.py` prepends the constants block when it inlines each script body. If the value you need can be expressed as a path under `WO_CONTENT_BASE_URL`, use that. Per-theme divergence belongs in `<theme>/playground/content/` (data) or `<theme>/playground/images/` (assets), never in the shared scripts. |
| "Simplified" the permalink section of `playground/wo-configure.php` back to `update_option(...)` + `flush_rewrite_rules(...)` | That's the bug. In a `wp eval-file` context the global `$wp_rewrite` is stale; you must use `$wp_rewrite->set_permalink_structure()` first. See "Playground gotchas" in step 9. |
| Removed the focus ring (`outline:none`) for visual cleanliness | Always keep a visible focus ring at ≥ 3:1 contrast. Style it; don't remove it. Tab through the homepage to verify before declaring done. |
| Status colors (sale price, error, success) defaulted to red/green with no recalibration against the variant palette | Treat status colors as palette slugs (`status-positive`, `status-negative`, `status-warning`) and run them through the contrast script along with everything else. |
| Used a `core/html` block to drop in raw markup because "the block I want doesn't quite exist" | Forbidden. Either compose the design from existing `core/*` / `woocommerce/*` blocks, or use the `theme.json` `css` escape hatch for pure styling problems. Raw HTML in a template defeats the entire design system. |
| Used `core/shortcode` with `[woocommerce_cart]` / `[woocommerce_checkout]` / `[woocommerce_my_account]` because the cloned template still had it | Replace with the modern `woocommerce/cart`, `woocommerce/checkout`, `woocommerce/customer-account-content` blocks. The legacy shortcodes render unstyled HTML the design system can't reach. |
| Left a `core/freeform` (Classic) block in a template after content migration | Convert to blocks via the editor or rewrite block-first. Classic blocks render outside the block tree and can't inherit any tokens. |
| Inlined arbitrary SVG via `core/html` in a template or part | Move the icon into a pattern (`patterns/`), confirm it's decorative + uses `currentColor`, or prefer a real `core/image` / icon block. Templates and parts are off-limits for raw HTML. |
| Set `display:grid` on `ul.products` (upsells / related / shop) without hiding WooCommerce's clearfix `::before` and `::after` pseudo-elements | The pseudos become real grid items and consume cells. See "WC integration gotchas" — fix is `display:none; content:none;` on the pseudos in the same scope. `bin/check.py` enforces this. |
| Used a vibe-check ("yep, looks brutal") instead of running the structural defect scan on every screenshot | Pass C-zero is non-optional. Walk all 8 items per screenshot. "Looks fine" is not an acceptable answer to any of them. |
| Trusted automated `check.py` + `check-contrast.py` green as proof the surface is shippable | Those checks catch token violations and palette pairings. They don't catch layout defects (empty grid cells, ghost overlays, displaced cards, default WC styles leaking through). Pass C-zero is the layer that catches those — run it. |
| Linked Google Fonts via `<link rel="stylesheet" href="https://fonts.googleapis.com/...">` in `parts/header.html` or via `wp_enqueue_style` in `functions.php` | Hard-rule violation. Download the `.woff2`(s) into `assets/fonts/` and register via `fontFace` with a `file:./...` src. `bin/check.py` `check_no_remote_fonts()` enforces it. |
| Stripped the View Transitions block from `theme.json` `styles.css` or the `render_block` filter from `functions.php` while restyling | Both halves of the cross-document VT contract are part of the visual baseline (see monorepo `AGENTS.md` "View Transitions"). Clones inherit them via `bin/clone.py`. The CSS opt-in (`@view-transition { navigation: auto }` + persistent header/footer/title names + reduced-motion guard) and the per-post `view-transition-name` filter must both ship on every variant. Without them, navigation feels static instead of like a modern site. |
| Reached for JavaScript to add typed View Transitions or `pagereveal` direction awareness | No JS bundles, no `<script>` tags. The CSS-only baseline (cross-document VT + persistent named regions + per-post morph) is the ceiling. If you want richer behavior, ship more CSS keyframes, not JavaScript. |
| Used `@import url('https://fonts.googleapis.com/...')` inside the `theme.json` `styles.css` escape hatch | Same violation. The `css` escape hatch is for tiny structural tweaks, not for smuggling in remote stylesheets. Self-host the `.woff2`. |
| Picked a non-Google-Fonts family (Adobe Typekit, custom foundry, Bunny Fonts CDN) for a variant | Not allowed. Either find a Google Fonts equivalent (there's almost always one) or stay on the system stack. Foundry/Adobe licensing rules out clone-and-ship. |
| Set `"fontDisplay":"block"` (or omitted it) so the page sat blank waiting for the custom font | Always `"fontDisplay":"swap"` so the system fallback renders first paint and the custom font swaps in when ready. |

---

## WooCommerce + theme.json integration gotchas

These are bugs where WooCommerce's plugin CSS or block-rendering quirks fight the variant's `theme.json`. Each one looks structurally broken (empty grid cells, ghost overlays, wrong widths) and *passes every existing automated check*. Add a new entry every time a new one is found in the wild.

| Symptom | Root cause | Fix in `theme.json` / `functions.php` | Lint check |
|---|---|---|---|
| `ul.products` rendered as `display:grid` shows ghost empty cells (e.g. 2 cards take cells 2 + 3 of 4, leaving 1 + 4 blank) | `.woocommerce ul.products::before` and `::after` are clearfix pseudo-elements (`display:table; clear:both`). When the parent becomes a grid container, those pseudos become real grid items and consume cells. | Hide the pseudos in the same scope as your grid rule: `.woocommerce-page <scope> ul.products::before, .woocommerce-page <scope> ul.products::after { display:none; content:none; }` | `bin/check.py` `check_wc_grid_integration()` — fails if any rule sets `display:grid` on `ul.products` (or `.products ul`) without a sibling rule nullifying the pseudos |
| `core/navigation` block with `overlayMenu:"never"` renders as a responsive hamburger overlay anyway, hiding its links | When multiple `core/navigation` blocks render in sequence on the same page (e.g. header nav + 2 footer column navs + 1 footer legal nav), WordPress's nav-block state leaks between them and a trailing horizontal nav inherits the responsive overlay behavior of an earlier vertical one. | Don't put a horizontal `core/navigation` after multiple vertical ones in the DOM. Either reorder, or replace the trailing one with a `wp:group` of `wp:paragraph` links if the menu is short and stable (privacy/terms/cookies). | `check.py` could grep for >2 `core/navigation` in a single template + part chain and warn — not yet implemented |
| Footer nav items have visually larger spacing than the `blockGap` setting | `core/navigation`'s global stylesheet sets `padding-block: var(--wp--preset--spacing--xs)` on `.wp-block-navigation-item__content` with higher specificity than block-level `blockGap`. | In your scoped footer CSS: `<scope> .wp-block-navigation-item__content { padding: 0; }` so the local `blockGap` wins. | Manual visual scan in Pass C-zero step 5 (collapsed/expanded dimensions) |
| Product cards in upsells / related render at 22% / 30% / 48% width instead of filling their grid cell | WC's legacy loop CSS: `.woocommerce ul.products[class*=columns-] li.product { width: 22.05% }` (varies per `.columns-N` class) overrides whatever you put on the LI inside the grid. | High-specificity reset: `.woocommerce-page <scope> ul.products li.product:nth-child(n) { width:100%; max-width:none; margin:0; padding:0; float:none; clear:none; }`. Note the `:nth-child(n)` — needed to win specificity over WC's `:nth-child(Nn)` margin-reset rules. | Same lint as row 1 |
| Theme.json CSS rule starting with `body ` ancestor selector renders without the `body` prefix | WordPress's theme.json CSS sanitizer strips a leading `body ` (or `body.<class>`) ancestor when it appears as the *first* selector in a comma-separated list. The other selectors keep their prefix. | Don't rely on `body ` for specificity. Use a more specific class on `body` (`.woocommerce-page`, `.single-product`, etc.) instead, or repeat the same prefix on every selector in the list. | Could be added: grep `theme.json` styles.css for `body ` followed by comma — not yet implemented |
| WC sets `.columns-4` on `ul.products` for upsells even when only 2 products exist, causing the grid to have empty cells | WC defaults `woocommerce_upsells_columns` to 4 regardless of available product count. | `add_filter('woocommerce_upsells_columns', fn($n, $upsells) => $upsells ? min(count($upsells), 4) : 4, 10, 2);` in `functions.php`. Also `woocommerce_output_related_products_args` for related. | Could grep `functions.php` for these filters when `single-product.html` template exists — not yet implemented |
| Footer "Privacy / Terms / Cookies" links don't render at all on some surfaces | A `core/navigation` block ref points to a `wp_navigation` post that doesn't exist (deleted, never created, or wrong ID). The block renders nothing instead of an error. | Verify every `ref:N` in templates/parts maps to a real post: `wp post list --post_type=wp_navigation --field=ID,post_title`. For short stable lists (≤4 items pointing at known pages), prefer inline `wp:paragraph` links over a `core/navigation` ref — fewer moving parts. | Could grep templates for `"ref":N` and verify each post exists — not yet implemented |
| `core/terms-query` shows nothing despite categories existing in DB | `showNested:false` (the default) only surfaces top-level terms; if your "Shop" parent has count 0 and all children are nested, the block looks empty. | Set `showNested:true` and use `orderBy:"count"` + `order:"desc"` so populated children float to the top. | Could grep templates for `core/terms-query` without `showNested:true` and warn — not yet implemented |
| Stock level renders twice on a single product page (e.g. themed "7 IN STOCK" above and a plain "7 in stock" right above the quantity field) | `woocommerce/add-to-cart-form` is a legacy block that auto-renders its own `<p class="stock">` and `<div class="woocommerce-variation-availability">` inside the form. When the template also includes a separate `woocommerce/product-stock-indicator` block (which we want, because that one is themable per block attrs), the user sees the stock label twice. We can't drop `add-to-cart-form` until WC ships the modern equivalent in its trunk template — see `obel/AGENTS.md` "Things that look like good ideas but aren't". | Hide the form's auto-rendered stock paragraphs in the theme.json `styles.css`: `.woocommerce div.product form.cart .stock, .woocommerce div.product .woocommerce-variation-availability { display: none; }`. Keep the standalone `woocommerce/product-stock-indicator` block in the template — that's the one with theme styling. | Could grep `templates/single-product.html` for both blocks without a matching display:none rule in `theme.json` styles.css — not yet implemented |
| Quantity field on the single product page looks small and visually disconnected from the ADD TO CART button (input renders ~28px tall, button ~44px tall, awkward gap) | Two compounding issues: (1) the form uses `align-items: center` so the smaller intrinsic input height stays small instead of stretching to match the button, and (2) WC's `input.qty` defaults are tiny (browser-default font + padding + 64px width) versus a generously padded button. | In theme.json `styles.css`: `.cart { align-items: stretch; gap: var(--wp--preset--spacing--md); }`, then bump the input to width ~88px, `font-size: var(--wp--preset--font-size--base)`, `font-weight: medium`, `padding: sm lg`, `line-height: 1`. Add a real `:focus-within` ring on the wrapper (`box-shadow: 0 0 0 3px var(--wp--preset--color--accent-soft)`) since `outline: none` on the input alone strips the only visible focus indicator. Kill `::-webkit-inner-spin-button` / `::-webkit-outer-spin-button` (`appearance: none; margin: 0`) so Chrome/Safari don't show ugly native spinners. | Visual scan in Pass C-zero step 4 (button vs input height parity). Worth a future lint that compares `padding-block` of `.cart .quantity input.qty` and `.single_add_to_cart_button` and warns when they don't match. |

**Process rule:** every time you find a new WC + theme.json integration bug, add a row to this table AND open a PR adding the lint check (or a "could be added" placeholder). Visual-only catches are a regression waiting to happen — encode the bug in the linter once and never see it again.

---

## The single AskQuestion call template

When the user asks for a variant, fire this exact pattern as your first action after preflight:

```
Title: "Pin the variant design"

Q1 (single): Theme slug?
  - [user-suggested name]
  - [vibe-derived suggestion 1]
  - [vibe-derived suggestion 2]

Q2 (multiple): Palette anchors?
  - Match the mockup
  - Cream + black + electric yellow
  - Off-white + ink + signal red
  - Custom (specify)

Q3 (single): Display type intent?
  - Condensed brutal poster (Anton, Impact)
  - High-contrast didone (Playfair Display)
  - Neutral grotesk (Inter, Helvetica)
  - Editorial serif (Cardo, EB Garamond)

Q4 (multiple): Layout aggression?
  - Asymmetric hero
  - Full-bleed announcement bar
  - Chunky tiled categories
  - Editorial 2-column page grid
  - Centered minimal (low aggression)
```

Plus generate a mockup image alongside, so the user can react to a picture, not a list.

---

## Final self-check before reporting

**Code hygiene:**

- [ ] `bin/check.py --quick` exits 0
- [ ] `bin/check-contrast.py` exits 0 (every required palette pairing meets WCAG AA)
- [ ] `INDEX.md` regenerated
- [ ] No `!important` in `theme.json` (grep confirms)
- [ ] No hardcoded hex colors in `theme.json` `css` field
- [ ] No remote font URLs anywhere — `fontFace[*].src` is `file:./...`, no `fonts.googleapis.com` / `fonts.gstatic.com` / `<link rel=preconnect>` to font CDNs / `@import url('https://fonts...')`. `bin/check.py check_no_remote_fonts` exits clean.

**No-static-content audit:**

- [ ] Zero `<ul><li><a>` link lists in templates/parts — every menu is `core/navigation` with a real `ref`
- [ ] Zero hardcoded site name, tagline, year, or address — every site datum is a `core/site-*` block
- [ ] Every category/product/post list uses `core/terms-query` or `core/query`, not hardcoded markup
- [ ] Menus, pages, and any referenced taxonomy terms exist in the DB (or explicitly handed off to the user with instructions)

**Playground blueprint (the deliverable is incomplete without this):**

- [ ] `<theme>/playground/blueprint.json` exists (created automatically by `bin/clone.py`)
- [ ] `<theme>/playground/content/` contains `products.csv`, `content.xml`, and `category-images.json` (created by `bin/seed-playground-content.py`)
- [ ] `<theme>/playground/images/` contains the per-theme product / page / post artwork (created by `bin/seed-playground-content.py`; replace with theme-styled artwork as desired)
- [ ] Sample image URLs inside `<theme>/playground/content/products.csv` and `content.xml` start with `https://raw.githubusercontent.com/<org>/<repo>/main/<theme>/playground/images/` — NOT `wonders-oddities` and NOT another theme's slug
- [ ] `python3 bin/sync-playground.py` reports "already in sync" for every theme (no stale inlined helpers)
- [ ] Blueprint metadata references the correct theme — `meta.title`, `meta.description`, `installTheme.path`, `installTheme.options.targetFolderName`, `setSiteOptions.blogname`, the `define('WO_THEME_NAME', '<Theme>')` constants prepended to `wo-import.php` and `wo-configure.php`, and the `importWxr` step's `file.url` all read `<Theme>` / `<theme>`, not `Obel` / `obel`
- [ ] Loaded the deeplink (`https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/<org>/<repo>/main/<theme>/playground/blueprint.json`) in a fresh browser / incognito window — boot completes without errors
- [ ] Walked every URL in the surface checklist (`/`, `/shop/`, `/product/bottled-morning/`, `/cart/?demo=cart`, `/checkout/?demo=cart`, `/journal/`, `/welcome-to-wonders-and-oddities/`, `/this-route-does-not-exist/`) — every pretty URL resolves to a designed page, no 404s on legitimate URLs, the 404 page renders the variant's branded 404
- [ ] `playground/wo-configure.php`'s permalink section still uses `$wp_rewrite->set_permalink_structure(...)` (not just `update_option(...)`)

**Modern-blocks-only audit (run the validation greps from the hard rule):**

- [ ] `grep -rE '<!-- wp:(html|shortcode|freeform)' templates parts patterns` returns zero matches
- [ ] `grep -rE '\[woocommerce_(cart|checkout|my_account|order_tracking)' templates parts patterns` returns zero matches
- [ ] `grep -rE '\[(products|product_category|recent_products|featured_products|sale_products|product_page|add_to_cart|shop_messages)' templates parts patterns` returns zero matches
- [ ] `wp_navigation` posts contain no `core/html` / `core/shortcode` / `core/freeform` blocks
- [ ] `templates/cart.html` uses `woocommerce/cart` (not `[woocommerce_cart]`)
- [ ] `templates/checkout.html` uses `woocommerce/checkout` (not `[woocommerce_checkout]`)
- [ ] My-account surface uses `woocommerce/customer-account-content` (not `[woocommerce_my_account]`)

**Surface coverage — for every surface, all four boxes must be ticked:**

| Surface | Restyled + desktop screenshot w/ real content | Mobile + tablet + desktop screenshots taken | Structural defect scan clean (8-item triage from Pass C-zero — empty cells, orphans, ghost overlays, default WC styles, collapsed dimensions, missing hover/focus, item-count mismatch, off-canvas) | Per-surface contrast audit clean (body, meta, buttons, links, focus, form fields) |
|---|---|---|---|---|
| Front page (`/`) | ☐ | ☐ | ☐ | ☐ |
| Blog index | ☐ | ☐ | ☐ | ☐ |
| Single post | ☐ | ☐ | ☐ | ☐ |
| Single page | ☐ | ☐ | ☐ | ☐ |
| Date / category / tag archive | ☐ | ☐ | ☐ | ☐ |
| Search results (real query) | ☐ | ☐ | ☐ | ☐ |
| Search results (no results) | ☐ | ☐ | ☐ | ☐ |
| 404 page | ☐ | ☐ | ☐ | ☐ |
| Shop archive | ☐ | ☐ | ☐ | ☐ |
| Product category archive | ☐ | ☐ | ☐ | ☐ |
| Single product (incl. upsells / related grid) | ☐ | ☐ | ☐ | ☐ |
| Cart (with items) | ☐ | ☐ | ☐ | ☐ |
| Cart (empty state) | ☐ | ☐ | ☐ | ☐ |
| Checkout | ☐ | ☐ | ☐ | ☐ |
| Order received | ☐ | ☐ | ☐ | ☐ |
| My account (logged in) | ☐ | ☐ | ☐ | ☐ |
| My account (logged out) | ☐ | ☐ | ☐ | ☐ |
| Header at every surface | ☐ | ☐ | ☐ | ☐ |
| Footer at every surface | ☐ | ☐ | ☐ | ☐ |
| Announcement bar at every surface | ☐ | ☐ | ☐ | ☐ |

The acceptable inheritance shortcut from Pass B applies (children of an already-verified parent surface need a desktop spot-check, not a full three-viewport pass), but the **structural defect scan** and **contrast audit** columns are **never** skipped — those are per-render, not per-template.

**End-to-end:**

- [ ] Walk every link in the rendered header and footer — none of them 404
- [ ] Mockup image vs. live site comparison: "yeah that's the same vibe", not "looks nothing like it"
- [ ] Place a test order start-to-finish (shop → product → add to cart → checkout → place order → order received) — every screen looks designed and reads cleanly at every viewport
- [ ] Tab through the homepage with keyboard alone — every interactive element shows a visible focus ring at ≥ 3:1 contrast
