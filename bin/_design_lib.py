"""Pure-python helpers for `bin/design.py` — spec validation, palette/font
mutation on theme.json, and brief generation.

Why this module exists
----------------------
`bin/design.py` is the deterministic spine of the "spec JSON -> theme" pipeline:
clone Obel, apply a JSON spec to `theme.json`, seed playground content, sync
the blueprint, run `bin/check.py`. Every step that can be expressed as a
pure data transform belongs here so it can be unit-tested without booting
Playground or shelling out to subprocesses.

The split is deliberate:
  * `_design_lib.py` (this file) — pure functions on dicts/strings, no I/O,
    no subprocess, except ``allow_non_miles_spec_tools()`` (one env var).
  * `design.py` — argparse + I/O orchestration. Calls into this module.

If you need to add a new design transform (e.g. swap shadow tokens, rewrite
the spacing scale), add a pure function here, unit-test it in
`tests/tools/test_design_lib.py`, then wire it into the appropriate phase
in `design.py`.

Spec contract
-------------
The spec is a JSON object. Required fields: `slug`, `name`. Everything else
is optional — anything not provided is left at the cloned source theme's
default. This is what lets the agent iterate: ship a minimal spec, run
design.py, eyeball the result, expand the spec, re-run.

Idempotency
-----------
Every transform is structural (operates on parsed JSON), not textual. Re-running
with the same spec produces zero diff. Re-running with a different spec
produces a diff scoped to exactly the slugs the spec mentions — sibling
slugs the spec doesn't touch are left alone.
"""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Slug pattern: lowercase letters, digits, hyphens, starting with a letter.
# Same regex `bin/clone.py` uses, kept in sync intentionally so a spec that
# validates here will clone successfully there.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,38}$")


def allow_non_miles_spec_tools() -> bool:
    """When false (default), CLIs refuse Anthropic-only spec shortcuts.

    Miles export + ``miles-ready.json`` (``--miles-artifacts`` / ``miles-bridge``),
    hand-authored ``--spec`` JSON, and deterministic ``concept-to-spec`` stay
    allowed. Set ``FIFTY_ALLOW_NON_MILES_SPEC=1`` to re-enable ``design.py
    --prompt``, manifest ``prompt`` rows, and ``concept-to-spec --llm``.
    """

    return os.environ.get("FIFTY_ALLOW_NON_MILES_SPEC", "").strip() == "1"


# Hex color: 3, 4, 6, or 8 digit forms (alpha allowed). Lowercase or upper.
HEX_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Color slugs that downstream tooling assumes exist. The spec doesn't have to
# provide all of them — anything missing stays at the clone source's value —
# but unknown slugs are still rejected so a typo ("primay") doesn't silently
# no-op. This list mirrors the palette every shipped theme actually uses
# (see obel/theme.json `settings.color.palette`); when adding a new slug,
# add it both here and to the source theme.
KNOWN_COLOR_SLUGS = frozenset(
    {
        "base",
        "surface",
        "subtle",
        "muted",
        "border",
        "tertiary",
        "secondary",
        "contrast",
        "primary",
        "primary-hover",
        "accent",
        "accent-soft",
        "success",
        "warning",
        "error",
        "info",
    }
)

# Font slugs the source theme exposes. `display` and `sans` are the two
# slots an agent realistically wants to swap; `serif` and `mono` exist
# but rarely need per-theme overrides. Same "unknown slug = error" policy
# as the palette so typos surface immediately.
KNOWN_FONT_SLUGS = frozenset({"sans", "serif", "mono", "display"})

# The spec voice keyword drives the per-theme `// === BEGIN wc microcopy ===`
# block in `functions.php`. We don't generate that block (it's intricate WP
# hook work that wants LLM judgment), but we record the keyword in `BRIEF.md`
# so the agent's next-action prompt has the design intent in front of it.


