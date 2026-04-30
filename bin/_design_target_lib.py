"""Per-theme design target: deterministic mockup → palette + rubric.

This module replaces the chain that previously turned a free-form prompt
into a sparse `spec.json` that the LLM design-tokens phase tried to massage
back into a full theme. The problems with that chain were specific:

* The spec only ever covered a handful of palette slugs (`base`, `accent`,
  maybe `contrast`). The remaining 11 slugs in `KNOWN_COLOR_SLUGS` (subtle,
  surface, muted, secondary, tertiary, primary-hover, accent-soft, success,
  warning, error, info) silently kept the source theme's hex values, so a
  scarlet-and-cream Agitprop shipped with Obel's olive `success` / ochre
  `warning` / blue `info` and a *grey* `primary-hover` — not on-brand.
* Each theme cloned `obel/design-intent.md` verbatim, so the vision
  reviewer's rubric described a "quiet, considered, editorial" shop
  regardless of what the mockup actually demanded.
* The Anthropic round-trip that tried to fix both of those (the
  design-tokens phase) shipped JSON patches that intermittently failed to
  parse (control characters, smart quotes, truncated arrays) and ran on
  every theme regardless of whether the mockup had already encoded the
  same information in `mockups/<slug>.meta.json`.

The design here is the opposite shape: the per-theme **target** is a
small, structured JSON document that the rest of the factory consumes.

* `DesignTarget` (this module) — typed dataclass + JSON schema v1
* `expand_palette(target)` — deterministic 16-slug expansion
* `derive_target_from_meta(slug)` — read `mockups/<slug>.meta.json`
  + tags and produce a complete target without an LLM call
* `render_design_intent_md(target, slug)` — produce a per-theme rubric
  the vision reviewer actually wants to grade against

The vision-API extractor that reads `mockups/<slug>.png` directly is a
follow-up: it produces the same `DesignTarget` shape, just with palette
hexes and composition fields lifted from pixels instead of from the
already-published meta tags. The factory does not care which producer
ran; it consumes the JSON.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Order matters in a few places (we emit palette entries in this order
# when writing theme.json so diffs read consistently).
_BACKGROUND_SLUGS: tuple[str, ...] = ("base", "surface", "subtle", "accent-soft")
_INK_SLUGS: tuple[str, ...] = ("contrast", "border")
_CHROME_SLUGS: tuple[str, ...] = ("muted", "secondary", "tertiary")
_BRAND_SLUGS: tuple[str, ...] = ("primary", "primary-hover", "accent")
_ALERT_SLUGS: tuple[str, ...] = ("success", "warning", "error", "info")

EXPANDED_SLUGS: tuple[str, ...] = (
    *_BACKGROUND_SLUGS,
    *_CHROME_SLUGS,
    *_INK_SLUGS,
    *_BRAND_SLUGS,
    *_ALERT_SLUGS,
)

# Recognised composition / ornament / hero buckets. The reviewer's rubric
# (the rendered design-intent.md) cites these verbatim, so keep them
# stable. Adding a new value here means extending `_HERO_RULES` /
# `_ORNAMENT_RULES` / `_DENSITY_RULES` below so the reviewer learns what
# to flag.
HERO_KINDS: tuple[str, ...] = (
    "type-led",
    "photo-led",
    "product-led",
    "poster-led",
    "engraved-led",
    "neutral",
)
ORNAMENT_KINDS: tuple[str, ...] = (
    "none",
    "diagonal",
    "etched",
    "stripes",
    "botanical",
    "geometric",
    "brutalist",
)
DENSITY_KINDS: tuple[str, ...] = ("airy", "balanced", "tight")
BORDER_KINDS: tuple[str, ...] = ("none", "hairline", "hard")
PHOTO_KINDS: tuple[str, ...] = (
    "natural-still-life",
    "studio-product",
    "high-contrast-poster",
    "engraving",
    "editorial",
    "neutral",
)
REGISTER_KINDS: tuple[str, ...] = (
    "editorial",
    "imperative",
    "playful",
    "workshop",
    "hospitality",
    "manifesto",
)


# --------------------------------------------------------------------------- #
# Color helpers (deterministic, no LLM, no third-party dep)                    #
# --------------------------------------------------------------------------- #
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def normalize_hex(value: str) -> str:
    """Return ``#rrggbb`` (lowercase) or raise ValueError."""
    if not isinstance(value, str) or not _HEX_RE.match(value.strip()):
        raise ValueError(f"not a 6-digit hex color: {value!r}")
    h = value.strip().lstrip("#").lower()
    return f"#{h}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float] | tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance for #rrggbb."""

    def _channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la = _relative_luminance(a) + 0.05
    lb = _relative_luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


