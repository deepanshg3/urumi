<?php
/**
 * Single page template.
 *
 * @package Urumi_Supply
 */

get_header();

while ( have_posts() ) :
	the_post();
	?>
	<section class="page-hero">
		<div class="shell">
			<p class="eyebrow"><?php esc_html_e( 'Urumi Supply', 'urumi-supply' ); ?></p>
			<h1 class="page-hero-title"><?php the_title(); ?></h1>
		</div>
	</section>

	<section class="section">
		<div class="shell prose">
			<?php
			the_content();

			wp_link_pages(
				array(
					'before' => '<div class="page-links">',
					'after'  => '</div>',
				)
			);
			?>
		</div>
	</section>
	<?php
endwhile;

get_footer();
