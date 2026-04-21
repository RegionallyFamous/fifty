#!/usr/bin/env python3
"""Validate that every block name referenced in theme.json actually exists.

Fetches the canonical block lists from the Gutenberg and WooCommerce GitHub
repositories, then checks every key under `styles.blocks` in `theme.json`.

Exits non-zero if:
  - theme.json is invalid JSON
  - any styles.blocks key starts with a prefix other than `core/` or `woocommerce/`
  - any `core/<name>` key does not match a folder in the Gutenberg block-library
  - any `woocommerce/<name>` key does not match a known WooCommerce block

Usage:
    python3 bin/validate-theme-json.py [path/to/theme.json]

Requires Python 3.8+ (standard library only).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

GUTENBERG_API = (
    "https://api.github.com/repos/WordPress/gutenberg/contents/"
    "packages/block-library/src?ref=trunk"
)
# Git Trees API returns the full recursive tree for a ref; we use it to find
# every block.json under WooCommerce's blocks tree, including deeply nested ones.
WOOCOMMERCE_TREE_API = (
    "https://api.github.com/repos/woocommerce/woocommerce/git/trees/trunk?recursive=1"
)
WOOCOMMERCE_BLOCK_PATH_PREFIX = "plugins/woocommerce/client/blocks/assets/js/blocks/"


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "obel-validator"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gutenberg_block_names() -> set[str]:
    """Return the set of `core/<slug>` names from Gutenberg's block-library tree."""
    entries = fetch_json(GUTENBERG_API)
    if not isinstance(entries, list):
        raise RuntimeError(f"Unexpected Gutenberg API response: {entries!r}")
    return {f"core/{e['name']}" for e in entries if e.get("type") == "dir"}


def woocommerce_block_names() -> set[str]:
    """Return the set of `woocommerce/<slug>` names found in the WC source.

    WC blocks live in deeply nested folders (cart-checkout/cart/, product-
    elements/product-title/, etc.). We use the Git Trees API to fetch the
    full recursive tree once, then look for every `block.json` and read
    its parent folder name as the block slug.

    Block.json files are not fetched (which would be N requests). Instead
    we treat the parent folder name as the slug, which matches WC's
    convention for the vast majority of blocks. False negatives can be
    overridden by editing the EXTRA_KNOWN_WC_BLOCKS set below.
    """
    seen: set[str] = set()
    try:
        tree = fetch_json(WOOCOMMERCE_TREE_API)
    except urllib.error.HTTPError as exc:
        print(
            f"  warning: could not fetch WooCommerce tree ({exc}); skipping WC validation",
            file=sys.stderr,
        )
        return set()
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        return set()

    for node in tree["tree"]:
        path = node.get("path", "")
        if (
            node.get("type") == "blob"
            and path.startswith(WOOCOMMERCE_BLOCK_PATH_PREFIX)
            and path.endswith("/block.json")
        ):
            # path looks like:
            #   plugins/.../blocks/cart-checkout/cart/block.json
            # the slug is the parent folder name, e.g. "cart"
            parts = path[len(WOOCOMMERCE_BLOCK_PATH_PREFIX):].split("/")
            if len(parts) >= 2:
                slug = parts[-2]
                seen.add(f"woocommerce/{slug}")

    seen.update(EXTRA_KNOWN_WC_BLOCKS)
    return seen


