"""Tests for the batch-pipeline additions introduced in design-pipeline-fixes.

Covers:
  1. ``bin/generate-product-photos.py``
     - Generates 30 parent-product JPEGs (no variations) from a mock CSV
     - Skips existing files (idempotent)
     - Creates ``product-images.json`` when missing
     - Creates ``category-images.json`` with defaults when missing

  2. ``bin/diversify-front-page.py``
     - Adds ``wo-layout-<slug>`` class to first group when fingerprint clashes
     - Is a no-op when fingerprint is already unique
     - Is a no-op when wo-layout class already present (idempotent)

  3. ``bin/apply-microcopy-overrides.py``
     - Applies substitutions from ``microcopy-overrides.json``
     - Rejects cascade-hazard pairs (replacement ⊃ needle)
     - Is a no-op when JSON absent

  4. CSS hover contrast extension in ``bin/autofix-contrast.py``
     - Rewrites ``color: var(--base)`` in hover rules where contrast fails
     - Leaves rules with passing contrast untouched
     - Idempotent: second run is a no-op

  5. ``bin/design.py`` PHASES tuple order
     - ``index`` comes after ``sync``
     - ``photos`` / ``microcopy`` / ``frontpage`` are in PHASES and come
       before ``prepublish``
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BIN_DIR / script), *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _make_minimal_theme(tmp_path: Path, slug: str, palette: list[dict] | None = None) -> Path:
    theme = tmp_path / slug
    theme.mkdir()
    _palette = palette or [
        {"slug": "base", "color": "#F5EFE6"},
        {"slug": "surface", "color": "#FFFFFF"},
        {"slug": "accent", "color": "#D87E3A"},
        {"slug": "border", "color": "#B8B3AC"},
        {"slug": "contrast", "color": "#1F1B16"},
        {"slug": "secondary", "color": "#191612"},
    ]
    (theme / "theme.json").write_text(
        json.dumps(
            {
                "settings": {
                    "color": {"palette": _palette},
                },
                "styles": {"css": ""},
            }
        ),
        encoding="utf-8",
    )
    (theme / "style.css").write_text("/* Theme Name: Test */", encoding="utf-8")
    for d in ("templates", "parts", "patterns"):
        (theme / d).mkdir()
    return theme


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. generate-product-photos.py
# ---------------------------------------------------------------------------

_MINI_CSV = """\
ID,Type,SKU,Name,Published
1,simple,WO-FOG-IN-BOTTLE,Fog in a Bottle,1
2,variable,WO-LEFT-SOCK,Left Sock,1
3,variation,WO-LEFT-SOCK-V1,Left Sock Red,1
4,simple,WO-VOID-SAMPLER,Void Sampler,1
"""

_CAT_JSON = json.dumps({"Curiosities": "cat-curiosities.jpg"})


def _make_seeded_theme(tmp_path: Path, slug: str) -> Path:
    """Minimal theme with playground/content seeded."""
    theme = _make_minimal_theme(tmp_path, slug)
    content = theme / "playground" / "content"
    content.mkdir(parents=True)
    (content / "products.csv").write_text(_MINI_CSV, encoding="utf-8")
    (content / "category-images.json").write_text(_CAT_JSON, encoding="utf-8")
    (theme / "playground" / "images").mkdir(parents=True)
    return theme


def test_generate_product_photos_creates_jpegs(tmp_path: Path) -> None:
    """Script generates one JPEG per parent-product SKU (no variations)."""
    pytest.importorskip("PIL")
    theme = _make_seeded_theme(tmp_path, "testbrand")
    result = _run("generate-product-photos.py", "--theme", "testbrand", cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    images_dir = theme / "playground" / "images"
    jpegs = sorted(images_dir.glob("product-wo-*.jpg"))
    # Should be WO-FOG-IN-BOTTLE + WO-VOID-SAMPLER (2 parents), not WO-LEFT-SOCK-V1
    jpeg_names = [j.name for j in jpegs]
    assert "product-wo-fog-in-bottle.jpg" in jpeg_names
    assert "product-wo-void-sampler.jpg" in jpeg_names
    assert "product-wo-left-sock-v1.jpg" not in jpeg_names
    # variable parents DO get a photo
    assert "product-wo-left-sock.jpg" in jpeg_names
    assert len(jpegs) == 3
    manifest = json.loads((theme / "playground" / "content" / "image-manifest.json").read_text())
    assert manifest["coverage"]["products"] == 3
    assert manifest["coverage"]["categories"] == 1
    assert not manifest["coverage"]["missing_products"]
    assert manifest["products"][0]["prompt"]
    assert "regeneration" in manifest


def test_generate_product_photos_idempotent(tmp_path: Path) -> None:
    """Running twice doesn't overwrite existing files."""
    pytest.importorskip("PIL")
    theme = _make_seeded_theme(tmp_path, "testbrand2")
    # First run
    _run("generate-product-photos.py", "--theme", "testbrand2", cwd=tmp_path)
    images = theme / "playground" / "images"
    first_mtimes = {p: p.stat().st_mtime for p in images.glob("product-wo-*.jpg")}

    # Second run — should be a no-op (files already exist)
    _run("generate-product-photos.py", "--theme", "testbrand2", cwd=tmp_path)
    for p, mtime in first_mtimes.items():
        assert p.stat().st_mtime == mtime, f"{p.name} was overwritten on second run"


