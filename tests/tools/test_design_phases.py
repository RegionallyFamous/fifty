"""Static-inspection tests for the phase contract of `bin/design.py`.

Background
----------
`bin/design.py` runs an ordered pipeline of named phases. Two specific
ordering invariants matter enough to lock down in a test rather than
rely on code review to catch a regression.

### Invariant #1: `prepublish` runs BEFORE `snap`.

The snap phase boots Playground, which fetches the new theme's
`playground/content/*` and `playground/images/*` from
`raw.githubusercontent.com/<org>/<repo>/<ref>/<slug>/playground/...`.
`bin/snap.py::_auto_detect_content_ref` picks the branch name as `<ref>`
IFF the branch has a pushed counterpart at `origin/<branch>`; otherwise
it falls back to `main`. For a brand-new theme, main does NOT have the
theme's `playground/` files, so the fallback serves a GitHub 404 HTML
page, PHP parses the HTML as CSV, and Playground boot dies at step #10
(`wo-import.php`) with:

    Error: W&O CSV looked malformed: fewer than 2 lines after trim.

This is the failure mode that killed the 2026-04-27 reship of five
themes (run-id dc3812…) after PR #69 unblocked the earlier
`iter_themes()` bug. The cure is the `prepublish` phase, which commits
the scaffolded theme and `git push -u origin HEAD` before snap runs —
so raw.githubusercontent serves the branch's tree, not main's.

Reorder a future phase list so prepublish sits AFTER snap and every new
theme's batch will regress to the 2026-04-27 fail mode. This test locks
the ordering. Matching implementation is in
`bin/design.py::_phase_prepublish`.

### Invariant #2: `--skip-publish` skips `prepublish` too.

`--skip-publish` is documented as "commit locally but don't push". A
mid-pipeline push inside a phase called prepublish obviously contradicts
that intent — snap phase in that mode WILL fail on a brand-new theme
(that's the documented trade-off), but the operator was explicit about
wanting no remote writes. A regression that pushes anyway under
`--skip-publish` would violate operator intent and would silently burn
API-rate / remote-write credentials that the operator was trying to
conserve.

### Invariant #3: `--skip-commit` skips only `commit` + `publish`.

`prepublish` still runs: snap's Playground boot needs a reachable
`raw.githubusercontent.com` ref for a *new* theme's `playground/content/`.
Dropping `prepublish` under `--skip-commit` regressed `build --skip-commit`
with HTTP 404 on `content.xml` before Playground boots.

Why this is a static source scan, not a behavioural test
--------------------------------------------------------
Full behavioural coverage would require a git sandbox, a spec, and a
mocked `git push`. The phase-list + gating logic is three lines of
Python that a grep-the-source test catches just as reliably and runs
in a millisecond — the grep-the-source shape of
`tests/tools/test_ci_yaml.py` is the right precedent.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DESIGN_PY = ROOT / "bin" / "design.py"


def _extract_drop_set_for_skip_flag(flag_attr: str) -> set[str]:
    """Walk the AST of `bin/design.py`'s top-level `main()` and return
    the set literal on the RHS of the ``phases_to_run = [... if p not in
    {…}]`` list comprehension guarded by ``args.<flag_attr>``.

    This is an AST walk rather than a regex because the set literal
    contains string constants (`"prepublish"`, `"commit"`, `"publish"`)
    that a string-literal-blanking helper would wipe out.

    Matches both `if args.skip_commit:` and `elif args.skip_publish:`
    shapes; the only thing the walker looks at is the `args.<flag>`
    test expression.
    """
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _find_if(node: ast.AST) -> ast.If | None:
        """Descend into the AST until we find an `If` whose test is
        `args.<flag_attr> and not args.only` (or just `args.<flag_attr>`
        — the `and` right-hand side is ignored).
        """
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.BoolOp):
                for inner in test.values:
                    if (
                        isinstance(inner, ast.Attribute)
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == "args"
                        and inner.attr == flag_attr
                    ):
                        return node
            elif (
                isinstance(test, ast.Attribute)
                and isinstance(test.value, ast.Name)
                and test.value.id == "args"
                and test.attr == flag_attr
            ):
                return node
            if node.orelse:
                # Walk the elif chain and the else body.
                for orelse_child in node.orelse:
                    found = _find_if(orelse_child)
                    if found is not None:
                        return found
            for body_child in node.body:
                found = _find_if(body_child)
                if found is not None:
                    return found
        else:
            for any_child in ast.iter_child_nodes(node):
                found = _find_if(any_child)
                if found is not None:
                    return found
        return None

    if_node = _find_if(tree)
    assert if_node is not None, (
        f"bin/design.py main() has no `if/elif args.{flag_attr}` branch. "
        "If you changed the shape of the skip-flag filter, update this "
        "test or add the branch back."
    )

    # The branch body reassigns `phases_to_run` from a list comp whose
    # test is `p not in {"…", "…"}`. Find the first Set literal inside
    # the branch.
    sets: list[ast.Set] = [n for n in ast.walk(if_node) if isinstance(n, ast.Set)]
    assert sets, (
        f"`args.{flag_attr}` branch no longer contains a set literal "
        "(expected `{...}` on the RHS of `p not in {...}`). Update the "
        "test or restore the expected shape."
    )
    items: set[str] = set()
    for elt in sets[0].elts:
        assert isinstance(elt, ast.Constant) and isinstance(elt.value, str), (
            "set literal in skip-flag filter must contain string "
            "constants only; non-string elements break the dispatch."
        )
        items.add(elt.value)
    return items


def _extract_phases_tuple() -> tuple[str, ...]:
    """Parse `bin/design.py` and return the `PHASES` tuple literal.
    Uses AST so comments between tuple elements can't confuse a regex."""
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "PHASES"
            and isinstance(node.value, ast.Tuple)
        ):
            phases: list[str] = []
            for elt in node.value.elts:
                assert isinstance(elt, ast.Constant) and isinstance(elt.value, str), (
                    "bin/design.py PHASES tuple contains a non-string literal; "
                    "every phase must be a plain string so the phase handler "
                    "registry and the skip-flag filters can key on it."
                )
                phases.append(elt.value)
            return tuple(phases)
    raise AssertionError("bin/design.py does not define a top-level PHASES tuple")


