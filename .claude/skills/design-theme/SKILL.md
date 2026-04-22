---
name: design-theme
description: Drive `bin/design.py` to build a new WooCommerce block theme from a prompt. Use when the user asks to "make a new theme called X", "build a theme that looks like [description]", "design a theme from this prompt", or "spin up a [style] theme". This skill owns the deterministic spine (clone + token swap + seed + sync + check); the longer `build-block-theme-variant` skill owns the design judgment (microcopy voice, structural restyle, photography). Both skills coexist — this one is the fast path that produces a runnable theme in one orchestrator pass.
---

# Design a theme from a prompt

The agent's job here is to translate a free-form prompt into a JSON spec, run `bin/design.py` once, then iterate the spec until the theme passes `bin/check.py`. This skill is intentionally short: the heavy reference material lives in `build-block-theme-variant`. Read this skill when you want to ship fast; read both skills when the result needs the full surface-by-surface judgment pass.

## When to read this skill (vs `build-block-theme-variant`)

| Trigger | Skill |
|---------|-------|
| "Make a new theme called X" / "build a [style] theme" / "design a theme from this prompt" | **design-theme** (this one) — drives `bin/design.py` |
| "Make a variant of obel that looks like [mockup]" / hands you a mockup image | `build-block-theme-variant` — long-form judgment-heavy flow |
| "I have a spec.json, run it" | **design-theme** (this one) |
| "Restyle the cart on every theme" / cross-theme structural changes | Neither — bare bin tools |

If the user's prompt has design intent but no mockup, start here. If they hand you a mockup, jump to `build-block-theme-variant`.

## The non-negotiable sequence

```
1. PROMPT      -> spec.json (you author this from the prompt + 1 confirmation question)
2. VALIDATE    -> python3 bin/design.py --spec spec.json --dry-run
3. RUN         -> python3 bin/design.py --spec spec.json
4. READ BRIEF  -> open <slug>/BRIEF.md (the orchestrator wrote this for you)
5. JUDGMENT    -> microcopy block + product photos + structural restyle
6. VERIFY      -> python3 bin/check.py <slug> --quick (must exit 0)
7. SNAP        -> python3 bin/snap.py shoot <slug> && bin/snap.py baseline <slug>
8. SHIP        -> commit + push (hooks gate; CI gates again)
```

Steps 1-4 are this skill. Steps 5-8 borrow from `build-block-theme-variant` and the per-theme `AGENTS.md`.

---

## Step 1 — Prompt to spec

The spec is a JSON object. Get the canonical shape with:

```bash
python3 bin/design.py --print-example-spec > tmp/<slug>.json
```

Edit the file in place. The required fields are `slug` and `name`; everything else is optional and defaults to the source theme's value when omitted.

**Spec shape (annotated):**

```jsonc
{
  "slug": "midcentury",                // lowercase, [a-z][a-z0-9-]{1,38}
  "name": "Midcentury",                // human-readable, used in style.css header
  "tagline": "Postwar shop, modern goods.",
  "voice": "warm midcentury department store: 'parcel' for order, ...",
  "source": "obel",                    // theme to clone from; default obel
  "palette": {                         // any subset of the 16 known slugs
    "base": "#F5EFE6",
    "contrast": "#1F1B16",
    "accent": "#D87E3A",
    // ...slugs you don't list keep the source's value
  },
  "fonts": {                           // any subset of {sans, serif, mono, display}
    "display": {
      "family": "Bricolage Grotesque",
      "fallback": "Helvetica, Arial, sans-serif",
      "google_font": true,             // if true, fontFace is wired to assets/fonts/
      "weights": [400, 700]
    }
  },
  "layout_hints": [                    // free-form; written into BRIEF.md verbatim
    "asymmetric hero with offset product image",
    "tiled 3x2 category grid"
  ]
}
```

**Authoring rules:**

1. **Always confirm in one batch before running.** Use `AskQuestion` exactly once with: slug confirm, palette anchor (3-6 hexes), display font intent, voice keyword, layout aggression. Do not drip-feed — the user gets one chance to correct your reading of their prompt before the orchestrator runs.
2. **Picking a palette:** if the user gave you vibes ("warm 1960s department store"), translate to 4-6 hexes and put them in the spec. Validate against WCAG by writing the contrast pairings to your scratch notes before locking.
3. **Picking fonts:** Google Fonts only (the per-theme `check_no_remote_fonts` lint blocks any other source). Default to system stacks unless the prompt explicitly calls for a custom display family.
4. **Voice keyword:** one paragraph. The orchestrator records it in `BRIEF.md`; you'll write the actual `// === BEGIN wc microcopy ===` block in step 5. `check_wc_microcopy_distinct_across_themes` enforces uniqueness vs every sibling theme — if you reuse phrasing from Obel/Chonk/Selvedge/Lysholm/Aero, the gate will reject it.

