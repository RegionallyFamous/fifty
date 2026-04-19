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
6. **No raw WooCommerce frontend CSS bleeds through.** WC ships a lot of opinionated frontend CSS that survives a block theme (rounded "folder" product tabs, hard-coded notice colours, `.button` overrides, etc.). Any WC surface whose default markup is styled by `plugins/woocommerce/assets/css/woocommerce.css` MUST be re-styled in `theme.json` via `styles.blocks.<wc-block>.css` using project tokens, with the WC defaults explicitly nullified (`content: none`, `display: none`, `box-shadow: none`, `border-radius: 0`, etc. as needed). Known surfaces: `woocommerce/product-details` (the `.wc-tabs` block), `woocommerce/store-notices`, `woocommerce/cart`/`woocommerce/checkout` form rows, the legacy `.button` class. If you add a new theme variant, copy the full block override — never just the spacing/typography. The check script enforces this for the known surfaces.
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
11. Open the new theme's Playground deeplink (`https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/<org>/<repo>/main/<new_name>/playground/blueprint.json`) and walk the surface checklist before declaring done. The blueprint is part of the deliverable — see "WordPress Playground blueprints" below.

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

## Working on shared tooling

`bin/` is shared. Anything you change there affects every theme. After editing:

```bash
python3 bin/check.py --all --quick
```

`bin/_lib.py` contains the theme resolver (`resolve_theme_root`, `iter_themes`, `MONOREPO_ROOT`). Every script imports from it. New scripts should follow the same pattern: positional theme arg, `--all` flag where it makes sense, default to cwd if it contains `theme.json`.

## When in doubt

- Read the theme's `AGENTS.md` and `INDEX.md`.
- Ask `python3 bin/list-tokens.py --theme <theme>` before inventing a value.
- Ask `python3 bin/list-templates.py <theme>` before creating a new template.
- Run `python3 bin/check.py <theme>` before claiming you are done.
