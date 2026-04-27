<?php
/**
 * Title: Shop-by-category tiles
 * Slug: agave/category-tiles
 * Categories: agave, woo-commerce
 * Block Types: core/post-content
 * Description: Three image tiles linking to top product categories. Replace images and labels with your own categories.
 * Keywords: categories, browse, shop, tiles, grid
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'Browse by category', 'agave' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:columns {"align":"wide","style":{"spacing":{"margin":{"top":"var:preset|spacing|xl"}}}} -->
	<div class="wp-block-columns alignwide" style="margin-top:var(--wp--preset--spacing--xl)">
		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:cover {"minHeight":320,"minHeightUnit":"px","overlayColor":"contrast","dimRatio":30,"contentPosition":"center center","style":{"spacing":{"padding":{"top":"var:preset|spacing|xl","bottom":"var:preset|spacing|xl"}},"border":{"radius":"var:custom|radius|md"}}} -->
			<div class="wp-block-cover" style="border-radius:var(--wp--custom--radius--md);padding-top:var(--wp--preset--spacing--xl);padding-bottom:var(--wp--preset--spacing--xl);min-height:320px"><span aria-hidden="true" class="wp-block-cover__background has-contrast-background-color has-background-dim-30 has-background-dim"></span><div class="wp-block-cover__inner-container">
				<!-- wp:heading {"textAlign":"center","level":3,"textColor":"base","fontSize":"xl"} -->
				<h3 class="wp-block-heading has-text-align-center has-base-color has-text-color has-xl-font-size"><?php esc_html_e( 'Apparel', 'agave' ); ?></h3>
				<!-- /wp:heading -->
			</div></div>
			<!-- /wp:cover -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:cover {"minHeight":320,"minHeightUnit":"px","overlayColor":"contrast","dimRatio":30,"contentPosition":"center center","style":{"spacing":{"padding":{"top":"var:preset|spacing|xl","bottom":"var:preset|spacing|xl"}},"border":{"radius":"var:custom|radius|md"}}} -->
			<div class="wp-block-cover" style="border-radius:var(--wp--custom--radius--md);padding-top:var(--wp--preset--spacing--xl);padding-bottom:var(--wp--preset--spacing--xl);min-height:320px"><span aria-hidden="true" class="wp-block-cover__background has-contrast-background-color has-background-dim-30 has-background-dim"></span><div class="wp-block-cover__inner-container">
				<!-- wp:heading {"textAlign":"center","level":3,"textColor":"base","fontSize":"xl"} -->
				<h3 class="wp-block-heading has-text-align-center has-base-color has-text-color has-xl-font-size"><?php esc_html_e( 'Accessories', 'agave' ); ?></h3>
				<!-- /wp:heading -->
			</div></div>
			<!-- /wp:cover -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:cover {"minHeight":320,"minHeightUnit":"px","overlayColor":"contrast","dimRatio":30,"contentPosition":"center center","style":{"spacing":{"padding":{"top":"var:preset|spacing|xl","bottom":"var:preset|spacing|xl"}},"border":{"radius":"var:custom|radius|md"}}} -->
			<div class="wp-block-cover" style="border-radius:var(--wp--custom--radius--md);padding-top:var(--wp--preset--spacing--xl);padding-bottom:var(--wp--preset--spacing--xl);min-height:320px"><span aria-hidden="true" class="wp-block-cover__background has-contrast-background-color has-background-dim-30 has-background-dim"></span><div class="wp-block-cover__inner-container">
				<!-- wp:heading {"textAlign":"center","level":3,"textColor":"base","fontSize":"xl"} -->
				<h3 class="wp-block-heading has-text-align-center has-base-color has-text-color has-xl-font-size"><?php esc_html_e( 'Sale', 'agave' ); ?></h3>
				<!-- /wp:heading -->
			</div></div>
			<!-- /wp:cover -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->
