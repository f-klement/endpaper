/** Tests for src/pages/hooks.ts: the hooks that belong to no single page. */

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getPurgeBookMutationOptions,
  getRestoreBookMutationOptions,
} from "../../src/api/generated/endpoints/books/books";
import { AuthMode, type UserOut } from "../../src/api/generated/model";
import {
  FILES_PER_LOOKUP,
  markMissing,
  readStoredUser,
  REFERENCES_PER_PAGE,
  reportEach,
  sweepFolder,
  useFolderSweep,
  useGoBack,
  useRowWrite,
  useSession,
} from "../../src/pages/hooks";
import { partialMd5 } from "../../src/lib/fileDigest";
import { boundOf, propertiesOf } from "../committedSchema";
import { makeUser, resetIds } from "../factories";
import {
  createTestQueryClient,
  heldOpen,
  mockApi,
  renderHookWithProviders,
  type MockApi,
} from "../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
});

function renderSession() {
  const client = createTestQueryClient();
  // `gcTime: Infinity`, against the shared helper's 0, and it is what makes
  // the cache assertions in this file mean anything. Every one of them is a
  // `setQueryData` on a key with no observer, which at `gcTime: 0` is
  // collected on the next tick: `await waitFor(... toBeUndefined())` then
  // measures garbage collection and passes with the clearing effect deleted.
  // Measured, not suspected: four tests here passed without it.
  client.setDefaultOptions({
    queries: { retry: false, staleTime: 0, gcTime: Infinity },
  });
  return {
    ...renderHook(() => useSession(), {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client }, children),
    }),
    client,
  };
}

/** A cached listing belonging to whoever is signed in at the time. */
const BOOKS_KEY = ["/api/books", { page: 1 }];
const BOOKS = {
  items: [{ id: 1, title: "A private diary", is_private: true }],
};

/** Configure the server's reported auth mode. */
function serverMode(mode: AuthMode, registrationEnabled = true) {
  api.on("/auth/config", {
    body: { auth_mode: mode, registration_enabled: registrationEnabled },
  });
}

describe("readStoredUser", () => {
  it("returns null when nothing is stored", () => {
    expect(readStoredUser()).toBeNull();
  });

  it("parses a stored account", () => {
    const account = makeUser({ username: "kim" });
    localStorage.setItem("user", JSON.stringify(account));
    expect(readStoredUser()).toEqual(account);
  });

  it("returns null rather than throwing on a corrupt value", () => {
    // A half-written entry would otherwise throw during the very first render
    // and white-screen the app, with no way back short of clearing site data.
    localStorage.setItem("user", "{not json");
    expect(readStoredUser()).toBeNull();
  });
});

