/** Tests for src/api/mutator.ts: the single fetch every endpoint goes through. */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  NetworkError,
  clearSession,
  customFetch,
  downloadFile,
  getToken,
  setSession,
} from "../../src/api/mutator";
import { makeUser, resetIds } from "../factories";
import { mockApi } from "../utils";

beforeEach(() => {
  resetIds();
  // jsdom refuses real navigation, so location is replaced wholesale.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { href: "/", pathname: "/" },
  });
});

describe("session storage", () => {
  it("starts empty", () => {
    expect(getToken()).toBeNull();
  });

  it("round-trips a session", () => {
    const user = makeUser();
    setSession("abc123", user);
    expect(getToken()).toBe("abc123");
    expect(JSON.parse(localStorage.getItem("user")!)).toEqual(user);
  });

  it("clears both keys", () => {
    setSession("abc123", makeUser());
    clearSession();
    expect(localStorage.getItem("token")).toBeNull();
    expect(localStorage.getItem("user")).toBeNull();
  });
});

describe("request headers", () => {
  it("omits Authorization when signed out", async () => {
    const api = mockApi().on("/api/books", { body: [] });
    await customFetch("/api/books");
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Authorization")).toBeNull();
  });

  it("attaches the bearer token when signed in", async () => {
    localStorage.setItem("token", "abc123");
    const api = mockApi().on("/api/books", { body: [] });
    await customFetch("/api/books");
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer abc123");
  });

  it("sends JSON content type by default", async () => {
    const api = mockApi().on("/api/books", { body: [] });
    await customFetch("/api/books");
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("leaves Content-Type unset for FormData", async () => {
    // The browser must set it itself to include the multipart boundary;
    // setting it by hand produces a request the server cannot parse.
    const api = mockApi().on("/api/books", { body: {} });
    const form = new FormData();
    form.append("file", new File(["x"], "cover.png"));
    await customFetch("/api/books", { method: "POST", body: form });
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("still sends the token with FormData", async () => {
    localStorage.setItem("token", "abc123");
    const api = mockApi().on("/api/books", { body: {} });
    const form = new FormData();
    await customFetch("/api/books", { method: "POST", body: form });
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer abc123");
  });

  it("asks for JSON, which is what the portal negotiates on", async () => {
    // Not decoration. A forward-auth portal decides between answering 401 and
    // redirecting to its own login page on this header alone: Authelia
    // redirects anything that accepts text/html, and a browser fetch with no
    // Accept sends a wildcard, which does. Measured against the live
    // deployment, same URL and same expired cookie: application/json got 401
    // and a wildcard got 302. That 302 is the first half of the endless-spinner
    // loop. There is no third case to test: a browser never sends no Accept at
    // all.
    const api = mockApi().on("/api/books", { body: [] });
    await customFetch("/api/books");
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("lets a caller override Accept", async () => {
    const api = mockApi().on("/api/books", { body: [] });
    await customFetch("/api/books", { headers: { Accept: "text/plain" } });
    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Accept")).toBe("text/plain");
  });
});

describe("responses", () => {
  it("returns the parsed body", async () => {
    mockApi().on("/api/books", { body: { title: "Dune" } });
    await expect(customFetch("/api/books")).resolves.toEqual({ title: "Dune" });
  });

  it("returns null for 204", async () => {
    mockApi().on("/api/books/1", { status: 204 });
    await expect(
      customFetch("/api/books/1", { method: "DELETE" }),
    ).resolves.toBeNull();
  });

  it("returns a blob for a non-JSON body", async () => {
    mockApi().on("/api/books/export", {
      body: "Title,Author",
      headers: { "content-type": "text/csv" },
    });
    await expect(customFetch("/api/books/export")).resolves.toBeInstanceOf(
      Blob,
    );
  });
});

describe("errors", () => {
  it("throws ApiError carrying the status", async () => {
    mockApi().on("/api/books", {
      status: 409,
      body: { detail: "Already exists" },
    });
    await expect(customFetch("/api/books")).rejects.toThrow(ApiError);
    await expect(customFetch("/api/books")).rejects.toMatchObject({
      status: 409,
    });
  });

  it("uses FastAPI's string detail", async () => {
    mockApi().on("/api/books", {
      status: 409,
      body: { detail: "Already exists" },
    });
    await expect(customFetch("/api/books")).rejects.toThrow("Already exists");
  });

  it("flattens a 422 detail array into one message", async () => {
    mockApi().on("/api/books", {
      status: 422,
      body: {
        detail: [
          { loc: ["body", "title"], msg: "Field required" },
          { loc: ["body", "year"], msg: "Input should be a valid integer" },
        ],
      },
    });
    await expect(customFetch("/api/books")).rejects.toThrow(
      "Field required, Input should be a valid integer",
    );
  });

  it("falls back to status text when the body is not JSON", async () => {
    // What a reverse proxy's own error page looks like from here.
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 502,
          statusText: "Bad Gateway",
          headers: new Headers(),
          json: () => Promise.reject(new SyntaxError("Unexpected token <")),
        } as unknown as Response),
      ),
    );
    await expect(customFetch("/api/books")).rejects.toThrow("Bad Gateway");
  });
});

describe("a request that never got an answer", () => {
  /** A rejected fetch: no status, no body, nothing reached the origin. */
  function unreachable() {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
  }

  it("is a NetworkError rather than the browser's TypeError", async () => {
    // Classified here because this is the only place that can tell a
    // rejection from a response. Downstream it would be a guess from the text
    // of a string the browser vendor chooses.
    unreachable();
    await expect(customFetch("/api/books")).rejects.toBeInstanceOf(
      NetworkError,
    );
  });

  it("keeps the original for the console", async () => {
    unreachable();
    const error = await customFetch("/api/books").catch((e: unknown) => e);
    expect((error as NetworkError).cause).toBeInstanceOf(TypeError);
  });

  it("is not an ApiError, which carries a status and a server message", async () => {
    unreachable();
    const error = await customFetch("/api/books").catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("does not end the session", async () => {
    // Nothing was said about this session. Signing somebody out because their
    // train went into a tunnel would be worse than the failure.
    setSession("abc123", makeUser());
    unreachable();
    await customFetch("/api/books").catch(() => undefined);
    expect(getToken()).toBe("abc123");
  });

  it("covers downloads too", async () => {
    unreachable();
    await expect(downloadFile("/api/books/export")).rejects.toBeInstanceOf(
      NetworkError,
    );
  });
});

/**
 * A fresh copy of the module, standing in for a fresh document.
 *
 * `mutator.ts` remembers whether this page load has already asked for a reload,
 * in module state, deliberately: its lifetime is meant to be the document's. A
 * test that wants its own page load therefore has to have its own module, and
 * re-importing is the only thing that is one. Without this, the first test to
 * trigger a reload silences every later one in the file.
 */
async function freshPageLoad() {
  vi.resetModules();
  return await import("../../src/api/mutator");
}

describe("an edge sign-out", () => {
  // The reverse proxy in front of this app answers an expired session with a
  // 302 to a login portal on another hostname, XHR requests included. Followed,
  // that 302 becomes an opaque cross-origin failure with no status to read, so
  // the 401 path below never runs: nothing redirects, React Query retries, and
  // the screen spins forever. This is that bug, pinned.

  beforeEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "/", pathname: "/", reload: vi.fn() },
    });
  });

  it("treats an opaque redirect as an expired session", async () => {
    const mutator = await freshPageLoad();
    mockApi().on("/api/books", { status: 0, type: "opaqueredirect" });
    await expect(mutator.customFetch("/api/books")).rejects.toThrow(
      "session has expired",
    );
  });

  it("requests the redirect rather than following it", async () => {
    // Following it is what loses the status. Nothing else can detect this.
    const mutator = await freshPageLoad();
    const api = mockApi().on("/api/books", { body: [] });
    await mutator.customFetch("/api/books");
    expect(api.fetch.mock.calls[0]![1].redirect).toBe("manual");
  });

  it("reloads rather than pushing to the login route", async () => {
    // /login is this app's own route and the proxy sits in front of it too, so
    // a router push would be redirected again. Only a top-level navigation is
    // followed across origins.
    const mutator = await freshPageLoad();
    mockApi().on("/api/books", { status: 0, type: "opaqueredirect" });
    await expect(mutator.customFetch("/api/books")).rejects.toThrow();
    expect(window.location.reload).toHaveBeenCalled();
  });

  it("clears the stored session on the way out", async () => {
    const mutator = await freshPageLoad();
    mutator.setSession("stale", makeUser());
    mockApi().on("/api/books", { status: 0, type: "opaqueredirect" });
    await expect(mutator.customFetch("/api/books")).rejects.toThrow();
    expect(localStorage.getItem("token")).toBeNull();
  });

  it("does not save the portal's page as a download", async () => {
    // Otherwise an expired session writes the proxy's redirect page to disk
    // under the export's filename.
    const mutator = await freshPageLoad();
    mockApi().on("/api/books/export", { status: 0, type: "opaqueredirect" });
    await expect(mutator.downloadFile("/api/books/export")).rejects.toThrow(
      "session has expired",
    );
  });

  it("leaves a zero status that is not an opaque redirect alone", async () => {
    // The narrowing, pinned. `status === 0` used to be accepted as a redirect
    // too, on the grounds that a missed one put the spinner back. The cost of
    // a false positive is not a wrong message: it is clearSession() plus a
    // page reload, which is the most destructive thing this client does.
    const mutator = await freshPageLoad();
    mutator.setSession("still-valid", makeUser());
    mockApi().on("/api/books", { status: 0 });

    await expect(mutator.customFetch("/api/books")).rejects.toBeInstanceOf(
      mutator.ApiError,
    );

    expect(mutator.getToken()).toBe("still-valid");
    expect(window.location.reload).not.toHaveBeenCalled();
  });
});

