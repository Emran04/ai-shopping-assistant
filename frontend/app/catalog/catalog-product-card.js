import Link from "next/link";
import { priceLabel } from "../../lib/catalog";
import { CatalogPhoto } from "./catalog-photo";

export function CatalogProductCard({ product }) {
  return (
    <Link href={"/catalog/" + product.slug} className="catalog-card">
      <div className="catalog-photo"><CatalogPhoto photo={product.cover} /></div>
      <div className="catalog-card-info">
        <h3>{product.name}</h3>
        <span>{priceLabel(product.price_minor, product.currency)}</span>
      </div>
      {!product.in_stock && <p className="catalog-stock">Sold out</p>}
    </Link>
  );
}