describe("useSession in local mode", () => {
  beforeEach(() => serverMode(AuthMode.local));

  it("starts signed out with an empty store", async () => {
    const { result } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    expect(result.current.user).toBeNull();
  });

  it("restores the session from localStorage", async () => {
    const account = makeUser({ username: "kim" });
    localStorage.setItem("user", JSON.stringify(account));

    const { result } = renderSession();

    await waitFor(() => expect(result.current.user).toEqual(account));
  });

  it("persists the token and account on sign-in", async () => {
    const account = makeUser({ username: "kim" });
    const { result } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));

    act(() => result.current.signIn(account, "token-123"));

    expect(localStorage.getItem("token")).toBe("token-123");
    expect(JSON.parse(localStorage.getItem("user")!)).toEqual(account);
    expect(result.current.user).toEqual(account);
  });

  it("clears both on sign-out", async () => {
    const { result } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    act(() => result.current.signIn(makeUser(), "token-123"));

    act(() => result.current.signOut());

    expect(localStorage.getItem("token")).toBeNull();
    expect(localStorage.getItem("user")).toBeNull();
    expect(result.current.user).toBeNull();
  });

  it("tells the server to drop the cover cookie", async () => {
    // The cookie is the server's, not ours, and outlives the tab. Clearing
    // localStorage alone would leave the next person on a shared machine
    // fetching covers as whoever signed out.
    const { result } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    act(() => result.current.signIn(makeUser(), "token-123"));

    act(() => result.current.signOut());

    await waitFor(() =>
      expect(api.lastCall("/auth/logout", "POST")).toBeDefined(),
    );
  });

  it("signs out locally even when that request fails", async () => {
    // Otherwise a server that is down leaves somebody apparently signed in.
    api.on("/auth/logout", { status: 500, body: { detail: "no" } });
    const { result } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    act(() => result.current.signIn(makeUser(), "token-123"));

    act(() => result.current.signOut());

    expect(result.current.user).toBeNull();
    expect(localStorage.getItem("token")).toBeNull();
  });

  it("drops the cache when signing out", async () => {
    // The client is created once per page load and survives an identity
    // change, so without this the next person at this browser is handed the
    // previous member's entries back under identical keys. `visible_to()` is
    // "public or mine", so a cached listing carries their private books, and
    // `my_status`, `my_rating` and `active_loan` are computed per caller.
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    act(() => result.current.signIn(makeUser(), "token-123"));
    client.setQueryData(BOOKS_KEY, BOOKS);
    expect(client.getQueryData(BOOKS_KEY)).toEqual(BOOKS);

    act(() => result.current.signOut());

    expect(client.getQueryData(BOOKS_KEY)).toBeUndefined();
  });

  it("drops the cache when somebody else signs in over the top", async () => {
    // Signing out is not the only way the identity changes: "Switch account"
    // is a router link to /login, deliberately reachable while signed in, so
    // the next sign-in happens with the previous member's cache still warm.
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    act(() => result.current.signIn(makeUser({ username: "kim" }), "t1"));
    client.setQueryData(BOOKS_KEY, BOOKS);

    act(() => result.current.signIn(makeUser({ username: "sam" }), "t2"));

    await waitFor(() => expect(client.getQueryData(BOOKS_KEY)).toBeUndefined());
  });

  it("keeps a cache the same member left behind", async () => {
    // Not thrift: it is that "nobody" and "not known yet" are the same value,
    // and the identity is itself cached, so clearing on every null is an app
    // that refetches for as long as it is open. Only a change between two
    // known accounts is an identity change.
    const kim = makeUser({ username: "kim" });
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.isResolving).toBe(false));
    act(() => result.current.signIn(kim, "t1"));
    client.setQueryData(BOOKS_KEY, BOOKS);

    act(() => result.current.signIn(kim, "t2"));

    expect(client.getQueryData(BOOKS_KEY)).toEqual(BOOKS);
  });

  it("never asks the server who the caller is", async () => {
    // The account travels in the token, so a request here would be a round
    // trip for something already held.
    localStorage.setItem("user", JSON.stringify(makeUser()));
    const { result } = renderSession();

    await waitFor(() => expect(result.current.isResolving).toBe(false));

    expect(api.lastCall("/auth/me")).toBeUndefined();
  });
});

describe("useSession in ldap mode", () => {
  beforeEach(() => serverMode(AuthMode.ldap, false));

  it("still uses a token, because this app issues one after the bind", async () => {
    const account = makeUser({ username: "kim" });
    localStorage.setItem("user", JSON.stringify(account));

    const { result } = renderSession();

    // Wait on the mode, not on the user: the user comes back from
    // localStorage synchronously, so asserting on it would pass before the
    // config request that carries the mode has landed.
    await waitFor(() => expect(result.current.mode).toBe(AuthMode.ldap));
    expect(result.current.user).toEqual(account);
    expect(api.lastCall("/auth/me")).toBeUndefined();
  });
});

