#!/usr/bin/env python3
"""Append the WC override CSS chunk to every theme's top-level styles.css.

This script is intentionally idempotent: it looks for a unique sentinel
string (`/* wc-tells: */`) and refuses to append a second copy if the
sentinel already exists. Run repeatedly without harm.

The CSS chunk re-uses the same `var(--wp--preset--color--*)` /
`var(--wp--custom--*)` tokens every theme already defines, so a single
chunk styles all four themes with no per-theme CSS forking.

Why a script and not StrReplace on theme.json directly:
  * styles.css is a single ~17 KB minified string per theme that contains
    URL-encoded SVG, embedded double quotes (escaped with `\\"` in JSON),
    and CSS that itself contains `:` and `{` which look like JSON.
    Writing the chunk through json.loads/json.dumps round-trips it safely.
  * The chunk can grow without re-anchoring StrReplace each time.

Run from the theme repo root:
  python3 bin/append-wc-overrides.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ["obel", "chonk", "selvedge", "lysholm"]

SENTINEL_OPEN = "/* wc-tells: notices, meta, rating, variations, lightbox, mini-cart, cart, checkout, order-confirm, my-account */"
SENTINEL_CLOSE = "/* /wc-tells */"

# IMPORTANT: every value here uses tokens (`var(--wp--preset--*)`,
# `var(--wp--custom--*)`) so the same chunk is correct for all four themes.
# The chevron SVG is single-quoted internally so the outer `url("...")` can
# stay double-quoted (which is how the existing chevron rule in styles.css is
# written; the JSON encoder will escape the outer `"` to `\"` for us).
CSS = f"""{SENTINEL_OPEN}
.woocommerce-notices-wrapper{{margin-block:var(--wp--preset--spacing--lg);}}
.woocommerce-message,.woocommerce-error,.woocommerce-info{{border:0;border-radius:0;background:transparent;border-top:1px solid var(--wp--preset--color--border);border-bottom:1px solid var(--wp--preset--color--border);padding:var(--wp--preset--spacing--md) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);display:flex;align-items:center;justify-content:space-between;gap:var(--wp--preset--spacing--md);list-style:none;}}
.woocommerce-message::before,.woocommerce-error::before,.woocommerce-info::before{{display:none;content:none;}}
.woocommerce-error{{color:var(--wp--preset--color--error,var(--wp--preset--color--contrast));}}
.added_to_cart{{display:inline-flex;align-items:center;gap:var(--wp--preset--spacing--xs);background:transparent;color:var(--wp--preset--color--contrast);border:0;padding:0;text-decoration:none;font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;border-bottom:1px solid currentColor;}}
.added_to_cart:hover{{color:var(--wp--preset--color--accent);}}
.product_meta .sku_wrapper>:first-child,.product_meta .posted_in>:first-child,.product_meta .tagged_as>:first-child{{display:none;}}
.product_meta .sku,.product_meta .posted_in a,.product_meta .tagged_as a{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);text-decoration:none;}}
.star-rating{{display:inline-block;position:relative;width:6rem;height:2px;overflow:hidden;background:var(--wp--preset--color--border);color:transparent;font-size:0;line-height:0;}}
.star-rating::before{{content:none;}}
.star-rating>span{{position:absolute;inset:0;right:auto;height:100%;background:var(--wp--preset--color--contrast);color:transparent;font-size:0;line-height:0;}}
.star-rating>span::before{{content:"";display:none;}}
.star-rating>span strong{{position:absolute;left:-9999px;}}
table.variations{{width:100%;border-collapse:collapse;margin:0 0 var(--wp--preset--spacing--md);}}
table.variations tr{{display:block;padding:var(--wp--preset--spacing--xs) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
table.variations th,table.variations td{{display:block;padding:0;border:0;text-align:left;}}
table.variations th{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin-bottom:var(--wp--preset--spacing--2-xs);}}
table.variations select{{appearance:none;-webkit-appearance:none;-moz-appearance:none;width:100%;background-color:var(--wp--preset--color--surface);background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8' fill='none'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right var(--wp--preset--spacing--sm) center;background-size:10px 6px;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);font:inherit;color:var(--wp--preset--color--contrast);padding:var(--wp--preset--spacing--sm) calc(var(--wp--preset--spacing--lg) + 12px) var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);}}
table.variations select:focus{{outline:none;border-color:var(--wp--preset--color--contrast);box-shadow:0 0 0 3px var(--wp--preset--color--accent-soft);}}
.reset_variations{{display:inline-block;margin-top:var(--wp--preset--spacing--sm);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);text-decoration:none;border-bottom:1px solid currentColor;}}
.reset_variations:hover{{color:var(--wp--preset--color--contrast);}}
.woocommerce-variation-price{{margin:var(--wp--preset--spacing--md) 0;}}
.woocommerce-variation-price .price{{font-size:var(--wp--preset--font-size--lg);color:var(--wp--preset--color--contrast);}}
.pswp__top-bar{{background:transparent;}}
.pswp__button{{color:var(--wp--preset--color--contrast);background:transparent;}}
.pswp__counter{{color:var(--wp--preset--color--secondary);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;}}
.flex-control-thumbs{{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--wp--preset--spacing--xs);margin:var(--wp--preset--spacing--md) 0 0;padding:0;list-style:none;}}
.flex-control-thumbs li{{margin:0;padding:0;}}
.flex-control-thumbs img{{display:block;width:100%;height:auto;border-radius:var(--wp--custom--radius--md);cursor:pointer;opacity:0.6;transition:opacity 160ms ease;}}
.flex-control-thumbs img:hover,.flex-control-thumbs img.flex-active{{opacity:1;}}
.wc-block-product-gallery-large-image-next-previous button{{background:transparent;border:1px solid var(--wp--preset--color--border);border-radius:9999px;color:var(--wp--preset--color--contrast);}}
.wc-block-product-gallery-large-image-next-previous button:hover{{border-color:var(--wp--preset--color--contrast);}}
.wc-block-mini-cart__drawer .components-modal__content{{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base);}}
.wc-block-mini-cart__title{{font-family:var(--wp--preset--font-family--display);font-weight:var(--wp--custom--font-weight--regular);font-size:var(--wp--preset--font-size--xl);letter-spacing:var(--wp--custom--letter-spacing--tight);}}
.wc-block-mini-cart-items{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);padding:0;margin:0;list-style:none;}}
.wc-block-mini-cart-items .wc-block-cart-item{{display:grid;grid-template-columns:64px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--sm) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-mini-cart-items .wc-block-cart-item img{{display:block;width:64px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-mini-cart__footer{{border-top:1px solid var(--wp--preset--color--border);padding-top:var(--wp--preset--spacing--md);margin-top:var(--wp--preset--spacing--md);}}
.wc-block-mini-cart__footer-actions{{display:grid;grid-template-columns:1fr 1fr;gap:var(--wp--preset--spacing--sm);}}
.wc-block-mini-cart__footer-actions a,.wc-block-mini-cart__footer-actions .wc-block-components-button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease,color 160ms ease;}}
.wc-block-mini-cart__footer-actions a:hover,.wc-block-mini-cart__footer-actions .wc-block-components-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.wp-block-woocommerce-empty-mini-cart-contents-block{{text-align:center;font-family:var(--wp--preset--font-family--sans);}}
.wc-block-cart{{display:grid;grid-template-columns:1fr;gap:var(--wp--preset--spacing--2-xl);}}
@media (min-width:782px){{.wc-block-cart{{grid-template-columns:2fr 1fr;}}}}
.wc-block-cart-items,.wp-block-woocommerce-cart-line-items-block{{padding:0;margin:0;border-collapse:collapse;border:0;}}
.wc-block-cart-items th{{display:none;}}
.wc-block-cart-items .wc-block-cart-items__row{{display:grid;grid-template-columns:96px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--md) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-cart-item__image img{{display:block;width:96px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-cart-item__product .wc-block-components-product-name{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--md);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);text-decoration:none;}}
.wc-block-cart-item__product .wc-block-components-product-name:hover{{color:var(--wp--preset--color--accent);}}
.wc-block-cart-item__product .wc-block-components-product-metadata{{font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);margin-top:var(--wp--preset--spacing--2-xs);}}
.wc-block-cart-item__total{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);text-align:right;}}
.wc-block-components-quantity-selector{{display:inline-flex;align-items:stretch;border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--pill);overflow:hidden;background:var(--wp--preset--color--surface);}}
.wc-block-components-quantity-selector__input{{width:48px;border:0;background:transparent;text-align:center;font-family:inherit;font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);appearance:textfield;-moz-appearance:textfield;}}
.wc-block-components-quantity-selector__input::-webkit-inner-spin-button,.wc-block-components-quantity-selector__input::-webkit-outer-spin-button{{-webkit-appearance:none;margin:0;}}
.wc-block-components-quantity-selector__button{{background:transparent;border:0;color:var(--wp--preset--color--contrast);width:32px;cursor:pointer;font-size:var(--wp--preset--font-size--base);transition:color 160ms ease;}}
.wc-block-components-quantity-selector__button:hover{{color:var(--wp--preset--color--accent);}}
.wc-block-cart__sidebar{{padding:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);}}
.wc-block-components-totals-item{{display:flex;justify-content:space-between;align-items:baseline;padding:var(--wp--preset--spacing--xs) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wc-block-components-totals-item__label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-components-totals-footer-item{{border-top:1px solid var(--wp--preset--color--border);padding-top:var(--wp--preset--spacing--md);margin-top:var(--wp--preset--spacing--xs);}}
.wc-block-components-totals-footer-item .wc-block-components-totals-item__value{{font-size:var(--wp--preset--font-size--lg);font-weight:var(--wp--custom--font-weight--medium);}}
.wc-block-components-totals-coupon__form{{display:flex;gap:var(--wp--preset--spacing--xs);}}
.wc-block-components-totals-coupon__input,.wc-block-components-totals-coupon input[type=text]{{flex:1;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
.wc-block-components-totals-coupon__button,.wc-block-components-totals-coupon button{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;cursor:pointer;transition:background 160ms ease;}}
.wc-block-components-totals-coupon__button:hover,.wc-block-components-totals-coupon button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button,.wc-block-cart__submit-container a.wc-block-cart__submit-button{{display:inline-flex;align-items:center;justify-content:center;width:100%;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wide);background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--xl);text-decoration:none;cursor:pointer;transition:background 160ms ease,transform 160ms ease;}}
.wc-block-cart__submit-container .wc-block-components-checkout-place-order-button:hover,.wc-block-cart__submit-container a.wc-block-cart__submit-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);transform:translateY(-1px);}}
.wc-block-cart-cross-sells{{margin-top:var(--wp--preset--spacing--3-xl);}}
.wc-block-cart-cross-sells>h2,.wc-block-cart-cross-sells .wp-block-heading{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--2-xl);margin:0 0 var(--wp--preset--spacing--lg);}}
.wc-block-components-shipping-calculator-address{{display:grid;gap:var(--wp--preset--spacing--sm);margin-top:var(--wp--preset--spacing--md);}}
.wc-block-checkout{{display:grid;grid-template-columns:1fr;gap:var(--wp--preset--spacing--2-xl);}}
@media (min-width:782px){{.wc-block-checkout{{grid-template-columns:2fr 1fr;}}}}
.wc-block-checkout__main{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xl);}}
.wc-block-components-checkout-step{{padding:var(--wp--preset--spacing--lg) 0;border-bottom:1px solid var(--wp--preset--color--border);position:relative;}}
.wc-block-components-checkout-step__heading{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--2-xs);margin-bottom:var(--wp--preset--spacing--md);}}
.wc-block-components-checkout-step__title{{font-family:var(--wp--preset--font-family--display);font-size:var(--wp--preset--font-size--xl);font-weight:var(--wp--custom--font-weight--regular);color:var(--wp--preset--color--contrast);}}
.wc-block-components-checkout-step__description{{font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.wc-block-components-checkout-step__container::before{{display:none;content:none;}}
.wc-block-components-checkout-step__heading-content{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-checkout__login-prompt,.wc-block-checkout__contact-information .wc-block-components-checkout-step__heading-content a{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--contrast);text-decoration:none;border-bottom:1px solid currentColor;}}
.wc-block-checkout__login-prompt:hover,.wc-block-checkout__contact-information .wc-block-components-checkout-step__heading-content a:hover{{color:var(--wp--preset--color--accent);}}
.wc-block-components-text-input input{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);transition:border-color 160ms ease,box-shadow 160ms ease;}}
.wc-block-components-text-input input:focus{{outline:none;border-color:var(--wp--preset--color--contrast);box-shadow:0 0 0 3px var(--wp--preset--color--accent-soft);}}
.wc-block-components-text-input label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wc-block-components-checkbox{{display:inline-flex;align-items:center;gap:var(--wp--preset--spacing--xs);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--secondary);}}
.wc-block-components-checkbox__input{{accent-color:var(--wp--preset--color--contrast);}}
.wc-block-components-payment-methods{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--xs);}}
.wc-block-components-payment-method{{display:block;padding:var(--wp--preset--spacing--md);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);background:var(--wp--preset--color--surface);transition:border-color 160ms ease;}}
.wc-block-components-payment-method:hover{{border-color:var(--wp--preset--color--contrast);}}
.wc-block-components-payment-method label{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);color:var(--wp--preset--color--contrast);}}
.wc-block-components-checkout-place-order-button{{display:inline-flex;align-items:center;justify-content:center;width:100%;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wide);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--md) var(--wp--preset--spacing--xl);text-decoration:none;cursor:pointer;transition:background 160ms ease,transform 160ms ease;}}
.wc-block-components-checkout-place-order-button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);transform:translateY(-1px);}}
.wc-block-components-order-summary{{display:flex;flex-direction:column;gap:var(--wp--preset--spacing--md);}}
.wc-block-components-order-summary-item{{display:grid;grid-template-columns:64px 1fr auto;gap:var(--wp--preset--spacing--md);align-items:start;padding:var(--wp--preset--spacing--sm) 0;border-bottom:1px solid var(--wp--preset--color--border);}}
.wc-block-components-order-summary-item__image img{{display:block;width:64px;height:auto;border-radius:var(--wp--custom--radius--md);}}
.wc-block-components-order-summary-item__description{{font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.wc-block-components-order-summary-item__quantity{{position:static;background:transparent;color:var(--wp--preset--color--secondary);font-size:var(--wp--preset--font-size--xs);width:auto;height:auto;border:0;}}
.wp-block-woocommerce-order-confirmation-downloads table{{width:100%;border-collapse:collapse;font-size:var(--wp--preset--font-size--sm);}}
.wp-block-woocommerce-order-confirmation-downloads th,.wp-block-woocommerce-order-confirmation-downloads td{{padding:var(--wp--preset--spacing--md);border-bottom:1px solid var(--wp--preset--color--border);text-align:left;vertical-align:top;}}
.wp-block-woocommerce-order-confirmation-downloads thead th{{background:var(--wp--preset--color--subtle);font-weight:var(--wp--custom--font-weight--semibold);text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider);font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.wp-block-woocommerce-order-confirmation-downloads .button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease;}}
.wp-block-woocommerce-order-confirmation-downloads .button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.wp-block-woocommerce-order-confirmation-create-account form{{display:grid;gap:var(--wp--preset--spacing--md);padding:var(--wp--preset--spacing--lg);background:var(--wp--preset--color--subtle);border-radius:var(--wp--custom--radius--md);}}
.wp-block-woocommerce-order-confirmation-create-account label{{font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);}}
.wp-block-woocommerce-order-confirmation-create-account input[type=password],.wp-block-woocommerce-order-confirmation-create-account input[type=text]{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
.wp-block-woocommerce-order-confirmation-create-account input[type=submit],.wp-block-woocommerce-order-confirmation-create-account button[type=submit]{{background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--lg);font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;cursor:pointer;}}
.woocommerce-account .woocommerce{{display:grid;grid-template-columns:220px 1fr;gap:var(--wp--preset--spacing--2-xl);}}
.woocommerce-MyAccount-navigation ul{{list-style:none;padding:0;margin:0;display:grid;gap:0;}}
.woocommerce-MyAccount-navigation li{{margin:0;}}
.woocommerce-MyAccount-navigation a{{display:block;padding:var(--wp--preset--spacing--sm) 0;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);text-decoration:none;border-bottom:1px solid var(--wp--preset--color--border);transition:color 160ms ease;}}
.woocommerce-MyAccount-navigation .is-active a,.woocommerce-MyAccount-navigation a:hover{{color:var(--wp--preset--color--contrast);}}
.woocommerce-MyAccount-content{{font-size:var(--wp--preset--font-size--sm);color:var(--wp--preset--color--contrast);}}
.woocommerce-MyAccount-content h2,.woocommerce-MyAccount-content h3{{font-family:var(--wp--preset--font-family--display);font-weight:var(--wp--custom--font-weight--regular);}}
.woocommerce-orders-table,.woocommerce-table--order-details,.shop_table{{width:100%;border-collapse:collapse;font-size:var(--wp--preset--font-size--sm);}}
.woocommerce-orders-table th,.woocommerce-orders-table td,.woocommerce-table--order-details th,.woocommerce-table--order-details td{{padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);border-bottom:1px solid var(--wp--preset--color--border);text-align:left;}}
.woocommerce-orders-table thead th,.woocommerce-table--order-details thead th{{background:var(--wp--preset--color--subtle);font-weight:var(--wp--custom--font-weight--semibold);text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider);font-size:var(--wp--preset--font-size--xs);color:var(--wp--preset--color--secondary);}}
.woocommerce-orders-table .button,.woocommerce-MyAccount-content .button{{display:inline-flex;align-items:center;justify-content:center;font-family:var(--wp--preset--font-family--sans);font-size:var(--wp--preset--font-size--xs);font-weight:var(--wp--custom--font-weight--medium);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;background:var(--wp--preset--color--contrast);color:var(--wp--preset--color--base);border:1px solid var(--wp--preset--color--contrast);border-radius:var(--wp--custom--radius--pill);padding:var(--wp--preset--spacing--xs) var(--wp--preset--spacing--md);text-decoration:none;transition:background 160ms ease;}}
.woocommerce-MyAccount-content form .button:hover,.woocommerce-orders-table .button:hover{{background:var(--wp--preset--color--accent);border-color:var(--wp--preset--color--accent);}}
.woocommerce-EditAccountForm,.woocommerce-address-fields__field-wrapper{{display:grid;gap:var(--wp--preset--spacing--md);}}
.woocommerce-EditAccountForm label,.woocommerce-address-fields__field-wrapper label{{display:block;font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase;color:var(--wp--preset--color--secondary);margin-bottom:var(--wp--preset--spacing--2-xs);}}
.woocommerce-EditAccountForm input,.woocommerce-address-fields__field-wrapper input,.woocommerce-EditAccountForm select,.woocommerce-address-fields__field-wrapper select{{width:100%;background:var(--wp--preset--color--surface);border:1px solid var(--wp--preset--color--border);border-radius:var(--wp--custom--radius--md);padding:var(--wp--preset--spacing--sm) var(--wp--preset--spacing--md);font:inherit;color:var(--wp--preset--color--contrast);}}
@media (max-width:720px){{.woocommerce-account .woocommerce{{grid-template-columns:1fr;}}}}
{SENTINEL_CLOSE}"""


ANCHOR = "/* /archive-product polish */"


def append_for(theme: str) -> str:
    """Append the chunk to the END of styles.css, just before the closing
    JSON-string `"`. We do raw text manipulation rather than round-tripping
    json.loads/dumps because:
      * the existing minified styles.css uses one long line, hand-tuned
        whitespace, and embedded URL-encoded SVG; round-tripping would
        cause spurious formatting churn across the whole 50 KB file,
      * there is exactly one occurrence of the marker `/* /archive-product
        polish */` in each theme.json, and it appears immediately before
        the closing `"` of the styles.css JSON value (3 themes) or
        immediately before `",` (selvedge, which has another property
        following). Both cases are handled by anchoring on `"` after the
        marker.
    """
    path = ROOT / theme / "theme.json"
    text = path.read_text(encoding="utf-8")
    if SENTINEL_OPEN in text:
        return f"{theme}: already has wc-tells (skipped)"
    if text.count(ANCHOR) != 1:
        return f"{theme}: anchor {ANCHOR!r} missing or non-unique"
    # Flatten the CSS chunk to one line (matches existing minified style).
    flat = " ".join(line.strip() for line in CSS.splitlines() if line.strip())
    # JSON-escape the chunk: only `\\` and `"` need escaping in our CSS
    # (no control chars, no `/` requiring escape). The chevron SVG uses
    # single quotes inside, so the only `"` are the outer `url("...")`
    # delimiters, which become `\"` here.
    escaped = flat.replace("\\", "\\\\").replace('"', '\\"')
    # Splice the escaped chunk in just BEFORE the JSON-string closing `"`.
    # The marker line currently ends `... /* /archive-product polish */"`
    # (or `*/",`). We insert immediately after the marker and before the
    # closing `"`.
    needle = ANCHOR + '"'
    if needle not in text:
        return f"{theme}: closing quote after anchor not found"
    text = text.replace(needle, ANCHOR + escaped + '"', 1)
    path.write_text(text, encoding="utf-8")
    return f"{theme}: appended {len(flat)} chars (escaped {len(escaped)})"


def main(argv: list[str]) -> int:
    targets = argv[1:] or THEMES
    for t in targets:
        if t not in THEMES:
            print(f"unknown theme: {t}", file=sys.stderr)
            return 2
        print(append_for(t))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
