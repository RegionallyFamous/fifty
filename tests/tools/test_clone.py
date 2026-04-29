"""Integration test for `bin/clone.py`.

The contract we care about:

1. Cloning a source theme produces a new theme tree at the target path
   whose slug + Title have been rewritten in editable files.
2. Directories in `clone.SKIP_RELPATHS` (e.g. `playground/content`,
   `playground/images`, `styles/claude.json`) are NOT copied through to
   the clone. Historical regression: before SKIP_RELPATHS, every new
   theme inherited ~50 MB of obel's playground fixtures and the
   retired `claude.json` style variation.
3. The clone is a valid starting theme — its `theme.json` + `style.css`
   still parse and still contain the expected WordPress theme header.

We drive the test through `run_bin_script` (real subprocess) so we
exercise the CLI exactly as `bin/clone.py` runs in the wild.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def sample_source(tmp_path: Path, make_theme) -> Path:
    """A mini `obel` fixture with the exact SKIP_RELPATHS populated
    so the test can verify the clone leaves them behind."""
    src = make_theme(slug="obel", title="Obel")
    # Files that must be SKIPPED by the clone:
    (src / "playground" / "content").mkdir(parents=True, exist_ok=True)
    (src / "playground" / "content" / "products.csv").write_text(
        "name,price\nBottled Morning,20\n", encoding="utf-8"
    )
    (src / "playground" / "images").mkdir(parents=True, exist_ok=True)
    (src / "playground" / "images" / "hero.jpg").write_text("fake-binary-image", encoding="utf-8")
    (src / "styles").mkdir(exist_ok=True)
    (src / "styles" / "claude.json").write_text(
        '{"$schema":"x","version":3,"title":"Claude"}\n',
        encoding="utf-8",
    )
    # A non-skipped style variation should come through.
    (src / "styles" / "warm.json").write_text(
        '{"$schema":"x","version":3,"title":"Warm"}\n',
        encoding="utf-8",
    )
    (src / "functions.php").write_text(
        """<?php