describe("useSession in proxy mode", () => {
  beforeEach(() => serverMode(AuthMode.proxy, false));

  /** Who /auth/me answers with once a held reply is released. */
  let heldAnswer: UserOut = makeUser({ username: "kim" });

  it("reads the identity from the server rather than storage", async () => {
    // There is no token in this mode: an upstream authenticated the request
    // and named the member in a header.
    const account = makeUser({ username: "kim" });
    api.on("/auth/me", { body: account });

    const { result } = renderSession();

    await waitFor(() => expect(result.current.user).toEqual(account));
  });

  it("ignores whatever happens to be in localStorage", async () => {
    localStorage.setItem(
      "user",
      JSON.stringify(makeUser({ username: "stale" })),
    );
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });

    const { result } = renderSession();

    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
  });

  it("reports an unidentified caller rather than offering a login form", async () => {
    // Almost always a deployment mistake. A login form would be useless here:
    // this deployment has no local passwords to offer.
    api.on("/auth/me", {
      status: 401,
      body: { detail: "Could not validate credentials" },
    });

    const { result } = renderSession();

    await waitFor(() => expect(result.current.proxyUnidentified).toBe(true));
    expect(result.current.user).toBeNull();
  });

  it("is still resolving while the identity is in flight", () => {
    api.on("/auth/me", { body: makeUser() });
    const { result } = renderSession();
    expect(result.current.isResolving).toBe(true);
  });

  it("settles on one identity rather than asking again forever", async () => {
    // The stale entry above is a **different person** from the one the
    // upstream names, so treating "not known yet" as an identity change made
    // the app clear the cache, refetch the identity, and clear it again. The
    // config request is the one to count: clearing the cache drops it too.
    localStorage.setItem(
      "user",
      JSON.stringify(makeUser({ username: "stale" })),
    );
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });

    const { result } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
    const settled = api.calls.filter((call) =>
      call.url.includes("/auth/config"),
    ).length;
    await waitFor(() => expect(result.current.isResolving).toBe(false));

    expect(settled).toBe(1);
    expect(
      api.calls.filter((call) => call.url.includes("/auth/config")).length,
    ).toBe(1);
    // And nothing is offered a way back: there is a stored account, but the
    // server is not honouring any token for it.
    expect(result.current.isSwitched).toBe(false);
  });

  it("drops the cache when the identity changes with nothing happening here", async () => {
    // The upstream owns the session in this mode, so the person at the
    // keyboard can change without a single click in this app: no signIn, no
    // signOut, and the whole cache still belonging to whoever was here.
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
    client.setQueryData(BOOKS_KEY, BOOKS);

    api.on("/auth/me", { body: makeUser({ username: "sam" }) });
    await act(async () => {
      await client.refetchQueries();
    });

    await waitFor(() => expect(result.current.user?.username).toBe("sam"));
    expect(client.getQueryData(BOOKS_KEY)).toBeUndefined();
  });

  /**
   * Put the identity back to not knowing, and hold it there.
   *
   * `reset`, not `invalidate`: an invalidation keeps the previous answer on
   * screen while it refetches, which is the opposite of the state under test.
   * The reply is held open because otherwise the whole thing settles inside
   * one `act`, React never renders the gap, and a test written against it
   * passes whatever the effect does. Measured: without the hold, both tests
   * below passed with the guard they exist for deleted.
   */
  async function forgetTheIdentity(
    client: QueryClient,
    release: Promise<void>,
  ) {
    api.on("/auth/me", async () => {
      await release;
      return { body: heldAnswer };
    });
    await act(async () => {
      void client.resetQueries({
        predicate: (query) =>
          JSON.stringify(query.queryKey).includes("/auth/me"),
      });
    });
  }

  it("remembers who was here across a moment of not knowing", async () => {
    // The identity is itself a cached query, so it can go away and come back
    // as somebody else while member-scoped data sits in the cache untouched.
    // The effect keys on the last account actually **known**, not the last
    // value seen: if a null in between overwrote that memory, the change from
    // kim to sam would look like a first sign-in and clear nothing.
    api.on("/auth/me", { body: makeUser({ id: 1, username: "kim" }) });
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
    client.setQueryData(BOOKS_KEY, BOOKS);
    const clears = vi.spyOn(client, "clear");

    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    heldAnswer = makeUser({ id: 2, username: "sam" });
    await forgetTheIdentity(client, held);

    // The gap itself: nobody is known, and nothing has been thrown away.
    await waitFor(() => expect(result.current.user).toBeNull());
    expect(clears).not.toHaveBeenCalled();
    expect(client.getQueryData(BOOKS_KEY)).toEqual(BOOKS);

    await act(async () => {
      release();
      await held;
    });

    await waitFor(() => expect(result.current.user?.username).toBe("sam"));
    expect(client.getQueryData(BOOKS_KEY)).toBeUndefined();
    // Once. Clearing on the way to null as well would drop the identity
    // queries too, so every moment of not knowing would refetch the thing that
    // produced it.
    expect(clears).toHaveBeenCalledTimes(1);
  });

  it("does not treat a moment of not knowing as somebody leaving", async () => {
    // The same person, whose identity query happened to be refetched from
    // nothing. Clearing on the way to null would drop their whole shelf, and
    // the identity queries with it, for an answer that came back identical.
    api.on("/auth/me", { body: makeUser({ id: 1, username: "kim" }) });
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
    client.setQueryData(BOOKS_KEY, BOOKS);
    const clears = vi.spyOn(client, "clear");

    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    heldAnswer = makeUser({ id: 1, username: "kim" });
    await forgetTheIdentity(client, held);
    await waitFor(() => expect(result.current.user).toBeNull());

    await act(async () => {
      release();
      await held;
    });
    await waitFor(() => expect(result.current.user?.username).toBe("kim"));

    expect(clears).not.toHaveBeenCalled();
    expect(client.getQueryData(BOOKS_KEY)).toEqual(BOOKS);
  });

  it("reports no switch when the identity is simply the proxy's", async () => {
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });
    const { result } = renderSession();

    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
    expect(result.current.isSwitched).toBe(false);
  });
});

