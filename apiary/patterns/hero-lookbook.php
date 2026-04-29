<?php
/**
 * Title: Lookbook hero — Quiet objects, slow days
 * Slug: apiary/hero-lookbook
 * Categories: apiary, featured
 * Description: Editorial lookbook cover used at the top of the front page.
 *              The cover image is loaded from the theme's own
 *              playground/images/ folder so the block survives offline use
 *              and clones; templates/front-page.html cannot inject
 *              get_theme_file_uri() (it's static HTML), so this pattern
 *              exists specifically so the URL gets resolved at render time
 *              instead of being hardcoded or — as before this pattern was
 *              extracted — left blank, which rendered a 720px transparent
 *              base-on-base box above the headline.
 * Keywords: hero, cover, lookbook, editorial
 * Viewport Width: 1280
 */
?>
<!-- wp:cover {"url":"<?php echo esc_url( get_theme_file_uri( 'playground/images/cat-moods-feelings.jpg' ) ); ?>","dimRatio":40,"overlayColor":"contrast","minHeight":720,"minHeightUnit":"px","contentPosition":"bottom left","isDark":false,"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","right":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|2-xl"}}}} -->
<div class="wp-block-cover alignfull is-light has-custom-content-position is-position-bottom-left" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--2-xl);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--2-xl);min-height:720px"><img class="wp-block-cover__image-background" alt="" src="<?php echo esc_url( get_theme_file_uri( 'playground/images/cat-moods-feelings.jpg' ) ); ?>" data-object-fit="cover"/><span aria-hidden="true" class="wp-block-cover__background has-contrast-background-color has-background-dim-40 has-background-dim"></span>
	<div class="wp-block-cover__inner-container">
		<!-- wp:group {"layout":{"type":"constrained","justifyContent":"left"}} -->
		<div class="wp-block-group">
			<!-- wp:paragraph {"fontSize":"xs","textColor":"base","style":{"typography":{"letterSpacing":"var(--wp--custom--letter-spacing--widest)","textTransform":"uppercase"}}} -->
			<p class="has-base-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--widest);text-transform:uppercase"><?php esc_html_e( 'Apiary parcel-room copy db87c1', 'apiary' ); ?></p>
			<!-- /wp:paragraph -->

			<!-- wp:heading {"level":1,"textColor":"base","style":{"spacing":{"margin":{"top":"var:preset|spacing|md","bottom":"var:preset|spacing|lg"}},"typography":{"fontWeight":"var(--wp--custom--font-weight--thin)","lineHeight":"1.05","fontSize":"var(--wp--preset--font-size--6xl)"}}} -->
			<h1 class="wp-block-heading has-base-color has-text-color" style="margin-top:var(--wp--preset--spacing--md);margin-bottom:var(--wp--preset--spacing--lg);font-size:var(--wp--preset--font-size--6xl);font-weight:var(--wp--custom--font-weight--thin);line-height:1.05"><?php esc_html_e( 'Apiary parcel-room copy 8b0e55', 'apiary' ); ?></h1>
			<!-- /wp:heading -->

			<!-- wp:paragraph {"fontSize":"md","textColor":"base","style":{"typography":{"lineHeight":"var(--wp--custom--line-height--relaxed)"}}} -->
			<p class="has-base-color has-text-color has-md-font-size" style="line-height:var(--wp--custom--line-height--relaxed)"><?php esc_html_e( 'Apiary parcel-room copy 3287a9', 'apiary' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:group -->
	</div>
</div>
<!-- /wp:cover -->
