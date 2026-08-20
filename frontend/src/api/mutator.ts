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
    /**
     * The book an error is about, when the server named one.
     *
     * Only the duplicate-ISBN 409 sets this, and only when the book is one the
     * caller may see. It is what lets "already in the library" offer to open
     * the book rather than being a sentence the reader can do nothing with.
     */
    readonly bookId?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * The request never got an answer.
 *
 * Distinct from `ApiError`, which carries a status and a sentence the server
 * wrote for the reader. This one has neither: `fetch` rejected, so nothing
 * reached the origin or nothing came back. The browser's own message for that
 * is a bare `TypeError: Failed to fetch`, which used to be printed to the
 * reader verbatim: untranslated, not a sentence, and no use to somebody on a
 * phone. Reported live from a mobile client behind a VPN whose MTU was
 * black-holing large HTTP/3 responses.
 *
 * The cause is kept for the console. The message shown is chosen by
 * `errorText`, which has the catalogue.
 *
 * Classified here rather than anywhere downstream because this is the only
 * place that can tell a rejection from a response. Everywhere else it would
 * be a guess from the text of a string the browser vendor chooses.
 */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("Network request failed", { cause });
    this.name = "NetworkError";
  }
}

/** Run a request, turning a rejected fetch into a `NetworkError`. */
async function request(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    // A rejection here is transport level. An HTTP error, even a 502 from the
    // proxy, arrives as a resolved response and is handled further down.
    throw new NetworkError(error);
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
 * Read what a failed response says, and anything it says about what to do.
 *
 * FastAPI puts it in `detail`, which is a string for a raised
 * `HTTPException`, an array of per-field objects for a 422, and an object
 * where a route wanted to say more than a sentence. A non-JSON body is
 * possible too, a reverse proxy's own error page, so all four end up here.
 */
async function errorDetail(
  response: Response,
  fallback: string,
): Promise<{ message: string; bookId?: number }> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown }).detail;

    if (typeof detail === "string") return { message: detail };

    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item as { msg?: unknown }).msg)
        .filter((msg): msg is string => typeof msg === "string");
      if (messages.length > 0) return { message: messages.join(", ") };
    }

    // An object detail: a message plus whatever the route could say about it.
    // Only the duplicate-ISBN 409 sends one today.
    if (detail && typeof detail === "object") {
      const { message, book_id: bookId } = detail as {
        message?: unknown;
        book_id?: unknown;
      };
      if (typeof message === "string") {
        return {
          message,
          bookId: typeof bookId === "number" ? bookId : undefined,
        };
      }
    }
  } catch {
    // Body was not JSON, so fall through to the status text.
  }
  return { message: response.statusText || fallback };
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
 *
 * `/auth/switch` is the sharpest case of the three, because the caller **is**
 * signed in: an admin who mistypes a test account's password would be signed
 * out of their own session and sent to the login screen, having changed
 * nothing. Measured, not predicted.
 */
const CREDENTIAL_PATHS = ["/auth/login", "/auth/register", "/auth/switch"];

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
 * The session ended at the reverse proxy rather than in this app.
 *
 * Endpaper sits behind a forward-auth portal on a different hostname. When its
 * cookie expires the proxy answers every request, XHR included, with a 302 to
 * that hostname. Three things follow, and together they were the whole of the
 * "endless spinner" bug:
 *
 * 1. `fetch` follows the redirect, the cross-origin response carries no CORS
 *    header, and the promise rejects with a bare `TypeError: NetworkError`.
 *    There is no status to read, so the 401 path below never runs.
 * 2. Nothing redirects the reader anywhere, because the app never learns it is
 *    signed out.
 * 3. React Query retries, forever, behind a spinner.
 *
 * Sending the browser to `/login` would not help: that is this app's own login
 * route, and the proxy sits in front of it too. The only thing that resolves
 * it is a **top-level navigation**, which is the one request the browser will
 * follow across origins and render. Hence `reload` rather than a router push.
 */
function reauthenticateAtEdge(): void {
  clearSession();
  window.location.reload();
}

/**
 * Did the request get redirected rather than answered?
 *
 * Under `redirect: "manual"` a redirect arrives as an opaque placeholder: the
 * body is unreadable and the status reads 0. Both are checked because the two
 * are not reported identically everywhere, and a false negative here puts the
 * spinner back.
 */
export function isRedirect(response: Response): boolean {
  return response.type === "opaqueredirect" || response.status === 0;
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

  // `redirect: "manual"` is what makes an edge sign-out detectable. Following
  // it instead, which is the default, turns the proxy's 302 into an opaque
  // cross-origin failure with no status attached. See `reauthenticateAtEdge`.
  //
  // The cost is that a genuine same-origin redirect is no longer followed
  // either. Nothing here relies on one: the generated client requests the
  // exact paths FastAPI declares, so the trailing-slash redirect never fires.
  const response = await request(url, {
    ...options,
    headers,
    redirect: "manual",
  });

  if (isRedirect(response)) {
    reauthenticateAtEdge();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

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
    const detail = await errorDetail(response, "Request failed");
    throw new ApiError(detail.message, response.status, detail.bookId);
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
  const response = await request(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    redirect: "manual",
  });

  // Same edge sign-out as in `customFetch`. Without this an expired portal
  // session saves the proxy's redirect page to disk under the export's name.
  if (isRedirect(response)) {
    reauthenticateAtEdge();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (response.status === 401) {
    endSession();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }
  if (!response.ok) {
    throw new ApiError(
      (await errorDetail(response, "Download failed")).message,
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
