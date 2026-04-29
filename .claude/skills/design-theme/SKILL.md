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

The orchestrator runs the following phases, in order. This list must
stay in sync with `PHASES` in `bin/design.py` — if you edit one, audit
the other. `tests/tools/test_design_phases.py::test_skill_phases_match_code`
snapshots the canonical list and fails loudly on drift.

| # | Phase | Action | Failure mode |
|---|-------|--------|--------------|
| 1 | **validate** | Re-validate the spec (no-op if `--dry-run` passed already) | Same errors as step 2 |
| 2 | **clone** | `bin/clone.py <slug> --source <source>` + reset `readiness.json` to `incubating` | Refuses if `<slug>/` already exists; pass `--skip-clone` to operate on it |
| 3 | **apply** | Mutates `<slug>/theme.json` (palette + fonts) and writes `<slug>/BRIEF.md` | JSON parse error on theme.json |
| 4 | **contrast** | `bin/autofix-contrast.py` rewrites any block whose resolved `(textColor, backgroundColor)` pair fails WCAG AA against the new palette | Idempotent; re-runs on green tree are no-ops |
| 5 | **seed** | `bin/seed-playground-content.py --theme <slug>` | Soft fail (warns, continues) |
| 6 | **sync** | `bin/sync-playground.py` (refreshes blueprints across all themes) | Hard fail |
| 7 | **photos** | `bin/generate-product-photos.py --theme <slug>` — per-theme product JPGs + category covers; idempotent (skips files already on disk) | `design.py dress` phase; skipped by `design.py build` |
| 8 | **microcopy** | `bin/generate-microcopy.py --theme <slug>` + `bin/apply-microcopy-overrides.py --theme <slug>` — per-theme voice substitutions | `design.py dress` phase; skipped by `design.py build` |
| 9 | **frontpage** | `bin/diversify-front-page.py --theme <slug>` — adds a `wo-layout-<slug>` className so the front-page fingerprint is unique vs every sibling | `design.py dress` phase; skipped by `design.py build` |
| 10 | **index** | `bin/build-index.py` refreshes the theme INDEX.md | Hard fail |
| 11 | **prepublish** | Scoped `git add <slug>/` + commit + push so `raw.githubusercontent.com` can serve playground assets before snap | Skipped with `--skip-publish`; snap will 404 without it on a fresh theme |
| 12 | **snap** | `bin/snap.py shoot <slug>` | Skipped with `--skip-snap`; leaves no screenshot evidence |
| 13 | **vision-review** | `bin/snap-vision-review.py` against each cell — LLM critique against `<slug>/design-intent.md` | Skipped silently when `ANTHROPIC_API_KEY` is unset; in a release pipeline treat the skip as a WARN, not a PASS |
| 14 | **scorecard** | `bin/design-scorecard.py <slug>` writes `tmp/runs/<run-id>/design-score.json` + contact sheet from snap/vision findings | Hard fail below threshold; feeds `design_unblock.py` |
| 15 | **baseline** | `bin/snap.py baseline <slug>` (writes `tests/visual-baseline/<slug>/`) | Hard fail |
| 16 | **screenshot** | `bin/build-theme-screenshots.py <slug>` replaces the WP admin card screenshot with a crop of this theme's home page | Hard fail |
| 17 | **check** | `bin/check.py <slug> --quick` | **Strict by default** — any failure aborts. `--no-strict` demotes to a warning (prototype-only; never ship in that mode) |
| 18 | **report** | `bin/snap.py report <slug>` prints the tiered `STATUS: PASS/WARN/FAIL` | Non-pass aborts unless `--no-strict` |
| 19 | **redirects** | `bin/build-redirects.py` regenerates the `docs/<slug>/` short-URL redirectors | Hard fail |
| 20 | **commit** | Stages `<slug>/` + generated artifacts and creates one `design: ship <slug>` commit | Skipped with `--skip-commit`; runs only if every earlier phase was green |
| 21 | **publish** | `git push` of the freshly-created commit | Skipped with `--skip-publish` |

**Strict is the default.** `bin/design.py` ships with `strict=True` as of
Spring 2026. A `STATUS: PASS` at phase 16 (`check`) and a `STATUS: PASS`
at phase 17 (`report`) are both required before the orchestrator will
reach phase 19 (`commit`). Passing `--no-strict` demotes check / report
to informational — **never use it for a release**. Prototype flags
(`--no-strict`, `--skip-snap`, and running with `ANTHROPIC_API_KEY`
unset so vision-review skips) explicitly produce an **incubating** theme
per the readiness manifest. Only a green full run — every phase
including vision-review — followed by `python3 bin/promote-theme.py
<slug>` flips `readiness.json` to `shipping`.

**`STATUS: PASS` is not the end.** Post-clone, the theme still shares
Obel's structural layout and most body copy. The front-page-uniqueness
check (`check_front_page_unique_layout`) and the cross-theme
rendered-text check (`check_all_rendered_text_distinct_across_themes`)
will **fail** until the judgment work in step 5 lands — that is the
design pipeline working as intended, not a gate to silence.