def _mix(a: str, b: str, t: float) -> str:
    """Linear RGB mix: t=0 returns a, t=1 returns b."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex((ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t))


def _is_light(hex_color: str) -> bool:
    return _relative_luminance(hex_color) >= 0.5


def _ensure_min_contrast(fg: str, bg: str, target_ratio: float = 4.5) -> str:
    """Nudge `fg` toward black or white until it has `target_ratio` against `bg`.

    Used for derived chrome that must stay legible on whatever the paper
    color happens to be. Idempotent — returns `fg` unchanged when it is
    already legible.
    """
    if contrast_ratio(fg, bg) >= target_ratio:
        return fg
    target_dark = "#000000"
    target_light = "#ffffff"
    target = target_dark if _is_light(bg) else target_light
    # 8 binary-search steps is plenty: each ~halves the gap.
    lo, hi = 0.0, 1.0
    best = fg
    for _ in range(8):
        mid = (lo + hi) / 2
        candidate = _mix(fg, target, mid)
        if contrast_ratio(candidate, bg) >= target_ratio:
            best = candidate
            hi = mid
        else:
            lo = mid
    return best


# --------------------------------------------------------------------------- #
# Schema                                                                       #
# --------------------------------------------------------------------------- #


@dataclass
class DesignTargetType:
    family: str
    fallback: str = ""
    google_font: bool = True
    weights: tuple[int, ...] = (400,)


@dataclass
class DesignTarget:
    """The full design intent for one theme.

    `palette` carries the **brand** hexes — paper, ink, accent and any
    chrome tones the mockup actually uses. `expand_palette()` derives
    the full 16-slug WordPress palette from those few inputs.
    """

    schema: int
    slug: str
    name: str
    voice: dict[str, Any]
    palette: dict[str, str]
    type: dict[str, Any]
    composition: dict[str, str]
    required_signals: list[str]
    forbidden_signals: list[str]
    source: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Serialisation                                                       #
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "slug": self.slug,
            "name": self.name,
            "voice": self.voice,
            "palette": self.palette,
            "type": self.type,
            "composition": self.composition,
            "required_signals": list(self.required_signals),
            "forbidden_signals": list(self.forbidden_signals),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DesignTarget:
        if not isinstance(data, dict):
            raise ValueError("design-target must be a JSON object")
        if data.get("schema") != 1:
            raise ValueError(f"unknown schema: {data.get('schema')!r}")
        for key in ("slug", "name"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ValueError(f"design-target.{key} must be a non-empty string")
        palette_raw = data.get("palette") or {}
        if not isinstance(palette_raw, dict) or not palette_raw:
            raise ValueError("design-target.palette must be a non-empty object")
        palette = {str(k): normalize_hex(v) for k, v in palette_raw.items()}
        if "paper" not in palette or "ink" not in palette or "accent" not in palette:
            raise ValueError(
                "design-target.palette must include paper, ink and accent at minimum"
            )
        composition = data.get("composition") or {}
        if not isinstance(composition, dict):
            raise ValueError("design-target.composition must be an object")
        composition.setdefault("hero", "neutral")
        composition.setdefault("density", "balanced")
        composition.setdefault("ornament", "none")
        composition.setdefault("borders", "hairline")
        composition.setdefault("photography_style", "neutral")
        for slot, allowed in (
            ("hero", HERO_KINDS),
            ("density", DENSITY_KINDS),
            ("ornament", ORNAMENT_KINDS),
            ("borders", BORDER_KINDS),
            ("photography_style", PHOTO_KINDS),
        ):
            if composition[slot] not in allowed:
                raise ValueError(
                    f"design-target.composition.{slot}={composition[slot]!r} "
                    f"not in {sorted(allowed)}"
                )
        type_section = data.get("type") or {}
        if not isinstance(type_section, dict):
            raise ValueError("design-target.type must be an object")
        voice = data.get("voice") or {}
        if not isinstance(voice, dict):
            raise ValueError("design-target.voice must be an object")
        voice.setdefault("register", "editorial")
        if voice["register"] not in REGISTER_KINDS:
            raise ValueError(
                f"design-target.voice.register={voice['register']!r} "
                f"not in {sorted(REGISTER_KINDS)}"
            )
        return cls(
            schema=int(data["schema"]),
            slug=str(data["slug"]),
            name=str(data["name"]),
            voice=voice,
            palette=palette,
            type=type_section,
            composition=composition,
            required_signals=list(data.get("required_signals") or []),
            forbidden_signals=list(data.get("forbidden_signals") or []),
            source=dict(data.get("source") or {}),
        )


# --------------------------------------------------------------------------- #
# Palette expansion                                                            #
# --------------------------------------------------------------------------- #
def expand_palette(target: DesignTarget) -> dict[str, str]:
    """Turn the brand palette into a full 16-slug WP palette.

    The expansion rules are deliberately simple and explicit so a human
    can read the result and reason about why every slug got the value it
    did. We never invent a color that wasn't either named in the target
    palette or derived from one by a documented transform.

    Inputs the target may carry:
      * paper        — page background (always)
      * ink          — body text + borders (always)
      * accent       — primary action / brand highlight (always)
      * accent_soft  — washed-out accent for tinted bands (optional)
      * chrome_warm  — a tan / brown / olive (optional)
      * chrome_cool  — a grey / blue-grey (optional)
      * Any explicit slug in ``EXPANDED_SLUGS`` — wins over derivations.

    The four alert slugs (success/warning/error/info) are derived from
    fixed, palette-tone-aware hues so they don't read as off-brand. We
    used to inherit Obel's olive / ochre / blue verbatim, which is what
    made every theme's checkout chrome feel identical.
    """
    paper = target.palette["paper"]
    ink = target.palette["ink"]
    accent = target.palette["accent"]
    light_paper = _is_light(paper)

    chrome_warm = target.palette.get("chrome_warm") or _mix(
        paper, ink, 0.45 if light_paper else 0.55
    )
    chrome_cool = target.palette.get("chrome_cool") or _mix(chrome_warm, ink, 0.5)

    # Surface: a faint shift away from paper. On light themes lift toward
    # white; on dark themes lift toward ink (still darker, but distinct).
    surface = target.palette.get("surface") or (
        _mix(paper, "#ffffff", 0.55) if light_paper else _mix(paper, ink, 0.18)
    )
    subtle = target.palette.get("subtle") or _mix(paper, chrome_warm, 0.25)
    accent_soft = target.palette.get("accent_soft") or _mix(
        accent, paper, 0.78 if light_paper else 0.65
    )

    border = target.palette.get("border") or ink
    contrast = target.palette.get("contrast") or ink

    primary = target.palette.get("primary") or accent
    primary_hover = target.palette.get("primary_hover") or _mix(
        primary, ink, 0.25 if light_paper else 0.15
    )

    # Chrome ladder. `secondary` and `tertiary` are routinely used as
    # paragraph text colors in patterns/templates (eyebrows, captions,
    # subtitles), so they must clear WCAG AA Normal (4.5:1) against the
    # paper. `muted` is reserved for icon fills, dividers and outlines
    # where AA-Large (3:1) is the right floor. We start from the brand
    # chrome the mockup gave us and only nudge toward ink when needed.
    muted = target.palette.get("muted") or chrome_warm
    secondary = target.palette.get("secondary") or chrome_cool
    tertiary = target.palette.get("tertiary") or _mix(chrome_warm, chrome_cool, 0.5)
    muted = _ensure_min_contrast(muted, paper, 3.0)
    secondary = _ensure_min_contrast(secondary, paper, 4.5)
    tertiary = _ensure_min_contrast(tertiary, paper, 4.5)

    # Alerts are derived from canonical hues, then retoned toward the
    # accent's *value* (light/dark) so they don't pop in front of the
    # rest of the palette. Each one is then nudged into AA-Large
    # contrast on `paper`.
    accent_lum = _relative_luminance(accent)
    alert_anchor_dark = "#1d3a26" if light_paper else "#2c5b3d"
    alert_anchor_warning_dark = "#7a4a1a" if light_paper else "#a06b29"
    alert_anchor_error_dark = "#8a2424" if light_paper else "#bf3a3a"
    alert_anchor_info_dark = "#1f4e8a" if light_paper else "#3a73c2"

    success = target.palette.get("success") or _ensure_min_contrast(
        _mix(alert_anchor_dark, accent, 0.15 if accent_lum < 0.5 else 0.25),
        paper,
        3.0,
    )
    warning = target.palette.get("warning") or _ensure_min_contrast(
        alert_anchor_warning_dark, paper, 3.0
    )
    error = target.palette.get("error") or _ensure_min_contrast(
        _mix(alert_anchor_error_dark, accent, 0.4), paper, 3.0
    )
    info = target.palette.get("info") or _ensure_min_contrast(alert_anchor_info_dark, paper, 3.0)

    return {
        "base": paper,
        "surface": surface,
        "subtle": subtle,
        "accent-soft": accent_soft,
        "muted": muted,
        "secondary": secondary,
        "tertiary": tertiary,
        "contrast": contrast,
        "border": border,
        "primary": primary,
        "primary-hover": primary_hover,
        "accent": accent,
        "success": success,
        "warning": warning,
        "error": error,
        "info": info,
    }


# --------------------------------------------------------------------------- #
# Derivation from `mockups/<slug>.meta.json`                                   #
# --------------------------------------------------------------------------- #
# The concept queue already encodes a structured summary of every concept
# in `mockups/<slug>.meta.json` (palette_hex, tags.palette / type / era /
# sector / hero, type_specimen). That is enough to build a `DesignTarget`
# without any LLM call — and it's a strict superset of the information
# the previous `spec.json` ever carried.

# Per-tag type defaults. Mono is intentionally absent: most concepts don't
# call for a custom mono and inheriting the source theme's `ui-monospace`
# stack is the right default. A theme that wants a custom mono can name
# it explicitly in `design-target.json` after extraction.
_TYPE_RULES: dict[str, dict[str, Any]] = {
    "geometric-sans": {
        "display": ("Bebas Neue", "Impact, Arial Narrow, sans-serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": None,
    },
    "humanist-sans": {
        "display": ("Sora", "system-ui, Helvetica, Arial, sans-serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": None,
    },
    "modern-serif": {
        "display": ("Bricolage Grotesque", "Georgia, serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": ("EB Garamond", "Georgia, serif"),
    },
    "old-style-serif": {
        "display": ("Cormorant Garamond", "Georgia, serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": ("EB Garamond", "Georgia, serif"),
    },
    "slab-serif": {
        "display": ("Roboto Slab", "Georgia, serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": ("Roboto Slab", "Georgia, serif"),
    },
    "monospace": {
        "display": ("JetBrains Mono", "Menlo, Consolas, monospace"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": None,
        "mono": ("JetBrains Mono", "Menlo, Consolas, monospace"),
    },
    "script": {
        "display": ("Playfair Display", "Georgia, serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": ("EB Garamond", "Georgia, serif"),
    },
    "engraved": {
        "display": ("Cormorant Garamond", "Georgia, serif"),
        "sans": ("Inter", "system-ui, Helvetica, Arial, sans-serif"),
        "serif": ("EB Garamond", "Georgia, serif"),
    },
}

# Default fallback stacks, used when the meta's type_specimen names a
# family but no fallback (the common case — the meta only carries the
# headline name).
_FALLBACK_STACKS: dict[str, str] = {
    "display": "system-ui, Helvetica, Arial, sans-serif",
    "sans": "system-ui, Helvetica, Arial, sans-serif",
    "serif": "Georgia, serif",
    "mono": "Menlo, Consolas, monospace",
}


_HERO_BY_TAG: dict[str, str] = {
    "type-led": "type-led",
    "photo-led": "photo-led",
    "photo-hero": "photo-led",
    "full-bleed": "photo-led",
    "product-led": "product-led",
    "product-hero": "product-led",
    "poster-led": "poster-led",
    "poster": "poster-led",
    "engraved-led": "engraved-led",
    "engraved": "engraved-led",
}


_ORNAMENT_BY_SECTOR: dict[str, str] = {
    "art-print": "diagonal",
    "spirits": "etched",
    "distillery": "etched",
    "beverage": "etched",
    "apothecary": "etched",
    "specialty": "etched",
    "press": "diagonal",
    "newsprint": "stripes",
    "garden": "botanical",
    "florist": "botanical",
    "ceramics": "geometric",
    "modernist": "geometric",
    "industrial": "brutalist",
    "gift-shop": "geometric",
}


_REGISTER_BY_TAG: dict[str, str] = {
    "art-print": "manifesto",
    "press": "manifesto",
    "newsprint": "manifesto",
    "newspaper": "manifesto",
    "distillery": "workshop",
    "spirits": "workshop",
    "beverage": "workshop",
    "apothecary": "workshop",
    "specialty": "workshop",
    "ceramics": "workshop",
    "atelier": "workshop",
    "cafe": "hospitality",
    "restaurant": "hospitality",
    "bakery": "hospitality",
    "bar": "hospitality",
    "playful": "playful",
    "pop": "playful",
    "gift-shop": "playful",
    "toy": "playful",
    "punk": "imperative",
    "campaign": "imperative",
    "gallery": "editorial",
    "lookbook": "editorial",
}

# Era + type tags can also push the register one notch when the sector
# is generic. Y2K + chrome-deco read playful regardless of sector;
# pre-1900 + ornamental serif reads editorial; pre-1950 + workshop type
# reads workshop.
_REGISTER_BY_TYPE: dict[str, str] = {
    "chrome-deco": "playful",
    "ornamental": "editorial",
    "engraved": "workshop",
    "transitional-serif": "editorial",
}
_REGISTER_BY_ERA: dict[str, str] = {
    "y2k": "playful",
    "pre-1900": "editorial",
}


def _classify_palette(hexes: list[str]) -> dict[str, str]:
    """Pick paper / ink / accent / chrome roles from the meta palette list.

    The convention in `mockups/<slug>.meta.json` is roughly
    "[paper, accent, ink, chrome_warm, chrome_cool]" but the order isn't
    guaranteed. We score each hex on its luminance and saturation:

      * lightest, low-saturation → paper
      * darkest → ink
      * highest-saturation → accent
      * the remaining mid-tones, sorted lightest → darkest, fill
        chrome_warm / chrome_cool

    Fewer than 3 hexes is fine — `expand_palette()` will derive the rest.
    """
    if not hexes:
        raise ValueError("classify_palette: empty hex list")
    normalized = [normalize_hex(h) for h in hexes]
    seen: set[str] = set()
    deduped: list[str] = []
    for h in normalized:
        if h in seen:
            continue
        seen.add(h)
        deduped.append(h)
    metrics: list[tuple[str, float, float]] = []
    for h in deduped:
        r, g, b = _hex_to_rgb(h)
        max_c, min_c = max(r, g, b), min(r, g, b)
        sat = (max_c - min_c) / max_c if max_c else 0.0
        metrics.append((h, _relative_luminance(h), sat))
    by_lum = sorted(metrics, key=lambda x: x[1])
    by_sat = sorted(metrics, key=lambda x: x[2], reverse=True)
    paper = by_lum[-1][0]
    ink = by_lum[0][0]
    # Accent: the most saturated hex that isn't paper or ink.
    accent = next((h for h, _, _ in by_sat if h not in (paper, ink)), by_sat[0][0])
    chrome_pool = [h for h in deduped if h not in (paper, ink, accent)]
    chrome_pool.sort(key=lambda h: _relative_luminance(h), reverse=True)
    palette: dict[str, str] = {"paper": paper, "ink": ink, "accent": accent}
    if chrome_pool:
        palette["chrome_warm"] = chrome_pool[0]
    if len(chrome_pool) > 1:
        palette["chrome_cool"] = chrome_pool[1]
    return palette


def _parse_type_specimen(spec: str | None) -> dict[str, DesignTargetType]:
    """Turn the `type_specimen` free-text in meta.json into structured slots.

    Examples we want to handle:

        "Display: Rodchenko / Bebas Neue. Body: Roboto Condensed."
        "Display: Cormorant. Body: Inter."
        "Mono caption + sans body."
    """
    out: dict[str, DesignTargetType] = {}
    if not spec:
        return out
    parts = re.split(r"[.;]\s*", spec)
    for part in parts:
        if ":" not in part:
            continue
        role, _, families = part.partition(":")
        role_l = role.strip().lower()
        if role_l not in {"display", "body", "sans", "serif", "mono"}:
            continue
        # Family is whatever comes before the first " / " or ","
        family = families.strip().split("/")[-1].split(",")[0].strip()
        if not family:
            continue
        slot = "sans" if role_l == "body" else role_l
        out[slot] = DesignTargetType(
            family=family,
            fallback="",
            google_font=True,
            weights=(400, 700) if slot in {"sans", "serif"} else (400,),
        )
    return out


def derive_target_from_meta(slug: str, meta: dict[str, Any]) -> DesignTarget:
    """Build a `DesignTarget` deterministically from `<slug>.meta.json`."""
    name = str(meta.get("name") or slug.title())
    palette = _classify_palette(meta.get("palette_hex") or [])
    tags = meta.get("tags") or {}

    type_pref = str(tags.get("type") or "").lower()
    type_table = _TYPE_RULES.get(type_pref)
    type_section: dict[str, Any] = {}
    if type_table:
        for slot, value in type_table.items():
            if value is None:
                type_section[slot] = None
                continue
            family, fallback = value
            type_section[slot] = {
                "family": family,
                "fallback": fallback,
                "google_font": True,
                "weights": [400, 700] if slot in {"sans", "serif"} else [400],
            }
    # Type specimen text in the meta wins over the table when present.
    # Merge order: take the table's fallback unless the parser captured
    # one explicitly. This preserves "Impact, Arial Narrow, sans-serif"
    # when the meta only said "Display: Bebas Neue".
    for slot, parsed in _parse_type_specimen(meta.get("type_specimen")).items():
        existing = type_section.get(slot) or {}
        fallback = parsed.fallback or (existing.get("fallback") if isinstance(existing, dict) else "")
        if not fallback:
            fallback = _FALLBACK_STACKS.get(slot, "")
        type_section[slot] = {
            "family": parsed.family,
            "fallback": fallback,
            "google_font": parsed.google_font,
            "weights": list(parsed.weights),
        }
    type_section.setdefault(
        "rules",
        {
            "display_dominates_hero": tags.get("hero") in {"type-led", "poster-led"},
            "all_caps_ok_in_display": type_pref in {"geometric-sans", "monospace"},
            "letter_spacing_max_body": 0.05,
        },
    )

    sector = str(tags.get("sector") or "").lower()
    hero_tag = str(tags.get("hero") or "").lower()
    composition = {
        "hero": _HERO_BY_TAG.get(hero_tag, "neutral"),
        "density": "tight" if hero_tag in {"type-led", "poster-led"} else "balanced",
        "ornament": _ORNAMENT_BY_SECTOR.get(sector, "none"),
        "borders": "hard" if hero_tag in {"poster-led", "type-led"} else "hairline",
        "photography_style": _photography_for(sector, hero_tag),
    }

    era = str(tags.get("era") or "").lower()
    register = (
        _REGISTER_BY_TAG.get(sector)
        or _REGISTER_BY_TAG.get(hero_tag)
        or _REGISTER_BY_TYPE.get(type_pref)
        or _REGISTER_BY_ERA.get(era)
        or "editorial"
    )
    voice = {
        "summary": str(meta.get("blurb") or "").strip(),
        "register": register,
        "preferred_motifs": list(tags.get("preferred_motifs") or []),
        "forbidden_words": list(tags.get("forbidden_words") or []),
    }

    required, forbidden = _signals_for(composition, type_section, register)

    return DesignTarget(
        schema=1,
        slug=slug,
        name=name,
        voice=voice,
        palette=palette,
        type=type_section,
        composition=composition,
        required_signals=required,
        forbidden_signals=forbidden,
        source={
            "mockup": f"mockups/mockup-{slug}.png",
            "method": "deterministic-from-meta",
            "extracted_at": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        },
    )


def _photography_for(sector: str, hero_tag: str) -> str:
    if sector in {"art-print", "press", "newsprint"} or hero_tag == "poster-led":
        return "high-contrast-poster"
    if sector in {"distillery", "apothecary", "spirits"}:
        return "engraving"
    if sector in {"cafe", "restaurant", "bakery", "bar", "florist"}:
        return "natural-still-life"
    if sector in {"gallery", "lookbook", "modernist"}:
        return "editorial"
    if hero_tag == "product-led":
        return "studio-product"
    return "neutral"


def _signals_for(
    composition: dict[str, str],
    type_section: dict[str, Any],
    register: str,
) -> tuple[list[str], list[str]]:
    required: list[str] = []
    forbidden: list[str] = []

    if composition["hero"] == "type-led":
        required.append("All-caps display headline that dominates the hero")
        required.append("Primary CTA reads as a slab, not a pill")
        forbidden.append("Photographic hero with the headline reduced to caption size")
    elif composition["hero"] == "photo-led":
        required.append("Photographic hero with subject clearly framed")
        required.append("Display headline takes <40% of the hero height")
        forbidden.append("All-caps display headline filling the hero")
    elif composition["hero"] == "poster-led":
        required.append("Poster-style hero with strong color blocks behind a subject")
    elif composition["hero"] == "engraved-led":
        required.append("Hero subject reads as an engraving / etched line art")
        forbidden.append("Flat photograph of a generic product")
    elif composition["hero"] == "product-led":
        required.append("Photographic product hero with the price + CTA visible above the fold")

    if composition["ornament"] == "diagonal":
        required.append("Diagonal accent blocks behind the hero subject")
    elif composition["ornament"] == "etched":
        required.append("Etched / botanical line art accenting the hero or footer")
        forbidden.append("Drop-shadows or gradients used as decoration")
    elif composition["ornament"] == "stripes":
        required.append("Horizontal rule lines between sections (newspaper register)")
    elif composition["ornament"] == "geometric":
        required.append("Geometric tile or grid ornament visible at hero or footer")
    elif composition["ornament"] == "brutalist":
        required.append("Hard contrast borders on every framed element")
        forbidden.append("Soft pastel washes, rounded button corners")
    if composition["borders"] == "hard":
        required.append("Borders are hard 1–2px contrast lines, not hairlines")
        forbidden.append("Default rounded button radius — buttons should be slabs")
    elif composition["borders"] == "hairline":
        required.append("Borders are 1px hairlines in a chrome tone")
        forbidden.append("Hard 2px+ borders (reads as poster, breaks editorial register)")

    if register == "manifesto":
        forbidden.append("Lifestyle phrasing (curated, considered, mindful)")
        required.append("Imperative microcopy (verbs first, no marketing softeners)")
    elif register == "imperative":
        forbidden.append("Soft hospitality phrasing")
    elif register == "hospitality":
        required.append("Warm, welcoming microcopy with table/menu/seasonal cadence")
    elif register == "workshop":
        required.append("Maker / process / workshop vocabulary, batch + edition language")

    if type_section.get("rules", {}).get("display_dominates_hero"):
        required.append("Hero display heading may consume up to 50% of viewport height")

    return required, forbidden


# --------------------------------------------------------------------------- #
# Per-theme `design-intent.md`                                                 #
# --------------------------------------------------------------------------- #
def render_design_intent_md(
    target: DesignTarget,
    live_palette: dict[str, str] | None = None,
) -> str:
    """Produce the per-theme rubric the vision reviewer reads.

    The structure (Voice / Palette / Typography / Required / Forbidden /
    Mockup / Allowed exceptions) matches the convention that every other
    theme's design-intent.md uses, so `bin/snap-vision-review.py` keeps
    parsing it. The *content* is per-theme — not Obel's.

    `live_palette` lets the caller override the rubric's palette table
    with the values currently shipped in the theme's `theme.json`. The
    deterministic expander is correct for *new* themes (where the live
    theme.json starts as a clone of Obel and *should* be replaced), but
    on already-shipped themes the live palette is what the reviewer
    will actually see at render time. Passing it keeps the rubric
    truthful instead of describing colors the theme doesn't paint.
    """
    paper = (live_palette or {}).get("base") or target.palette["paper"]
    ink = (live_palette or {}).get("contrast") or target.palette["ink"]
    accent = (live_palette or {}).get("accent") or target.palette["accent"]
    expanded = expand_palette(target)
    if live_palette:
        # Live values win over the projected ones; missing slugs fall
        # back to the deterministic expansion so the rubric is always
        # complete.
        expanded = {**expanded, **{k: v for k, v in live_palette.items() if v}}

    type_lines: list[str] = []
    for slot in ("display", "sans", "serif", "mono"):
        slot_def = target.type.get(slot)
        if not slot_def:
            continue
        if isinstance(slot_def, dict):
            family = slot_def.get("family") or "—"
            fallback = slot_def.get("fallback") or "—"
            type_lines.append(f"- `{slot}` — {family} ({fallback})")
        else:
            type_lines.append(f"- `{slot}` — {slot_def}")

    composition_lines = [
        f"- **Hero**: {target.composition['hero']}",
        f"- **Density**: {target.composition['density']}",
        f"- **Ornament**: {target.composition['ornament']}",
        f"- **Borders**: {target.composition['borders']}",
        f"- **Photography**: {target.composition['photography_style']}",
    ]

    palette_table = "\n".join(
        [
            "| Slug | Hex | Role |",
            "|------|-----|------|",
            f"| `base` | `{expanded['base']}` | page background (paper) |",
            f"| `surface` | `{expanded['surface']}` | cards / panels |",
            f"| `subtle` | `{expanded['subtle']}` | gentle dividers |",
            f"| `contrast` | `{expanded['contrast']}` | body text (ink) |",
            f"| `accent` | `{expanded['accent']}` | CTA + brand highlight |",
            f"| `accent-soft` | `{expanded['accent-soft']}` | tinted accent band |",
            f"| `primary` | `{expanded['primary']}` | resting brand action |",
            f"| `primary-hover` | `{expanded['primary-hover']}` | hover state |",
        ]
    )

    required_block = "\n".join(f"- {item}" for item in target.required_signals) or "- None"
    forbidden_block = "\n".join(f"- {item}" for item in target.forbidden_signals) or "- None"

    voice_summary = target.voice.get("summary") or ""
    voice_register = target.voice.get("register") or "editorial"
    voice_motifs = ", ".join(target.voice.get("preferred_motifs") or []) or "—"

    mockup_rel = target.source.get("mockup") or f"mockups/mockup-{target.slug}.png"

    return f"""# {target.slug} — design intent

