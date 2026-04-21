"""Tests for `bin/check.py:check_no_fake_forms`.

Guards two surfaces:

1. `core/search` allowed only in 5 search-context paths
   (`parts/header.html`, `parts/no-results.html`, `templates/search.html`,
   `templates/product-search-results.html`, `templates/404.html`).

2. `core/html` blocks containing `<form>`, `<input type="email">`,
   or a Subscribe / Sign-up / Notify-me / Join-the-list button.

These tests exist because both surfaces are regex-based; a typo in the
allow-list path or the signal regex would silently ship fake forms back
into the codebase.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_passes_with_no_form_shaped_blocks_anywhere(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "real-cta.php",
        """\
        <?php
        /**
         * Title: Real CTA
         * Slug: scratch/real-cta
         */
        ?>
        <!-- wp:buttons -->
        <div class="wp-block-buttons">
            <!-- wp:button -->
            <div class="wp-block-button">
                <a class="wp-block-button__link wp-element-button" href="/journal/">Read</a>
            </div>
            <!-- /wp:button -->
        </div>
        <!-- /wp:buttons -->
        """,
    )
    assert check.check_no_fake_forms().passed


def test_allows_core_search_in_header_part(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "parts" / "header.html",
        """\
        <!-- wp:group {"layout":{"type":"flex"}} -->
        <div class="wp-block-group">
            <!-- wp:site-title /-->
            <!-- wp:search {"label":"Search","placeholder":"Search"} /-->
        </div>
        <!-- /wp:group -->
        """,
    )
    assert check.check_no_fake_forms().passed


def test_allows_core_search_in_404_template(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "404.html",
        """\
        <!-- wp:heading --><h1>Not found</h1><!-- /wp:heading -->
        <!-- wp:search {"label":"Search","placeholder":"Try again"} /-->
        """,
    )
    assert check.check_no_fake_forms().passed


def test_fails_when_core_search_appears_in_a_pattern(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "fake-newsletter.php",
        """\
        <?php
        /**
         * Title: Fake newsletter
         * Slug: scratch/fake-newsletter
         */
        ?>
        <!-- wp:search {"label":"Email","placeholder":"you@example.com","buttonText":"Subscribe"} /-->
        """,
    )
    result = check.check_no_fake_forms()
    assert not result.passed
    rendered = " ".join(result.details)
    assert "core/search" in rendered
    assert "fake-newsletter.php" in rendered


def test_fails_when_core_search_appears_in_front_page(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:heading --><h1>Welcome</h1><!-- /wp:heading -->
        <!-- wp:search {"placeholder":"you@x"} /-->
        """,
    )
    assert not check.check_no_fake_forms().passed


def test_fails_when_html_block_contains_raw_form(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "raw-form.php",
        """\
        <?php
        /**
         * Title: Raw form
         * Slug: scratch/raw-form
         */
        ?>
        <!-- wp:html -->
        <form action="/?wo-newsletter=1" method="post">
            <input type="email" name="email" placeholder="you@example.com" />
            <button type="submit">Subscribe</button>
        </form>
        <!-- /wp:html -->
        """,
    )
    result = check.check_no_fake_forms()
    assert not result.passed
    rendered = " ".join(result.details)
    assert "raw-form.php" in rendered


def test_fails_when_html_block_contains_input_type_email_only(minimal_theme, bind_check_root):
    """No <form> tag, but the type=email input alone is enough of a signal."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "input-only.php",
        """\
        <?php
        /**
         * Title: Input only
         * Slug: scratch/input-only
         */
        ?>
        <!-- wp:html -->
        <div><input type="email" name="email" /></div>
        <!-- /wp:html -->
        """,
    )
    assert not check.check_no_fake_forms().passed


def test_fails_when_html_block_contains_notify_me_button(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "notify.php",
        """\
        <?php
        /**
         * Title: Notify me
         * Slug: scratch/notify
         */
        ?>
        <!-- wp:html -->
        <div><button>Notify me</button></div>
        <!-- /wp:html -->
        """,
    )
    assert not check.check_no_fake_forms().passed


def test_html_block_without_form_signals_passes(minimal_theme, bind_check_root):
    """A core/html block on its own is fine — the check is about FORM markup."""
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "html-ok.php",
        """\
        <?php
        /**
         * Title: HTML OK
         * Slug: scratch/html-ok
         */
        ?>
        <!-- wp:html -->
        <div class="callout"><p>This is just a styled callout.</p></div>
        <!-- /wp:html -->
        """,
    )
    assert check.check_no_fake_forms().passed