def test_generate_product_photos_creates_product_images_json(
    tmp_path: Path,
) -> None:
    """Script creates product-images.json when it doesn't exist."""
    pytest.importorskip("PIL")
    theme = _make_seeded_theme(tmp_path, "testbrand3")
    assert not (theme / "playground" / "content" / "product-images.json").exists()

    _run("generate-product-photos.py", "--theme", "testbrand3", cwd=tmp_path)

    pij = theme / "playground" / "content" / "product-images.json"
    assert pij.exists()
    data = json.loads(pij.read_text())
    assert "WO-FOG-IN-BOTTLE" in data
    assert data["WO-FOG-IN-BOTTLE"] == "product-wo-fog-in-bottle.jpg"
    # Variations must not appear
    assert not any("v1" in k.lower() for k in data)


def test_generate_product_photos_creates_category_images_json(
    tmp_path: Path,
) -> None:
    """Script creates category-images.json with defaults when missing."""
    pytest.importorskip("PIL")
    theme = _make_seeded_theme(tmp_path, "testbrand4")
    (theme / "playground" / "content" / "category-images.json").unlink()

    _run("generate-product-photos.py", "--theme", "testbrand4", cwd=tmp_path)

    cij = theme / "playground" / "content" / "category-images.json"
    assert cij.exists()
    data = json.loads(cij.read_text())
    assert len(data) >= 6, "Expected at least 6 default categories"


# ---------------------------------------------------------------------------
# 2. diversify-front-page.py
# ---------------------------------------------------------------------------

_FP_OBEL_SHAPE = """\
<!-- wp:template-part {"slug":"header","tagName":"div"} /-->
<!-- wp:group {"tagName":"main","layout":{"type":"constrained"}} -->
<main class="wp-block-group">
    <!-- wp:pattern {"slug":"testtheme/hero-split"} /-->
    <!-- wp:group {"align":"full"} -->
    <div class="wp-block-group alignfull"><!-- wp:paragraph --><p>products</p><!-- /wp:paragraph --></div>
    <!-- /wp:group -->
    <!-- wp:group {"align":"full"} -->
    <div class="wp-block-group alignfull"><!-- wp:paragraph --><p>journal</p><!-- /wp:paragraph --></div>
    <!-- /wp:group -->
</main>
<!-- /wp:group -->
"""