describe("the reload an edge sign-out triggers is counted", () => {
  // An unguarded reload is a loop waiting for its next trigger, and this one
  // had one: the reloaded page was answered from the service worker's
  // precache, so it booted looking signed in, made a request, was redirected,
  // and reloaded again. Reported live as a page that never stopped
  // refreshing behind a spinner.
  //
  // Two scenarios with two different right answers, and conflating them was a
  // bug of its own: several requests failing together in ONE page load is one
  // sign-out and gets one reload, while a marker left by a PREVIOUS page load
  // means the reload has already been tried and gets the dead-end screen.

  /** The key `mutator.ts` records the reload under, per tab. */
  const MARKER = "endpaper.edge-reload";

  beforeEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "/", pathname: "/", reload: vi.fn() },
    });
  });

  /** Answer one request the way an expired portal session does. */
  async function expiredAtTheEdge(fetcher: typeof customFetch): Promise<void> {
    mockApi().on("/api/books", { status: 0, type: "opaqueredirect" });
    await expect(fetcher("/api/books")).rejects.toThrow();
  }

  it("reloads the first time", async () => {
    const mutator = await freshPageLoad();
    await expiredAtTheEdge(mutator.customFetch);
    expect(window.location.reload).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(MARKER)).not.toBeNull();
  });

  it("reloads once for a whole batch of requests failing together", async () => {
    // The library screen has six requests in flight, so an expiry resolves six
    // opaque redirects in one batch. Counting calls rather than page loads made
    // the other five believe they were looping.
    const mutator = await freshPageLoad();
    const ended = vi.fn();
    const stop = mutator.onSessionEnded(ended);

    for (let n = 0; n < 5; n += 1) await expiredAtTheEdge(mutator.customFetch);

    stop();
    expect(window.location.reload).toHaveBeenCalledTimes(1);
    // And says nothing about having tried, because it has not tried yet.
    expect(ended).not.toHaveBeenCalled();
  });

  it("says so rather than reloading again, when a previous page load did", async () => {
    // The marker is what survives the reload, so a marker plus a fresh module
    // is exactly the state a reloaded tab boots into.
    sessionStorage.setItem(MARKER, String(Date.now() - 1000));
    const mutator = await freshPageLoad();
    const ended = vi.fn();
    const stop = mutator.onSessionEnded(ended);

    await expiredAtTheEdge(mutator.customFetch);

    stop();
    expect(window.location.reload).not.toHaveBeenCalled();
    expect(ended).toHaveBeenCalledTimes(1);
  });

  it("reloads again once the reload is old enough to be unrelated", async () => {
    // A session that expires an hour later is not the loop, and reloading is
    // still the right answer to it.
    sessionStorage.setItem(MARKER, String(Date.now() - 60 * 60 * 1000));
    const mutator = await freshPageLoad();
    await expiredAtTheEdge(mutator.customFetch);
    expect(window.location.reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload when it cannot record that it did", async () => {
    // A private window, or site data blocked. A reload nothing can count is
    // exactly the unbounded loop this guard exists for, so the dead-end screen
    // is the safe answer rather than the fallback.
    const mutator = await freshPageLoad();
    const ended = vi.fn();
    const stop = mutator.onSessionEnded(ended);
    vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });

    await expiredAtTheEdge(mutator.customFetch);

    stop();
    expect(window.location.reload).not.toHaveBeenCalled();
    expect(ended).toHaveBeenCalledTimes(1);
  });
});

