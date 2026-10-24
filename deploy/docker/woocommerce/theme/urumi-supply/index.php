<?php
/**
 * Generic index template.
 *
 * @package Urumi_Supply
 */

get_header();
?>

<section class="page-hero">
	<div class="shell">
		<p class="eyebrow"><?php esc_html_e( 'Urumi Supply', 'urumi-supply' ); ?></p>
		<h1 class="page-hero-title">
			<?php
			if ( is_home() && ! is_front_page() ) {
				echo esc_html( get_the_title() );
			} else {
				esc_html_e( 'Journal', 'urumi-supply' );
			}
			?>
		</h1>
	</div>
</section>

<section class="section">
	<div class="shell">
		<?php if ( have_posts() ) : ?>
			<div class="post-grid">
				<?php
				while ( have_posts() ) :
					the_post();
					?>
					<article <?php post_class( 'post-card' ); ?>>
						<a class="post-card-media" href="<?php the_permalink(); ?>">
							<?php if ( has_post_thumbnail() ) : ?>
								<?php the_post_thumbnail( 'urumi-product-card', array( 'loading' => 'lazy' ) ); ?>
							<?php else : ?>
								<span class="post-card-placeholder" aria-hidden="true"></span>
							<?php endif; ?>
						</a>
						<h2 class="post-card-title">
							<a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
						</h2>
						<p class="post-card-date"><?php echo esc_html( get_the_date() ); ?></p>
					</article>
					<?php
				endwhile;
				?>
			</div>

			<?php
			the_posts_pagination(
				array(
					'mid_size'  => 2,
					'prev_text' => esc_html__( 'Previous', 'urumi-supply' ),
					'next_text' => esc_html__( 'Next', 'urumi-supply' ),
				)
			);
			?>
		<?php else : ?>
			<p class="empty-note"><?php esc_html_e( 'Nothing here yet.', 'urumi-supply' ); ?></p>
		<?php endif; ?>
	</div>
</section>

<?php
get_footer();