describe("useSession switched into a test account under proxy", () => {
  /**
   * The precedence this mode did not have before: the proxy header is the
   * default identity, a switch token overrides it, and clearing the token
   * restores it. The server decides all three; what is asserted here is that
   * this hook asks it again at each of those moments, because its answer
   * depends on a token it does not send until now.
   */
  beforeEach(() => serverMode(AuthMode.proxy, false));

  // Fixed ids, because the account the server names and the account stored
  // beside the token are the same row, and `isSwitched` compares them. A fresh
  // id per call would make every one of these tests a different pair of people.
  const admin = () => makeUser({ id: 1, username: "boss", is_admin: true });
  const tester = () => makeUser({ id: 2, username: "tester" });

  it("takes the switched identity from the server, not from the token", async () => {
    api.on("/auth/me", { body: admin() });
    const { result } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("boss"));

    api.on("/auth/me", { body: tester() });
    act(() => result.current.signIn(tester(), "switch-token"));

    await waitFor(() => expect(result.current.user?.username).toBe("tester"));
    expect(localStorage.getItem("token")).toBe("switch-token");
  });

  it("drops the previous member's cache on the way in", async () => {
    api.on("/auth/me", { body: admin() });
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("boss"));
    client.setQueryData(BOOKS_KEY, BOOKS);

    api.on("/auth/me", { body: tester() });
    act(() => result.current.signIn(tester(), "switch-token"));

    await waitFor(() => expect(client.getQueryData(BOOKS_KEY)).toBeUndefined());
  });

  it("offers the way back, and only while switched", async () => {
    api.on("/auth/me", { body: admin() });
    const { result } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("boss"));
    expect(result.current.isSwitched).toBe(false);

    api.on("/auth/me", { body: tester() });
    act(() => result.current.signIn(tester(), "switch-token"));

    await waitFor(() => expect(result.current.isSwitched).toBe(true));
  });

  it("reports no switch once the server stops honouring the token", async () => {
    // Expiry, or the flag coming off the row: either way the server falls back
    // to the header, and the app is the admin again with a dead token still in
    // localStorage. Offering "Return to my account" then is an offer to
    // somebody who already is themselves.
    api.on("/auth/me", { body: admin() });
    localStorage.setItem("token", "expired-switch-token");
    localStorage.setItem("user", JSON.stringify(tester()));

    const { result } = renderSession();

    await waitFor(() => expect(result.current.user?.username).toBe("boss"));
    expect(result.current.isSwitched).toBe(false);
  });

  it("returns to the proxy identity when the token goes", async () => {
    api.on("/auth/me", { body: tester() });
    localStorage.setItem("token", "switch-token");
    localStorage.setItem("user", JSON.stringify(tester()));
    const { result } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("tester"));

    api.on("/auth/me", { body: admin() });
    act(() => result.current.signOut());

    await waitFor(() => expect(result.current.user?.username).toBe("boss"));
    expect(result.current.isSwitched).toBe(false);
    expect(localStorage.getItem("token")).toBeNull();
  });

  it("tells the server to drop the cover cookie on the way back", async () => {
    // The switch set one, scoped to /covers and naming the test account. It is
    // the server's and outlives the tab, so returning has to clear it.
    api.on("/auth/me", { body: tester() });
    localStorage.setItem("token", "switch-token");
    localStorage.setItem("user", JSON.stringify(tester()));
    const { result } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("tester"));

    api.on("/auth/me", { body: admin() });
    act(() => result.current.signOut());

    await waitFor(() =>
      expect(api.lastCall("/auth/logout", "POST")).toBeDefined(),
    );
  });

  it("drops the test account's cache on the way back", async () => {
    // This one pins `signOut`'s own clear rather than the identity effect:
    // under proxy the way back **is** signOut, and it clears before the server
    // has said who the caller is now.
    api.on("/auth/me", { body: tester() });
    localStorage.setItem("token", "switch-token");
    localStorage.setItem("user", JSON.stringify(tester()));
    const { result, client } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("tester"));
    client.setQueryData(BOOKS_KEY, BOOKS);

    api.on("/auth/me", { body: admin() });
    act(() => result.current.signOut());

    await waitFor(() => expect(client.getQueryData(BOOKS_KEY)).toBeUndefined());
  });
});

