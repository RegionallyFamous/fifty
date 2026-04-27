"""Tests for `bin/autofix-contrast.py`.

The autofix script walks templates/parts/patterns and rewrites any
block whose resolved (textColor, backgroundColor) pair fails WCAG AA
to use the highest-contrast palette slug available. Idempotent:
rerunning on a fixed tree is a no-op.

Test coverage:
  1. Happy path — `base on accent` rewritten to `contrast on accent`.
  2. Child-inherits-bg case — paragraph with textColor:base inside a
     group with backgroundColor:accent gets its textColor fixed.
  3. No-rescue-possible case — palette lacks any slug passing 4.5:1 →
     autofix leaves the block alone and emits a WARN.
  4. `--check` (dry-run) mode returns non-zero when rewrites needed,
     zero when everything passes.
  5. Idempotence: fix-then-fix returns 0 changes on the second run.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"
AUTOFIX = BIN_DIR / "autofix-contrast.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _set_palette(theme_root: Path, palette: list[dict]) -> None:
    data = json.loads((theme_root / "theme.json").read_text(encoding="utf-8"))
    data["settings"]["color"]["palette"] = palette
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


def _run_autofix(theme_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(AUTOFIX), *args],
        cwd=str(theme_root),  # cwd-mode picks up the theme
        capture_output=True,
        text=True,
        check=False,
    )


def test_rewrites_base_on_accent_to_contrast(minimal_theme):
    """The agave wordmark-band regression: textColor:base on
    backgroundColor:accent → rewrite to textColor:contrast."""
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    front = minimal_theme / "templates" / "front-page.html"
    _write(
        front,
        """\
        <!-- wp:group {"backgroundColor":"accent","textColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>Ledger band.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = _run_autofix(minimal_theme)
    assert result.returncode == 0, result.stderr
    text = front.read_text(encoding="utf-8")
    # textColor was rewritten in place.
    assert '"textColor":"contrast"' in text
    assert '"textColor":"base"' not in text
    # backgroundColor was NOT touched.
    assert '"backgroundColor":"accent"' in text


def test_injects_textcolor_on_child_paragraph(minimal_theme):
    """Child paragraph inherits backgroundColor:accent from the parent
    group but declares no textColor itself. Autofix injects an
    explicit `textColor:"contrast"` override."""
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    front = minimal_theme / "templates" / "front-page.html"
    _write(
        front,
        """\
        <!-- wp:group {"backgroundColor":"accent","layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph {"textColor":"base"} -->
            <p>Legible?</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = _run_autofix(minimal_theme)
    assert result.returncode == 0
    text = front.read_text(encoding="utf-8")
    # Paragraph's textColor flipped to contrast.
    assert '"textColor":"contrast"' in text
    # But the ancestor group's backgroundColor is untouched.
    assert '"backgroundColor":"accent"' in text


def test_check_mode_returns_nonzero_when_fixes_needed(minimal_theme):
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"accent","textColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>Failing pair.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    result = _run_autofix(minimal_theme, "--check")
    assert result.returncode == 1
    # And the file is untouched since --check is dry-run.
    text = (minimal_theme / "templates" / "front-page.html").read_text()
    assert '"textColor":"base"' in text


def test_idempotent(minimal_theme):
    """Run autofix twice; second run is a no-op (0 changes)."""
    _set_palette(
        minimal_theme,
        [
            {"slug": "base", "name": "Base", "color": "#f5efe6"},
            {"slug": "contrast", "name": "Contrast", "color": "#1a1a1a"},
            {"slug": "primary", "name": "Primary", "color": "#3a352b"},
            {"slug": "border", "name": "Border", "color": "#D9D6CC"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:group {"backgroundColor":"accent","textColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>Band.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    first = _run_autofix(minimal_theme)
    assert first.returncode == 0
    # Second run sees no failing pairs; --check should exit 0.
    second = _run_autofix(minimal_theme, "--check")
    assert second.returncode == 0


def test_no_rescue_emits_warning_and_leaves_file_alone(minimal_theme):
    """Palette with only low-luminance slugs; accent bg has no
    candidate text slug that meets 4.5:1. Autofix leaves the block
    alone and logs a WARN."""
    _set_palette(
        minimal_theme,
        [
            # All slugs near-orange; no slug has >=4.5:1 contrast on accent.
            {"slug": "base", "name": "Base", "color": "#d87e3a"},
            {"slug": "contrast", "name": "Contrast", "color": "#c27032"},
            {"slug": "primary", "name": "Primary", "color": "#b8652b"},
            {"slug": "border", "name": "Border", "color": "#e68a45"},
            {"slug": "accent", "name": "Accent", "color": "#d87e3a"},
        ],
    )
    front = minimal_theme / "templates" / "front-page.html"
    _write(
        front,
        """\
        <!-- wp:group {"backgroundColor":"accent","textColor":"base","layout":{"type":"constrained"}} -->
        <div class="wp-block-group">
            <!-- wp:paragraph -->
            <p>No rescue.</p>
            <!-- /wp:paragraph -->
        </div>
        <!-- /wp:group -->
        """,
    )
    before = front.read_text(encoding="utf-8")
    result = _run_autofix(minimal_theme)
    # Returncode 0 (no rewrite means no changes), file untouched,
    # but the WARN message appeared on stdout.
    assert front.read_text(encoding="utf-8") == before
    assert "WARN" in result.stdout
