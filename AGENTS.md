# AGENTS.md — Fifty monorepo

This is the agent guide for the **Fifty monorepo**. Each theme inside this repo (`obel/`, `chonk/`, `selvedge/`, `lysholm/`, `aero/`, `foundry/`, plus any future variants you scaffold via `bin/clone.py`) has its own `AGENTS.md`, `INDEX.md`, and `readiness.json` with theme-specific rules and shipping state. Read this file first to understand the layout, then read the theme-specific `AGENTS.md` for the theme you are editing. If you're shipping a brand-new theme (not just editing an existing one), also read [`docs/shipping-a-theme.md`](docs/shipping-a-theme.md) and for N-at-a-time runs [`docs/batch-playbook.md`](docs/batch-playbook.md).

Agent voice and manner are defined separately in [`AGENT-PERSONA.md`](./AGENT-PERSONA.md): the agent operating in this repo is **Woo-drow**, a fussy Victorian shopdresser. That file governs how the agent speaks in chat (cadence, vocabulary, how it addresses the user as "the Proprietor"). This file (`AGENTS.md`) governs what it does. When they disagree — if cadence ever gets in the way of a rule — this file wins.

## Repo layout

```
fifty/
├── obel/                 # base theme (canonical reference) — editorial, soft, restrained
│   ├── AGENTS.md         ← read this when editing obel
│   ├── INDEX.md          # auto-generated surface map (bin/build-index.py)
│   ├── readiness.json    # shipping-stage manifest + gate claims (see below)
│   ├── theme.json
│   └── …
├── chonk/                # neo-brutalist variant
│   ├── AGENTS.md         ← read this when editing chonk
│   ├── INDEX.md
│   ├── readiness.json
│   └── …
├── selvedge/             # workwear / indigo variant
│   └── (same shape)
├── lysholm/              # Nordic home goods variant
│   └── (same shape)
├── aero/                 # Y2K iridescent / glass variant
│   └── (same shape)
├── foundry/              # editorial sibling of obel (warm cream, hairline)
│   └── (same shape)
├── bin/                  # shared CLI tooling (theme-aware)
├── playground/           # shared Playground PHP scaffolding + mu-plugins (read playground/AGENTS.md)
├── specs/                # canonical bin/design.py specs for every theme (checked-in JSON)
├── mockups/              # concept-queue source (1 PNG + 1 <slug>.meta.json per concept; read mockups/README.md)
├── tests/                # committed visual-baseline PNGs (read tests/visual-baseline/README.md)
├── docs/                 # generated GH Pages site + the tier-infra prose (shipping-a-theme.md, batch-playbook.md, blindspot-decisions.md, day-0-smoke.md, tier-3-deferrals.md)
├── .agents/skills/       # agent skills installed via `npx skills add …` (vendored copy; lockfile `skills-lock.json`)
├── .claude/skills/       # first-party skills (design-theme, build-block-theme-variant) + optional symlinks into `.agents/skills/`
├── .cursor/rules/        # Cursor-style per-area agent rules (.mdc)
├── README.md             # human-facing project intro
├── AGENTS.md             # you are here (rules, gotchas, tooling)
├── AGENT-PERSONA.md      # agent voice (Woo-drow) — how, not what
└── LICENSE
```

WordPress sees each theme via symlinks: `wp-content/themes/obel -> fifty/obel`, `wp-content/themes/chonk -> fifty/chonk`, etc. Edit the files inside `fifty/<theme>/` and the live site updates immediately.

## Hard rules (apply to every theme)

These are inherited by every theme in the monorepo. Per-theme `AGENTS.md` files may add more rules but never relax these.

