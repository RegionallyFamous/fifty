# Playground — agent notes

This folder holds the **shared, theme-agnostic** scaffolding for every theme's
WordPress Playground demo. The actual content (products, pages, blog posts,
images) lives **per theme** under `<theme>/playground/`. Read this file before
editing anything in here, and before adding a new theme variant.

---

## Layout (post-refactor)

```
playground/                          # SHARED — no content lives here
  AGENTS.md                          # this file
  wo-import.php                      # generic WC catalogue importer (reads URLs from constants)
  wo-configure.php                   # generic WP/WC configurator (reads URLs from constants)
  wo-cart-mu.php                     # mu-plugin: pre-fills cart on ?demo=cart
  wo-pages-mu.php                    # mu-plugin: branded my-account + archive header (Phase D)
  wo-payment-icons-mu.php            # mu-plugin: payment-method icons in checkout (Phase C)
  wo-swatches-mu.php                 # mu-plugin: variation <select> -> swatches (Phase C)

<theme>/playground/                  # PER-THEME — content + assets + blueprint
  blueprint.json                     # auto-synced by bin/sync-playground.py
  content/
    products.csv                     # WC product catalogue for THIS theme
    content.xml                      # WXR (pages, posts, blog) for THIS theme
    category-images.json             # cat-name → image filename map for THIS theme
  images/                            # every binary attachment THIS theme references
    *.{png,jpg,jpeg,gif,webp,svg}    # product / page / post / category artwork
    *.{pdf,wav,mp3,mp4}              # downloadable attachments referenced from CSV/XML
```

## What each shared script does

| File | Type | Theme-aware? | Purpose |
| --- | --- | --- | --- |
| `wo-import.php` | `wp eval-file` | yes (constants) | Imports the per-theme `products.csv` into WooCommerce, sideloads images from `WO_CONTENT_BASE_URL`. |
| `wo-configure.php` | `wp eval-file` | yes (constants) | Sets WP/WC options (permalinks, store address, shipping, payment methods, `show_on_front`, blogname / tagline), seeds 5 sample orders, 12 reviews, the customer account. |
| `wo-cart-mu.php` | mu-plugin | no | Pre-fills the cart with two products when the URL contains `?demo=cart`. Drives the cart / checkout demo screenshots. |
| `wo-pages-mu.php` | mu-plugin | no | Wraps the my-account login form in a branded `wo-account-intro` panel (Phase D) and injects the editorial `wo-archive-hero` header on category / tag / shop archives. Tracked by `bin/snap_config.py::INSPECT_SELECTORS["my-account"]` and `["category"]`. |
| `wo-payment-icons-mu.php` | mu-plugin | no | Renders payment-method icons next to each gateway label in the WC Blocks checkout (Phase C). |
| `wo-swatches-mu.php` | mu-plugin | no | Replaces variation `<select>` elements on the PDP with colour-swatch / text-pill button groups, keeping the original select visually-hidden so WC's `variation_form` JS continues to drive price + stock + image swap (Phase C). See root `AGENTS.md` rule #11. |

The mu-plugins (`*-mu.php`) ship as `writeFile` steps in every blueprint that drop them into `wp-content/mu-plugins/` — no theme activation needed. The two `wp eval-file` scripts (`wo-import.php`, `wo-configure.php`) are inlined by `bin/sync-playground.py` with the per-theme constants block prepended.

When you add a new shared script:

1. Drop it in `playground/` with a `wo-*` prefix.
2. If it's a mu-plugin, end the filename in `-mu.php` so the sync script knows to write it to `mu-plugins/`.
3. If it needs theme-specific values, read them from `WO_THEME_NAME`, `WO_THEME_SLUG`, or `WO_CONTENT_BASE_URL` (mu-plugins don't get the constants block — it's only prepended to the `wp eval-file` scripts).
4. `python3 bin/sync-playground.py` to inline it into every blueprint.
5. If the new script affects rendered output, also extend `bin/snap_config.py::INSPECT_SELECTORS` so the visual gate proves it landed.

