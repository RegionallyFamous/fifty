<?php
/**
 * Title: FAQ accordion
 * Slug: atomic/faq-accordion
 * Categories: atomic
 * Block Types: core/post-content
 * Description: Five-item FAQ section using the core Accordion block. Replace the questions and answers.
 * Keywords: faq, questions, accordion, support
 * Viewport Width: 1024
 */
?>
<!-- wp:group {"style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl"},"blockGap":"var:preset|spacing|xl"}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group" style="padding-top:var(--wp--preset--spacing--2-xl);padding-bottom:var(--wp--preset--spacing--2-xl)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'Countdown questions', 'atomic' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:accordion -->
	<div role="group" class="wp-block-accordion">
		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'How long until the capsule reaches my door?', 'atomic' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Most capsules launch within one or two working days and land inside the week.', 'atomic' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'What if the payload misses its mark?', 'atomic' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Every capsule may be returned to the pad, freight prepaid, within thirty days of splashdown.', 'atomic' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'Do you send capsules beyond the continental orbit?', 'atomic' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'We launch worldwide. Trans-orbital freight is calculated at the console at the moment of payment.', 'atomic' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'Can I track the mission in flight?', 'atomic' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'A mission number is transmitted to your flight deck the moment the courier clears the pad.', 'atomic' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->

		<!-- wp:accordion-item -->
		<div class="wp-block-accordion-item">
			<!-- wp:accordion-heading -->
			<h3 class="wp-block-accordion-heading"><button type="button" class="wp-block-accordion-heading__toggle"><span class="wp-block-accordion-heading__toggle-title"><?php esc_html_e( 'How do I hail ground control?', 'atomic' ); ?></span><span class="wp-block-accordion-heading__toggle-icon" aria-hidden="true">+</span></button></h3>
			<!-- /wp:accordion-heading -->

			<!-- wp:accordion-panel -->
			<div role="region" class="wp-block-accordion-panel">
				<!-- wp:paragraph -->
				<p><?php esc_html_e( 'Send a signal to help@example.com &mdash; the console is staffed Mondays through Fridays, and every signal is answered inside a working day.', 'atomic' ); ?></p>
				<!-- /wp:paragraph -->
			</div>
			<!-- /wp:accordion-panel -->
		</div>
		<!-- /wp:accordion-item -->
	</div>
	<!-- /wp:accordion -->
</div>
<!-- /wp:group -->
