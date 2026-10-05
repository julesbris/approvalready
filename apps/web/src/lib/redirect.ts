/** Only same-site relative paths are allowed as post-login destinations (no open redirects). */
export function safeNext(value: string | string[] | undefined, fallback = "/account"): string {
  const next = Array.isArray(value) ? value[0] : value;
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return fallback;
  }
  return next;
}

export function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