The folder name `images/` is the historical convention; in practice it holds
**every binary attachment** the per-theme CSV or XML points at, including
PDFs and audio (`imaginary-deed.pdf`, `one-hand.wav`, etc.). Any URL inside
`content/products.csv` or `content/content.xml` of the form
`https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/images/<file>`
is sideloaded by the importer; the file must exist in that theme's `images/`
folder.

---

## Why per-theme content

Every theme variant in the monorepo is supposed to look and feel
distinctively different. Until this refactor, all three themes pointed at
the same external `RegionallyFamous/wonders-oddities` repo for both the
product catalogue and the product photography, which meant a "brutalist"
theme and an "editorial menswear" theme rendered the **same product photos**.
That defeated the purpose of having visual variants.

Per-theme `content/` and `images/` make the per-theme blueprint
self-sufficient — it never reaches outside this monorepo for content — and
lets each theme diverge independently:

- Different product copy, different SKUs, different categories
- Different product photography that matches the theme's visual language
- Different page/post body text and hero imagery
- Optional: different category cover artwork via `category-images.json`

The `wo-*.php` scripts under this folder stay generic. They never embed a
theme name, a URL, or a per-theme image filename. Per-theme values flow in
through three constants supplied by `bin/sync-playground.py`.

---

## The three per-theme constants

`bin/sync-playground.py` prepends this block to every shared script body
when it inlines that script into a theme's `blueprint.json`:

```php
<?php
define( 'WO_THEME_NAME', 'Chonk' );
define( 'WO_THEME_SLUG', 'chonk' );
define( 'WO_CONTENT_BASE_URL',
    'https://raw.githubusercontent.com/RegionallyFamous/fifty/main/chonk/playground/' );
```

| Constant | Source | Used by |
| --- | --- | --- |
| `WO_THEME_NAME` | `theme.json` `title` (fallback: title-cased slug) | tagline / blogname strings in `wo-configure.php` |
| `WO_THEME_SLUG` | theme directory name | available for any future PHP that needs to compose URLs/paths |
| `WO_CONTENT_BASE_URL` | `https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<slug>/playground/` | `wo-import.php` (CSV URL), `wo-configure.php` (category-images map URL + image base URL) |

The shared scripts read these constants and **fall back to the upstream
wonders-oddities repo** if `WO_CONTENT_BASE_URL` is undefined, so a
developer can `wp eval-file wo-import.php` directly during local debugging
without going through the sync pipeline and still get a working catalogue.

---

## What `bin/sync-playground.py` rewrites in each blueprint

For every `<theme>/playground/blueprint.json` the script walks the `steps`
array and:

1. **`writeFile` steps for shared scripts** — replaces the `data` field
   with the current source from `playground/wo-*.php`. Only the two
   `wp eval-file` scripts (`wo-import.php`, `wo-configure.php`) get the
   per-theme constants block prepended (the set lives in
   `bin/sync-playground.py::TARGETS_NEEDING_CONSTANTS`); every mu-plugin
   (`wo-cart-mu.php`, `wo-pages-mu.php`, `wo-payment-icons-mu.php`,
   `wo-swatches-mu.php`) is inlined verbatim because it doesn't need
   theme-specific values. (Note: WC microcopy used to live here as
   `wo-microcopy-mu.php`; it now ships in each theme's `functions.php`
   between the `// === BEGIN wc microcopy ===` sentinels — see root
   `AGENTS.md` rules #10 and #16. Don't reintroduce a shared microcopy
   mu-plugin here; `check_no_brand_filters_in_playground` will fail.)
2. **`importWxr` step** — rewrites `file.url` to point at
   `<WO_CONTENT_BASE_URL>content/content.xml`.

Run it after **any** change to `playground/wo-*.php` and after **any** change
to a per-theme blueprint structure. The script is idempotent and prints
exactly what it changed.

---

## Adding a new theme variant

After cloning a new theme via `bin/clone.py <name>`, you have to:

1. Seed per-theme content for the new theme:
   ```bash
   python3 bin/seed-playground-content.py
   ```
   This populates `<name>/playground/content/{products.csv, content.xml,
   category-images.json}` and `<name>/playground/images/*` from the
   canonical `RegionallyFamous/wonders-oddities` source (cached at
   `/tmp/wonders-oddities-source` between runs). All image URLs inside the
   CSV and XML are rewritten to point at the new theme's `images/` folder.

