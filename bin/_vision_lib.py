"""Pure-python wrapper around the Anthropic Messages API for the smart
design agent's vision reviewer.

Why this module exists
----------------------
[`bin/snap-vision-review.py`](snap-vision-review.py) needs to:

  1. Send a screenshot + a prompt to Claude (a multimodal model)
  2. Get back structured JSON describing visual design problems
  3. Track every API call's cost and refuse to run if today's spend
     exceeds a configurable budget
  4. Be runnable without an API key for testing (`--dry-run`)

We could pull in the official `anthropic` SDK as a pip dep. We deliberately
do not: the rest of the repo's tooling (`bin/snap.py`, `bin/check.py`,
`bin/build-redirects.py`) is Python-stdlib-only by convention. Adding a new
runtime dep changes the deploy story for every CI job. The Anthropic
Messages API is one POST endpoint that takes JSON and returns JSON, so
`urllib.request` is sufficient.

The split mirrors `bin/_design_lib.py`:
  * `_vision_lib.py` (this file) — pure functions on dicts/strings + one
    thin HTTP wrapper. Trivial to test in isolation.
  * `snap-vision-review.py` — argparse + I/O orchestration. Calls into
    this module.

Cost discipline
---------------
Vision tokens are not free. A single 1280×800 PNG bills ~1500 input image
tokens. Five themes × 11 routes × 4 viewports × ~$0.015 per call lands at
~$3 for a full --all sweep with current Claude Sonnet pricing.

The discipline this module enforces:
  1. Every successful call appends a line to `tmp/vision-spend.jsonl`
     with timestamp, model, input/output tokens, and estimated USD cost.
  2. `today_spend_usd()` sums today's lines (UTC day boundary). Caller
     can refuse to start a new call if spend >= `FIFTY_VISION_DAILY_BUDGET`
     (default $20).
  3. `--dry-run` mode in the caller bypasses the API entirely — useful
     for prompt iteration, fixture validation, and CI smoke tests on
     branches without secrets.

Retry policy
------------
Anthropic's API returns 429 (rate limit) when the request exceeds a
requests-per-minute, input-tokens-per-minute, output-tokens-per-minute, or
acceleration limit. 429 responses include a `retry-after` header; retrying
before that window expires will usually fail again. We respect
`retry-after` when present and fall back to exponential backoff for other
transient failures (529 / 5xx). 4xx other than 429 fails fast.

Schema contract
---------------
The vision reviewer asks the model to return JSON with this shape:

    {
      "findings": [
        {
          "kind": "vision:typography-overpowered",
          "severity": "error" | "warn" | "info",
          "message": "<= 280 chars human-readable description",
          "bbox": {"x": int, "y": int, "w": int, "h": int} | null,
          "rationale": "<= 600 chars explaining the violation against
                        either the generic rubric or the theme's
                        design-intent.md",
          "remedy_hint": "<= 200 chars actionable fix direction" | null
        },
        ...
      ]
    }

`parse_findings_response()` validates that shape and returns a normalised
list. Anything that doesn't fit the schema is dropped with a warning so a
flaky model response can't poison `findings.json`.
"""
from __future__ import annotations

import base64
import datetime as dt
import email.utils
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# `datetime.UTC` is the modern alias (Python 3.11+) and what ruff's
# UP017 insists on under our py312 lint target. The project's
# documented minimum runtime in `pyproject.toml` is `python>=3.9`,
# where the alias does not exist. Resolve once at import time so the
# rest of the file can use `UTC` without scattering version checks.
UTC = getattr(dt, "UTC", dt.timezone.utc)  # noqa: UP017


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Default model. Overridable via FIFTY_VISION_MODEL env var. The default is
# pinned at a Sonnet snapshot known to be reliable for image+JSON; bumping
# the default model invalidates every cached fingerprint by design (the
# fingerprint includes the model id), so you'll re-burn budget once.
DEFAULT_MODEL = os.environ.get("FIFTY_VISION_MODEL", "claude-sonnet-4-6")

# Pricing in USD per million tokens. Updated 2026-Q2 from Anthropic public
# pricing. Override via FIFTY_VISION_PRICE_INPUT / FIFTY_VISION_PRICE_OUTPUT.
# Image tokens are billed as input tokens at the same rate; ~1500 tokens per
# 1280x800 PNG is the empirical observation.
DEFAULT_PRICE_INPUT_PER_MTOK = float(os.environ.get("FIFTY_VISION_PRICE_INPUT", "3.00"))
DEFAULT_PRICE_OUTPUT_PER_MTOK = float(os.environ.get("FIFTY_VISION_PRICE_OUTPUT", "15.00"))

# Daily spend cap. Hard fail (raise BudgetExceededError) above this.
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("FIFTY_VISION_DAILY_BUDGET", "20.00"))

