"""Tests for `check_no_duplicate_templates`."""

from __future__ import annotations


def test_distinct_templates_pass(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        "<!-- wp:paragraph --><p>page</p><!-- /wp:paragraph -->\n",
        encoding="utf-8",
    )
    (minimal_theme / "templates" / "single.html").write_text(
        "<!-- wp:paragraph --><p>single</p><!-- /wp:paragraph -->\n",
        encoding="utf-8",
    )
    assert check.check_no_duplicate_templates().passed


def test_byte_identical_templates_fail(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    same = "<!-- wp:paragraph --><p>same</p><!-- /wp:paragraph -->\n"
    (minimal_theme / "templates" / "page.html").write_text(same, encoding="utf-8")
    (minimal_theme / "templates" / "single.html").write_text(same, encoding="utf-8")
    result = check.check_no_duplicate_templates()
    assert not result.passed


def test_missing_templates_dir_fails(minimal_theme, bind_check_root):
    import shutil

    shutil.rmtree(minimal_theme / "templates")
    check = bind_check_root(minimal_theme)
    assert not check.check_no_duplicate_templates().passed