def test_prepublish_runs_before_snap() -> None:
    """`prepublish` must precede `snap` in the phase list. Reordering
    would regress the 2026-04-27 "W&O CSV looked malformed" boot failure
    on every new theme.
    """
    phases = _extract_phases_tuple()
    assert "prepublish" in phases, (
        "`prepublish` phase is missing from bin/design.py PHASES. "
        "Without it, `bin/snap.py shoot <new-theme>` dies at Playground "
        "boot step #10 (`wo-import.php`) with 'W&O CSV looked "
        "malformed: fewer than 2 lines after trim.' because "
        "raw.githubusercontent.com has no content for the new theme's "
        "branch. Add the phase and restore the ordering."
    )
    assert "snap" in phases, "bin/design.py PHASES must include `snap`"
    assert phases.index("prepublish") < phases.index("snap"), (
        f"prepublish ({phases.index('prepublish')}) must run BEFORE snap "
        f"({phases.index('snap')}) — otherwise the snap phase fetches "
        "from a branch that isn't pushed yet and Playground boot dies. "
        f"Current order: {phases}"
    )


def test_scorecard_runs_after_vision_before_baseline() -> None:
    phases = _extract_phases_tuple()
    assert "scorecard" in phases
    assert phases.index("vision-review") < phases.index("scorecard")
    assert phases.index("scorecard") < phases.index("baseline")


def test_prepublish_is_registered_in_phase_handlers() -> None:
    """Every entry in PHASES must have a corresponding handler in
    `_PHASE_HANDLERS`. A phase in the list with no handler would raise
    KeyError at runtime on the first batch — silent test drift we guard
    against here."""
    phases = _extract_phases_tuple()
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    handlers: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_PHASE_HANDLERS"
            and isinstance(node.value, ast.Dict)
        ):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    handlers.add(key.value)
    assert handlers, "bin/design.py does not define _PHASE_HANDLERS"
    for phase in phases:
        assert phase in handlers, (
            f"Phase {phase!r} is in PHASES but has no handler in "
            "_PHASE_HANDLERS. Add it to the registry or drop it from "
            "PHASES; the runtime dispatch would KeyError on this phase."
        )


def test_contrast_phase_refreshes_generated_wc_overrides() -> None:
    """A freshly cloned theme must get palette-aware generated WC chrome.

    Phase FF in `append-wc-overrides.py` computes `body.theme-<slug>`
    hover-polarity selectors from the current theme palettes. If
    `design.py build` skips that script after cloning a new slug, the
    clone keeps the source theme's old generated chunk and dark-base
    concepts fail `check_hover_state_legibility`.
    """
    src = DESIGN_PY.read_text(encoding="utf-8")
    assert "append-wc-overrides.py" in src
    assert '"--update", spec.slug' in src


