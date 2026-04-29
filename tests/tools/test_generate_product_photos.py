from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "generate_product_photos_under_test", BIN_DIR / "generate-product-photos.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_product_photos_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _ahash(path: Path) -> int:
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    with Image.open(path) as im:
        small = im.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
    avg = sum(pixels) / 64.0
    bits = 0
    for i, pixel in enumerate(pixels):
        if pixel >= avg:
            bits |= 1 << i
    return bits


def test_generated_product_cards_are_perceptually_distinct(tmp_path: Path) -> None:
    gp = _load_module()
    palette = {
        "base": "#F5EFE6",
        "surface": "#FFFFFF",
        "accent": "#D87E3A",
        "border": "#C9BBA3",
        "contrast": "#1F1B16",
        "secondary": "#5C5343",
    }
    first = tmp_path / "product-wo-bottled-morning.jpg"
    second = tmp_path / "product-wo-forbidden-honey.jpg"

    gp._make_product_photo("Bottled Morning", "bottled-morning", palette, first)
    gp._make_product_photo("Forbidden Honey", "forbidden-honey", palette, second)

    distance = bin(_ahash(first) ^ _ahash(second)).count("1")
    assert distance > 5


def test_generated_hero_placeholders_are_theme_specific(tmp_path: Path) -> None:
    gp = _load_module()
    palette = {
        "base": "#F5EFE6",
        "surface": "#FFFFFF",
        "accent": "#D8281A",
        "border": "#B8B3AC",
        "contrast": "#0A0A0A",
    }
    first = tmp_path / "agitprop.png"
    second = tmp_path / "chonk.png"

    gp._make_hero_placeholder("About", "wonders-page-about", "agitprop", palette, first)
    gp._make_hero_placeholder("About", "wonders-page-about", "chonk", palette, second)

    assert first.read_bytes() != second.read_bytes()
    distance = bin(_ahash(first) ^ _ahash(second)).count("1")
    assert distance > 2
