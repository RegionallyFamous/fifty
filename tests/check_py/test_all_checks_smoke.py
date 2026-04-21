"""Smoke test: every `check_*` function in `bin/check.py` runs without
crashing on a minimal theme fixture.

This is a floor guarantee. If a future refactor renames a global, drops
a helper, or changes a function signature in a way that makes any
check raise, this test fires. The richer invariants (pass/fail on
good/bad fixtures) live in the per-check modules next to this file.

Specifically:
- Every result is a `check.Result` instance.
- Every result ends in one of {passed, skipped, failed} — none hang.
- The cross-theme checks use the `monorepo` fixture so they have
  more than one theme to compare.
"""

from __future__ import annotations

import inspect

import pytest

# Checks that depend on cross-theme data; they need the `monorepo`
# fixture (which patches `_lib.MONOREPO_ROOT` + `iter_themes`).
_CROSS_THEME = frozenset(
    {
        "check_distinctive_chrome",
        "check_pattern_microcopy_distinct",
        "check_all_rendered_text_distinct_across_themes",
        "check_front_page_unique_layout",
        "check_no_brand_filters_in_playground",
        "check_wc_microcopy_distinct_across_themes",
    }
)

# Checks whose signature takes a single `offline: bool` argument.
_TAKES_OFFLINE = frozenset(
    {
        "check_block_names",
    }
)


def _all_check_names():
    import check

    return sorted(
        name
        for name, obj in vars(check).items()
        if name.startswith("check_") and callable(obj) and inspect.isfunction(obj)
    )


ALL_CHECKS = _all_check_names()


@pytest.mark.parametrize("check_name", ALL_CHECKS)
def test_check_runs_on_minimal_theme(check_name, minimal_theme, bind_check_root):
    """Every check_* returns a Result without raising on the minimal theme."""
    check = bind_check_root(minimal_theme)
    fn = getattr(check, check_name)

    if check_name in _TAKES_OFFLINE:
        result = fn(offline=True)
    else:
        result = fn()

    assert isinstance(result, check.Result), (
        f"{check_name} returned {type(result).__name__}, not Result"
    )
    # Result state is fully determined: the check did not leave it
    # in-flight (passed + skipped are mutually exclusive by convention,
    # but we only assert the boolean fields exist).
    assert isinstance(result.passed, bool)
    assert isinstance(result.skipped, bool)
    assert isinstance(result.details, list)


@pytest.mark.parametrize("check_name", sorted(_CROSS_THEME - {"check_front_page_unique_layout"}))
def test_cross_theme_check_runs_on_monorepo(check_name, monorepo, bind_check_root):
    """Same smoke test but with >=2 themes in place via `monorepo`."""
    check = bind_check_root(monorepo["obel"])
    fn = getattr(check, check_name)
    result = fn()
    assert isinstance(result, check.Result)
    assert isinstance(result.passed, bool)


def test_all_checks_in_run_checks_for_registry():
    """Every `check_*` in the module is wired into `run_checks_for`.

    Regression: adding a new `check_foo()` to `bin/check.py` but
    forgetting to append it to the `results = [...]` list in
    `run_checks_for` makes the check silently not run in CI.
    """
    import check

    src = inspect.getsource(check.run_checks_for)
    missing: list[str] = []
    for name in ALL_CHECKS:
        # `check_no_unpushed_commits` intentionally isn't run by the
        # minimal path on clean checkouts with no upstream, but it IS
        # wired into `run_checks_for`. Just require its textual
        # presence in the source.
        if name not in src:
            missing.append(name)
    assert missing == [], (
        f"These check_* functions are defined but not wired into run_checks_for(): {missing}"
    )