describe("401 handling", () => {
  it("clears the stored session", async () => {
    setSession("expired", makeUser());
    mockApi().on("/api/books", {
      status: 401,
      body: { detail: "Not authenticated" },
    });

    await expect(customFetch("/api/books")).rejects.toThrow();

    expect(localStorage.getItem("token")).toBeNull();
    expect(localStorage.getItem("user")).toBeNull();
  });

  it("redirects to the login page", async () => {
    mockApi().on("/api/books", { status: 401, body: {} });
    await expect(customFetch("/api/books")).rejects.toThrow();
    expect(window.location.href).toBe("/login");
  });

  it("does not redirect when already on the login page", async () => {
    // Otherwise a failed sign-in attempt reloads the page out from under the
    // form, discarding what was typed.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "/login", pathname: "/login" },
    });
    mockApi().on("/auth/login", { status: 401, body: { detail: "Incorrect" } });

    await expect(
      customFetch("/auth/login", { method: "POST" }),
    ).rejects.toThrow();

    expect(window.location.href).toBe("/login");
  });

  it("rejects rather than resolving undefined", async () => {
    // Regression: returning undefined here had every caller render with
    // missing data instead of showing an error.
    mockApi().on("/api/books", { status: 401, body: {} });
    await expect(customFetch("/api/books")).rejects.toThrow(
      "session has expired",
    );
  });

  describe("a 401 from a credential endpoint is not an expired session", () => {
    // Regression: a mistyped password came back 401 and was handled as an
    // expired session: the stored session was cleared and the server's
    // "Incorrect username or password" was replaced with "Your session has
    // expired", which is wrong and, for someone not signed in at all,
    // nonsense.

    it("keeps the server's message on a rejected login", async () => {
      mockApi().on("/auth/login", {
        status: 401,
        body: { detail: "Incorrect username or password" },
      });
      await expect(
        customFetch("/auth/login", { method: "POST" }),
      ).rejects.toThrow("Incorrect username or password");
    });

    it("does not clear an existing session on a rejected login", async () => {
      // Someone signed in as one member, trying to switch to another and
      // mistyping, should not be signed out of the account they had.
      setSession("still-valid", makeUser());
      mockApi().on("/auth/login", {
        status: 401,
        body: { detail: "Incorrect" },
      });

      await expect(
        customFetch("/auth/login", { method: "POST" }),
      ).rejects.toThrow();

      expect(getToken()).toBe("still-valid");
    });

    it("keeps the server's message on a rejected registration", async () => {
      mockApi().on("/auth/register", {
        status: 401,
        body: { detail: "Registration is disabled" },
      });
      await expect(
        customFetch("/auth/register", { method: "POST" }),
      ).rejects.toThrow("Registration is disabled");
    });

    it("keeps the admin signed in when a switch password is wrong", async () => {
      // The sharpest of the three: the caller is signed in, so treating this
      // 401 as an expired session signs an admin out of their own account for
      // mistyping a test account's password, having changed nothing.
      setSession("still-valid", makeUser());
      mockApi().on("/auth/switch", {
        status: 401,
        body: { detail: "Incorrect password for that account" },
      });

      await expect(
        customFetch("/auth/switch", { method: "POST" }),
      ).rejects.toThrow("Incorrect password for that account");

      expect(getToken()).toBe("still-valid");
    });

    it("still ends the session on a 401 from any other endpoint", async () => {
      setSession("expired", makeUser());
      mockApi().on("/api/books", { status: 401, body: {} });

      await expect(customFetch("/api/books")).rejects.toThrow(
        "session has expired",
      );

      expect(getToken()).toBeNull();
    });
  });
});

