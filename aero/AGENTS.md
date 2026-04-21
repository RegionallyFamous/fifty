# AGENTS.md — Aero

> Aero is one theme inside the **Fifty monorepo**. The monorepo lives one directory up; its `AGENTS.md` (`../AGENTS.md`) and `README.md` (`../README.md`) describe the layout and the rules that apply to every theme. Read this file for Aero-specific rules. Tooling lives in `../bin/`.

Instructions for AI coding agents working on the Aero theme. Read this file in full before making any changes. Human-oriented docs live in `README.md` and the [project wiki](https://github.com/RegionallyFamous/Fifty/wiki).

## Required reading order

1. **`INDEX.md`** -- auto-generated map of every template, part, pattern, style variation, design token, and block style entry. Read this first; it tells you what exists without reading individual files.
2. This file (constraints + workflow).
3. `README.md` (human-facing overview with the project quickstart and links to deeper docs).

For deeper task-specific reference, read the wiki on demand. The relevant pages are listed below under "Where to find more detail".

## Tools you should use

| Command | What it does |
|---|---|
| `python3 ../bin/check.py` | Run every project check. Use this before declaring "done". |
| `python3 ../bin/check.py --quick` | Same, skipping the network-dependent block-name check. |
| `python3 ../bin/check.py --visual` | Run the static checks AND the snap-gated visual regression sweep (`snap.py shoot + diff + report --strict`). Tiered gate; exits 1 only on `fail`. Recommended pre-commit gate after any change to templates, parts, patterns, theme.json, or playground content. |
| `python3 ../bin/snap.py doctor` | One-time check that Pillow, Playwright/Chromium, npx, axe-core, and baseline coverage are all wired up. Run after a fresh clone or Python upgrade. |
| `python3 ../bin/snap.py shoot --routes <route> --viewports <viewport>` | Capture a single (route × viewport) PNG into `tmp/snaps/` for the inner edit loop. `Read` the resulting PNG to verify the change. |
| `python3 ../bin/snap.py serve` | Boot this theme's WordPress Playground locally on `http://localhost:9400/` so you can drive it interactively (admin auto-login enabled). |
| `python3 ../bin/build-index.py` | Regenerate `INDEX.md` after adding/removing files or editing `theme.json`. |
| `python3 ../bin/list-tokens.py` | Print every design token in `theme.json`. (`INDEX.md` already contains this; use this script for fresh output if `INDEX.md` is stale.) |
| `python3 ../bin/validate-theme-json.py` | Verify every `core/*` and `woocommerce/*` block name in `theme.json` against trunk. |
| `python3 ../bin/clone.py NEW_NAME` | Clone Aero into a new theme folder, renaming all identifiers. |
| `python3 ../bin/list-templates.py` | Print every template file alongside the WordPress URL it handles. Paste output into LLM context to find the right file without reading the directory. |

If you remember nothing else from this file: **read `INDEX.md` first, run `python3 ../bin/check.py --visual` last** (or `--quick` for a fast offline subset that skips the visual sweep).

## What this project is

Aero is a block-only WooCommerce starter theme for WordPress. It is intended to be copied (use `python3 ../bin/clone.py NEW_NAME`) and then customized by editing `theme.json` and adding project-specific patterns. The framework itself is deliberately small.

## Hard rules — never violate

These rules are not preferences. They define what this theme *is*. Do not break them, even if the user's request would be easier to fulfill by breaking them. If a request requires breaking a rule, push back and propose an alternative.

1. **No CSS files.** `style.css` exists only for the WordPress theme header. Do not create any other `.css` file. Do not add `<style>` tags. Do not enqueue stylesheets.
2. **No `!important`.** Anywhere. The block style engine handles specificity; `!important` is a sign that the design tokens or block scope are wrong.
3. **No custom blocks.** Use only blocks shipped by WordPress core (`core/*`) or WooCommerce core (`woocommerce/*`). Do not register new block types in PHP or JS.
4. **No JavaScript bundles.** No `package.json`, no `webpack`, no build step. Pure PHP + JSON + HTML.
5. **`theme.json` is the single source of truth for styling.** Every visual change goes through `theme.json` — global tokens, element styles, or per-block `styles.blocks.*` entries.
6. **All block names must be real.** Verify every `core/*` and `woocommerce/*` key against the Gutenberg / WooCommerce source before adding it. Run `../bin/validate-theme-json.py` after editing `theme.json`. Past mistakes (`core/time-to-read` instead of `core/post-time-to-read`, etc.) cost real time.
7. **No marketing fluff in user-facing text.** Plain, factual prose. No em-dashes (`—`), no triadic constructions ("clean, fast, beautiful"), no "leverage / robust / comprehensive / seamless" vocabulary. The check script enforces this on `README.md`, `readme.txt`, and `style.css`.
8. **Web fonts must be self-hosted from Google Fonts.** System font stacks are always allowed and are the default. If a font outside the system stack is needed, it must be a Google Fonts family downloaded as `.woff2` into `assets/fonts/` and registered via `theme.json` `settings.typography.fontFamilies[*].fontFace[*].src` as `file:./assets/fonts/<file>.woff2`. Forbidden: any reference to `fonts.googleapis.com`, `fonts.gstatic.com`, `<link rel="preconnect">` to a font CDN, `@import url('https://fonts...')`, Adobe Typekit, Bunny Fonts, custom CDNs, or any other remote font URL. The check script enforces this. Reasons: privacy (no third-party requests), performance (no DNS / TLS to a CDN before first paint), license clarity (Google Fonts SIL OFL is project-safe; arbitrary CDNs aren't), offline editability (the Site Editor must render the variant correctly with no network).
9. **Never render `wp:woocommerce/product-details`.** That umbrella block ships WC's hardcoded rounded "folder" tabs (Description / Additional Information / Reviews) — the single biggest "this is a default WooCommerce store" tell on a PDP, and Baymard's UX research shows that tab-hidden content is ignored by 50%+ of users. Premium PDPs (Apple, Aesop, Glossier, Hermès, Lululemon) ship stacked sections or native `<details>` accordions instead. The canonical pattern in this monorepo: render the description always-visible via `wp:woocommerce/product-description`, then one `wp:details` (`core/details`) per collapsible section, with `wp:woocommerce/product-reviews` living inside one of them. `core/details` is a pure core block (WP 6.3+), zero JS, native keyboard / screen-reader / print / SEO behavior, search engines index closed content. Theme each variant by setting `styles.blocks["core/details"]` in `theme.json` — block-scoped `css` is safe here because the only thing it competes with is the browser's user-agent stylesheet (no WC plugin CSS). The check `check_no_wc_tabs_block` enforces both halves: it fails if any template / part / pattern references `wp:woocommerce/product-details`, AND it fails if `theme.json` still has a stale `styles.blocks["woocommerce/product-details"]` entry. Secondary point — for any *other* WC surface you ever do have to override (cart form rows, store-notices, the legacy `.button` class), the WC override MUST live in top-level `styles.css`, not `styles.blocks.<x>.css`: WP wraps block-scoped css in `:root :where(<block-selector>) { ... }`, and `:where()` has specificity zero, so the entire block.css string ends up at `(0,0,1)` — WC's `(0,4,3)` plugin CSS dwarfs it. Top-level `styles.css` is emitted verbatim and wins the cascade by load order (theme after plugin). `check_wc_overrides_styled` enforces that for any registered WC surface (currently empty — the tabs surface was retired by `check_no_wc_tabs_block`).

## Allowed dependencies

- WordPress 6.8 or newer
- PHP 8.2 or newer
- WooCommerce 10.0 or newer

Anything else (Composer packages, NPM packages, external libraries) is forbidden in the framework. Project clones may add what they need.

## Where to put things

| Change | Goes in |
|---|---|
| Color, font, spacing, shadow, radius, transition tokens | `theme.json` → `settings.color` / `settings.typography` / `settings.spacing` / `settings.shadow` / `settings.custom` |
| Default styling for an HTML element (h1–h6, link, button, caption, cite) | `theme.json` → `styles.elements.*` |
| Default styling for a specific block | `theme.json` → `styles.blocks.<block-name>` |
| A named visual variant of a block (e.g. button outline, separator dots) | `theme.json` → `styles.blocks.<block-name>.variations.<name>` |
| A whole-theme look (e.g. dark mode, editorial) | A new file in `styles/` (style variation JSON) |
| A reusable layout the user can insert | A new `.php` file in `patterns/` |
| A page layout (front-page, cart, etc.) | A `.html` file in `templates/` |
| A reusable region (header, footer) | A `.html` file in `parts/` |
| Theme bootstrap (`add_theme_support`, pattern category registration) | `functions.php` — keep it minimal |
| Translation strings | `languages/` |
| Project tooling (validators, clone script) | `bin/` |
| Copy-from stubs for new files | `_examples/` |
| Long-form docs for humans | The [project wiki](https://github.com/RegionallyFamous/Aero/wiki). Do not commit Markdown docs into the repo (other than `README.md`, `INDEX.md`, `SYSTEM-PROMPT.md`, `AGENTS.md`, `CHANGELOG.md`). |
| Paste-in system prompt for any LLM | `SYSTEM-PROMPT.md` |

## Workflow for common tasks

### Restyling the theme

1. Edit `theme.json`. Start with `settings.color.palette` and `settings.typography.fontFamilies`. Do not edit individual `styles.blocks.*` unless a block needs to deviate from the global tokens.
2. Run `../bin/validate-theme-json.py` to confirm all block names still exist.
3. Test in a real WP install (or wp-env / Playground). The site editor at `/wp-admin/site-editor.php` is the primary preview surface.

### Adding a new pattern

1. Create `patterns/my-pattern.php` with the standard WP pattern header (see existing files in `patterns/`).
2. Use only `core/*` and `woocommerce/*` blocks in the markup.
3. Reference design tokens via the `var:preset|...` syntax inside block attributes, never hardcoded colors or pixel values.
4. Set `Categories: aero-store` for project-style patterns or another registered category.
5. Set `Block Types: core/post-content` to make it inserter-available in the post-content area.

### Adding a new style variation

1. Create `styles/my-variation.json`. Schema is the same as `theme.json` but only the keys you want to override.
2. Variations should override `settings.color.palette` and possibly `settings.typography` and `styles.elements`. Avoid overriding individual `styles.blocks.*` unless necessary.
3. Add a `title` field at the top so it appears with a friendly name in the global styles UI.

### Adding styling for a new core block

1. **Verify the block name exists** by checking [the Gutenberg source](https://github.com/WordPress/gutenberg/tree/trunk/packages/block-library/src). The folder name is the block slug.
2. Add the entry under `styles.blocks.<core/blockname>` in `theme.json`.
3. Use design tokens (`var(--wp--preset--color--*)`, `var(--wp--preset--font-size--*)`, `var(--wp--preset--spacing--*)`, `var(--wp--custom--*)`) — never hardcode values.
4. Run `../bin/validate-theme-json.py`.

### Cloning Aero for a new project

Use `../bin/clone.py` (cross-platform Python script). The script handles macOS, Linux, and Windows.

```bash
python3 ../bin/clone.py acme            # clones into ../acme
python3 ../bin/clone.py acme --target ~/Projects
python3 ../bin/clone.py --help
```

### Scaffolding a new pattern, style variation, or template

Copy from `_examples/`:

```bash
cp _examples/pattern.php.txt patterns/your-slug.php
cp _examples/style-variation.json.txt styles/your-name.json
cp _examples/template.html.txt templates/your-template.html
```

Then update the header (slug, title, description) and replace the body with your content. The `.txt` suffix is intentional and prevents WordPress from loading the stubs.

## Where to find more detail

For deeper reference, point the user (or read directly via `WebFetch` if you can) at the [project wiki](https://github.com/RegionallyFamous/Aero/wiki):

| Topic | Wiki page |
|---|---|
| Project structure (every file, what it does) | [Project-Structure](https://github.com/RegionallyFamous/Aero/wiki/Project-Structure) |
| Design tokens (which slug to use when) | [Design-Tokens](https://github.com/RegionallyFamous/Aero/wiki/Design-Tokens) |
| Step-by-step recipes for common tasks | [Recipes](https://github.com/RegionallyFamous/Aero/wiki/Recipes) |
| Bad-code/good-code pairs | [Anti-Patterns](https://github.com/RegionallyFamous/Aero/wiki/Anti-Patterns) |
| Inventory of every block referenced | [Block-Reference](https://github.com/RegionallyFamous/Aero/wiki/Block-Reference) |
| WooCommerce template guide | [WooCommerce-Integration](https://github.com/RegionallyFamous/Aero/wiki/WooCommerce-Integration) |
| Architecture and philosophy | [Architecture](https://github.com/RegionallyFamous/Aero/wiki/Architecture) |
| Style variation guide | [Style-Variations](https://github.com/RegionallyFamous/Aero/wiki/Style-Variations) |
| Tooling reference | [Tooling](https://github.com/RegionallyFamous/Aero/wiki/Tooling) |

## Glossary of design tokens

The full token reference is in `theme.json` (`settings.*`) and summarized in `INDEX.md`. **Do not introduce new token slugs** for project clones unless you also document them in the wiki. Prefer reusing existing slugs over inventing new ones.

## Things that look like good ideas but aren't

- **Adding `add_editor_style()`.** The theme has no CSS by design. There is nothing to load.
- **Registering block styles in PHP via `register_block_style()`.** Use `theme.json` → `styles.blocks.*.variations` instead. Single source of truth.
- **Inlining CSS in HTML templates via `<style>` blocks.** The block markup in templates already contains `style="..."` attributes from the block editor; that's fine. Free-standing `<style>` blocks are not.
- **Using the `css` escape hatch in `theme.json` for layout fixes.** Only use `css` when the block style engine literally cannot express the design (e.g. negative-margin tricks for accordion border collapse). If you find yourself reaching for `css` more than 2-3 times, reconsider the design.
- **Switching to `woocommerce/add-to-cart-with-options` in `single-product.html`** before WooCommerce switches its own canonical template. Stay aligned with the WC trunk template at `plugins/woocommerce/templates/templates/single-product.html`.
- **Adding emojis to user-facing text or commit messages.** WP core themes don't, and Automattic reviewers notice.

## Validation checklist (run before declaring "done")

```bash
python3 ../bin/check.py            # full check (online; validates block names)
python3 ../bin/check.py --quick    # offline subset (skip block-name network check)
python3 ../bin/check.py --visual   # static checks + snap-gated visual regression sweep
                                   # (default scope: --visual-scope=changed; use =all
                                   #  before a release, or =quick for a single-theme smoke test)
```

`../bin/check.py` runs every check the project cares about: JSON validity, PHP syntax, block-name validity, `INDEX.md` freshness, `!important` scan, stray-CSS scan, block-namespace scan, AI-fingerprint scan, hardcoded-color scan, hardcoded-dimensions scan, block-attribute-token enforcement, duplicate-template scan. Output is one line per check. Exit code 0 if all pass.

For a deeper dive into individual checks, see the script source.

## When in doubt

1. Run `python3 ../bin/list-tokens.py` to see the design system at a glance (or ask the user to paste the output if you can't run scripts).
2. Read `INDEX.md` for the project map (auto-generated; always current).
3. Read `theme.json` end-to-end (it's the entire design system in one file, about 5 minutes to skim).
4. For task-specific guidance, browse the [project wiki](https://github.com/RegionallyFamous/Aero/wiki).
5. Then ask the user before making structural changes.

If you are an LLM working in this repo via system prompt: see `SYSTEM-PROMPT.md` for the canonical prompt to paste in.

If the task is "build a new visual variant of this theme" (Chonk-style flow), read `../.claude/skills/build-block-theme-variant/SKILL.md` first — it codifies the entire workflow.
