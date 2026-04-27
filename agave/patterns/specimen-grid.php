<?php
/**
 * Title: Specimen grid — three labelled cells
 * Slug: agave/specimen-grid
 * Categories: agave, featured
 * Block Types: core/post-content
 * Description: Herbarium-style three-cell grid — each cell holds one specimen
 *              image plus a fine-line caption (genus / species in italic, a
 *              single sensory note underneath). The rhythm echoes the product
 *              grid below so the page reads as one continuous catalog.
 * Keywords: specimen, grid, hero, herbarium, three-column
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","className":"agave-specimen-grid","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|md","right":"var:preset|spacing|md"},"blockGap":"var:preset|spacing|xl"}},"backgroundColor":"base","layout":{"type":"constrained","contentSize":"var(--wp--style--global--wide-size)"}} -->
<div class="wp-block-group alignfull agave-specimen-grid has-base-background-color has-background" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--md);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--md)">

	<!-- wp:group {"align":"wide","className":"agave-specimen-grid__intro","layout":{"type":"flex","flexWrap":"wrap","justifyContent":"space-between","verticalAlignment":"bottom"}} -->
	<div class="wp-block-group alignwide agave-specimen-grid__intro">
		<!-- wp:paragraph {"className":"agave-specimen-grid__eyebrow","fontSize":"xs","textColor":"accent","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var:custom|letter-spacing|widest"}}} -->
		<p class="agave-specimen-grid__eyebrow has-accent-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--widest);text-transform:uppercase"><?php esc_html_e( 'Pressings nº 01', 'agave' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:paragraph {"fontSize":"sm","textColor":"secondary"} -->
		<p class="has-secondary-color has-text-color has-sm-font-size"><a href="/shop"><?php esc_html_e( 'Catalog, in full →', 'agave' ); ?></a></p>
		<!-- /wp:paragraph -->
	</div>
	<!-- /wp:group -->

	<!-- wp:columns {"align":"wide","className":"agave-specimen-grid__cells","style":{"spacing":{"blockGap":{"top":"var:preset|spacing|2-xl","left":"var:preset|spacing|xl"}}}} -->
	<div class="wp-block-columns alignwide agave-specimen-grid__cells">
		<!-- wp:column {"style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"agave-specimen-grid__plate","style":{"spacing":{"padding":{"top":"var:preset|spacing|lg","bottom":"var:preset|spacing|lg","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}},"border":{"color":"var:preset|color|border","width":"1px","style":"solid"}},"backgroundColor":"surface","layout":{"type":"constrained"}} -->
			<div class="wp-block-group agave-specimen-grid__plate has-border-color has-surface-background-color has-background" style="border-color:var(--wp--preset--color--border);border-style:solid;border-width:1px;padding-top:var(--wp--preset--spacing--lg);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--lg);padding-left:var(--wp--preset--spacing--lg)">
				<!-- wp:image {"sizeSlug":"large","align":"center","style":{"border":{"radius":"0"}}} -->
				<figure class="wp-block-image aligncenter size-large has-custom-border"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-bottled-morning.jpg' ) ); ?>" alt="<?php esc_attr_e( 'Agave tequilana — a bottled specimen of warm morning light, terracotta label on cream paper.', 'agave' ); ?>" style="border-radius:0"/></figure>
				<!-- /wp:image -->
			</div>
			<!-- /wp:group -->

			<!-- wp:paragraph {"className":"agave-specimen-grid__caption","fontSize":"xs","textColor":"tertiary","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var:custom|letter-spacing|wider"}}} -->
			<p class="agave-specimen-grid__caption has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Plate I', 'agave' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:paragraph {"fontSize":"lg","style":{"typography":{"fontStyle":"italic","fontWeight":"400"}}} -->
			<p class="has-lg-font-size" style="font-style:italic;font-weight:400"><?php esc_html_e( 'Agave tequilana', 'agave' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:paragraph {"fontSize":"sm","textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color has-sm-font-size"><?php esc_html_e( 'Terracotta resin, bottled and stoppered by hand. Keep upright; pair with cream linen.', 'agave' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column {"style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"agave-specimen-grid__plate","style":{"spacing":{"padding":{"top":"var:preset|spacing|lg","bottom":"var:preset|spacing|lg","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}},"border":{"color":"var:preset|color|border","width":"1px","style":"solid"}},"backgroundColor":"surface","layout":{"type":"constrained"}} -->
			<div class="wp-block-group agave-specimen-grid__plate has-border-color has-surface-background-color has-background" style="border-color:var(--wp--preset--color--border);border-style:solid;border-width:1px;padding-top:var(--wp--preset--spacing--lg);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--lg);padding-left:var(--wp--preset--spacing--lg)">
				<!-- wp:image {"sizeSlug":"large","align":"center","style":{"border":{"radius":"0"}}} -->
				<figure class="wp-block-image aligncenter size-large has-custom-border"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-borrowed-nostalgia.jpg' ) ); ?>" alt="<?php esc_attr_e( 'Opuntia ficus-indica — borrowed nostalgia, sage and dust-pink, pressed on warm paper.', 'agave' ); ?>" style="border-radius:0"/></figure>
				<!-- /wp:image -->
			</div>
			<!-- /wp:group -->

			<!-- wp:paragraph {"className":"agave-specimen-grid__caption","fontSize":"xs","textColor":"tertiary","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var:custom|letter-spacing|wider"}}} -->
			<p class="agave-specimen-grid__caption has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Plate II', 'agave' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:paragraph {"fontSize":"lg","style":{"typography":{"fontStyle":"italic","fontWeight":"400"}}} -->
			<p class="has-lg-font-size" style="font-style:italic;font-weight:400"><?php esc_html_e( 'Opuntia ficus-indica', 'agave' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:paragraph {"fontSize":"sm","textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color has-sm-font-size"><?php esc_html_e( 'Sage-green pad, dust-pink bloom. A quiet thing to keep by a window where the light drifts.', 'agave' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column {"style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"agave-specimen-grid__plate","style":{"spacing":{"padding":{"top":"var:preset|spacing|lg","bottom":"var:preset|spacing|lg","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}},"border":{"color":"var:preset|color|border","width":"1px","style":"solid"}},"backgroundColor":"surface","layout":{"type":"constrained"}} -->
			<div class="wp-block-group agave-specimen-grid__plate has-border-color has-surface-background-color has-background" style="border-color:var(--wp--preset--color--border);border-style:solid;border-width:1px;padding-top:var(--wp--preset--spacing--lg);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--lg);padding-left:var(--wp--preset--spacing--lg)">
				<!-- wp:image {"sizeSlug":"large","align":"center","style":{"border":{"radius":"0"}}} -->
				<figure class="wp-block-image aligncenter size-large has-custom-border"><img src="<?php echo esc_url( get_theme_file_uri( 'playground/images/product-wo-deja-vu-session.jpg' ) ); ?>" alt="<?php esc_attr_e( 'Yucca filamentosa — a déjà-vu session, fine-line spines drawn in terracotta ink.', 'agave' ); ?>" style="border-radius:0"/></figure>
				<!-- /wp:image -->
			</div>
			<!-- /wp:group -->

			<!-- wp:paragraph {"className":"agave-specimen-grid__caption","fontSize":"xs","textColor":"tertiary","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var:custom|letter-spacing|wider"}}} -->
			<p class="agave-specimen-grid__caption has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Plate III', 'agave' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:paragraph {"fontSize":"lg","style":{"typography":{"fontStyle":"italic","fontWeight":"400"}}} -->
			<p class="has-lg-font-size" style="font-style:italic;font-weight:400"><?php esc_html_e( 'Yucca filamentosa', 'agave' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:paragraph {"fontSize":"sm","textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color has-sm-font-size"><?php esc_html_e( 'Filament and fine line — the sharpest of the three, ruled against cream stock in ink.', 'agave' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->
