<?php
/**
 * Front page.
 *
 * @package Urumi_Supply
 */

get_header();

$featured = new WP_Query(
	array(
		'post_type'           => 'product',
		'post_status'         => 'publish',
		'posts_per_page'      => 6,
		'ignore_sticky_posts' => true,
		'tax_query'           => array(
			array(
				'taxonomy' => 'product_visibility',
				'field'    => 'name',
				'terms'    => array( 'featured' ),
				'operator' => 'IN',
			),
		),
	)
);

if ( ! $featured->have_posts() ) {
	$featured = new WP_Query(
		array(
			'post_type'      => 'product',
			'post_status'    => 'publish',
			'posts_per_page' => 6,
			'no_found_rows'  => true,
		)
	);
}

$categories = get_terms(
	array(
		'taxonomy'   => 'product_cat',
		'hide_empty' => true,
		'number'     => 3,
		'orderby'    => 'count',
		'order'      => 'DESC',
	)
);
?>

<section class="hero">
	<div class="shell hero-grid">
		<div class="hero-copy">
			<p class="eyebrow"><?php esc_html_e( 'Spring edit · 2026', 'urumi-supply' ); ?></p>
			<h1 class="hero-title">
				<?php esc_html_e( 'Tools for the desk you actually use.', 'urumi-supply' ); ?>
			</h1>
			<p class="hero-lede">
				<?php esc_html_e( 'Twelve considered pieces — notebooks, organizers, totes and daily-carry goods — chosen to be used every day and kept for years.', 'urumi-supply' ); ?>
			</p>
			<div class="hero-actions">
				<a class="btn btn-primary btn-lg" href="<?php echo esc_url( wc_get_page_permalink( 'shop' ) ); ?>">
					<?php esc_html_e( 'Shop the collection', 'urumi-supply' ); ?>
				</a>
				<a class="btn btn-link" href="<?php echo esc_url( home_url( '/#story' ) ); ?>">
					<?php esc_html_e( 'Why Urumi', 'urumi-supply' ); ?>
				</a>
			</div>
			<dl class="hero-facts">
				<div>
					<dt><?php esc_html_e( 'Free shipping', 'urumi-supply' ); ?></dt>
					<dd><?php esc_html_e( 'On orders over $60', 'urumi-supply' ); ?></dd>
				</div>
				<div>
					<dt><?php esc_html_e( 'Returns', 'urumi-supply' ); ?></dt>
					<dd><?php esc_html_e( '30 days, no questions', 'urumi-supply' ); ?></dd>
				</div>
				<div>
					<dt><?php esc_html_e( 'Stock', 'urumi-supply' ); ?></dt>
					<dd><?php esc_html_e( 'Live from our warehouse', 'urumi-supply' ); ?></dd>
				</div>
			</dl>
		</div>

		<div class="hero-art" aria-hidden="true">
			<?php
			$hero_products = wc_get_products(
				array(
					'limit'   => 3,
					'orderby' => 'date',
					'order'   => 'DESC',
					'status'  => 'publish',
				)
			);

			$index = 0;
			foreach ( $hero_products as $hero_product ) {
				++$index;
				printf(
					'<figure class="hero-card hero-card-%d">',
					(int) $index
				);
				echo wp_kses_post( $hero_product->get_image( 'urumi-hero', array( 'class' => 'hero-image' ) ) );
				echo '<figcaption>' . esc_html( $hero_product->get_name() ) . '</figcaption>';
				echo '</figure>';
			}
			?>
		</div>
	</div>
</section>

<section class="section" id="collection">
	<div class="shell">
		<header class="section-head">
			<div>
				<p class="eyebrow"><?php esc_html_e( 'The collection', 'urumi-supply' ); ?></p>
				<h2 class="section-title"><?php esc_html_e( 'Everything we make, in one place', 'urumi-supply' ); ?></h2>
			</div>
			<a class="btn btn-link" href="<?php echo esc_url( wc_get_page_permalink( 'shop' ) ); ?>">
				<?php esc_html_e( 'View all products', 'urumi-supply' ); ?>
				<span aria-hidden="true">→</span>
			</a>
		</header>

		<?php if ( $featured->have_posts() ) : ?>
			<div class="product-grid">
				<?php
				while ( $featured->have_posts() ) :
					$featured->the_post();
					get_template_part( 'template-parts/product-card' );
				endwhile;
				wp_reset_postdata();
				?>
			</div>
		<?php else : ?>
			<p class="empty-note"><?php esc_html_e( 'The collection is being prepared. Please check back shortly.', 'urumi-supply' ); ?></p>
		<?php endif; ?>
	</div>
