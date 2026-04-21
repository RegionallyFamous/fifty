"""Visual-snapshot config for the bin/snap.py framework.

Defines the cartesian product of (route, viewport) that bin/snap.py shoots
for every theme. Edit this file to add/remove pages or viewport widths;
the change applies uniformly across all themes.

Conventions
-----------

* Route slugs (the first tuple element) are stable identifiers used as
  filenames in `tmp/snaps/<theme>/<viewport>/<slug>.png` and
  `tests/visual-baseline/<theme>/<viewport>/<slug>.png`. Keep them
  filesystem-safe (lowercase, hyphens, no spaces).
* Route paths are relative to the WordPress site root and may include a
  query string. The `?demo=cart` suffix on cart/checkout deep-links
  triggers wo-cart-mu.php which pre-fills the cart with a known set of
  W&O products so reviewers see the full purchase flow without manual
  clicks. Removing it leaves the page in its empty-cart state, which is
  also worth snapping (see `cart-empty` / `checkout-empty`).
* Viewports are named so diff summaries are human-readable. Widths
  chosen to bracket the responsive breakpoints used in the themes:
    - mobile  390px   below the 782px grid breakpoint (single-column)
    - tablet  768px   straddling the breakpoint (single-column on most pages)
    - desktop 1280px  matches theme.json wideSize and the cart/checkout
                       sidebar at its natural max
    - wide    1920px  ultrawide; surfaces issues with `align:full` blocks
* Heights are large enough to keep the fold visible at common screen
  ratios. Playwright's `full_page=True` overrides the height anyway so
  the value only matters for above-the-fold-only screenshots, which we
  don't currently take.

Route selection rationale
-------------------------

Each theme exposes the same set of WC pages thanks to the shared
playground/wo-configure.php seeding. The routes below cover:

  * Home                     -- editorial front-page (theme identity)
  * Shop archive             -- product grid + sort dropdown
  * Single simple product    -- gallery + add-to-cart + reviews
  * Single variable product  -- swatch picker + variation image swap
  * Single category archive  -- archive header + product grid
  * Cart (filled)            -- the page that broke at 560px on desktop
  * Checkout (filled)        -- the page that wrapped per-letter on desktop
  * My Account (logged-out)  -- WC's customer login form
  * Journal (blog index)     -- post grid + theme typography
  * Single blog post         -- prose flow + theme typography

If you add a route here, also add a corresponding baseline by running
`python3 bin/snap.py shoot <theme> && python3 bin/snap.py baseline <theme>`.
"""

from __future__ import annotations

from typing import NamedTuple


class Route(NamedTuple):
    slug: str
    path: str
    description: str  # surfaced in `bin/snap.py list` for human readability


class Viewport(NamedTuple):
    name: str
    width: int
    height: int


ROUTES: list[Route] = [
    Route(
        slug="home",
        path="/",
        description="Editorial front-page (theme identity, hero, featured products).",
    ),
    Route(
        slug="shop",
        path="/shop/",
        description="WC shop archive with sort dropdown and product grid.",
    ),
    Route(
        slug="product-simple",
        path="/product/bottled-morning/",
        description="Single simple product with gallery, add-to-cart, reviews.",
    ),
    Route(
        slug="product-variable",
        path="/product/bottled-morning-variants/",
        description="Single variable product with attribute swatches and variation image swap.",
    ),
    Route(
        slug="category",
        path="/product-category/curiosities/",
        description="Single product-category archive page.",
    ),
    Route(
        slug="cart-filled",
        path="/cart/?demo=cart",
        description="Cart page with 3 items pre-loaded via wo-cart-mu.php.",
    ),
    Route(
        slug="cart-empty",
        path="/cart/",
        description="Cart page in empty state (regression-prone block).",
    ),
    Route(
        slug="checkout-filled",
        path="/checkout/?demo=cart",
        description="Checkout with 3 items pre-loaded; the desktop-squeeze hot-spot.",
    ),
    Route(
        slug="my-account",
        path="/my-account/",
        description="My Account login form (logged-out view).",
    ),
    Route(
        slug="journal",
        path="/journal/",
        description="Blog index (posts page) for editorial typography.",
    ),
]


VIEWPORTS: list[Viewport] = [
    Viewport(name="mobile", width=390, height=844),     # iPhone 14
    Viewport(name="tablet", width=768, height=1024),    # iPad portrait
    Viewport(name="desktop", width=1280, height=800),   # matches wideSize
    Viewport(name="wide", width=1920, height=1080),     # 1080p desktop
]


# When `bin/snap.py shoot --quick` is passed, only this subset is shot.
# Keeps the inner loop fast for "just show me the page I'm working on".
QUICK_ROUTES: set[str] = {"home", "shop", "product-simple", "checkout-filled"}
QUICK_VIEWPORTS: set[str] = {"desktop"}


