"""Tests for `check_pattern_microcopy_distinct` and
`check_all_rendered_text_distinct_across_themes` (cross-theme).

Both checks use `iter_themes()` to enumerate siblings, so they ride on
the monorepo fixture with its two themes (obel + chonk).
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _w(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


# ---------------------------------------------------------------------------
# check_pattern_microcopy_distinct
# ---------------------------------------------------------------------------
def test_microcopy_distinct_when_patterns_differ(monorepo, bind_check_root):
    _w(
        monorepo["obel"] / "patterns" / "hero.php",
        """\
        <?php /** Title: Hero */ ?>
        <?php esc_html_e( 'A quiet shop for unusual things.', 'obel' ); ?>
        """,
    )
    _w(
        monorepo["chonk"] / "patterns" / "hero.php",
        """\
        <?php /** Title: Hero */ ?>
        <?php esc_html_e( 'Loud colors, louder objects, zero apologies.', 'chonk' ); ?>
        """,
    )
    check = bind_check_root(monorepo["obel"])
    assert check.check_pattern_microcopy_distinct().passed


def test_microcopy_fails_when_same_string_in_same_named_pattern(monorepo, bind_check_root):
    shared = 'esc_html_e( "A short statement of intent that repeats.", "THEME" );'
    _w(
        monorepo["obel"] / "patterns" / "hero.php",
        f"<?php /** Title: Hero */ ?>\n<?php {shared.replace('THEME', 'obel')} ?>\n",
    )
    _w(
        monorepo["chonk"] / "patterns" / "hero.php",
        f"<?php /** Title: Hero */ ?>\n<?php {shared.replace('THEME', 'chonk')} ?>\n",
    )
    check = bind_check_root(monorepo["obel"])
    result = check.check_pattern_microcopy_distinct()
    assert not result.passed


def test_microcopy_fails_on_shared_heading_verbatim(monorepo, bind_check_root):
    shared = (
        '<!-- wp:heading {"content":"Our latest collection arrives"} -->'
        "<h2>Our latest collection arrives</h2><!-- /wp:heading -->\n"
    )
    _w(monorepo["obel"] / "templates" / "front-page.html", shared)
    _w(monorepo["chonk"] / "templates" / "front-page.html", shared)
    check = bind_check_root(monorepo["obel"])
    assert not check.check_pattern_microcopy_distinct().passed


# ---------------------------------------------------------------------------
# check_all_rendered_text_distinct_across_themes
# ---------------------------------------------------------------------------
def test_all_text_distinct_passes_when_copy_differs(monorepo, bind_check_root):
    _w(
        monorepo["obel"] / "patterns" / "about.php",
        """\
        <?php /** Title: About */ ?>
        <!-- wp:paragraph --><p>Obel keeps a short list of things worth holding.</p><!-- /wp:paragraph -->
        """,
    )
    _w(
        monorepo["chonk"] / "patterns" / "about.php",
        """\
        <?php /** Title: About */ ?>
        <!-- wp:paragraph --><p>Chonk lists loud objects that refuse to hide.</p><!-- /wp:paragraph -->
        """,
    )
    check = bind_check_root(monorepo["obel"])
    result = check.check_all_rendered_text_distinct_across_themes()
    # Either passes outright or skips if the two themes share no
    # scannable copy at all.
    assert result.passed or result.skipped


def test_all_text_distinct_fails_when_paragraph_shared_verbatim(monorepo, bind_check_root):
    shared_p = (
        "<!-- wp:paragraph --><p>A two or three sentence placeholder explaining "
        "why this brand exists and what it keeps on the shelf.</p><!-- /wp:paragraph -->\n"
    )
    _w(monorepo["obel"] / "patterns" / "about.php", "<?php /** Title: About */ ?>\n" + shared_p)
    _w(monorepo["chonk"] / "patterns" / "about.php", "<?php /** Title: About */ ?>\n" + shared_p)
    check = bind_check_root(monorepo["obel"])
    assert not check.check_all_rendered_text_distinct_across_themes().passed