@dataclass
class SpecError:
    """One validation problem with the spec, plus a JSON-pointer-ish path."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"  - {self.path}: {self.message}"


@dataclass
class ValidatedSpec:
    """A spec that passed `validate_spec`. Fields are normalized (lowercased
    slug, lowercased hex). Optional sections that weren't provided default
    to empty dicts/lists so callers can `for k, v in spec.palette.items()`
    without a None check."""

    slug: str
    name: str
    tagline: str = ""
    voice: str = ""
    source: str = "obel"
    palette: dict[str, str] = field(default_factory=dict)
    fonts: dict[str, dict[str, Any]] = field(default_factory=dict)
    layout_hints: list[str] = field(default_factory=list)


def example_spec() -> dict[str, Any]:
    """Return a fully-populated example spec the agent can crib from.

    Doubled as `bin/design.py --print-example-spec` so an agent can pipe it
    to a file (`bin/design.py --print-example-spec > tmp/midcentury.json`),
    edit, then run `bin/design.py --spec tmp/midcentury.json`."""
    return {
        "slug": "midcentury",
        "name": "Midcentury",
        "tagline": "Postwar shop, modern goods.",
        "voice": (
            "warm midcentury department store: 'parcel' for order, "
            "'register' for checkout, 'kindly' on prompts, '·' as the "
            "required-field marker"
        ),
        "source": "obel",
        "palette": {
            "base": "#F5EFE6",
            "surface": "#FFFFFF",
            "subtle": "#EBE3D6",
            "muted": "#D9CDB8",
            "border": "#C9BBA3",
            "tertiary": "#7A6F5C",
            "secondary": "#5C5343",
            "contrast": "#1F1B16",
            "primary": "#1F1B16",
            "primary-hover": "#403828",
            "accent": "#D87E3A",
            "accent-soft": "#F2D8B8",
        },
        "fonts": {
            "display": {
                "family": "Bricolage Grotesque",
                "fallback": "Helvetica, Arial, sans-serif",
                "google_font": True,
                "weights": [400, 700],
            },
            "sans": {
                "family": "Inter",
                "fallback": "-apple-system, BlinkMacSystemFont, sans-serif",
                "google_font": True,
                "weights": [400, 600],
            },
        },
        "layout_hints": [
            "asymmetric hero with offset product image",
            "tiled 3x2 category grid",
            "full-bleed top announcement strip",
        ],
    }


def validate_spec(raw: Any) -> tuple[list[SpecError], ValidatedSpec | None]:
    """Validate a parsed-JSON spec dict. Returns `(errors, spec_or_None)`.

    On success: `errors` is empty and the second element is a `ValidatedSpec`.
    On failure: `errors` is non-empty and the second element is `None`.

    The validator is strict on shape (typos in known fields fail loudly) and
    lenient on completeness (every section is optional except `slug`/`name`).
    Unknown top-level keys are rejected so spec drift surfaces here, not as
    a silent no-op three phases later.
    """
    errors: list[SpecError] = []

    if not isinstance(raw, dict):
        errors.append(SpecError("$", f"spec must be a JSON object, got {type(raw).__name__}"))
        return errors, None

    allowed_top = {"slug", "name", "tagline", "voice", "source", "palette", "fonts", "layout_hints"}
    unknown = set(raw.keys()) - allowed_top
    for k in sorted(unknown):
        errors.append(SpecError(f"$.{k}", f"unknown top-level key (allowed: {sorted(allowed_top)})"))

    slug = raw.get("slug")
    if not isinstance(slug, str) or not SLUG_PATTERN.match(slug.lower()):
        errors.append(
            SpecError(
                "$.slug",
                "must be a lowercase string of letters/digits/hyphens, starting with a letter, 2-39 chars",
            )
        )
        slug = ""
    else:
        slug = slug.lower()

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(SpecError("$.name", "must be a non-empty string"))
        name = ""

    tagline = raw.get("tagline", "")
    if not isinstance(tagline, str):
        errors.append(SpecError("$.tagline", f"must be a string, got {type(tagline).__name__}"))
        tagline = ""

    voice = raw.get("voice", "")
    if not isinstance(voice, str):
        errors.append(SpecError("$.voice", f"must be a string, got {type(voice).__name__}"))
        voice = ""

    source = raw.get("source", "obel")
    if not isinstance(source, str) or not SLUG_PATTERN.match(source.lower()):
        errors.append(SpecError("$.source", "must be a valid theme slug (lowercase, hyphenated)"))
        source = "obel"
    else:
        source = source.lower()

    palette: dict[str, str] = {}
    palette_raw = raw.get("palette", {})
    if not isinstance(palette_raw, dict):
        errors.append(SpecError("$.palette", f"must be an object, got {type(palette_raw).__name__}"))
    else:
        for color_slug, color_value in palette_raw.items():
            ptr = f"$.palette.{color_slug}"
            if color_slug not in KNOWN_COLOR_SLUGS:
                errors.append(
                    SpecError(
                        ptr,
                        f"unknown color slug (allowed: {sorted(KNOWN_COLOR_SLUGS)})",
                    )
                )
                continue
            if not isinstance(color_value, str) or not HEX_PATTERN.match(color_value):
                errors.append(SpecError(ptr, "must be a hex color like #RRGGBB or #RGB"))
                continue
            palette[color_slug] = color_value.lower() if len(color_value) <= 7 else color_value

    fonts: dict[str, dict[str, Any]] = {}
    fonts_raw = raw.get("fonts", {})
    if not isinstance(fonts_raw, dict):
        errors.append(SpecError("$.fonts", f"must be an object, got {type(fonts_raw).__name__}"))
    else:
        for font_slug, font_def in fonts_raw.items():
            ptr = f"$.fonts.{font_slug}"
            if font_slug not in KNOWN_FONT_SLUGS:
                errors.append(
                    SpecError(
                        ptr,
                        f"unknown font slug (allowed: {sorted(KNOWN_FONT_SLUGS)})",
                    )
                )
                continue
            if not isinstance(font_def, dict):
                errors.append(SpecError(ptr, "must be an object with `family`, `fallback`, etc."))
                continue
            f_errors, normalized = _validate_font_def(ptr, font_def)
            errors.extend(f_errors)
            if normalized is not None:
                fonts[font_slug] = normalized

    layout_hints: list[str] = []
    hints_raw = raw.get("layout_hints", [])
    if not isinstance(hints_raw, list):
        errors.append(SpecError("$.layout_hints", "must be a list of strings"))
    else:
        for i, hint in enumerate(hints_raw):
            if not isinstance(hint, str):
                errors.append(SpecError(f"$.layout_hints[{i}]", "must be a string"))
                continue
            layout_hints.append(hint)

    if errors:
        return errors, None

    return [], ValidatedSpec(
        slug=slug,
        name=name,
        tagline=tagline,
        voice=voice,
        source=source,
        palette=palette,
        fonts=fonts,
        layout_hints=layout_hints,
    )


def _hex_luminance(hex_color: str) -> float | None:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return None
    try:
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None

    def _linearize(channel: float) -> float:
        return (
            channel / 12.92
            if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
        )

    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def _hex_contrast(hex_a: str, hex_b: str) -> float | None:
    lum_a = _hex_luminance(hex_a)
    lum_b = _hex_luminance(hex_b)
    if lum_a is None or lum_b is None:
        return None
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def validate_generation_safety(spec: ValidatedSpec) -> list[SpecError]:
    """Cheap deterministic rules that prevent known factory mistakes.

    `validate_spec` only checks shape. This pass checks values that are
    technically valid JSON but known to produce broken generated themes.
    Keep it pure and fast: no filesystem, no subprocess, no fleet scan.
    """
    errors: list[SpecError] = []
    palette = spec.palette

    base = palette.get("base")
    contrast = palette.get("contrast")
    if base and contrast:
        ratio = _hex_contrast(base, contrast)
        if ratio is not None and ratio < 4.5:
            errors.append(
                SpecError(
                    "$.palette.contrast",
                    f"must contrast with base at >= 4.5:1 for body text (got {ratio:.2f}:1)",
                )
            )

    primary = palette.get("primary")
    if base and primary:
        ratio = _hex_contrast(base, primary)
        if ratio is not None and ratio < 3.0:
            errors.append(
                SpecError(
                    "$.palette.primary",
                    f"must contrast with base at >= 3.0:1 for generated hover/button states (got {ratio:.2f}:1)",
                )
            )

    if spec.source == spec.slug:
        errors.append(
            SpecError(
                "$.source",
                "must name an existing source theme different from the generated slug",
            )
        )

    return errors


def _validate_font_def(ptr: str, raw: dict[str, Any]) -> tuple[list[SpecError], dict[str, Any] | None]:
    """Validate one font slug's spec entry. See `example_spec()` for shape."""
    errors: list[SpecError] = []
    allowed = {"family", "fallback", "google_font", "weights"}
    unknown = set(raw.keys()) - allowed
    for k in sorted(unknown):
        errors.append(SpecError(f"{ptr}.{k}", f"unknown font key (allowed: {sorted(allowed)})"))

    family = raw.get("family")
    if not isinstance(family, str) or not family.strip():
        errors.append(SpecError(f"{ptr}.family", "must be a non-empty string"))
        family = ""

    fallback = raw.get("fallback", "")
    if not isinstance(fallback, str):
        errors.append(SpecError(f"{ptr}.fallback", "must be a string (CSS family stack)"))
        fallback = ""

    google_font = raw.get("google_font", False)
    if not isinstance(google_font, bool):
        errors.append(SpecError(f"{ptr}.google_font", "must be true/false"))
        google_font = False

    weights_raw = raw.get("weights", [400])
    weights: list[int] = []
    if not isinstance(weights_raw, list):
        errors.append(SpecError(f"{ptr}.weights", "must be a list of integers (e.g. [400, 700])"))
    else:
        for i, w in enumerate(weights_raw):
            if not isinstance(w, int) or w < 100 or w > 900 or w % 100 != 0:
                errors.append(
                    SpecError(
                        f"{ptr}.weights[{i}]",
                        f"must be a multiple of 100 between 100 and 900, got {w!r}",
                    )
                )
                continue
            weights.append(w)
        if not weights:
            weights = [400]

    if errors:
        return errors, None
    return [], {
        "family": family,
        "fallback": fallback,
        "google_font": google_font,
        "weights": weights,
    }


