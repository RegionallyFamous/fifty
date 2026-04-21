<?php
/**
 * Title: Featured products grid
 * Slug: chonk/featured-products
 * Categories: chonk, woo-commerce
 * Block Types: core/post-content
 * Description: 3-column grid of featured products using the Product Collection block. Adjust the query attributes for your needs.
 * Keywords: products, collection, grid, shop, featured
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"wide","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"},"blockGap":"var:preset|spacing|xl"}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignwide" style="padding-top:var(--wp--preset--spacing--2-xl);padding-bottom:var(--wp--preset--spacing--2-xl)">
	<!-- wp:group {"layout":{"type":"flex","orientation":"vertical","justifyContent":"center"}} -->
	<div class="wp-block-group">
		<!-- wp:paragraph {"align":"center","fontSize":"xs","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|wider","textTransform":"uppercase"}},"textColor":"tertiary"} -->
		<p class="has-text-align-center has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Featured', 'chonk' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:heading {"textAlign":"center","level":2} -->
		<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'THIS SEASON\'s picks', 'chonk' ); ?></h2>
		<!-- /wp:heading -->
	</div>
	<!-- /wp:group -->

	<!-- wp:woocommerce/product-collection {"queryId":0,"query":{"perPage":3,"pages":0,"offset":0,"postType":"product","order":"desc","orderBy":"date","search":"","exclude":[],"inherit":false,"taxQuery":{},"isProductCollectionBlock":true,"featured":true,"woocommerceOnSale":false,"woocommerceStockStatus":["instock","outofstock","onbackorder"],"woocommerceAttributes":[],"woocommerceHandPickedProducts":[]},"tagName":"div","displayLayout":{"type":"flex","columns":3,"shrinkColumns":true},"queryContextIncludes":["collection"],"collection":"woocommerce/product-collection/featured"} -->
	<div class="wp-block-woocommerce-product-collection">
		<!-- wp:woocommerce/product-template -->
			<!-- wp:woocommerce/product-image {"showSaleBadge":true,"imageSizing":"thumbnail","isDescendentOfQueryLoop":true} /-->
			<!-- wp:post-title {"level":3,"isLink":true,"style":{"typography":{"fontSize":"var(--wp--preset--font-size--md)","fontWeight":"500","lineHeight":"var(--wp--custom--line-height--snug)"},"elements":{"link":{"color":{"text":"var(--wp--preset--color--contrast)"},":hover":{"color":{"text":"var(--wp--preset--color--accent)"}}}}}} /-->
			<!-- wp:woocommerce/product-price {"isDescendentOfSingleProductBlock":false} -->
			<div class="is-loading"></div>
			<!-- /wp:woocommerce/product-price -->
			<!-- wp:woocommerce/product-button {"isDescendentOfQueryLoop":true} /-->
		<!-- /wp:woocommerce/product-template -->

		<!-- wp:woocommerce/product-collection-no-results /-->
	</div>
	<!-- /wp:woocommerce/product-collection -->
</div>
<!-- /wp:group -->
