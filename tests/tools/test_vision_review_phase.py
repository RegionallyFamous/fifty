"""Phase-split invariants for `bin/snap-vision-review.py` / `bin/_vision_lib.py`.

The two-step `design.py build` / `dress` pipeline relies on three
things being true of the vision layer:

1. The content-phase kind set and the structural-phase kind set are
   disjoint and together cover ALLOWED_FINDING_KINDS. Gaps produce
   silent false negatives (a real finding is never graded); overlaps
   produce double-counted findings when `--phase all` is later
   reconciled against the per-phase subsets.
2. `kinds_for_phase` is the single source of truth — both the prompt
   layer (enumerated allowed kinds in `build_user_prompt`) and the
   output layer (post-filter in `parse_findings_response`) must
   consult it so a prompt-drift regression can't leak off-phase
   kinds through.
3. `VISION_PHASE_ALL` is the default and is byte-equivalent to the
   pre-split behavior: it returns the full `ALLOWED_FINDING_KINDS`
   and applies NO post-filter.

All via pure-Python imports; no API calls.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))


def _vision_lib():
    return importlib.import_module("_vision_lib")


def test_content_and_structural_kinds_partition_allowlist() -> None:
    mod = _vision_lib()
    content = mod._CONTENT_VISION_KINDS
    structural = mod._STRUCTURAL_VISION_KINDS
    assert content & structural == set(), (
        f"Content and structural vision kinds overlap: "
        f"{sorted(content & structural)}. Every `vision:*` kind must "
        "belong to exactly one phase."
    )
    assert content | structural == mod.ALLOWED_FINDING_KINDS, (
        f"Content ∪ structural does not cover ALLOWED_FINDING_KINDS. "
        f"Missing: {sorted(mod.ALLOWED_FINDING_KINDS - content - structural)}. "
        "Every kind needs a phase assignment."
    )


def test_content_kinds_match_plan() -> None:
    """The plan specifies the four content-fit kinds by name. If this
    test starts failing because a new catalogue-fit kind was added,
    update the plan AND this test together."""
    mod = _vision_lib()
    expected = frozenset(
        {
            "vision:photography-mismatch",
            "vision:color-clash",
            "vision:brand-violation",
            "vision:mockup-divergent",
        }
    )
    assert expected == mod._CONTENT_VISION_KINDS, (
        f"Content kinds drifted from plan. "
        f"plan:    {sorted(expected)}\n"
        f"code:    {sorted(mod._CONTENT_VISION_KINDS)}\n"
        "Update the plan's 'Kind mapping' table alongside this change."
    )


def test_kinds_for_phase_dispatch() -> None:
    mod = _vision_lib()
    assert mod.kinds_for_phase(mod.VISION_PHASE_CONTENT) == mod._CONTENT_VISION_KINDS
    assert mod.kinds_for_phase(mod.VISION_PHASE_STRUCTURAL) == mod._STRUCTURAL_VISION_KINDS
    assert mod.kinds_for_phase(mod.VISION_PHASE_ALL) == mod.ALLOWED_FINDING_KINDS
    # Unknown phases fall back to ALL -- keeps a garbage CLI value
    # from accidentally dropping every finding.
    assert mod.kinds_for_phase("__garbage__") == mod.ALLOWED_FINDING_KINDS


def test_parse_findings_response_post_filters_by_phase() -> None:
    """Output layer: a response that names a structural kind under
    `--phase content` must be dropped."""
    mod = _vision_lib()
    off_phase_payload = (
        '{"findings": ['
        '{"kind": "vision:typography-overpowered", "severity": "error", '
        '"message": "hero is huge", "rationale": "too big", '
        '"remedy_hint": "shrink", "bbox": null}'
        ']}'
    )
    content_allow = mod.kinds_for_phase(mod.VISION_PHASE_CONTENT)
    out = mod.parse_findings_response(off_phase_payload, kinds_allowlist=content_allow)
    assert out == [], (
        "parse_findings_response must drop structural kinds when "
        "called with the content-phase allowlist. Otherwise `dress`'s "
        "vision review would re-grade structural complaints that "
        "`build` already gated."
    )
    # And keeps an in-phase one.
    in_phase_payload = (
        '{"findings": ['
        '{"kind": "vision:photography-mismatch", "severity": "error", '
        '"message": "cartoons", "rationale": "not photographic", '
        '"remedy_hint": "regen", "bbox": null}'
        ']}'
    )
    out2 = mod.parse_findings_response(in_phase_payload, kinds_allowlist=content_allow)
    assert len(out2) == 1 and out2[0]["kind"] == "vision:photography-mismatch"


def test_default_allowlist_is_full_set() -> None:
    """`parse_findings_response` with no explicit allowlist must behave
    byte-identically to the pre-split behavior (accepts every kind in
    ALLOWED_FINDING_KINDS)."""
    mod = _vision_lib()
    payload = (
        '{"findings": ['
        '{"kind": "vision:typography-overpowered", "severity": "warn", '
        '"message": "m", "rationale": "r", "remedy_hint": null, '
        '"bbox": null},'
        '{"kind": "vision:photography-mismatch", "severity": "warn", '
        '"message": "m", "rationale": "r", "remedy_hint": null, '
        '"bbox": null}'
        ']}'
    )
    out = mod.parse_findings_response(payload)  # no kwarg
    kinds = {f["kind"] for f in out}
    assert kinds == {
        "vision:typography-overpowered",
        "vision:photography-mismatch",
    }, (
        "Default call (no `kinds_allowlist`) must accept every "
        "ALLOWED_FINDING_KINDS; got " + repr(kinds)
    )


def test_build_user_prompt_enumerates_only_phase_kinds() -> None:
    """The prompt layer must narrow the kinds list the model sees so
    the model doesn't waste tokens considering off-phase kinds."""
    mod = _vision_lib()
    content_allow = mod.kinds_for_phase(mod.VISION_PHASE_CONTENT)
    prompt = mod.build_user_prompt(
        theme="t",
        route="r",
        viewport="v",
        intent_md="## intent",
        kinds_allowlist=content_allow,
    )
    # Every content kind appears in the enumerated list.
    for k in content_allow:
        assert f"`{k}`" in prompt, (
            f"Content-phase prompt must enumerate {k!r}; got:\n{prompt}"
        )
    # No structural kind appears.
    for k in mod._STRUCTURAL_VISION_KINDS:
        assert f"`{k}`" not in prompt, (
            f"Content-phase prompt must NOT enumerate structural kind {k!r}. "
            "Leaving it in wastes tokens and invites off-phase findings."
        )


def test_vision_phases_tuple_matches_cli_choices() -> None:
    """`VISION_PHASES` is the single source of truth for the CLI
    `choices=` list. A drift here would let `--phase foo` slip through
    argparse."""
    mod = _vision_lib()
    assert mod.VISION_PHASES == ("structural", "content", "all")
