<?php
/**
 * Title: Four-column footer with site map
 * Slug: aero/footer-columns
 * Categories: aero, footer
 * Block Types: core/template-part/footer
 * Description: Replacement footer with shop, support, about, and legal columns. Drop into the footer template part.
 * Keywords: footer, columns, sitemap
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"tagName":"footer","align":"full","backgroundColor":"subtle","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<footer class="wp-block-group alignfull has-subtle-background-color has-background" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:columns {"align":"wide"} -->
	<div class="wp-block-columns alignwide">
		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:site-title {"level":3,"fontSize":"lg"} /-->
			<!-- wp:site-tagline /-->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":4,"fontSize":"sm","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|wider","textTransform":"uppercase"}}} -->
			<h4 class="wp-block-heading has-sm-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Shop', 'aero' ); ?></h4>
			<!-- /wp:heading -->
			<!-- wp:page-list {"isNavigationChild":false,"openSubmenusOnClick":false,"showSubmenuIcon":false} /-->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":4,"fontSize":"sm","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|wider","textTransform":"uppercase"}}} -->
			<h4 class="wp-block-heading has-sm-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Support', 'aero' ); ?></h4>
			<!-- /wp:heading -->
			<!-- wp:paragraph -->
			<p><a href="#"><?php esc_html_e( 'Contact', 'aero' ); ?></a></p>
			<!-- /wp:paragraph -->
			<!-- wp:paragraph -->
			<p><a href="#"><?php esc_html_e( 'Shipping', 'aero' ); ?></a></p>
			<!-- /wp:paragraph -->
			<!-- wp:paragraph -->
			<p><a href="#"><?php esc_html_e( 'Returns', 'aero' ); ?></a></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":4,"fontSize":"sm","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|wider","textTransform":"uppercase"}}} -->
			<h4 class="wp-block-heading has-sm-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Legal', 'aero' ); ?></h4>
			<!-- /wp:heading -->
			<!-- wp:paragraph -->
			<p><a href="#"><?php esc_html_e( 'Privacy', 'aero' ); ?></a></p>
			<!-- /wp:paragraph -->
			<!-- wp:paragraph -->
			<p><a href="#"><?php esc_html_e( 'Terms', 'aero' ); ?></a></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->

	<!-- wp:separator {"className":"is-style-wide"} -->
	<hr class="wp-block-separator has-alpha-channel-opacity is-style-wide"/>
	<!-- /wp:separator -->

	<!-- wp:paragraph {"align":"center","fontSize":"xs","textColor":"tertiary"} -->
	<p class="has-text-align-center has-tertiary-color has-text-color has-xs-font-size">&copy; <?php echo esc_html( gmdate( 'Y' ) ); ?> <?php echo esc_html( get_bloginfo( 'name' ) ); ?></p>
	<!-- /wp:paragraph -->
</footer>
<!-- /wp:group -->
