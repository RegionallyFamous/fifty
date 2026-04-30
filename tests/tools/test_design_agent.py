from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "design_agent_under_test", BIN_DIR / "design-agent.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["design_agent_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _minimal_theme(tmp_path: Path) -> Path:
    theme = tmp_path / "agentic"
    (theme / "templates").mkdir(parents=True)
    (theme / "playground" / "content").mkdir(parents=True)
    (theme / "templates" / "front-page.html").write_text(
        """<!-- wp:group {"tagName":"main"} -->
<main class="wp-block-group">
<!-- wp:paragraph -->
<p>Original hero</p>
<!-- /wp:paragraph -->
</main>
<!-- /wp:group -->
""",
        encoding="utf-8",
    )
    (theme / "theme.json").write_text(
        json.dumps(
            {
                "settings": {
                    "color": {
                        "palette": [
                            {"slug": "base", "color": "#111111"},
                            {"slug": "contrast", "color": "#eeeeee"},
                            {"slug": "accent", "color": "#c8102e"},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (theme / "BRIEF.md").write_text(
        """# Agentic

## Voice

Clipped noir shopkeeper.

## Layout hints

- Full-bleed dark photo hero
- Centered scarlet CTA
""",
        encoding="utf-8",
    )
    (theme / "playground" / "content" / "product-images.json").write_text(
        json.dumps({"WO-SAMPLE": "product-wo-sample.jpg"}),
        encoding="utf-8",
    )
    return theme


def test_frontpage_dry_run_emits_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    da = _load_module()
    theme = _minimal_theme(tmp_path)
    monkeypatch.setattr(da, "resolve_theme_root", lambda slug: theme)

    rc = da.main(["--theme", "agentic", "--task", "frontpage", "--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "DESIGN AGENT FRONTPAGE CLASSIFIER" in out
    assert "available_layouts" in out
    assert "photo-hero-product-grid" in out


def test_photos_dry_run_emits_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    da = _load_module()
    theme = _minimal_theme(tmp_path)
    monkeypatch.setattr(da, "resolve_theme_root", lambda slug: theme)

    rc = da.main(["--theme", "agentic", "--task", "photos", "--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "DESIGN AGENT PHOTOS PROMPT" in out
    assert "WO-SAMPLE" in out
    assert "product-wo-sample.jpg" in out


def test_layout_manifest_loads_all_skeletons() -> None:
    da = _load_module()

    layouts = da._load_layout_manifest()

    assert set(layouts) == {
        "photo-hero-product-grid",
        "centered-masthead-editorial-grid",
        "poster-cta-commerce-stack",
        "split-hero-category-strip",
        "magazine-index-commerce",
    }
    for layout in layouts.values():
        assert layout["slots"]
        assert layout["required_blocks"]
        assert layout["trait_tags"]["hero"]


def test_rendered_skeletons_have_balanced_block_comments(tmp_path: Path) -> None:
    da = _load_module()
    context = {"name": "Agentic", "tagline": "A precise shop counter."}

    for layout_id in da._layout_ids():
        choice = da.LayoutChoice(
            layout_id=layout_id,
            confidence=0.9,
            rationale="test",
            evidence_quality="mockup",
            slot_copy=da._default_slot_copy("agentic", context),
            style_directives=[],
            source="test",
        )
        html = da._render_layout("agentic", choice)
        assert da._block_comment_balance_ok(html), layout_id
        assert "wo-layout-agentic" in html


def test_rendered_skeletons_validate_when_validator_dependencies_exist(tmp_path: Path) -> None:
    da = _load_module()
    if shutil.which("node") is None or not (BIN_DIR / "blocks-validator" / "node_modules").is_dir():
        pytest.skip("block validator dependencies are not installed")

    theme = _minimal_theme(tmp_path)
    (theme / "parts").mkdir()
    (theme / "parts" / "header.html").write_text("<!-- wp:site-title /-->", encoding="utf-8")
    (theme / "parts" / "footer.html").write_text("<!-- wp:site-title /-->", encoding="utf-8")
    context = {"name": "Agentic", "tagline": "A precise shop counter."}
    for layout_id in da._layout_ids():
        choice = da.LayoutChoice(
            layout_id=layout_id,
            confidence=0.9,
            rationale="test",
            evidence_quality="mockup",
            slot_copy=da._default_slot_copy("agentic", context),
            style_directives=[],
            source="test",
        )
        (theme / "templates" / "front-page.html").write_text(
            da._render_layout("agentic", choice),
            encoding="utf-8",
        )
        result = da._run_block_validator(theme)
        assert result.ok, f"{layout_id}: {result.detail}"


def test_classifier_parser_rejects_invalid_layout_id() -> None:
    da = _load_module()
    layouts = da._load_layout_manifest()

    with pytest.raises(ValueError, match="invalid layout_id"):
        da._parse_layout_choice(
            {"layout_id": "made-up", "confidence": 0.8},
            slug="agentic",
            context={},
            layouts=layouts,
            evidence_quality="mockup",
            source="test",
        )


def test_invalid_template_candidate_does_not_replace_source(tmp_path: Path) -> None:
    da = _load_module()
    theme = _minimal_theme(tmp_path)
    original = (theme / "templates" / "front-page.html").read_text(encoding="utf-8")

    result = da._write_candidate_if_valid(theme, "<!-- wp:group --><div>")

    assert not result.ok
    assert (theme / "templates" / "front-page.html").read_text(encoding="utf-8") == original


def test_missing_mockup_strict_fails_and_writes_repair(monkeypatch, tmp_path: Path) -> None:
    da = _load_module()
    theme = _minimal_theme(tmp_path)
    monkeypatch.setattr(da, "_agent_dir", lambda slug: tmp_path / "agent-output")

    rc = da.run_frontpage(
        theme,
        dry_run=False,
        max_rounds=1,
        model="test",
        keep_going=False,
        score_threshold=70,
    )

    assert rc == 1
    repair = tmp_path / "agent-output" / "repair.json"
    assert repair.is_file()
    data = json.loads(repair.read_text(encoding="utf-8"))
    assert data["problems"][0]["problem"] == "missing-mockup"


def test_missing_mockup_keep_going_renders_with_repair_packet(monkeypatch, tmp_path: Path) -> None:
    da = _load_module()
    theme = _minimal_theme(tmp_path)
    monkeypatch.setattr(da, "_agent_dir", lambda slug: tmp_path / "agent-output")
    monkeypatch.setattr(
        da,
        "_write_candidate_if_valid",
        lambda theme_root, candidate: da.ValidationResult(True, "ok"),
    )
    monkeypatch.setattr(
        da,
        "_run_frontpage_evidence",
        lambda slug, keep_going, threshold: (
            {"snapshots": [], "scorecard": None, "status": "skipped"},
            [],
            True,
        ),
    )

    rc = da.run_frontpage(
        theme,
        dry_run=False,
        max_rounds=1,
        model="test",
        keep_going=True,
        score_threshold=70,
    )

    assert rc == 0
    repair = tmp_path / "agent-output" / "repair.json"
    result = tmp_path / "agent-output" / "frontpage-result.json"
    assert repair.is_file()
    assert result.is_file()
    assert json.loads(result.read_text(encoding="utf-8"))["selected_skeleton"]


def test_photos_without_image_key_marks_placeholder_fallback(monkeypatch, tmp_path: Path) -> None:
    da = _load_module()
    theme = _minimal_theme(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(da, "_agent_dir", lambda slug: tmp_path / "agent-output")
    monkeypatch.setattr(
        da,
        "_completion",
        lambda **kwargs: json.dumps({"prompts": {"WO-SAMPLE": "square product photo"}}),
    )
    monkeypatch.setattr(da, "_fallback_photos", lambda slug, force=False: 0)

    rc = da.run_photos(theme, dry_run=False, model="test", keep_going=True)

    manifest = json.loads(
        (theme / "playground" / "content" / "product-photo-prompts.json").read_text(
            encoding="utf-8"
        )
    )
    assert rc == 0
    assert manifest["status"] == "placeholder-fallback"
    assert manifest["provider"] == "pillow"


def test_openai_and_fal_outputs_normalize_to_jpeg(tmp_path: Path) -> None:
    da = _load_module()
    pillow = pytest.importorskip("PIL.Image")
    source = tmp_path / "source.png"
    image = pillow.new("RGBA", (8, 8), (255, 0, 0, 128))
    image.save(source)

    dest = tmp_path / "out.jpg"
    da._write_image_bytes(dest, source.read_bytes())

    assert dest.read_bytes()[:3] == b"\xff\xd8\xff"


def test_openai_generation_uses_gpt_image_2(monkeypatch) -> None:
    da = _load_module()
    seen: dict[str, dict[str, object]] = {}

    def fake_request_json(url, headers, payload):
        seen["url"] = url
        seen["payload"] = payload
        return {"data": [{"b64_json": "ZmFrZQ=="}]}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(da, "_request_json", fake_request_json)

    raw = da._generate_openai("square product photo")

    assert raw == b"fake"
    assert seen["payload"]["model"] == "gpt-image-2"