This file is the canonical design rubric for the **{target.slug}** theme. It is
read by [`bin/snap-vision-review.py`](../bin/snap-vision-review.py) and
concatenated into the prompt that asks Claude to review every screenshot.
Anything stated here becomes a thing the reviewer will flag when violated.

> _Auto-generated by `bin/render-design-target.py` from `design-target.json`._
> _Edit `design-target.json`, then re-run the renderer; do not hand-edit
> below this line unless you also update the JSON._

## Voice

{voice_summary or "(no blurb supplied — see `design-target.json` voice.summary)"}

- **Register**: {voice_register}
- **Preferred motifs**: {voice_motifs}

## Palette

Paper `{paper}` · ink `{ink}` · accent `{accent}`. Every other slug below is
derived from the brand palette; the alert family (success / warning / error
/ info) is retoned to sit on top of paper without hijacking the brand.

{palette_table}

**Forbidden uses**:

- Accent applied to decorative elements (borders, dividers, icon fills) —
  accent is reserved for "this is the action".
- Off-palette colors anywhere outside the table above.
- Drop-shadows on anything except active form states.

## Typography

{chr(10).join(type_lines) if type_lines else "- (inherit from source theme)"}

**Forbidden**:

- Display font on long-form body copy.
- All-caps body copy.
- Letter-spacing > 0.05em on body text.

## Composition

{chr(10).join(composition_lines)}

## Required signals

{required_block}

## Forbidden signals

{forbidden_block}

## Mockup

`{mockup_rel}` — concept mockup used as the visual reference for layout
selection, palette tuning, and `vision:mockup-divergent` review.

## Allowed exceptions

These document deliberate decisions in the shipped {target.slug} theme.
The vision reviewer should treat them as intent, not regressions.

- Hero `display` heading on `home` may consume up to 50% of viewport
  height when `composition.hero` is `type-led` or `poster-led`.
- Buttons may be slabs (no border-radius) when `composition.borders` is
  `hard`.
"""


# --------------------------------------------------------------------------- #
# Convenience IO                                                               #
# --------------------------------------------------------------------------- #
def read_target(path: Path) -> DesignTarget:
    data = json.loads(path.read_text(encoding="utf-8"))
    return DesignTarget.from_dict(data)


def write_target(target: DesignTarget, path: Path) -> None:
    path.write_text(
        json.dumps(target.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
