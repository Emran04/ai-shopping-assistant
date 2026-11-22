import { catalogRequest } from "../../../../../../../lib/catalog";

const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export async function GET(request, { params }) {
  const { productId, imageId } = await params;
  if (!/^[1-9]\d{0,9}$/.test(productId) || !uuid.test(imageId)) return new Response(null, { status: 404 });

  try {
    const etag = request.headers.get("if-none-match");
    const upstream = await catalogRequest("/catalog/media/" + productId + "/" + imageId + "/thumbnail", {
      headers: etag ? { "If-None-Match": etag } : {},
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(20000)]),
    });
    if (!upstream.ok && upstream.status !== 304) {
      await upstream.body?.cancel();
      return new Response(null, {
        status: upstream.status === 404 ? 404 : 503,
        headers: { "Cache-Control": "no-store" },
      });
    }
    const headers = new Headers();
    for (const name of ["Cache-Control", "Content-Type", "Content-Length", "ETag", "X-Content-Type-Options"]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return new Response(null, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
