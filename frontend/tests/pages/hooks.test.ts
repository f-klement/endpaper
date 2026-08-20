/** Tests for src/pages/hooks.ts: the cross-page session hook. */

import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { AuthMode } from "../../src/api/generated/model";
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
  return renderHook(() => useSession(), {
    wrapper: ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children),
  });
}

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
