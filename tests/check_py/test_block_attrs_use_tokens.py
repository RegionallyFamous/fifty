"""Tests for `check_block_attrs_use_tokens`.

Forbids hardcoded `"contentSize":"720px"` / `"aspectRatio":"4/3"` in
block JSON; those values must flow from `theme.json` or a `--wp--custom--`
token.
"""

from __future__ import annotations


def test_passes_on_minimal(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_block_attrs_use_tokens().passed


def test_hardcoded_content_size_px_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        '<!-- wp:group {"layout":{"type":"constrained","contentSize":"720px"}} /-->\n',
        encoding="utf-8",
    )
    assert not check.check_block_attrs_use_tokens().passed


def test_hardcoded_aspect_ratio_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "patterns" / "p.php").write_text(
        "<?php /** Title: X */ ?>\n"
        '<!-- wp:cover {"style":{"dimensions":{"aspectRatio":"4/3"}}} /-->\n',
        encoding="utf-8",
    )
    assert not check.check_block_attrs_use_tokens().passed


def test_token_contentsize_passes(minimal_theme, bind_check_root):
    """The canonical replacement uses a `var(--wp--custom--…)` token."""
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        '<!-- wp:group {"layout":{"type":"constrained","contentSize":"var(--wp--custom--layout--narrow)"}} /-->\n',
        encoding="utf-8",
    )
    assert check.check_block_attrs_use_tokens().passed
