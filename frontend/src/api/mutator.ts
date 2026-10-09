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
 * Fired when the session ended and reloading cannot fix it.
 *
 * An event rather than state read by the shell: the only consumer is one
 * component, and module state holding "the session is over" would outlive the
 * mount that read it, so a remount would start out already dead. That is the
 * opposite of `reloadRequested` below, which is module state precisely because
 * it must last exactly as long as the document.
 */
const SESSION_ENDED_EVENT = "endpaper:session-ended";

/** Subscribe to that event. Returns the unsubscribe. */
export function onSessionEnded(listener: () => void): () => void {
  window.addEventListener(SESSION_ENDED_EVENT, listener);
  return () => window.removeEventListener(SESSION_ENDED_EVENT, listener);
}

/**
 * When the last automatic reload happened, per tab.
 *
 * `sessionStorage`, not `localStorage`: this is about one tab's own reload, and
 * it should die with the tab rather than teach the next one about a session
 * that ended yesterday.
 */
const RELOAD_MARKER_KEY = "endpaper.edge-reload";

/**
 * How recently a reload has to have happened for the next edge sign-out to
 * count as a loop rather than as an unrelated second expiry.
 *
 * Long enough to cover a reload plus a boot plus the first requests, short
 * enough that somebody who signed in again and read for a minute gets the
 * ordinary reload rather than the dead-end screen.
 */
const RELOAD_WINDOW_MS = 30_000;

/** The marker, or null if there is none and if storage cannot be read. */
function lastReloadAt(): number | null {
  try {
    const stored = sessionStorage.getItem(RELOAD_MARKER_KEY);
    const at = stored === null ? NaN : Number(stored);
    return Number.isFinite(at) ? at : null;
  } catch {
    // A private window or blocked site data. Not an error: see below for what
    // is done about being unable to count.
    return null;
  }
}

/**
 * Whether this page load has already asked for a reload.
 *
 * Module state, and its lifetime is the point: it dies with the document, which
 * is exactly the boundary being drawn. Without it the guard counts *calls*
 * rather than page loads, and an ordinary expiry is misreported. Six queries
 * are in flight on the library screen: four in `useLibrary` (the books, the
 * tags, the locations, the collections), the `useListBooks` inside
 * `useUnconfirmedCount`, which `Home.tsx` calls with no `enabled` gate, and the
 * auth config. Seven under proxy auth, where `useMe` is enabled too. So an
 * expiry resolves six opaque redirects in one batch: the first writes the
 * marker and reloads, and the rest then read a marker aged about zero
 * milliseconds, conclude they are looping, and put up a screen saying reloading
 * did not help while the reload is still in flight. The guard handles any
 * number of them; the number is here because it is what makes the batch real
 * rather than theoretical.
 */
let reloadRequested = false;

/** Record a reload. False means it was not recorded and cannot be counted. */
function recordReload(): boolean {
  try {
    sessionStorage.setItem(RELOAD_MARKER_KEY, String(Date.now()));
    return true;
  } catch {
    return false;
  }
}

/**
 * The session ended at the reverse proxy rather than in this app.
 *
 * Endpaper can sit behind a forward-auth portal on a different hostname. When
 * its cookie expires the proxy answers requests itself, and whether that answer
 * is a 401 or a redirect to the portal depends on the request's `Accept`
 * header: Authelia redirects anything that accepts `text/html`, which a browser
 * `fetch` with no `Accept` does, because it sends a wildcard. `customFetch` now
 * asks for `application/json`, so against that portal this path is not the
 * ordinary way a session ends any more. It is kept because the header is a
 * request this app makes and not a promise the proxy gives back: nginx's
 * `auth_request` and oauth2-proxy both redirect regardless of `Accept`.
 *
 * Under `redirect: "manual"` that redirect arrives as an `opaqueredirect`
 * response rather than being followed, so there is no status and no body to
 * read: only the fact of it. (An earlier version of this comment described
 * `fetch` following the redirect and rejecting with a bare `TypeError`. That
 * was true before `redirect: "manual"`, which was added in the same commit,
 * 4d9aa1e, tagged v0.2.0. The description of the behaviour it replaced was
 * still here at v0.5.0.)
 *
 * Sending the browser to `/login` would not help: that is this app's own login
 * route, and the proxy sits in front of it too. The only thing that resolves it
 * is a **top-level navigation**, which is the one request the browser will
 * follow across origins and render. Hence `reload` rather than a router push.
 *
 * **The reload is counted, and that is the point of the marker.** A reload that
 * comes back to the same expired session reloads again, and that is an endless
 * spinner with a refreshing page behind it: reported live, with two tabs open,
 * against a build whose service worker answered `/` from the precache so the
 * portal never saw the navigation at all. The two faults that produced it are
 * fixed; this exists so the next one degrades to a sentence somebody can act
 * on instead of to a loop.
 *
 * Not being able to record the marker is treated as "do not reload", not as
 * "reload blindly": an uncountable reload is exactly the loop this guards.
 */