# Themes are auto-discovered from the repo (any folder with a theme.json).
# Override here if you want to pin the order or skip experimental themes.
THEME_ORDER: list[str] = ["obel", "chonk", "selvedge", "lysholm", "aero"]


# ---------------------------------------------------------------------------
# Known harmless noise from WordPress core / Playground that we never
# want to count as a real page issue.
#
# Each entry is a substring matched (case-sensitive) against captured
# page_error / console.text payloads. Add to this list when investigation
# confirms the message is upstream noise — never to silence a real theme
# bug. The snap framework reads this at import time; no restart needed
# beyond the next `bin/snap.py shoot`.
# ---------------------------------------------------------------------------
KNOWN_NOISE_SUBSTRINGS: tuple[str, ...] = (
    # wp-emoji-loader appends a hidden <canvas> to <head> while the
    # head is briefly null in headless Chromium during early DOM setup.
    # Harmless; emoji rendering still works.
    "Cannot read properties of null (reading 'appendChild')",
)


# ---------------------------------------------------------------------------
# Tier-policy budgets. Each `(metric, threshold)` pair is enforced at
# shoot/report time; exceedances become findings using the listed
# severity. Designed to be overridable per-theme later (Phase 10+).
#
#   page_weight_kb        Total transferred bytes for the route, in KB.
#   image_count           Number of <img> elements rendered above the fold.
#   request_count         HTTP requests fired by the page.
#   console_warning_count Non-noise warnings on the route.
#
# Threshold None disables that budget. Values are intentionally
# generous: budgets exist to flag REGRESSIONS (a route that suddenly
# triples its image count), not to police hand-tuned routes.
# ---------------------------------------------------------------------------
BUDGETS: dict[str, dict] = {
    "console_warning_count": {"max": 10, "severity": "info"},
    # The metrics below are wired up but disabled by default; bump
    # `max` from None to a real number when we have data.
    "page_weight_kb": {"max": None, "severity": "warn"},
    "image_count": {"max": None, "severity": "info"},
    "request_count": {"max": None, "severity": "info"},
}


# ---------------------------------------------------------------------------
# Inspector selectors -- per-route CSS selectors whose computed dimensions
# get captured in `*.findings.json` and surfaced in the review.md report.
#
# Add a selector when its size or visibility is the "tell" for a known
# regression class (e.g. cart sidebar collapsing below its min-width). The
# inspector reports {selector, count, widths[], heights[], display, visible}
# for each entry -- it doesn't fail builds, just makes the data available
# without re-shooting. Use it as the "hard data" companion to the visual
# pixel diff.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Interactive states (Phase 3) -- per-route scripted flows that produce
# additional cells.
#
# Each interaction renders `<route>.<flow>.png` (and a matching
# `<route>.<flow>.findings.json`) alongside the static capture, so a
# single route can yield multiple snaps without duplicating the route
# table. The dispatcher in bin/snap.py walks the steps in order; if any
# step times out it logs a finding (severity warn, kind
# `interaction-failed`) and the rest of the flow is skipped.
#
# Step shapes:
#   {"action": "click",  "selector": "<css>",            "timeout_ms": 4000}
#   {"action": "hover",  "selector": "<css>",            "timeout_ms": 2000}
#   {"action": "focus",  "selector": "<css>"}
#   {"action": "fill",   "selector": "<css>", "text": "Hello"}
#   {"action": "press",  "key":      "Tab"}
#   {"action": "wait",   "ms":       400}
#
# `viewports` (optional) restricts the flow to a subset of viewport
# names so e.g. the mobile menu only runs on `mobile`. Default is all.
# ---------------------------------------------------------------------------
class Interaction(NamedTuple):
    name: str  # filename suffix; <route>.<name>.png
    description: str
    steps: list[dict]
    viewports: tuple[str, ...] = ()  # () = all viewports


