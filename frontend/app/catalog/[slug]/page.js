import Link from "next/link";
import { notFound } from "next/navigation";
import { catalogRequest, priceLabel } from "../../../lib/catalog";
import { ProductGallery } from "../catalog-photo";

export const metadata = { title: "Product details | Ecomm Assistant" };

export default async function ProductPage({ params }) {
  const { slug } = await params;
  let response;
  try {
    response = await catalogRequest("/catalog/products/" + encodeURIComponent(slug));
  } catch {
    response = null;
  }
  if (response?.status === 404) notFound();
  if (!response?.ok) {
    return (
      <main className="catalog-detail">
        <Link className="catalog-back" href="/catalog">← Back to clothing</Link>
        <p role="status">Product details are temporarily unavailable.</p>
      </main>
    );
  }
  const product = await response.json();

  return (
    <main className="catalog-detail">
      <Link className="catalog-back" href="/catalog">← Back to clothing</Link>
      <div className="catalog-detail-grid">
        <ProductGallery images={product.images} />
        <div className="catalog-product-info">
          <nav className="catalog-product-categories" aria-label="Product categories">
            {Object.entries(product.categories).flatMap(([kind, entries]) => entries.map((category) => (
              <Link key={kind + category.slug} href={"/catalog?" + new URLSearchParams({ [kind]: category.slug })}>
                {category.name}
              </Link>
            )))}
          </nav>
          <h1>{product.name}</h1>
          <p className="catalog-detail-price">{priceLabel(product.price_minor, product.currency)}</p>
          {product.description && <p className="catalog-description">{product.description}</p>}
          <section className="catalog-availability" aria-labelledby="availability-heading">
            <h2 id="availability-heading">Size &amp; color availability</h2>
            <table>
              <thead><tr><th scope="col">Size</th><th scope="col">Color</th><th scope="col">Availability</th></tr></thead>
              <tbody>
                {product.variants.map((variant) => (
                  <tr key={variant.sku}>
                    <td>{variant.size}</td><td>{variant.color}</td>
                    <td className={variant.in_stock ? "catalog-available" : "catalog-stock"}>
                      {variant.in_stock ? "In stock" : "Sold out"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    </main>
  );
}