# Anthropic vision API limits (as of 2026-Q2):
#   * 5 MB per image after base64 encoding (raw bytes must therefore stay
#     under ~3.93 MB; we keep a safety margin and target 3.7 MB).
#   * Neither dimension may exceed 8000 pixels.
# Full-page screenshots produced by `bin/snap.py` regularly trip both
# limits (mobile heights of 12000-15000 px, desktop PNGs of 6-11 MB on
# image-heavy themes). `_prepare_image_for_api` resizes / recompresses
# transparently so callers can hand `review_image` raw `tmp/snaps/` PNGs
# without thinking about it.
MAX_IMAGE_DIMENSION_PX = 7500
MAX_IMAGE_BYTES = 3_700_000

# Cost ledger location. Per-call append-only JSONL.
DEFAULT_LEDGER_PATH = Path("tmp/vision-spend.jsonl")

# Prompt version. Bump when the system prompt or schema changes; this
# becomes part of the per-PNG cache fingerprint so a prompt iteration
# invalidates all cached findings (it must — the model would have produced
# different findings).
PROMPT_VERSION = "v1.1.0"

# Retry policy
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})
RATE_LIMIT_HEADER_PREFIXES = (
    "retry-after",
    "anthropic-ratelimit-",
    "anthropic-priority-",
    "anthropic-fast-",
)

# Output token cap. The findings response is bounded — even a very busy
# screenshot maps to at most ~10 findings of ~100 tokens each. Cap protects
# against the model writing a novel.
DEFAULT_MAX_OUTPUT_TOKENS = 2000

# Allowed finding kinds. A response that names something outside this set is
# dropped with a warning. Keep in sync with `vision:*` entries in
# `bin/finding_remedies.json`.
ALLOWED_FINDING_KINDS = frozenset(
    {
        # Aesthetic / design-judgment findings (v1.0 kinds).
        "vision:typography-overpowered",
        "vision:hierarchy-flat",
        "vision:content-orphan",
        "vision:cta-buried",
        "vision:alignment-off",
        "vision:whitespace-imbalance",
        "vision:photography-mismatch",
        "vision:color-clash",
        "vision:brand-violation",
        "vision:mockup-divergent",
        # Functional-breakage findings (v1.1 kinds). Added after the
        # Foundry /my-account/ broken-login-grid shipped to demo with
        # zero vision complaints: the old rubric explicitly disclaimed
        # "broken HTML / rendering bugs," so the reviewer graded a
        # 228px-wide content column inside a 1280px viewport as
        # "aesthetic fine." These kinds fire only on desktop + wide
        # viewports of WooCommerce chrome routes (my-account, cart-*,
        # checkout-*) where collapsed/rebroken-layout regressions
        # actually matter and are visually unambiguous.
        "vision:layout-collapsed-at-desktop",
        "vision:menu-without-content-panel",
        "vision:primary-button-missing-or-unclickable",
        "vision:container-narrower-than-viewport-wide",
        "vision:empty-state-instead-of-content",
    }
)

# Phase-split for the two-step `design.py build` / `design.py dress`
# pipeline. `build` never calls vision (step 1 is deterministic-only),
# so the split only matters inside `dress`: its vision-review pass uses
# phase=content so the reviewer stays focused on the catalogue-fit
# lens instead of re-raising structural complaints that `check --phase
# structural` already covered in step 1.
VISION_PHASE_STRUCTURAL = "structural"
VISION_PHASE_CONTENT = "content"
VISION_PHASE_ALL = "all"
VISION_PHASES = (VISION_PHASE_STRUCTURAL, VISION_PHASE_CONTENT, VISION_PHASE_ALL)

# Content-fit kinds: each of these grades the demo catalogue against
# the theme's design-intent.md (does the photo/palette/voice match?).
# Everything else in ALLOWED_FINDING_KINDS is structural.
_CONTENT_VISION_KINDS = frozenset(
    {
        "vision:photography-mismatch",
        "vision:color-clash",
        "vision:brand-violation",
        "vision:mockup-divergent",
    }
)
_STRUCTURAL_VISION_KINDS = ALLOWED_FINDING_KINDS - _CONTENT_VISION_KINDS


def kinds_for_phase(phase: str) -> frozenset[str]:
    """Return the allowed-kind set for a given vision phase.

    `all` (the default) returns the full ALLOWED_FINDING_KINDS; the two
    split phases return the content or structural subset. Unknown
    phases fall back to ALL so callers that accidentally pass an
    empty/garbage string never silently drop everything.
    """
    if phase == VISION_PHASE_CONTENT:
        return _CONTENT_VISION_KINDS
    if phase == VISION_PHASE_STRUCTURAL:
        return _STRUCTURAL_VISION_KINDS
    return ALLOWED_FINDING_KINDS

# Route prefixes where the functional-breakage kinds above are
# meaningful. On non-WC routes (home, shop, journal, PDP) the review
# should stick to the aesthetic kinds so we don't chase shadows on
# routes that don't have a well-defined "content panel" concept.
FUNCTIONAL_BREAKAGE_ROUTE_PREFIXES = (
    "my-account",
    "cart-",
    "checkout-",
    "order-received",
)
# Viewports where the functional-breakage kinds above are meaningful.
# Mobile (375px) legitimately collapses the WC 2-column grids to a
# single column via media queries; flagging that would produce ~100%
# false-positive rate. Tablet (782px+) is the first viewport where
# the sidebar layout is expected.
FUNCTIONAL_BREAKAGE_VIEWPORTS = ("desktop", "wide")


