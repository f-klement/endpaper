/**
 * The single fetch implementation every generated endpoint calls.
 *
 * Orval generates one function per API operation, and each delegates the
 * actual request to this. That makes it the one place where the bearer token
 * is attached, an expired session is handled, and the server's error shape is
 * turned into something the UI can display. None of that is known to the generator
 * anything about.
 *
 * Nothing outside this file should call `fetch` directly.
 */

const TOKEN_KEY = "token";
const USER_KEY = "user";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: unknown): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/**
 * Read a displayable message out of a failed response.
 *
 * FastAPI puts it in `detail`, but that is a string for a raised
 * `HTTPException` and an array of per-field objects for a 422. A non-JSON body
 * is possible too (a reverse proxy's own error page), so all three end up as
 * a string here.
 */
async function errorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown }).detail;

    if (typeof detail === "string") return detail;

    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item as { msg?: unknown }).msg)
        .filter((msg): msg is string => typeof msg === "string");
      if (messages.length > 0) return messages.join(", ");
    }
  } catch {
    // Body was not JSON, so fall through to the status text.
  }
  return response.statusText || fallback;
}

/** Where to send someone whose session has ended. */
const LOGIN_PATH = "/login";

/**
 * Endpoints where a 401 means "those credentials are wrong", not "your session
 * expired".
 *
 * Without this distinction, a mistyped password is handled as an expired
 * session: the stored session is cleared and the server's "Incorrect username
 * or password" is replaced with "Your session has expired", which is both
 * wrong and, for someone who was not signed in to begin with, nonsense.
 */
const CREDENTIAL_PATHS = ["/auth/login", "/auth/register"];

function isCredentialRequest(url: string): boolean {
  return CREDENTIAL_PATHS.some((path) => url.includes(path));
}

function endSession(): void {
  clearSession();
  // A full navigation rather than a router push: the session is gone, so the
  // cleanest thing is to drop all in-memory state with it.
  if (window.location.pathname !== LOGIN_PATH) {
    window.location.href = LOGIN_PATH;
  }
}

/**
 * The mutator Orval calls for every operation.
 *
 * Generic over the response type so the generated hooks stay fully typed.
 */
export const customFetch = async <T>(
  url: string,
  options: RequestInit = {},
): Promise<T> => {
  const token = getToken();
  const isFormData = options.body instanceof FormData;

  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Never set Content-Type for FormData: the browser has to set it itself so
  // it can include the multipart boundary. Setting it by hand produces a
  // request the server cannot parse.
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, { ...options, headers });

  // A 401 from a credential endpoint is a rejected sign-in attempt, so it
  // falls through to the ordinary error path below and keeps the server's
  // message.
  if (response.status === 401 && !isCredentialRequest(url)) {
    endSession();
    // Throw rather than resolve: returning undefined here would have every
    // caller render with missing data instead of showing an error.
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    throw new ApiError(
      await errorMessage(response, "Request failed"),
      response.status,
    );
  }

  if (response.status === 204) return null as T;

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    // File downloads and the like: hand back the blob rather than failing to
    // parse it as JSON.
    return (await response.blob()) as T;
  }

  return (await response.json()) as T;
};

/**
 * Fetch a file and hand it to the browser as a download.
 *
 * Not expressible through a generated hook: a plain `<a href>` cannot carry
 * the Authorization header, and the filename comes from a response header that
 * `customFetch` discards along with the rest of the envelope. It lives here
 * rather than in a page because this file is the API boundary: nothing
 * outside it should be calling `fetch`.
 */
export async function downloadFile(
  url: string,
  fallbackName = "export",
): Promise<void> {
  const token = getToken();
  const response = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (response.status === 401) {
    endSession();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }
  if (!response.ok) {
    throw new ApiError(
      await errorMessage(response, "Download failed"),
      response.status,
    );
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;

  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export default customFetch;
