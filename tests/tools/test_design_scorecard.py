from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_design_scorecard_for_test", BIN_DIR / "design-scorecard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_design_scorecard_for_test"] = module
    spec.loader.exec_module(module)
    return module


def test_score_findings_maps_vision_to_taste_categories() -> None:
    m = _load_module()
    scores, weak = m._score_findings(
        [
            {
                "kind": "vision:photography-mismatch",
                "severity": "warn",
                "route": "shop",
                "viewport": "desktop",
                "message": "catalogue photos fight the rubric",
            },
            {
                "kind": "button-label-overflow",
                "severity": "error",
                "route": "cart-filled",
                "viewport": "mobile",
                "message": "button text spills",
            },
        ]
    )

    assert scores["product_photography_fit"] < 100
    assert scores["cta_clarity"] < 100
    assert {item.category for item in weak} == {"product_photography_fit", "cta_clarity"}


def test_build_scorecard_writes_contact_sheet(tmp_path, monkeypatch) -> None:
    m = _load_module()
    theme = "example"
    root = tmp_path
    (root / theme).mkdir()
    (root / theme / "theme.json").write_text("{}", encoding="utf-8")
    snap_dir = root / "tmp" / "snaps" / theme / "desktop"
    snap_dir.mkdir(parents=True)
    (snap_dir / "shop.png").write_bytes(b"png")
    (snap_dir / "shop.findings.json").write_text(
        json.dumps(
            {
                "route": "shop",
                "viewport": "desktop",
                "findings": [
                    {
                        "kind": "vision:hierarchy-flat",
                        "severity": "error",
                        "message": "nothing leads the eye",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(m, "MONOREPO_ROOT", root)
    monkeypatch.setattr(m, "resolve_theme_root", lambda slug: root / slug)

    scorecard = m.build_scorecard(theme, "proof", threshold=70)

    assert scorecard.verdict == "pass"
    assert scorecard.scores["hierarchy"] == 82
    assert scorecard.contact_sheet == "tmp/runs/proof/contact-sheet.md"
    assert (root / scorecard.contact_sheet).is_file()


def test_mass_failure_classification_groups_top_findings() -> None:
    m = _load_module()
    findings = [
        {
            "kind": "vision:brand-violation",
            "severity": "error",
            "route": "home",
            "viewport": "desktop",
            "message": "generic storefront chrome",
        }
        for _ in range(6)
    ]

    scores, weak = m._score_findings(findings)
    groups = m._top_weak_findings(weak)

    assert m._is_mass_failure(scores, weak)
    assert groups[0].category == "visual_distinctness"
    assert groups[0].kind == "vision:brand-violation"
    assert groups[0].count == 6


def test_no_fail_prints_warning_and_exits_zero(tmp_path, monkeypatch, capsys) -> None:
    m = _load_module()
    theme = "example"
    root = tmp_path
    (root / theme).mkdir()
    (root / theme / "theme.json").write_text("{}", encoding="utf-8")
    snap_dir = root / "tmp" / "snaps" / theme / "desktop"
    snap_dir.mkdir(parents=True)
    (snap_dir / "home.png").write_bytes(b"png")
    (snap_dir / "home.findings.json").write_text(
        json.dumps(
            {
                "route": "home",
                "viewport": "desktop",
                "findings": [
                    {
                        "kind": "vision:brand-violation",
                        "severity": "error",
                        "message": "generic storefront chrome",
                    }
                    for _ in range(6)
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(m, "MONOREPO_ROOT", root)
    monkeypatch.setattr(m, "resolve_theme_root", lambda slug: root / slug)

    rc = m.main([theme, "--run-id", "proof", "--no-fail"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "[WARN] [scorecard] Scorecard mass failure" in out
    assert "[FAIL] [scorecard]" not in out
    assert (root / "tmp" / "runs" / "proof" / "design-score.json").is_file()