def should_flag_functional_breakage(route: str, viewport: str) -> bool:
    """Return True if the given (route, viewport) is in scope for the
    functional-breakage kinds.

    Kept as a module function (rather than inlined) so the same
    predicate is used by both the prompt builder and any downstream
    severity-filter logic.
    """
    if viewport not in FUNCTIONAL_BREAKAGE_VIEWPORTS:
        return False
    return any(route.startswith(p) for p in FUNCTIONAL_BREAKAGE_ROUTE_PREFIXES)

ALLOWED_SEVERITIES = ("error", "warn", "info")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VisionError(Exception):
    """Base class for any user-actionable failure in this module."""


class BudgetExceededError(VisionError):
    """Raised when a call would push today's spend over the daily cap."""


class ApiKeyMissingError(VisionError):
    """Raised when ANTHROPIC_API_KEY is unset and we're not in dry-run."""


class ApiCallFailedError(VisionError):
    """Raised after MAX_RETRY_ATTEMPTS exhausted on transient failures, or
    immediately on a non-retryable 4xx."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after_seconds: float | None = None,
        rate_limit_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        self.rate_limit_headers = rate_limit_headers or {}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class VisionResponse:
    """One model call's worth of structured output."""

    findings: list[dict]
    raw_text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    elapsed_s: float
    dry_run: bool = False
    cache_hit: bool = False


@dataclass
class LedgerEntry:
    """One row in `tmp/vision-spend.jsonl`."""

    timestamp_iso: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    png_path: str = ""
    theme: str = ""
    route: str = ""
    viewport: str = ""

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp_iso,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "png_path": self.png_path,
            "theme": self.theme,
            "route": self.route,
            "viewport": self.viewport,
        }


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    *,
    price_input_per_mtok: float = DEFAULT_PRICE_INPUT_PER_MTOK,
    price_output_per_mtok: float = DEFAULT_PRICE_OUTPUT_PER_MTOK,
) -> float:
    """Estimate USD cost for a single call. Image tokens are billed as
    input tokens; we don't separate them in the math because Anthropic
    returns combined `input_tokens` in the usage block.
    """
    in_cost = (input_tokens / 1_000_000.0) * price_input_per_mtok
    out_cost = (output_tokens / 1_000_000.0) * price_output_per_mtok
    return in_cost + out_cost


def fingerprint_inputs(
    *,
    png_bytes: bytes,
    intent_md: str,
    prompt_version: str = PROMPT_VERSION,
    model: str = DEFAULT_MODEL,
    extra: str = "",
) -> str:
    """Stable fingerprint covering every input that would change a finding.

    Anything that goes into the model's reasoning belongs here; if any one
    of these changes, the cached findings on disk must be discarded. SHA-256
    is overkill for collision risk but keeps the value cheap to compute and
    reasonable to display in logs.
    """
    h = hashlib.sha256()
    h.update(b"png:")
    h.update(hashlib.sha256(png_bytes).digest())
    h.update(b"\nintent:")
    h.update(hashlib.sha256(intent_md.encode("utf-8")).digest())
    h.update(b"\nprompt:")
    h.update(prompt_version.encode("utf-8"))
    h.update(b"\nmodel:")
    h.update(model.encode("utf-8"))
    if extra:
        h.update(b"\nextra:")
        h.update(extra.encode("utf-8"))
    return h.hexdigest()


