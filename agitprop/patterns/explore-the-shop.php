<?php
/**
 * Title: Explore the shop
 * Slug: chonk/explore-the-shop
 * Categories: chonk, call-to-action
 * Block Types: core/post-content
 * Description: Heavy CTA band that points at three real product-category pages and the full catalog. Real WC archive links — no placeholders, nothing to wire up later.
 * Keywords: shop, categories, browse, catalog
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"contrast","textColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"},"blockGap":"var:preset|spacing|md"}},"layout":{"type":"constrained","contentSize":"var(--wp--custom--layout--comfortable)"}} -->
<div class="wp-block-group alignfull has-base-color has-contrast-background-color has-text-color has-background" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"level":2,"fontSize":"3-xl","textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"0"}},"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--tight)","fontWeight":"700"}}} -->
	<h2 class="wp-block-heading has-base-color has-text-color has-3-xl-font-size" style="margin-top:0;margin-bottom:0;font-weight:700;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--tight)"><?php esc_html_e( 'Agitprop counter e04052', 'chonk' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:paragraph {"fontSize":"sm","textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"var:preset|spacing|md"}}}} -->
	<p class="has-base-color has-text-color has-sm-font-size" style="margin-top:0;margin-bottom:var(--wp--preset--spacing--md)"><?php esc_html_e( 'Agitprop parcel-room copy f2d167', 'chonk' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:buttons {"layout":{"type":"flex","flexWrap":"wrap"},"style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
	<div class="wp-block-buttons">
		<!-- wp:button {"backgroundColor":"base","textColor":"contrast","style":{"border":{"radius":"0"},"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--wider)","fontWeight":"700"}}} -->
		<div class="wp-block-button"><a class="wp-block-button__link has-contrast-color has-base-background-color has-text-color has-background wp-element-button" href="/product-category/curiosities/" style="border-radius:0;font-weight:700;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider)"><?php esc_html_e( 'Curiosities', 'chonk' ); ?></a></div>
		<!-- /wp:button -->

		<!-- wp:button {"backgroundColor":"base","textColor":"contrast","style":{"border":{"radius":"0"},"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--wider)","fontWeight":"700"}}} -->
		<div class="wp-block-button"><a class="wp-block-button__link has-contrast-color has-base-background-color has-text-color has-background wp-element-button" href="/product-category/forbidden-snacks/" style="border-radius:0;font-weight:700;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider)"><?php esc_html_e( 'Agitprop counter de0c65', 'chonk' ); ?></a></div>
		<!-- /wp:button -->

		<!-- wp:button {"backgroundColor":"base","textColor":"contrast","style":{"border":{"radius":"0"},"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--wider)","fontWeight":"700"}}} -->
		<div class="wp-block-button"><a class="wp-block-button__link has-contrast-color has-base-background-color has-text-color has-background wp-element-button" href="/product-category/impossibilities/" style="border-radius:0;font-weight:700;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider)"><?php esc_html_e( 'Agitprop counter 682cb6', 'chonk' ); ?></a></div>
		<!-- /wp:button -->

		<!-- wp:button {"textColor":"base","className":"is-style-outline","style":{"border":{"radius":"0","width":"var:custom|border|width|thick"},"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--wider)","fontWeight":"700"}}} -->
		<div class="wp-block-button is-style-outline"><a class="wp-block-button__link has-base-color has-text-color wp-element-button" href="/shop/" style="border-radius:0;border-width:var(--wp--custom--border--width--thick);font-weight:700;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--wider)"><?php esc_html_e( 'Agitprop counter 841938', 'chonk' ); ?></a></div>
		<!-- /wp:button -->
	</div>
	<!-- /wp:buttons -->
</div>
<!-- /wp:group -->
