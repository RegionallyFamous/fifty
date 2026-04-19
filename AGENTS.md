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
6. **Run `python3 bin/check.py <theme> --quick` before every commit.** It catches every mistake the other rules try to prevent.

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

1. `python3 bin/clone.py <new_name>` — scaffolds `fifty/<new_name>/` from Obel.
2. Edit `<new_name>/theme.json` (palette, fonts, layout sizes, shadows, radii).
3. Restructure templates and parts only when the design demands it; otherwise inherit Obel's defaults.
4. Seed real data (pages, navigations, categories) via WP CLI — never hardcode.
5. `ln -s fifty/<new_name> ../<new_name>` so WordPress sees it.
6. `wp theme activate <new_name>`
7. `python3 bin/build-index.py <new_name>`
8. `python3 bin/check.py <new_name>`

## WordPress Playground blueprints

Each theme has a Playground blueprint at `<theme>/playground/blueprint.json`. The blueprints share a single Wonders & Oddities sample-data importer at `playground/wo-import.php` (repo root, not under any theme).

**The script is inlined into both blueprints**, not fetched at boot. Don't change the blueprints' `writeFile` step to use a `{ resource: url }` data field — Playground caches URL resources aggressively (and `raw.githubusercontent.com` ships `cache-control: max-age=300`), so a freshly-pushed script change can take 5+ minutes to propagate and Playground will run the previous version against the new blueprint. Inlining puts the script body in the same payload as the blueprint, so there is one URL to invalidate, not two.

After editing `playground/wo-import.php`:

```bash
python3 bin/sync-playground.py   # re-inlines the script into both blueprints
```

Commit the resulting `*/playground/blueprint.json` changes alongside the script change. `bin/check.py` does not (yet) enforce that the blueprints are in sync — keep them in sync by hand.

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