def build_system_prompt(
    *,
    include_functional_breakage: bool = False,
) -> str:
    """The fixed instruction text that frames every vision review.

    Kept in code (not in a markdown file) so changes to it bump
    PROMPT_VERSION explicitly — the prompt is a versioned interface with
    the model, not config.

    ``include_functional_breakage`` expands the rubric to also flag
    broken layouts and missing controls on WC chrome routes at desktop+
    viewports. Defaults to False so non-WC-chrome routes keep the
    narrower aesthetic rubric (fewer false positives on routes where
    "content panel" isn't a well-defined concept).
    """
    base = (
        "You are a senior product designer reviewing a screenshot of a "
        "WordPress block theme. You will receive (1) a generic visual "
        "rubric, (2) the theme's specific design-intent.md rubric, "
        "(3) the route's purpose, and (4) the screenshot itself.\n\n"
        "Your job is to identify VISUAL design problems — things a "
        "designer would flag in a 30-second review. You are NOT looking "
        "for accessibility issues or browser-specific rendering bugs "
        "(those are caught by other tooling). You are looking for: "
        "typography overpowering the page, collapsed visual hierarchy, "
        "buried calls-to-action, color clashes, alignment drift, "
        "whitespace imbalance, brand-voice violations against the "
        "theme's design-intent.md, and mockup divergence.\n\n"
    )
    functional = ""
    if include_functional_breakage:
        functional = (
            "## Functional-breakage pass (this route is in scope)\n\n"
            "This screenshot is of a WooCommerce chrome route "
            "(my-account, cart-*, checkout-*, order-received) captured "
            "at a desktop or wider viewport, where the theme promises "
            "a two-column grid and visibly populated content. On these "
            "screenshots you MUST also flag the following structural "
            "failures (they count as user-facing regressions, not "
            "polish opportunities):\n"
            "  * `vision:layout-collapsed-at-desktop` — a multi-column "
            "grid (account nav + content, cart items + sidebar, "
            "checkout form + order summary) has collapsed to a single "
            "narrow column despite the viewport being >= 1280px. Tell "
            "is: wide whitespace gutters on either side of a ~400px-"
            "or-narrower content strip.\n"
            "  * `vision:menu-without-content-panel` — a populated "
            "account/checkout navigation is visible but the expected "
            "content panel beside it is empty cream, a giant vertical "
            "gap, or wrapping vertically beneath the nav.\n"
            "  * `vision:primary-button-missing-or-unclickable` — the "
            "screenshot's primary CTA for the route (Proceed to "
            "checkout, Place order, Return to cart, Sign in) has no "
            "visible hit target — missing, near-zero-height, or "
            "overlapping another element so the label is unreadable.\n"
            "  * `vision:container-narrower-than-viewport-wide` — the "
            "cart/checkout/my-account content container is clearly "
            "narrower than ~900px at a 1280px+ viewport, producing "
            "per-letter text wraps or a single squeezed column in a "
            "wide viewport.\n"
            "  * `vision:empty-state-instead-of-content` — the page "
            "displays an empty-state illustration or message when the "
            "test data for this route should have produced populated "
            "content (filled cart, logged-in dashboard, etc.).\n"
            "Severity for these is `error` by default — they are "
            "user-facing regressions, not polish.\n\n"
        )
    tail = (
        "Return ONLY valid JSON in the schema described in the user "
        "message. No prose before or after the JSON. No markdown code "
        "fences. Each finding MUST use one of the allowed `kind` values "
        "exactly. If the screenshot looks fine, return "
        "`{\"findings\": []}` — false positives are worse than misses.\n\n"
        "Severity guide:\n"
        "  - `error`: a designer would refuse to ship this; user-facing "
        "regression\n"
        "  - `warn`: a designer would flag this in review but might ship\n"
        "  - `info`: a polish opportunity, not a bug"
    )
    return base + functional + tail


def build_user_prompt(
    *,
    theme: str,
    route: str,
    viewport: str,
    intent_md: str,
    route_purpose: str = "",
    kinds_allowlist: frozenset[str] | None = None,
) -> str:
    """The per-call user message. Plain text; image is attached separately
    by the caller.

    ``kinds_allowlist`` shrinks the enumerated "Allowed kind values"
    list the model sees. When None, enumerates the full
    ALLOWED_FINDING_KINDS (legacy behaviour). When set to the content
    or structural subset (via ``kinds_for_phase``), the model is told
    that only those kinds are valid, so off-phase findings become
    off-list and get dropped by ``parse_findings_response``'s filter
    too (defence-in-depth).
    """
    allowlist = kinds_allowlist if kinds_allowlist else ALLOWED_FINDING_KINDS
    return (
        f"## Theme\n`{theme}`\n\n"
        f"## Route\n`{route}` at viewport `{viewport}`"
        + (f"\n\n## Route purpose\n{route_purpose}" if route_purpose else "")
        + f"\n\n## Theme design-intent.md\n\n{intent_md}\n\n"
        "## Schema (return EXACTLY this shape, no extras)\n\n"
        "```json\n"
        "{\n"
        '  "findings": [\n'
        "    {\n"
        '      "kind": "vision:<one-of-allowed-kinds>",\n'
        '      "severity": "error" | "warn" | "info",\n'
        '      "message": "<= 280 chars",\n'
        '      "bbox": {"x": <int>, "y": <int>, "w": <int>, "h": <int>} or null,\n'
        '      "rationale": "<= 600 chars explaining which rubric rule was violated",\n'
        '      "remedy_hint": "<= 200 chars actionable suggestion" or null\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n\n"
        "## Allowed `kind` values\n\n"
        + "\n".join(f"- `{k}`" for k in sorted(allowlist))
        + "\n\nReturn the JSON object now."
    )


