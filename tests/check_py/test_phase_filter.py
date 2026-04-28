"""Phase-filter invariants for `bin/check.py`.

The two-step `design.py build` / `design.py dress` pipeline relies on
two things being true about `bin/check.py`:

1. Every name in `_CONTENT_FIT_CHECK_NAMES` is actually a check the
   module invokes. A rename that breaks the tie would silently demote
   a content-fit check to "runs in structural" — a freshly cloned
   theme whose product photos are still upstream cartoons would pass
   `design.py build --spec X` AND ALSO pass every structural check
   even though the photo-diversity gate was secretly off. This is the
   single worst drift mode the refactor can have, so we lock it down.

2. `--phase structural` and `--phase content` partition the full
   check set exactly (no overlaps, no gaps) and together equal
   `--phase all`.

All tests use static inspection via pure-Python imports — no Playground,
no filesystem mutations, no API calls.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))


def _load_check_module():
    """Reload `bin/check.py` fresh each call so tests stay order-independent."""
    if "check" in sys.modules:
        return importlib.reload(sys.modules["check"])
    return importlib.import_module("check")


def _check_names_from_build_results(offline: bool = True) -> list[str]:
    """Return the ordered list of function names that `_build_results` registers.

    Uses the offline branch so the test runs without network (and
    without picking up any online-only side effects).
    """
    mod = _load_check_module()
    # `ROOT` is read inside each check closure, but `_build_results`
    # itself only returns the tuples. No theme root needs to be set.
    return [name for name, _thunk in mod._build_results(offline=offline)]


def test_every_content_name_is_invoked_by_build_results() -> None:
    """The frozenset and the registry must not drift.

    If someone renames `check_product_images_json_complete` (or any
    other content-fit check) without updating
    `_CONTENT_FIT_CHECK_NAMES`, the phase filter will silently stop
    demoting that check to "content only" and `design.py build`
    on a fresh theme will fail at the structural gate.
    """
    mod = _load_check_module()
    registered = set(_check_names_from_build_results())
    missing = mod._CONTENT_FIT_CHECK_NAMES - registered
    assert not missing, (
        "The following names are listed in "
        "`_CONTENT_FIT_CHECK_NAMES` but aren't in `_build_results()`. "
        "Either the check was renamed (update the frozenset) or it was "
        f"dropped (remove it from the frozenset): {sorted(missing)}"
    )


def test_phase_sets_partition_the_full_registry() -> None:
    """`structural` ∪ `content` == every registered check, no overlap."""
    mod = _load_check_module()
    names = set(_check_names_from_build_results())
    structural = {n for n in names if mod._phase_for(n) == mod.PHASE_STRUCTURAL}
    content = {n for n in names if mod._phase_for(n) == mod.PHASE_CONTENT}
    assert not (structural & content), (
        f"A check belongs to both phases; this cannot happen: "
        f"{sorted(structural & content)}"
    )
    assert structural | content == names, (
        f"Some checks belong to neither phase: {sorted(names - structural - content)}"
    )


def test_phase_all_preserves_name_set_and_order() -> None:
    """`--phase all` must be byte-equivalent to the pre-split behavior.

    Not about rendered output (the dim `[structural]` / `[content]`
    prefix is explicitly additive) — about the set of checks that run
    and the order they run in. Flipping `--phase all` must leave both
    untouched.
    """
    names = _check_names_from_build_results()
    mod = _load_check_module()
    kept_all = [n for n in names if mod._phase_keeps(n, mod.PHASE_ALL)]
    assert kept_all == names, (
        "`--phase all` dropped or reordered a check. The filter should "
        "be an identity pass in this mode."
    )


def test_phase_structural_drops_exactly_the_content_set() -> None:
    """`--phase structural` must drop precisely the 10 content-fit checks
    (and the number 10 matches the plan). If the frozenset grows, this
    test fails loudly so a new content check doesn't accidentally ship
    as structural.
    """
    mod = _load_check_module()
    names = _check_names_from_build_results()
    kept = [n for n in names if mod._phase_keeps(n, mod.PHASE_STRUCTURAL)]
    dropped = set(names) - set(kept)
    assert dropped == mod._CONTENT_FIT_CHECK_NAMES, (
        f"`--phase structural` dropped {sorted(dropped)} but "
        f"`_CONTENT_FIT_CHECK_NAMES` == {sorted(mod._CONTENT_FIT_CHECK_NAMES)}. "
        "The filter must agree with the frozenset."
    )
    assert len(dropped) == 10, (
        f"Plan says 10 content-fit checks; found {len(dropped)}. "
        "Either the plan is stale or a new content check was added. "
        "If the latter, update this count and the plan together."
    )


def test_phase_content_complements_phase_structural() -> None:
    """`--phase content` must keep exactly what `--phase structural` drops."""
    mod = _load_check_module()
    names = _check_names_from_build_results()
    content_kept = {n for n in names if mod._phase_keeps(n, mod.PHASE_CONTENT)}
    structural_kept = {n for n in names if mod._phase_keeps(n, mod.PHASE_STRUCTURAL)}
    assert content_kept == mod._CONTENT_FIT_CHECK_NAMES, (
        "`--phase content` keeps exactly `_CONTENT_FIT_CHECK_NAMES`."
    )
    assert content_kept | structural_kept == set(names), (
        "Together the two partitions cover every registered check."
    )
    assert not (content_kept & structural_kept), (
        "The partitions are disjoint."
    )


def test_phase_constants_exist_and_are_canonical_strings() -> None:
    """A lint-style guard: constants are the single source of truth for
    the CLI choices and the Result tag. Renaming one without the other
    would break either the CLI or the render pass silently."""
    mod = _load_check_module()
    assert mod.PHASE_STRUCTURAL == "structural"
    assert mod.PHASE_CONTENT == "content"
    assert mod.PHASE_ALL == "all"
    assert mod._PHASES == ("structural", "content", "all")
