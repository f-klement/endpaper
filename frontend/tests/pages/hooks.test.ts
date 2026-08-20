/** Tests for src/pages/hooks.ts: the cross-page session hook. */

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthMode, type UserOut } from "../../src/api/generated/model";
import { readStoredUser, useGoBack, useSession } from "../../src/pages/hooks";
import { makeUser, resetIds } from "../factories";
import { createTestQueryClient, mockApi, type MockApi } from "../utils";

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
const BOOKS = { items: [{ id: 1, title: "A private diary", is_private: true }] };

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

    await waitFor(() => expect(api.lastCall("/auth/logout", "POST")).toBeDefined());
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
    localStorage.setItem("user", JSON.stringify(makeUser({ username: "stale" })));
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });

    const { result } = renderSession();
    await waitFor(() => expect(result.current.user?.username).toBe("kim"));
    const settled = api.calls.filter((call) => call.url.includes("/auth/config")).length;
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
  async function forgetTheIdentity(client: QueryClient, release: Promise<void>) {
    api.on("/auth/me", async () => {
      await release;
      return { body: heldAnswer };
    });
    await act(async () => {
      void client.resetQueries({
        predicate: (query) => JSON.stringify(query.queryKey).includes("/auth/me"),
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
    return renderHook(() => ({ goBack: useGoBack(), location: useLocation() }), {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(MemoryRouter, { initialEntries: entries }, children),
    });
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
          createElement(MemoryRouter, { initialEntries: ["/book/1"] }, children),
      },
    );

    act(() => result.current.goBack());

    expect(result.current.location.pathname).toBe("/loans");
  });
});
