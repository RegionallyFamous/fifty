"""Tests for `bin/promote-theme.py`.

`promote-theme.py` is the formal incubating -> shipping gate. The
contract we care about:

1. The script can be imported as a module (no syntax errors).
2. The CLI registers `--check-only`, `--force`, `--no-strict-branch`,
   `--no-verify`, `--no-publish`, `--remote`, `--demote`, and `--reason` flags.
3. The internal gate functions correctly identify when a theme is
   missing readiness, design-intent, or playground content.
4. The promotion flips `readiness.json` stage from `incubating` to
   `shipping` when every gate passes.
5. The demotion flips `readiness.json` stage from `shipping` to
   `incubating` and records the reason.

We drive the gate functions directly with synthetic theme trees
rather than through the CLI so the tests stay fast and don't shell
out to `bin/verify-theme.py` (which requires Playwright + a running
Playground server).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"
SCRIPT_PATH = BIN_DIR / "promote-theme.py"


@pytest.fixture
def promote_module():
    """Load `bin/promote-theme.py` as a module so the gate helpers
    are importable without running the CLI."""
    spec = importlib.util.spec_from_file_location("promote_theme", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["promote_theme"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def incubating_theme(tmp_path: Path) -> Path:
    """Build a synthetic theme tree shaped like a freshly-cloned
    `incubating` theme: readiness.json + design-intent.md + a
    playground/blueprint.json + seeded content + a product image."""
    theme = tmp_path / "demo"
    theme.mkdir()
    (theme / "theme.json").write_text(
        json.dumps({"$schema": "x", "version": 3, "title": "Demo"}),
        encoding="utf-8",
    )
    (theme / "readiness.json").write_text(
        json.dumps(
            {
                "stage": "incubating",
                "summary": "Demo theme for promote-theme.py tests.",
                "owner": "test",
                "last_checked": "",
                "notes": "",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (theme / "design-intent.md").write_text(
        "# Demo design intent\n\n" + ("Voice / Palette / Typography / Required / Forbidden. " * 10),
        encoding="utf-8",
    )
    pg_content = theme / "playground" / "content"
    pg_images = theme / "playground" / "images"
    pg_content.mkdir(parents=True)
    pg_images.mkdir(parents=True)
    (theme / "playground" / "blueprint.json").write_text('{"steps": []}', encoding="utf-8")
    (pg_content / "content.xml").write_text("<?xml version='1.0'?><rss/>", encoding="utf-8")
    (pg_content / "products.csv").write_text("sku,name\n", encoding="utf-8")
    return theme


def test_module_imports(promote_module):
    assert hasattr(promote_module, "main")
    assert hasattr(promote_module, "cmd_promote")
    assert hasattr(promote_module, "cmd_demote")


def test_cli_help_lists_required_flags():
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    out = proc.stdout
    for flag in (
        "--check-only",
        "--force",
        "--no-strict-branch",
        "--no-verify",
        "--no-publish",
        "--remote",
        "--demote",
        "--reason",
    ):
        assert flag in out, f"missing CLI flag: {flag}"


def test_gate_readiness_missing(promote_module, tmp_path: Path):
    theme = tmp_path / "noreadiness"
    theme.mkdir()
    (theme / "theme.json").write_text("{}", encoding="utf-8")
    result = promote_module._gate_readiness_present(theme)
    assert result.passed is False
    assert "readiness.json" in result.detail


def test_gate_readiness_present(promote_module, incubating_theme: Path):
    result = promote_module._gate_readiness_present(incubating_theme)
    assert result.passed is True


def test_gate_design_intent_missing(promote_module, tmp_path: Path):
    theme = tmp_path / "intentless"
    theme.mkdir()
    (theme / "theme.json").write_text("{}", encoding="utf-8")
    result = promote_module._gate_design_intent(theme)
    assert result.passed is False
    assert "design-intent.md" in result.detail


def test_gate_design_intent_too_short(promote_module, tmp_path: Path):
    theme = tmp_path / "stub"
    theme.mkdir()
    (theme / "design-intent.md").write_text("# Stub\n", encoding="utf-8")
    result = promote_module._gate_design_intent(theme)
    assert result.passed is False
    assert "placeholder" in result.detail or "shorter" in result.detail


def test_gate_design_intent_passes(promote_module, incubating_theme: Path):
    result = promote_module._gate_design_intent(incubating_theme)
    assert result.passed is True


def test_gate_playground_skipped_without_blueprint(promote_module, tmp_path: Path):
    theme = tmp_path / "noblueprint"
    theme.mkdir()
    (theme / "theme.json").write_text("{}", encoding="utf-8")
    result = promote_module._gate_playground_seeded(theme)
    assert result.passed is True


def test_gate_playground_missing_content_fails(promote_module, tmp_path: Path):
    theme = tmp_path / "blueprintonly"
    theme.mkdir()
    (theme / "playground").mkdir()
    (theme / "playground" / "blueprint.json").write_text("{}", encoding="utf-8")
    result = promote_module._gate_playground_seeded(theme)
    assert result.passed is False
    assert "missing" in result.detail


def test_gate_playground_passes_when_seeded(promote_module, incubating_theme: Path):
    (incubating_theme / "playground" / "images" / "hero.jpg").write_text("x", encoding="utf-8")
    result = promote_module._gate_playground_seeded(incubating_theme)
    assert result.passed is True


def test_gate_product_images_map_required_when_photos_present(
    promote_module, incubating_theme: Path
):
    (incubating_theme / "playground" / "images" / "product-wo-mug.jpg").write_text(
        "x", encoding="utf-8"
    )
    result = promote_module._gate_product_images_map(incubating_theme)
    assert result.passed is False
    assert "product-images.json" in result.detail


def test_gate_check_py_passes_always_runs_static_gate(
    promote_module, monkeypatch, incubating_theme: Path
):
    """The `bin/check.py` static gate runs even when `--no-verify` is
    passed — it's the fast floor that keeps a freshly-cloned theme
    with obvious static failures from being promoted via an escape
    hatch flag combination.
    """
    called: dict[str, list] = {"args": []}

    class FakeProc:
        returncode = 1
        stdout = "  [FAIL] Front page layout differs from every other theme\n"
        stderr = ""

    def fake_run(args, **_):
        called["args"].append(args)
        return FakeProc()

    monkeypatch.setattr(promote_module.subprocess, "run", fake_run)
    result = promote_module._gate_check_py_passes(incubating_theme)
    assert result.passed is False
    assert "Front page layout" in result.detail
    assert any("bin/check.py" in a for a in called["args"][0])


def test_gate_check_py_passes_on_clean_run(promote_module, monkeypatch, incubating_theme: Path):
    class FakeProc:
        returncode = 0
        stdout = "  [PASS] everything\n"
        stderr = ""

    monkeypatch.setattr(promote_module.subprocess, "run", lambda *a, **kw: FakeProc())
    result = promote_module._gate_check_py_passes(incubating_theme)
    assert result.passed is True


def test_gate_product_images_map_passes(promote_module, incubating_theme: Path):
    (incubating_theme / "playground" / "images" / "product-wo-mug.jpg").write_text(
        "x", encoding="utf-8"
    )
    (incubating_theme / "playground" / "content" / "product-images.json").write_text(
        json.dumps({"WO-MUG": "product-wo-mug.jpg"}),
        encoding="utf-8",
    )
    result = promote_module._gate_product_images_map(incubating_theme)
    assert result.passed is True


def test_gate_gpt_image_photos_requires_openai_manifest(promote_module, incubating_theme: Path):
    (incubating_theme / "playground" / "content" / "product-images.json").write_text(
        json.dumps({"WO-MUG": "product-wo-mug.jpg"}),
        encoding="utf-8",
    )
    (incubating_theme / "playground" / "images" / "product-wo-mug.jpg").write_text(
        "x", encoding="utf-8"
    )

    result = promote_module._gate_gpt_image_photos(incubating_theme)

    assert result.passed is False
    assert "product-photo-prompts.json" in result.detail


def test_gate_gpt_image_photos_rejects_fallback_provider(promote_module, incubating_theme: Path):
    content = incubating_theme / "playground" / "content"
    (content / "product-images.json").write_text(
        json.dumps({"WO-MUG": "product-wo-mug.jpg"}),
        encoding="utf-8",
    )
    (content / "product-photo-prompts.json").write_text(
        json.dumps(
            {
                "status": "generated",
                "provider": "pillow",
                "model": "generate-product-photos.py",
                "records": [{"sku": "WO-MUG", "status": "generated"}],
            }
        ),
        encoding="utf-8",
    )

    result = promote_module._gate_gpt_image_photos(incubating_theme)

    assert result.passed is False
    assert "gpt-image-2" in result.detail


def test_gate_gpt_image_photos_passes_for_complete_openai_manifest(
    promote_module, incubating_theme: Path
):
    content = incubating_theme / "playground" / "content"
    images = incubating_theme / "playground" / "images"
    (content / "product-images.json").write_text(
        json.dumps({"WO-MUG": "product-wo-mug.jpg"}),
        encoding="utf-8",
    )
    (images / "product-wo-mug.jpg").write_text("x", encoding="utf-8")
    (content / "product-photo-prompts.json").write_text(
        json.dumps(
            {
                "status": "generated",
                "provider": "openai",
                "model": "gpt-image-2",
                "records": [{"sku": "WO-MUG", "status": "generated"}],
            }
        ),
        encoding="utf-8",
    )

    result = promote_module._gate_gpt_image_photos(incubating_theme)

    assert result.passed is True
    assert "OpenAI/gpt-image-2" in result.detail


def test_write_readiness_promotes_and_records_note(promote_module, incubating_theme: Path):
    from _readiness import load_readiness

    readiness = load_readiness(incubating_theme)
    promote_module._write_readiness(
        incubating_theme,
        readiness,
        stage="shipping",
        note="Promoted by test",
    )
    refreshed = load_readiness(incubating_theme)
    assert refreshed.stage == "shipping"
    assert "Promoted by test" in refreshed.notes
    assert refreshed.last_checked  # YYYY-MM-DD stamped


def test_demote_requires_reason(promote_module, incubating_theme: Path):
    rc = promote_module.cmd_demote(str(incubating_theme), reason="")
    assert rc == 2


def test_demote_flips_to_incubating(promote_module, incubating_theme: Path):
    from _readiness import load_readiness, manifest_path

    manifest_path(incubating_theme).write_text(
        json.dumps({"stage": "shipping", "summary": "demo"}),
        encoding="utf-8",
    )

    import _lib

    real_resolve = _lib.resolve_theme_root

    def fake_resolve(slug: str) -> Path:
        if slug == incubating_theme.name:
            return incubating_theme
        return real_resolve(slug)

    promote_module.resolve_theme_root = fake_resolve
    try:
        rc = promote_module.cmd_demote(
            incubating_theme.name, reason="regressed gate after stricter rule"
        )
    finally:
        promote_module.resolve_theme_root = real_resolve
    assert rc == 0
    assert load_readiness(incubating_theme).stage == "incubating"
    assert "regressed gate" in load_readiness(incubating_theme).notes
