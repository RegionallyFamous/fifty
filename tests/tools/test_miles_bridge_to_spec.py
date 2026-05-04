"""Tests for bin/miles-bridge-to-spec.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_miles_bridge():
    path = ROOT / "bin" / "miles-bridge-to-spec.py"
    spec = importlib.util.spec_from_file_location("miles_bridge_to_spec", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _valid_spec_for_bridge(slug: str, name: str) -> dict:
    bin_dir = str(ROOT / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    from _design_lib import example_spec

    data = dict(example_spec())
    data["slug"] = slug
    data["name"] = name
    return data


def test_miles_bridge_dry_run_writes_spec(tmp_path: Path) -> None:
    mbs = _load_miles_bridge()
    out = tmp_path / "out.json"
    rc = mbs.main(
        [
            "--slug",
            "bridge-test",
            "--name",
            "Bridge Test",
            "--dry-run",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["slug"] == "bridge-test"
    assert data["name"] == "Bridge Test"


def test_miles_bridge_validates_miles_export(tmp_path: Path) -> None:
    mbs = _load_miles_bridge()
    art = tmp_path / "miles-art"
    art.mkdir()
    spec_body = _valid_spec_for_bridge("bakery-miles", "Bakery Miles")
    (art / "spec.json").write_text(
        json.dumps(spec_body, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (art / "miles-ready.json").write_text(
        json.dumps({"site_ready": True, "spec": "spec.json"}),
        encoding="utf-8",
    )
    out = tmp_path / "out-spec.json"
    rc = mbs.main(
        [
            "--slug",
            "bakery-miles",
            "--name",
            "Bakery Miles",
            "--artifacts-dir",
            str(art),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["slug"] == "bakery-miles"
    assert body["name"] == "Bakery Miles"
    assert body["palette"]["accent"] == "#D87E3A"


def test_miles_bridge_requires_miles_ready(tmp_path: Path) -> None:
    mbs = _load_miles_bridge()
    empty = tmp_path / "e"
    empty.mkdir()
    rc = mbs.main(
        [
            "--slug",
            "x",
            "--name",
            "X",
            "--artifacts-dir",
            str(empty),
            "--out",
            str(tmp_path / "o.json"),
        ]
    )
    assert rc == 2


def test_miles_bridge_rejects_site_not_ready(tmp_path: Path) -> None:
    mbs = _load_miles_bridge()
    art = tmp_path / "a"
    art.mkdir()
    (art / "miles-ready.json").write_text(
        json.dumps({"site_ready": False, "spec": "spec.json"}),
        encoding="utf-8",
    )
    (art / "spec.json").write_text(
        json.dumps(_valid_spec_for_bridge("ready-test", "Ready Test")),
        encoding="utf-8",
    )
    rc = mbs.main(
        [
            "--slug",
            "ready-test",
            "--name",
            "Ready Test",
            "--artifacts-dir",
            str(art),
            "--out",
            str(tmp_path / "o.json"),
        ]
    )
    assert rc == 2


def test_miles_bridge_slug_mismatch_fails(tmp_path: Path) -> None:
    mbs = _load_miles_bridge()
    art = tmp_path / "m"
    art.mkdir()
    (art / "spec.json").write_text(
        json.dumps(_valid_spec_for_bridge("spec-slug", "Match Name")),
        encoding="utf-8",
    )
    (art / "miles-ready.json").write_text(
        json.dumps({"site_ready": True, "spec": "spec.json"}),
        encoding="utf-8",
    )
    rc = mbs.main(
        [
            "--slug",
            "cli-slug",
            "--name",
            "Match Name",
            "--artifacts-dir",
            str(art),
            "--out",
            str(tmp_path / "o.json"),
        ]
    )
    assert rc == 2
