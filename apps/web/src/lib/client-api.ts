/**
 * Browser-side calls to the API through the same-origin `/api/v1` proxy. Sends the CSRF token
 * (read from the CSRF cookie, which is deliberately not HttpOnly) on state-changing requests.
 */

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; code: string; message: string; fields?: Record<string, string> };

const CSRF_COOKIES = ["__Host-ar_csrf", "ar_csrf"];

export function readCsrfToken(cookieString: string): string | undefined {
  for (const part of cookieString.split(";")) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName && CSRF_COOKIES.includes(rawName)) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

export type ApiErrorInfo = { code: string; message: string; fields?: Record<string, string> };

export function errorFrom(status: number, body: unknown): ApiErrorInfo {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { code, message, fields } = detail as {
      code?: string;
      message?: string;
      fields?: unknown;
    };
    if (code && message) {
      // Per-field messages (e.g. questionnaire answers), keyed by field or question key.
      if (fields && typeof fields === "object" && !Array.isArray(fields)) {
        return { code, message, fields: fields as Record<string, string> };
      }
      return { code, message };
    }
  }
  if (Array.isArray(detail)) {
    // FastAPI validation errors.
    const first = detail[0] as { msg?: string } | undefined;
    return { code: "invalid", message: first?.msg?.replace(/^Value error, /, "") ?? "Check the form." };
  }
  if (status === 429) return { code: "rate_limited", message: "Too many attempts. Please wait." };
  return { code: "error", message: "Something went wrong. Please try again." };
}

export async function apiRequest<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") {
    const csrf = readCsrfToken(document.cookie);
    if (csrf) headers["x-csrf-token"] = csrf;
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    return { ok: false, status: 0, code: "network", message: "Can't reach the server." };
  }
  const data: unknown = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) return { ok: false, status: response.status, ...errorFrom(response.status, data) };
  return { ok: true, status: response.status, data: data as T };
}