function reauthenticateAtEdge(): void {
  clearSession();

  // The rest of a failing batch is the same event, not a new one: the
  // navigation is already in flight and has not had its chance yet.
  if (reloadRequested) return;

  const previous = lastReloadAt();
  const looping = previous !== null && Date.now() - previous < RELOAD_WINDOW_MS;
  if (looping || !recordReload()) {
    window.dispatchEvent(new Event(SESSION_ENDED_EVENT));
    return;
  }

  reloadRequested = true;
  window.location.reload();
}

/**
 * Did the request get redirected rather than answered?
 *
 * `opaqueredirect` only, and the narrowing is deliberate. It used to accept
 * `status === 0` as well, on the grounds that a false negative put the spinner
 * back; a false *positive* costs `clearSession()` plus a page reload, which is
 * the most destructive thing this client does, so the trade is not the one that
 * comment was written against.
 *
 * Under `redirect: "manual"` and the default request mode there is no other
 * resolved response with status 0. The spec gives an opaque-redirect filtered
 * response `type: "opaqueredirect"` and `status: 0` together; the only other
 * zero-status response is an opaque one, which needs `mode: "no-cors"`, and
 * nothing here sets it. A transport failure does not resolve at all, it rejects,
 * and is a `NetworkError` above.
 */
export function isRedirect(response: Response): boolean {
  return response.type === "opaqueredirect";
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
  // `Accept`, and it is not decoration. A browser `fetch` sends `*/*` when
  // nothing sets it, and a forward-auth portal reads exactly that header to
  // decide whether an unauthenticated request gets a 401 or a 302 to its login
  // page: Authelia redirects anything that accepts `text/html`, which `*/*`
  // does. Measured against the deployment, same URL, same expired cookie:
  //
  //     Accept: application/json   ->  401
  //     Accept: */*                ->  302
  //     Accept: <absent>           ->  401
  //
  // The third row is the portal being consistent, not a third case to design
  // for: a browser `fetch` never sends no Accept at all, it sends `*/*`, which
  // is row two. It is in the table because the first measurement of it was
  // taken with curl, which sends `*/*` unless told otherwise, so the wildcard
  // was measured twice and one of the two was written down as "absent".
  //
  // A 401 is the answer this file can act on. The 302 is what the endless
  // spinner was built out of. Asking for JSON is also simply true: every
  // operation in the schema declares a JSON response, and the blob fallback
  // below exists for a proxy's own error page rather than for an endpoint of
  // ours.
  if (!headers.has("Accept")) headers.set("Accept", "application/json");

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
 * What a download is willing to receive, and deliberately not a wildcard.
 *
 * The three types are the ones this app actually downloads: a CSV or JSON
 * export, and a ZIP backup, plus `application/json` for the error body FastAPI
 * sends when the download is refused. `customFetch`'s plain
 * `Accept: application/json` would be a lie here, and a wildcard would put this
 * request back on the wrong side of the portal's content negotiation, which is
 * the whole reason any of these requests carry an `Accept` at all.
 */
const DOWNLOAD_ACCEPT =
  "application/octet-stream, application/zip, text/csv, application/json";

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
  const headers = new Headers({ Accept: DOWNLOAD_ACCEPT });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await request(url, { headers, redirect: "manual" });

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
