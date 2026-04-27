"""Shared WCAG contrast helpers for the Fifty monorepo tooling.

This module consolidates the handful of pieces that every
colour-checking script was otherwise reimplementing:

* hex ↔ RGB conversion, tolerating 3-digit shorthand and optional `#`
* WCAG 2.x relative luminance + contrast ratio
* parsing the `palette` array out of a theme.json (dict[slug → hex])
* resolving a CSS `var(--wp--preset--color--<slug>, var(...))` fallback
  chain to the first slug present in the palette, used by
  `check_hover_state_legibility` to read rules like
  `color: var(--accent, var(--contrast))` without crashing
* resolving a Gutenberg block's effective (textColor, backgroundColor)
  given the block's own JSON attributes PLUS any parent `wp:group`
  block that declared them first (the `wordmark-band__ledger` case —
  the child paragraph inherits from the coloured-group parent)
* picking the best-contrast palette slug against a given background,
  used by `autofix-contrast.py` to rewrite a failing `textColor`

The only non-helper in here is the tiny `hex_contrast(a, b)` shortcut
that takes two `#rrggbb` strings and returns the ratio — callers
shouldn't need to know the two-step `relative_luminance` dance.

WCAG constants intentionally NOT exported because callers should
phrase the floor they need in the context of what they're checking:
`3.0` for state changes, `4.5` for normal text, `7.0` for AAA.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

# ---- hex + luminance ---------------------------------------------------


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse a hex color to (r, g, b). Accepts `#abc`, `#abcdef`,
    `abc`, `abcdef`. Raises ValueError on any other shape.

    We don't accept `rgb(…)`, `hsl(…)`, named colors, or alpha channels
    — theme.json palettes in this repo are always 6-digit hex (enforced
    by `check_no_hex_in_templates` and schema validation), so any other
    shape hitting this parser is a bug upstream that we want to surface."""
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"Not a 6-digit hex color: {value!r}")
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError as exc:
        raise ValueError(f"Not a 6-digit hex color: {value!r}") from exc


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance. Per spec:
    L = 0.2126 R + 0.7152 G + 0.0722 B, with sRGB gamma unbaked."""
    def chan(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG 2.x contrast ratio between two hex colors. Symmetric —
    order of arguments doesn't matter for the result."""
    l1 = relative_luminance(hex_to_rgb(fg_hex))
    l2 = relative_luminance(hex_to_rgb(bg_hex))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# Alias for callers that prefer the shorter name.
hex_contrast = contrast_ratio


# ---- palette parsing ---------------------------------------------------


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?$")


def load_palette(theme_json_path: Path | str) -> dict[str, str]:
    """Load `settings.color.palette` from a theme.json file and return
    `{slug: hex}`. Non-hex palette entries are silently dropped —
    they're a hard-fail elsewhere (`check_no_hex_in_theme_json` /
    schema validation), and we don't want an unparseable entry to
    tank an otherwise-valid contrast check.

    Missing file / invalid JSON / no palette -> empty dict."""
    path = Path(theme_json_path)
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    palette_list = ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    out: dict[str, str] = {}
    for entry in palette_list:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        color = entry.get("color")
        if isinstance(slug, str) and isinstance(color, str) and _HEX_RE.match(color):
            out[slug] = color
    return out


# ---- CSS `var()` resolution -------------------------------------------


# Matches one `var(--wp--preset--color--<slug>)` segment. Used to pluck
# the ordered list of slugs out of a fallback chain like
# `var(--wp--preset--color--accent, var(--wp--preset--color--contrast))`.
_VAR_SLUG_RE = re.compile(r"var\(\s*--wp--preset--color--([a-z0-9-]+)")


def resolve_var_chain(
    value: str,
    palette: dict[str, str],
) -> tuple[str | None, str | None]:
    """Walk a CSS declaration right-hand-side, return (slug, hex) for
    the first `var(--wp--preset--color--<slug>)` whose slug is present
    in `palette`.

    Handles the WC-override pattern
        color:var(--wp--preset--color--accent,var(--wp--preset--color--contrast));
    which the old hover-check regex refused because it required a `)`
    immediately after the slug. The CSS cascade itself picks the FIRST
    var that resolves, so we return the first one whose slug is known;
    an unknown first slug falls through to the next one in the chain
    (which is exactly how browsers treat `var(--undefined, fallback)`).

    Returns (None, None) if no known slug is found."""
    if not value:
        return None, None
    for match in _VAR_SLUG_RE.finditer(value):
        slug = match.group(1)
        if slug in palette:
            return slug, palette[slug]
    # Last-ditch: grab the first slug regardless of palette presence,
    # so callers can at least log "bad slug" rather than silently drop.
    first = _VAR_SLUG_RE.search(value)
    if first:
        return first.group(1), None
    return None, None


