<?php
/**
 * Title: Latest dispatch
 * Slug: aero/latest-dispatch
 * Categories: aero, call-to-action
 * Block Types: core/post-content
 * Description: Pulls the most recent blog post into a chrome-framed card via core/query — real wp_query, real permalink, no fake email field. Updates itself whenever a new post lands.
 * Keywords: blog, post, latest, news, dispatch
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"contrast","textColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"},"blockGap":"var:preset|spacing|md"}},"layout":{"type":"constrained","contentSize":"var(--wp--custom--layout--comfortable)"}} -->
<div class="wp-block-group alignfull has-base-color has-contrast-background-color has-text-color has-background" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:paragraph {"align":"center","fontSize":"xs","textColor":"base","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--widest)"},"spacing":{"margin":{"bottom":"0"}}}} -->
	<p class="has-text-align-center has-base-color has-text-color has-xs-font-size" style="margin-bottom:0;text-transform:uppercase;letter-spacing:var(--wp--custom--letter-spacing--widest)"><?php esc_html_e( 'Now broadcasting', 'aero' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:heading {"textAlign":"center","level":2,"textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"var:preset|spacing|md"}}}} -->
	<h2 class="wp-block-heading has-text-align-center has-base-color has-text-color" style="margin-top:0;margin-bottom:var(--wp--preset--spacing--md)"><?php esc_html_e( 'Tune in to the latest dispatch.', 'aero' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:query {"queryId":42,"query":{"perPage":1,"pages":0,"offset":0,"postType":"post","order":"desc","orderBy":"date","author":"","search":"","exclude":[],"sticky":"","inherit":false},"align":"wide"} -->
	<div class="wp-block-query alignwide">
		<!-- wp:post-template {"layout":{"type":"default"}} -->
			<!-- wp:group {"backgroundColor":"base","textColor":"contrast","style":{"spacing":{"padding":{"top":"var:preset|spacing|lg","bottom":"var:preset|spacing|lg","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"},"blockGap":"var:preset|spacing|sm"},"border":{"radius":"var:custom|radius|lg"}},"layout":{"type":"constrained"}} -->
			<div class="wp-block-group has-contrast-color has-base-background-color has-text-color has-background" style="border-radius:var(--wp--custom--radius--lg);padding-top:var(--wp--preset--spacing--lg);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--lg);padding-left:var(--wp--preset--spacing--lg)">
				<!-- wp:post-date {"isLink":false,"fontSize":"xs","textColor":"tertiary","style":{"typography":{"textTransform":"uppercase","letterSpacing":"var(--wp--custom--letter-spacing--wider)"},"spacing":{"margin":{"bottom":"0"}}}} /-->

				<!-- wp:post-title {"isLink":true,"level":2,"fontSize":"2-xl","style":{"spacing":{"margin":{"top":"0","bottom":"var:preset|spacing|2-xs"}}}} /-->

				<!-- wp:post-excerpt {"moreText":"Open the full dispatch →","fontSize":"sm","textColor":"secondary"} /-->
			</div>
			<!-- /wp:group -->
		<!-- /wp:post-template -->

		<!-- wp:query-no-results -->
			<!-- wp:paragraph {"align":"center","textColor":"base"} -->
			<p class="has-text-align-center has-base-color has-text-color"><?php esc_html_e( 'Static on the line. Check back soon.', 'aero' ); ?></p>
			<!-- /wp:paragraph -->
		<!-- /wp:query-no-results -->
	</div>
	<!-- /wp:query -->
</div>
<!-- /wp:group -->