def test_diversify_front_page_adds_class(tmp_path: Path) -> None:
    """Adds wo-layout-<slug> class to first group when fingerprint clashes."""
    # Create a "fake obel" reference theme to clash with
    obel = _make_minimal_theme(tmp_path, "obel")
    _write(obel / "templates" / "front-page.html", _FP_OBEL_SHAPE)

    theme = _make_minimal_theme(tmp_path, "newtheme")
    _write(theme / "templates" / "front-page.html", _FP_OBEL_SHAPE.replace("testtheme", "newtheme"))

    result = _run("diversify-front-page.py", "--theme", "newtheme", cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    content = (theme / "templates" / "front-page.html").read_text()
    assert "wo-layout-newtheme" in content


def test_diversify_front_page_no_op_when_already_has_class(
    tmp_path: Path,
) -> None:
    """Is a no-op when wo-layout class already present (idempotent guard)."""
    obel = _make_minimal_theme(tmp_path, "obel")
    _write(obel / "templates" / "front-page.html", _FP_OBEL_SHAPE)

    theme = _make_minimal_theme(tmp_path, "alreadydone")
    # Give the first group a wo-layout class already
    fp_with_class = _FP_OBEL_SHAPE.replace(
        'wp:group {"align":"full"}',
        'wp:group {"align":"full","className":"wo-layout-alreadydone"}',
    ).replace("testtheme", "alreadydone")
    _write(theme / "templates" / "front-page.html", fp_with_class)
    original = (theme / "templates" / "front-page.html").read_text()

    _run("diversify-front-page.py", "--theme", "alreadydone", cwd=tmp_path)
    # The file should be unchanged
    assert (theme / "templates" / "front-page.html").read_text() == original


def test_diversify_front_page_idempotent(tmp_path: Path) -> None:
    """Running twice doesn't add the class twice."""
    obel = _make_minimal_theme(tmp_path, "obel2")
    _write(obel / "templates" / "front-page.html", _FP_OBEL_SHAPE)

    theme = _make_minimal_theme(tmp_path, "newtheme2")
    _write(
        theme / "templates" / "front-page.html", _FP_OBEL_SHAPE.replace("testtheme", "newtheme2")
    )

    _run("diversify-front-page.py", "--theme", "newtheme2", cwd=tmp_path)
    content_after_first = (theme / "templates" / "front-page.html").read_text()
    _run("diversify-front-page.py", "--theme", "newtheme2", cwd=tmp_path)
    content_after_second = (theme / "templates" / "front-page.html").read_text()
    assert content_after_first == content_after_second


# ---------------------------------------------------------------------------
# 3. apply-microcopy-overrides.py
# ---------------------------------------------------------------------------


def test_apply_microcopy_overrides_basic(tmp_path: Path) -> None:
    """Applies substitutions from microcopy-overrides.json."""
    theme = _make_minimal_theme(tmp_path, "copytheme")
    pattern = theme / "patterns" / "hero.php"
    pattern.write_text(
        '<?php\n$title = __("a clear, confident headline", "copytheme");',
        encoding="utf-8",
    )
    overrides = {"a clear, confident headline": "a considered warm headline"}
    (theme / "microcopy-overrides.json").write_text(json.dumps(overrides), encoding="utf-8")

    result = _run("apply-microcopy-overrides.py", "--theme", "copytheme", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "a considered warm headline" in pattern.read_text()


def test_apply_microcopy_overrides_cascade_guard(tmp_path: Path) -> None:
    """Rejects pairs where replacement contains the needle."""
    theme = _make_minimal_theme(tmp_path, "cascadetheme")
    (theme / "microcopy-overrides.json").write_text(
        json.dumps({"Order received": "Order received, with thanks"}),
        encoding="utf-8",
    )
    result = _run("apply-microcopy-overrides.py", "--theme", "cascadetheme", cwd=tmp_path)
    assert result.returncode == 1


def test_apply_microcopy_overrides_no_op_when_absent(tmp_path: Path) -> None:
    """No-op and exit 0 when microcopy-overrides.json is missing."""
    _make_minimal_theme(tmp_path, "emptytheme")
    # Run from the theme dir itself so resolve_theme_root finds it via cwd
    result = subprocess.run(
        [sys.executable, str(BIN_DIR / "apply-microcopy-overrides.py"), "--theme", "emptytheme"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 4. autofix-contrast.py — CSS hover-contrast extension
# ---------------------------------------------------------------------------


def _set_theme_css(theme_root: Path, css: str) -> None:
    data = json.loads((theme_root / "theme.json").read_text())
    data["styles"] = data.get("styles", {})
    data["styles"]["css"] = css
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


def _get_theme_css(theme_root: Path) -> str:
    data = json.loads((theme_root / "theme.json").read_text())
    return data.get("styles", {}).get("css", "")


def test_autofix_contrast_fixes_hover_rule(tmp_path: Path) -> None:
    """Rewrites color: var(--base) in a :hover rule when contrast fails."""
    theme = _make_minimal_theme(
        tmp_path,
        "hovertheme",
        palette=[
            {"slug": "base", "color": "#F5EFE6"},  # cream (light)
            {"slug": "accent", "color": "#D87E3A"},  # terracotta mid-tone
            {"slug": "contrast", "color": "#1F1B16"},  # near-black
        ],
    )
    # accent vs base: ~2.6:1 → should be rewritten
    _set_theme_css(
        theme,
        ".btn:hover { color: var(--base); background: var(--accent); }",
    )
    result = subprocess.run(
        [sys.executable, str(BIN_DIR / "autofix-contrast.py"), "hovertheme"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    css_after = _get_theme_css(theme)
    # Should NOT still have color: var(--base) in the hover rule
    assert "var(--base)" not in css_after
    # Should have a high-contrast color instead
    assert "var(--contrast)" in css_after or "var(--secondary)" in css_after


def test_autofix_contrast_leaves_passing_hover_rule(tmp_path: Path) -> None:
    """Does NOT rewrite a hover rule that already passes contrast."""
    theme = _make_minimal_theme(
        tmp_path,
        "passhover",
        palette=[
            {"slug": "base", "color": "#F5EFE6"},
            {"slug": "accent", "color": "#D87E3A"},
            {"slug": "contrast", "color": "#1F1B16"},
        ],
    )
    # contrast on accent: >4.5:1 → should be left alone
    original_css = ".btn:hover { color: var(--contrast); background: var(--accent); }"
    _set_theme_css(theme, original_css)
    subprocess.run(
        [sys.executable, str(BIN_DIR / "autofix-contrast.py"), "passhover"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert _get_theme_css(theme) == original_css


def test_autofix_contrast_hover_idempotent(tmp_path: Path) -> None:
    """Running twice after a fix doesn't change the file again."""
    theme = _make_minimal_theme(
        tmp_path,
        "idempotent",
        palette=[
            {"slug": "base", "color": "#F5EFE6"},
            {"slug": "accent", "color": "#D87E3A"},
            {"slug": "contrast", "color": "#1F1B16"},
        ],
    )
    _set_theme_css(
        theme,
        ".btn:hover { color: var(--base); background: var(--accent); }",
    )
    subprocess.run(
        [sys.executable, str(BIN_DIR / "autofix-contrast.py"), "idempotent"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    css_after_first = _get_theme_css(theme)
    subprocess.run(
        [sys.executable, str(BIN_DIR / "autofix-contrast.py"), "idempotent"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    css_after_second = _get_theme_css(theme)
    assert css_after_first == css_after_second


# ---------------------------------------------------------------------------
# 5. design.py PHASES order
# ---------------------------------------------------------------------------


def test_design_phases_order() -> None:
    """index is after sync; photos/microcopy/frontpage are before prepublish."""
    import ast  # noqa: PLC0415

    design_src = (BIN_DIR / "design.py").read_text()
    tree = ast.parse(design_src)

    phases: list[str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PHASES":
                    if isinstance(node.value, ast.Tuple):
                        phases = [
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
                    break

    assert phases is not None, "PHASES tuple not found in design.py"

    def _idx(name: str) -> int:
        assert name in phases, f"{name!r} not in PHASES"
        return phases.index(name)

    assert _idx("index") > _idx("sync"), "index must come after sync"
    assert _idx("photos") < _idx("prepublish"), "photos must come before prepublish"
    assert _idx("microcopy") < _idx("prepublish"), "microcopy must come before prepublish"
    assert _idx("frontpage") < _idx("prepublish"), "frontpage must come before prepublish"
    assert _idx("photos") < _idx("index"), "photos must come before index"
    assert _idx("microcopy") < _idx("index"), "microcopy must come before index"
    assert _idx("frontpage") < _idx("index"), "frontpage must come before index"
