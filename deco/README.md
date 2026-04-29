# Deco

The loud cousin of [Obel](https://github.com/RegionallyFamous/Obel). Same architecture, different attitude.

Cream backgrounds. Pure black 3px borders. Hard 6px offset shadows. Square corners. Big ugly-beautiful display type. A storefront that yells.

One `theme.json` file. Zero CSS. Zero JS. Zero build step. You edit a token, the whole storefront re-skins.

## What makes it Deco

```
■ Cream base (#F5F1E8) and pure black (#000) everywhere
■ Electric yellow (#FFE600) primary accent
■ Hot pink (#FF3C8A) secondary accent
■ Cobalt blue (#1F4FE0) tertiary accent
■ Hard offset shadows (no blur, no softness, ever)
■ Square corners (radius tokens all resolve to 0)
■ Heavy display sans on every heading, uppercase by default
■ Bold buttons with chunky borders that flatten on press
```

Want a different palette or shape? Open `theme.json`, change the tokens, save. The framework is identical to Obel; only the values are different.

## What you get

```
✓ Every WordPress page covered (single, page, archive, category, tag, author, date, search, 404...)
✓ Every WooCommerce page covered (single-product, shop, cart, checkout, order-confirmation, coming-soon...)
✓ ~100 block style entries in theme.json (everything wired up)
✓ 11 starter patterns (hero, FAQ, newsletter, brand story, value props, more)
✓ 3 style variations (dark, editorial, high-contrast)
✓ A clone script that bootstraps a new branded theme in 60 seconds
✓ A check script that catches every common mistake before you ship
```

```
✗ No CSS files (style.css holds only the theme header)
✗ No custom blocks (only core/* and woocommerce/*)
✗ No JS bundle, no package.json, no webpack
✗ No PHP outside functions.php (which is ~50 lines)
✗ No external dependencies
```

The whole framework is small enough to read in an afternoon and rebrand in 20 minutes. That is unusual for a WooCommerce theme. It is also the whole point.

## Why it is fun to work in

The fastest feedback loop in WordPress theme work. You save `theme.json`, hit reload in the Site Editor, and the whole site is restyled. No `npm run watch`. No SCSS compile step. No PurgeCSS step. No browser cache hassle. The block editor reads `theme.json` directly and updates live.

Once you have worked this way you do not go back.

## Requirements

- WordPress 6.8 or higher
- PHP 8.2 or higher
- WooCommerce 10.0 or higher (for the canonical `page-cart` and `page-checkout` template slugs)

## Install

```bash
cd wp-content/themes
git clone https://github.com/RegionallyFamous/Deco.git deco
```

Then activate Deco in *Appearance > Themes*. If WooCommerce is installed, the storefront templates start rendering immediately.

## Make your first edit

Open `theme.json`. Find the `accent` color in `settings.color.palette`:

```json
{ "slug": "accent", "name": "Accent", "color": "#B66E3C" }
```

Change `#B66E3C` to anything (try `#0B6E4F` for a forest green). Save. Reload any page. The links, sale prices, ratings stars, and accent backgrounds all change. That is the loop.

## Bootstrap a new shop

Do not edit Deco directly for a real project. Clone it:

```bash
python3 bin/clone.py acme
```

Copies the theme to `../acme/`, renames every `Deco`/`deco` reference inside editable files, and prints next steps. Cross-platform (macOS, Linux, Windows). See `bin/clone.py --help` for options.

Then edit `theme.json` to set the brand. Templates do not need to change.

## Documentation

Long-form docs live in the [Deco Wiki](https://github.com/RegionallyFamous/Deco/wiki):

- [Getting Started](https://github.com/RegionallyFamous/Deco/wiki/Getting-Started) - install, clone, first edit
- [Architecture](https://github.com/RegionallyFamous/Deco/wiki/Architecture) - the philosophy, the five hard rules
- [Project Structure](https://github.com/RegionallyFamous/Deco/wiki/Project-Structure) - every file and what it does
- [Design Tokens](https://github.com/RegionallyFamous/Deco/wiki/Design-Tokens) - the vocabulary of the design system
- [Recipes](https://github.com/RegionallyFamous/Deco/wiki/Recipes) - 15 step-by-step common tasks
- [Block Reference](https://github.com/RegionallyFamous/Deco/wiki/Block-Reference) - every block grouped by purpose
- [Templates](https://github.com/RegionallyFamous/Deco/wiki/Templates) - what each template covers
- [WooCommerce Integration](https://github.com/RegionallyFamous/Deco/wiki/WooCommerce-Integration) - deep guide to every WC surface
- [Style Variations](https://github.com/RegionallyFamous/Deco/wiki/Style-Variations) - how to build whole-theme looks
- [Anti-Patterns](https://github.com/RegionallyFamous/Deco/wiki/Anti-Patterns) - 17 mistakes to avoid
- [Working with LLMs](https://github.com/RegionallyFamous/Deco/wiki/Working-with-LLMs) - using Claude, ChatGPT, Cursor, etc.
- [Tooling](https://github.com/RegionallyFamous/Deco/wiki/Tooling) - every script in `bin/` explained
- [Contributing](https://github.com/RegionallyFamous/Deco/wiki/Contributing) - how to send a PR
- [FAQ](https://github.com/RegionallyFamous/Deco/wiki/FAQ) - quick answers

In-repo files for AI agents:

- `INDEX.md` - auto-generated single-file project map
- `SYSTEM-PROMPT.md` - paste-in system prompt for any LLM
- `AGENTS.md` - the contract: hard rules + workflow recipes
- `CHANGELOG.md` - per-version change log

## The hard rules

These are not preferences. They define what Deco is.

1. **No CSS files.** `style.css` is just the theme header. No other stylesheets. No `<style>` tags. No `wp_enqueue_style`.
2. **No `!important`.** Anywhere. The block style engine handles specificity.
3. **Only `core/*` and `woocommerce/*` blocks.** No custom block registration. No third-party block prefixes.
4. **No build step.** No `package.json`, no JS bundles, no Composer dependencies.
5. **`theme.json` is the single source of truth for styling.** Every visual change goes through it.

If a request requires breaking one, the request needs to change, not the rule. See [Architecture](https://github.com/RegionallyFamous/Deco/wiki/Architecture) for the full reasoning.

## Validate your changes

Run a single command:

```bash
python3 bin/check.py            # full check (online; validates block names against trunk)
python3 bin/check.py --quick    # offline subset
```

Twelve checks: JSON validity, PHP syntax, block-name validity, `INDEX.md` freshness, `!important` scan, stray-CSS scan, block-namespace scan, marketing-fluff scan, hardcoded-color scan, hardcoded-dimensions scan, block-attribute-token enforcement, duplicate-template scan.

Exit code 0 if everything passes.

## Working with an LLM

Paste [`SYSTEM-PROMPT.md`](SYSTEM-PROMPT.md) into your assistant's system prompt at the start of any session. The prompt tells the assistant to read [`INDEX.md`](INDEX.md) first, which gives it the entire project structure (files, tokens, block styles, patterns, variations) in one read.

After any change that adds or removes files (or edits `theme.json`), regenerate the index:

```bash
python3 bin/build-index.py
python3 bin/check.py --quick
```

The "INDEX.md in sync" check fails if you forget. See [Working with LLMs](https://github.com/RegionallyFamous/Deco/wiki/Working-with-LLMs) for more.

## Template inventory

### WordPress

| Template          | Purpose                              |
| ----------------- | ------------------------------------ |
| `index.html`      | Universal fallback                   |
| `home.html`       | Blog index                           |
| `front-page.html` | Static front page                    |
| `singular.html`   | Shared single-entity fallback        |
| `single.html`     | Single post                          |
| `page.html`       | Single page                          |
| `archive.html`    | Generic archive                      |
| `category.html`   | Category archive                     |
| `tag.html`        | Tag archive                          |
| `author.html`     | Author archive                       |
| `date.html`       | Date archive                         |
| `taxonomy.html`   | Custom taxonomy archive              |
| `search.html`     | Search results                       |
| `404.html`        | Not found                            |

### WooCommerce

| Template                          | Purpose                               |
| --------------------------------- | ------------------------------------- |
| `single-product.html`             | Single product                        |
| `archive-product.html`            | Shop / catalog (also handles `product_cat`, `product_tag`, and `product_attribute` archives via the WP template hierarchy fallback) |
| `product-search-results.html`     | Product search results                |
| `page-cart.html`                  | Cart                                  |
| `page-checkout.html`              | Checkout                              |
| `order-confirmation.html`         | Order received                        |
| `page-coming-soon.html`           | Coming-soon mode landing              |

### Template parts

| Part                  | Purpose                                  |
| --------------------- | ---------------------------------------- |
| `header.html`         | Primary header (with mini-cart inline)   |
| `checkout-header.html`| Minimal header for checkout flow         |
| `footer.html`         | Site footer                              |
| `comments.html`       | Comments thread and form                 |
| `post-meta.html`      | Post date, author, categories            |
| `product-meta.html`   | Product SKU, categories, tags            |
| `no-results.html`     | Shared empty-state                       |

## Try in Playground

Each link below opens a disposable WordPress + WooCommerce install with Deco active and the [Wonders & Oddities](https://github.com/RegionallyFamous/wonders-oddities) dataset pre-loaded. Nothing to install locally. Expect 60 to 90 seconds on first boot while the dataset and images download.

The blueprint also seeds: a working checkout (Flat Rate + Free shipping, COD + Bank Transfer payments), a sample customer account, 5 orders in varied statuses, 2 variable products, on-sale / out-of-stock / backorder states, and 12 product reviews.

Default login: `admin` / `password`. To check the customer dashboard, log out and sign in as `customer` / `customer`.

| Page | Short URL | Long URL (what the short URL redirects to) |
| --- | --- | --- |
| Home | [`deco/`](https://demo.regionallyfamous.com/deco/) | [/](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/) |
| Shop | [`deco/shop/`](https://demo.regionallyfamous.com/deco/shop/) | [/shop/](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/shop/) |
| Single product | [`deco/product/bottled-morning/`](https://demo.regionallyfamous.com/deco/product/bottled-morning/) | [/product/bottled-morning/](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/product/bottled-morning/) |
| Cart (pre-filled) | [`deco/cart/`](https://demo.regionallyfamous.com/deco/cart/) | [/cart/?demo=cart](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/cart/?demo=cart) |
| Checkout | [`deco/checkout/`](https://demo.regionallyfamous.com/deco/checkout/) | [/checkout/?demo=cart](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/checkout/?demo=cart) |
| My Account | [`deco/my-account/`](https://demo.regionallyfamous.com/deco/my-account/) | [/my-account/](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/my-account/) |
| Journal | [`deco/journal/`](https://demo.regionallyfamous.com/deco/journal/) | [/journal/](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/journal/) |
| 404 | [`deco/404/`](https://demo.regionallyfamous.com/deco/404/) | [/this-route-does-not-exist/](https://playground.wordpress.net/?blueprint-url=https://raw.githubusercontent.com/RegionallyFamous/fifty/main/deco/playground/blueprint.json&url=/this-route-does-not-exist/) |

The blueprint lives at [`deco/playground/blueprint.json`](playground/blueprint.json).

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
