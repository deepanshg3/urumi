<?php
/**
 * Single post template.
 *
 * @package Urumi_Supply
 */

get_header();

while ( have_posts() ) :
	the_post();
	?>
	<section class="page-hero">
		<div class="shell">
			<p class="eyebrow"><?php echo esc_html( get_the_date() ); ?></p>
			<h1 class="page-hero-title"><?php the_title(); ?></h1>
		</div>
	</section>

	<section class="section">
		<div class="shell prose">
			<?php
			if ( has_post_thumbnail() ) {
				the_post_thumbnail( 'large', array( 'class' => 'single-image' ) );
			}

			the_content();
			?>
		</div>
	</section>
	<?php
endwhile;

get_footer();
