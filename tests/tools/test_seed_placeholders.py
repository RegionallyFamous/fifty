"""Behavioural tests for the two "fresh-clone friction" fixes shipped in the
`build` smoke: photograph placeholder seeding (`bin/seed-playground-content.py`)
and heuristics-allowlist cloning (`bin/design.py::_seed_allowlist_from_source`).

Background
----------
A freshly-scaffolded theme cloned from obel used to exit
`design.py build` at `check --phase structural` for two orthogonal reasons:

1.  `obel/patterns/hero-split.php` hardcodes
    `product-wo-bottled-morning.jpg` in the hero markup. When cloned, the
    new theme inherits that reference but its `playground/images/` folder
    holds only upstream `wonders-*.png` cartoons — so the page renders
    with a broken image, `snap.py`'s `broken-image` heuristic fires
    (0 cells allowlisted), and the gate blocks. The cure is to copy obel's
    `product-wo-*.jpg` photographs into the new theme's images folder as
    placeholders; `dress` later regenerates them with theme-specific
    photography.
2.  Shipping themes grandfather several known-tolerated heuristic findings
    (`narrow-wc-block` on `.wc-block-cart-items` at desktop/wide, etc.)
    via `tests/visual-baseline/heuristics-allowlist.json`. The new theme
    inherits the SAME markup (same templates, same CSS) but none of the
    allowlist entries, so the same findings re-fire as NEW errors against
    a theme the operator never touched. The cure is to duplicate the
    source theme's entries under the new slug in `apply`.

Both fixes must be strictly idempotent and must never clobber a theme's
own files / entries. These tests nail down those invariants.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import design  # noqa: E402

# `bin/seed-playground-content.py` has a hyphen in its module name, so we
# can't write `import seed_playground_content` — importlib is the escape
# hatch the rest of the bin/-side helpers use to reach it.
seed_module = importlib.import_module("seed-playground-content")


# ---------------------------------------------------------------------------
# copy_photo_placeholders
# ---------------------------------------------------------------------------


def _fake_theme_tree(root: Path, slug: str, product_wo: dict[str, bytes]) -> Path:
    """Create `<root>/<slug>/playground/images/` and populate it with the
    given product-wo JPG filenames mapped to their byte contents. Used
    to simulate a source theme with real photography and a target theme
    without it."""
    imgs = root / slug / "playground" / "images"
    imgs.mkdir(parents=True, exist_ok=True)
    for name, data in product_wo.items():
        (imgs / name).write_bytes(data)
    return imgs


def test_copy_photo_placeholders_copies_missing_jpgs(tmp_path, monkeypatch):
    """The happy path: target theme has zero product-wo JPGs; source has
    three; all three get copied."""
    monkeypatch.setattr(seed_module, "MONOREPO_ROOT", tmp_path)

    _fake_theme_tree(
        tmp_path,
        "obel",
        {
            "product-wo-bottled-morning.jpg": b"obel-bottled-bytes",
            "product-wo-left-sock.jpg": b"obel-sock-bytes",
            "product-wo-moon-dust.jpg": b"obel-moon-bytes",
        },
    )
    target_images = tmp_path / "target" / "playground" / "images"

    copied, skipped = seed_module.copy_photo_placeholders("obel", "target", target_images)

    assert (copied, skipped) == (3, 0)
    assert (target_images / "product-wo-bottled-morning.jpg").read_bytes() == b"obel-bottled-bytes"
    assert (target_images / "product-wo-left-sock.jpg").exists()
    assert (target_images / "product-wo-moon-dust.jpg").exists()


def test_copy_photo_placeholders_never_clobbers_existing(tmp_path, monkeypatch):
    """Target already has its own `product-wo-bottled-morning.jpg` — we
    must NEVER overwrite it. This is the primary idempotence guarantee
    shipping themes rely on: a shipped theme with its own real
    photography survives a seeder re-run byte-identical."""
    monkeypatch.setattr(seed_module, "MONOREPO_ROOT", tmp_path)

    _fake_theme_tree(
        tmp_path,
        "obel",
        {"product-wo-bottled-morning.jpg": b"obel-bottled-bytes"},
    )
    target_images = _fake_theme_tree(
        tmp_path,
        "target",
        {"product-wo-bottled-morning.jpg": b"target-OWN-bytes"},
    )

    copied, skipped = seed_module.copy_photo_placeholders("obel", "target", target_images)

    assert (copied, skipped) == (0, 1)
    assert (target_images / "product-wo-bottled-morning.jpg").read_bytes() == b"target-OWN-bytes"


def test_copy_photo_placeholders_self_source_is_noop(tmp_path, monkeypatch):
    """Seeding obel from obel is a no-op — the guard prevents a subtle
    'copy into the same folder' footgun if the source and target slugs
    ever collide."""
    monkeypatch.setattr(seed_module, "MONOREPO_ROOT", tmp_path)

    obel_images = _fake_theme_tree(tmp_path, "obel", {"product-wo-x.jpg": b"obel-x"})

    copied, skipped = seed_module.copy_photo_placeholders("obel", "obel", obel_images)

    assert (copied, skipped) == (0, 0)


def test_copy_photo_placeholders_ignores_non_product_wo_files(tmp_path, monkeypatch):
    """The seeder only copies product-wo-<slug>.jpg — never wonders-*.png
    cartoons (they're seeded separately from the upstream repo), never
    category covers, never page/post hero images (which live under
    different filename prefixes). A broader filter would conflict with
    the existing `copy_asset_files` cleanup pass."""
    monkeypatch.setattr(seed_module, "MONOREPO_ROOT", tmp_path)

    _fake_theme_tree(
        tmp_path,
        "obel",
        {
            "product-wo-bottled-morning.jpg": b"copy-me",
            "wonders-bottled-morning.png": b"DO-NOT-COPY",
            "cat-tools.jpg": b"DO-NOT-COPY",
            "product-wo-left-sock.png": b"DO-NOT-COPY",  # wrong extension
        },
    )
    target_images = tmp_path / "target" / "playground" / "images"

    copied, skipped = seed_module.copy_photo_placeholders("obel", "target", target_images)

    assert copied == 1
    assert (target_images / "product-wo-bottled-morning.jpg").exists()
    assert not (target_images / "wonders-bottled-morning.png").exists()
    assert not (target_images / "cat-tools.jpg").exists()
    assert not (target_images / "product-wo-left-sock.png").exists()


def test_copy_photo_placeholders_missing_source_is_graceful(tmp_path, monkeypatch):
    """If the source theme doesn't exist (or hasn't been seeded yet),
    the helper returns (0, 0) rather than crashing. This matters for
    the very first run of `design.py build` against a fresh checkout
    where obel itself may not have been photographed yet."""
    monkeypatch.setattr(seed_module, "MONOREPO_ROOT", tmp_path)

    target_images = tmp_path / "target" / "playground" / "images"

    copied, skipped = seed_module.copy_photo_placeholders("nonexistent", "target", target_images)

    assert (copied, skipped) == (0, 0)


# ---------------------------------------------------------------------------
# _seed_allowlist_from_source
# ---------------------------------------------------------------------------


@pytest.fixture
def allowlist_sandbox(tmp_path, monkeypatch):
    """Point `design._seed_allowlist_from_source` at a sandbox allowlist
    file and return (path, writer). The writer lets each test dictate
    the on-disk JSON shape for the scenario it's nailing down."""
    allow_path = tmp_path / "tests" / "visual-baseline" / "heuristics-allowlist.json"
    allow_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(design, "MONOREPO_ROOT", tmp_path)

    def write(payload: dict) -> None:
        allow_path.write_text(
            json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )

    return allow_path, write


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_seed_allowlist_duplicates_source_cells_under_target(allowlist_sandbox):
    """Every `obel:<viewport>:<route>` cell gets cloned under
    `target:<viewport>:<route>` with byte-identical contents."""
    path, write = allowlist_sandbox
    write(
        {
            "obel:desktop:cart-filled": {"narrow-wc-block": [".wc-block-cart-items"]},
            "obel:wide:my-account": {"narrow-wc-block": [".wo-account-login-grid"]},
            "chonk:desktop:checkout-filled": {"a11y-color-contrast": ["*"]},
        }
    )

    added = design._seed_allowlist_from_source("obel", "target")

    assert added == 2  # 2 obel cells → 2 target cells; chonk is untouched
    data = _read(path)
    assert data["target:desktop:cart-filled"] == {"narrow-wc-block": [".wc-block-cart-items"]}
    assert data["target:wide:my-account"] == {"narrow-wc-block": [".wo-account-login-grid"]}
    # chonk entries are preserved byte-for-byte
    assert data["chonk:desktop:checkout-filled"] == {"a11y-color-contrast": ["*"]}


