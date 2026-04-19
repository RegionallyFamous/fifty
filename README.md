# Fifty

A monorepo of block-only WooCommerce themes. Every theme is one `theme.json` file, zero CSS, zero JS, zero build step. You edit a token, the whole storefront re-skins.

## Themes in this repo

| Theme | Path | Status | Vibe |
| --- | --- | --- | --- |
| **Obel** | [`obel/`](./obel/) | Base / canonical reference | Editorial, soft, restrained |
| **Chonk** | [`chonk/`](./chonk/) | Variant | Neo-brutalist, chunky, high contrast |

Obel is the reference theme. Read it first. Every other theme in this repo is a clone of Obel with a different `theme.json` and a few template tweaks.

## Layout

```
fifty/
├── obel/          # base theme (the reference implementation)
├── chonk/         # neo-brutalist variant
├── bin/           # shared CLI tooling (run from the monorepo root)
├── README.md      # you are here
├── LICENSE        # GPL-2.0+, applies to every theme
└── .editorconfig  # shared editor config
```

Each theme directory is self-contained from WordPress's perspective: it has its own `theme.json`, `style.css`, `templates/`, `parts/`, `patterns/`, and `screenshot.png`. Each theme also has its own `AGENTS.md`, `INDEX.md`, `CHANGELOG.md`, and `SYSTEM-PROMPT.md` capturing theme-specific guidance.

## Loading themes into WordPress

WordPress expects each theme as a top-level directory under `wp-content/themes/`. This repo lives inside `wp-content/themes/fifty/`, so each theme is symlinked back so WordPress's theme scanner finds it:

```
wp-content/themes/
├── fifty/             # this monorepo
│   ├── obel/
│   └── chonk/
├── obel  -> fifty/obel
└── chonk -> fifty/chonk
```

Activate a theme via WP CLI using the short alias:

```bash
wp theme activate obel
wp theme activate chonk
```

## CLI tooling

All scripts live in `bin/` at the monorepo root. They accept a positional theme name, default to the cwd if it contains a `theme.json`, and most support `--all` to operate on every theme in the repo.

```bash
# Run the full check suite against one theme
python3 bin/check.py obel --quick
python3 bin/check.py chonk --quick

# Run it against every theme
python3 bin/check.py --all --quick

# Rebuild a theme's INDEX.md
python3 bin/build-index.py obel

# Inspect tokens
python3 bin/list-tokens.py --theme obel colors
cd obel && python3 ../bin/list-tokens.py colors    # cwd-detected

# Clone Obel into a new theme variant (sibling of obel/ inside the monorepo)
python3 bin/clone.py acme
```

The full toolchain:

| Script | What it does |
| --- | --- |
| `check.py` | Runs every project check (JSON, PHP, blocks, tokens, AI fingerprints, …). Use this before every commit. |
| `build-index.py` | Regenerates a theme's `INDEX.md` (token map, template list, block style list). |
| `validate-theme-json.py` | Validates a theme's `theme.json` block names against the live Gutenberg + WooCommerce sources. |
| `list-templates.py` | Prints every template the theme could ship and the URL it serves. |
| `list-tokens.py` | Inspects design tokens defined in `theme.json`. |
| `clone.py` | Scaffolds a new sibling theme from Obel with the names rewritten. |

Each script also responds to `--help`.

## Adding a new theme

1. Clone the base: `python3 bin/clone.py mybrand`
2. Edit `mybrand/theme.json` until the storefront looks right.
3. Symlink it for WordPress: `ln -s fifty/mybrand wp-content/themes/mybrand`
4. Activate: `wp theme activate mybrand`
5. Run the checks: `python3 bin/check.py mybrand`

## Working in this repo

Each theme has its own `AGENTS.md` describing the per-theme rules (token system, block conventions, hard rules). Read the `AGENTS.md` for the theme you are editing. They do not contradict each other but they are theme-specific.

When working on shared tooling (anything in `bin/`), changes affect every theme — run `python3 bin/check.py --all` after.

## License

GPL-2.0-or-later. See `LICENSE`.
