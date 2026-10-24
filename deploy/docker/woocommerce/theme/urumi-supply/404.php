<?php
/**
 * 404 template.
 *
 * @package Urumi_Supply
 */

get_header();
?>

<section class="section error-page">
	<div class="shell error-inner">
		<p class="eyebrow"><?php esc_html_e( 'Error 404', 'urumi-supply' ); ?></p>
		<h1 class="page-hero-title"><?php esc_html_e( 'We could not find that page.', 'urumi-supply' ); ?></h1>
		<p class="error-note">
			<?php esc_html_e( 'The link may be out of date, or the piece may have sold out for good. The collection is still here.', 'urumi-supply' ); ?>
		</p>
		<div class="hero-actions">
			<a class="btn btn-primary" href="<?php echo esc_url( home_url( '/' ) ); ?>">
				<?php esc_html_e( 'Back to home', 'urumi-supply' ); ?>
			</a>
			<a class="btn btn-secondary" href="<?php echo esc_url( wc_get_page_permalink( 'shop' ) ); ?>">
				<?php esc_html_e( 'Shop the collection', 'urumi-supply' ); ?>
			</a>
		</div>
	</div>
</section>

<?php
get_footer();