def test_seed_allowlist_is_idempotent(allowlist_sandbox):
    """Running apply twice is a no-op on the second call: the first run
    creates the target cells, the second run sees they already exist
    and adds nothing."""
    _, write = allowlist_sandbox
    write({"obel:desktop:cart-filled": {"narrow-wc-block": [".wc-block-cart-items"]}})

    first = design._seed_allowlist_from_source("obel", "target")
    second = design._seed_allowlist_from_source("obel", "target")

    assert first == 1
    assert second == 0


def test_seed_allowlist_merges_new_fingerprints_into_existing_cells(allowlist_sandbox):
    """If the target cell pre-exists (operator-authored, or a prior
    run with a narrower source), newly-discovered fingerprints from
    the source merge in — never replace. Existing fingerprints survive
    untouched."""
    path, write = allowlist_sandbox
    write(
        {
            "obel:desktop:cart-filled": {
                "narrow-wc-block": [".wc-block-cart-items", ".new-selector"]
            },
            "target:desktop:cart-filled": {
                "narrow-wc-block": [".operator-added-selector"],
                "a11y-color-contrast": ["*"],
            },
        }
    )

    added = design._seed_allowlist_from_source("obel", "target")

    assert added == 0  # no new CELLS, just merged fingerprints
    data = _read(path)
    target = data["target:desktop:cart-filled"]
    assert set(target["narrow-wc-block"]) == {
        ".operator-added-selector",
        ".wc-block-cart-items",
        ".new-selector",
    }
    # Operator-authored kind survives untouched even though obel doesn't have it.
    assert target["a11y-color-contrast"] == ["*"]