def apply_palette(theme_json: dict[str, Any], palette: dict[str, str]) -> dict[str, Any]:
    """Mutate `theme_json` in place: for every (slug, hex) in `palette`, find
    the matching entry in `settings.color.palette` and update its `color`.

    Slugs in the spec that the source theme doesn't already define are
    appended as new palette entries with a Title-Case display name. This is
    the path for adding a new color (e.g. an "ink" slug a variant wants).
    Slugs the spec doesn't mention are left untouched.

    Returns the same dict for chaining; the in-place mutation is the
    intended contract (callers re-serialize once at the end).
    """
    settings = theme_json.setdefault("settings", {})
    color_section = settings.setdefault("color", {})
    entries = color_section.setdefault("palette", [])

    by_slug = {entry.get("slug"): entry for entry in entries if isinstance(entry, dict)}
    for slug, hex_value in palette.items():
        if slug in by_slug:
            by_slug[slug]["color"] = hex_value
        else:
            entries.append(
                {
                    "slug": slug,
                    "name": _title_case_slug(slug),
                    "color": hex_value,
                }
            )
    return theme_json


def apply_fonts(theme_json: dict[str, Any], fonts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Mutate `theme_json` in place: rewrite `settings.typography.fontFamilies`
    entries for every (slug, font_def) the spec provides.

    For each entry:
      * `fontFamily` becomes `"<family>", <fallback>` (the family is
        wrapped in double quotes only if it contains spaces — single-word
        Google fonts like "Inter" stay bare).
      * If `google_font: true`, a `fontFace` array is added with one entry
        per requested weight, pointing at `file:./assets/fonts/<slug>-<wt>.woff2`.
        The agent (or a future helper script) is responsible for actually
        dropping the .woff2 files at those paths — see `BRIEF.md` for
        instructions emitted by `make_brief()`.
      * If `google_font: false`, no `fontFace` is set (the family is
        assumed to be a system stack the spec is just renaming).

    Slugs the spec doesn't mention are left untouched.
    """
    settings = theme_json.setdefault("settings", {})
    typography = settings.setdefault("typography", {})
    families = typography.setdefault("fontFamilies", [])

    by_slug = {entry.get("slug"): entry for entry in families if isinstance(entry, dict)}

    for slug, font_def in fonts.items():
        family = font_def["family"]
        fallback = font_def.get("fallback", "")
        family_token = f'"{family}"' if " " in family else family
        font_family = family_token if not fallback else f"{family_token}, {fallback}"

        if slug in by_slug:
            entry = by_slug[slug]
        else:
            entry = {"slug": slug, "name": _title_case_slug(slug)}
            families.append(entry)
            by_slug[slug] = entry

        entry["fontFamily"] = font_family

        if font_def.get("google_font"):
            entry["fontFace"] = [
                {
                    "fontFamily": family,
                    "fontWeight": str(weight),
                    "fontStyle": "normal",
                    "fontDisplay": "swap",
                    "src": [f"file:./assets/fonts/{slug}-{weight}.woff2"],
                }
                for weight in font_def["weights"]
            ]
        elif "fontFace" in entry:
            del entry["fontFace"]

    return theme_json


TOKEN_PATCH_KEYS = frozenset(
    {
        "schema",
        "spacing_sizes",
        "shadow_presets",
        "custom_radius",
        "custom_border_width",
        "styles_css_append",
    }
)


def _replace_or_append_by_slug(
    entries: list[Any],
    *,
    slug: str,
    field: str,
    value: str,
    name: str | None = None,
) -> None:
    for entry in entries:
        if isinstance(entry, dict) and entry.get("slug") == slug:
            entry[field] = value
            return
    entries.append(
        {
            "slug": slug,
            "name": name or _title_case_slug(slug),
            field: value,
        }
    )


def apply_token_patches(theme_json: dict[str, Any], patches: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``theme_json`` with design-token patches applied.

    The input shape is intentionally narrow because this is fed by an LLM
    during the design pipeline. The model may tune spacing sizes, shadow
    presets, radius tokens, border-width tokens, and append top-level
    ``styles.css`` only. Palette, fonts, templates, and arbitrary theme.json
    paths stay out of bounds.
    """

    unknown = set(patches) - TOKEN_PATCH_KEYS
    if unknown:
        raise ValueError(f"unknown token patch key(s): {', '.join(sorted(unknown))}")

    out = copy.deepcopy(theme_json)
    settings = out.setdefault("settings", {})

    spacing_sizes = patches.get("spacing_sizes")
    if spacing_sizes is not None:
        if not isinstance(spacing_sizes, list):
            raise ValueError("spacing_sizes must be a list")
        spacing = settings.setdefault("spacing", {})
        entries = spacing.setdefault("spacingSizes", [])
        if not isinstance(entries, list):
            raise ValueError("settings.spacing.spacingSizes must be a list")
        for item in spacing_sizes:
            if not isinstance(item, dict):
                raise ValueError("spacing_sizes entries must be objects")
            slug = str(item.get("slug") or "").strip()
            size = str(item.get("size") or "").strip()
            if not slug or not size:
                raise ValueError("spacing_sizes entries require slug and size")
            name = str(item.get("name") or "") or None
            _replace_or_append_by_slug(entries, slug=slug, field="size", value=size, name=name)

    shadow_presets = patches.get("shadow_presets")
    if shadow_presets is not None:
        if not isinstance(shadow_presets, list):
            raise ValueError("shadow_presets must be a list")
        shadow = settings.setdefault("shadow", {})
        entries = shadow.setdefault("presets", [])
        if not isinstance(entries, list):
            raise ValueError("settings.shadow.presets must be a list")
        for item in shadow_presets:
            if not isinstance(item, dict):
                raise ValueError("shadow_presets entries must be objects")
            slug = str(item.get("slug") or "").strip()
            value = str(item.get("shadow") or "").strip()
            if not slug or not value:
                raise ValueError("shadow_presets entries require slug and shadow")
            name = str(item.get("name") or "") or None
            _replace_or_append_by_slug(entries, slug=slug, field="shadow", value=value, name=name)

    custom_radius = patches.get("custom_radius")
    if custom_radius is not None:
        if not isinstance(custom_radius, dict):
            raise ValueError("custom_radius must be an object")
        custom = settings.setdefault("custom", {})
        radius = custom.setdefault("radius", {})
        if not isinstance(radius, dict):
            raise ValueError("settings.custom.radius must be an object")
        for slug, value in custom_radius.items():
            radius[str(slug)] = str(value)

    custom_border_width = patches.get("custom_border_width")
    if custom_border_width is not None:
        if not isinstance(custom_border_width, dict):
            raise ValueError("custom_border_width must be an object")
        custom = settings.setdefault("custom", {})
        border = custom.setdefault("border", {})
        if not isinstance(border, dict):
            raise ValueError("settings.custom.border must be an object")
        width = border.setdefault("width", {})
        if not isinstance(width, dict):
            raise ValueError("settings.custom.border.width must be an object")
        for slug, value in custom_border_width.items():
            width[str(slug)] = str(value)

    styles_css_append = patches.get("styles_css_append")
    if styles_css_append is not None:
        if not isinstance(styles_css_append, str):
            raise ValueError("styles_css_append must be a string")
        snippet = styles_css_append.strip()
        if snippet:
            styles = out.setdefault("styles", {})
            css = str(styles.get("css") or "")
            if snippet not in css:
                styles["css"] = (css.rstrip() + "\n\n" + snippet + "\n").lstrip()

    return out


def make_brief(spec: ValidatedSpec, theme_root: Path) -> str:
    """Return the contents of `BRIEF.md` — a markdown file dropped at the
    new theme's root that tells the next agent what to do after `design.py`
    finishes.

    The brief is the handoff between the deterministic phase (clone + token
    swap) and the judgment phase (microcopy voice, structural restyle,
    product photography). It records the spec inputs verbatim so the agent
    has the design intent in front of it without re-reading the spec file.

    When `<theme_root>/design-target.json` exists (target-driven flow), the
    palette section reflects the EXPANDED 16-slug palette from the target,
    not the partial spec palette — otherwise the brief lies about what
    `theme.json` actually paints.
    """
    target_palette: dict[str, str] | None = None
    target_source_method: str | None = None
    target_accent_evidence: str | None = None
    target_path = theme_root / "design-target.json"
    if target_path.is_file():
        try:
            import _design_target_lib as _dt_lib

            target = _dt_lib.read_target(target_path)
            target_palette = _dt_lib.expand_palette(target)
            target_source_method = (target.source or {}).get("method")
            target_accent_evidence = (target.source or {}).get("accent_evidence")
        except Exception:
            target_palette = None

    lines: list[str] = []
    lines.append(f"# {spec.name} — design brief")
    lines.append("")
    lines.append(
        f"This file was emitted by `bin/design.py` after cloning `{spec.source}` -> "
        f"`{spec.slug}` and applying the spec's palette + font choices. Read it before "
        "you do anything else; it captures the design intent the spec encoded so you "
        "can write the per-theme microcopy block, restyle the templates that need it, "
        "and brief any product photography in the same voice."
    )
    lines.append("")

    if spec.tagline:
        lines.append("## Tagline")
        lines.append("")
        lines.append(f"> {spec.tagline}")
        lines.append("")

    if spec.voice:
        lines.append("## Voice")
        lines.append("")
        lines.append(spec.voice)
        lines.append("")
        lines.append(
            "Write this voice into the `// === BEGIN wc microcopy ===` block in "
            f"`{spec.slug}/functions.php`. Every theme's microcopy must read distinctly "
            "from every other theme's; `bin/check.py check_wc_microcopy_distinct_across_themes` "
            "enforces it. Crib the structure from any sibling theme's microcopy block, then "
            "rewrite every literal string in this voice."
        )
        lines.append("")

    if spec.layout_hints:
        lines.append("## Layout hints")
        lines.append("")
        for hint in spec.layout_hints:
            lines.append(f"- {hint}")
        lines.append("")
        lines.append(
            "These hints came from the spec. Restructure `templates/front-page.html` and "
            "any sibling templates whose composition needs to change. Token swaps alone "
            "are never enough; see `.claude/skills/build-block-theme-variant/SKILL.md` step 6."
        )
        lines.append("")

    palette_for_brief = target_palette if target_palette else spec.palette
    if palette_for_brief:
        lines.append("## Palette applied")
        lines.append("")
        if target_palette:
            method_note = (
                "via the deterministic `bin/extract-design-target.py` + "
                "`bin/render-design-target.py` chain"
                if target_source_method == "deterministic-from-meta"
                else "after the vision-from-mockup refinement pass"
                if target_source_method == "vision-from-mockup"
                else "from `design-target.json`"
            )
            lines.append(
                f"_The 16-slug palette below was expanded from the brand hexes_ "
                f"_{method_note}; it matches what `theme.json` actually paints._"
            )
            lines.append("")
            if target_accent_evidence:
                lines.append("**Why accent landed where it did**:")
                lines.append("")
                lines.append(f"> {target_accent_evidence}")
                lines.append("")
        lines.append("| Slug | Hex |")
        lines.append("|------|-----|")
        for slug in sorted(palette_for_brief):
            lines.append(f"| `{slug}` | `{palette_for_brief[slug]}` |")
        lines.append("")
        lines.append(
            "Run `python3 bin/check-contrast.py` (if it exists in this repo) before locking "
            "the palette. Verify every pairing in the WCAG table at "
            "`.claude/skills/build-block-theme-variant/SKILL.md` step 5."
        )
        lines.append("")

    if spec.fonts:
        lines.append("## Fonts registered")
        lines.append("")
        google_fonts = [(s, f) for s, f in spec.fonts.items() if f.get("google_font")]
        if google_fonts:
            lines.append("**Google Fonts to download as `.woff2`** (the `fontFace` entries already")
            lines.append(f"point at `{spec.slug}/assets/fonts/<slug>-<weight>.woff2` — drop the files there):")
            lines.append("")
            for slug, font in google_fonts:
                weights = ", ".join(str(w) for w in font["weights"])
                lines.append(f"- `{font['family']}` ({slug}, weights {weights})")
            lines.append("")
            lines.append(
                "Use https://gwfh.mranftl.com/fonts to pull the official `.woff2` files (one per "
                "weight + style). Then run `python3 bin/check.py check_no_remote_fonts` to confirm "
                "no remote URLs slipped in."
            )
            lines.append("")
        system_fonts = [(s, f) for s, f in spec.fonts.items() if not f.get("google_font")]
        if system_fonts:
            lines.append("**System-stack font slots** (no asset work needed):")
            lines.append("")
            for slug, font in system_fonts:
                lines.append(f"- `{slug}`: {font['family']}")
            lines.append("")

    lines.append("## Next steps")
    lines.append("")
    lines.append("1. Open `theme.json` and confirm the palette / font slots match your intent.")
    lines.append(f"2. Drop product photographs as `{spec.slug}/playground/images/product-wo-*.jpg` ")
    lines.append("   (one per product). Generate them so they read as this theme's voice;")
    lines.append("   `bin/check.py check_product_images_unique_across_themes` will reject any")
    lines.append("   byte-shared with a sibling theme.")
    lines.append("3. Edit the `// === BEGIN wc microcopy ===` block in `functions.php` to match")
    lines.append("   the voice above.")
    lines.append("4. Restructure `templates/front-page.html` per the layout hints; every theme's")
    lines.append("   homepage must be structurally distinct (`check_front_page_unique_layout`).")
    lines.append(f"5. Re-shoot screenshot.png: `python3 bin/build-theme-screenshots.py {spec.slug}`.")
    lines.append(f"6. Snap baseline: `python3 bin/snap.py shoot {spec.slug} && \\")
    lines.append(f"   python3 bin/snap.py baseline {spec.slug}`.")
    lines.append(f"7. Verify: `python3 bin/check.py {spec.slug} --quick` — fix every failure before")
    lines.append("   committing. Don't suppress with `--no-verify`.")
    lines.append("8. Commit + push everything (theme dir, blueprint, content, baselines).")
    lines.append("")
    lines.append("`BRIEF.md` is committed alongside the theme so future agents (and the next")
    lines.append("human reading the repo a year from now) can see the design intent that")
    lines.append("seeded the theme without spelunking the original prompt.")
    lines.append("")
    lines.append(f"_Brief auto-generated for {theme_root.name} by `bin/design.py`._")
    lines.append("")
    return "\n".join(lines)


def _title_case_slug(slug: str) -> str:
    """`primary-hover` -> `Primary Hover`. Used for palette/font display names."""
    return " ".join(word.capitalize() for word in slug.split("-"))


def serialize_theme_json(theme_json: dict[str, Any]) -> str:
    """JSON-serialize `theme_json` with the tab indentation the rest of the
    monorepo uses, plus a trailing newline.

    `theme.json` files in this repo are tab-indented (see any sibling theme).
    Preserving that on round-trip keeps the post-design diff scoped to actual
    semantic changes instead of a full reformat.
    """
    return json.dumps(theme_json, indent="\t", ensure_ascii=False) + "\n"