def test_skip_snap_check_does_not_require_snap_evidence() -> None:
    """`--skip-snap` smoke runs intentionally have no tmp/snaps evidence."""
    src = DESIGN_PY.read_text(encoding="utf-8")
    assert 'getattr(args, "skip_snap", False)' in src
    assert 'env.setdefault("FIFTY_REQUIRE_SNAP_EVIDENCE", "1")' in src


def test_final_commit_refreshes_last_mile_artifacts() -> None:
    """The final commit must not rely on earlier phases alone.

    Operators frequently re-run from `--only commit` or after a partial
    failure. Phase N should refresh INDEX.md, home snap evidence, and
    screenshot.png immediately before staging so copied source-theme
    screenshots and stale indexes cannot reach the pre-commit hook.
    """
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    commit_fn: ast.FunctionDef | None = None
    guard_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_phase_commit":
            commit_fn = node
        if isinstance(node, ast.FunctionDef) and node.name == "_refresh_final_commit_artifacts":
            guard_fn = node
    assert commit_fn is not None, "bin/design.py no longer defines `_phase_commit`"
    assert guard_fn is not None, (
        "bin/design.py must define `_refresh_final_commit_artifacts` so the "
        "last-mile artifact contract is named and testable."
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_refresh_final_commit_artifacts"
        for node in ast.walk(commit_fn)
    ), "_phase_commit must call `_refresh_final_commit_artifacts` before staging."

    guard_src = ast.get_source_segment(src, guard_fn) or ""
    for required in (
        "_phase_index(spec, dest, args)",
        '"shoot"',
        '"home"',
        '"mobile"',
        '"desktop"',
        '"--no-skip"',
        "_run_theme_screenshot(spec, strict=True)",
    ):
        assert required in guard_src


def test_skip_publish_drops_prepublish_too() -> None:
    """`--skip-publish` must filter out `prepublish` in addition to
    `publish`. A regression that lets prepublish push under
    `--skip-publish` would violate the documented "commit locally but
    don't push" contract."""
    drop_set = _extract_drop_set_for_skip_flag("skip_publish")
    for required in ("prepublish", "publish"):
        assert required in drop_set, (
            f"`--skip-publish` branch no longer drops {required!r}. "
            "A mid-pipeline push inside `prepublish` would violate the "
            "documented 'commit locally but don't push' contract. "
            f"Re-add {required!r} to the drop set."
        )


def test_skip_flags_are_independent_not_elif_chained() -> None:
    """Combining --skip-commit with --skip-prepublish must honor both.

    A local design-watch rehearsal used `--skip-commit --skip-publish
    --skip-prepublish` and still created a pre-snap content commit
    because these filters were chained as `if` / `elif` / `elif`.
    """
    src = DESIGN_PY.read_text(encoding="utf-8")
    assert "elif args.skip_publish" not in src
    assert "elif args.skip_prepublish" not in src


def test_prepublish_push_skips_every_snap_dependent_gate() -> None:
    """The push inside `_phase_prepublish` must set every documented
    `FIFTY_SKIP_*=1` env var whose input is snap evidence that this
    phase hasn't produced yet. Missing any one of them stalls the
    push with a 3-retry pre-push-hook failure.

    Previously-observed regressions:
      * Missing FIFTY_SKIP_BOOT_SMOKE=1 → .githooks/pre-push spins up
        Playground against the not-yet-pushed branch, Playground
        fetches content from `main` (which has no new-theme content),
        boot aborts with "W&O CSV looked malformed: fewer than 2 lines
        after trim.", the hook retries 3 times, and the push exits 1
        after ~120s of wasted work (logged in the 2026-04-27 reship).
      * Missing FIFTY_SKIP_VISUAL_PUSH=1 → `bin/snap.py check --changed`
        runs on a theme with zero snap evidence; false fail.
      * Missing FIFTY_SKIP_EVIDENCE_FRESHNESS=1 → `bin/check.py`'s
        "snap evidence is fresh" gate fails trivially (no snap has
        been produced yet; evidence is stale by definition).

    Every one is a first-class documented escape hatch; using them
    here is NOT a bypass, it's honoring the phase contract (these
    gates have no meaningful input at this point in the pipeline).
    NEVER replace them with `--no-verify` (rule #19).
    """
    required_env_keys = (
        "FIFTY_DESIGN_PREPUBLISH",
        "FIFTY_SKIP_VISUAL_PUSH",
        "FIFTY_SKIP_EVIDENCE_FRESHNESS",
        "FIFTY_SKIP_BOOT_SMOKE",
    )
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    prepublish_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_phase_prepublish":
            prepublish_fn = node
            break
    assert prepublish_fn is not None, (
        "bin/design.py no longer defines `_phase_prepublish`. If the "
        "phase was renamed, update this test; if it was deleted, "
        "PR #70's fix for the 2026-04-27 snap failure has been "
        "reverted and every new-theme batch will regress."
    )
    # Collect every string-constant subscript assignment
    # `env["<key>"] = "1"` inside the function body.
    assigned_keys: set[str] = set()
    for inner in ast.walk(prepublish_fn):
        if (
            isinstance(inner, ast.Assign)
            and len(inner.targets) == 1
            and isinstance(inner.targets[0], ast.Subscript)
            and isinstance(inner.targets[0].value, ast.Name)
            and inner.targets[0].value.id == "env"
            and isinstance(inner.targets[0].slice, ast.Constant)
            and isinstance(inner.targets[0].slice.value, str)
        ):
            assigned_keys.add(inner.targets[0].slice.value)
    for key in required_env_keys:
        assert key in assigned_keys, (
            f"_phase_prepublish's push env no longer sets {key!r}. "
            "The pre-push hook chain runs every snap-dependent gate "
            "unless the matching skip-env is set; a missing skip-env "
            "stalls the push for ~40s/retry × 3 retries per theme "
            f"and the batch reports 'failed' with `git push exited 1`. "
            f'Re-add `env[{key!r}] = "1"` alongside the other two.'
        )


