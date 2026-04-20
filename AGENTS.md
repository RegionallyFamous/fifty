# AGENTS.md — Fifty monorepo

This is the agent guide for the **Fifty monorepo**. Each theme inside this repo (`obel/`, `chonk/`, future variants) has its own `AGENTS.md` with theme-specific rules. Read this file first to understand the layout, then read the theme-specific `AGENTS.md` for the theme you are editing.

## Repo layout

```
fifty/
├── obel/          # base theme (canonical reference)
│   ├── AGENTS.md  ← read this when editing obel
│   ├── INDEX.md
│   ├── theme.json
│   └── …
├── chonk/         # neo-brutalist variant
│   ├── AGENTS.md  ← read this when editing chonk
│   ├── INDEX.md
│   └── …
├── bin/           # shared CLI tooling (theme-aware)
├── playground/    # shared Playground PHP helpers (read playground/AGENTS.md)
├── docs/          # generated GH Pages site of short URLs (read bin/build-redirects.py)
├── README.md      # human-facing project intro
├── AGENTS.md      # you are here
└── LICENSE
```

WordPress sees each theme via symlinks: `wp-content/themes/obel -> fifty/obel`, `wp-content/themes/chonk -> fifty/chonk`. Edit the files inside `fifty/<theme>/` and the live site updates immediately.

## Hard rules (apply to every theme)

These are inherited by every theme in the monorepo. Per-theme `AGENTS.md` files may add more rules but never relax these.

1. **`theme.json` is the source of truth.** Every visible decision (color, spacing, type, shadow, radius, layout) lives there as a token. No raw hex codes, px, em, or rem in templates, parts, or patterns.
2. **No CSS files.** Only `style.css` (the WP-required theme header) is allowed. All styles go through `theme.json`'s `styles.blocks.*` and `styles.css`.
3. **No `!important`.** If you reach for it, the cascade is wrong; fix the cascade instead.
4. **Only modern blocks.** Only `core/*` and `woocommerce/*` blocks. No `core/freeform`, `core/html`, `core/shortcode`, no `[woocommerce_*]` shortcodes, no other shortcodes. Custom blocks are forbidden — if a built-in block can do it, use that.
5. **Nothing static.** Menus must be `core/navigation` blocks backed by real `wp_navigation` posts. Category lists must be `core/terms-query`. Product grids must be `woocommerce/product-collection`. No hardcoded link lists masquerading as menus, no hand-typed category tiles.
6. **No raw WooCommerce frontend CSS bleeds through.** WC ships a lot of opinionated frontend CSS that survives a block theme (rounded "folder" product tabs, hard-coded notice colours, `.button` overrides, etc.). Any WC surface whose default markup is styled by `plugins/woocommerce/assets/css/woocommerce.css` MUST be re-styled in `theme.json` via `styles.blocks.<wc-block>.css` using project tokens, with the WC defaults explicitly nullified (`content: none`, `display: none`, `box-shadow: none`, `border-radius: 0`, etc. as needed). Known surfaces: `woocommerce/product-details` (the `.wc-tabs` block), `woocommerce/store-notices`, `woocommerce/cart`/`woocommerce/checkout` form rows, the legacy `.button` class. **Specificity matters**: WC's selectors like `.woocommerce div.product .woocommerce-tabs ul.tabs li` are `(0,4,3)`, and the `&` prefix WP injects only gets you `(0,4,2)` — so every rule must start with `html body &` (the same `(+0,0,2)` trick WC's own `is-style-minimal` block style uses). If you add a new theme variant, copy the full block override — never just the spacing/typography. The check script enforces this for the known surfaces.
7. **Run `python3 bin/check.py <theme> --quick` before every commit.** It catches every mistake the other rules try to prevent.

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

1. **CSS opt-in (in `theme.json` root `styles.css`)** — prepend the View Transitions block at the start of the existing root `css` string. It declares `@view-transition { navigation: auto }`, defines the `fifty-vt-in` / `fifty-vt-out` keyframes, sets refined `::view-transition-old(root)` and `::view-transition-new(root)` animations, and assigns persistent names: `fifty-site-header` to `.wp-site-blocks > header`, `fifty-site-footer` to `.wp-site-blocks > footer`, `fifty-site-title` to `.wp-block-site-title`. It also disables transitions under `prefers-reduced-motion: reduce`.
2. **PHP per-post names (in `functions.php`)** — a single `render_block` filter that uses `WP_HTML_Tag_Processor` to add `style="view-transition-name:fifty-post-{ID}-{kind}"` to `core/post-title` and `core/post-featured-image` outputs. The post ID comes from the block context (`$instance->context['postId']`), falling back to `get_the_ID()` and `get_queried_object_id()` for singular templates. Together with the CSS opt-in, this produces a real morph from the archive card to the single post hero.

Why both halves are required:

- Without the CSS opt-in there is no transition at all (cross-document VT is opt-in on both pages).
- Without the PHP filter the per-post elements have no shared identity, so the browser falls back to a root crossfade — you lose the morph that makes it feel modern.
- Per-page uniqueness: `view-transition-name` must be unique on each page. The site-level names (`fifty-site-header`, `fifty-site-footer`, `fifty-site-title`) appear once per page; the per-post names use the post ID, which is unique inside a single archive page and trivially unique on a singular page.

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
