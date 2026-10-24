<?php
/**
 * Single product template.
 *
 * Keeps WooCommerce's well-tested markup but reframes it inside the theme's
 * editorial shell: breadcrumbs, a two-column layout and a matched summary.
 *
 * @package Urumi_Supply
 */

get_header( 'shop' );

while ( have_posts() ) :
	the_post();
	?>
	<section class="product-hero">
		<div class="shell">
			<?php woocommerce_output_all_notices(); ?>
			<?php woocommerce_breadcrumb( array( 'wrap_before' => '<nav class="breadcrumbs" aria-label="Breadcrumb">', 'wrap_after' => '</nav>' ) ); ?>
		</div>
	</section>

	<div class="shell product-layout">
		<div class="product-gallery">
			<?php
			do_action( 'woocommerce_before_single_product' );
			/**
			 * @hooked woocommerce_show_product_images - 20
			 */
			do_action( 'woocommerce_before_single_product_summary' );
			?>
			<?php woocommerce_show_product_images(); ?>
		</div>

		<div class="product-summary">
			<?php
			do_action( 'woocommerce_single_product_summary' );
			do_action( 'woocommerce_after_single_product' );
			?>
		</div>
	</div>

	<section class="section section-sunken">
		<div class="shell">
			<?php
			$related = new WP_Query(
				array(
					'post_type'      => 'product',
					'posts_per_page' => 4,
					'post_status'    => 'publish',
					'no_found_rows'  => true,
					'post__not_in'   => array( get_the_ID() ),
				)
			);

			if ( $related->have_posts() ) :
				?>
				<header class="section-head">
					<div>
						<p class="eyebrow"><?php esc_html_e( 'You may also like', 'urumi-supply' ); ?></p>
						<h2 class="section-title"><?php esc_html_e( 'More from the collection', 'urumi-supply' ); ?></h2>
					</div>
				</header>
				<div class="product-grid">
					<?php
					while ( $related->have_posts() ) :
						$related->the_post();
						get_template_part( 'template-parts/product-card' );
					endwhile;
					wp_reset_postdata();
					?>
				</div>
				<?php
			endif;
			?>
		</div>
	</section>
	<?php
endwhile;

get_footer( 'shop' );
