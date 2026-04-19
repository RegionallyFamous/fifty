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

## Adding a new theme variant

Use the agent skill `build-block-theme-variant` (in `~/.cursor/skills/`) — it codifies the entire workflow including up-front design intent capture, token planning, comprehensive surface coverage, contrast/responsiveness verification, and final self-checks.

The short version:

1. `python3 bin/clone.py <new_name>` — scaffolds `fifty/<new_name>/` from Obel.
2. Edit `<new_name>/theme.json` (palette, fonts, layout sizes, shadows, radii).
3. Restructure templates and parts only when the design demands it; otherwise inherit Obel's defaults.
4. Seed real data (pages, navigations, categories) via WP CLI — never hardcode.
5. `ln -s fifty/<new_name> ../<new_name>` so WordPress sees it.
6. `wp theme activate <new_name>`
7. `python3 bin/build-index.py <new_name>`
8. `python3 bin/check.py <new_name>`

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