describe("useGoBack", () => {
  /**
   * Rendered inside a real router, because the whole behaviour is a property
   * of the router's history: `location.key` is the string "default" only for
   * the first entry, which is exactly the case `navigate(-1)` cannot handle.
   */
  function renderGoBack(entries: string[]) {
    return renderHook(
      () => ({ goBack: useGoBack(), location: useLocation() }),
      {
        wrapper: ({ children }: { children: ReactNode }) =>
          createElement(MemoryRouter, { initialEntries: entries }, children),
      },
    );
  }

  it("goes back when there is somewhere to go back to", () => {
    const { result } = renderGoBack(["/", "/book/1"]);

    act(() => result.current.goBack());

    expect(result.current.location.pathname).toBe("/");
  });

  it("goes to the library on a deep link with no history", () => {
    // A reload, a shared link or a PWA cold start at /book/1. navigate(-1)
    // does nothing at all here: no navigation, no error, nothing on screen.
    const { result } = renderGoBack(["/book/1"]);

    act(() => result.current.goBack());

    expect(result.current.location.pathname).toBe("/");
  });

  it("honours a fallback of its own", () => {
    const { result } = renderHook(
      () => ({ goBack: useGoBack("/loans"), location: useLocation() }),
      {
        wrapper: ({ children }: { children: ReactNode }) =>
          createElement(
            MemoryRouter,
            { initialEntries: ["/book/1"] },
            children,
          ),
      },
    );

    act(() => result.current.goBack());

    expect(result.current.location.pathname).toBe("/loans");
  });
});

