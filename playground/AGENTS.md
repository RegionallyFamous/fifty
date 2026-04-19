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
  wo-cart-mu.php                     # mu-plugin: pre-fills cart on ?demo=cart
  wo-import.php                      # generic WC catalogue importer (reads URLs from constants)
  wo-configure.php                   # generic WP/WC configurator (reads URLs from constants)

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
   with the current source from `playground/wo-*.php`, prepending the
   constants block above (except for `wo-cart-mu.php`, which is theme-
   agnostic and constant-free).
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

3. Open the new theme's deeplink and verify the surface checklist (front
   page, shop, single product, cart, checkout, blog post, 404). The
   blueprint URL is
   `https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<name>/playground/blueprint.json`.

4. (Optional) Replace any seeded image with theme-styled artwork by
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
