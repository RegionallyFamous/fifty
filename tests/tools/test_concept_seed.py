"""Contract tests for `bin/concept_seed.py` and `bin/audit-concepts.py`.

The seed module is the source of truth for every concept on the bench.
These tests guard:

* Every concept on disk (in `mockups/`) has a matching seed entry.
* Every controlled-vocabulary token used in the seed is registered in
  the corresponding *_TOKENS / *_GENRES / *_ERAS / *_SECTORS sets.
* The audit clustering remains deterministic — two runs against the
  same seed produce byte-identical AUDIT.md output.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def seed():
    """Import bin/concept_seed.py once per module."""
    sys.path.insert(0, str(ROOT / "bin"))
    import concept_seed  # noqa: E402

    return concept_seed


@pytest.fixture
def audit():
    """Load `bin/audit-concepts.py` as a module (hyphenated filename)."""
    spec = importlib.util.spec_from_file_location(
        "audit_concepts", ROOT / "bin" / "audit-concepts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_validates_clean(seed) -> None:
    """`validate()` must return an empty list. Any token outside the
    controlled vocab, any duplicate slug, any missing field is
    surfaced here so the next reader knows immediately what broke."""
    errors = seed.validate()
    assert errors == [], "\n  ".join(["concept_seed.validate() failures:"] + errors)


def test_seed_covers_every_mockup_on_disk(seed) -> None:
    """Every PNG in mockups/ — single-image OR directory form — must
    have a seed entry. Without this the audit + the queue card both
    silently render with an empty blurb / missing tags."""
    seed_slugs = set(seed.CONCEPTS_BY_SLUG.keys())
    disk_slugs: set[str] = set()
    for path in (ROOT / "mockups").glob("mockup-*.png"):
        disk_slugs.add(path.stem.removeprefix("mockup-"))
    for sub in (ROOT / "mockups").iterdir():
        if sub.is_dir() and (sub / "home.png").is_file():
            disk_slugs.add(sub.name)
    missing_in_seed = disk_slugs - seed_slugs
    assert not missing_in_seed, (
        f"Concepts on disk without a seed entry: {sorted(missing_in_seed)}. "
        f"Add them to bin/concept_seed.py::CONCEPTS."
    )


def test_seed_does_not_reference_phantom_mockups(seed) -> None:
    """A seed entry pointing at a non-existent PNG (typo, deleted file)
    would render as a broken thumbnail in the queue. Catch it here."""
    seed_slugs = set(seed.CONCEPTS_BY_SLUG.keys())
    disk_slugs: set[str] = set()
    for path in (ROOT / "mockups").glob("mockup-*.png"):
        disk_slugs.add(path.stem.removeprefix("mockup-"))
    for sub in (ROOT / "mockups").iterdir():
        if sub.is_dir() and (sub / "home.png").is_file():
            disk_slugs.add(sub.name)
    phantoms = seed_slugs - disk_slugs
    assert not phantoms, (
        f"Seed references concepts with no mockup on disk: {sorted(phantoms)}. "
        f"Either add the PNG OR remove the seed entry."
    )


def test_audit_render_is_deterministic(audit) -> None:
    """Two consecutive renders against the same seed must produce
    byte-identical output. AUDIT.md is committed to the repo; a
    non-deterministic render would re-dirty the file on every CI
    run and pollute every PR diff."""
    first = audit.render_audit()
    second = audit.render_audit()
    assert first == second
