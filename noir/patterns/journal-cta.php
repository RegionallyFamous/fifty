<?php
/**
 * Title: Journal call-to-action
 * Slug: noir/journal-cta
 * Categories: noir, call-to-action
 * Block Types: core/post-content
 * Description: Editorial dispatch block that links straight to the workshop journal page. Real anchor, real destination — no email field, no provider integration to defer.
 * Keywords: journal, dispatch, story, read more
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"contrast","textColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"},"blockGap":"var:preset|spacing|md"}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull has-base-color has-contrast-background-color has-text-color has-background" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:paragraph {"align":"center","fontSize":"xs","textColor":"tertiary","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--widest)"},"spacing":{"margin":{"bottom":"0"}}}} -->
	<p class="has-text-align-center has-tertiary-color has-text-color has-xs-font-size" style="margin-bottom:0;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--widest)"><?php esc_html_e( 'Bench notes', 'noir' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:heading {"textAlign":"center","level":2,"textColor":"base","fontSize":"3-xl","style":{"typography":{"fontStyle":"italic","fontWeight":"500","letterSpacing":"var(--wp--custom--letter-spacing--tight)"},"spacing":{"margin":{"top":"0","bottom":"0"}}}} -->
	<h2 class="wp-block-heading has-text-align-center has-base-color has-text-color has-3-xl-font-size" style="margin-top:0;margin-bottom:0;font-style:italic;font-weight:500;letter-spacing:var(--wp--custom--letter-spacing--tight)"><?php esc_html_e( 'A dispatch from the cutting table. Regular. Unannounced.', 'noir' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:paragraph {"align":"center","textColor":"base","style":{"spacing":{"margin":{"top":"0"}}}} -->
	<p class="has-text-align-center has-base-color has-text-color" style="margin-top:0"><?php esc_html_e( 'Every item in the ledger has a source, a maker, and a reason we keep going back. Read it any hour — no appointment, no cover.', 'noir' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:buttons {"layout":{"type":"flex","justifyContent":"center"},"style":{"spacing":{"margin":{"top":"var:preset|spacing|md"}}}} -->
	<div class="wp-block-buttons" style="margin-top:var(--wp--preset--spacing--md)">
		<!-- wp:button {"backgroundColor":"base","textColor":"contrast","style":{"border":{"radius":"0"},"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--wider)","fontSize":"var(--wp--preset--font-size--xs)"},"spacing":{"padding":{"top":"var:preset|spacing|sm","bottom":"var:preset|spacing|sm","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}}} -->
		<div class="wp-block-button"><a class="wp-block-button__link has-contrast-color has-base-background-color has-text-color has-background has-custom-font-size wp-element-button" href="/journal/" style="border-radius:0;padding-top:var(--wp--preset--spacing--sm);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--sm);padding-left:var(--wp--preset--spacing--lg);font-size:var(--wp--preset--font-size--xs);letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Pull the file →', 'noir' ); ?></a></div>
		<!-- /wp:button -->
	</div>
	<!-- /wp:buttons -->
</div>
<!-- /wp:group -->