---

## Step 2 — Validate

```bash
python3 bin/design.py --spec tmp/<slug>.json --dry-run
```

Dry-run parses the spec, validates every field, prints a one-line summary, and exits without touching the filesystem. If validation fails the script prints a JSON-pointer-ish error path per problem (e.g. `$.palette.acent: unknown color slug`). Fix the spec and rerun until you see `OK: spec is valid`.

**Common validation failures:**

| Error path | Cause | Fix |
|-----------|-------|-----|
| `$.slug` | Uppercase / spaces / starts with digit | Use `[a-z][a-z0-9-]{1,38}` |
| `$.palette.<slug>` (unknown slug) | Typo (`primay`, `acent`) | Fix typo; allowed slugs in error message |
| `$.palette.<slug>` (must be a hex) | Used `rgb()` or named color | Convert to `#RRGGBB` |
| `$.fonts.<slug>.weights[0]` | Non-multiple of 100 | Use `[400, 700]` not `[450]` |
| `$.<key>` (unknown top-level key) | Typo / made-up field | Allowed keys are listed in the error |

---

## Step 3 — Run

```bash
python3 bin/design.py --spec tmp/<slug>.json
```

The orchestrator runs phases A-F:

| Phase | Action | Failure mode |
|-------|--------|--------------|
| **validate** | Re-validate (no-op if dry-run already passed) | Same errors as step 2 |
| **clone** | `bin/clone.py <slug> --source <source>` | Refuses if `<slug>/` already exists; pass `--skip-clone` to operate on it |
| **apply** | Mutates `<slug>/theme.json` (palette + fonts) and writes `<slug>/BRIEF.md` | JSON parse error on theme.json |
| **seed** | `bin/seed-playground-content.py --theme <slug>` | Soft fail (warns, continues) |
| **sync** | `bin/sync-playground.py` (refreshes blueprints across all themes) | Hard fail |
| **check** | `bin/check.py <slug> --quick` | Default informational; `--strict` to fail |

**Iteration patterns:**

```bash
# Edit spec palette, re-apply only (skip re-clone, skip seed/sync):
python3 bin/design.py --spec tmp/<slug>.json --only apply

# Re-run from apply onwards (after editing spec):
python3 bin/design.py --spec tmp/<slug>.json --from apply --skip-clone

# Strict mode (CI-style: any check failure aborts):
python3 bin/design.py --spec tmp/<slug>.json --strict
```

The `--only` and `--from` switches are the inner loop. Rebuilding the whole theme from a single spec edit usually means `--from apply --skip-clone`.

---

## Step 4 — Read the brief

After `apply`, the orchestrator writes `<slug>/BRIEF.md`. **Read it before doing anything else.** The brief captures:

- The voice keyword (so you can write the microcopy block)
- The layout hints (so you can restructure templates)
- The palette table (so you can sanity-check WCAG pairings)
- The list of Google Fonts that need `.woff2` files dropped at the right paths
- A numbered "next steps" list (microcopy, photography, screenshot, snap baseline, check, commit)

The brief is committed alongside the theme — it's the design intent record for future agents (and humans) reading the repo a year from now.

---

## Step 5 — Judgment work (delegate to `build-block-theme-variant`)

Everything past phase F is judgment-heavy. The shortest path:

1. **Microcopy block.** Open any sibling theme's `functions.php`, copy the block between `// === BEGIN wc microcopy ===` and `// === END wc microcopy ===`, paste into `<slug>/functions.php`, rewrite every literal string in the spec's voice. `check_wc_microcopy_distinct_across_themes` enforces no overlap.
2. **Product photos.** Drop branded `.jpg`s at `<slug>/playground/images/product-wo-*.jpg` (one per product). Use `GenerateImage` with prompts derived from the voice + layout hints. `check_product_images_unique_across_themes` rejects byte-shared images.
3. **Front page restructure.** `templates/front-page.html` must be structurally distinct from every sibling. Apply the spec's layout hints — change the section count, swap dynamic-block types, reorder. `check_front_page_unique_layout` enforces this.
4. **Screenshot.** `python3 bin/build-theme-screenshots.py <slug>` so `screenshot.png` shows the new theme rendering, not the cloned source's.
5. **Snap baseline.** `python3 bin/snap.py shoot <slug> && python3 bin/snap.py baseline <slug>`.

