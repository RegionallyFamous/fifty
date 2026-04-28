# Changelog

Versions follow [Semantic Versioning](https://semver.org/). Append new entries to the top.

## 1.0.0

Initial release.

A block-only WooCommerce starter theme. All visual styling lives in `theme.json`. No custom CSS files, no custom blocks, no patterns library that ships activated by default. The intended workflow is to copy the theme folder, rename it for the project, and edit `theme.json`.

### Templates and parts

- WordPress templates: `index`, `home`, `front-page`, `singular`, `single`, `page`, `archive`, `category`, `tag`, `author`, `date`, `taxonomy`, `search`, `404`.
- WooCommerce templates: `single-product`, `archive-product` (also handles `product_cat` / `product_tag` / `product_attribute` archives via the WP template hierarchy fallback), `product-search-results`, `page-cart`, `page-checkout`, `order-confirmation`, `page-coming-soon`.
- Custom page templates: `page-no-title`, `page-full-width`, `page-landing`.
- Template parts: `header`, `checkout-header`, `footer`, `comments`, `post-meta`, `product-meta`, `no-results`.

### Design system (`theme.json`)

- Single source of truth for color, typography, spacing, shadow, radius, border, layout, line-height, letter-spacing, font-weight, transition, cover height, and aspect-ratio tokens.
- ~100 block style entries covering every `core/*` and `woocommerce/*` block referenced by the templates.
- Block style variations: `core/group` (`card`, `panel`, `callout`, `surface`), `core/button` (`outline`), `core/separator` (`wide`, `dots`).
- `core/image` lightbox enabled by default.
- Three style variations in `styles/`: `dark`, `editorial`, `high-contrast`.

### Edit-one-value-ripples-everywhere tokens

Every layout width, cover height, and aspect ratio used in markup is a CSS variable. Editing one value in `theme.json` propagates through every template, part, and pattern.

- `settings.layout.contentSize` (720px) drives every prose-width container; templates do not override it.
- `settings.layout.wideSize` (1280px) is referenced via `var(--wp--style--global--wide-size)` in header, footer, checkout-header, and front-page sections.
- `settings.custom.layout` defines `narrow` (480px), `prose` (560px), `comfortable` (640px) for special containers.
- `settings.custom.cover` defines `hero` (640px), `promo` (520px), `tile` (320px) for cover `min-height`.
- `settings.custom.aspect-ratio` defines `square`, `portrait`, `card`, `widescreen` for `core/post-featured-image` and `woocommerce/product-image`.
- `settings.custom.border.width` defines `hairline` (1px), `thick` (2px).

### Starter patterns

Eleven generic patterns in `patterns/`: `hero-image`, `hero-text`, `featured-products`, `value-props`, `faq-accordion`, `testimonials`, `brand-story`, `newsletter`, `cta-banner`, `footer-columns`, `category-tiles`. Six pattern categories registered: `batik`, `woo-commerce`, `featured`, `call-to-action`, `testimonials`, `footer`.

### Tooling (`bin/`)

- `check.py` — single-command validator. Runs JSON validity, PHP syntax, block-name validity (against Gutenberg + WooCommerce trunk), `INDEX.md` freshness, `!important` scan, stray-`.css` scan, block-namespace scan, AI-fingerprint scan, hardcoded-color scan, hardcoded-dimensions scan, block-attribute-token enforcement, and duplicate-template scan.
- `build-index.py` — regenerates `INDEX.md`, the auto-generated single-file project map.
- `list-tokens.py` — prints every design token in `theme.json`.
- `list-templates.py` — prints every template alongside the URL pattern it handles.
- `validate-theme-json.py` — verifies every block name in `theme.json` against the Gutenberg and WooCommerce sources.
- `clone.py` — cross-platform script to copy and rename the theme for a new project.

### Documentation

- `README.md`, `INDEX.md` (auto-generated), `SYSTEM-PROMPT.md` (paste-in for any LLM), `AGENTS.md` (full constraints + workflow recipes).
- Long-form docs (Architecture, Project Structure, Design Tokens, Recipes, Anti-Patterns, Block Reference, Templates, WooCommerce Integration, Style Variations, Working with LLMs, Tooling, Contributing, FAQ) live in the [project wiki](https://github.com/RegionallyFamous/Batik/wiki).
- `_examples/` stubs for new patterns, style variations, and templates.

### Theme support

- `appearanceTools: true`, `useRootPaddingAwareAlignments: true`, `defaultPalette: false`, `defaultGradients: false`, `defaultDuotone: false`, `defaultFontSizes: false`.
- `add_theme_support` for `post-formats` and full `html5` (`comment-list`, `comment-form`, `search-form`, `gallery`, `caption`, `style`, `script`, `navigation-widgets`).

### Requirements

- WordPress 6.8 or higher
- PHP 8.2 or higher
- WooCommerce 10.0 or higher (for the canonical `page-cart` and `page-checkout` template slugs)
