/** Tests for src/pages/hooks.ts: the cross-page session hook. */

import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { AuthMode } from "../../src/api/generated/model";
import { readStoredUser, useSession } from "../../src/pages/hooks";
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
