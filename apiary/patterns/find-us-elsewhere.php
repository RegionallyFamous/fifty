<?php
/**
 * Title: Find us elsewhere
 * Slug: apiary/find-us-elsewhere
 * Categories: apiary, call-to-action
 * Block Types: core/post-content
 * Description: A quiet social-icons cluster pointing at the studio's outside-the-shop spaces. All real outbound links via core/social-links — no inbox capture, nothing to integrate later.
 * Keywords: social, instagram, follow, contact
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"contrast","textColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"},"blockGap":"var:preset|spacing|sm"}},"layout":{"type":"constrained","contentSize":"var(--wp--custom--layout--comfortable)"}} -->
<div class="wp-block-group alignfull has-base-color has-contrast-background-color has-text-color has-background" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center","level":2,"textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"0"}}}} -->
	<h2 class="wp-block-heading has-text-align-center has-base-color has-text-color" style="margin-top:0;margin-bottom:0"><?php esc_html_e( 'Between the hives and the bench.', 'apiary' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:paragraph {"align":"center","textColor":"base","style":{"spacing":{"margin":{"top":"0","bottom":"var:preset|spacing|md"}}}} -->
	<p class="has-text-align-center has-base-color has-text-color" style="margin-top:0;margin-bottom:var(--wp--preset--spacing--md)"><?php esc_html_e( 'Forage logs, spring-harvest photos, and the odd bee-yard video live on the channels below. Slow posts, and only when there is something worth saying.', 'apiary' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:social-links {"iconColor":"base","iconColorValue":"var(--wp--preset--color--base)","openInNewTab":true,"size":"has-normal-icon-size","className":"is-style-logos-only","layout":{"type":"flex","justifyContent":"center"}} -->
	<ul class="wp-block-social-links has-normal-icon-size has-icon-color is-style-logos-only">
		<!-- wp:social-link {"url":"https://instagram.com/","service":"instagram","label":"Instagram"} /-->
		<!-- wp:social-link {"url":"https://www.are.na/","service":"feed","label":"Are.na journal"} /-->
		<!-- wp:social-link {"url":"/contact/","service":"mail","label":"Email the studio"} /-->
		<!-- wp:social-link {"url":"/feed/","service":"feed","label":"RSS feed"} /-->
	</ul>
	<!-- /wp:social-links -->
</div>
<!-- /wp:group -->