describe("useRowWrite", () => {
  it("reports a slow failure on one row after a later row's write succeeded", async () => {
    // The shape a mutation hook's own `error` gets wrong: it is the latest
    // call's, the second row's here, which succeeded. A purge held open on a
    // third book is another write keyed by the same field, so it marks a row
    // here only if the pending calls are not filtered by this write's key.
    const first = heldOpen();
    const other = heldOpen();
    api.on("/api/books/7/restore", first.respond);
    api.on("/api/books/8/restore", { body: {} });
    api.on("/api/books/9/permanent", other.respond, "DELETE");
    const { result } = renderHookWithProviders(() => ({
      restore: useRowWrite(getRestoreBookMutationOptions, "bookId"),
      purge: useRowWrite(getPurgeBookMutationOptions, "bookId"),
    }));

    act(() => result.current.purge.mutate({ bookId: 9 }));
    act(() => result.current.restore.mutate({ bookId: 7 }));
    act(() => result.current.restore.mutate({ bookId: 8 }));
    await waitFor(() =>
      expect(result.current.restore.pendingRows).toEqual(new Set([7])),
    );
    expect(result.current.purge.pendingRows).toEqual(new Set([9]));
    first.release({ status: 404, body: { detail: "Book not found" } });

    await waitFor(() =>
      expect(result.current.restore.error).toMatchObject({
        message: "Book not found",
      }),
    );
    expect(result.current.restore.pendingRows).toEqual(new Set());
    other.release({ status: 204 });
  });

  it("refuses at the type check a row key its write does not carry", async () => {
    // At run time a misspelt key marks nothing and says nothing, so the type
    // check is what refuses it. `@ts-expect-error` is itself an error once the
    // line under it compiles, and `tsconfig.json` includes `tests`, so a
    // signature that stops refusing turns the type check red. The first call
    // carries no directive, so one that refused every key would too. Row zero
    // is a row, so a truthiness test in place of the type test would show here.
    const held = heldOpen();
    api.on("/api/books/0/restore", held.respond);
    const { result } = renderHookWithProviders(() => [
      useRowWrite(getRestoreBookMutationOptions, "bookId"),
      // @ts-expect-error not a field of the variables
      useRowWrite(getRestoreBookMutationOptions, "bookid"),
    ]);

    act(() => result.current[0]!.mutate({ bookId: 0 }));

    await waitFor(() =>
      expect(result.current.map((write) => write.pendingRows)).toEqual([
        new Set([0]),
        new Set(),
      ]),
    );
    held.release({ body: {} });
  });
});

describe("asking which Book already holds a file", () => {
  it("asks in chunks no larger than the schema takes", () => {
    const files = propertiesOf("HoldersIn")["files"]!;

    expect(FILES_PER_LOOKUP).toBe(boundOf(files, "maxItems"));
  });
});

describe("reportEach", () => {
  it("sends the next reference only once the one before it is answered", async () => {
    // The per book ceiling is held on the server whatever arrives; a client
    // sending a book's files at once is the client that makes it race.
    let answer!: () => void;
    const post = vi.fn<(reference: string) => Promise<void>>(
      () =>
        new Promise<void>((resolve) => {
          answer = resolve;
        }),
    );

    const sending = reportEach(["first", "second"], post);
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    answer();
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    answer();
    await sending;

    expect(post.mock.calls.map(([reference]) => reference)).toEqual([
      "first",
      "second",
    ]);
  });
});

/** A file as a folder pick hands it over, under the folder `Books`. */
function picked(path: string, bytes = "bytes"): File {
  const file = new File([bytes], path.split("/").at(-1)!);
  Object.defineProperty(file, "webkitRelativePath", {
    value: `Books/${path}`,
  });
  return file;
}