def test_seed_allowlist_self_source_is_noop(allowlist_sandbox):
    """Seeding obel from obel adds nothing — prevents a subtle duplicate-
    key self-inflation if the source and target slugs ever collide."""
    path, write = allowlist_sandbox
    write({"obel:desktop:cart-filled": {"narrow-wc-block": [".sel"]}})

    added = design._seed_allowlist_from_source("obel", "obel")

    assert added == 0
    assert _read(path) == {"obel:desktop:cart-filled": {"narrow-wc-block": [".sel"]}}


def test_seed_allowlist_missing_file_is_graceful(tmp_path, monkeypatch):
    """No allowlist on disk (fresh checkout) returns 0 without
    crashing. Matches the `bin/check.py` behaviour: missing file
    means 'no allowlist', not 'fail'."""
    monkeypatch.setattr(design, "MONOREPO_ROOT", tmp_path)
    assert not (tmp_path / "tests" / "visual-baseline").exists()

    added = design._seed_allowlist_from_source("obel", "target")

    assert added == 0


def test_seed_allowlist_malformed_json_is_graceful(allowlist_sandbox):
    """A corrupt allowlist returns 0 rather than exploding — the
    operator will see the underlying `check_json_validity` failure
    downstream, which is the right surface to surface it."""
    path, _ = allowlist_sandbox
    path.write_text("{this is not json", encoding="utf-8")

    added = design._seed_allowlist_from_source("obel", "target")

    assert added == 0
    # The bad file is NOT clobbered — operator can still read it to debug.
    assert path.read_text(encoding="utf-8") == "{this is not json"


