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
THEME_ORDER: list[str] = ["obel", "chonk", "selvedge", "lysholm"]