function stored(
  id: number,
  path: string,
  fields: { size_bytes?: number; partial_md5?: string } = {},
) {
  return {
    id,
    book_id: id * 10,
    root_label: "Books",
    relative_path: path,
    root_confirmed: true,
    size_bytes: null,
    file_modified_at: null,
    partial_md5: null,
    created_at: "2026-10-01T00:00:00Z",
    confirmed_at: "2026-10-01T00:00:00Z",
    missing_since: null,
    ...fields,
  };
}

type Sent = { seen: { reference_id: number }[]; missing: number[] };

describe("sweepFolder", () => {
  const UNDER = "/api/books/digital-references";
  const SWEEP = "/api/books/digital-references/sweep";

  /** The server holding these references under `Books`, served in pages of
   * `REFERENCES_PER_PAGE`, answering a sweep with every id it was sent. */
  function holding(...references: ReturnType<typeof stored>[]) {
    api.on(
      UNDER,
      (url) => {
        const page = Number(new URL(url, "http://x").searchParams.get("page"));
        const start = (page - 1) * REFERENCES_PER_PAGE;
        return {
          body: {
            items: references.slice(start, start + REFERENCES_PER_PAGE),
            total: references.length,
            page,
            page_size: REFERENCES_PER_PAGE,
          },
        };
      },
      "GET",
    );
    api.on(
      SWEEP,
      (_url, init) => {
        const body = JSON.parse(String(init?.body)) as Sent;
        return {
          body: {
            seen: body.seen.map((one) => one.reference_id),
            missing: body.missing,
          },
        };
      },
      "POST",
    );
  }

  function sweeps(): Sent[] {
    return api.calls
      .filter((call) => call.url.includes(SWEEP))
      .map((call) => call.body as Sent);
  }

  it("confirms a file still there and lists one that is gone without marking it", async () => {
    holding(stored(1, "Le Guin/Dune.epub"), stored(2, "Gone.epub"));

    const [swept] = await sweepFolder([picked("Le Guin/Dune.epub")]);

    expect(sweeps()).toEqual([
      {
        root_label: "Books",
        seen: [expect.objectContaining({ reference_id: 1 })],
        missing: [],
      },
    ]);
    expect(swept).toEqual({
      kind: "checked",
      root: "Books",
      seen: 1,
      moved: 0,
      notFound: [{ referenceId: 2, bookId: 20, path: "Gone.epub" }],
      marked: null,
      bookIds: [10],
    });
  });

  it("sends a sighting with the fingerprint read from the file", async () => {
    holding(stored(1, "Dune.epub"));

    await sweepFolder([picked("Dune.epub")]);

    expect(sweeps()[0]!.seen).toEqual([
      expect.objectContaining({ reference_id: 1, size_bytes: 5 }),
    ]);
  });

  it("asks nothing for files picked one at a time", async () => {
    const swept = await sweepFolder([new File(["bytes"], "Dune.epub")]);

    expect(swept).toEqual([]);
    expect(api.calls).toEqual([]);
  });

  it("sweeps nothing under a folder with nothing saved", async () => {
    holding();

    expect(await sweepFolder([picked("Dune.epub")])).toEqual([]);
    expect(sweeps()).toEqual([]);
  });

  it("takes a folder holding none of the saved paths for a different one", async () => {
    // Two members' Calibre libraries share Calibre's default name, so a pick of
    // one would otherwise list every file of the other as gone.
    holding(stored(1, "Theirs/Dune.epub"), stored(2, "Theirs/Emma.epub"));

    const swept = await sweepFolder([picked("Mine/Kindred.epub")]);

    expect(swept).toEqual([{ kind: "different", root: "Books", saved: 2 }]);
    expect(sweeps()).toEqual([]);
  });

  it("reads every page of the references under the folder", async () => {
    const many = Array.from({ length: REFERENCES_PER_PAGE + 1 }, (_, at) =>
      stored(at + 1, `${at}.epub`),
    );
    holding(...many);

    const [swept] = await sweepFolder([picked(`${REFERENCES_PER_PAGE}.epub`)]);

    expect(swept).toMatchObject({ seen: 1 });
    expect(sweeps()[0]!.seen).toEqual([
      expect.objectContaining({ reference_id: REFERENCES_PER_PAGE + 1 }),
    ]);
  });

  it("sends no more sightings in one request than the schema takes", async () => {
    const many = Array.from({ length: FILES_PER_LOOKUP + 1 }, (_, at) =>
      stored(at + 1, `${at}.epub`),
    );
    holding(...many);

    await sweepFolder(many.map((one) => picked(one.relative_path)));

    expect(sweeps().map((sent) => sent.seen.length)).toEqual([
      FILES_PER_LOOKUP,
      1,
    ]);
  });

  it("finds a file moved inside the folder by its fingerprint and does not list it", async () => {
    const moved = picked("Sorted/Dune.epub", "the bytes of dune");
    const digest = await partialMd5(moved);
    holding(
      stored(1, "Kept.epub"),
      stored(2, "Dune.epub", { size_bytes: moved.size, partial_md5: digest }),
    );

    const [swept] = await sweepFolder([picked("Kept.epub"), moved]);

    expect(swept).toMatchObject({ moved: 1, notFound: [] });
  });

  it("lists a gone file beside a file of its size with other bytes", async () => {
    // The digest decides, not the size: a size match alone is any other book.
    const gone = picked("Gone.epub", "the bytes of dune");
    const digest = await partialMd5(gone);
    holding(
      stored(1, "Kept.epub"),
      stored(2, "Gone.epub", { size_bytes: gone.size, partial_md5: digest }),
    );

    const [swept] = await sweepFolder([
      picked("Kept.epub"),
      picked("Other.epub", "the bytes of emma"),
    ]);

    expect(swept).toMatchObject({
      moved: 0,
      notFound: [{ referenceId: 2, bookId: 20, path: "Gone.epub" }],
    });
  });

  it("marks the files not found only when asked, and says which it marked", async () => {
    holding(stored(2, "Gone.epub"));

    const marked = await markMissing("Books", [
      { referenceId: 2, bookId: 20, path: "Gone.epub" },
    ]);

    expect(marked).toEqual([2]);
    expect(sweeps()).toEqual([{ root_label: "Books", seen: [], missing: [2] }]);
  });
});

