"""Static-inspection tests for the `design.py build` / `dress` subcommands.

Mirrors the style of `tests/tools/test_design_phases.py` — AST walk
over `bin/design.py` to assert phase-list invariants without booting
Playground.

Invariants locked down here:

1. `_PHASES_FOR_BUILD` and `_PHASES_FOR_DRESS` are both subsets of the
   full `PHASES` tuple. No subcommand may invent a phase.
2. Every phase in either list has a real handler in `_PHASE_HANDLERS`.
3. `build` excludes every phase that's specific to the content-fit
   pass (`photos`, `microcopy`, `frontpage`, `vision-review`). A regression
   here means `design.py build` would try to regenerate photos before
   the spec-driven structural pass is green.
4. `dress` excludes every phase that's part of the structural
   bring-up (everything up to and including `prepublish`). A regression
   means `dress` would re-clone the theme, which is destructive.
5. Both subcommands end with `commit` + `publish` so each step lands
   its own commit with a distinct headline (`design: build <slug>` /
   `design: dress <slug>`).
6. The flat CLI (no subcommand) still runs the full `PHASES` tuple —
   protects the back-compat contract in the plan's acceptance criteria.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN_PY = ROOT / "bin" / "design.py"


def _tuple_literal(name: str) -> tuple[str, ...]:
    """Parse `bin/design.py` and return the tuple literal assigned to
    `name` at module scope. Uses AST so interspersed comments can't
    confuse a regex."""
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
            and isinstance(node.value, ast.Tuple)
        ):
            out: list[str] = []
            for elt in node.value.elts:
                assert isinstance(elt, ast.Constant) and isinstance(elt.value, str), (
                    f"bin/design.py {name} contains a non-string element; "
                    "every phase must be a plain string."
                )
                out.append(elt.value)
            return tuple(out)
    raise AssertionError(f"bin/design.py does not define a top-level {name} tuple")


def _phase_handler_keys() -> set[str]:
    """Return the set of keys in `_PHASE_HANDLERS`."""
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_PHASE_HANDLERS"
            and isinstance(node.value, ast.Dict)
        ):
            out: set[str] = set()
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out.add(key.value)
            return out
    raise AssertionError("bin/design.py does not define _PHASE_HANDLERS")


def test_build_phases_subset_of_phases() -> None:
    phases = _tuple_literal("PHASES")
    build = _tuple_literal("_PHASES_FOR_BUILD")
    assert set(build).issubset(set(phases)), (
        f"_PHASES_FOR_BUILD contains phases not in PHASES: "
        f"{set(build) - set(phases)}. Every subcommand phase must be "
        "a real phase with a handler."
    )


def test_dress_phases_subset_of_phases() -> None:
    phases = _tuple_literal("PHASES")
    dress = _tuple_literal("_PHASES_FOR_DRESS")
    assert set(dress).issubset(set(phases)), (
        f"_PHASES_FOR_DRESS contains phases not in PHASES: "
        f"{set(dress) - set(phases)}."
    )


def test_build_and_dress_phases_all_have_handlers() -> None:
    handlers = _phase_handler_keys()
    for name in ("_PHASES_FOR_BUILD", "_PHASES_FOR_DRESS"):
        for phase in _tuple_literal(name):
            assert phase in handlers, (
                f"{name} lists {phase!r} but _PHASE_HANDLERS has no "
                "entry for it. Runtime dispatch would KeyError."
            )


def test_build_excludes_content_fit_phases() -> None:
    """`build` is the structural step and must not try to regenerate
    photos / microcopy / front-page / vision-review. Those belong to
    `dress`; running them in `build` would waste budget and clobber
    artifacts before the structural pass is green."""
    build = set(_tuple_literal("_PHASES_FOR_BUILD"))
    forbidden = {"photos", "microcopy", "frontpage", "vision-review"}
    overlap = build & forbidden
    assert not overlap, (
        f"_PHASES_FOR_BUILD must NOT contain {sorted(forbidden)}; "
        f"got overlap {sorted(overlap)}. These are dress-only phases."
    )


def test_dress_excludes_structural_bring_up_phases() -> None:
    """`dress` presumes `build` already shipped a structurally sound
    theme; it must not re-clone, re-apply palette, re-index, etc."""
    dress = set(_tuple_literal("_PHASES_FOR_DRESS"))
    # Every phase strictly before `photos` in PHASES is structural
    # bring-up and must not be in dress.
    phases = _tuple_literal("PHASES")
    photos_idx = phases.index("photos")
    pre_dress = set(phases[:photos_idx])
    overlap = dress & pre_dress
    assert not overlap, (
        f"_PHASES_FOR_DRESS contains structural bring-up phases "
        f"{sorted(overlap)}. These belong to `build`; re-running them "
        "in `dress` would be destructive (re-clone) or wasteful."
    )


def test_both_subcommands_end_with_commit_publish() -> None:
    """Each subcommand produces its own commit so the git history
    shows `design: build <slug>` and `design: dress <slug>` as
    separate SHAs."""
    for name in ("_PHASES_FOR_BUILD", "_PHASES_FOR_DRESS"):
        tup = _tuple_literal(name)
        assert "commit" in tup, f"{name} must include `commit`."
        assert "publish" in tup, f"{name} must include `publish`."
        # publish immediately after commit: a regression that
        # swaps the order would leave the commit without a push.
        assert tup.index("commit") < tup.index("publish"), (
            f"{name} must order commit before publish."
        )


def test_flat_cli_full_pipeline_unchanged() -> None:
    """The flat CLI (`design.py --spec X`, no subcommand) MUST still
    run the full PHASES tuple. The plan's acceptance criterion #3
    says the flat CLI is byte-identical to pre-split behavior; this
    test protects that by asserting `_select_phases_for_subcommand`
    returns None (i.e. "use _select_phases") when subcommand is None.
    """
    sys.path.insert(0, str(ROOT / "bin"))
    import importlib

    design = importlib.import_module("design")
    importlib.reload(design)
    assert design._select_phases_for_subcommand(None) is None, (
        "Flat CLI must fall through to _select_phases; "
        "`_select_phases_for_subcommand(None)` should return None."
    )
    assert design._select_phases_for_subcommand("build") == design._PHASES_FOR_BUILD
    assert design._select_phases_for_subcommand("dress") == design._PHASES_FOR_DRESS


def test_banners_include_next_step_hint() -> None:
    """The OK banners must both point at the next step so an operator
    who just finished `build` knows to run `dress`, and one who just
    finished `dress` knows to run `promote-theme`."""
    sys.path.insert(0, str(ROOT / "bin"))
    import importlib

    design = importlib.import_module("design")
    importlib.reload(design)
    build_banner = design.BUILD_OK_BANNER.format(slug="__test__")
    dress_banner = design.DRESS_OK_BANNER.format(slug="__test__")
    assert "design.py dress" in build_banner, (
        "BUILD_OK_BANNER must tell the operator to run `design.py dress` next."
    )
    assert "promote-theme" in dress_banner, (
        "DRESS_OK_BANNER must tell the operator to run `promote-theme` next."
    )
    assert "__test__" in build_banner
    assert "__test__" in dress_banner