def test_publish_push_skips_redundant_snap_dependent_gates() -> None:
    """The final publish phase runs after design.py has already snapped,
    checked, reported, and committed the generated theme. Re-running the
    pre-push visual gate here can mutate generated allowlist files after
    the commit and reject an otherwise green branch, so publish must set
    the documented skip envs without using --no-verify.
    """
    src = DESIGN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    publish_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_phase_publish":
            publish_fn = node
            break
    assert publish_fn is not None
    assigned_keys: set[str] = set()
    for inner in ast.walk(publish_fn):
        if (
            isinstance(inner, ast.Assign)
            and len(inner.targets) == 1
            and isinstance(inner.targets[0], ast.Subscript)
            and isinstance(inner.targets[0].value, ast.Name)
            and inner.targets[0].value.id == "env"
            and isinstance(inner.targets[0].slice, ast.Constant)
            and isinstance(inner.targets[0].slice.value, str)
        ):
            assigned_keys.add(inner.targets[0].slice.value)

    for key in (
        "FIFTY_SKIP_VISUAL_PUSH",
        "FIFTY_SKIP_EVIDENCE_FRESHNESS",
        "FIFTY_SKIP_BOOT_SMOKE",
    ):
        assert key in assigned_keys
    publish_src = ast.get_source_segment(src, publish_fn) or ""
    assert "--no-verify" not in publish_src


def test_prepublish_commit_skips_evidence_freshness() -> None:
    """The pre-snap scaffold commit itself runs the pre-commit hook.

    At that point snap evidence cannot be fresh yet, because snap runs
    after prepublish. The phase must therefore set the documented
    evidence-freshness skip env on the commit subprocess too, not only
    on the following push.
    """
    src = DESIGN_PY.read_text(encoding="utf-8")
    assert 'commit_env["FIFTY_SKIP_EVIDENCE_FRESHNESS"] = "1"' in src
    assert 'subprocess.call([*git, "commit", "-m", msg], env=commit_env)' in src


def test_sale_badge_text_contrast_repairs_after_palette_apply() -> None:
    sys.path.insert(0, str(ROOT / "bin"))
    import importlib

    design = importlib.import_module("design")
    importlib.reload(design)
    theme_json: dict[str, Any] = {
        "settings": {
            "color": {
                "palette": [
                    {"slug": "base", "color": "#F5EFE6"},
                    {"slug": "contrast", "color": "#0A0A0A"},
                    {"slug": "accent", "color": "#C8281A"},
                ]
            }
        },
        "styles": {
            "blocks": {
                "woocommerce/product-sale-badge": {
                    "color": {
                        "background": "var(--wp--preset--color--accent)",
                        "text": "var(--wp--preset--color--contrast)",
                    }
                }
            }
        },
    }

    design._repair_sale_badge_text_contrast(theme_json)

    badge = theme_json["styles"]["blocks"]["woocommerce/product-sale-badge"]
    assert badge["color"]["text"] == "var(--wp--preset--color--base)"


