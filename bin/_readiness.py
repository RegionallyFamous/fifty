"""Per-theme readiness manifests (Tier 1.3 of pre-100-themes hardening).

Every theme may now ship a `<theme>/readiness.json` file that tells the
discovery layer (`_lib.iter_themes`, `snap.discover_themes`,
`append-wc-overrides.discover_themes`) and the theme-status dashboard
(Tier 2.2) what state the theme is in:

  * `incubating`  -- still being designed; excluded from the default
                     visibility filter used by the snap gallery, the
                     `bin/check.py --all` sweep, and
                     `bin/append-wc-overrides.py`. Mockups and WIP
                     mockup-driven iteration still happen, but the
                     theme does NOT count against CI's green/red gate
                     and is not listed on `docs/themes/index.html`.
  * `shipping`    -- live on demo.regionallyfamous.com, listed in the
                     gallery, gated by every CI check. This is the
                     stage the six original themes backfill into.
  * `retired`     -- kept on disk for provenance (so git history + the
                     redirect map keep resolving) but excluded from
                     everything: not gated by CI, not listed anywhere.
                     A retirement note explains why it was deprecated.

Why a separate manifest instead of overloading `theme.json`:
    `theme.json` is WordPress's own theme-config format; WP doesn't
    know about `stage` and a lone custom top-level key (`"fifty": {...}`)
    risks tripping future WP core validation. A sibling file in the
    theme dir is schema-free from WP's POV, easy to diff, and keeps
    the WP-facing theme.json minimal and portable.

Why default missing == "shipping":
    Backward compat for the six existing themes that don't have
    manifests yet on existing branches. `bin/check.py::check_theme_
    readiness` reports a WARN (not FAIL) when the file is missing,
    nudging operators to add one; we can promote that to FAIL once
    the backfill has rolled through every active branch and every
    Day-0 smoke batch concept.

Example (shipping):
    {
      "stage": "shipping",
      "summary": "Farm co-op marketplace with warm sepia palette.",
      "owner": "nick",
      "last_checked": "2026-04-26",
      "notes": "First shipped in the original 5-theme batch."
    }

Example (incubating):
    {
      "stage": "incubating",
      "summary": "Specimen-grid beauty brand, contemporary tone.",
      "owner": "nick",
      "last_checked": "2026-04-26",
      "notes": "Awaiting microcopy pass + front-page restructure."
    }
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

STAGE_INCUBATING = "incubating"
STAGE_SHIPPING = "shipping"
STAGE_RETIRED = "retired"
VALID_STAGES = frozenset({STAGE_INCUBATING, STAGE_SHIPPING, STAGE_RETIRED})

# What counts as "visible by default" when a caller asks for themes
# without explicitly naming a stage filter. Incubating themes are
# deliberately hidden from the default sweep so an unfinished theme
# doesn't bring the green CI down; they're opt-in via an explicit
# `stages=(STAGE_INCUBATING,)` argument.
DEFAULT_VISIBLE_STAGES: frozenset[str] = frozenset({STAGE_SHIPPING})

MANIFEST_NAME = "readiness.json"


@dataclass(frozen=True)
class Readiness:
    """Parsed view of a `<theme>/readiness.json`, or a default for themes
    that don't have one yet.

    Attributes:
        stage:        one of VALID_STAGES.
        summary:      single-sentence brand/design summary (free text).
        owner:        operator slug responsible for this theme.
        last_checked: ISO date (YYYY-MM-DD) of the last human review.
        notes:        free-form notes (retirement reasons, blockers).
        source:       path the manifest was read from, or None if the
                      theme didn't have one and we're returning a
                      default Readiness object.
    """

    stage: str = STAGE_SHIPPING
    summary: str = ""
    owner: str = ""
    last_checked: str = ""
    notes: str = ""
    source: Path | None = None

    @property
    def exists(self) -> bool:
        """Whether a real readiness.json was present on disk."""
        return self.source is not None


def manifest_path(theme_dir: Path) -> Path:
    """Return the path where `theme_dir`'s readiness manifest lives.

    The file does NOT have to exist; callers that need existence info
    should check `manifest_path(theme_dir).exists()` or load via
    `load_readiness()` and inspect `Readiness.exists`.
    """
    return theme_dir / MANIFEST_NAME


def load_readiness(theme_dir: Path) -> Readiness:
    """Load `theme_dir/readiness.json`, returning a safe default if
    missing or unreadable.

    A malformed JSON file, an unknown `stage`, or a read error ALL fall
    back to the default (stage=shipping, source=None). The check.py
    rule is the place for strict validation; discovery code should
    never crash because a single theme's manifest is bad.
    """
    path = manifest_path(theme_dir)
    if not path.is_file():
        return Readiness()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Readiness(source=path)
    if not isinstance(data, dict):
        return Readiness(source=path)
    stage = data.get("stage", STAGE_SHIPPING)
    if stage not in VALID_STAGES:
        stage = STAGE_SHIPPING
    return Readiness(
        stage=stage,
        summary=str(data.get("summary", "") or ""),
        owner=str(data.get("owner", "") or ""),
        last_checked=str(data.get("last_checked", "") or ""),
        notes=str(data.get("notes", "") or ""),
        source=path,
    )


def is_visible(
    theme_dir: Path,
    stages: Iterable[str] | None = None,
) -> bool:
    """Return True if `theme_dir`'s stage is in `stages` (or the default).

    `stages=None` means "use the default visible set" (shipping only).
    Passing an explicit `stages=("shipping", "incubating")` opts an
    operator tool into WIP themes (e.g. an agent building a new concept).
    """
    wanted = frozenset(stages) if stages is not None else DEFAULT_VISIBLE_STAGES
    readiness = load_readiness(theme_dir)
    return readiness.stage in wanted


def validate_payload(data: object) -> list[str]:
    """Return a list of human-readable problems with a manifest payload.

    Used by `bin/check.py::check_theme_readiness`. An empty list means
    the manifest is valid. This is intentionally permissive: all fields
    except `stage` are soft so an operator can ship a shell manifest
    and backfill the narrative later. `stage` itself must be one of the
    known values.
    """
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["readiness.json root must be a JSON object"]
    stage = data.get("stage")
    if not isinstance(stage, str):
        problems.append("`stage` is required and must be a string")
    elif stage not in VALID_STAGES:
        problems.append(
            f"`stage` must be one of {sorted(VALID_STAGES)}, got {stage!r}"
        )
    for field in ("summary", "owner", "last_checked", "notes"):
        if field in data and not isinstance(data[field], str):
            problems.append(f"`{field}` must be a string if present")
    return problems
