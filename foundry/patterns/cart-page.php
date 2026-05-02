<?php
/**
 * Title: Cart page
 * Slug: foundry/cart-page
 * Categories: foundry, woo-commerce
 * Block Types: woocommerce/cart
 * Description: Controlled WC Cart block tree for the storefront Cart page. Removes the default "Customers also bought" cross-sells inner block (a hard generic-WC tell that does not match an editorial storefront), keeps the cart-totals + accepted-payment-methods sidebar, and replaces the default empty-cart-block content with a branded eyebrow + display heading + 2 CTAs in Foundry's quiet-editorial voice. Targets `woocommerce/cart` so the Cart block placeholder picker offers it; also drives the seeded Cart page in `playground/wo-configure.php` so the demo and a real install (Proprietor inserts the pattern in the editor) render the same chrome.
 * Keywords: cart, basket, woocommerce, empty-cart, checkout
 * Viewport Width: 1280
 * Inserter: true
 */
?>
<!-- wp:woocommerce/cart {"align":"wide"} -->
<div class="wp-block-woocommerce-cart alignwide is-loading"><!-- wp:woocommerce/filled-cart-block -->
<div class="wp-block-woocommerce-filled-cart-block"><!-- wp:woocommerce/cart-items-block -->
<div class="wp-block-woocommerce-cart-items-block"><!-- wp:woocommerce/cart-line-items-block -->
<div class="wp-block-woocommerce-cart-line-items-block"></div>
<!-- /wp:woocommerce/cart-line-items-block --></div>
<!-- /wp:woocommerce/cart-items-block -->

<!-- wp:woocommerce/cart-totals-block -->
<div class="wp-block-woocommerce-cart-totals-block"><!-- wp:woocommerce/cart-order-summary-block -->
<div class="wp-block-woocommerce-cart-order-summary-block"></div>
<!-- /wp:woocommerce/cart-order-summary-block -->

<!-- wp:woocommerce/cart-express-payment-block -->
<div class="wp-block-woocommerce-cart-express-payment-block"></div>
<!-- /wp:woocommerce/cart-express-payment-block -->

<!-- wp:woocommerce/proceed-to-checkout-block -->
<div class="wp-block-woocommerce-proceed-to-checkout-block"></div>
<!-- /wp:woocommerce/proceed-to-checkout-block -->

<!-- wp:woocommerce/cart-accepted-payment-methods-block -->
<div class="wp-block-woocommerce-cart-accepted-payment-methods-block"></div>
<!-- /wp:woocommerce/cart-accepted-payment-methods-block --></div>
<!-- /wp:woocommerce/cart-totals-block --></div>
<!-- /wp:woocommerce/filled-cart-block -->

<!-- wp:woocommerce/empty-cart-block -->
<div class="wp-block-woocommerce-empty-cart-block wo-empty wo-empty--cart"><!-- wp:paragraph {"align":"center","className":"wo-empty__eyebrow","fontSize":"xs","textColor":"secondary","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var:custom|letter-spacing|wider"},"spacing":{"margin":{"bottom":"0"}}}} -->
<p class="has-text-align-center has-secondary-color has-text-color has-xs-font-size wo-empty__eyebrow" style="text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider);margin-bottom:0"><?php esc_html_e( 'Cart', 'foundry' ); ?></p>
<!-- /wp:paragraph -->

<!-- wp:heading {"textAlign":"center","level":2,"className":"wo-empty__title","fontSize":"3xl","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|tight"},"spacing":{"margin":{"top":"0","bottom":"0"}}}} -->
<h2 class="wp-block-heading has-text-align-center has-3-xl-font-size wo-empty__title" style="margin-top:0;margin-bottom:0;letter-spacing:var(--wp--custom--letter-spacing--tight)"><?php esc_html_e( 'The ledger is, for the moment, bare.', 'foundry' ); ?></h2>
<!-- /wp:heading -->

<!-- wp:paragraph {"align":"center","className":"wo-empty__lede","textColor":"secondary"} -->
<p class="has-text-align-center has-secondary-color has-text-color wo-empty__lede"><?php esc_html_e( 'Along the shelves, or pick up a thread you left in the journal.', 'foundry' ); ?></p>
<!-- /wp:paragraph -->

<!-- wp:buttons {"layout":{"type":"flex","justifyContent":"center"},"style":{"spacing":{"margin":{"top":"var:preset|spacing|md"}}}} -->
<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--md)"><!-- wp:button -->
<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="/shop/"><?php esc_html_e( 'Back to the shelves', 'foundry' ); ?></a></div>
<!-- /wp:button -->

<!-- wp:button {"className":"is-style-outline"} -->
<div class="wp-block-button is-style-outline"><a class="wp-block-button__link wp-element-button" href="/journal/"><?php esc_html_e( 'Open the compounding journal', 'foundry' ); ?></a></div>
<!-- /wp:button --></div>
<!-- /wp:buttons --></div>
<!-- /wp:woocommerce/empty-cart-block --></div>
<!-- /wp:woocommerce/cart -->