# ---- block-attribute resolution ---------------------------------------


def resolve_block_colors(
    block_attrs: dict,
    palette: dict[str, str],
    *,
    inherited_text: str | None = None,
    inherited_bg: str | None = None,
) -> tuple[tuple[str | None, str | None], tuple[str | None, str | None]]:
    """Resolve (text_slug, text_hex), (bg_slug, bg_hex) for a single
    block's attributes, falling back to the inherited values from the
    nearest ancestor that declared them.

    Gutenberg-isms handled here:
      * `textColor` / `backgroundColor` carry the palette slug
        (e.g. "accent", "contrast") — no `var(…)` wrapper.
      * `style.color.text` / `style.color.background` carry raw hex for
        custom (non-palette) colors. We return the hex, but slug is None
        so callers can tell the difference.
      * When an attr isn't set, we inherit from the ancestor — that's
        the `.agave-wordmark-band__ledger` failure mode: the paragraph
        sets no color of its own, but the parent wp:group set
        textColor=base + backgroundColor=accent, and the resolved
        contrast (base on accent) fails.

    Returns ((text_slug, text_hex), (bg_slug, bg_hex)). Any piece can
    be None — the caller decides the policy for "no known color". A
    slug that isn't in the palette is returned with hex=None so the
    caller can distinguish "typo / custom name" from "no color at all"."""
    text_slug = block_attrs.get("textColor")
    text_hex: str | None = None
    if isinstance(text_slug, str):
        text_hex = palette.get(text_slug)
    else:
        text_slug = None

    # Raw hex style override wins over slug iff both are present.
    style = block_attrs.get("style") or {}
    color_block = style.get("color") or {}
    raw_text = color_block.get("text") if isinstance(color_block, dict) else None
    if isinstance(raw_text, str) and _HEX_RE.match(raw_text):
        text_slug = None
        text_hex = raw_text

    bg_slug = block_attrs.get("backgroundColor")
    bg_hex: str | None = None
    if isinstance(bg_slug, str):
        bg_hex = palette.get(bg_slug)
    else:
        bg_slug = None

    raw_bg = color_block.get("background") if isinstance(color_block, dict) else None
    if isinstance(raw_bg, str) and _HEX_RE.match(raw_bg):
        bg_slug = None
        bg_hex = raw_bg

    # Gradient support: `style.color.gradient` paints a background too
    # but defeats contrast reasoning (we'd have to pick the worst stop).
    # We treat it the same way the hover-check treats a non-palette bg
    # — skip. Callers look at bg_hex is None + bg_slug is None + the
    # `gradient` presence to decide.
    # For now: leave bg_hex/bg_slug alone; callers can read the raw
    # `gradient` key off the original attrs if they care.

    # Inherit from ancestor only when NOTHING local declared the slot.
    if text_slug is None and text_hex is None:
        text_hex = inherited_text
    if bg_slug is None and bg_hex is None:
        bg_hex = inherited_bg

    return (text_slug, text_hex), (bg_slug, bg_hex)


# ---- best-contrast slug picker ----------------------------------------


def best_text_slug(
    bg_hex: str,
    palette: dict[str, str],
    *,
    candidates: Iterable[str] = ("contrast", "base", "secondary", "tertiary"),
    min_ratio: float = 4.5,
) -> tuple[str, float] | None:
    """Pick the palette slug from `candidates` that has the highest
    contrast ratio against `bg_hex` and meets `min_ratio`. Returns
    `(slug, ratio)` on success, or None if nothing in the candidate
    list passes.

    The default candidate list is ordered by "most likely to be text":
    `contrast` is the intended dark ink for light themes, then `base`
    for dark themes that reverse out, then the secondary / tertiary
    mid-tones for muted text.

    We evaluate every candidate and return the winner by ratio (not
    by list order) so a palette where `contrast` happens to be softer
    than `secondary` still picks `secondary` if it wins — the point is
    to rescue a failing combo, not to preserve the candidate ordering."""
    best: tuple[str, float] | None = None
    for slug in candidates:
        hex_val = palette.get(slug)
        if not hex_val:
            continue
        try:
            ratio = contrast_ratio(hex_val, bg_hex)
        except ValueError:
            continue
        if ratio < min_ratio:
            continue
        if best is None or ratio > best[1]:
            best = (slug, ratio)
    return best


# ---- public WCAG floors (for callers that want named constants) -------

# State changes (hover/focus/active) relax to AA-Large because the
# state is transient and rarely long-form prose.
WCAG_AA_LARGE = 3.0
# Normal-weight body text against its background.
WCAG_AA_NORMAL = 4.5
# AAA bar for prose-heavy surfaces.
WCAG_AAA_NORMAL = 7.0
