import Link from "next/link";
import { Suspense } from "react";
import { catalogRequest } from "../lib/catalog";
import { CatalogProductCard } from "./catalog/catalog-product-card";
import { ShoppingChat } from "./shopping-chat";

async function HomeProducts() {
  let products = [];
  let status = "";

  try {
    const response = await catalogRequest("/catalog/products?sort=newest&page_size=8");
    if (!response.ok) throw new Error("Catalog unavailable");
    ({ items: products } = await response.json());
    if (!products.length) status = "No products have been added yet.";
  } catch {
    status = "Products are temporarily unavailable.";
  }

  return (
    <section className="home-products" aria-labelledby="home-products-title">
      <div className="home-products-header">
        <h2 id="home-products-title">Latest arrivals</h2>
        <Link href="/catalog">View all clothing <span aria-hidden="true">→</span></Link>
      </div>
      {status ? <p className="home-products-status">{status}</p> : (
        <ul className="catalog-grid">
          {products.map((product) => (
            <li key={product.id}><CatalogProductCard product={product} /></li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function Home() {
  return (
    <div className="site-shell">
      <header className="site-header home-header">
        <div className="wordmark">
          <span className="brand-mark" aria-hidden="true">e.</span>
          Ecomm Assistant
        </div>
        <nav aria-label="Main navigation"><Link href="/catalog">Shop clothing</Link></nav>
      </header>

      <main className="workspace">
        <section className="intro" aria-labelledby="page-title">
          <h1 id="page-title">What are you<br className="desktop-break" /> shopping for?</h1>
          <p>Ask what to look for, compare options, or find a gift that fits your budget.</p>
        </section>
        <Suspense fallback={null}>
          <HomeProducts />
        </Suspense>
        <ShoppingChat />
      </main>
    </div>
  );
}