For the deeper surface-by-surface methodology (hero composition, archive layout, cart/checkout polish, three-viewport audit), read `.claude/skills/build-block-theme-variant/SKILL.md`.

---

## Step 6 — Verify

```bash
python3 bin/check.py <slug> --quick
```

Must exit 0. If it doesn't, fix every failure listed before committing — don't suppress with `--no-verify`. Common first-build failures:

| Check | Fix |
|-------|-----|
| `check_wc_microcopy_distinct_across_themes` | Rewrite microcopy strings; you reused phrasing from a sibling |
| `check_product_images_unique_across_themes` | Generate fresh product photos; you copied from a sibling |
| `check_front_page_unique_layout` | Restructure `templates/front-page.html` (different section count + block mix) |
| `check_theme_screenshots_distinct` | Re-run `bin/build-theme-screenshots.py <slug>` |
| `check_no_remote_fonts` | Self-host the `.woff2` per the brief |
| `check_no_default_wc_strings` | Microcopy block missing required override (see brief) |

---

## Step 7 — Snap

The snap baseline is the visual contract. Re-shoot after every structural template change:

```bash
python3 bin/snap.py shoot <slug>
python3 bin/snap.py baseline <slug>
python3 bin/snap.py report <slug>
```

`bin/snap.py report` prints a `STATUS: PASS` / `WARN` / `FAIL` line. Anything but PASS needs investigation before committing.

---

## Step 8 — Ship

```bash
git add <slug> tests/visual-baseline/<slug>
git commit -m "Add <Name> theme: <one-line description from spec.tagline>"
git push
```

The pre-commit and pre-push hooks run `bin/check.py --all --offline` and (on push) `bin/snap.py check --changed`. Both will block if any sibling theme regressed because of the new theme's seed/sync run — that almost always means `bin/sync-playground.py` modified another theme's blueprint and you need to include those edits in the commit.

---

## Anti-patterns

| Mistake | Fix |
|---------|-----|
| Generated a spec, ran `bin/design.py`, then immediately ran `git commit` without reading `BRIEF.md` | Always read the brief — it's the only place the design intent lives between phase F and the judgment work |
| Used `--only check` as a one-liner verifier instead of `bin/check.py <slug> --quick` directly | `--only check` is fine but `bin/check.py` is the ground truth; reach for it first when debugging |
| Authored the spec with palette hexes copied from Obel verbatim | The whole point is per-theme distinctiveness; if your palette matches a sibling, the contrast / chrome / hover-state checks will probably pass but the theme will fail the user's eye test |
| Ran `bin/design.py` once, hit a check failure, abandoned the theme | The default check phase is informational so you can iterate. Read the failure, edit the spec or the post-apply files, re-run with `--only check` or `--from apply --skip-clone` |
| Skipped `--dry-run` and ran the full pipeline on an invalid spec | Dry-run is ~100ms and prevents a half-cloned theme on disk. Always run it first |
| Generated product photos via screenshot of an existing theme | `check_product_images_unique_across_themes` is a hash-based gate; sharing a single byte means failing CI |
| Wrote the `voice` field as one word ("brutalist") | Give the orchestrator a paragraph — it gets dumped into BRIEF.md verbatim and is what you'll re-read when writing the microcopy block. One word is not enough to write 50 distinct WC strings against |

---

## Final self-check

- [ ] `tmp/<slug>.json` validates with `--dry-run`
- [ ] `python3 bin/design.py --spec tmp/<slug>.json` exited 0 with `STATUS: PASS`
- [ ] `<slug>/BRIEF.md` exists and was read
- [ ] Microcopy block in `<slug>/functions.php` rewritten in the spec's voice
- [ ] `<slug>/playground/images/product-wo-*.jpg` are branded for this theme (not sibling copies)
- [ ] `<slug>/templates/front-page.html` is structurally distinct from every sibling
- [ ] `python3 bin/check.py <slug> --quick` exits 0
- [ ] `python3 bin/snap.py report <slug>` shows `STATUS: PASS`
- [ ] Commit + push lands green CI
