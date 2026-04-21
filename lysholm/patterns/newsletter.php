<?php
/**
 * Title: Newsletter signup
 * Slug: lysholm/newsletter
 * Categories: lysholm, call-to-action
 * Block Types: core/post-content
 * Description: Inline newsletter call-out. Connect a real form provider when wiring up; this is a visual placeholder using the core Search block as a stand-in.
 * Keywords: newsletter, signup, email, subscribe
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"contrast","textColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained","contentSize":"var(--wp--custom--layout--comfortable)"}} -->
<div class="wp-block-group alignfull has-base-color has-contrast-background-color has-text-color has-background" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center","level":2,"textColor":"base"} -->
	<h2 class="wp-block-heading has-text-align-center has-base-color has-text-color"><?php esc_html_e( 'A quiet note from the studio.', 'lysholm' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:paragraph {"align":"center","textColor":"base","style":{"spacing":{"margin":{"bottom":"var:preset|spacing|md"}}}} -->
	<p class="has-text-align-center has-base-color has-text-color" style="margin-bottom:var(--wp--preset--spacing--md)"><?php esc_html_e( 'A short letter once in a while, when a new piece arrives or a maker shares a story. Easy to leave whenever it\'s no longer welcome.', 'lysholm' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:search <?php echo wp_json_encode( array(
		'label'          => __( 'Your address', 'lysholm' ),
		'showLabel'      => false,
		'placeholder'    => __( 'name@quiet.example', 'lysholm' ),
		'buttonText'     => __( 'Subscribe', 'lysholm' ),
		'buttonPosition' => 'button-inside',
		'buttonUseIcon'  => false,
		'align'          => 'center',
	) ); ?> /-->
</div>
<!-- /wp:group -->
