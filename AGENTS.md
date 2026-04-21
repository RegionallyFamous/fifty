# AGENTS.md — Fifty monorepo

This is the agent guide for the **Fifty monorepo**. Each theme inside this repo (`obel/`, `chonk/`, `selvedge/`, `lysholm/`, plus any future variants you scaffold via `bin/clone.py`) has its own `AGENTS.md` with theme-specific rules. Read this file first to understand the layout, then read the theme-specific `AGENTS.md` for the theme you are editing.

Agent voice and manner are defined separately in [`AGENT-PERSONA.md`](./AGENT-PERSONA.md): the agent operating in this repo is **Woo-drow**, a fussy Victorian shopdresser. That file governs how the agent speaks in chat (cadence, vocabulary, how it addresses the user as "the Proprietor"). This file (`AGENTS.md`) governs what it does. When they disagree — if cadence ever gets in the way of a rule — this file wins.

## Repo layout

```
fifty/
├── obel/                 # base theme (canonical reference) — editorial, soft, restrained
│   ├── AGENTS.md         ← read this when editing obel
│   ├── INDEX.md
│   ├── theme.json
│   └── …
├── chonk/                # neo-brutalist variant
│   ├── AGENTS.md         ← read this when editing chonk
│   ├── INDEX.md
│   └── …
├── selvedge/             # workwear / indigo variant
│   └── (same shape)
├── lysholm/              # Nordic home goods variant
│   └── (same shape)
├── bin/                  # shared CLI tooling (theme-aware)
├── playground/           # shared Playground PHP scaffolding + mu-plugins (read playground/AGENTS.md)
├── tests/                # committed visual-baseline PNGs (read tests/visual-baseline/README.md)
├── docs/                 # generated GH Pages site of short URLs (read bin/build-redirects.py)
├── .claude/skills/       # in-repo agent skills (e.g. build-block-theme-variant)
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
10. **No default WooCommerce strings on the live demo.** A handful of WC's stock frontend strings are visually unmistakable "this is a free WooCommerce theme" tells: `"Showing 1-16 of 55 results"` (loop result count), `"Default sorting"` (catalog-sorting first option), `"Estimated total"` (cart totals label), `"Proceed to Checkout"` (order button), `"Lost your password?"` (account login link), and the screaming red `<abbr class="required">*</abbr>` after every required field. Every premium reference (Aesop, Glossier, Hermès, Lululemon) replaces these with brand-specific wording. The canonical pattern in this monorepo: override them server-side via `add_filter()` in `playground/wo-microcopy-mu.php` (a must-use plugin, no theme activation needed). The mu-plugin is inlined into every theme's `playground/blueprint.json` by `bin/sync-playground.py`, so the same overrides ship for every variant. `bin/check.py`'s `check_no_default_wc_strings` enforces both halves: it asserts the inlined `wo-microcopy-mu.php` writeFile step is present in `blueprint.json`, AND it asserts each of the five canonical override fragments (`woocommerce_blocks_cart_totals_label`, `woocommerce_order_button_text`, `woocommerce_default_catalog_orderby_options`, `Lost your password?`, `wo-result-count`) survives the inline. New WC strings that read as default-WC tells should be added to the mu-plugin AND to the `required` list in the check so the regression is impossible to ship. NEVER hardcode the replacement strings in templates or PHP partials — the override must live in the mu-plugin so a single edit ripples across every variant.
11. **Variation `<select>`s become swatches; never ship the bare native dropdown on a PDP.** A `<select>` element on a PDP is the second-loudest "default WC theme" tell after the WC tabs block. Browsers render it with their OS-native chrome (chevron, focus ring, dropdown panel), and the cascade conflict between WC's `table.variations select.orderby` plugin rules and any theme reset is unwinnable without `appearance:none` plus a custom chevron — at which point you've reinvented half a swatch component anyway. The canonical pattern: `playground/wo-swatches-mu.php` filters `woocommerce_dropdown_variation_attribute_options_html` and replaces the dropdown with an HTML button group (color circles for `Finish`, text pills for `Size` / `Intensity`), keeping the original `<select>` in the DOM but visually hidden (`.wo-swatch-select` clips it to 1×1px). A small inline JS shim in `wp_footer` syncs button clicks to `select.dispatchEvent(new Event('change', {bubbles:true}))` so WooCommerce's `variation_form` JS continues to drive price / stock / image swap. `bin/snap_config.py` `INSPECT_SELECTORS` for `product-variable` track both `.wo-swatch-wrap` AND `.wo-swatch-select` so a regression that drops either side fails the visual gate. Color swatches read their hex from `wo_swatches_color_map()` in the mu-plugin — add a new entry there when a new color attribute lands. NEVER add a `<select>` to a PDP via theme markup; if you need a third attribute axis (date, size+letter, etc.) extend the swatches mu-plugin instead.
12. **Single-product templates MUST always render a product image block.** A PDP that paints with no image (an empty cream-coloured box with a magnifying-glass overlay) is the loudest "this site is broken" tell on the entire demo. Two failure modes produce it: (a) `wp:woocommerce/product-image-gallery` depends on Flexslider + PhotoSwipe runtime wiring; on Playground (and on any fresh WC install where the gallery JS hasn't initialised yet) it sometimes fails silently, leaving the gallery's `opacity:0` start state in place; (b) the template author removed the image block thinking core/featured-image would be inherited from the underlying post (it isn't — `single-product.html` is rendered against a WC product post type that the page builder treats as opaque). The canonical pattern in this monorepo: render `wp:post-featured-image` on every theme's `single-product.html` (server-rendered `<img>`, zero JS dependency, plays well with `core/cover` ratios). `bin/check.py`'s `check_pdp_has_image` enforces this by failing the static gate if the template renders NONE of `wp:post-featured-image`, `wp:woocommerce/product-image-gallery`, `wp:woocommerce/product-image`, or `wp:woocommerce/product-gallery`, and warning (informational, not a fail) if the legacy `wp:woocommerce/product-image-gallery` is the only image block present. The defensive CSS rule in `bin/append-wc-overrides.py` (`/* wc-tells-phase-a-premium */ .woocommerce-product-gallery{opacity:1!important;}`) is the second line of defence — it makes the legacy gallery visible even if its JS never runs — but the template MUST have the block in the first place. NEVER ship a PDP without a product image block; the empty cream box is unrecoverable from CSS alone.
13. **Every Playground blueprint MUST ship its content payload alongside it.** A theme that has `<theme>/playground/blueprint.json` but no `<theme>/playground/content/content.xml`, no `<theme>/playground/content/products.csv`, and no `<theme>/playground/images/*` is unbootable on the live demo. The blueprint's WXR import step (`importWxr` against `https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/content/content.xml`) 404s on `raw.githubusercontent.com`; the failed XML import leaves WC's catalogue empty; every subsequent `wp eval-file` (`wo-import.php`, `wo-configure.php`, `wo-cart.php`, etc.) crashes because it tries to read products WC never imported; the user sees an unbroken stream of `PHP.run() failed with exit code 1` in the browser console and a blank page. The fail mode is invisible from a local checkout — the theme dir looks complete (it has `theme.json`, `templates/`, `parts/`, `patterns/`, `playground/blueprint.json`) and `bin/snap.py` mounts the local content via Playground's filesystem mount so it works locally too. The canonical fix the moment a theme is scaffolded (whether by `bin/clone.py`, by hand, or by the `build-block-theme-variant` skill) is `python3 bin/seed-playground-content.py --theme <slug>` (copies the canonical wonders-oddities CSV/WXR/images into `<theme>/playground/content/` and `<theme>/playground/images/` and rewrites every image URL to point at the per-theme folder), then `python3 bin/sync-playground.py` (re-inlines the mu-plugins into the blueprint), then commit `content/` + `images/` + the updated `blueprint.json` together. `bin/check.py`'s `check_playground_content_seeded` enforces both halves: it fails if `playground/blueprint.json` exists without `content/content.xml` + `content/products.csv` + a non-empty `images/` directory, AND it fails if the blueprint references any `raw.githubusercontent.com/.../playground/images/<file>` URL whose file is missing on disk (drift between blueprint and the seeded asset set). NEVER commit a `playground/blueprint.json` without first running the seed script for that theme; the demo will boot to a blank screen the moment GitHub raw catches up to the push.
14. **No two themes may ship the same user-visible string.** `bin/clone.py` copies obel verbatim into every new theme, including all paragraph body copy, button labels, list items, eyebrow strap text, footer copyright, FAQ questions, hero subtitles, order-confirmation step lists, 404 / no-results / coming-soon body copy, and PDP care + shipping policy paragraphs. Without a follow-up voice pass the new theme reads on a side-by-side demo browse as one shop in different paint jobs — the exact failure mode this monorepo exists to avoid. The canonical pattern: keep obel's wording as the baseline, then rewrite every other theme into its own brand voice using the per-theme substitution map in `bin/personalize-microcopy.py` (re-runnable, idempotent, refuses to start if any replacement would cascade). `bin/check.py`'s `check_all_rendered_text_distinct_across_themes` enforces this end-to-end: it scans every `*.html` and `*.php` file in `templates/`, `parts/`, and `patterns/`, extracts every block-delimiter `"content"` value, every inner-text run inside `<h1-6>/<p>/<li>/<button>/<a>/<figcaption>/<blockquote>`, and every PHP `__()/_e()/esc_html_e()/esc_html__()/esc_attr_e()/esc_attr__()` literal, normalises (lowercase, collapse whitespace, strip trailing punctuation, decode unicode + PHP escapes), drops anything < 12 chars or in the wayfinding allowlist, and fails on any normalised fragment that appears in another theme. When this fires either rewrite the offending fragment in this theme's voice (preferred) or extend `ALL_TEXT_ALLOWLIST` if the duplicate is truly system / wayfinding text. The companion `check_pattern_microcopy_distinct` covers the same-named-pattern case and word-overlap heuristic; both run in the gate.
15. **No fake forms. Email-capture / newsletter / "subscribe" UI MUST submit somewhere real or be deleted.** WordPress core ships zero working email-capture blocks: `core/search` submits `?s=…` to the home URL, `core/login` submits to `wp-login.php`, `core/comments` is per-post — that is the entire form-shaped surface area. So a "Subscribe" button that looks like an email field and is built out of `core/search` styled with an email placeholder, OR a `core/html` block containing a raw `<form action="/?my-fake-endpoint=1">`, is a dummy feature: a visitor who types their email in either gets a search-results page for their own address or a 404. That is worse than no signup at all because it sets an expectation the codebase cannot honor — hard rule #4 (only `core/*` and `woocommerce/*` blocks; no custom blocks, no third-party form plugins) makes integrating MailPoet / Jetpack Subscribe / ConvertKit a hard "no", which means a real email-capture surface is not buildable inside this codebase, full stop. The canonical replacement when a "newsletter" section is wanted: pick a real CTA whose link ACTUALLY DOES something — `woocommerce/customer-account` (logged-in icon + register/sign-in flow on `/my-account/`), an `<a>` to `/journal/`, an `<a>` to `/contact/`, a `core/social-links` cluster pointing at the brand's real off-site channels, or a featured `woocommerce/product-collection` linking to `/shop/`. Per-theme distinctiveness still applies (rule #14): five themes ≠ five identical "Read the journal →" buttons, so each theme's call-out should pick a different real action that fits its voice (chonk → categories grid, obel → account CTA, selvedge → journal CTA, lysholm → social cluster, aero → latest blog post via `core/query`). `bin/check.py`'s `check_no_fake_forms` enforces this in two passes: (a) it fails if `core/search` appears in any pattern / template / part outside the five legitimate search surfaces (`parts/header.html`, `parts/no-results.html`, `templates/search.html`, `templates/product-search-results.html`, `templates/404.html`), and (b) it scans every `core/html` block body for `<form>`, `<input type="email">`, or a Subscribe / Sign up / Notify-me button — any of those fails the check. NEVER ship a form-shaped UI element without a real submission target; if you cannot name the working endpoint, delete the section.

16. **`bin/check.py --all --offline` MUST pass on every commit, on every theme, no exceptions.** Two regressions made it to `main` because nothing automated ran the gate before the push: a Phase J refactor leaked `!important` past `check_no_important`, and a Phase K addition shipped the same leak under a new sentinel. The gate is fast (~3s × 5 themes ≈ 15s on a laptop) and has zero false positives — there is no real-world reason to commit past a red gate. Three layers enforce this and they stack rather than overlap because each one closes a different bypass: (a) `.githooks/pre-commit` runs the gate on every `git commit` and blocks the commit on any failure (this is the fast inner-loop signal); (b) `.githooks/pre-push` re-runs the gate AND a `bin/append-wc-overrides.py` drift check on every `git push` (this catches commits made with `git commit --no-verify`); (c) `.github/workflows/check.yml` runs the same gate server-side on every PR and every push to `main` (this is authoritative — no local bypass survives it). The local hooks only fire if `git config core.hooksPath` points at `.githooks/`; that's not on by default for a fresh clone, so the canonical bootstrap the moment you clone the repo (whether you're a human or a coding agent) is `python3 bin/install-hooks.py` — it sets `core.hooksPath`, fixes the executable bit on every hook, and smoke-tests the gate so you find out NOW if the working tree is already in a state that would block your next commit. The drift check piece matters as much as the static-analysis piece: `bin/append-wc-overrides.py` is sentinel-based, so a clean re-run is a no-op (every chunk reports `skip <sentinel>`); the moment the script's source diverges from the committed `theme.json` bytes, the script's next run reports `+<size> <sentinel>` and the pre-push gate blocks. NEVER edit `bin/append-wc-overrides.py` without re-running it AND committing the resulting `theme.json` diff in the same commit; NEVER `--no-verify` past a red gate; NEVER disable the GitHub Actions workflow.

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

# Whole monorepo (~10 routes × 4 viewports × 4 themes ≈ 160 PNGs)
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
```

Per-cell artifacts (all under `tmp/snaps/<theme>/<viewport>/<route>.*`):

| Artifact | What's in it |
|---|---|
| `*.png` | The screenshot. `Read` directly. |
| `*.html` | Final rendered DOM after JS settled. Useful for `Grep`-ing class names without re-shooting. |
| `*.findings.json` | DOM-heuristic + axe + budget findings, captured console messages, page errors, network failures (>=400 split into 4xx/5xx), and computed widths/displays/grid-template-columns for `INSPECT_SELECTORS`. The `report` subcommand reads these. |
| `*.a11y.json` | Raw axe-core report (violations only) for that cell. |
| `<route>.<flow>.png` etc. | Interactive cells produced by `INTERACTIONS` (e.g. `home.menu-open.png`, `cart-filled.line-remove.png`). |

### The tiered gate

Every cell's findings are classified into one of three buckets:

- **fail** (build-blocking, exit 1): heuristic `error`, uncaught JS (after noise filter), HTTP 5xx, axe critical/serious.
- **warn** (loud banner, exit 0): heuristic `warn`/`info`, HTTP 4xx, console errors, axe moderate/minor, parity drift, perf-budget exceedances, interaction-failed.
- **pass**: nothing flagged.

The verdict appears as a `STATUS: PASS | WARN | FAIL` line at the end of every `report` and `check` run. It also lives at the top of each per-theme `review.md` as a `**GATE: …**` badge so triage starts with the verdict, not the table.

### Recommended loops

When you make ANY change that could affect rendered output (template, theme.json, CSS, pattern, blueprint), the loop is:

1. Make the change.
2. `python3 bin/snap.py shoot <theme> --routes <route> --viewports <viewport>` for the affected cell(s).
3. `Read` the PNG to verify.
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
- **`VIEWPORTS`** — Playwright viewport sizes (mobile / tablet / desktop / wide). Same idea.
- **`INSPECT_SELECTORS`** — per-route map of CSS selectors whose computed width, height, display, and grid-template-columns get captured into `*.findings.json` and rendered into the per-theme `review.md` "Inspector measurements" tables. This is how the cart/checkout sidebar regression got diagnosed without re-shooting — add an entry here when you find yourself running ad-hoc Playwright probes to measure layout issues, so the next regression is visible immediately.
- **`INTERACTIONS`** — per-route list of scripted flows (`menu-open`, `qty-increment`, `swatch-pick`, `line-remove`, `field-focus`). Each flow renders an extra `<route>.<flow>.png` cell so the post-interaction state is reviewable side-by-side with the static one.
- **`KNOWN_NOISE_SUBSTRINGS`** — substring filter for pre-confirmed-harmless console / page errors. **Add to it only after investigation confirms upstream noise** — never to silence a real theme bug.
- **`BUDGETS`** — soft thresholds for `console_warning_count`, `page_weight_kb`, `image_count`, `request_count`. Exceedances become findings at the configured severity. Set `max: None` to disable a budget.
- **`QUICK_*`** — subsets used when `shoot` is invoked with `--quick`.

## Agent skills

This repo ships its own agent skills under `.claude/skills/` so any LLM working in the codebase (Claude Code, Claude.ai with this repo attached, Cursor, etc.) can pick them up without any local install. Cursor users will also find a mirror at `~/.cursor/skills/` on the maintainer's machine; the in-repo copy under `.claude/skills/` is the source of truth.

| Skill | Use when |
|---|---|
| `.claude/skills/build-block-theme-variant/SKILL.md` | Building a new visual variant of Obel (e.g. Chonk-style flow): mockup → tokens → templates → dynamic data → verification. Encodes the surface checklist, structural defect scan, WC-integration gotchas, and the hard rules (modern blocks only, nothing static, self-hosted Google Fonts only). |

If you add a new skill, drop it under `.claude/skills/<name>/SKILL.md` with the standard frontmatter (`name`, `description`) so every agent host can discover it.

## Adding a new theme variant

Use the agent skill `build-block-theme-variant` (in `.claude/skills/build-block-theme-variant/SKILL.md`) — it codifies the entire workflow including up-front design intent capture, token planning, comprehensive surface coverage, contrast/responsiveness verification, and final self-checks.

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
10. `python3 bin/check.py <new_name>`
11. `python3 bin/build-redirects.py` — regenerates `docs/<new_name>/<page>/index.html` so the theme is reachable at `https://demo.regionallyfamous.com/<new_name>/` once the change is pushed and GH Pages picks it up. Re-run any time you add a theme or change the `PAGES` list inside the script. See "GitHub Pages short URLs" below.
12. Open the new theme's short URL (`https://demo.regionallyfamous.com/<new_name>/`, which redirects to the canonical `playground.wordpress.net/?blueprint-url=…` deeplink) and walk the surface checklist before declaring done. The blueprint AND the short-URL redirector are part of the deliverable — see "WordPress Playground blueprints" and "GitHub Pages short URLs" below.

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

**Every theme in this monorepo MUST opt into cross-document View Transitions** with the same contract Obel and Chonk already implement. It is part of the visual baseline, not an enhancement — clones inherit it by default and you should not strip it out.

The contract has two halves:

1. **CSS opt-in (in `theme.json` root `styles.css`)** — prepend the View Transitions block at the start of the existing root `css` string. It declares `@view-transition { navigation: auto }`, defines the `fifty-vt-in` / `fifty-vt-out` keyframes, sets refined `::view-transition-old(root)` and `::view-transition-new(root)` animations, and assigns persistent names: `fifty-site-header` to `.wp-site-blocks > header:first-of-type`, `fifty-site-footer` to `.wp-site-blocks > footer:last-of-type`, `fifty-site-title` to `.wp-site-blocks > header .wp-block-site-title`. It also disables transitions under `prefers-reduced-motion: reduce`. **The `:first-of-type` / `:last-of-type` / header-scoped selectors are load-bearing** — themes that ship multiple `<header>` template parts at the root (announcement bar above the main header, etc.) or that include the site title in a footer wordmark would otherwise produce duplicate `view-transition-name` values, which Chrome treats as a hard error (see the per-page uniqueness footgun below).
2. **PHP per-post names (in `functions.php`)** — a single `render_block` filter that uses `WP_HTML_Tag_Processor` to add `style="view-transition-name:fifty-post-{ID}-{kind}"` to `core/post-title` and `core/post-featured-image` outputs. The post ID comes from the block context (`$instance->context['postId']`), falling back to `get_the_ID()` and `get_queried_object_id()` for singular templates. Together with the CSS opt-in, this produces a real morph from the archive card to the single post hero.

Why both halves are required:

- Without the CSS opt-in there is no transition at all (cross-document VT is opt-in on both pages).
- Without the PHP filter the per-post elements have no shared identity, so the browser falls back to a root crossfade — you lose the morph that makes it feel modern.
- Per-page uniqueness: `view-transition-name` must be unique on each page. The site-level names (`fifty-site-header`, `fifty-site-footer`, `fifty-site-title`) appear once per page; the per-post names use the post ID, which is unique inside a single archive page and trivially unique on a singular page.

> **Per-page uniqueness footgun (do not regress):** Chrome aborts every transition on the page with `InvalidStateError: Transition was aborted because of invalid state` AND logs `Unexpected duplicate view-transition-name: <name>` to the console if any value collides. Two patterns will silently break this contract; both are guarded:
>
> - **Site-title selector must be header-scoped.** `wp-block-site-title` typically appears in BOTH the header AND the footer wordmark. Always scope the rule to the header instance: `.wp-site-blocks > header .wp-block-site-title { view-transition-name: fifty-site-title }`. Naked `.wp-block-site-title { view-transition-name: ... }` is the bug — it also matches the footer wordmark and produces a duplicate.
> - **Per-post filter must dedupe per request.** A post ID can render in multiple block contexts on the same page (featured products + post-template grid). The `render_block` filter in `functions.php` MUST track assigned `(post_id, kind)` pairs in a request-scoped global (NOT a closure `static`, which leaks across PHP-FPM/Playground requests) and skip duplicates. The companion `add_action( 'init', … )` resets the global at the top of every request.
>
> Both regressions are caught at runtime by `bin/snap.py`'s `view-transition-name-collision` heuristic, which walks every element's computed `view-transition-name`, groups by value, and emits a hard-fail finding (severity `error`) for any group with two or more members. The finding includes the offending name and the first few collider tag/class fingerprints, so the fix surface is always obvious from `tmp/snaps/<theme>/<vp>/<route>.findings.json`.

Do not add JavaScript for this. Cross-document VT is a CSS-only feature, and this monorepo bans JS bundles. If you want fancier behaviors (typed transitions, back/forward direction awareness via `pagereveal`, etc.), either ship them as theme-level CSS only or skip them — adding a `<script>` is a hard-rule violation.

When cloning a theme via `bin/clone.py`, both halves come along automatically (the CSS lives in `theme.json`, the filter lives in `functions.php`). Do not delete either half during a restyle.

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
- The script wipes and rewrites `docs/` from scratch on every run, **except** for `docs/CNAME` which is preserved so a custom domain doesn't drop on every regeneration. If you delete a theme, its `docs/<theme>/` folder disappears on the next run.
- One-time GH Pages setup (already done for the canonical repo): repo settings → Pages → Source "Deploy from a branch", Branch `main`, Folder `/docs`. Pushes to `main` propagate within ~1 minute.

When you must re-run `bin/build-redirects.py`:

- After `bin/clone.py` (a new theme appeared).
- After deleting a theme.
- After changing the `PAGES` list inside `build-redirects.py`.
- After changing `_lib.GITHUB_ORG` / `GITHUB_REPO` / `GITHUB_BRANCH` (also re-run `bin/sync-playground.py` because both consumers read from the same source of truth).

You should **not** edit any file under `docs/` by hand. The whole tree is generated; manual edits are wiped on the next `build-redirects.py` run. If you need a redirector that isn't reachable from `(theme, page)` shape (e.g. a top-level alias), add it to `build-redirects.py` so the next run still produces it.

When you write theme READMEs, prefer the short URL (`https://demo.regionallyfamous.com/<theme>/<page>/`) over the long deeplink. Keep the long deeplink in a "Long-form deeplinks" table for the case where someone runs the repo on a fork before GH Pages is enabled.

## Working on shared tooling

`bin/` is shared. Anything you change there affects every theme. After editing:

```bash
python3 bin/check.py --all --quick
```

`bin/_lib.py` contains the theme resolver (`resolve_theme_root`, `iter_themes`, `MONOREPO_ROOT`) AND the canonical GitHub identity (`GITHUB_ORG`, `GITHUB_REPO`, `GITHUB_BRANCH`, `GH_PAGES_BASE_URL`, `RAW_GITHUB_BASE_URL`, `theme_content_base_url(slug)`, `theme_blueprint_raw_url(slug)`, `playground_deeplink(slug, url_path)`, `gh_pages_short_url(slug, page_slug)`). `bin/sync-playground.py` and `bin/build-redirects.py` both consume those helpers — if you change the org / repo / branch, change it once in `_lib.py` and re-run both scripts. Every new bin/ script should follow the same pattern: positional theme arg, `--all` flag where it makes sense, default to cwd if it contains `theme.json`, and pull any GH-identity URL from `_lib` rather than re-encoding it.

## When in doubt

- Read the theme's `AGENTS.md` and `INDEX.md`.
- Ask `python3 bin/list-tokens.py --theme <theme>` before inventing a value.
- Ask `python3 bin/list-templates.py <theme>` before creating a new template.
- Run `python3 bin/check.py <theme>` before claiming you are done.