/** One file in a folder of this name. */
function inFolder(root: string): File {
  const file = new File(["bytes"], "Dune.epub");
  Object.defineProperty(file, "webkitRelativePath", {
    value: `${root}/Dune.epub`,
  });
  return file;
}

describe("useFolderSweep", () => {
  it("shows the latest pick's answer when an earlier one finishes last", async () => {
    const first = heldOpen();
    api.on(/root_label=Old/, first.respond, "GET");
    api.on(
      /root_label=New/,
      {
        body: {
          items: [{ ...stored(1, "Dune.epub"), root_label: "New" }],
          total: 1,
          page: 1,
          page_size: REFERENCES_PER_PAGE,
        },
      },
      "GET",
    );
    api.on(
      "/api/books/digital-references/sweep",
      { body: { seen: [1], missing: [] } },
      "POST",
    );
    const { result } = renderHookWithProviders(() => useFolderSweep());

    act(() => result.current.sweep([inFolder("Old")]));
    act(() => result.current.sweep([inFolder("New")]));
    await waitFor(() => expect(result.current.swept).not.toBeNull());
    first.release({
      body: {
        items: [{ ...stored(9, "Dune.epub"), root_label: "Old" }],
        total: 1,
        page: 1,
        page_size: REFERENCES_PER_PAGE,
      },
    });
    // The earlier pick's own sweep has been sent and answered, so its result
    // has had the chance to land.
    await waitFor(() =>
      expect(
        api.calls.some(
          (call) =>
            call.method === "POST" &&
            (call.body as { root_label: string }).root_label === "Old",
        ),
      ).toBe(true),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(result.current.swept?.map((one) => one.root)).toEqual(["New"]);
  });
});