add_action( 'woocommerce_account_dashboard', 'obel_render_account_dashboard' );
if ( ! function_exists( 'obel_render_account_dashboard' ) ) {
\tfunction obel_render_account_dashboard(): void {}
}
if ( ! function_exists( 'obel_swatches_color_map' ) ) {
\tfunction obel_swatches_color_map(): array {
\t\treturn array();
\t}
}
""",
        encoding="utf-8",
    )
    # Source's readiness.json is shipping — clone.py must rewrite this
    # to incubating on the destination so new themes don't fraudulently
    # claim shipping status before they've been reviewed + baselined.
    (src / "readiness.json").write_text(
        json.dumps(
            {
                "stage": "shipping",
                "summary": "Obel summary.",
                "owner": "nick",
                "last_checked": "2026-04-26",
                "notes": "Original shipping theme.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return src


def test_clone_creates_new_theme_with_renamed_slug(
    tmp_path: Path,
    sample_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running clone.py --source SRC --target TMP_PARENT new-slug produces a
    new theme whose slug has been rewritten and whose playground/ + claude
    files are absent."""
    import subprocess

    target_parent = tmp_path / "mono"
    target_parent.mkdir()

    # clone.py reads MONOREPO_ROOT via _lib; pass --source + --target to
    # keep the test hermetic.
    cmd = [
        sys.executable,
        str(BIN_DIR / "clone.py"),
        "acme",
        "--source",
        str(sample_source),
        "--target",
        str(target_parent),
    ]
    env = {"PYTHONPATH": f"{BIN_DIR}"}
    result = subprocess.run(
        cmd, capture_output=True, text=True, env={**__import__("os").environ, **env}
    )
    assert result.returncode == 0, (
        f"clone.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    clone = target_parent / "acme"
    assert clone.is_dir(), "clone destination was not created"

    style = (clone / "style.css").read_text(encoding="utf-8")
    assert "Theme Name: Acme" in style, "style.css header was not rewritten (Obel -> Acme)"
    assert "Text Domain: acme" in style
    assert "obel" not in style.lower()

    theme_json = json.loads((clone / "theme.json").read_text(encoding="utf-8"))
    assert theme_json["version"] == 3

    assert (clone / "templates" / "index.html").is_file()
    assert (clone / "parts" / "header.html").is_file()

    # Skipped content must not have come through.
    assert not (clone / "playground" / "content" / "products.csv").exists(), (
        "SKIP_RELPATHS leaked: playground/content/products.csv was copied"
    )
    assert not (clone / "playground" / "images" / "hero.jpg").exists(), (
        "SKIP_RELPATHS leaked: playground/images/hero.jpg was copied"
    )
    assert not (clone / "styles" / "claude.json").exists(), (
        "SKIP_RELPATHS leaked: styles/claude.json was copied"
    )
    # Non-skipped style variation IS copied.
    assert (clone / "styles" / "warm.json").is_file()


def test_clone_renames_non_obel_source_theme(
    tmp_path: Path,
    make_theme,
) -> None:
    """`--source chonk` must not leave Chonk branding in the clone."""
    import os
    import subprocess

    src = make_theme(slug="chonk", title="Chonk")
    (src / "functions.php").write_text(
        """<?php
/**
 * Chonk theme bootstrap.
 */
add_action( 'init', 'chonk_boot' );
function chonk_boot(): void {}
""",
        encoding="utf-8",
    )

    target_parent = tmp_path / "mono"
    target_parent.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(BIN_DIR / "clone.py"),
            "agitprop",
            "--source",
            str(src),
            "--target",
            str(target_parent),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
    )
    assert result.returncode == 0, (
        f"clone.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    clone = target_parent / "agitprop"
    style = (clone / "style.css").read_text(encoding="utf-8")
    functions = (clone / "functions.php").read_text(encoding="utf-8")

    assert "Theme Name: Agitprop" in style
    assert "Text Domain: agitprop" in style
    assert "Agitprop theme bootstrap" in functions
    assert "agitprop_boot" in functions
    assert "chonk" not in (style + functions).lower()


def test_clone_keeps_hyphenated_slug_but_sanitizes_php_identifiers(
    tmp_path: Path,
    sample_source: Path,
) -> None:
    """Hyphenated slugs are valid theme slugs but invalid PHP identifiers."""
    import os
    import subprocess

    target_parent = tmp_path / "mono"
    target_parent.mkdir()

    cmd = [
        sys.executable,
        str(BIN_DIR / "clone.py"),
        "midcentury-emporium",
        "--source",
        str(sample_source),
        "--target",
        str(target_parent),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
    )
    assert result.returncode == 0, (
        f"clone.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    clone = target_parent / "midcentury-emporium"
    style = (clone / "style.css").read_text(encoding="utf-8")
    functions = (clone / "functions.php").read_text(encoding="utf-8")

    assert "Text Domain: midcentury-emporium" in style
    assert "midcentury_emporium_render_account_dashboard" in functions
    assert "midcentury_emporium_swatches_color_map" in functions
    assert "midcentury-emporium_render_account_dashboard" not in functions


def test_clone_writes_incubating_readiness(
    tmp_path: Path,
    sample_source: Path,
) -> None:
    """A freshly-cloned theme MUST land at ``stage: "incubating"``.

    Without this, clone.py byte-for-byte inherits the source theme's
    ``readiness.json`` — which always says ``stage: "shipping"`` on
    the six originals — and ``check_visual_baseline_present`` then
    fails on the new theme with "no baselines" because shipping
    themes are required to have a visual-baseline tree. The fix is
    to scope baseline requirements to shipping themes AND to land
    new themes at incubating; the ``.github/workflows/first-baseline.yml``
    workflow auto-promotes them to shipping after baselines are
    generated.

    This test pins the clone-side half of the contract.
    """
    import os
    import subprocess

    target_parent = tmp_path / "mono"
    target_parent.mkdir()

    cmd = [
        sys.executable,
        str(BIN_DIR / "clone.py"),
        "acme",
        "--source",
        str(sample_source),
        "--target",
        str(target_parent),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
    )
    assert result.returncode == 0, (
        f"clone.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    readiness_path = target_parent / "acme" / "readiness.json"
    assert readiness_path.is_file(), "clone did not produce a readiness.json on the new theme"
    payload = json.loads(readiness_path.read_text())
    assert payload["stage"] == "incubating", (
        f"freshly-cloned theme must start at stage=incubating; got "
        f"{payload['stage']!r}. Fix: bin/clone.py must overwrite the "
        "source readiness.json rather than byte-copy it."
    )
    # The summary/notes should mention the new slug AND indicate WIP
    # state, so a human reading the file knows it's a scaffold.
    assert "Acme" in payload["summary"]
    assert "WIP" in payload["summary"] or "wip" in payload["summary"].lower()


def test_clone_refuses_invalid_slug(sample_source: Path, tmp_path: Path) -> None:
    """clone.py's `slug_validate` rejects slugs that start with a digit,
    contain uppercase, or contain underscores."""
    import os
    import subprocess

    target_parent = tmp_path / "mono"
    target_parent.mkdir()

    # clone.py lowercases the slug before validating, so "Mixed-Case"
    # is NOT rejected. The genuinely-invalid cases are: starts-with-digit,
    # contains underscore, contains a space, or is longer than 39 chars.
    for bad in ("9bad", "bad_name", "bad name", "x" * 40):
        cmd = [
            sys.executable,
            str(BIN_DIR / "clone.py"),
            bad,
            "--source",
            str(sample_source),
            "--target",
            str(target_parent),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
        )
        assert result.returncode != 0, f"clone.py should have rejected slug '{bad}', got rc=0"
        assert "not a valid theme slug" in (result.stdout + result.stderr), (
            f"expected slug-validation error for '{bad}', "
            f"got stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def test_clone_refuses_existing_destination(sample_source: Path, tmp_path: Path) -> None:
    """Clone must NOT overwrite an existing target directory."""
    import os
    import subprocess

    target_parent = tmp_path / "mono"
    target_parent.mkdir()
    (target_parent / "conflict").mkdir()
    (target_parent / "conflict" / "keep.txt").write_text("keep", encoding="utf-8")

    cmd = [
        sys.executable,
        str(BIN_DIR / "clone.py"),
        "conflict",
        "--source",
        str(sample_source),
        "--target",
        str(target_parent),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BIN_DIR)},
    )
    assert result.returncode != 0
    assert (target_parent / "conflict" / "keep.txt").read_text() == "keep", (
        "clone.py overwrote an existing destination directory"
    )
