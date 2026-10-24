<?php
/**
 * Search results template.
 *
 * @package Urumi_Supply
 */

get_header();

// WordPress excludes products from the site search, so the storefront runs its
// own product query and renders the matching items as a product grid.
$urumi_products = new WP_Query(
	array(
		'post_type'      => 'product',
		'post_status'    => 'publish',
		's'              => get_search_query(),
		'posts_per_page' => 12,
	)
);
?>

<section class="page-hero">
	<div class="shell">
		<p class="eyebrow"><?php esc_html_e( 'Search', 'urumi-supply' ); ?></p>
		<h1 class="page-hero-title">
			<?php
			printf(
				/* translators: %s: search term. */
				esc_html__( 'Results for “%s”', 'urumi-supply' ),
				esc_html( get_search_query() )
			);
			?>
		</h1>
		<p class="page-hero-note">
			<?php
			printf(
				/* translators: %d: number of matching products. */
				esc_html(
					_n(
						'%d product found.',
						'%d products found.',
						(int) $urumi_products->found_posts,
						'urumi-supply'
					)
				),
				(int) $urumi_products->found_posts
			);
			?>
		</p>
	</div>
</section>

<section class="section">
	<div class="shell">
		<?php if ( $urumi_products->have_posts() ) : ?>
			<div class="product-grid">
				<?php
				while ( $urumi_products->have_posts() ) :
					$urumi_products->the_post();
					get_template_part( 'template-parts/product-card' );
				endwhile;
				?>
			</div>
		<?php endif; ?>

		<?php if ( have_posts() ) : ?>
			<div class="post-grid">
				<?php
				while ( have_posts() ) :
					the_post();
					?>
					<article <?php post_class( 'post-card' ); ?>>
						<h2 class="post-card-title">
							<a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
						</h2>
						<p class="post-card-excerpt"><?php echo esc_html( wp_trim_words( get_the_excerpt(), 24 ) ); ?></p>
					</article>
					<?php
				endwhile;
				?>
			</div>
		<?php endif; ?>

		<?php if ( ! $urumi_products->have_posts() && ! have_posts() ) : ?>
			<p class="empty-note">
				<?php esc_html_e( 'No matches. Try a shorter phrase, or browse the full collection.', 'urumi-supply' ); ?>
			</p>
			<p>
				<a class="btn btn-primary" href="<?php echo esc_url( wc_get_page_permalink( 'shop' ) ); ?>">
					<?php esc_html_e( 'Shop all products', 'urumi-supply' ); ?>
				</a>
			</p>
		<?php endif; ?>
	</div>
</section>

<?php
get_footer();
