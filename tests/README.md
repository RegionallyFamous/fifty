# Fifty tooling test suite

This directory tests the **tooling** in [`bin/`](../bin/), not the themes themselves.
The existing GitHub Actions workflow already runs `bin/check.py --all --offline`
against the five committed theme directories on every push; that catches
**theme** regressions. This suite catches **tooling** regressions — a silent
regex bug in `check_no_fake_forms`, a broken `clone.py`, a `@wordpress/blocks`
upgrade that changes validation behavior, etc.

## Layout

```
tests/
├── README.md                    # this file
├── conftest.py                  # shared fixtures
├── check_py/                    # one module per check_* in bin/check.py
│   └── test_*.py                # (named check_py/ NOT check/ to avoid
│                                #  shadowing `import check` on sys.path)
├── tools/                       # round-trip / integration tests for bin/*.py
│   └── test_*.py
├── validator/                   # Node.js smoke tests for bin/blocks-validator/
│   ├── test_check_blocks.py
│   └── fixtures/
│       ├── good/                # patterns that MUST validate clean
│       └── bad/                 # patterns each tripping a known invariant
└── visual-baseline/             # NOT pytest — committed PNG baselines
                                 # used by `bin/snap.py check`. pytest skips
                                 # this dir via `norecursedirs`.
```

## Conventions

### Every new `check_*` function ships with two tests

When you add a `check_foo()` function to `bin/check.py`, you also add
`tests/check_py/test_foo.py` with at minimum:

```python
def test_passes_on_good_fixture(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    # write the canonical "this is what the check is happy with" file
    (minimal_theme / "patterns" / "good.php").write_text(GOOD_PATTERN)
    assert check.check_foo().passed

def test_fails_on_bad_fixture(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    # write a file that flips exactly one invariant the check guards
    (minimal_theme / "patterns" / "bad.php").write_text(BAD_PATTERN)
    assert not check.check_foo().passed
```

This isn't ceremony — it's the only way to know that a refactor (e.g.
swapping a regex for a parser, tightening an invariant) hasn't silently
loosened or broken the check.

### Cross-theme checks use the `monorepo` fixture

`check_distinctive_chrome`, `check_pattern_microcopy_distinct`, and
`check_all_rendered_text_distinct_across_themes` compare files across
all sibling themes. Use the `monorepo` fixture, which builds a synthetic
two-theme tree and patches `_lib.MONOREPO_ROOT` for the test:

```python
def test_distinctive_chrome_catches_clones(monorepo, bind_check_root):
    check = bind_check_root(monorepo["obel"])
    # make obel and chonk paint identical buttons
    obel_css = "..."
    chonk_css = obel_css
    ...
    assert not check.check_distinctive_chrome().passed
```

### Build tools get round-trip tests

For scripts like `clone.py`, `seed-playground-content.py`, and
`append-wc-overrides.py`, write tests under `tests/tools/` that:

1. Set up a clean fixture monorepo (use `monorepo` or `make_theme`).
2. Run the script via the `run_bin_script` fixture.
3. Assert on observable outputs (files written, files NOT written,
   stdout/exit-code, idempotence on a second run).

For idempotence in particular, the canonical pattern is:

```python
result_a = run_bin_script("append-wc-overrides.py", str(theme))
assert result_a.returncode == 0
snapshot_a = (theme / "theme.json").read_bytes()

result_b = run_bin_script("append-wc-overrides.py", str(theme))
assert result_b.returncode == 0
snapshot_b = (theme / "theme.json").read_bytes()

assert snapshot_a == snapshot_b, "second run drifted"
```

### The Node validator gets exit-code smoke tests

`bin/blocks-validator/check-blocks.mjs` is a Node.js script. The Python
test (`tests/validator/test_check_blocks.py`) invokes it via subprocess
and asserts on exit codes + stderr keywords. The fixture HTML/PHP files
live under `tests/validator/fixtures/{good,bad}/` so they double as
documentation of what "valid" and "invalid" block markup look like.

## Running

```bash
# Everything
pytest

# Just the unit tests for a single check
pytest tests/check_py/test_no_fake_forms.py -v

# Skip the Node validator suite (no Node available, or working offline)
pytest --ignore=tests/validator

# Lint + type + format + tests in one go
python3 bin/lint.py && pytest
```

## CI

`pytest` runs as the `tooling-tests` and `validator-smoke` jobs in
[`.github/workflows/check.yml`](../.github/workflows/check.yml), in
parallel with the existing `theme-gate` job that runs
`bin/check.py --all --offline`. See the workflow file for the
authoritative job graph.
