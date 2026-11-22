# Shopping chat product results plan

When a shopper asks to find or browse products, chat will show a short AI reply followed by up to eight product cards that look and behave like the cards on the storefront listing page.

## Use the storefront catalog query

- Keep using `search_products`, the function behind `GET /catalog/products`. Pass the shopper’s requested filters through the existing `ProductFilters` model so size, color, budget, and availability have the same meaning in both places.
- Request up to eight products and keep the query’s result order. If fewer than eight products match, show all matches.
- Use the storefront’s stock filter behavior for browsing. Include sold-out products with their existing label unless the shopper asks for in-stock items only.

## Return the AI reply and product JSON

- The AI writes a short message about the results. The backend supplies a separate `products` array with the catalog’s existing `ProductSummary` fields, including ID, slug, name, price, currency, stock status, and cover image. The frontend uses the slug to link to the product page.
- For `POST /chat`, include the array alongside `reply` when there are matches. For `POST /chat/stream`, keep streaming text with `delta` events and send the array in a `products` event before `done`.
- For an empty search or a catalog error, show an AI message that explains what happened. Replay the original reply and its product data when the client retries a completed message.

## Reuse the storefront product card

- Extract the existing listing card into a shared component. Reuse its image proportions, typography, price formatting, sold-out label, and click-through to the product page.
- Render the cards below the AI message in a responsive grid inside the chat panel. Let shoppers scroll through the results with the composer still accessible.

## Verify the result

- Compare chat results with the first eight storefront results for the same filters and sort order.
- Check searches that return eight or more matches, fewer than eight, and zero. Check unavailable catalog responses, text-only messages, and retries.
- In desktop and mobile layouts, confirm that the AI message and all product cards are reachable, the cards match the storefront, and product links open the correct pages.