def parse_findings_response(
    raw_text: str,
    *,
    kinds_allowlist: frozenset[str] | None = None,
) -> list[dict]:
    """Extract + normalise the findings list from the model's response.

    Best-effort: if the model wraps JSON in a code fence, strip it. If
    fields are missing, supply defaults. If a finding has an unknown
    `kind` or invalid `severity`, drop it (don't crash).

    ``kinds_allowlist`` tightens the kind filter to a subset of
    ALLOWED_FINDING_KINDS (e.g. the content-only or structural-only
    subset from ``kinds_for_phase``). The default (None) keeps the
    full legacy allowlist.

    Returns a list of normalised finding dicts ready to be appended to
    `<route>.findings.json`.
    """
    effective_allowlist = (
        kinds_allowlist if kinds_allowlist else ALLOWED_FINDING_KINDS
    )
    text = raw_text.strip()
    # Tolerate fenced output even though the prompt forbids it.
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    raw_findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw_findings, list):
        return []
    out: list[dict] = []
    for f in raw_findings:
        if not isinstance(f, dict):
            continue
        kind = f.get("kind")
        severity = f.get("severity")
        if kind not in effective_allowlist:
            continue
        if severity not in ALLOWED_SEVERITIES:
            severity = "warn"
        bbox = f.get("bbox")
        if isinstance(bbox, dict):
            try:
                bbox = {
                    "x": int(bbox.get("x", 0)),
                    "y": int(bbox.get("y", 0)),
                    "w": int(bbox.get("w", 0)),
                    "h": int(bbox.get("h", 0)),
                }
            except (TypeError, ValueError):
                bbox = None
        else:
            bbox = None
        out.append(
            {
                "kind": kind,
                "severity": severity,
                "message": str(f.get("message", ""))[:280],
                "bbox": bbox,
                "rationale": str(f.get("rationale", ""))[:600],
                "remedy_hint": (str(f.get("remedy_hint"))[:200] if f.get("remedy_hint") else None),
                "source": "vision",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Ledger I/O (impure but tiny + isolated)
# ---------------------------------------------------------------------------


def append_ledger(entry: LedgerEntry, *, path: Path = DEFAULT_LEDGER_PATH) -> None:
    """Append one JSON line to the spend ledger. Creates parent dir if
    missing. Crash-safe via O_APPEND semantics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.as_dict(), ensure_ascii=False) + "\n")


def today_spend_usd(*, path: Path = DEFAULT_LEDGER_PATH, now: dt.datetime | None = None) -> float:
    """Sum today's ledger entries (UTC day boundary). Returns 0.0 if the
    ledger doesn't exist yet."""
    if not path.exists():
        return 0.0
    today = (now or dt.datetime.now(UTC)).date().isoformat()
    total = 0.0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("timestamp", "")
            if ts.startswith(today):
                total += float(row.get("cost_usd", 0))
    except OSError:
        return 0.0
    return total


def assert_under_budget(
    estimated_call_usd: float,
    *,
    cap_usd: float = DEFAULT_DAILY_BUDGET_USD,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> None:
    """Raise BudgetExceededError if (today's spend + estimated_call_usd)
    would exceed the daily cap. Estimated cost is approximate (we don't
    know output tokens until after the call); we use input-only as a floor
    and add a small fixed budget for output."""
    spent = today_spend_usd(path=ledger_path)
    if spent + estimated_call_usd > cap_usd:
        raise BudgetExceededError(
            f"Today's vision spend is ${spent:.2f}. This call would add "
            f"~${estimated_call_usd:.2f}, exceeding the daily cap "
            f"${cap_usd:.2f}. Wait until tomorrow (UTC) or raise "
            f"FIFTY_VISION_DAILY_BUDGET."
        )


# ---------------------------------------------------------------------------
# Image preparation (Anthropic 5 MB / 8000 px limits)
# ---------------------------------------------------------------------------


def _prepare_image_for_api(png_bytes: bytes) -> tuple[bytes, str]:
    """Return (image_bytes, media_type) sized to fit Anthropic's vision
    limits. Lossless PNG is preferred; only switches to JPEG when
    downscaling alone can't hit the byte budget (the API doesn't care
    about format, but JPEG is ~4-8x smaller for photographic content
    while preserving enough detail for layout critique).

    Strategy:
      1. If the raw PNG is already within MAX_IMAGE_BYTES and both
         dimensions are <= MAX_IMAGE_DIMENSION_PX, return it untouched.
      2. Otherwise, resize so the longest edge is at most
         MAX_IMAGE_DIMENSION_PX (LANCZOS, preserves aspect ratio).
      3. Re-encode as PNG. If still too big, fall back to JPEG starting
         at quality 90 and stepping down.
      4. As a last resort (image is dominated by photographs), iteratively
         halve dimensions until the JPEG fits.

    Pillow is imported lazily to keep the module loadable in
    Pillow-less environments (the rest of the lib is pure stdlib so
    `--help` / dry-run don't need it).
    """
    from io import BytesIO

    from PIL import Image

    # Pillow 9.1+ moved the enum-style resampling filters to
    # `Image.Resampling.LANCZOS`; older releases keep them on
    # `Image.LANCZOS`. Use `getattr` on the module so mypy (which
    # knows only the new-location stub on fresh Pillow) doesn't
    # complain, and falls back gracefully on Pillow < 9.1.
    _resampling = getattr(Image, 'Resampling', Image)
    lanczos = _resampling.LANCZOS

    if (
        len(png_bytes) <= MAX_IMAGE_BYTES
        and _png_dimensions_within_limit(png_bytes)
    ):
        return png_bytes, "image/png"

    with Image.open(BytesIO(png_bytes)) as img:
        img.load()
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION_PX:
            scale = MAX_IMAGE_DIMENSION_PX / float(max(w, h))
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                lanczos,
            )

        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png_out = buf.getvalue()
        if len(png_out) <= MAX_IMAGE_BYTES:
            return png_out, "image/png"

        if img.mode != "RGB":
            img = img.convert("RGB")
        for quality in (92, 85, 78, 70, 60):
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            jpeg_out = buf.getvalue()
            if len(jpeg_out) <= MAX_IMAGE_BYTES:
                return jpeg_out, "image/jpeg"

        scale = 0.75
        while img.width > 800 or img.height > 800:
            new_w = max(800, int(img.width * scale))
            new_h = max(800, int(img.height * scale))
            small = img.resize((new_w, new_h), lanczos)
            buf = BytesIO()
            small.save(buf, format="JPEG", quality=70, optimize=True)
            out = buf.getvalue()
            if len(out) <= MAX_IMAGE_BYTES:
                return out, "image/jpeg"
            img = small

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=True)
        return buf.getvalue(), "image/jpeg"


def _png_dimensions_within_limit(png_bytes: bytes) -> bool:
    """Cheap dimension check that doesn't decode the pixels. PNG IHDR
    starts at byte 16 (8-byte sig + 4-byte length + 4-byte type 'IHDR')
    and encodes width + height as two 4-byte big-endian integers."""
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        # Not a recognisable PNG -- defer to the slow path so PIL can
        # decide what to do (could be a stripped/odd image).
        return False
    width = int.from_bytes(png_bytes[16:20], "big")
    height = int.from_bytes(png_bytes[20:24], "big")
    return max(width, height) <= MAX_IMAGE_DIMENSION_PX


# ---------------------------------------------------------------------------
# HTTP wrapper
# ---------------------------------------------------------------------------


def parse_retry_after(value: str | None, *, now: dt.datetime | None = None) -> float | None:
    """Parse Anthropic's `retry-after` header into seconds.

    The docs define this as "the number of seconds to wait", but HTTP
    allows a date form too. Accept both so the wrapper stays robust.
    """
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        retry_at = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    current = now or dt.datetime.now(UTC)
    return max(0.0, (retry_at - current).total_seconds())


def _rate_limit_headers(exc: urllib.error.HTTPError) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in exc.headers.items():
        lower = key.lower()
        if any(lower.startswith(prefix) for prefix in RATE_LIMIT_HEADER_PREFIXES):
            out[lower] = str(value)
    return out


def _rate_limit_summary(
    status: int,
    headers: dict[str, str],
    err_body: str,
) -> str:
    parts = [f"HTTP {status} from Anthropic"]
    if status == 429:
        parts.append("rate limit exceeded")
    retry_after = headers.get("retry-after")
    if retry_after:
        parts.append(f"retry-after={retry_after}s")
    for name in (
        "anthropic-ratelimit-requests-remaining",
        "anthropic-ratelimit-requests-reset",
        "anthropic-ratelimit-input-tokens-remaining",
        "anthropic-ratelimit-input-tokens-reset",
        "anthropic-ratelimit-output-tokens-remaining",
        "anthropic-ratelimit-output-tokens-reset",
        "anthropic-ratelimit-tokens-remaining",
        "anthropic-ratelimit-tokens-reset",
    ):
        if headers.get(name):
            parts.append(f"{name}={headers[name]}")
    if err_body:
        parts.append(f"body={err_body[:400]}")
    return "; ".join(parts)


def _post_with_retry(payload: dict, headers: dict, *, timeout_s: float = 90.0) -> dict:
    """POST to Anthropic's Messages API with exponential backoff on
    transient failures. Returns the parsed JSON response. Raises
    ApiCallFailedError after exhausting retries or on a non-retryable
    4xx.
    """
    body = json.dumps(payload).encode("utf-8")
    last_exc: Exception | None = None
    last_status: int | None = None
    last_retry_after: float | None = None
    last_rate_limit_headers: dict[str, str] = {}
    last_error_summary = ""
    for attempt in range(MAX_RETRY_ATTEMPTS):
        req = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = exc.code
            last_status = status
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            rate_headers = _rate_limit_headers(exc)
            retry_after = parse_retry_after(rate_headers.get("retry-after"))
            last_retry_after = retry_after
            last_rate_limit_headers = rate_headers
            last_error_summary = _rate_limit_summary(status, rate_headers, err_body)
            if status not in RETRYABLE_STATUS:
                raise ApiCallFailedError(
                    f"HTTP {status} from Anthropic (non-retryable): {err_body[:400]}",
                    status=status,
                    retry_after_seconds=retry_after,
                    rate_limit_headers=rate_headers,
                ) from exc
            last_exc = exc
        except urllib.error.URLError as exc:
            last_exc = exc
            last_error_summary = repr(exc)
        if attempt < MAX_RETRY_ATTEMPTS - 1:
            delay = (
                last_retry_after
                if last_status == 429 and last_retry_after is not None
                else RETRY_BACKOFF_SECONDS[attempt]
            )
            time.sleep(delay)
    raise ApiCallFailedError(
        f"Anthropic call failed after {MAX_RETRY_ATTEMPTS} attempts: "
        f"{last_error_summary or last_exc!r}",
        status=last_status,
        retry_after_seconds=last_retry_after,
        rate_limit_headers=last_rate_limit_headers,
    )


# ---------------------------------------------------------------------------
# Public API: review_image
# ---------------------------------------------------------------------------


def vision_completion(
    *,
    png_path: Path,
    system_prompt: str,
    user_prompt: str,
    theme: str = "",
    route: str = "",
    viewport: str = "",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    dry_run: bool = False,
    dry_run_text: str = "",
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    daily_budget_usd: float = DEFAULT_DAILY_BUDGET_USD,
    extra_png_paths: list[Path] | None = None,
) -> VisionResponse:
    """Generic PNG + prompt -> text completion against Anthropic's vision API.

    This is the low-level primitive shared by every vision caller in the
    repo. Callers supply their own `system_prompt` and `user_prompt` and
    get back the model's raw text in `VisionResponse.raw_text`; parsing
    the text into task-specific JSON (findings, a design spec, anything
    else) is the caller's job.

    Re-uses every piece of the original `review_image` plumbing --
    image downscaling, retry loop, spend ledger, daily budget cap,
    model pin, pricing constants -- so the project has exactly one
    place that knows how to talk to Anthropic for vision calls and one
    ledger that records their spend.

    `VisionResponse.findings` is always an empty list when called
    through this primitive; only `review_image` populates it, because
    findings parsing is specific to the screenshot-review rubric.

    Raises:
      ApiKeyMissingError if not dry_run and ANTHROPIC_API_KEY is unset.
      BudgetExceededError if today's spend + this call > daily cap.
      ApiCallFailedError on persistent HTTP failures.

    In dry_run mode returns a synthetic VisionResponse carrying
    `dry_run_text` (or a placeholder) without touching the network or
    the ledger -- useful for prompt iteration and CI smoke tests on
    branches without secrets.
    """
    if dry_run:
        return VisionResponse(
            findings=[],
            raw_text=dry_run_text or "(dry-run; no API call)",
            model=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            elapsed_s=0.0,
            dry_run=True,
        )

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ApiKeyMissingError(
            "ANTHROPIC_API_KEY not set and not running with dry_run=True. "
            "Either export an API key or pass --dry-run."
        )

    # Assemble every image (main + extras) into a list so the API call
    # gets the full visual context. `extra_png_paths` lets callers send
    # e.g. two near-duplicate product photos side-by-side for a pairwise
    # judgment without having to composite them first.
    all_paths: list[Path] = [Path(png_path)]
    if extra_png_paths:
        all_paths.extend(Path(p) for p in extra_png_paths)

    # Approximate floor cost: 1500 image tokens per image + ~800 prompt.
    estimated = estimate_cost_usd(1500 * len(all_paths) + 800, max_output_tokens // 2)
    assert_under_budget(estimated, cap_usd=daily_budget_usd, ledger_path=ledger_path)

    # Resize / recompress each one to fit Anthropic's 5 MB + 8000 px
    # image limits before base64-encoding. Full-page snap PNGs routinely
    # blow both.
    image_blocks: list[dict] = []
    for p in all_paths:
        img_bytes, media_type = _prepare_image_for_api(p.read_bytes())
        image_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(img_bytes).decode("ascii"),
                },
            }
        )

    payload = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": [
                    *image_blocks,
                    {"type": "text", "text": user_prompt},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    started = time.monotonic()
    resp = _post_with_retry(payload, headers)
    elapsed = time.monotonic() - started

    raw_text = ""
    for block in resp.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            raw_text += block.get("text", "")
    usage = resp.get("usage") or {}
    in_tokens = int(usage.get("input_tokens", 0))
    out_tokens = int(usage.get("output_tokens", 0))
    cost = estimate_cost_usd(in_tokens, out_tokens)

    append_ledger(
        LedgerEntry(
            timestamp_iso=dt.datetime.now(UTC).isoformat(),
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=cost,
            png_path=str(png_path),
            theme=theme,
            route=route,
            viewport=viewport,
        ),
        path=ledger_path,
    )

    return VisionResponse(
        findings=[],
        raw_text=raw_text,
        model=model,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_usd=cost,
        elapsed_s=elapsed,
        dry_run=False,
    )


