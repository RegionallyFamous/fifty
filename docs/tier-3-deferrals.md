# Tier 3 deferrals — what is intentionally NOT shipped

This stub exists so the plan's "don't ship Tier 3 without documented pain"
rule has a single home and is discoverable alongside the other Tier docs.
It is meant to be edited *by the operator who runs the Tier-0 smoke
batch and the first full Tier-1 batches*, not by the bot.

The rule, restated from the pre-100-themes hardening plan's §Tier 3
(the plan lived in Cursor's local `.cursor/plans/` and is not checked
in; this doc, along with `shipping-a-theme.md` and `batch-playbook.md`,
is the committed source of truth):

> Infrastructure without evidence is waste. Nothing in Tier 3 ships
> until we've seen the specific pain it addresses in a real batch.

## Items intentionally deferred

### 3.1 Build-time pattern snippet library (`_shared-patterns/` + `bin/expand-patterns.py`)

- **Status:** deferred.
- **Trigger to build:** the same copy-paste pattern (hero, product-grid,
  announcement, footer-columns) has been hand-duplicated across three
  or more themes AND a generator script would clearly have saved
  operator time.
- **Evidence required:** log the theme slug + pattern + approximate
  hand-edit time in this doc as it happens. Three real entries is the
  go-signal.
- **Why deferred:** a shared pattern library adds a new directory, a
  new copying script, and a new "is this file hand-written or copied?"
  question to every PR review. If fewer than three themes actually
  share the pattern, the copying-by-hand is cheaper than the
  abstraction.

### 3.2 functions.php fragment system (`functions.d/*.php`)

- **Status:** deferred.
- **Trigger to build:** functions.php drift has concretely bitten a
  rebuild (running `bin/design.py` or a regenerator clobbers hand-edits
  in `functions.php`) in at least two themes.
- **Evidence required:** log the theme slug + regenerator script +
  which hand-edit got clobbered here when it happens.
- **Why deferred:** sentinel-block concatenation is a non-trivial
  behaviour change (it silently rewrites a PHP file on every build),
  and the failure mode when it goes wrong is "theme's functions.php
  is empty or duplicated". High risk, and today's themes mostly don't
  share enough functions.php content to justify it.

### 3.3 Per-theme performance budgets (`snap_config.BUDGETS`)

- **Status:** deferred.
- **Trigger to build:** a theme has shipped that silently exceeded
  reasonable rendered-HTML size, script-tag count, or LCP pixel area,
  AND the drift wasn't caught by existing review. I.e., we have
  a real "theme ballooned and no human noticed" incident.
- **Evidence required:** link to the PR / shoot where it happened.
- **Why deferred:** without a real incident we have no calibration for
  what the budgets should be. Premature budgets create false-positive
  noise that erodes trust in the gate.

## How to move something out of Tier 3

1. Add an evidence entry under the item above (slug, date, what
   happened, link to PR / shoot).
2. Once the evidence meets the trigger ("3+ themes", "2+ incidents",
   etc.), author a scoped plan (either a Cursor-local
   `.cursor/plans/<slug>.plan.md` for a short run, or a committed
   issue / PR description for a larger one) — **don't inline-ship
   it**, the plan is the contract.
3. Delete the item from this file once it lands on main, so this doc
   only ever lists what is *still* deferred.

## See also

- [docs/shipping-a-theme.md](shipping-a-theme.md) — operator checklist,
  where "hit Tier 3 pain" would typically surface first.
- [docs/batch-playbook.md](batch-playbook.md) — batch runner guide.
- [docs/blindspot-decisions.md](blindspot-decisions.md) — the companion
  doc for the six §B-items that, unlike Tier 3 deferrals, already
  have a landed decision.
