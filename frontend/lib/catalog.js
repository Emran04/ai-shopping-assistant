export function catalogRequest(path, options = {}) {
  const base = process.env.FASTAPI_URL || "http://127.0.0.1:8000";
  return fetch(new URL(path, base), {
    cache: "no-store",
    signal: AbortSignal.timeout(6000),
    ...options,
  });
}

export function catalogUrl(params) {
  const query = params.toString();
  return query ? "/catalog?" + query : "/catalog";
}

export function priceLabel(priceMinor, currency) {
  const formatter = new Intl.NumberFormat("en", { style: "currency", currency });
  return formatter.format(priceMinor / (10 ** formatter.resolvedOptions().maximumFractionDigits));
}

export function minorUnits(amount, currency) {
  if (!amount || !currency) return null;
  const digits = new Intl.NumberFormat("en", { style: "currency", currency })
    .resolvedOptions().maximumFractionDigits;
  const [whole, fraction = ""] = amount.split(".");
  if (!/^\d{1,12}(\.\d{1,3})?$/.test(amount) || fraction.length > digits) {
    throw new Error("Enter a valid " + currency + " amount.");
  }
  const minor = Number(whole + fraction.padEnd(digits, "0"));
  if (minor > 999_999_999_999) throw new Error("The price filter is too large.");
  return minor;
}
