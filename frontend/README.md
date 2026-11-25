# Ecomm Assistant frontend

The Next.js storefront uses assistant-ui for shopping conversations and renders matching catalog products as clickable cards in the chat.

[Project architecture](../README.md) · [Backend setup](../backend/README.md)

## Run locally

Start FastAPI and PostgreSQL using the [backend guide](../backend/README.md#run-fastapi-and-postgresql-with-docker). Use Node.js 20.9 or newer and the pnpm version declared in [`package.json`](package.json).

From the repository root, run the following commands.

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open the [homepage](http://localhost:3000) or [clothing catalog](http://localhost:3000/catalog). The frontend forwards requests to FastAPI at `http://127.0.0.1:8000` by default. To use another address, set this in `frontend/.env.local` and restart Next.js.

```dotenv
FASTAPI_URL=http://127.0.0.1:8000
```

[FastAPI interactive docs](http://127.0.0.1:8000/docs)

## Shopping chat

Select **Shopping chat** in the bottom-right corner of the homepage or catalog. Opening the panel checks the browser’s allowance and enables the composer. Choose a suggested prompt or type a question, use **Stop** to cancel a reply, and follow a product card to its detail page.

The panel keeps its conversation when closed and reopened on the loaded page. Reloading the page starts a new thread. The same browser cookie keeps the remaining allowance across reloads. When the limit is reached, the panel displays a support email and customer reference. Select **Check again** or reopen the panel after staff resets the allowance. [Quota operations](../backend/README.md#shopping-chat)

| Code | Role |
| --- | --- |
| [`app/shopping-chat.js`](app/shopping-chat.js) | Renders the panel, suggestions, messages, product cards, and allowance status. |
| [`lib/chat-model.js`](lib/chat-model.js) | Adapts the assistant-ui runtime to the chat API, sends thread and message IDs, and reads NDJSON events. |
| [`app/api/chat/route.js`](app/api/chat/route.js) and [`app/api/chat/session/route.js`](app/api/chat/session/route.js) | Proxy browser requests to FastAPI. The message route forwards NDJSON when requested and otherwise returns JSON. |
| [`lib/chat-api.js`](lib/chat-api.js) | Forwards the customer cookie and quota headers and passes cancellation signals to FastAPI. |

## Storefront and media

The homepage shows the latest arrivals. The catalog at `/catalog` provides filters, sorting, and pagination. Product detail pages at `/catalog/[slug]` show the description, variants, availability, and gallery. The same [product card](app/catalog/catalog-product-card.js) renders catalog results and chat recommendations.

Next.js fetches catalog data from FastAPI on the server. For photos, the browser loads a configured CDN URL directly or requests a thumbnail through the Next.js media route, which passes conditional requests and cache headers through to FastAPI.

## Build and preview

Run these commands from `frontend/`.

| Command | Purpose |
| --- | --- |
| `pnpm build` | Build the Next.js application. |
| `pnpm start` | Serve the completed Next.js build locally. |
| `pnpm build:cloudflare` | Build the Cloudflare Worker with OpenNext. |
| `pnpm preview` | Build the Worker and preview it locally with Wrangler. |
| `pnpm deploy` | Build and deploy the Worker to Cloudflare. |

[`wrangler.jsonc`](wrangler.jsonc) configures the Worker and its `FASTAPI_URL`. Use the backend URL for the target environment when deploying.