1. **`theme.json` is the source of truth.** Every visible decision (color, spacing, type, shadow, radius, layout) lives there as a token. No raw hex codes, px, em, or rem in templates, parts, or patterns.
2. **No CSS files.** Only `style.css` (the WP-required theme header) is allowed. All styles go through `theme.json`'s `styles.blocks.*` and `styles.css`.
3. **No `!important`.** If you reach for it, the cascade is wrong; fix the cascade instead.
4. **Only modern blocks.** Only `core/*` and `woocommerce/*` blocks. No `core/freeform`, `core/html`, `core/shortcode`, no `[woocommerce_*]` shortcodes, no other shortcodes. Custom blocks are forbidden — if a built-in block can do it, use that.
5. **Nothing static.** Menus must be `core/navigation` blocks backed by real `wp_navigation` posts. Category lists must be `core/terms-query`. Product grids must be `woocommerce/product-collection`. No hardcoded link lists masquerading as menus, no hand-typed category tiles.
6. **Never render `wp:woocommerce/product-details`; use `core/details` for any WC override that needs collapsing.** `woocommerce/product-details` is the umbrella tabs block (Description / Additional Information / Reviews) with WC's hardcoded rounded "folder" markup — the single biggest "this is a default WooCommerce store" tell on a PDP. Baymard's UX research shows that tab-hidden content is ignored by 50%+ of users; every premium PDP we benchmark (Apple, Aesop, Glossier, Hermès, Lululemon) ships stacked sections or native `<details>` accordions instead. The canonical pattern in this monorepo: render the description always-visible via `wp:woocommerce/product-description`, then one `wp:details` (`core/details`) per collapsible section, with `wp:woocommerce/product-reviews` living inside one of them. `core/details` is a pure core block (WP 6.3+), zero JS, native keyboard / screen-reader / print / SEO behavior, and search engines index closed content. Theme each variant by setting `styles.blocks["core/details"]` in `theme.json` — block-scoped `css` is safe here because the only thing it competes with is the browser's user-agent stylesheet (no WC plugin CSS). `bin/check.py`'s `check_no_wc_tabs_block` enforces both halves: it fails if any template / part / pattern references `wp:woocommerce/product-details`, AND it fails if `theme.json` still has a stale `styles.blocks["woocommerce/product-details"]` entry. Secondary point — for any *other* WC surface you ever do have to override (cart form rows, `woocommerce/store-notices`, the legacy `.button` class), the WC override MUST live in top-level `styles.css`, not `styles.blocks.<x>.css`: WP processes block-scoped css through `WP_Theme_JSON::process_blocks_custom_css()`, which wraps every rule in `:root :where(<block-selector>) { ... }`. `:where()` has specificity zero, so the entire block.css string ends up at `(0,0,1)` — WC's `(0,4,3)` always wins. Top-level `styles.css` is emitted verbatim, so we can write the WC selectors with their natural specificity and win the cascade by load order (theme after plugin). `check_wc_overrides_styled` enforces this for any registered surface (currently empty — the tabs surface was retired by `check_no_wc_tabs_block`).
7. **Run `python3 bin/check.py <theme> --quick` before every commit.** It catches every mistake the other rules try to prevent.
8. **Every theme's homepage layout MUST be structurally distinct from every other theme's.** A variant is not done if its `templates/front-page.html` ships the same composition as obel (or any sibling) with only different colors / fonts / tokens. Real divergence means: different section count, different mix of dynamic surfaces (`woocommerce/product-collection` vs `terms-query` vs `query` vs `media-text` vs `cover`), different hero pattern, or a different ordering. The check `check_front_page_unique_layout` enforces this by comparing the ordered list of `<main>`'s direct children (block name + first className, or `pattern:slug` for `wp:pattern` references) across every theme — identical fingerprints fail. Other templates (`single-product.html`, `archive-product.html`, `cart`, `checkout`, etc.) are allowed and encouraged to stay structurally similar across themes because the shop function must remain coherent; the front page is the only template where uniqueness is enforced because it is the visual signature.
9. **Product (and ideally page/post) imagery MUST be real photographs, not placeholder illustrations.** The shared upstream `wonders-oddities` source ships flat cartoon PNGs (yellow-background mug silhouettes, lightning clouds, etc.) so the catalogue can boot before any per-theme art has been generated. Those cartoons are scaffolding, not the deliverable. Every theme MUST ship its own photographic `<theme>/playground/images/product-wo-<slug>.jpg` for every catalogue product, and the theme's `playground/content/products.csv` and `content.xml` MUST reference those JPGs (not the upstream `wonders-<slug>.png`). `bin/seed-playground-content.py` automates this — it copies the photos when the theme is seeded, rewrites every `wonders-<product-slug>.png` reference in CSV+XML to `product-wo-<slug>.jpg` when the photograph is present, and deletes the now-unused product cartoons. Page/post hero photographs (`wonders-page-*.png`, `wonders-post-*.png`) are still served from the upstream cartoons because per-theme photographic versions don't exist yet — generate them as a follow-up; the seeder's upgrade pass will pick them up automatically once a per-theme `product-wo-page-<slug>.jpg` / `product-wo-post-<slug>.jpg` (or equivalent photo naming) ships in the theme's images folder.
10. **No default WooCommerce strings on the live demo, AND every override ships with the theme.** A handful of WC's stock frontend strings are visually unmistakable "this is a free WooCommerce theme" tells: `"Showing 1-16 of 55 results"` (loop result count), `"Default sorting"` (catalog-sorting first option), `"Estimated total"` (cart totals label), `"Proceed to Checkout"` (order button), `"Lost your password?"` (account login link), and the screaming red `<abbr class="required">*</abbr>` after every required field. Every premium reference (Aesop, Glossier, Hermès, Lululemon) replaces these with brand-specific wording. The canonical pattern in this monorepo: every theme's `<theme>/functions.php` ships its own override block bracketed by `// === BEGIN wc microcopy ===` / `// === END wc microcopy ===` sentinels, written in that theme's voice and scoped to that theme's text domain. The block lives in the theme (not in any mu-plugin) so the overrides travel with the released theme — drop the directory into `wp-content/themes/` on a real install and the strings ship with it. `bin/check.py`'s `check_no_default_wc_strings` enforces presence: the sentinel block must exist AND each of the five canonical override fragments (`woocommerce_blocks_cart_totals_label`, `woocommerce_order_button_text`, `woocommerce_default_catalog_orderby_options`, `Lost your password?`, `render_block_woocommerce/product-results-count`) must survive between the sentinels. The companion `check_wc_microcopy_distinct_across_themes` enforces uniqueness: if two themes translate the same WC default to the same override, the gate fails (with a small `bin/wc_microcopy_universal.json` allowlist for genuine universals like `Total`, `Subtotal`, `Apply`, `Update`, single-word financial labels and case-variant duplicates). New WC strings that read as default-WC tells should be added to every theme's map AND to the `required` list in `check_no_default_wc_strings` so the regression is impossible to ship. NEVER hardcode the replacement strings in templates or PHP partials, NEVER move the overrides back into `playground/`, and NEVER share one map across themes — every variant must speak in its own voice (rule #14 already prohibits the same shopper-visible string in two themes; this rule extends it to the WC microcopy surface).
11. **Variation `<select>`s become swatches; never ship the bare native dropdown on a PDP, AND every theme owns its own per-brand swatches.** A `<select>` element on a PDP is the second-loudest "default WC theme" tell after the WC tabs block. Browsers render it with their OS-native chrome (chevron, focus ring, dropdown panel), and the cascade conflict between WC's `table.variations select.orderby` plugin rules and any theme reset is unwinnable without `appearance:none` plus a custom chevron — at which point you've reinvented half a swatch component anyway. The canonical pattern in this monorepo: every theme's `<theme>/functions.php` ships its own swatches block bracketed by `// === BEGIN swatches ===` / `// === END swatches ===` sentinels, which (a) defines a per-theme `<theme>_swatches_color_map()` so the palette stays on-brand even when the catalogue is shared, (b) registers `woocommerce_dropdown_variation_attribute_options_html` at prio 20 to delegate into a per-theme `<theme>_swatches_render_group()` callback that emits the button group (color circles for `Finish`, text pills for `Size` / `Intensity`), keeping the original `<select>` in the DOM but visually hidden (`.wo-swatch-select` clips it to 1×1px), and (c) inlines a `wp_footer` JS shim that syncs button clicks to `select.dispatchEvent(new Event('change', {bubbles:true}))` so WooCommerce's `variation_form` JS continues to drive price / stock / image swap. The block lives in the theme (not in any mu-plugin) so the swatches travel with the released theme: drop the directory into `wp-content/themes/` on a real install and the bespoke per-brand swatches ship with it. `bin/snap_config.py` `INSPECT_SELECTORS` for `product-variable` tracks both `.wo-swatch-wrap` AND `.wo-swatch-select` so a regression that drops either side fails the visual gate. The shared `playground/wo-swatches-mu.php` mu-plugin that this pattern replaced was deleted; re-introducing it (or any shared swatch-rendering filter inside `playground/`) is a hard fail per rule #17 — `check_no_brand_filters_in_playground` denies `woocommerce_dropdown_variation_attribute_options_html` registrations and the `wo-swatch` marker class in any `playground/*.php`. NEVER add a `<select>` to a PDP via theme markup, NEVER move the swatch render callback back into a shared playground mu-plugin, and NEVER share one color map across themes — every variant must paint its swatches in its own voice (rule #14 already prohibits the same shopper-visible string across themes; this rule extends it to the swatch-color surface).
12. **Single-product templates MUST always render a product image block.** A PDP that paints with no image (an empty cream-coloured box with a magnifying-glass overlay) is the loudest "this site is broken" tell on the entire demo. Two failure modes produce it: (a) `wp:woocommerce/product-image-gallery` depends on Flexslider + PhotoSwipe runtime wiring; on Playground (and on any fresh WC install where the gallery JS hasn't initialised yet) it sometimes fails silently, leaving the gallery's `opacity:0` start state in place; (b) the template author removed the image block thinking core/featured-image would be inherited from the underlying post (it isn't — `single-product.html` is rendered against a WC product post type that the page builder treats as opaque). The canonical pattern in this monorepo: render `wp:post-featured-image` on every theme's `single-product.html` (server-rendered `<img>`, zero JS dependency, plays well with `core/cover` ratios). `bin/check.py`'s `check_pdp_has_image` enforces this by failing the static gate if the template renders NONE of `wp:post-featured-image`, `wp:woocommerce/product-image-gallery`, `wp:woocommerce/product-image`, or `wp:woocommerce/product-gallery`, and warning (informational, not a fail) if the legacy `wp:woocommerce/product-image-gallery` is the only image block present. The defensive CSS rule in `bin/append-wc-overrides.py` (`/* wc-tells-phase-a-premium */ .woocommerce-product-gallery{opacity:1!important;}`) is the second line of defence — it makes the legacy gallery visible even if its JS never runs — but the template MUST have the block in the first place. NEVER ship a PDP without a product image block; the empty cream box is unrecoverable from CSS alone.
13. **Every Playground blueprint MUST ship its content payload alongside it.** A theme that has `<theme>/playground/blueprint.json` but no `<theme>/playground/content/content.xml`, no `<theme>/playground/content/products.csv`, and no `<theme>/playground/images/*` is unbootable on the live demo. The blueprint's WXR import step (`importWxr` against `https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/content/content.xml`) 404s on `raw.githubusercontent.com`; the failed XML import leaves WC's catalogue empty; every subsequent `wp eval-file` (`wo-import.php`, `wo-configure.php`, `wo-cart.php`, etc.) crashes because it tries to read products WC never imported; the user sees an unbroken stream of `PHP.run() failed with exit code 1` in the browser console and a blank page. The fail mode is invisible from a local checkout — the theme dir looks complete (it has `theme.json`, `templates/`, `parts/`, `patterns/`, `playground/blueprint.json`) and `bin/snap.py` mounts the local content via Playground's filesystem mount so it works locally too. The canonical fix the moment a theme is scaffolded (whether by `bin/clone.py`, by hand, or by the `build-block-theme-variant` skill) is `python3 bin/seed-playground-content.py --theme <slug>` (copies the canonical wonders-oddities CSV/WXR/images into `<theme>/playground/content/` and `<theme>/playground/images/` and rewrites every image URL to point at the per-theme folder), then `python3 bin/sync-playground.py` (re-inlines the mu-plugins into the blueprint), then commit `content/` + `images/` + the updated `blueprint.json` together. `bin/check.py`'s `check_playground_content_seeded` enforces both halves: it fails if `playground/blueprint.json` exists without `content/content.xml` + `content/products.csv` + a non-empty `images/` directory, AND it fails if the blueprint references any `raw.githubusercontent.com/.../playground/images/<file>` URL whose file is missing on disk (drift between blueprint and the seeded asset set). NEVER commit a `playground/blueprint.json` without first running the seed script for that theme; the demo will boot to a blank screen the moment GitHub raw catches up to the push.
14. **No two themes may ship the same user-visible string.** `bin/clone.py` copies obel verbatim into every new theme, including all paragraph body copy, button labels, list items, eyebrow strap text, footer copyright, FAQ questions, hero subtitles, order-confirmation step lists, 404 / no-results / coming-soon body copy, and PDP care + shipping policy paragraphs. Without a follow-up voice pass the new theme reads on a side-by-side demo browse as one shop in different paint jobs — the exact failure mode this monorepo exists to avoid. The canonical pattern: keep obel's wording as the baseline, then rewrite every other theme into its own brand voice using the per-theme substitution map in `bin/personalize-microcopy.py` (re-runnable, idempotent, refuses to start if any replacement would cascade). `bin/check.py`'s `check_all_rendered_text_distinct_across_themes` enforces this end-to-end: it scans every `*.html` and `*.php` file in `templates/`, `parts/`, and `patterns/`, extracts every block-delimiter `"content"` value, every inner-text run inside `<h1-6>/<p>/<li>/<button>/<a>/<figcaption>/<blockquote>`, and every PHP `__()/_e()/esc_html_e()/esc_html__()/esc_attr_e()/esc_attr__()` literal, normalises (lowercase, collapse whitespace, strip trailing punctuation, decode unicode + PHP escapes), drops anything < 12 chars or in the wayfinding allowlist, and fails on any normalised fragment that appears in another theme. When this fires either rewrite the offending fragment in this theme's voice (preferred) or extend `ALL_TEXT_ALLOWLIST` if the duplicate is truly system / wayfinding text. The companion `check_pattern_microcopy_distinct` covers the same-named-pattern case and word-overlap heuristic; both run in the gate.
15. **No fake forms. Email-capture / newsletter / "subscribe" UI MUST submit somewhere real or be deleted.** WordPress core ships zero working email-capture blocks: `core/search` submits `?s=…` to the home URL, `core/login` submits to `wp-login.php`, `core/comments` is per-post — that is the entire form-shaped surface area. So a "Subscribe" button that looks like an email field and is built out of `core/search` styled with an email placeholder, OR a `core/html` block containing a raw `<form action="/?my-fake-endpoint=1">`, is a dummy feature: a visitor who types their email in either gets a search-results page for their own address or a 404. That is worse than no signup at all because it sets an expectation the codebase cannot honor — hard rule #4 (only `core/*` and `woocommerce/*` blocks; no custom blocks, no third-party form plugins) makes integrating MailPoet / Jetpack Subscribe / ConvertKit a hard "no", which means a real email-capture surface is not buildable inside this codebase, full stop. The canonical replacement when a "newsletter" section is wanted: pick a real CTA whose link ACTUALLY DOES something — `woocommerce/customer-account` (logged-in icon + register/sign-in flow on `/my-account/`), an `<a>` to `/journal/`, an `<a>` to `/contact/`, a `core/social-links` cluster pointing at the brand's real off-site channels, or a featured `woocommerce/product-collection` linking to `/shop/`. Per-theme distinctiveness still applies (rule #14): five themes ≠ five identical "Read the journal →" buttons, so each theme's call-out should pick a different real action that fits its voice (chonk → categories grid, obel → account CTA, selvedge → journal CTA, lysholm → social cluster, aero → latest blog post via `core/query`). `bin/check.py`'s `check_no_fake_forms` enforces this in two passes: (a) it fails if `core/search` appears in any pattern / template / part outside the five legitimate search surfaces (`parts/header.html`, `parts/no-results.html`, `templates/search.html`, `templates/product-search-results.html`, `templates/404.html`), and (b) it scans every `core/html` block body for `<form>`, `<input type="email">`, or a Subscribe / Sign up / Notify-me button — any of those fails the check. NEVER ship a form-shaped UI element without a real submission target; if you cannot name the working endpoint, delete the section.

16. **Comments are part of the storefront. The shared `parts/comments.html` MUST render distinct avatars and visual separation between comments — never the gray-mystery-person silhouette gallery.** WordPress's default avatar (`mystery`) is a single flat gray silhouette; every commenter who lacks a Gravatar-resolvable email collapses to the same icon, and a multi-comment journal post paints a wall of identical placeholders that reads as "this site is broken / never seen real engagement". Compounding this, the demo WXR (`<theme>/playground/content/content.xml`) ships with `comment_author_email` empty for every named demo commenter (Jamie / Brenda Ash / L. Ortega / Percival Aftermath, etc.), so even switching `avatar_default` to `identicon` would still hash every author to the SAME identicon (the hash of the empty string). Two halves fix it and BOTH must ship together: (a) **The template-part** in `<theme>/parts/comments.html` MUST render exactly one section heading (`core/comments-title` at level 3 — never a hand-typed `<h3>Comments</h3>` followed by it), wrap each comment entry in a `wp:group` with class `wo-comment` carrying a 1px `border-top` token (`var:preset|color|border`) and vertical padding (`var:preset|spacing|lg`) so adjacent comments are visibly separated, and render the avatar via `wp:avatar` (size 48) on every theme so the identicon has somewhere to land. The class hooks (`wo-comment`, `wo-comment__avatar`, `wo-comment__byline`, `wo-comment__meta`, `wo-comment__name`, `wo-comment__date`, `wo-comment__body`, `wo-comment__actions`, `wo-comment__reply`, `wo-comment__edit`) are deliberately stable across every theme so a per-theme override in `theme.json`'s `styles.css` (or `styles.blocks["core/avatar"]`) restyles every comments surface in lockstep. (b) **`playground/wo-configure.php`** MUST set `update_option('show_avatars', '1')` and `update_option('avatar_default', 'identicon')` AND backfill every empty `comment_author_email` row with a stable per-author placeholder (`sanitize_title(comment_author) . '@example.invalid'` — `.invalid` is the IETF-reserved TLD per RFC 2606 so the addresses never resolve to a real mailbox, important because demo content is publicly cloned). Without the backfill every commenter still hashes to the empty-string identicon and the gallery degrades to one repeating pattern. The `journal-post` route in `bin/snap_config.py` (`/caring-for-your-portable-hole/`) intentionally points at the demo post with the largest comment thread so a regression in either half is visible in the next snap; whenever you touch the comments template-part or the wo-configure backfill, re-shoot that route at desktop AND mobile (root-rule #18 below) and read both PNGs before declaring done. NEVER hand-roll a second `<h3>Comments</h3>` inside the part, NEVER drop the `wo-comment` separator group (the WP default flush-stacked rendering is the failure mode this rule prevents), NEVER remove the `comment_author_email` backfill from `wo-configure.php` (the WXR will continue to ship empty emails for the foreseeable future), and NEVER re-introduce `avatar_default = mystery` "for consistency with stock WordPress" — distinct identicons ARE the consistency this storefront family wants.

17. **Shopper-facing brand lives in the theme, not in `playground/`.** Anything that affects what a real shopper sees on a released theme MUST live in the theme directory (`<theme>/functions.php`, templates, parts, patterns, `theme.json`, `styles/`, `style.css`). The `playground/` directory is for boot-time setup that has no analogue on a real WordPress install: WXR import, WC catalogue seeding, demo cart pre-fill. When a Proprietor downloads a theme and drops it into `wp-content/themes/`, none of `playground/` ships with it; anything brand-affecting hidden in a `playground/*.php` mu-plugin therefore evaporates on release, and the theme paints with WC defaults. `bin/check.py`'s `check_no_brand_filters_in_playground` enforces the boundary in two passes: (1) **Hook denylist** — it scans every `playground/*.php` for `add_filter` / `add_action` registrations against a denylist of shopper-visible hooks: the `gettext` family (`gettext`, `gettext_with_context`, `ngettext`, `ngettext_with_context`), the `render_block_woocommerce/*` and `woocommerce_blocks_*` prefixes, the WC display hooks (`woocommerce_form_field`, `woocommerce_default_catalog_orderby_options`, `woocommerce_catalog_orderby`, `woocommerce_pagination_args`, `woocommerce_show_page_title`, `woocommerce_order_button_text`, `woocommerce_order_button_html`), the WC pages hooks migrated out of the deleted `wo-pages-mu.php` (`woocommerce_before_customer_login_form`, `woocommerce_after_customer_login_form`, `woocommerce_cart_is_empty`, `woocommerce_no_products_found`, `woocommerce_before_main_content`), the variation-swatches hook migrated out of the deleted `wo-swatches-mu.php` (`woocommerce_dropdown_variation_attribute_options_html`), and the body-class slug filter (`body_class`); registrations are allowed only if guarded by `if ( defined( 'WO_DEMO_ONLY' ) )` (or any `defined('WO_*')` constant) within 200 chars upstream so a future genuine demo-only filter can opt out explicitly. (2) **Marker-class scanner** — even without a hook registration, any hardcoded reference to a per-theme paint marker (`wo-empty`, `wo-account-`, `wo-archive-hero`, `wo-swatch`, `wo-payment-icons`) inside `playground/*.php` would mean a mu-plugin runtime injection or a `wo-configure.php` HEREDOC is painting brand markup from outside the theme directory; those fail too. The scrubber strips `// …` and `/* … */` comments before either pass so HISTORICAL NOTE blocks that name a retired hook or marker are safe. Three corollaries that come up most often: (a) **WC microcopy belongs in `<theme>/functions.php`** between the `// === BEGIN wc microcopy ===` sentinels (see rule #10 for the full contract), NOT in a shared `playground/wo-microcopy-mu.php`; the previous mu-plugin was deleted as part of this boundary and re-introducing it is a hard fail. (b) **Variation swatches, payment-icons, login intro, empty-cart, no-products, archive hero, and the per-theme `theme-<slug>` body class belong in `<theme>/functions.php`** between the `// === BEGIN swatches / payment-icons / my-account / empty-states / archive-hero / body-class ===` sentinels (see rule #11 for swatches); the four shared mu-plugins that previously hosted these (`wo-swatches-mu.php`, `wo-payment-icons-mu.php`, `wo-pages-mu.php`, plus the older `wo-microcopy-mu.php`) were deleted and re-introducing any of them is a hard fail. (c) **Surfaces that have a block MUST be rewritten with `render_block_<block-name>` filters, not `woocommerce_before_shop_loop` / `woocommerce_after_shop_loop` / `woocommerce_no_products_found` HTML echoes** — those legacy actions fire BOTH in the historical `woocommerce_content()` loop AND inside `wp:woocommerce/product-collection`'s server render, so an echo paints the same HTML twice and the second copy lands floating in the middle of nowhere with no parent flex container (the "23 ITEMS off in the middle of nowhere" failure mode the gate now prevents). The canonical example lives in every theme's wc microcopy block: the result-count rewrite is wired through `render_block_woocommerce/product-results-count`, not `woocommerce_before_shop_loop`. NEVER move a brand-affecting filter into `playground/`, NEVER paint a `wo-*` marker class from `playground/*.php`, NEVER reach for a `woocommerce_*_shop_loop` echo when a `render_block_*` filter exists, and NEVER add a new check-bypass without first adding the failing case to the denylist.

18. **Every visual investigation MUST cover BOTH desktop AND mobile from the first look — never declare a UI bug "fixed" or "absent" from a single viewport.** Block themes inherit very different layouts on mobile (collapsed nav, single-column WC My Account, stacked product gallery, off-canvas drawer, `align: wide` collapsed to `align: full`) and on desktop (sidebar nav, floated WC layouts, multi-column grids, sticky cart panels, true `wideSize` containers), and a layout that looks correct on one routinely renders broken on the other. The reverse is just as common: an issue the user is reporting on desktop frequently looks completely fine on mobile (because mobile already collapses to a single column that happens to work), so a "looks fine to me" verdict from a single viewport is meaningless evidence. Two failure modes recur: (a) a desktop-only bug looks fine when the agent's interactive browser viewport happens to be narrow (the `cursor-ide-browser` MCP returns the *visible* viewport scaled to a small inline image, so a 514px-rendered crop of a 1280px page reads as "the mobile layout works" — it isn't the mobile layout, it's a scaled desktop layout misinterpreted as mobile, and the actual mobile layout was never observed), and (b) a mobile-only bug ships unnoticed because the agent only ran `bin/snap.py shoot <theme> --viewports desktop` (the production pipeline shoots both — `mobile` and `desktop` — but a `--viewports desktop` flag during debugging skips the very viewport where the bug lives). The canonical workflow whenever you're investigating, reproducing, or claiming-resolved any rendered-output issue: (1) snap the affected route at `mobile` (390x844) AND `desktop` (1280x800); (2) `Read` every PNG before drawing a conclusion; (3) when boot-testing live in `bin/snap.py serve`, drive the page through Playwright (or the `cursor-ide-browser` MCP via `browser_resize`) at BOTH widths, never the default — a `browser_take_screenshot` from the unsized MCP browser is reconnaissance, not evidence; (4) any ad-hoc Playwright probe / screenshot script written under `/tmp/` MUST iterate over both `mobile` and `desktop` viewports as a baseline (copy-paste the `VIEWPORTS = [("mobile", 390, 844), ("desktop", 1280, 800)]` shape — never just `[("desktop", 1280, 800)]`). The same rule applies to declarations of absence: "the issue isn't reproducing" is only true if BOTH viewports fail to reproduce. There's no automated check for this — it's a process rule because the failure mode is "agent looked at one screenshot and stopped looking" — but the per-cell artifacts under `tmp/snaps/<theme>/<viewport>/` make it cheap to honor: the default `bin/snap.py shoot <theme> --routes <route>` (no `--viewports` flag) already covers both, and `bin/snap.py report` surfaces per-viewport findings side-by-side. NEVER conclude a visual investigation from a single viewport, NEVER trust a `cursor-ide-browser` screenshot as a reliable rendering of any specific viewport without first calling `browser_resize` to the target width, NEVER ship an ad-hoc snap script that only shoots desktop, and NEVER report "fixed" without `Read`ing the mobile PNG too.

19. **`bin/check.py --all --offline` MUST pass on every commit, on every theme, no exceptions.** Two regressions made it to `main` because nothing automated ran the gate before the push: a Phase J refactor leaked `!important` past `check_no_important`, and a Phase K addition shipped the same leak under a new sentinel. The gate is fast (~3s × 5 themes ≈ 15s on a laptop) and has zero false positives — there is no real-world reason to commit past a red gate. Three layers enforce this and they stack rather than overlap because each one closes a different bypass: (a) `.githooks/pre-commit` runs the gate on every `git commit` and blocks the commit on any failure (this is the fast inner-loop signal); (b) `.githooks/pre-push` re-runs the gate AND a `bin/append-wc-overrides.py` drift check on every `git push` (this catches commits made with `git commit --no-verify`); (c) `.github/workflows/check.yml` runs the same gate server-side on every PR and every push to `main` (this is authoritative — no local bypass survives it). The local hooks only fire if `git config core.hooksPath` points at `.githooks/`; that's not on by default for a fresh clone, so the canonical bootstrap the moment you clone the repo (whether you're a human or a coding agent) is `python3 bin/install-hooks.py` — it sets `core.hooksPath`, fixes the executable bit on every hook, and smoke-tests the gate so you find out NOW if the working tree is already in a state that would block your next commit. The drift check piece matters as much as the static-analysis piece: `bin/append-wc-overrides.py` is sentinel-based, so a clean re-run is a no-op (every chunk reports `skip <sentinel>`); the moment the script's source diverges from the committed `theme.json` bytes, the script's next run reports `+<size> <sentinel>` and the pre-push gate blocks. NEVER edit `bin/append-wc-overrides.py` without re-running it AND committing the resulting `theme.json` diff in the same commit; NEVER `--no-verify` past a red gate; NEVER disable the GitHub Actions workflow.

20. **Long-running agent tasks MUST run inside a dedicated git worktree under `~/.cursor/worktrees/<task-slug>/` — never edit `bin/`, `.githooks/`, `.cursor/rules/`, or any framework file from the shared monorepo root while another agent task is in flight.** Two `bin/check.py` edits made by one agent during the closed-loop session were silently undone by a *parallel* agent's `git reset --hard` from the shared root, even though neither agent had any reason to know the other existed. The fix is workspace isolation: the moment a task is going to span more than one or two commits — anything that touches `bin/`, `.githooks/`, `.cursor/rules/`, `playground/`, or that needs to write `tmp/` artifacts the user will read across multiple turns — create a worktree with `python3 bin/agent-worktree.py new <slug>` and let the script run `git worktree add ~/.cursor/worktrees/<slug> -b agent/<slug>` and then call the `cursor-app-control` MCP's `move_agent_to_root` so the conversation auto-relocates into the worktree. Subsequent edits, snaps (`tmp/snaps/`, `tmp/playground-state/`, `tmp/dispatch-state.json`, `tmp/snap-server-<theme>.pid`), and commits all happen inside the worktree, isolated from `git reset --hard` blast radius elsewhere. When the task is done, `python3 bin/agent-worktree.py finish <slug>` opens a PR (via `gh pr create`) against `main` and offers to remove the worktree. Recurring traps the script handles for you: (a) a worktree shares the same `.git` object database as the main checkout, so `git push` from inside the worktree publishes the branch normally — no extra step beyond the move; (b) a worktree DOES NOT share `node_modules/` or any uncommitted state — re-run `npm install` (the pinned `@wp-playground/cli` from `package.json`) inside the worktree the first time you boot Playground there; (c) the `cursor-app-control` MCP refuses to move into a worktree whose branch is already checked out elsewhere — the script handles this by pre-creating a NEW branch (`agent/<slug>`) so the conflict can't arise; (d) the per-theme PID file (`tmp/snap-server-<theme>.pid` from rule #19's `bin/snap.py serve --persistent`) lives inside the worktree's `tmp/` so two agents running a warm server against the same theme in different worktrees use different ports and don't clash. The pre-commit hook gains a soft warning if `git rev-parse --show-toplevel` resolves to the shared root AND `git worktree list` shows any active `~/.cursor/worktrees/agent/*` branches — "you may be racing another agent; consider moving this task into a worktree." NEVER run a multi-commit task from the shared root if there's any chance another agent is also working there; NEVER edit `bin/` from outside a worktree if the task is going to span more than one turn.

## Bootstrapping a fresh clone

On the very first clone of this repo, run three commands in order. Each one is idempotent, so re-running them on a populated checkout is a no-op:

```bash
# 1. Install git hooks (pre-commit + pre-push) so `bin/check.py` runs
#    automatically before every commit and push. Without this the
#    local gate (layer a and b in rule #19) is inert.
python3 bin/install-hooks.py

# 2. Install the Python dev dependencies used by the tooling test
#    suite and the lint gate (pytest + ruff + mypy). No WP/theme
#    runtime deps — those live in the theme directories.
python3 -m pip install -r requirements-dev.txt

# 3. Install the Node dependencies for the editor-parity block
#    validator (bin/blocks-validator/check-blocks.mjs). Only needed
#    if you want to run `tests/validator/` locally; CI installs
#    them from the committed package-lock.json.
npm --prefix bin/blocks-validator ci
```

Once installed, four local commands together reproduce what CI runs:

```bash
python3 bin/check.py --all --offline    # theme-gate (same as CI)
python3 -m pytest tests/                # unit + integration + validator tests
python3 bin/lint.py                     # ruff + mypy + JS syntax check
python3 bin/snap.py check --changed     # visual regression (slow; optional)
```

**Maintainers only — set up `FIFTY_AUTO_PAT`.** The automation in
`.github/workflows/first-baseline.yml` and the rebaseline path in
`.github/workflows/visual.yml` auto-commits baselines into the PR
branch. Without a repo-scoped classic PAT stored as the
`FIFTY_AUTO_PAT` secret, those pushes are attributed to `GITHUB_TOKEN`
and GitHub intentionally suppresses the follow-up workflow runs that
would re-gate the PR — so the PR stalls at "baselines present but
un-gated". The workflows fall back to `GITHUB_TOKEN` when the secret
isn't set and print a loud `::warning::`, so no one silently stalls,
but close the loop once via [`docs/ci-pat-setup.md`](docs/ci-pat-setup.md).

If you're an agent operating in this repo and hooks aren't installed yet, stop and run `python3 bin/install-hooks.py` before your first `git commit`. See root-rule #19 for the full story.

## Working on a theme

```bash
# Pick the theme
cd fifty/obel       # or fifty/chonk

# Read its AGENTS.md and INDEX.md first
$EDITOR AGENTS.md INDEX.md

# Make your edits…

# Rebuild the index after structural changes
python3 ../bin/build-index.py

# Run checks
python3 ../bin/check.py --quick
```

You can also run from the monorepo root with explicit theme names:

```bash
cd fifty
python3 bin/check.py obel --quick
python3 bin/check.py chonk --quick
python3 bin/check.py --all --quick
python3 bin/build-index.py --all
```

When generating a whole theme from a spec/prompt, `bin/design.py` supports a two-step flow: `design.py build --spec <spec>.json` runs the deterministic structural phases and exits 0 when the theme renders correctly (even if product photos are still upstream cartoons); `design.py dress <slug>` then runs the content-fit phases (photos, microcopy, front-page restructure, vision-review at `--phase content`, `check --phase all`) and exits 0 only when every check is green. Both subcommands share every `--skip-*` flag with the flat CLI. See `.claude/skills/design-theme/SKILL.md` for the full two-step flow and when to prefer it over the one-shot `design.py --spec X`.

## Seeing what you built (visual snapshots)

You cannot load `playground.wordpress.net` from the in-app browser, and asking the user to ship screenshots back over chat is a broken loop. Use `bin/snap.py` instead. It boots the theme's WordPress Playground locally via `@wp-playground/cli` (same blueprint the live demos use, with the local theme dir mounted on top of the GitHub-installed copy so unsynced edits show up), captures Playwright PNGs **plus diagnostic artifacts** for every (route × viewport) cell, runs a JS heuristics pass (broken images, mid-word wraps, raw i18n tokens, PHP debug output, visible WC notices, web-font load state, tap-target sizes, ellipsis truncation, empty landmarks, placeholder images, responsive-image mismatches), and runs an axe-core a11y audit. Findings are bucketed into a tiered gate (`pass | warn | fail`) so the build can fail loudly when something genuinely broke.

```bash
# First time? Verify deps are ready before booting Playground.
python3 bin/snap.py doctor

# Just the page you're working on (fastest)
python3 bin/snap.py shoot chonk --routes checkout-filled --viewports desktop
# -> tmp/snaps/chonk/desktop/checkout-filled.png  (Read this)

# Full sweep for a theme
python3 bin/snap.py shoot chonk

# Smart sweep — only re-shoot themes whose files changed in git
python3 bin/snap.py shoot --changed
# -> falls back to all themes if bin/* changed (framework-wide)

# Whole monorepo (~10 routes × 2 viewports × 4 themes ≈ 80 PNGs)
python3 bin/snap.py shoot --all --concurrency 2

# Boot a single theme and leave it running so you can drive it interactively
# via the cursor-ide-browser MCP (auto-login enabled for /wp-admin/ access).
python3 bin/snap.py serve chonk
# -> http://localhost:9400/

# Aggregate the latest captures' findings into reviewable markdown
# (per-theme review.md + cross-theme rollup, sorted worst-first).
python3 bin/snap.py report
# -> tmp/snaps/<theme>/review.md   (per-theme, with GATE badge + inspector measurements)
# -> tmp/snaps/<theme>/review.json (machine-readable summary, includes gate)
# -> tmp/snaps/review.md           (cross-theme rollup table + parity drift)
# -> tmp/snaps/review.json         (machine-readable summary, includes overall gate)

# Did anything change vs the committed reference set?
python3 bin/snap.py diff --all
# Re-baseline after intentional changes:
python3 bin/snap.py baseline --all

# Rebuild every theme's admin-card screenshot.png from the fresh snaps
# (or from the baselines if you've just rebaselined). Without this, all
# five themes ship the SAME placeholder bytes — the WP admin Themes
# screen shows five identical cards labelled with five different names.
# `bin/check.py` runs `check_theme_screenshots_distinct` and FAILS when
# any two themes' screenshot.png have the same sha-256.
python3 bin/build-theme-screenshots.py            # all themes
python3 bin/build-theme-screenshots.py chonk      # one theme
```

Per-cell artifacts (all under `tmp/snaps/<theme>/<viewport>/<route>.*`):

| Artifact | What's in it |
|---|---|
| `*.png` | The screenshot. `Read` directly. |
| `*.html` | Final rendered DOM after JS settled. Useful for `Grep`-ing class names without re-shooting. |
| `*.findings.json` | DOM-heuristic + axe + budget findings, captured console messages, page errors, network failures (>=400 split into 4xx/5xx), and computed widths/displays/grid-template-columns for `INSPECT_SELECTORS`. The `report` subcommand reads these. |
| `*.a11y.json` | Raw axe-core report (violations only) for that cell. |
| `<route>.<flow>.png` etc. | Interactive cells produced by `INTERACTIONS` (e.g. `home.menu-open.png`, `cart-filled.line-remove.png`). |

### Desktop-first bug reproduction

When a user reports a visual bug ("the account page is broken", "checkout is too narrow", "the button is missing"), **reproduce it at a desktop or wider viewport first** (≥1280px). The embedded Cursor / in-app browser practically caps at ~800px, which is BELOW the `(min-width:782px)` media-query breakpoint that activates every WooCommerce two-column grid in the monorepo (cart items + sidebar, checkout form + order summary, account nav + content). A capture at 800px always shows the mobile-collapsed layout, so a desktop-only regression (layout collapse, narrow content column, missing button) is invisible to it — which is exactly how the 2026-04-22 Foundry `/my-account/` `.wo-account-login-grid` 228px-content-inside-1280px-viewport bug shipped to the live demo with a clean vision review and no automated gate complaints.

The canonical desktop-first reproduction loop:

```bash
# Re-snap just the route under suspicion at desktop (+ mobile if needed), fast.
python3 bin/snap.py shoot <theme> \
    --routes my-account,cart-filled,checkout-filled \
    --viewports desktop
# -> tmp/snaps/<theme>/desktop/<route>.png  (Read directly)
```

Rules:
* NEVER accept a screenshot captured in the embedded browser as evidence that a desktop bug is or isn't present. Re-shoot via `bin/snap.py`.
* The committed `tests/visual-baseline/<theme>/desktop/` PNGs are captured at 2560×… (2× DPR). Read them directly via `Read` to diagnose layouts without a re-shoot.
* `bin/_vision_lib.py` `build_system_prompt(include_functional_breakage=True)` explicitly reminds the vision reviewer of this policy for WC chrome routes at desktop (see `should_flag_functional_breakage`). Keep these in sync — if you add a new WC chrome route that must be checked for functional breakage at desktop, add it to `FUNCTIONAL_BREAKAGE_ROUTE_PREFIXES` so the vision pass and this rule agree.

### The tiered gate

Every cell's findings are classified into one of three buckets:

- **fail** (build-blocking, exit 1): heuristic `error`, uncaught JS (after noise filter), HTTP 5xx, axe critical/serious.
- **warn** (loud banner, exit 0): heuristic `warn`/`info`, HTTP 4xx, console errors, axe moderate/minor, parity drift, perf-budget exceedances, interaction-failed.
- **pass**: nothing flagged.

The verdict appears as a `STATUS: PASS | WARN | FAIL` line at the end of every `report` and `check` run. It also lives at the top of each per-theme `review.md` as a `**GATE: …**` badge so triage starts with the verdict, not the table.

### Content-correctness heuristics

On top of the broad page-level checks (`horizontal-overflow`, `placeholder-image`, `view-transition-name-collision`, etc.) `_HEURISTICS_JS` runs eight per-element invariants designed to catch the "looks bad at a glance" failure modes a pixel diff misses (text overflowing its container, the same nav link rendered twice, a cover-block whose background image 404'd, a 1200px hero that lost its content). All eight emit `error` severity by default and feed the same gate as everything else; the allowlist (next section) tames false positives so they ship without first fixing every existing offence.

| Kind | What it catches |
|---|---|
| `element-overflow-x` | A visible element whose `scrollWidth > clientWidth + 2` while computed `overflow-x: visible` (i.e. the overflow paints past the box). Skips `inline` display + opt-in scroll containers. |
| `heading-clipped-vertical` | A visible `h1`-`h4` whose `scrollHeight > clientHeight + 2` — typically a wrapping headline inside a parent with `max-height` + `overflow: hidden` eating the second line. |
| `button-label-overflow` | A `<button>`, `.wp-block-button__link`, `[role=button]`, or `input[type=submit/button]` whose label is wider than the button. Special-cased because button overflow is uniquely jarring (visible borders + backgrounds make the spill impossible to miss). |
| `duplicate-nav-block` | Two visible navigation containers whose link sets are nearly identical (Jaccard ≥ 0.8). Catches the real menu-mirror bugs: footer accidentally pulling the primary nav block, two `wp-navigation` blocks rendering the same `wp_navigation` post, mobile drawer + desktop nav both visible at the same viewport, or a footer "legal" row that literally repeats the same links as the help column above it. Ignores benign cross-references like a "Company" footer column linking to `/about/`, `/journal/`, `/contact/` (those are subsets of primary, not duplicates). |
| `duplicate-h1` | More than one visible `<h1>`, or two `<h1>`s with identical text. Catches templates rendering both site title and post title as `<h1>`, or hero patterns that hard-code an `<h1>` on a route that already has one. |
| `background-image-broken` | A computed `background-image: url(...)` whose URL `404`'d (or any `>=400`). Wired by intersecting the JS-collected `(selector, url)` pairs with the response listener's `network_failures` — no async JS needed. |
| `region-void` | A visible element occupying `>=15%` of the viewport area with NO text, NO `img/svg/video/picture/iframe/canvas` descendants, NO `background-image`, AND a `background-color` that matches the body's. The lysholm "transparent cover" regression generalised. |
| `region-low-density` (warn) | A region taller than 40% of viewport height whose `(text_chars + 50 * media_count) / area_kpx < 0.05`. Information-only — too easy to false-positive on legitimate hero compositions to ship as `error`. |

Each detector caps reports at 5 instances per page so a single structural bug doesn't drown the findings list. Every emitted finding carries a stable `selector` (and, for `duplicate-nav-block`, a `pair:<label_a>|<label_b>` `fingerprint` built from the two duplicate nav containers' aria-labels) so the allowlist can address it precisely.

### Cropped evidence per finding

`_capture_cell` follows up every finding that exposes a `selector` (or an `axe_first_selectors[0]`) with a small JPG screenshot of just that element padded ±20px, written next to the full-page PNG as `<route>.<kind>.<idx>.crop.jpg` and recorded as `crop_path` on the finding. `bin/snap.py report` links each finding's row to its crop in `review.md`; `bin/build-snap-gallery.py` renders the crops inline below the failing cell on the per-theme gallery page so a reviewer can see exactly which element fired which check without scrubbing through a 3000px-tall full-page screenshot.

Crops are best-effort: a flaky scroll, an axe selector Playwright can't parse, or an element that scrolled out of the viewport just yields no `crop_path` and no warning — the snap pipeline's job is to record what happened, not to fail because evidence capture had a bad moment.

### The heuristic-finding allowlist

`tests/visual-baseline/heuristics-allowlist.json` snapshots the set of `error`-tier heuristic findings that exist on the current shoot, so the new content-correctness checks can ship without first fixing every pre-existing violation. Going forward only NEW findings (anything not in the file) fail the gate. Same pattern Stylelint, ESLint, and Knip use for "fail on new violations only".

File shape:

```json
{
  "obel:desktop:home": {
    "element-overflow-x": ["nav.primary > ul > li:nth-of-type(3) > a"],
    "duplicate-nav-block": ["pair:Help|Footer legal"]
  },
  "chonk:mobile:cart-filled": {
    "button-label-overflow": ["button.wp-block-button__link"]
  }
}
```

Key shape: `<theme>:<viewport>:<route>` → `<kind>` → list of fingerprints (selectors for layout bugs; `pair:<label_a>|<label_b>` tuples for `duplicate-nav-block`; whatever the heuristic emitted as `fingerprint`). When a finding matches an allowlist entry it is **demoted to `info`** and tagged `allowlisted: true` — the original finding is still in the JSON artifact and still appears in `review.md` (with an `_(allowlisted; demoted to info)_` suffix), but it no longer counts toward the gate.

The matching pass runs in two places (defence-in-depth):
1. **`_capture_cell`** at shoot time, so each cell's recorded `error_count` and the gallery badges built from it reflect the post-allowlist gate.
2. **`cmd_report`** at report time, so re-running `bin/snap.py report` against an existing `findings.json` after editing the allowlist takes effect immediately (and so parity findings, which are spliced in only at report time, get filtered too).

#### Managing the allowlist

```bash
python3 bin/snap.py allowlist regenerate           # all themes (after a shoot)
python3 bin/snap.py allowlist regenerate --theme obel
python3 bin/snap.py allowlist diff                 # show pending changes; exits 1 on new findings
```

`regenerate` reads every `tmp/snaps/<theme>/<viewport>/<slug>.findings.json`, collects every `error`-tier finding with a stable fingerprint, and writes the canonical allowlist file. It **merges** rather than overwrites: cells/themes you didn't re-scan keep their existing entries, so a partial shoot doesn't accidentally drop allowlist entries for themes you didn't touch.

`diff` is the same scan but read-only — it prints any new findings (would fail the gate), any resolved ones (would shrink the allowlist), and exits non-zero when there are new findings, so CI / pre-push can plug it in as a check. Run this after any visual change to spot allowlist drift before it lands.

Re-run `regenerate` only when the team has consciously decided to accept a new batch of pre-existing offences. The default path is "fix the new finding, don't add it to the allowlist".

#### Static-check baseline allowlist (`tests/check-baseline-failures.json`)

`bin/check.py` has its own baseline allowlist for the same reason: main has always carried a small amount of latent debt (Foundry's 2.14:1 hover contrast, stray WC-override specificity losses) that was irrelevant to every unrelated PR but blocked them anyway, forcing agents into a `git commit --no-verify` habit that defeats the whole point of having a gate.

`tests/check-baseline-failures.json` lists `(theme, check-title)` pairs that fail on `origin/main`. When `FIFTY_ALLOW_BASELINE_FAILURES=1` (set automatically by `.githooks/pre-commit`, `.githooks/pre-push`, and the PR-side of `.github/workflows/check.yml`'s `theme-gate`), `bin/check.py` **demotes** matching failures from `FAIL` (exit 1) to `WARN-BASELINE` (printed in yellow, exit 0). New failures introduced by the branch — anything NOT in the JSON — still block normally. Push-to-main CI keeps the strict gate so the baseline can't silently grow.

File shape:

```json
{
  "recorded_against": "origin/main",
  "recorded_sha": "<40-char sha>",
  "recorded_at_utc": "2026-04-24T05:45:00Z",
  "failures": [
    {"theme": "foundry", "check": "Hover/focus states have legible text-vs-background contrast"},
    {"theme": "obel", "check": "WC override selectors win the cascade vs WC Blocks defaults"}
  ]
}
```

Managing it:

```bash
# Regenerate from the CURRENT tree (run this while checked out on
# a clean origin/main, or from a detached `git worktree` that is).
python3 bin/check.py --save-baseline-failures
```

Staleness is graceful:
- Stale additions (things already fixed on main but still listed) just produce extra permissiveness on the fixed checks. Harmless.
- Stale omissions (new failures on main that aren't listed yet) block unrelated PRs. Regenerate the file when this happens.

Re-generate whenever:
1. You add or remove a check title in `bin/check.py` (the allowlist matches on the exact `Result(...)` title string).
2. You land a fix on main that resolves a listed failure (optional — the stale entry just becomes a no-op).
3. You notice a new pre-existing failure on main is blocking unrelated work.

The JSON does NOT let agents hide *new* regressions introduced by the current branch. If the check title isn't already listed in the file — with the `recorded_sha` pointing at real main — the demote doesn't fire.

#### Allowlist vs `A11Y_SUPPRESSIONS`: when to use which

These are different tools for different problems and should not be conflated:

- **`A11Y_SUPPRESSIONS`** in `bin/snap_config.py` is for **broad** per-rule axe drops — "skip the `region` rule on every cell, because it fires on the WC mini-cart drawer that ships from upstream and we can't fix it." It silences a whole `(rule, route, selector_substring)` tuple regardless of how many nodes match.
- **`heuristics-allowlist.json`** is for **narrow** per-finding waivers — "this one specific selector on this one cell is a known exception we've decided to accept." It demotes one matched fingerprint at a time.

Reach for `A11Y_SUPPRESSIONS` when an axe rule is structurally unfixable in our themes (upstream WC markup, non-applicable rule). Reach for the heuristics allowlist when one specific element is a known false positive or an accepted technical debt that the team will revisit.

### Recommended loops

When you make ANY change that could affect rendered output (template, theme.json, CSS, pattern, blueprint), the loop is:

1. Make the change.
2. `python3 bin/snap.py shoot <theme> --routes <route>` — leave the `--viewports` flag OFF so both (`mobile`, `desktop`) are captured. Never pass `--viewports` with only one viewport (see root-rule #18). The same applies to ad-hoc Playwright probes you write under `/tmp/`: always iterate over `[("mobile", 390, 844), ("desktop", 1280, 800)]`.
3. `Read` every PNG (both viewports at minimum) before drawing a conclusion. A "looks fixed on desktop" verdict that hasn't `Read` the mobile PNG is not a verdict.
4. `python3 bin/snap.py report` and read the `STATUS:` line; drill into per-theme `review.md` if anything is non-pass.
5. If wider impact possible: `python3 bin/snap.py check --changed` (smart, fast) or `python3 bin/snap.py check` (full sweep before a release).
6. If diffs are intentional: `python3 bin/snap.py baseline --all` and commit the updated baselines alongside the change.

`bin/check.py --visual` is the single pre-commit gate. It runs `shoot + diff + report --strict`, returns 0 on `pass`/`warn` and 1 on `fail`. The default scope is `--visual-scope=changed` (only the themes whose files moved); pass `--visual-scope=all` for the full pre-release sweep, or `--visual-scope=quick` for a single-theme/quick-routes smoke test.

Other build-pipeline scripts grew matching `--snap` flags so the gate runs inline after a mutation:

- `python3 bin/clone.py <name> --snap` — auto-baseline a freshly-cloned theme.
- `python3 bin/sync-playground.py --snap` — re-shoot affected themes after blueprint sync.
- `python3 bin/append-wc-overrides.py --snap` — re-shoot after appending WC override CSS.

### Configuration

`bin/snap_config.py` is the single config file:

- **`ROUTES`** — every (slug, URL path) the framework visits. Add a route here and it appears in every theme's review.
- **`VIEWPORTS`** — Playwright viewport sizes (mobile / desktop). Same idea.
- **`INSPECT_SELECTORS`** — per-route map of CSS selectors whose computed width, height, display, and grid-template-columns get captured into `*.findings.json` and rendered into the per-theme `review.md` "Inspector measurements" tables. This is how the cart/checkout sidebar regression got diagnosed without re-shooting — add an entry here when you find yourself running ad-hoc Playwright probes to measure layout issues, so the next regression is visible immediately.
- **`INTERACTIONS`** — per-route list of scripted flows (`menu-open`, `qty-increment`, `swatch-pick`, `line-remove`, `field-focus`). Each flow renders an extra `<route>.<flow>.png` cell so the post-interaction state is reviewable side-by-side with the static one.
- **`KNOWN_NOISE_SUBSTRINGS`** — substring filter for pre-confirmed-harmless console / page errors. **Add to it only after investigation confirms upstream noise** — never to silence a real theme bug.
- **`BUDGETS`** — soft thresholds for `console_warning_count`, `page_weight_kb`, `image_count`, `request_count`. Exceedances become findings at the configured severity. Set `max: None` to disable a budget.
- **`QUICK_*`** — subsets used when `shoot` is invoked with `--quick`.

## Agent skills

This repo ships first-party agent skills under `.claude/skills/` so any LLM working in the codebase (Claude Code, Claude.ai with this repo attached, Cursor, etc.) can pick them up without any local install. Cursor users will also find a mirror at `~/.cursor/skills/` on the maintainer's machine; the in-repo copy under `.claude/skills/` is the source of truth for **Fifty-owned** skills.

**Miles (bymilesai)** — installed from [`bymilesai/skills`](https://github.com/bymilesai/skills) with `npx skills add bymilesai/skills -y` (from the repo root). Skill files live under `.agents/skills/miles/`; `.claude/skills/miles` is a symlink for hosts that read the Claude layout. Update or refresh with the same command; `skills-lock.json` records the resolved skill hash. **Precedence:** anything in this `AGENTS.md` (block-only themes, `theme.json` as source of truth, Playground seeding, WC microcopy/swatches boundaries, `bin/check.py` gates) overrides Miles when you are editing *this* monorepo. Use Miles for external site design via the Miles CLI (`miles create-site`, `miles reply`, etc.); use `design-theme` / `build-block-theme-variant` for shipping a Fifty variant.

**Miles → theme factory (optional):** Miles is the only creative authority on that path — Fifty does **not** call Claude/Anthropic to turn Miles notes into a spec. Export a validated **spec JSON** from Miles (same schema as `bin/design.py --spec`) into an artifact directory together with **`miles-ready.json`** containing `"site_ready": true` and a relative **`spec`** path (default `spec.json`). Validate and copy with `python3 bin/miles-bridge-to-spec.py --slug <slug> --name "<Display Name>" --artifacts-dir <dir> [--out tmp/specs/<slug>.json]`, then either `python3 bin/design.py --spec tmp/specs/<slug>.json` or in one step `python3 bin/design.py --miles-artifacts <dir> --miles-slug <slug> --miles-name "<Display Name>"` (mutually exclusive with `--spec` and `--prompt`). The `design.py` miles path runs **`miles whoami`** first (requires `.agents/skills/miles/scripts/miles-cli.mjs` and a logged-in CLI); set **`FIFTY_SKIP_MILES_GATE=1`** only for CI or workstations without Miles. Concept-queue specs stay on **`bin/concept-to-spec.py`** (mockup + seed); there is no Miles injection into that LLM prompt.

| Skill | Use when |
|---|---|
| `.claude/skills/design-theme/SKILL.md` | Shipping a brand-new theme *from a prompt* (no mockup yet). Owns the deterministic spine: prompt → `spec.json` → `bin/design.py` (clone + token swap + seed + sync + check). Short; hands off to `build-block-theme-variant` for the judgment-heavy passes. Pair with `docs/shipping-a-theme.md`. |
| `.claude/skills/build-block-theme-variant/SKILL.md` | Building a new visual variant of Obel *from a mockup or explicit visual reference*: mockup → tokens → templates → dynamic data → verification. Encodes the surface checklist, structural defect scan, WC-integration gotchas, and the hard rules (modern blocks only, nothing static, self-hosted Google Fonts only). |
| `.agents/skills/miles/SKILL.md` | User wants **Miles AI** for discovery, briefs, design directions, or builds *outside* the Fifty block-theme pipeline; user says “Miles” or “bymilesai”. Requires `miles login` / credentials under `~/.miles/` when calling the API. |

If you add a new **first-party** skill, drop it under `.claude/skills/<name>/SKILL.md` with the standard frontmatter (`name`, `description`) so every agent host can discover it. Third-party installs from `npx skills add` go under `.agents/skills/`; commit them (and `skills-lock.json`) when the team should share the same skill revision.

## Adding a new theme variant

Two skills cover this depending on what you have in hand:

- **Prompt only, no mockup** → `.claude/skills/design-theme/SKILL.md`. Drives `bin/design.py` end-to-end: prompt → `spec.json` (via `bin/concept-to-spec.py`) → clone → token swap → seed → sync → check. Fast path; one orchestrator pass produces a runnable theme.
- **Mockup or explicit visual reference** → `.claude/skills/build-block-theme-variant/SKILL.md`. Long-form judgment-heavy flow: mockup → tokens → templates → dynamic data → verification. Encodes the surface checklist, structural defect scan, WC-integration gotchas, and the hard rules (modern blocks only, nothing static, self-hosted Google Fonts only).

Either skill hands off to the same per-theme checklist in [`docs/shipping-a-theme.md`](docs/shipping-a-theme.md) for the final manual passes (microcopy, product imagery, front-page restructure), the promotion to `readiness.json.stage = "shipping"`, and PR-time gates. For N-at-a-time runs the wrapper is [`docs/batch-playbook.md`](docs/batch-playbook.md) (uses `bin/design-batch.py --from-concepts`).

The short version:

1. `python3 bin/clone.py <new_name>` — scaffolds `fifty/<new_name>/` from Obel, including `playground/blueprint.json`.
2. Edit `<new_name>/theme.json` (palette, fonts, layout sizes, shadows, radii).
3. Restructure templates and parts only when the design demands it; otherwise inherit Obel's defaults.
4. Seed real data (pages, navigations, categories) via WP CLI — never hardcode.
5. `ln -s fifty/<new_name> ../<new_name>` so WordPress sees it.
6. `wp theme activate <new_name>`
7. `python3 bin/build-index.py <new_name>`
8. `python3 bin/seed-playground-content.py` — populates the new theme's `playground/content/` (CSV + WXR + category-images map) and `playground/images/` (product / page / post / category artwork) from the canonical W&O source, rewriting every image URL to point at the new theme's own folder.
9. `python3 bin/sync-playground.py` — auto-discovers the new theme and re-inlines the shared helpers into its blueprint, prepending the per-theme constants and rewriting the importWxr URL.
10. `python3 bin/snap.py shoot <new_name> --routes home --viewports desktop` then `python3 bin/build-theme-screenshots.py <new_name>` — replaces `<new_name>/screenshot.png` (which `bin/clone.py` copied verbatim from Obel) with a real 1200x900 crop of the theme's own home page so the WP admin Themes card actually shows your theme. `bin/check.py` will fail until you do this.
11. `python3 bin/check.py <new_name>`
12. `python3 bin/build-redirects.py` — regenerates `docs/<new_name>/<page>/index.html` so the theme is reachable at `https://demo.regionallyfamous.com/<new_name>/` once the change is pushed and GH Pages picks it up. Re-run any time you add a theme or change the `PAGES` list inside the script. See "GitHub Pages short URLs" below.
13. Open the new theme's short URL (`https://demo.regionallyfamous.com/<new_name>/`, which redirects to the canonical `playground.wordpress.net/?blueprint-url=…` deeplink) and walk the surface checklist before declaring done. The blueprint AND the short-URL redirector are part of the deliverable — see "WordPress Playground blueprints" and "GitHub Pages short URLs" below.

## Readiness manifest and the tier infrastructure

Every theme ships a `<slug>/readiness.json` that declares its pipeline stage (`concept` → `design` → `shipping` → `retired`) and the boolean gate claims behind that stage (`boots`, `visual_baseline`, `microcopy_distinct`, `images_unique`, `vision_review_passed`). The three discovery sites — `bin/_lib.iter_themes`, `bin/snap.discover_themes`, `bin/append-wc-overrides.discover_themes` — filter on `stage`, so flipping a theme to `retired` drops it out of snap / gallery / check fan-outs without touching the source (this is the B.1 retirement decision in [`docs/blindspot-decisions.md`](docs/blindspot-decisions.md)). Lying in `readiness.json` is caught by `check_theme_readiness` in `bin/check.py`, which cross-checks the claimed gate booleans against the real artifacts (the dashboard would look foolish if a theme could self-declare `vision_review_passed` without the label). The live dashboard is rebuilt by `bin/build-theme-status.py` into `docs/themes/index.html` on every merge.

The pre-100-themes hardening plan (tiers 0 → 4) is what introduced the scripts and docs that make shipping at volume tractable. The tier prose lives in `docs/`:

| File | What's in it |
|---|---|
| [`docs/shipping-a-theme.md`](docs/shipping-a-theme.md) | Per-theme operator checklist (concept pick → spec → `bin/design.py` → boot smoke → manual passes → `check.py` → visual baseline → vision review → promote to `shipping` → open PR). Every gating step is called out. |
| [`docs/batch-playbook.md`](docs/batch-playbook.md) | N-themes-at-once wrapper around the same checklist, driven by `bin/design-batch.py --from-concepts`. Start here when shipping 5+ themes in one pass. |
| [`docs/day-0-smoke.md`](docs/day-0-smoke.md) | Honest per-phase timings from hand-shipping 3–5 themes through the pipeline. Used as the calibration baseline for every batch overrun. |
| [`docs/blindspot-decisions.md`](docs/blindspot-decisions.md) | Landed-on decisions for the six §B blind spots (retirement flow, image sourcing, microcopy voice bank, baseline decay, uniqueness cache invalidation, vision-review spend). Updated in place, not appended — always reads as the current stance. |
| [`docs/tier-3-deferrals.md`](docs/tier-3-deferrals.md) | What was intentionally NOT shipped yet and under what trigger to build it. "Infrastructure without evidence is waste." |

Key shared scripts introduced by the tier work (all run from the repo root):

| Script | Use when |
|---|---|
| `bin/concept-to-spec.py <slug>` | Generate a `bin/design.py` spec from a concept seed + mockup. Default is LLM-assisted; `--no-llm` is a deterministic fallback. Output lands at `tmp/specs/<slug>.json`. |
| `bin/miles-bridge-to-spec.py` | Validate a Miles-exported spec JSON (`miles-ready.json` + spec file), check `--slug` / `--name` match, write `tmp/specs/<slug>.json`. No LLM. `--dry-run` writes `example_spec()` for tests (no `--artifacts-dir`). |
| `bin/design.py tmp/specs/<slug>.json` | Clone Obel, apply palette + typography tokens, seed products, sync patterns, run first snap + check pass. Idempotent. |
| `bin/design.py --miles-artifacts DIR --miles-slug SLUG --miles-name "…"` | Runs the bridge then the same pipeline as `--spec` (mutually exclusive with `--spec` / `--prompt`). |
| `bin/design-batch.py --from-concepts` | Wrap the single-theme flow for 5–20 concepts in one run, with logging + recovery. |
| `bin/snap.py boot <slug>` | Fast (~30s) boot smoke: catches PHP fatals + broken templates. Runs in `.githooks/pre-push` (with 3-attempt retry to tolerate transient Playground download flakes) and as the first step of `check.yml`. Moved out of `.githooks/pre-commit` in April 2026 — the cold-cache cost (~2-3 min/theme) made the pre-commit loop unusable for PHP-touching diffs and the transient-flake rate pushed agents toward reflex `--no-verify`. |
| `bin/verify-theme.py <slug> --strict` | Reproduces CI's theme gate locally against a pushed branch. Reports `branch-ready` / `static-check` / `snap-shoot` / `evidence-check` phases as JSON or markdown. `bin/design-batch.py` runs this automatically after pushing each theme branch and embeds the verdict in the PR body so the batch report shows red/green before CI even starts. |
| `bin/visual-matrix.py` | Detects brand-new themes on a PR (used by the vision-review gate in `check.yml`). |
| `bin/build-theme-status.py` | Rebuilds `docs/themes/index.html` (the shipping dashboard) from every theme's `readiness.json`. |
| `bin/audit-concepts.py` | Cross-checks `mockups/` against `bin/concept_seed.py::CONCEPTS` and the GH Pages concept queue. |
| `bin/check-concept-similarity.py` | Flags near-duplicate concepts via the `bin/concept-similarity-allowlist.json` allowlist (same pattern as the heuristics allowlist). |
| `bin/build-concept-meta.py` | Builds `<slug>.meta.json` sidecars for every concept from the concept seed. |

Baseline allowlists that the tier work introduced (defence-in-depth against pre-existing debt blocking unrelated PRs):

- **`tests/check-baseline-failures.json`** — `bin/check.py` failures that pre-exist on `origin/main`; demoted to `WARN-BASELINE` on branch CI via `FIFTY_ALLOW_BASELINE_FAILURES=1` (the env is set automatically by the hooks and the PR-side of `check.yml`). Push-to-main CI keeps the strict gate. Regenerate with `python3 bin/check.py --save-baseline-failures`.
- **`tests/visual-baseline/heuristics-allowlist.json`** — `bin/snap.py`'s `error`-tier heuristic-finding allowlist. Same pattern Stylelint / ESLint / Knip use.
- **`bin/concept-similarity-allowlist.json`** — human-approved concept pairs that the similarity check would otherwise flag.

None of these are to-do lists — they're safety nets. The default path is always "fix the new finding, don't add it to the allowlist."

## Concept queue mockups (the public bench)

Concepts on the bench at <https://demo.regionallyfamous.com/concepts/> are tracked in `mockups/`, one PNG + one `<slug>.meta.json` per concept. **Every concept mockup MUST be a two-view composition: home page on the LEFT, shop / category grid on the RIGHT, shown as two desktop browser windows side-by-side on a neutral backdrop.** The Bauhaus mockup (`mockups/mockup-bauhaus.png`) is the canonical reference — match its STRUCTURE (two windows, full chrome on each, identical brand mark + nav across both) when generating any new concept, even though the brand voice (palette, typography, era) will differ. Output dimensions are fixed at **1376x768 pixels** so every queue card lays out at the same aspect ratio. Never hand-write a custom prompt for image generation — derive it from the concept's metadata via `python3 bin/paint-mockup.py <slug>`, which emits the canonical two-view prompt with the concept's `palette_hex` + `type_specimen` + tags interpolated. See [`mockups/README.md`](mockups/README.md) for the full workflow (concept_seed → build-concept-meta → paint-mockup → image generation → re-extract palette → audit-concepts → build-redirects → commit).

## WordPress Playground blueprints

**Every theme in this monorepo MUST ship a working Playground blueprint and a self-contained per-theme content set.** This is part of the deliverable, not an extra. A theme without a working blueprint is incomplete — there's no other way for a reviewer to load it without a full local WP + WC install.

The expected layout:

```
fifty/
├── playground/                          # SHARED — scaffolding only, no content
│   ├── AGENTS.md                        # full contract — read it before editing here
│   ├── wo-import.php                    # generic WC importer (reads URLs from WO_CONTENT_BASE_URL)
│   ├── wo-configure.php                 # generic WP/WC configurator (reads URLs from WO_CONTENT_BASE_URL)
│   └── wo-cart-mu.php                   # ?demo=cart pre-filler mu-plugin
├── obel/playground/                     # PER-THEME — content + assets + blueprint
│   ├── blueprint.json                   # auto-synced
│   ├── content/
│   │   ├── products.csv                 # WC catalogue for THIS theme
│   │   ├── content.xml                  # WXR (pages, posts, blog) for THIS theme
│   │   └── category-images.json         # cat-name → image filename map
│   └── images/                          # every binary attachment THIS theme references
│       ├── *.{png,jpg,…}                # products / pages / posts / category covers
│       └── *.{pdf,wav,…}                # downloadable attachments referenced from CSV/XML
├── chonk/playground/                    # same shape, with chonk-styled imagery
└── <new-theme>/playground/              # same shape, seeded by bin/seed-playground-content.py
```

The per-theme `content/` files are the **canonical source for that theme** after the initial seed. Each theme is free to diverge: rewrite product copy, swap SKUs, replace pages, drop different artwork into `images/`. The shared `playground/wo-*.php` scripts must stay theme-agnostic — they receive theme-specific values through three constants (`WO_THEME_NAME`, `WO_THEME_SLUG`, `WO_CONTENT_BASE_URL`) which `bin/sync-playground.py` prepends when it inlines the script body into each theme's blueprint.

How a new theme gets a working blueprint (the only correct path):

1. `python3 bin/clone.py <new_name>` — copies obel including `playground/blueprint.json`, and rewrites `obel`→`<new_name>` and `Obel`→`<New_name>` in the editable files (the JSON included). The blueprint's `installTheme.path`, `installTheme.options.targetFolderName`, and `setSiteOptions.blogname` are rewritten automatically.
2. `python3 bin/seed-playground-content.py` — auto-discovers themes that don't yet have `playground/content/` and seeds CSV + WXR + `category-images.json` + every image / PDF / audio attachment, rewriting image URLs in the CSV/XML to point at the new theme's own `images/` folder. Idempotent; safe to re-run.
3. `python3 bin/sync-playground.py` — auto-discovers every theme via `_lib.iter_themes()` and re-inlines the latest `playground/*.php` bodies into each blueprint, prepending the per-theme constants block (deriving `WO_THEME_NAME` from each theme's `theme.json` `title` and composing `WO_CONTENT_BASE_URL` from the theme slug) and rewriting the `importWxr` step's URL to point at the per-theme `content.xml`. There is no hardcoded theme list to update.
4. Open the resulting deeplink in Playground (`https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/<org>/<repo>/main/<new_name>/playground/blueprint.json`) once and click through the surface checklist (front page, shop, single product, cart, checkout, blog post, 404). If anything 404s or renders unstyled, the blueprint is not done.

**The shared helpers are inlined into every blueprint**, not fetched at boot. Don't change the `writeFile` steps to use a `{ resource: url }` data field — Playground caches URL resources aggressively (and `raw.githubusercontent.com` ships `cache-control: max-age=300`), so a freshly-pushed script change can take 5+ minutes to propagate and Playground will run the previous version against the new blueprint. Inlining puts the script body in the same payload as the blueprint, so there is one URL to invalidate, not two.

After editing any of `playground/wo-import.php`, `playground/wo-configure.php`, or `playground/wo-cart-mu.php`:

```bash
python3 bin/sync-playground.py   # re-inlines into every theme's blueprint
```

After editing any per-theme `<theme>/playground/content/` file or replacing artwork in `<theme>/playground/images/`, no re-sync is needed — those URLs are fetched live by the blueprint and importer at boot.

Commit the resulting `*/playground/blueprint.json` changes alongside the source-file change. `bin/check.py` does not (yet) enforce that the blueprints are in sync — keep them in sync by running `sync-playground.py` before every commit that touches `playground/`.

### Default landing page

Every blueprint MUST set `"landingPage": "/"`. Reasons:

- The `docs/<theme>/index.html` redirector built by `bin/build-redirects.py` sends visitors to `…&url=/` (PAGES[0] in `bin/_lib.py`). Keep the blueprint's standalone default aligned with the homepage card on `demo.regionallyfamous.com` so they tell the same story.
- WP's stock default (no `show_on_front=page`) is "Your latest posts" — for a storefront that's empty / wrong. WC 8.4's "Coming soon" mode (already disabled in `wo-configure.php`) would otherwise pin the default landing to `/shop/`, which is the second-worst option.
- The seeded `home` page exists precisely so the blueprint can show a designed homepage on first paint. `wo-configure.php`'s `runPHP` block sets `show_on_front=page` and `page_on_front` to that page; `landingPage: "/"` is what makes `/` actually resolve to it on first load.

`bin/check.py` enforces this via `check_blueprint_landing_page` — any drift fails the check before push.

### Shop archive header

The shop archive header is the most-judged surface in any WooCommerce theme review — it's the first page visitors land on after clicking "Shop", and it's where default-WooCommerce tells stack up fastest. Two non-negotiables:

1. **The catalog-sorting `<select>` MUST have a themed appearance.** `wp:woocommerce/catalog-sorting` renders a bare `<select class="orderby">` with zero theme styling. Browsers paint OS-native dropdown chrome (chevron + border + focus ring), which fights every adjacent typographic element and screams "default WooCommerce" louder than any other single element on the page. Override it in **top-level `styles.css`** (NOT block-scoped — see `check_wc_overrides_styled` for the specificity story), targeting both `.wp-block-woocommerce-catalog-sorting select.orderby` and `.woocommerce-ordering select.orderby` (the legacy shortcode-rendered form), starting with `appearance:none;-webkit-appearance:none;-moz-appearance:none` to strip the UA chrome. Re-paint everything from scratch in the theme's voice (border, padding, custom chevron via background-image, focus state).
2. **Don't dump the result count + sort dropdown into a single double-bordered bar.** Default WC themes wrap them in a top+bottom `1px` border that reads as a generic plugin echo. Move the result count up beside the page title (`flex space-between`, `verticalAlignment:bottom`) so they share an editorial line, and let the sort dropdown sit in its own slim row above the products with a single hairline `border-bottom`. The whole header should look composed, not stitched-together.

`bin/check.py` enforces (1) via `check_archive_sort_dropdown_styled` — any archive template that renders `wp:woocommerce/catalog-sorting` without the matching top-level `styles.css` rule fails the check before push. (2) is taste-driven and not auto-checked, but every archive in the monorepo follows the same pattern; deviate from it deliberately.

### WooCommerce panel surfaces ("card" rule)

The cart sidebar, checkout sidebar, mini-cart drawer, and order-summary panel are *card surfaces* — opaque blocks that hold dense compound content (subtotals, taxes, totals, coupon input, primary CTA). The moment we paint them with a non-transparent `background:` they READ as a panel, and they need to feel like proper panels — not tight boxes the plugin echoed onto the page.

- **The default `padding: lg` (≈24-40px depending on viewport) is too small.** It's fine for type-only blocks, but on a totals card with a price column on the right and a checkout button on the bottom it visibly cramps the content against the edge. Use `xl` or larger (`2-xl`/`3-xl` are also fine) for any WC card surface that owns its own background. The hard floor is `xl`.
- **Card chrome MUST live in top-level `styles.css`.** Block-scoped CSS in `styles.blocks["woocommerce/cart-totals-block"].css` gets wrapped in `:root :where(...)` (specificity 0,0,1) and silently loses to WC's own padding declarations on the wrapper. Only top-level rules are emitted verbatim and reliably win the cascade. Same story as `check_wc_overrides_styled` and `check_archive_sort_dropdown_styled`.
- **Card chrome is a place to express the theme's voice, not boilerplate.** A brutalist theme should have a thick contrast border + flat box shadow on the cart sidebar, a Nordic theme should have soft warm subtle, a dark editorial theme should have a thin hairline border, and so on. If two themes are shipping byte-identical card chrome, one of them isn't doing its job.

`bin/check.py` enforces the padding floor via `check_wc_card_surfaces_padded` — any WC card surface (cart sidebar, checkout sidebar, mini-cart drawer modal, etc.) that gets a `background:` in top-level `styles.css` but uses padding below `xl` fails the check before push. The list of recognised surfaces lives at the top of the check; add new entries as new card surfaces get reskinned.

- **The inner totals block is *also* a card surface — and it has no background of its own.** In current WooCommerce blocks (9.x+) `.wp-block-woocommerce-cart-totals-block` and `.wp-block-woocommerce-checkout-totals-block` render at width:100% inside the sidebar wrapper. On themes where the wrapper is unpainted (or painted the same color as the page background — e.g. Selvedge's dark `--base` ≈ `--surface`), the totals block IS the visible "Order summary" card a shopper sees. Phase C's `::before` pseudo-label "Order summary" lives directly on those selectors; without padding on the totals block itself, the label sits flush at the panel's left edge and the whole stack reads edge-to-edge. **Phase H** (`bin/append-wc-overrides.py::CSS_PHASE_H`) emits an unconditional `padding: var(--wp--preset--spacing--xl); box-sizing: border-box;` on both totals blocks — theme-agnostic plumbing, separate from per-theme voice (Phase G). The companion check **`check_wc_totals_blocks_padded`** enforces this floor independently of background paint, because in modern WC these blocks are *always* the visible card on at least some themes.

### Form-input chrome on dark themes (the "Selvedge checkout was unreadable" footgun)

WooCommerce checkout/account blocks ship their own `.wc-block-components-text-input`, `.wc-block-components-select`, and `.wc-block-components-textarea` chrome that hardcodes a **white wrapper background** and inherits the ambient page `color` for the floating label. On a light-base theme this looks fine — the page color is dark, so the floating label renders dark-on-white. On a **dark-base theme like Selvedge** (where the page inherits `color: var(--wp--preset--color--contrast)` = cream), every checkout `<label>` ends up cream-on-white at ~1.27:1 contrast. The entire form goes invisible; axe flags it across `label[for="email"]`, `label[for="shipping-first_name"]`, etc.

This is exactly the kind of regression that's invisible during light-theme development and only surfaces when a dark theme is added later. **Phase I** (`bin/append-wc-overrides.py::CSS_PHASE_I`, sentinel `wc-tells-phase-i-form-input-chrome`) closes the gap. It paints the wrapper **and** the input/select/textarea with `--surface` and forces the input text to `--contrast`, so the floating label sits over a theme-aware background instead of WC's hardcoded white. Floating labels are forced to `--secondary`, which has ≥4.5:1 contrast against `--surface` in every palette in this monorepo (mid-gray on light themes, warm-tan on dark themes — both legible). Placeholder text gets the same treatment with `opacity: 1` so the placeholder doesn't fade further.

**Why `body` prefix on every selector and not `!important`:** WC ships its rules at specificity ~`(0,0,2)` (e.g. `.wc-block-components-text-input input`). A bare top-level rule at the same specificity loses or wins based on source order, and WC's stylesheet is enqueued *after* theme.json's inline `styles.css` in many setups. Adding `body` bumps us to `(0,1,2)` — just enough to win without an `!important` cascade fight. We deliberately keep this *out* of `IMPORTANT_ALLOWED_SENTINELS` so per-theme voice rules (Phase E, Phase G) can still reskin form inputs without crashing into a `!important` wall.

If a future theme adds a *third* base/surface tone — e.g. a "high-contrast warm" with cream surface but coffee-brown labels — verify the `--secondary`-on-`--surface` contrast there too. The check infrastructure could be extended to run a contrast check on the resolved Phase I outputs in a follow-up; for now the ratio is verified by snapshotting `checkout-filled` + `checkout-filled.field-focus` in `bin/snap.py shoot` and reading the resulting `*.a11y.json` for `color-contrast` violations on `label[for=...]`.

### Hover/focus states must stay legible (the "accent-on-base" footgun)

A theme can pass every other check and still ship a hover state that paints text in a color with ~1:1 contrast against the background it lands on. Two patterns cause it; both are subtle because they only manifest *after* the palette interacts with the rule. The rule looks fine in isolation; the rendered result is invisible.

- **Pattern 1 — `:hover { color: var(--accent); }` on a theme whose accent collapses against `--base`.** Chonk's `--accent` is `#FFE600` and `--base` is `#F5F1E8`; that's **1.12:1** of contrast. Lysholm's `--accent` is `#C9A97C` against base `#F7F5F1` is **2.04:1**. Both fail WCAG AA-Large badly. The same rule that's perfectly readable on Selvedge (orange accent on dark base, ~4.9:1) renders the link text unreadable on the cream-base themes. Don't use `--accent` as a text color in a hover state unless the theme's accent has ≥3:1 contrast with `--base`. Signal hover with a non-color shift instead — `text-decoration: underline` paired with `text-decoration-color: var(--accent)` and a thick `text-decoration-thickness` keeps the accent as the visual cue without making the text invisible.
- **Pattern 2 — `:hover { background: var(--accent); }` on a button whose resting state is `color: var(--base)`.** This is the `.button:hover` family in the WC override boilerplate. The hover paints a yellow/orange surface but never declares its own `color:`, so the button keeps its resting cream text — cream-on-yellow at 1.12:1, cream-on-tan at 2.04:1. Whenever a hover/focus state changes the background, **declare `color: var(--contrast)` explicitly in the same rule** to flip the text to the dark token. Don't rely on inheritance — the resting `color: var(--base)` declared on the button itself wins over body inheritance.

`bin/check.py` enforces both patterns via `check_hover_state_legibility`. For every `:hover` / `:focus` / `:focus-visible` / `:active` rule in top-level `styles.css`, it resolves the effective text color (the rule's own `color:` declaration if present; otherwise the resting state's `color:` declaration on the same exact selector; otherwise `--contrast`) and the effective background color (the rule's own `background:` if present; otherwise `--base`), looks both up in the theme's palette, and computes the WCAG 2.x contrast ratio. Anything below **3.0:1** (the AA-Large floor — relaxed for state changes since they're transient) fails with the offending selector and the resolved color tuple printed in the log. The check sits next to `check_wc_card_surfaces_padded` in the runner and catches palette/rule interactions that would otherwise only surface in browser review.

### Nothing is "standard" — every theme must spin its own visible chrome

The fastest way to make a WooCommerce demo read as off-the-shelf is to ship byte-identical chrome across themes. The cart sidebar, the checkout sidebar, the trust-strip pills, the primary CTA, the sale badge — these are exactly the surfaces a shopper looks at to answer "does this brand have its own taste?" If chonk and obel render the payment-icon row with byte-identical white pills, both themes lose the answer. "It's the same code, just different colors and fonts" is the failure mode a real designer notices in five seconds; it's also the reason customers describe stock-WooCommerce sites as cheap.

The rule is **not** "no shared CSS rules anywhere." Utility and structural plumbing — `min-width:0` overflow fixes, screen-reader visually-hidden helpers, layout grids, `overflow-wrap:break-word` typography fixes — SHOULD be byte-identical across themes; that's not chrome, that's plumbing, and per-theme variation there means somebody forgot to backport a fix. The rule is scoped to a curated list of "premium chrome" selectors that live in `bin/check.py` as `DISTINCT_CHROME_SELECTORS`.

A theme can earn a unique treatment two ways:

1. **Author a different base rule body** for the selector in its own `styles.css` / `styles.blocks` — chonk just writes a different rule than obel does and the check passes.
2. **Share the base rule but add a per-theme `body.theme-<slug> <selector>` override** in `bin/append-wc-overrides.py` Phase E/F/G. Phase E houses the original distinctive treatments (primary CTA, sale badge, etc.); Phase F houses the payment-pill voices; Phase G houses the cart/checkout card-surface voices. Add a new phase whenever a new chrome surface needs per-theme variants — the sentinel-comment pattern keeps the chunks idempotent so re-runs are no-ops.

`bin/check.py` enforces this via `check_distinctive_chrome`. It loads every shipped theme's top-level `styles.css`, extracts the base rule body for each entry in `DISTINCT_CHROME_SELECTORS`, groups themes by byte-identical body, and fails any cluster of 2+ themes that share a body without a `body.theme-<slug>` override on each. Add a selector to `DISTINCT_CHROME_SELECTORS` whenever a new premium-chrome surface ships — the list is curated on purpose so structural plumbing isn't dragged in.

### Permalinks gotcha (the one footgun that will burn you)

In a `wp eval-file` context (which is how `wo-configure.php` runs), the global `$wp_rewrite` was constructed at WP boot from the previous (default = empty) `permalink_structure` option. Calling

```php
update_option( 'permalink_structure', '/%postname%/' );
flush_rewrite_rules( true );
```

**does not work** — the flush regenerates `rewrite_rules` from the stale in-memory `$wp_rewrite->permalink_structure`, producing rules for the default URL scheme. Every pretty post / page / product URL then 404s inside Playground.

The correct pattern (already in `wo-configure.php`) is:

```php
global $wp_rewrite;
$wp_rewrite->set_permalink_structure( '/%postname%/' );
$wp_rewrite->set_category_base( '' );
$wp_rewrite->set_tag_base( '' );
$wp_rewrite->flush_rules( true );
delete_option( 'rewrite_rules' );  // belt + suspenders for lazy rebuild
```

Don't regress this. If you find yourself "simplifying" the permalink section back to `update_option` + `flush_rewrite_rules`, you are reintroducing the bug.

The script must be type-aware when calling WC product setters:

- `WC_Product_External` and `WC_Product_Grouped` reject `set_manage_stock()` / `set_stock_quantity()` / `set_weight()` / `set_length()` / `set_width()` / `set_height()` with `WC_Data_Exception`.
- `WC_Product_Grouped` also rejects `set_regular_price()` / `set_sale_price()` (price comes from children).
- `WC_Product_External` exposes `set_product_url()` and `set_button_text()`.

Wrap the entire per-row loop body in a single `try { … } catch ( Exception $e )` so one bad product can't kill the whole import.

Use only WC's stable public CRUD surface (`WC_Product_*`, `set_*`, `wc_get_product_id_by_sku`, `wp_insert_term`, `get_term_by`). Do **not** call `WC_Product_CSV_Importer` or `WC_Product_CSV_Importer_Controller` directly — both have unstable signatures (visibility/static modifiers have flipped multiple times across releases) and the importer's `read_file()` rejects any file path that doesn't satisfy `wp_check_filetype()`, which Playground's WASM PHP can't always satisfy even with a `.csv` suffix.

Playground's `wp-cli` step has **no shell**. The command string is parsed into args and handed straight to WP-CLI; there is no `&&`, no `||`, no `;`, no `$(…)` substitution, no pipes. Use one of these patterns instead:

- For a sequence of WP-CLI calls or anything that needs a shell, use a `runPHP` step that calls `update_option()` / `wp_insert_post()` / etc. directly. WP isn't loaded by default in `runPHP`, so start the code with `require_once '/wordpress/wp-load.php';`.
- For a single WP-CLI call that needs a value from another query, do the lookup in PHP and inline the resulting literal — never `$(wp post list …)`.
- If you genuinely need WP-CLI semantics for a long script, write it to disk with `writeFile` and run it with a single `wp eval-file <path>` step.

## View Transitions (cross-document)

**Every theme in this monorepo MUST opt into cross-document View Transitions** with the same four-piece contract Obel ships. It is part of the visual baseline, not an enhancement — clones inherit it by default, the migration script (`bin/migrate-view-transitions.py`) keeps the five shipped non-obel themes (`aero`, `chonk`, `foundry`, `lysholm`, `selvedge`) in lockstep with `obel/`, and you should not strip any piece out. When you add a new non-obel theme, extend `TARGETS` in `bin/migrate-view-transitions.py` so future obel VT changes propagate.

The contract has FOUR pieces, all between the sentinels `// === BEGIN view-transitions === … // === END view-transitions ===` (in `functions.php`) and `/* === BEGIN view-transitions === */ … /* === END view-transitions === */` (in `theme.json` styles.css):

1. **CSS prelude (in `theme.json` root `styles.css`)** — declares `@view-transition { navigation: auto; types: fifty-default; }`, defines the `fifty-vt-in/out` and `fifty-vt-slide-in-right/out-left` keyframes, sets the baseline `::view-transition-old(root)` / `::view-transition-new(root)` animations, tunes `::view-transition-group(.fifty-card-img)` and `(.fifty-card-title)` for the per-post morph, and assigns persistent names: `fifty-site-header` to `.wp-site-blocks > header:first-of-type`, `fifty-site-footer` to `.wp-site-blocks > footer:last-of-type`, `fifty-site-title` to `.wp-site-blocks > header .wp-block-site-title`. **Five named transition types** drive route-flavored animations via `:root:active-view-transition-type(<name>)` selectors:
   - `fifty-default` — cold-path cross-fade (the type Chrome falls back to when no other matched).
   - `fifty-shop-to-detail` — slower 580ms image morph for `body.archive` (shop / category) → `body.single-product`.
   - `fifty-archive-to-single` — same morph for blog/journal/category → single post.
   - `fifty-paginate` — content slides while the header pins; matches when the URL only differs in `/page/N/`.
   - `fifty-cart-flow` — fast 220ms cross-fade only; image morph is explicitly disabled (cart line items don't share visual identity with the checkout summary).
   
   `prefers-reduced-motion: reduce` flips `@view-transition` to `navigation: none`, killing every transition.
2. **PHP per-post names (in `functions.php`)** — a single `render_block` filter that uses `WP_HTML_Tag_Processor` to add `style="view-transition-name:fifty-post-{ID}-{kind};view-transition-class:fifty-card-img"` (or `fifty-card-title` for titles) to FOUR block names: `core/post-title`, `core/post-featured-image`, **`woocommerce/product-image`** (shop cards / cross-sells / related / order-confirm), and **`woocommerce/product-image-gallery`** (PDP gallery, in case a theme switches off `core/post-featured-image`). Together this produces a real cross-document morph from the shop card to the PDP hero — without the WC block names the morph silently no-ops because the source page's image element has no `view-transition-name`. To extend coverage when a future Woo block ships (e.g. `woocommerce/product-image-tile`), add the new block name to the `$names` map in the same filter; rule #21 will start failing if you forget.
   
   The post ID comes from the block context (`$instance->context['postId']`), falling back to `get_the_ID()` and `get_queried_object_id()` for singular templates. The companion `init` hook resets the request-scoped `$GLOBALS['fifty_vt_assigned']` dedup tracker at the top of every request.
3. **Inline `pageswap` / `pagereveal` handler (in `functions.php`)** — `fifty_view_transitions_inline_script` is registered on `wp_head` priority 1. It classifies the navigation by URL pattern (shop→product, paged URLs, cart/checkout) and calls `e.viewTransition.types.add(<type>)` so the CSS in piece 1 picks the right per-route flavor. It also just-in-time names the clicked card's `<img>` and clears the name on `viewTransition.finished` to avoid BFCache leakage.
   
   This is the **documented JS exception** for VT, treated identically to the long-standing swatches and payment-icons inline scripts. Hard requirements:
   
   - **≤30 LOC, inline IIFE, classic parser-blocking script.** No external `.js` file. No bundle. No `package.json`. No `<script type="module">`. No `defer`/`async`.
   - **Registered on `wp_head` priority 1.** The `pagereveal` listener MUST be installed before the destination page's first rendering opportunity per the Chrome cross-document VT spec.
   - **Lives in `<theme>/functions.php`** between the `// === BEGIN view-transitions === … // === END view-transitions ===` sentinels — never in an MU plugin, never in `playground/`.
4. **Speculation rules JSON (in `functions.php`)** — `fifty_view_transitions_speculation_rules` echoes a `<script type="speculationrules">` block from `wp_head`. This is **data-only** (the browser parses the JSON; nothing executes), but it's the single biggest perceived-perf lever for cross-document VT — the destination page is already prerendered when the user clicks, so the transition runs against an in-memory page. Excludes mutation-prone routes (`/cart/`, `/checkout/`, `/my-account/`, `/wp-admin/`, `/wp-login.php`) and gives a `.no-prerender` opt-out class for any future link a theme wants to keep cold. Eagerness `moderate` triggers on hover. Skipped for logged-in users (admin bar markup + cookie state make prerender misses much more likely).

Why all four pieces are required:

- Without piece 1 there is no transition at all (cross-document VT is opt-in on both pages).
- Without piece 2 the per-post elements have no shared identity, so the browser falls back to a root crossfade — you lose the morph.
- Without piece 3 every transition uses the `fifty-default` type, so the per-route flavors in piece 1 never match (the slide-paginate, the cart-flow crossfade, and the longer shop-to-detail easing all silently degrade to the default).
- Without piece 4 the destination page is fetched on click, so the transition runs against a half-painted page (image not decoded, fonts swapping mid-morph). Demoably worse — the morph "looks broken" in playground recordings.

> **Per-page uniqueness footgun (do not regress):** Chrome aborts every transition on the page with `InvalidStateError: Transition was aborted because of invalid state` AND logs `Unexpected duplicate view-transition-name: <name>` to the console if any value collides. Two patterns will silently break this contract; both are guarded:
>
> - **Site-title selector must be header-scoped.** `wp-block-site-title` typically appears in BOTH the header AND the footer wordmark. Always scope the rule to the header instance: `.wp-site-blocks > header .wp-block-site-title { view-transition-name: fifty-site-title }`. Naked `.wp-block-site-title { view-transition-name: ... }` is the bug — it also matches the footer wordmark and produces a duplicate.
> - **Per-post filter must dedupe per request.** A post ID can render in multiple block contexts on the same page (featured products + post-template grid). The `render_block` filter in `functions.php` MUST track assigned `(post_id, kind)` pairs in a request-scoped global (NOT a closure `static`, which leaks across PHP-FPM/Playground requests) and skip duplicates. The companion `add_action( 'init', … )` resets the global at the top of every request.
>
> Both regressions are caught at runtime by `bin/snap.py`'s `view-transition-name-collision` heuristic. The matching coverage gap (a card link with no descendant `view-transition-name`) is caught by `view-transition-name-coverage` on every listing route. And actual transition firing is asserted at navigation time by `view-transition-fires-on-click`, which clicks the first product/post card in each viewport, listens for `pageswap`/`pagereveal`, and emits a `view-transition-aborted` finding (severity `error`) if `pagereveal.viewTransition` is null on the destination doc. Findings land in the manifest under `vt_probes`.

**Static gate (rule #21).** `bin/check.py`'s `check_view_transitions_wired` hard-fails the pre-push hook if any of the four pieces above is missing from any theme: the `@view-transition` opt-in + `fifty-default` types descriptor in `theme.json`, the four block names in the `render_block` filter, the `fifty_vt_assigned` dedup tracker, the inline pageswap handler registration, and the `<script type="speculationrules">` block. Failing the gate prints a precise diagnostic per missing piece — far cheaper than chasing a silent runtime regression through `tmp/snaps/`.

**JavaScript policy.** Cross-document VT is mostly CSS-only; the only allowed JS is the documented inline `pageswap`/`pagereveal` handler in piece 3 and the `<script type="speculationrules">` JSON block in piece 4. Both ship as inline `<script>` tags in `<theme>/functions.php`. **No external `.js` file, no module, no bundle, no `defer`/`async`.** Adding any other `<script>` for VT (or moving these into an external file) is a hard-rule violation.

When cloning a theme via `bin/clone.py`, all four pieces come along automatically (the CSS lives in `theme.json`, the filter / handler / speculation rules live in `functions.php`). When the obel source-of-truth changes, run `python3 bin/migrate-view-transitions.py` from the repo root to roll the change to every shipped non-obel theme — it's idempotent, so re-running it after a no-op edit is safe. Do not delete any piece during a restyle.

## GitHub Pages short URLs

**Every theme MUST have a working short URL** at `https://demo.regionallyfamous.com/<theme>/`. The canonical Playground deeplink is ~200 characters before any extra parameters (`?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/blueprint.json&url=/shop/`) — unusable in tweets, slide decks, or anywhere a human reads the URL out loud. wp.me is not an option (it only mints links for posts on real wordpress.com / wordpress.org-hosted sites), so we self-host the redirector via GH Pages.

The contract:

```
fifty/
├── docs/                       # GH Pages serves this folder from main
│   ├── .nojekyll               # disable Jekyll on Pages (required)
│   ├── CNAME                   # optional custom domain — preserved across rebuilds
│   ├── index.html              # landing page listing every theme
│   ├── obel/
│   │   ├── index.html          # → playground.wordpress.net/?blueprint-url=…&url=/
│   │   ├── shop/index.html     # → …&url=/shop/
│   │   ├── product/bottled-morning/index.html
│   │   ├── cart/index.html     # → …&url=/cart/?demo=cart
│   │   ├── checkout/index.html # → …&url=/checkout/?demo=cart
│   │   ├── my-account/index.html
│   │   ├── journal/index.html
│   │   └── 404/index.html
│   ├── chonk/…                 # same shape
│   └── <theme>/…               # auto-generated for every theme
└── bin/build-redirects.py      # the only thing allowed to write into docs/
```

How it works:

- `bin/build-redirects.py` walks `_lib.iter_themes()`, reads each theme's `playground/blueprint.json` URL via `_lib.theme_blueprint_raw_url(slug)`, and emits one HTML file per `(theme, page)` pair under `docs/`. Every redirector ships both a `<meta http-equiv="refresh">` (works without JS / on link previews) and a `<script>location.replace(…)</script>` (no flash, faster). The page list lives in the script as `PAGES`; add a row there if a new entry point becomes interesting.
- The script wipes and rewrites `docs/` from scratch on every run, **except** for the allowlist of human-owned / brand-asset files inside `PRESERVED_FILES` (currently: `CNAME`, `assets/style.css`, `favicon.svg`, `favicon-{16,32}.png`, `favicon.ico`, `apple-touch-icon.png`, `assets/og-default.png`). The snap gallery directory `docs/snaps/` is also preserved — it's owned by `bin/build-snap-gallery.py`. If you delete a theme, its `docs/<theme>/` folder disappears on the next run; brand assets survive untouched.
- Brand assets (favicon set + Open Graph share card) are produced by a third script: `bin/build-brand-assets.py`. It rasterizes `docs/favicon.svg` to PNG/ICO via Pillow and renders `docs/assets/og-default.png` (1200×630) by screenshotting an HTML template through headless Chrome with Google Fonts. The output binaries are checked in; re-run the script (and commit) any time you change `docs/favicon.svg` or the magazine-cover palette in `docs/assets/style.css`. `bin/build-brand-assets.py --check` exits non-zero if the on-disk derivatives drift from the sources — useful as a CI gate.
- One-time GH Pages setup (already done for the canonical repo): repo settings → Pages → Source "Deploy from a branch", Branch `main`, Folder `/docs`. Pushes to `main` propagate within ~1 minute.

When you must re-run `bin/build-redirects.py`:

- After `bin/clone.py` (a new theme appeared).
- After deleting a theme.
- After changing the `PAGES` list inside `build-redirects.py`.
- After changing `_lib.GITHUB_ORG` / `GITHUB_REPO` / `GITHUB_BRANCH` (also re-run `bin/sync-playground.py` because both consumers read from the same source of truth).

When you must re-run `bin/build-brand-assets.py`:

- After hand-editing `docs/favicon.svg` (the canonical mark).
- After changing the magazine-cover palette in `docs/assets/style.css` (so favicons + OG card match the new ink/paper/accent values).
- After editing the `OG_TEMPLATE` literal inside `bin/build-brand-assets.py` itself.

You should **not** edit any file under `docs/` by hand. The whole tree is generated; manual edits are wiped on the next `build-redirects.py` run. If you need a redirector that isn't reachable from `(theme, page)` shape (e.g. a top-level alias), add it to `build-redirects.py` so the next run still produces it.

When you write theme READMEs, prefer the short URL (`https://demo.regionallyfamous.com/<theme>/<page>/`) over the long deeplink. Keep the long deeplink in a "Long-form deeplinks" table for the case where someone runs the repo on a fork before GH Pages is enabled.

## Working on shared tooling

`bin/` is shared. Anything you change there affects every theme. After editing:

```bash
python3 bin/check.py --all --quick    # theme-gate
python3 -m pytest tests/              # tooling-tests (unit + integration)
python3 bin/lint.py                   # ruff + mypy
```

The tooling test suite lives under `tests/` and is organised as:

- `tests/check_py/` — unit tests for every `check_*` function in `bin/check.py`. One file per function family; each defines good + bad fixtures.
- `tests/tools/` — integration tests for build scripts (`clone.py` round-trip, `build-index.py` determinism, `append-wc-overrides.py` idempotence, etc.).
- `tests/validator/` — Node editor-parity validator smoke tests. Shells out to `bin/blocks-validator/check-blocks.mjs`; skipped when `node` / `php` / `node_modules/` are missing.
- `tests/conftest.py` — shared `minimal_theme` / `monorepo` fixtures. Start here when writing a new test.

See `tests/README.md` for the full convention (fixture patterns, naming, what to monkeypatch).

CI runs all of this plus a visual-regression pass (`bin/snap.py check --changed`) on a separate workflow; see `.github/workflows/check.yml` + `.github/workflows/visual.yml`. Branch protection requires every job in `check.yml` to pass before a PR can merge; `visual.yml` is warn-only until the baselines stabilise. Applying / updating branch protection is a one-liner: `bash bin/setup-branch-protection.sh` (requires `gh auth login`).

`bin/_lib.py` contains the theme resolver (`resolve_theme_root`, `iter_themes`, `MONOREPO_ROOT`) AND the canonical GitHub identity (`GITHUB_ORG`, `GITHUB_REPO`, `GITHUB_BRANCH`, `GH_PAGES_BASE_URL`, `RAW_GITHUB_BASE_URL`, `theme_content_base_url(slug)`, `theme_blueprint_raw_url(slug)`, `playground_deeplink(slug, url_path)`, `gh_pages_short_url(slug, page_slug)`). `bin/sync-playground.py` and `bin/build-redirects.py` both consume those helpers — if you change the org / repo / branch, change it once in `_lib.py` and re-run both scripts. Every new bin/ script should follow the same pattern: positional theme arg, `--all` flag where it makes sense, default to cwd if it contains `theme.json`, and pull any GH-identity URL from `_lib` rather than re-encoding it.

## When in doubt

- Read the theme's `AGENTS.md` and `INDEX.md`.
- Ask `python3 bin/list-tokens.py --theme <theme>` before inventing a value.
- Ask `python3 bin/list-templates.py <theme>` before creating a new template.
- Run `python3 bin/check.py <theme>` before claiming you are done.
