import Link from "next/link";
import { catalogRequest, catalogUrl, minorUnits } from "../../lib/catalog";
import { CatalogProductCard } from "./catalog-product-card";

export const metadata = { title: "Shop clothing | Ecomm Assistant" };

const filterNames = ["audience", "clothing_type", "size", "color", "min", "max", "q", "in_stock", "sort", "page"];
const multiValueFilters = new Set(["audience", "clothing_type", "size", "color"]);
const searchMaxLength = 255;
const sortOptions = [
  { value: "newest", label: "Newest" },
  { value: "price_asc", label: "Price low to high" },
  { value: "price_desc", label: "Price high to low" },
  { value: "name", label: "Product name" },
];

function selectedParams(raw) {
  const params = new URLSearchParams();
  for (const name of filterNames) {
    const values = Array.isArray(raw[name]) ? raw[name] : [raw[name]];
    for (const value of values.slice(0, multiValueFilters.has(name) ? 20 : 1)) {
      if (value?.trim()) params.append(name, value.trim().slice(0, name === "q" ? searchMaxLength : 120));
    }
  }
  return params;
}

function changeFilter(params, name, value) {
  const next = new URLSearchParams(params);
  next.delete("page");
  next.delete(name);
  if (value) next.set(name, value);
  return catalogUrl(next);
}

function FilterSelect({ name, label, options, params, emptyLabel }) {
  if (!options.length) return null;
  const selected = params.get(name) || "";
  return (
    <label>
      {label}
      <select name={name} defaultValue={selected}>
        {emptyLabel && <option value="">{emptyLabel}</option>}
        {selected && !options.some((item) => item.value === selected) && (
          <option value={selected}>{selected}</option>
        )}
        {options.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
  );
}

function Filters({ params, categories, products }) {
  return (
    <aside className="catalog-filters" aria-label="Product filters">
      <h2>Filter products</h2>
      <form action="/catalog">
        {params.getAll("audience").map((audience) => (
          <input key={audience} type="hidden" name="audience" value={audience} />
        ))}
        <label>
          Search by title or keyword
          <input name="q" type="search" maxLength={searchMaxLength} defaultValue={params.get("q") || ""} />
        </label>
        <FilterSelect name="clothing_type" label="Clothing type" emptyLabel="All types" params={params}
          options={categories.clothing_type.map(({ slug, name }) => ({ value: slug, label: name }))} />
        <FilterSelect name="size" label="Size" emptyLabel="All sizes" options={products.sizes} params={params} />
        <FilterSelect name="color" label="Color" emptyLabel="All colors" options={products.colors} params={params} />
        {categories.currency && (
          <fieldset>
            <legend>Price ({categories.currency})</legend>
            <div className="catalog-price-range">
              <label>Min<input name="min" inputMode="decimal" maxLength={16} defaultValue={params.get("min") || ""} /></label>
              <label>Max<input name="max" inputMode="decimal" maxLength={16} defaultValue={params.get("max") || ""} /></label>
            </div>
          </fieldset>
        )}
        <FilterSelect name="sort" label="Sort by" options={sortOptions} params={params} />
        <label className="catalog-checkbox">
          <input type="checkbox" name="in_stock" value="true" defaultChecked={params.get("in_stock") === "true"} />
          In stock only
        </label>
        <div className="catalog-filter-actions">
          <button className="catalog-button" type="submit">Apply filters</button>
          {params.size > 0 && <Link href={changeFilter(new URLSearchParams(), "audience", params.get("audience"))}>Clear</Link>}
        </div>
      </form>
    </aside>
  );
}

export default async function CatalogPage({ searchParams }) {
  const params = selectedParams(await searchParams);
  const apiParams = new URLSearchParams(params);
  apiParams.delete("min");
  apiParams.delete("max");
  let categories = null;
  let products = { items: [], colors: [], sizes: [], page: 1, page_size: 12, total: 0 };
  let error = "";

  try {
    const response = await catalogRequest("/catalog/categories");
    if (!response.ok) throw new Error("Catalog unavailable");
    categories = await response.json();
    try {
      for (const [name, key] of [["min", "min_price"], ["max", "max_price"]]) {
        const minor = minorUnits(params.get(name), categories.currency);
        if (minor !== null) apiParams.set(key, minor);
      }
    } catch (inputError) {
      error = inputError.message;
    }
    if (!error) {
      const result = await catalogRequest("/catalog/products?" + apiParams);
      if (result.ok) products = await result.json();
      else if (result.status === 422) {
        const body = await result.json();
        error = typeof body.detail === "string" ? body.detail : "Check the selected filters and try again.";
      } else throw new Error("Catalog unavailable");
    }
  } catch {
    error = "The clothing catalog is temporarily unavailable.";
  }
  const pageCount = Math.max(1, Math.ceil(products.total / products.page_size));
  const audience = params.getAll("audience");

  return (
    <main>
      <div className="catalog-masthead">
        <h1>Shop clothing</h1>
        {categories && (
          <nav className="catalog-audiences" aria-label="Shop by audience">
            {[{ slug: "", name: "All clothing" }, ...categories.audience].map(({ slug, name }) => (
              <Link key={slug} href={changeFilter(params, "audience", slug)}
                aria-current={(slug ? audience.includes(slug) : !audience.length) ? "true" : undefined}>{name}</Link>
            ))}
          </nav>
        )}
      </div>
      <div className={"catalog-content" + (categories ? "" : " catalog-content-wide")}>
        {categories && <Filters params={params} categories={categories} products={products} />}
        <section className="catalog-results" aria-label="Products">
          {error ? <p className="catalog-empty" role="status">{error}</p> : (
            <>
              <div className="catalog-results-bar">
                <h2>Products</h2>
                <span>{products.total} {products.total === 1 ? "result" : "results"}</span>
              </div>
              {products.items.length ? (
                <ul className="catalog-grid">
                  {products.items.map((product) => (
                    <li key={product.id}>
                      <CatalogProductCard product={product} />
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="catalog-empty">
                  <h3>No products found</h3>
                  {params.size > 0 && <Link href="/catalog">Browse all clothing</Link>}
                </div>
              )}
              {(products.page > 1 || pageCount > 1) && (
                <nav className="catalog-pagination" aria-label="Product pages">
                  {products.page > 1 && (
                    <Link href={changeFilter(params, "page", products.page - 1)}>← Previous</Link>
                  )}
                  <span>Page {products.page} of {pageCount}</span>
                  {products.page < pageCount && (
                    <Link href={changeFilter(params, "page", products.page + 1)}>Next →</Link>
                  )}
                </nav>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
