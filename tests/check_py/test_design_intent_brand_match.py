"""Tests for `check_design_intent_brand_match`."""

from __future__ import annotations

import textwrap


def _intent_body(h1_line: str) -> str:
    return textwrap.dedent(
        f"""\
        {h1_line}

        ## Voice

        Placeholder voice for the fixture.

        ## Palette

        - `base` `#ffffff` — paper

        ## Typography

        Sans.
        """
    )


def test_skips_when_design_intent_missing(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    r = check.check_design_intent_brand_match()
    assert r.skipped


def test_passes_when_h1_contains_slug(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "design-intent.md").write_text(
        _intent_body("# scratch — design intent"),
        encoding="utf-8",
    )
    assert check.check_design_intent_brand_match().passed


def test_passes_when_h1_uses_spaced_words_for_hyphen_slug(make_theme, bind_check_root):
    root = make_theme(slug="midcentury-depot", title="Midcentury Depot")
    check = bind_check_root(root)
    (root / "design-intent.md").write_text(
        _intent_body("# Midcentury Depot — design intent"),
        encoding="utf-8",
    )
    assert check.check_design_intent_brand_match().passed


def test_fails_when_h1_names_wrong_theme(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "design-intent.md").write_text(
        _intent_body("# foundry — design intent"),
        encoding="utf-8",
    )
    assert not check.check_design_intent_brand_match().passed


def test_fails_when_first_heading_is_h2_not_h1(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "design-intent.md").write_text(
        textwrap.dedent(
            """\
            ## Voice

            Oops — no H1.

            ## Palette

            - `base` `#ffffff` — paper

            ## Typography

            Sans.
            """
        ),
        encoding="utf-8",
    )
    assert not check.check_design_intent_brand_match().passed
