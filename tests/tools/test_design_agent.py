from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

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
    assert "DESIGN AGENT FRONTPAGE PROMPT" in out
    assert "front-page.html" in out
    assert "Full-bleed dark photo hero" in out


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