2. Refresh blueprints so the new theme's constants and `importWxr` URL
   land in its `blueprint.json`:
   ```bash
   python3 bin/sync-playground.py
   ```

3. Generate the GH Pages short-URL redirector for the new theme:
   ```bash
   python3 bin/build-redirects.py
   ```
   This writes `docs/<name>/<page>/index.html` for every entry in the
   script's `PAGES` list. The new theme becomes reachable at
   `https://demo.regionallyfamous.com/<name>/` once the change
   is committed and pushed (Pages picks it up within ~1 minute). See
   the root `AGENTS.md` "GitHub Pages short URLs" section for the
   contract; you should never edit anything under `docs/` by hand.

4. Open the new theme's short URL and verify the surface checklist
   (front page, shop, single product, cart, checkout, blog post, 404).
   `https://demo.regionallyfamous.com/<name>/` redirects to the
   canonical Playground deeplink
   `https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<name>/playground/blueprint.json&url=/`,
   which is what to share when GH Pages is not yet enabled on a fork.

5. (Optional) Replace any seeded image with theme-styled artwork by
   dropping a same-named file into `<name>/playground/images/`. Re-running
   the seed script with `--force` will overwrite seeded files, but normal
   runs preserve any per-theme imagery already present (this is how
   `chonk/playground/images/` keeps its 59 generated PNGs across re-seeds).

---

## Editing a theme's content

The per-theme `content/` files are the **canonical source for that theme**
after the initial seed. Edit them in place: change product copy, swap SKUs,
rewrite the WXR pages, reshuffle the category-images map. Just keep the
image URL references inside CSV/XML pointing at this theme's
`<theme>/playground/images/<filename>` — and make sure the matching file
exists in `images/`.

Don't bring back a shared content folder. The whole point of this layout
is that each theme is free to diverge.

---

## Editing the shared `wo-*.php` scripts

When you change anything in `playground/wo-*.php`:

1. Edit the source file.
2. `python3 bin/sync-playground.py` — re-inlines into every theme's blueprint.
3. Commit both the source change and the resulting `*/playground/blueprint.json`
   diffs in the same commit.

The shared scripts must stay theme-agnostic. They should never:

- Embed a theme name (use `WO_THEME_NAME`).
- Embed a hardcoded image URL (compose from `WO_CONTENT_BASE_URL`).
- Hardcode a path that contains a theme slug (use `WO_THEME_SLUG` if the
  fallback URL doesn't suffice).
- Add a `<?php` opener — the constants block supplies it.

If a step is genuinely per-theme (e.g. the legacy `wo-patch-images.php`
workaround chonk used before this refactor), don't put it in shared
scaffolding — put it in that theme's blueprint directly, or better, fold
the divergence back into per-theme `content/` and `images/` so the shared
pipeline handles it.

---

## Permalinks gotcha

Inside a `wp eval-file` context (which is how `wo-configure.php` runs), the
global `$wp_rewrite` was constructed at WP boot from the previous
`permalink_structure` option. Calling `update_option(... '/%postname%/')`
followed by `flush_rewrite_rules()` will **not** work — it flushes the
**stale** in-memory state and produces default permalink rules, so every
pretty URL 404s.

The correct pattern (already in `wo-configure.php`) is:

```php
global $wp_rewrite;
$wp_rewrite->set_permalink_structure( '/%postname%/' );
$wp_rewrite->set_category_base( '' );
$wp_rewrite->set_tag_base( '' );
$wp_rewrite->flush_rules( true );
delete_option( 'rewrite_rules' );
```

If you ever rewrite the permalink-handling section, keep using
`WP_Rewrite::set_permalink_structure()` — it updates both the option
**and** the in-memory state via `init()`. The trailing `delete_option()`
forces the next frontend hit to lazily rebuild the rules in case a plugin
loaded after `$wp_rewrite` registers a permastruct mid-request.