def test_site_title_mobile_overflow_guard_is_appended_once() -> None:
    sys.path.insert(0, str(ROOT / "bin"))
    import importlib

    design = importlib.import_module("design")
    importlib.reload(design)
    theme_json: dict[str, Any] = {"styles": {"css": "body{color:inherit}"}}

    design._repair_site_title_mobile_overflow(theme_json)
    design._repair_site_title_mobile_overflow(theme_json)

    css = theme_json["styles"]["css"]
    assert css.count("generated-site-title-mobile-overflow") == 1
    assert ".wp-block-site-title,.wp-block-site-title a" in css
    assert "overflow-wrap:anywhere" in css
    assert ".wp-block-group:has(>.wp-block-site-title)" in css


def test_product_reviews_mobile_overflow_guard_is_appended_once() -> None:
    sys.path.insert(0, str(ROOT / "bin"))
    import importlib

    design = importlib.import_module("design")
    importlib.reload(design)
    theme_json: dict[str, Any] = {"styles": {"css": ""}}

    design._repair_product_reviews_mobile_overflow(theme_json)
    design._repair_product_reviews_mobile_overflow(theme_json)

    css = theme_json["styles"]["css"]
    assert css.count("generated-product-reviews-mobile-overflow") == 1
    assert ".wp-block-woocommerce-product-reviews" in css
    assert ".wp-block-woocommerce-product-reviews-title,#reviews" in css
    assert ".comment-reply-title" in css
    assert "white-space:normal" in css


def test_design_runs_phase_invariants_after_each_phase() -> None:
    src = DESIGN_PY.read_text(encoding="utf-8")

    assert "def _run_phase_invariants" in src
    assert "handler(spec, dest, args)" in src
    assert "_run_phase_invariants(spec, dest, phase)" in src
    assert 'phase == "clone"' in src
    assert 'phase == "apply"' in src
    assert 'phase == "seed"' in src
    assert 'phase == "sync"' in src
    assert 'phase == "photos"' in src
    assert 'phase == "microcopy"' in src


def test_snap_phase_accepts_viewport_subset() -> None:
    src = DESIGN_PY.read_text(encoding="utf-8")

    assert "--snap-viewports" in src
    assert "args.snap_viewports" in src
    assert 'cmd.extend(["--viewports", *args.snap_viewports])' in src


def test_phase_invariants_use_factory_rule_rollout_modes() -> None:
    src = DESIGN_PY.read_text(encoding="utf-8")

    assert "from factory_rules import get_rule" in src
    assert 'mode == "report-only"' in src
    assert 'mode == "disabled"' in src


def test_skill_phases_match_code() -> None:
    """The design-theme SKILL documents the phase pipeline in a
    Markdown table; when an agent reads the skill to plan work, the
    table IS the mental model. If the table drifts from `PHASES` in
    `bin/design.py`, agents follow a stale pipeline and land half-done
    themes.

    Lock the two together by parsing the skill's Markdown table and
    comparing its phase column to `PHASES`.
    """
    phases = _extract_phases_tuple()
    skill_path = ROOT / ".claude" / "skills" / "design-theme" / "SKILL.md"
    body = skill_path.read_text(encoding="utf-8")
    import re

    documented: list[str] = []
    for row in re.finditer(
        r"^\|\s*\d+\s*\|\s*\*\*([a-z][a-z0-9-]*)\*\*\s*\|",
        body,
        re.MULTILINE,
    ):
        documented.append(row.group(1))
    assert documented, (
        "design-theme SKILL.md does not list numbered phase rows. "
        "The skill must document every phase in `PHASES` so agents "
        "know what the pipeline runs."
    )
    assert tuple(documented) == phases, (
        "design-theme SKILL.md phase table is out of sync with "
        f"bin/design.py PHASES.\n"
        f"  code:   {phases}\n"
        f"  skill:  {tuple(documented)}\n"
        "Update the markdown table in "
        ".claude/skills/design-theme/SKILL.md to match."
    )


def test_skip_commit_drops_final_commit_and_publish_only() -> None:
    """`--skip-commit` must keep `prepublish` so snap can resolve content.

    Regression: filtering out `prepublish` with `--skip-commit` made
    `design.py build --skip-commit` run `snap` before GitHub served the
    new theme's playground payload (404 preflight on content.xml).
    """
    drop_set = _extract_drop_set_for_skip_flag("skip_commit")
    assert drop_set == {"commit", "publish"}, (
        f"expected {{'commit', 'publish'}} only, got {drop_set!r}"
    )
