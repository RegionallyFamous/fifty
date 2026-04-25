"""Contract tests for the concept-queue v2 helpers in
`bin/build-redirects.py`.

These guard the "single-image OR directory" discovery contract,
the metadata loading + render-card shape, and the multi-view
gallery emission for the per-concept detail page. Anything that
moves the URL structure (where docs/concepts/<slug>/ lives, where
docs/mockups/ images get copied, what the queue card body link
points at) has a test here so the static-site contract stays
boring across refactors.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def br():
    """Load `bin/build-redirects.py` as a module. Hyphenated filename so
    importlib.util.spec is the only option."""
    spec = importlib.util.spec_from_file_location(
        "build_redirects", ROOT / "bin" / "build-redirects.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_mockups(tmp_path: Path, monkeypatch, br):
    """Spin up a tiny fake `mockups/` tree with one single-image and one
    multi-image concept, plus matching meta.json files. Used to test
    discovery + view resolution without depending on the real (and
    growing) mockups directory.
    """
    mockups = tmp_path / "mockups"
    mockups.mkdir()

    # Single-image concept (legacy form).
    (mockups / "mockup-single.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (mockups / "single.meta.json").write_text(
        json.dumps(
            {
                "slug": "single",
                "name": "Single",
                "blurb": "A single-image concept fixture.",
                "tags": {
                    "palette": ["cream", "ink"],
                    "type": "geometric-sans",
                    "era": "contemporary",
                    "sector": "general",
                    "hero": "type-led",
                },
                "palette_hex": ["#ffffff", "#000000"],
                "type_specimen": "Display: Foo. Body: Bar.",
            }
        )
    )

    # Multi-image concept (directory form, several views).
    multi_dir = mockups / "multi"
    multi_dir.mkdir()
    for view in ("home", "pdp", "cart"):
        (multi_dir / f"{view}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (mockups / "multi.meta.json").write_text(
        json.dumps(
            {
                "slug": "multi",
                "name": "Multi",
                "blurb": "A directory-form concept fixture.",
                "tags": {
                    "palette": ["scarlet", "cobalt"],
                    "type": "grotesk-sans",
                    "era": "1980s",
                    "sector": "art-print",
                    "hero": "specimen-grid",
                },
                "palette_hex": ["#ff0000", "#0000ff"],
                "type_specimen": "Display: Helvetica.",
            }
        )
    )

    monkeypatch.setattr(br, "MOCKUPS_DIR", mockups)
    return mockups


def test_discover_concepts_finds_both_layouts(br, fake_mockups) -> None:
    """A concept can ship as either `mockup-<slug>.png` or as
    `<slug>/home.png`. Both forms must show up in the queue. If this
    fails, half the queue silently disappears from
    demo.regionallyfamous.com/concepts/."""
    unbuilt, built = br.discover_concepts(set())
    slugs = {c["slug"] for c in unbuilt + built}
    assert slugs == {"single", "multi"}


def test_multi_image_concept_exposes_all_views(br, fake_mockups) -> None:
    """For directory-form concepts, every PNG that's in
    CONCEPT_VIEW_ORDER must appear in `views`, in order. The detail-
    page renderer relies on this order for the carousel slides."""
    unbuilt, _ = br.discover_concepts(set())
    multi = next(c for c in unbuilt if c["slug"] == "multi")
    view_names = [v[0] for v in multi["views"]]
    assert view_names == ["home", "pdp", "cart"]
    assert multi["hero"] == multi["views"][0][1]


def test_single_image_concept_has_one_home_view(br, fake_mockups) -> None:
    """Legacy single-image concepts get a synthetic single ('home', path)
    view so downstream code can treat both layouts uniformly."""
    unbuilt, _ = br.discover_concepts(set())
    single = next(c for c in unbuilt if c["slug"] == "single")
    assert len(single["views"]) == 1
    assert single["views"][0][0] == "home"


def test_meta_data_round_trips_into_concept_record(br, fake_mockups) -> None:
    """`name`, `blurb`, `tags`, `palette_hex`, `type_specimen` from the
    sibling .meta.json must land in the concept dict. The render
    helpers depend on this — without it the detail page renders a
    title-cased slug and an empty tag dl."""
    unbuilt, _ = br.discover_concepts(set())
    multi = next(c for c in unbuilt if c["slug"] == "multi")
    assert multi["name"] == "Multi"
    assert multi["blurb"] == "A directory-form concept fixture."
    assert multi["tags"]["sector"] == "art-print"
    assert multi["palette_hex"] == ["#ff0000", "#0000ff"]
    assert "Helvetica" in multi["type_specimen"]


def test_built_concepts_partition_by_theme_slugs(br, fake_mockups) -> None:
    """When a slug matches a built theme directory, the concept moves
    from the unbuilt queue to the shipped section. Without this the
    landing page would never tag the live themes as 'shipped'."""
    unbuilt, built = br.discover_concepts({"multi"})
    assert {c["slug"] for c in unbuilt} == {"single"}
    assert {c["slug"] for c in built} == {"multi"}


def test_queue_card_body_links_to_detail_page(br, fake_mockups) -> None:
    """Track-B contract: the queue card body now links to
    `concepts/<slug>/`, not to a GitHub issue. The 'Pick this one'
    button moves to the detail page where there's room for the
    palette + type spec + carousel that justify the click."""
    unbuilt, _ = br.discover_concepts(set())
    single = next(c for c in unbuilt if c["slug"] == "single")
    html = br.render_concept_card(single, shipped=False)
    assert 'href="./single/"' in html, html
    # Old behaviour (issue URL in the body) must be gone.
    assert "github.com/RegionallyFamous/fifty/issues/new" not in html


def test_queue_card_carries_filter_data_attrs(br, fake_mockups) -> None:
    """The filter-strip JS reads data-sector / data-era / data-type /
    data-palette / data-slug off each card. Drop any of these and the
    filter buttons stop working for that concept."""
    unbuilt, _ = br.discover_concepts(set())
    multi = next(c for c in unbuilt if c["slug"] == "multi")
    html = br.render_concept_card(multi, shipped=False)
    assert 'data-slug="multi"' in html
    assert 'data-sector="art-print"' in html
    assert 'data-era="1980s"' in html
    assert 'data-type="grotesk-sans"' in html
    assert 'data-palette="scarlet cobalt"' in html


def test_palette_dots_render_inline_hex_backgrounds(br, fake_mockups) -> None:
    """Each .dot inlines its background color so the static page works
    without runtime CSS variables. Helpful when the page is opened
    from a print preview or an email digest with stripped CSS."""
    unbuilt, _ = br.discover_concepts(set())
    single = next(c for c in unbuilt if c["slug"] == "single")
    html = br.render_concept_card(single, shipped=False)
    assert 'class="dot" style="background:#ffffff"' in html
    assert 'class="dot" style="background:#000000"' in html


def test_detail_page_renders_every_view_in_gallery(br, fake_mockups) -> None:
    """Multi-view concepts must emit one <figure> per view, with the
    view name in <figcaption> for screen readers. Single-view concepts
    collapse to a single solo figure with no caption."""
    unbuilt, _ = br.discover_concepts(set())
    multi = next(c for c in unbuilt if c["slug"] == "multi")
    html = br.render_concept_detail_page(multi, shipped=False)
    for view in ("home", "pdp", "cart"):
        assert f"../mockups/multi/{view}.png" in html
        assert f"<figcaption>{view}</figcaption>" in html
    single = next(c for c in unbuilt if c["slug"] == "single")
    html = br.render_concept_detail_page(single, shipped=False)
    assert "gallery-slide--solo" in html
    assert "../mockups/single.png" in html


def test_detail_page_swaps_cta_for_shipped_concepts(br, fake_mockups) -> None:
    """Shipped concepts get a 'See it live' CTA instead of the
    'Pick this one' issue button. If this regresses, the detail
    page would prompt people to file an issue to build a theme that
    already exists."""
    unbuilt, _ = br.discover_concepts({"multi"})
    multi = next(c for c in br.discover_concepts({"multi"})[1] if c["slug"] == "multi")
    html = br.render_concept_detail_page(multi, shipped=True)
    assert "See it live" in html
    assert "Pick this one" not in html


def test_filter_strip_only_emits_axes_with_values(br, fake_mockups) -> None:
    """The filter strip is data-driven: only axes with at least one
    populated value emit a button group. A queue with no `era` tags
    must NOT emit an empty 'Era' summary."""
    unbuilt, _ = br.discover_concepts(set())
    strip = br._render_filter_strip(unbuilt)
    assert "Sector" in strip
    assert "Era" in strip  # both fixtures populate era
    assert 'data-filter-value="art-print"' in strip
