=== Lab-decant ===
Contributors: lab-decant
Tags: block-styles, full-site-editing, wide-blocks, e-commerce, one-column, two-columns, custom-colors, featured-images, threaded-comments, translation-ready
Requires at least: 6.8
Tested up to: 6.9
Requires PHP: 8.2
Stable tag: 1.0.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

A block-only WooCommerce starter theme. All styling is defined in theme.json. No custom CSS, no custom blocks, no patterns library.

== Description ==

Lab-decant is a block (FSE) theme for WordPress and WooCommerce stores. It ships full template coverage for both, composed entirely of core WordPress blocks and core WooCommerce blocks. All visual styling lives in theme.json. There is no custom CSS, no custom blocks, and no patterns library.

The intended workflow is to copy the theme folder, rename it for the project, and edit theme.json to set the brand. Templates do not need to change to take on the new look.

= Templates included =

WordPress templates: index, home, front-page, singular, single, page, archive, category, tag, author, date, taxonomy, search, 404.

WooCommerce templates: single-product, archive-product (also handles product_cat / product_tag / product_attribute archives via the WP template hierarchy fallback), product-search-results, page-cart, page-checkout, order-confirmation, page-coming-soon.

Template parts: header, checkout-header, footer, comments, post-meta, product-meta, no-results.

= Requirements =

* WordPress 6.8 or higher
* PHP 8.2 or higher
* WooCommerce 10.0 or higher

These minimums target new shops. Existing stores on older stacks should upgrade WordPress, PHP, and WooCommerce before activating this theme.

== Installation ==

1. Upload the `lab-decant` folder to `/wp-content/themes/`.
2. Activate the theme in *Appearance > Themes*.
3. Install and activate WooCommerce if you want the storefront templates to render.

== Frequently Asked Questions ==

= Does this theme support classic WooCommerce templates? =

No. Lab-decant is block-only. It supports the Cart, Checkout, Mini-Cart, Product Collection, and Product Filters blocks. It does not include classic PHP templates or shortcode-based cart/checkout pages.

= Why no patterns? =

Patterns tend to be project-specific. Lab-decant is a starter, so patterns belong in the per-project clone rather than in the framework.

= How do I customize the look? =

Open *Appearance > Editor > Styles* in the WordPress admin to adjust colors, typography, and spacing visually. For deeper changes, edit `theme.json` directly. There is no other styling layer.

= Can I add custom CSS? =

Lab-decant ships with zero custom CSS by design. If you must add CSS, use *Appearance > Editor > Styles > Additional CSS*, or use the `styles.blocks.<name>.css` escape hatch in `theme.json` (WordPress 6.6+).

== Copyright ==

Lab-decant WordPress Theme, (C) 2026 Lab-decant.
Lab-decant is distributed under the terms of the GNU GPL v2 or later.

This theme bundles the following resources:

* No third-party fonts. Typography uses system font stacks declared in theme.json.
* No third-party images. The screenshot is an original work released under GPLv2.

== Changelog ==

= 1.0.0 =
* Initial release.
* WordPress templates: index, home, front-page, singular, single, page, archive, category, tag, author, date, taxonomy, search, 404.
* WooCommerce templates: single-product, archive-product (also handles product_cat / product_tag / product_attribute via the WP template hierarchy fallback), product-search-results, page-cart, page-checkout, order-confirmation, page-coming-soon.
* Custom page templates: page-no-title, page-full-width, page-landing.
* Template parts: header, checkout-header, footer, comments, post-meta, product-meta, no-results.
* theme.json with the full design token system (color, typography, spacing, shadow, radius, border-width, layout, line-height, letter-spacing, font-weight, transition, cover height, aspect-ratio) and ~100 block style entries covering every core and WooCommerce block used.
* Edit-one-value-ripples-everywhere: every layout width, cover height, and aspect ratio in markup is a CSS variable. Editing a single value in theme.json propagates through every template, part, and pattern.
* Block style variations: core/group (card, panel, callout, surface), core/button (outline), core/separator (wide, dots).
* core/image lightbox enabled by default.
* Three style variations in styles/: dark, editorial, high-contrast.
* Eleven starter patterns: hero-image, hero-text, featured-products, value-props, faq-accordion, testimonials, brand-story, newsletter, cta-banner, footer-columns, category-tiles. Six pattern categories registered.
* Tooling in bin/: check.py (single-command validator with 12 checks), build-index.py (regenerates INDEX.md), list-tokens.py, list-templates.py, validate-theme-json.py, clone.py.
* Docs: README.md, INDEX.md (auto-generated), SYSTEM-PROMPT.md, AGENTS.md in the repo. Long-form docs (Architecture, Design Tokens, Recipes, Anti-Patterns, Block Reference, WooCommerce Integration, Style Variations, Tooling, FAQ) in the project wiki at github.com/RegionallyFamous/Lab-decant/wiki.
* _examples/ stubs for new patterns, style variations, and templates.
