# Day-0 smoke batch

> **Status:** template. Fill in the timings + findings below before starting
> Tier 1 infrastructure work. Context: this doc was drafted alongside
> the pre-100-themes hardening plan (Cursor-local, not checked in);
> the tier conclusions now live in
> [`docs/shipping-a-theme.md`](shipping-a-theme.md) and
> [`docs/batch-playbook.md`](batch-playbook.md).
>
> **Why this exists:** the hardening plan assumes certain steps are slow
> (design-spec authoring, manual microcopy, front-page restructure) and
> other steps are fast (clone, visual gate under the Phase 2 signature
> skip). Before writing new tooling against those assumptions, a human
> should ship 3-5 themes through the **existing** pipeline with a
> stopwatch. The measured bottleneck drives which Tier 1 item actually
> moves the needle.

## How to run it

Pick 3-5 un-shipped concepts from `bin/concept_seed.py::CONCEPTS`.
Suggested spread (covers different `hero_composition` / `sector` /
`era` axes so one slow concept doesn't skew the average):

- `agave`           -- specimen-grid, beauty, contemporary
- `apiary`          -- ?, food/gift, contemporary
- `brine`           -- ?, food/drink, contemporary
- `cathode`         -- ?, ?, retro
- `cobbler`         -- ?, artisan, contemporary

For each theme, record:

1. **Spec authoring** (wall clock, minutes)
   -- did you hand-write the `design.py` spec JSON, or start from
   `bin/spec-from-prompt.py`? How many revisions before it produced a
   usable clone?

2. **design.py run** (wall clock, minutes; Chromium log if it crashed)
   -- `python3 bin/design.py tmp/specs/<slug>.json`
   -- from clone start to "snap baseline promoted".

3. **Manual WooCommerce microcopy pass** (wall clock)
   -- how many strings did you end up changing in `functions.php`
   beyond what `bin/personalize-microcopy.py` produced?

4. **Product imagery pass** (wall clock + image count)
   -- where did images come from (generated / licensed / hand-shot)?

5. **Front-page restructure** (wall clock + pattern count changed)
   -- how many patterns did you touch to make the front-page visually
   distinct from the Obel clone skeleton?

6. **check.py iteration loop** (count + wall clock)
   -- how many `python3 bin/check.py --all --offline` -> fix -> rerun
   cycles before green?
   -- which rules fired the most?

7. **Visual review** (wall clock + rounds)
   -- `bin/snap-vision-review.py` runs and reviewer edits.

8. **PR to merge** (wall clock + review rounds)

## Findings table (fill in)

| Theme  | Spec | design.py | WC copy | Images | Front-page | check loops | Vision | PR | **Total** |
|--------|-----:|----------:|--------:|-------:|-----------:|------------:|-------:|---:|----------:|
| agave  |      |           |         |        |            |             |        |    |           |
| apiary |      |           |         |        |            |             |        |    |           |
| brine  |      |           |         |        |            |             |        |    |           |
| ...    |      |           |         |        |            |             |        |    |           |

## Which gate fired most?

Tally every `check.py` failure you saw across the batch and list the
top 3 offending rule names here. If one rule accounts for >50% of
failures, there's a fix-it-once opportunity that wasn't in the plan.

-
-
-

## Go / no-go per Tier 1 item

Fill in **yes / no / reorder** + a one-line rationale.

- **1.1 boot-fatal smoke gate:**
  Does the full `snap.py shoot` complete in under 90 s warm on your
  laptop? If yes, boot smoke may add no value -- downgrade or drop.
  (The plan's kill criterion.)

- **1.3 readiness manifest:**
  Did you accidentally push an incomplete theme into a fan-out during
  the batch (e.g. it showed up in `docs/snaps/index.html` half-finished)?
  If yes, build readiness. If no, still worth it for discipline.

- **1.2 concept -> spec bridge:**
  How long did "spec authoring" take on average? If <15 min, don't build
  this tool -- write an LLM prompt template instead. If >30 min, build it
  first.

- **1.4 bulk rebaseline:**
  Did the nightly sweep flag drift during the batch? If yes, build it.
  If no, keep it on the list but lower urgency.

## Surprises that should become blind-spot decisions

If anything surfaces during the batch that isn't in the plan (e.g.
"Playground cold-boot takes 3 minutes on CI and we have no way to
warm it" or "copyright compliance for hero images was a blocker"),
note it here. These become inputs to the `blindspots-decisions` todo.

-
-

## Decision sign-off

- Date: _____
- Operator: _____
- Go / reorder summary: _____
