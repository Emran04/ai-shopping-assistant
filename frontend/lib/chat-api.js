const customerCookie = "ecomm_chat_customer";
const quotaHeaders = ["X-Chat-Customer-Id", "X-Chat-Messages-Remaining", "X-Chat-Support-Phone"];

export function chatBackendRequest(request, path, timeout, body) {
  const customer = request.cookies.get(customerCookie);
  const headers = { "Content-Type": "application/json" };
  if (customer && /^[A-Za-z0-9_-]{43}$/.test(customer.value)) {
    headers.Cookie = `${customerCookie}=${customer.value}`;
  }
  return fetch(new URL(path, process.env.FASTAPI_URL || "http://127.0.0.1:8000"), {
    method: "POST",
    headers,
    body: body && JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.any([request.signal, AbortSignal.timeout(timeout)]),
  });
}

export function chatResponseHeaders(request, response) {
  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const name of quotaHeaders) {
    const value = response.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  const cookie = response.headers.get("set-cookie");
  if (cookie) {
    const secure = request.nextUrl.protocol === "https:" && !/;\s*secure(?:;|$)/i.test(cookie);
    headers.set("Set-Cookie", secure ? `${cookie}; Secure` : cookie);
  }
  return headers;
}
