"use client";

import { useState } from "react";

export function CatalogPhoto({ photo, eager = false, decorative = false }) {
  const src = photo ? "/api" + photo.url : null;
  const [failedUrl, setFailedUrl] = useState(null);

  if (!src || src === failedUrl) {
    return (
      <span className="catalog-photo-placeholder" aria-hidden={decorative || undefined}>
        <span aria-hidden="true">◇</span>
        {!decorative && "Photo unavailable"}
      </span>
    );
  }
  return (
    <img
      src={src}
      alt={decorative ? "" : photo.alt_text}
      loading={eager ? "eager" : "lazy"}
      decoding="async"
      onError={() => setFailedUrl(src)}
    />
  );
}

export function ProductGallery({ images }) {
  const [activeId, setActiveId] = useState(images[0]?.id);
  const active = images.find((image) => image.id === activeId) ?? images[0];

  return (
    <section className="catalog-gallery" aria-label="Product images">
      <div className="catalog-photo catalog-main-photo"><CatalogPhoto photo={active} eager /></div>
      {images.length > 1 && (
        <div className="catalog-gallery-options">
          {images.map((image) => (
            <button
              key={image.id}
              className="catalog-photo"
              type="button"
              onClick={() => setActiveId(image.id)}
              aria-pressed={image.id === active?.id}
              aria-label={image.alt_text}
            >
              <CatalogPhoto photo={image} decorative />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
