# Visual baselines

Committed PNG references that `bin/snap.py diff` compares each
freshly-captured screenshot against. When a baseline exists, the diff
command flags any cell whose changed-pixel percentage exceeds the
threshold (default 0.5%).

## Layout

```
tests/visual-baseline/
  <theme>/
    <viewport>/
      <route-slug>.png
```

The slug names mirror `bin/snap_config.py::ROUTES` and viewport names
mirror `bin/snap_config.py::VIEWPORTS`. The same paths are used by
`tmp/snaps/` (latest captures) and `tmp/diffs/` (per-pixel overlays).

## Workflow

```bash
# 1. Capture latest into tmp/snaps/ (use --concurrency 2 for ~2x speed
#    if you have RAM to spare; each worker boots its own playground at
#    ~400MB).
python3 bin/snap.py shoot --all --concurrency 2

# 2. Triage non-pixel signal (uncaught JS, console errors, 4xx/5xx,
#    DOM heuristics). A clean run is "0 / 0 / 0 / 0" across every theme
#    in the rollup table.
python3 bin/snap.py report

# 3. Compare against baselines, see what regressed
python3 bin/snap.py diff --all

# 4. If the changes are intentional (intentional redesign,
#    new content, fixed bug), promote latest -> baseline:
python3 bin/snap.py baseline --all                # entire matrix
python3 bin/snap.py baseline chonk                # one theme
python3 bin/snap.py baseline chonk --route checkout-filled --viewport desktop
                                                  # one cell

# 5. Re-run diff to confirm clean (0 regressions above threshold).
python3 bin/snap.py diff --all
```

Always review the diff PNG (under `tmp/diffs/`) AND the per-theme
`tmp/snaps/<theme>/review.md` before re-baselining. The diff PNG tells
you which pixels changed; the review tells you whether anything broke
on the way (broken images, mid-word wraps, narrow grid items, console
errors, network failures). Re-baselining a green-pixel-diff that ships
with a new uncaught JS error is exactly the regression this folder
exists to prevent.

## Why commit PNGs

Yes, binary blobs in git aren't ideal. The alternative -- regenerating
baselines on every CI run -- doesn't catch regressions because there's
nothing to compare against. Storing the PNGs:

  * makes diffs reviewable in GitHub PRs (the GH UI renders side-by-side
    PNG diffs natively)
  * lets the agent loop work without a separate artifact store
  * is bounded: ~10 routes × 4 viewports × 4 themes ≈ 160 PNGs at ~50KB
    each ≈ 8MB total, within reason for a theme repo

If a particular cell becomes too noisy (e.g. an animation that always
captures mid-transition), exclude it from `bin/snap_config.py::ROUTES`
or `VIEWPORTS` rather than committing a "this one will always be 5%
different" baseline.