INTERACTIONS: dict[str, list[Interaction]] = {
    "home": [
        Interaction(
            name="menu-open",
            description="Open the mobile hamburger menu and verify the overlay nav.",
            viewports=("mobile",),
            steps=[
                # Core navigation block uses an aria-label "Open menu"
                # button on mobile; click it then wait for the overlay
                # transition to settle.
                {"action": "click",
                 "selector": "button.wp-block-navigation__responsive-container-open",
                 "timeout_ms": 4000},
                {"action": "wait", "ms": 500},
            ],
        ),
    ],
    "product-simple": [
        Interaction(
            name="qty-increment",
            description="Increment quantity using the +1 button on the add-to-cart form.",
            steps=[
                {"action": "click",
                 "selector": ".wp-block-add-to-cart-form button.plus, "
                             ".quantity .plus, "
                             "input.qty + button",
                 "timeout_ms": 3000},
                {"action": "wait", "ms": 200},
            ],
        ),
    ],
    "product-variable": [
        Interaction(
            name="swatch-pick",
            description="Select a non-default attribute and verify variation image swap.",
            steps=[
                # Generic variation selector: any radio swatch or the
                # second <option> in the first attribute <select>.
                {"action": "click",
                 "selector": "table.variations select option:nth-child(3), "
                             ".wc-block-components-product-add-to-cart-attribute-picker__option:not([aria-checked='true'])",
                 "timeout_ms": 3000},
                {"action": "wait", "ms": 600},
            ],
        ),
    ],
    "cart-filled": [
        Interaction(
            name="line-remove",
            description="Remove the first line item; cart should re-flow without breaking.",
            steps=[
                {"action": "click",
                 "selector": ".wc-block-cart-item__remove-link, "
                             ".product-remove a, "
                             ".wc-block-cart-items__row:first-child .wc-block-cart-item__remove-link",
                 "timeout_ms": 4000},
                {"action": "wait", "ms": 800},
            ],
        ),
    ],
    "checkout-filled": [
        Interaction(
            name="field-focus",
            description="Focus the first checkout text input; verify focus-ring + label state.",
            steps=[
                {"action": "focus",
                 "selector": "#email, "
                             "input[autocomplete='email'], "
                             ".wc-block-components-text-input input"},
                {"action": "wait", "ms": 200},
            ],
        ),
    ],
}


INSPECT_SELECTORS: dict[str, list[str]] = {
    # Cart layout: sidebar must be >= 300px on desktop (>=782px viewport).
    "cart-filled": [
        ".wc-block-cart",
        ".wc-block-cart__sidebar",
        ".wc-block-cart__main",
        ".wc-block-components-sidebar-layout__sidebar",
        ".wc-block-cart-items",
        ".wc-block-cart__submit-container",
    ],
    "cart-empty": [
        ".wp-block-woocommerce-empty-cart-block",
        ".wc-block-cart",
    ],
    # Checkout layout: same sidebar contract; main column should match
    # theme.json wideSize (1280px) on desktop, NOT contentSize (720px).
    "checkout-filled": [
        ".wc-block-checkout",
        ".wc-block-checkout__sidebar",
        ".wc-block-checkout__main",
        ".wc-block-components-sidebar-layout__sidebar",
        ".wc-block-components-order-summary",
        "main.wp-block-group",  # the page-checkout.html wrapper
    ],
    "shop": [
        ".wp-block-woocommerce-product-template",
        ".wc-block-product-template",
    ],
    "product-simple": [
        ".woocommerce-product-gallery",
        ".product .summary",
        ".wp-block-add-to-cart-form",
        # Phase A: PDP image now renders via core/post-featured-image
        # because the WC product-image-gallery block was unreliable.
        # Track both so we can prove the swap landed.
        ".wp-block-post-featured-image",
        ".wp-block-post-featured-image img",
    ],
    "product-variable": [
        ".woocommerce-product-gallery",
        "table.variations",
        # Phase C: variation `<select>`s are visually replaced by an
        # interactive button-group. The original select stays in the
        # DOM (visually hidden) so WC's variation_form JS keeps driving
        # price/stock. Track all three so the gate fails if either the
        # swatch wrapper or the hidden select disappear.
        ".wo-swatch-wrap",
        ".wo-swatch-group",
        ".wo-swatch",
        ".wo-swatch-select",
        # Phase C: PDP gallery becomes sticky on >=782px viewports.
        ".wp-block-post-featured-image",
    ],
    "home": [
        ".wp-site-blocks > main",
        ".wp-block-post-featured-image",
    ],
    "my-account": [
        ".woocommerce-form-login",
        ".u-columns",
        # Phase D: branded login screen wraps the form in a
        # `wo-account-intro` panel + `wo-account-help` link.
        ".wo-account-intro",
        ".wo-account-help",
    ],
    "journal": [
        ".wp-block-query",
        ".wp-block-post-template",
    ],
    "category": [
        ".wp-block-woocommerce-product-template",
        ".wp-block-term-description",
        # Phase D: editorial archive header strip injected by
        # wo-pages-mu.php on category / tag / shop archives.
        ".wo-archive-hero",
        ".wo-archive-hero__title",
    ],
    # Phase C: mini-cart drawer is opened by the cart icon in the
    # header. The drawer renders into a portal at the body root via
    # WC Blocks, so this selector is global rather than nested under
    # cart/checkout.
    "mini-cart": [
        ".wc-block-mini-cart__drawer",
        ".wc-block-mini-cart-items",
        ".wc-block-mini-cart__footer",
    ],
    # Phase D: branded order-confirmation template (Thank-you hero +
    # next-steps timeline + recommendations).
    "order-received": [
        ".wo-next-steps",
        ".wo-recs",
    ],
    # Phase D: branded 404 page (eyebrow + display heading + lede +
    # search + dual CTA, all wrapped in `.wo-empty wo-empty--404`).
    "not-found": [
        ".wo-empty",
        ".wo-empty--404",
    ],
}