def review_image(
    *,
    png_path: Path,
    intent_md: str,
    theme: str = "",
    route: str = "",
    viewport: str = "",
    route_purpose: str = "",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    dry_run: bool = False,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    daily_budget_usd: float = DEFAULT_DAILY_BUDGET_USD,
    phase: str = VISION_PHASE_ALL,
) -> VisionResponse:
    """Send one screenshot to the vision model and return parsed findings.

    Thin wrapper over `vision_completion`: builds the findings-rubric
    system + user prompts, delegates the HTTP/ledger/retry work, then
    runs `parse_findings_response` on the model's raw text. Callers
    that want a different response shape (e.g. a design spec) should
    call `vision_completion` directly with their own prompts.

    ``phase`` controls the two-step `design.py build` / `dress` split:
    ``all`` (default) keeps legacy behaviour — the model grades
    everything in ALLOWED_FINDING_KINDS. ``content`` shrinks the
    allowlist to the 4 catalogue-fit kinds (photography-mismatch,
    color-clash, brand-violation, mockup-divergent), used by
    `design.py dress`. ``structural`` shrinks it to the complement,
    which `design.py build` never needs (build skips vision entirely)
    but is wired for symmetry and for callers that want to isolate
    layout/hierarchy problems without content noise.

    Raises:
      ApiKeyMissingError if not dry_run and ANTHROPIC_API_KEY is unset.
      BudgetExceededError if today's spend + this call > daily cap.
      ApiCallFailedError on persistent HTTP failures.

    In dry_run mode: returns a synthetic VisionResponse with empty
    findings; does not call the API or touch the ledger.
    """
    include_functional = should_flag_functional_breakage(route, viewport)
    phase_allowlist = kinds_for_phase(phase)
    # When phase is `content`, the functional-breakage section is
    # out-of-phase (those kinds are structural). Force it off so the
    # prompt doesn't contradict the smaller allowed-kinds list the
    # model sees in the user prompt.
    if phase == VISION_PHASE_CONTENT:
        include_functional = False
    system_prompt = build_system_prompt(
        include_functional_breakage=include_functional,
    )
    user_prompt = build_user_prompt(
        theme=theme,
        route=route,
        viewport=viewport,
        intent_md=intent_md,
        route_purpose=route_purpose,
        kinds_allowlist=phase_allowlist,
    )

    resp = vision_completion(
        png_path=png_path,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        theme=theme,
        route=route,
        viewport=viewport,
        model=model,
        api_key=api_key,
        dry_run=dry_run,
        max_output_tokens=max_output_tokens,
        ledger_path=ledger_path,
        daily_budget_usd=daily_budget_usd,
    )

    findings = (
        []
        if resp.dry_run
        else parse_findings_response(
            resp.raw_text, kinds_allowlist=phase_allowlist
        )
    )

    return VisionResponse(
        findings=findings,
        raw_text=resp.raw_text,
        model=resp.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cost_usd=resp.cost_usd,
        elapsed_s=resp.elapsed_s,
        dry_run=resp.dry_run,
    )