</section>

<section class="section section-sunken" id="story">
	<div class="shell story-grid">
		<div class="story-art" aria-hidden="true">
			<svg viewBox="0 0 320 260" role="presentation">
				<rect width="320" height="260" fill="#E5EAE2"/>
				<rect x="34" y="46" width="120" height="168" rx="10" fill="#244A3C"/>
				<rect x="54" y="70" width="80" height="9" rx="4.5" fill="#9CD3B7"/>
				<rect x="54" y="92" width="60" height="7" rx="3.5" fill="#7FB79B"/>
				<rect x="54" y="110" width="72" height="7" rx="3.5" fill="#7FB79B"/>
				<circle cx="212" cy="96" r="46" fill="#B87926"/>
				<circle cx="212" cy="96" r="26" fill="#F7F5EF"/>
				<path d="M42 214h236" stroke="#3E7860" stroke-width="3" stroke-linecap="round"/>
			</svg>
		</div>
		<div class="story-copy">
			<p class="eyebrow"><?php esc_html_e( 'Our approach', 'urumi-supply' ); ?></p>
			<h2 class="section-title"><?php esc_html_e( 'Made to be used, not replaced', 'urumi-supply' ); ?></h2>
			<p>
				<?php esc_html_e( 'Every object in the Urumi Supply collection earns its place. We design for the small rituals of the workday — the first note of the morning, the tidy desk at four, the bag that closes on a crowded train.', 'urumi-supply' ); ?>
			</p>
			<p>
				<?php esc_html_e( 'Stock levels on this site are live. What you see is what is on the shelf, updated as orders are placed.', 'urumi-supply' ); ?>
			</p>
			<ul class="check-list">
				<li><?php esc_html_e( 'Considered materials, honest pricing', 'urumi-supply' ); ?></li>
				<li><?php esc_html_e( 'Small-batch restocks, no seasonal churn', 'urumi-supply' ); ?></li>
				<li><?php esc_html_e( 'Packaged without plastic', 'urumi-supply' ); ?></li>
			</ul>
		</div>
	</div>
</section>

<?php if ( ! is_wp_error( $categories ) && count( $categories ) > 0 ) : ?>
	<section class="section">
		<div class="shell">
			<header class="section-head">
				<div>
					<p class="eyebrow"><?php esc_html_e( 'Browse', 'urumi-supply' ); ?></p>
					<h2 class="section-title"><?php esc_html_e( 'Shop by category', 'urumi-supply' ); ?></h2>
				</div>
			</header>
			<div class="category-grid">
				<?php foreach ( $categories as $category ) : ?>
					<a class="category-card" href="<?php echo esc_url( get_term_link( $category ) ); ?>">
						<span class="category-name"><?php echo esc_html( $category->name ); ?></span>
						<span class="category-count">
							<?php
							printf(
								/* translators: %d: number of products. */
								esc_html__( '%d pieces', 'urumi-supply' ),
								(int) $category->count
							);
							?>
						</span>
					</a>
				<?php endforeach; ?>
			</div>
		</div>
	</section>
<?php endif; ?>

<section class="section cta-band">
	<div class="shell cta-inner">
		<div>
			<h2 class="cta-title"><?php esc_html_e( 'Questions before you buy?', 'urumi-supply' ); ?></h2>
			<p class="cta-note">
				<?php esc_html_e( 'Our team answers every message within one business day.', 'urumi-supply' ); ?>
			</p>
		</div>
		<a class="btn btn-primary btn-lg" href="<?php echo esc_url( home_url( '/contact' ) ); ?>">
			<?php esc_html_e( 'Talk to us', 'urumi-supply' ); ?>
		</a>
	</div>
</section>

<?php
get_footer();