describe("downloadFile", () => {
  const objectUrl = "blob:mock-url";

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => objectUrl);
    URL.revokeObjectURL = vi.fn();
  });

  it("asks for the types a download can actually be", async () => {
    // Not `application/json`, which is what `customFetch` sends and would be a
    // lie about a CSV or a ZIP, and not a wildcard, which is what puts a
    // request back on the redirecting side of the portal's content
    // negotiation. Those are the two mistakes available here, so both are
    // named.
    const api = mockApi().on("/api/books/export", { body: "Title,Author" });
    await downloadFile("/api/books/export");
    const accept = (api.fetch.mock.calls[0]![1].headers as Headers).get(
      "Accept",
    )!;
    expect(accept).toContain("text/csv");
    expect(accept).toContain("application/zip");
    expect(accept).not.toContain("text/html");
    expect(accept).not.toContain("*/*");
  });

  /** Capture the synthetic anchor the download clicks. */
  function captureAnchor(): HTMLAnchorElement[] {
    const created: HTMLAnchorElement[] = [];
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = realCreate(tag);
      if (tag === "a") created.push(element as HTMLAnchorElement);
      return element;
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    return created;
  }

  it("names the file from Content-Disposition", async () => {
    mockApi().on("/api/books/export", {
      body: "csv",
      headers: {
        "content-type": "text/csv",
        "content-disposition":
          'attachment; filename="endpaper-export-2026-08-18.csv"',
      },
    });
    const anchors = captureAnchor();

    await downloadFile("/api/books/export");

    expect(anchors[0]?.download).toBe("endpaper-export-2026-08-18.csv");
  });

  it("falls back to the given name when the header is absent", async () => {
    mockApi().on("/api/books/export", {
      body: "csv",
      headers: { "content-type": "text/csv" },
    });
    const anchors = captureAnchor();

    await downloadFile("/api/books/export", "fallback.csv");

    expect(anchors[0]?.download).toBe("fallback.csv");
  });

  it("releases the object URL", async () => {
    mockApi().on("/api/books/export", {
      body: "csv",
      headers: { "content-type": "text/csv" },
    });
    captureAnchor();

    await downloadFile("/api/books/export");

    expect(URL.revokeObjectURL).toHaveBeenCalledWith(objectUrl);
  });

  it("sends the bearer token", async () => {
    localStorage.setItem("token", "abc123");
    const api = mockApi().on("/api/books/export", {
      body: "csv",
      headers: { "content-type": "text/csv" },
    });
    captureAnchor();

    await downloadFile("/api/books/export");

    const headers = api.fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer abc123");
  });

  it("throws on a failed download", async () => {
    mockApi().on("/api/books/export", {
      status: 500,
      body: { detail: "boom" },
    });
    await expect(downloadFile("/api/books/export")).rejects.toThrow("boom");
  });
});