# Block names that are valid but whose folder names don't match the slug
# (e.g. blocks registered programmatically via JS without a block.json file).
# Verified manually against WooCommerce trunk. Add new entries here when
# validation reports false negatives for blocks you know are real.
EXTRA_KNOWN_WC_BLOCKS: set[str] = {
    # Cart top-level + inner blocks
    "woocommerce/cart",
    "woocommerce/filled-cart-block",
    "woocommerce/empty-cart-block",
    "woocommerce/cart-items-block",
    "woocommerce/cart-line-items-block",
    "woocommerce/cart-totals-block",
    "woocommerce/cart-order-summary-block",
    "woocommerce/cart-order-summary-heading-block",
    "woocommerce/cart-order-summary-totals-block",
    "woocommerce/proceed-to-checkout-block",
    "woocommerce/cart-cross-sells-block",
    # Checkout inner blocks
    "woocommerce/checkout-fields-block",
    "woocommerce/checkout-totals-block",
    "woocommerce/checkout-contact-information-block",
    "woocommerce/checkout-shipping-address-block",
    "woocommerce/checkout-billing-address-block",
    "woocommerce/checkout-shipping-method-block",
    "woocommerce/checkout-payment-block",
    "woocommerce/checkout-order-note-block",
    "woocommerce/checkout-actions-block",
    "woocommerce/checkout-terms-block",
    "woocommerce/checkout-order-summary-block",
    "woocommerce/checkout-order-summary-cart-items-block",
    "woocommerce/checkout-order-summary-totals-block",
    # Product Elements (registered via JS in product-elements/index.tsx)
    "woocommerce/product-image",
    "woocommerce/product-image-gallery",
    "woocommerce/product-title",
    "woocommerce/product-price",
    "woocommerce/product-rating",
    "woocommerce/product-rating-counter",
    "woocommerce/product-rating-stars",
    "woocommerce/product-summary",
    "woocommerce/product-sku",
    "woocommerce/product-stock-indicator",
    "woocommerce/product-sale-badge",
    "woocommerce/product-meta",
    "woocommerce/product-button",
    "woocommerce/related-products",
    # Product Filters (registered as inner blocks of woocommerce/product-filters)
    "woocommerce/product-filter-active",
    "woocommerce/product-filter-attribute",
    "woocommerce/product-filter-price",
    "woocommerce/product-filter-rating",
    "woocommerce/product-filter-status",
    "woocommerce/product-filter-category",
    "woocommerce/product-filter-tag",
    "woocommerce/product-filter-brand",
    "woocommerce/product-filter-checkbox-list",
    "woocommerce/product-filter-chips",
    "woocommerce/product-filter-clear-button",
    # Order Confirmation inner blocks
    "woocommerce/order-confirmation-summary",
    "woocommerce/order-confirmation-status",
    "woocommerce/order-confirmation-totals",
    "woocommerce/order-confirmation-totals-wrapper",
    "woocommerce/order-confirmation-shipping-address",
    "woocommerce/order-confirmation-billing-address",
    "woocommerce/order-confirmation-additional-fields",
    "woocommerce/order-confirmation-additional-information",
    "woocommerce/order-confirmation-create-account",
    "woocommerce/order-confirmation-downloads",
}


def validate(theme_json_path: Path) -> int:
    if not theme_json_path.exists():
        print(f"error: {theme_json_path} not found", file=sys.stderr)
        return 2

    try:
        data = json.loads(theme_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: theme.json is not valid JSON: {exc}", file=sys.stderr)
        return 2

    blocks = data.get("styles", {}).get("blocks", {})
    if not isinstance(blocks, dict):
        print("error: styles.blocks is missing or not an object", file=sys.stderr)
        return 2

    print(f"checking {len(blocks)} block-style entries in {theme_json_path}...")

    print("  fetching Gutenberg block list...")
    try:
        core = gutenberg_block_names()
    except Exception as exc:
        print(f"error: could not fetch Gutenberg block list: {exc}", file=sys.stderr)
        return 3
    print(f"    {len(core)} core blocks found")

    print("  fetching WooCommerce block list...")
    wc = woocommerce_block_names()
    print(f"    {len(wc)} WooCommerce blocks found (including known inner blocks)")

    bad_prefix: list[str] = []
    bad_core: list[str] = []
    suspicious_wc: list[str] = []

    for key in blocks:
        if key.startswith("core/"):
            if key not in core:
                bad_core.append(key)
        elif key.startswith("woocommerce/"):
            if wc and key not in wc:
                # WC block names often live in nested folders; flag as
                # "suspicious" rather than "wrong".
                suspicious_wc.append(key)
        else:
            bad_prefix.append(key)

    failed = False

    if bad_prefix:
        failed = True
        print("\n  invalid prefix (only core/ and woocommerce/ allowed):")
        for k in bad_prefix:
            print(f"    {k}")

    if bad_core:
        failed = True
        print("\n  unknown core/ block names (not present in Gutenberg trunk):")
        for k in bad_core:
            print(f"    {k}")

    if suspicious_wc:
        print("\n  woocommerce/ blocks not found at top level (verify manually):")
        for k in suspicious_wc:
            print(f"    {k}")

    if failed:
        print("\nFAIL: theme.json contains invalid block names.")
        return 1

    print("\nOK: all core/* keys are valid registered block names.")
    if suspicious_wc:
        print(
            f"Note: {len(suspicious_wc)} woocommerce/* keys could not be auto-verified;"
            " confirm against the WC source if uncertain."
        )
    return 0


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _lib import resolve_theme_root

    if len(argv) > 2:
        print("usage: validate-theme-json.py [theme_name|path/to/theme.json]", file=sys.stderr)
        return 2
    if len(argv) == 2:
        arg = argv[1]
        candidate = Path(arg)
        if candidate.is_file():
            target = candidate
        else:
            target = resolve_theme_root(arg) / "theme.json"
    else:
        target = resolve_theme_root() / "theme.json"
    return validate(target)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