**Iteration patterns:**

```bash
# Edit spec palette, re-apply only (skip re-clone, skip seed/sync):
python3 bin/design.py --spec tmp/<slug>.json --only apply

# Re-run from apply onwards (after editing spec):
python3 bin/design.py --spec tmp/<slug>.json --from apply --skip-clone

# Prototype mode (informational check; NEVER ship in this mode):
python3 bin/design.py --spec tmp/<slug>.json --no-strict
```

The `--only` and `--from` switches are the inner loop. Rebuilding the whole theme from a single spec edit usually means `--from apply --skip-clone`.

---

## Two-step flow (optional but recommended)

When you have room to stage the work over more than one turn, split the one-shot pipeline into two subcommands that answer two separable questions:

```bash
# Step 1: Is the theme structurally sound?
python3 bin/design.py build --spec tmp/<slug>.json

# Step 2: Does the demo content match the vibe?
python3 bin/design.py dress <slug>
```

- **`design.py build`** runs the deterministic structural phases — `validate, clone, apply, contrast, seed, sync, index, prepublish, snap, baseline, screenshot, check, report, redirects, commit, publish`. The `check` phase runs with `--phase structural`, which skips the 10 content-fit checks (product-image diversity, per-theme microcopy uniqueness, front-page fingerprint, etc.) that only pass AFTER `dress` has regenerated per-theme photography and microcopy. It does NOT call a vision model. Re-running `build` after a CSS / token / markup tweak is the tight inner loop (5–10 min).
- **`design.py dress`** runs the content-fit phases — `photos, microcopy, frontpage, snap, vision-review, scorecard, check, report, commit, publish`. The `check` phase runs with `--phase all` (every check must pass before promotion), and `vision-review` runs with `--phase content` so the reviewer focuses on the catalogue-fit lens (photography-mismatch, color-clash, brand-violation, mockup-divergent) instead of re-grading structural complaints that `build` already gated. `scorecard` converts that evidence into a repairable design-quality artifact. This is the outer loop that burns vision-review budget (≈ $0.30 / run).
- **`dress`** requires the theme to already exist on disk — preflight checks for `<slug>/theme.json` and `<slug>/playground/blueprint.json` and exits 2 with a "run build first" message if either is missing.
- Each subcommand emits its own verdict banner on green (`BUILD OK — ...` / `DRESS OK — ...`) and lands its own commit (`design: build <slug> (structurally sound)` / `design: dress <slug> (content-fit)`).

Use the two-step flow when iterating on tokens / CSS / markup (re-run `build` many times, `dress` once at the end). Use the flat CLI (`design.py --spec X`) when you want one-shot ship-it semantics and the spec is known-good.

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
python3 bin/check.py <slug>              # full static gate (preferred)
python3 bin/verify-theme.py <slug> --snap --strict   # full release gate (snap + vision + check)
```

`bin/check.py <slug>` runs every static gate. `bin/check.py <slug> --quick`
(which is what `bin/design.py`'s internal `check` phase calls) is an
alias for `--offline`, which **skips** `check_block_names` and the
Node-side `validate-theme-json.py` block-tree validator — so passing
`--quick` is necessary but not sufficient. Always re-run without
`--quick` before promotion.

`bin/verify-theme.py <slug> --snap --strict` is the single local command
that reproduces the release gate. `bin/promote-theme.py <slug>` calls
it internally before flipping the readiness manifest.

If check fails, fix every failure listed before committing — don't
suppress with `--no-verify`. Common first-build failures:

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
- [ ] `python3 bin/design.py --spec tmp/<slug>.json` exited 0 with `STATUS: PASS` at BOTH `check` and `report`
- [ ] `<slug>/BRIEF.md` exists and was read
- [ ] Microcopy block in `<slug>/functions.php` rewritten in the spec's voice (`check_wc_microcopy_distinct_across_themes`)
- [ ] My-account dashboard lede + card copy in `<slug>/functions.php` rewritten in the spec's voice (not reused from obel/foundry/etc)
- [ ] `<slug>/playground/images/product-wo-*.jpg` are branded for this theme AND visually distinct from each other (`check_product_image_visual_diversity` — same composition with different labels still fails)
- [ ] `<slug>/playground/content/product-images.json` exists and maps every parent SKU to its photograph (`check_product_images_json_complete`)
- [ ] `<slug>/templates/front-page.html` is structurally distinct from every sibling
- [ ] `<slug>/design-intent.md` exists with non-trivial Voice / Palette / Typography / Required / Forbidden sections (vision reviewer grades against it)
- [ ] `python3 bin/check.py <slug>` exits 0 (full check, not just `--quick`)
- [ ] `python3 bin/snap.py report <slug>` shows `STATUS: PASS`
- [ ] No default WP content strings ("Hello world!", "Sample Page") in any snapshot
- [ ] `python3 bin/promote-theme.py <slug>` succeeds — flips `readiness.json` from `incubating` to `shipping`
- [ ] Commit + push lands green CI with `verify-theme` returning `passed`