def test_seed_allowlist_preserves_wildcard_cells_untouched(allowlist_sandbox):
    """`*:viewport:route` wildcard entries (the 4 cross-theme waivers
    for checkout-filled autocomplete) are by design shared by every
    theme. Cloning source → target must never convert wildcards into
    per-theme entries, and must never drop them."""
    path, write = allowlist_sandbox
    write(
        {
            "obel:desktop:cart-filled": {"narrow-wc-block": [".wc-block-cart-items"]},
            "*:desktop:checkout-filled.return-to-cart-visible": {"a11y-autocomplete-valid": ["*"]},
        }
    )

    added = design._seed_allowlist_from_source("obel", "target")

    assert added == 1  # the obel cell, NOT the wildcard
    data = _read(path)
    assert "*:desktop:checkout-filled.return-to-cart-visible" in data
    assert "target:desktop:checkout-filled.return-to-cart-visible" not in data


def test_seed_allowlist_preserves_existing_key_order(allowlist_sandbox):
    """The file must be rewritten with original keys in their original
    order, with new target cells appended after the source cells they
    mirror. Sorting the whole file on every apply run would turn a
    2-line operator review into a 300-line "the whole allowlist
    reshuffled" review — the same footgun that motivated the existing
    `sort_keys=False` serialisation everywhere else in the codebase."""
    path, write = allowlist_sandbox
    write(
        {
            "*:wide:checkout-filled.return-to-cart-visible": {"a11y-autocomplete-valid": ["*"]},
            "obel:wide:my-account": {"narrow-wc-block": [".x"]},
            "obel:desktop:cart-filled": {"narrow-wc-block": [".y"]},
            "chonk:desktop:foo": {"a11y-color-contrast": ["*"]},
        }
    )

    design._seed_allowlist_from_source("obel", "target")

    data = json.loads(path.read_text(encoding="utf-8"))
    keys = list(data.keys())
    # Originals stay where they were — wildcard first, obel entries in
    # their original (reverse-alphabetic) order, chonk last.
    assert keys[:4] == [
        "*:wide:checkout-filled.return-to-cart-visible",
        "obel:wide:my-account",
        "obel:desktop:cart-filled",
        "chonk:desktop:foo",
    ], f"originals must not re-order; got {keys[:4]!r}"
    # New target cells are appended after the last source cell, in the
    # same order as the source cells they mirror.
    assert keys[4:] == ["target:wide:my-account", "target:desktop:cart-filled"], (
        f"new target cells must mirror source order; got {keys[4:]!r}"
    )


# ---------------------------------------------------------------------------
# Safety net: every test above monkeypatches MONOREPO_ROOT into tmp_path
# before calling the helpers. This autouse teardown makes sure the REAL
# monorepo allowlist is never clobbered as a side-effect — if a future
# test regresses and forgets the monkeypatch, we'd see obel's entries
# disappear from the committed file, and this fixture would flag it
# immediately rather than letting a silent corruption ship.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _real_allowlist_untouched():
    yield

    real_allow = REPO_ROOT / "tests" / "visual-baseline" / "heuristics-allowlist.json"
    if real_allow.is_file():
        payload = json.loads(real_allow.read_text(encoding="utf-8"))
        assert any(k.startswith("obel:") for k in payload), (
            "FATAL: tests/visual-baseline/heuristics-allowlist.json was "
            "clobbered by a seed_placeholders test — please revert it. "
            "The real allowlist should never be touched by tests."
        )