# ---------------------------------------------------------------------------
# Text-only completions (used by bin/spec-from-prompt.py)
# ---------------------------------------------------------------------------


def text_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    dry_run: bool = False,
    dry_run_text: str = "",
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    daily_budget_usd: float = DEFAULT_DAILY_BUDGET_USD,
    label: str = "text",
) -> VisionResponse:
    """Send a text-only prompt to Anthropic, return the text response.

    Re-uses every piece of `review_image`'s plumbing -- retry loop,
    spend ledger, daily budget cap, model pin, pricing constants -- so
    the project has exactly one place that knows how to talk to
    Anthropic and one ledger that records spend.

    Returns a `VisionResponse` (the field names map directly: `raw_text`
    is the model's output, `findings` is always empty for text calls,
    `cost_usd` is the per-call cost). Callers who need structured
    output should JSON-parse `raw_text` themselves -- this helper
    deliberately stays format-agnostic so it can serve spec generation
    today and other text-only call sites tomorrow.

    `label` is a freeform tag the caller supplies to keep different
    call sites apart in the spend ledger (e.g. "spec-from-prompt").
    """
    if dry_run:
        return VisionResponse(
            findings=[],
            raw_text=dry_run_text or "(dry-run; no API call)",
            model=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            elapsed_s=0.0,
            dry_run=True,
        )

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ApiKeyMissingError(
            "ANTHROPIC_API_KEY not set and not running with dry_run=True. "
            "Either export an API key or pass --dry-run."
        )

    estimated = estimate_cost_usd(len(user_prompt) // 3 + 500, max_output_tokens // 2)
    assert_under_budget(estimated, cap_usd=daily_budget_usd, ledger_path=ledger_path)

    payload = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    started = time.monotonic()
    resp = _post_with_retry(payload, headers)
    elapsed = time.monotonic() - started

    raw_text = ""
    for block in resp.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            raw_text += block.get("text", "")
    usage = resp.get("usage") or {}
    in_tokens = int(usage.get("input_tokens", 0))
    out_tokens = int(usage.get("output_tokens", 0))
    cost = estimate_cost_usd(in_tokens, out_tokens)

    append_ledger(
        LedgerEntry(
            timestamp_iso=dt.datetime.now(UTC).isoformat(),
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=cost,
            png_path=f"text:{label}",
            theme="",
            route="",
            viewport="",
        ),
        path=ledger_path,
    )

    return VisionResponse(
        findings=[],
        raw_text=raw_text,
        model=model,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_usd=cost,
        elapsed_s=elapsed,
        dry_run=False,
    )
