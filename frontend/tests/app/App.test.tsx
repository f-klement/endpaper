/** Tests for src/app/App.tsx: the session gate and route table. */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { AuthMode } from "../../src/api/generated/model";
import App from "../../src/app/App";
import { BAR_OFFSET } from "../../src/app/components/NavBar";
import { createTestQueryClient, mockApi, signIn, type MockApi } from "../utils";
import { makeBookPage, makeStats, makeUser, resetIds } from "../factories";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/auth/config", {
    body: { auth_mode: AuthMode.local, registration_enabled: true },
  });
  api.on("/api/settings/login-image", {
    status: 404,
    body: { detail: "none" },
  });
  api.on("/api/books/tags", { body: [] });
  api.on(/\/api\/books\?/, { body: makeBookPage([]) });
  api.on("/api/stats", { body: makeStats() });
});

function renderApp() {
  // App owns its own router and providers, so it is rendered directly rather
  // than through renderWithProviders, which would nest a second router.
  return render(<App queryClient={createTestQueryClient()} />);
}

describe("App", () => {
  it("shows the login page when signed out", async () => {
    renderApp();
    expect(
      await screen.findByRole("button", { name: "Sign In" }),
    ).toBeInTheDocument();
  });

  it("hides the sidebar when signed out", async () => {
    // There is no route reachable without an account.
    renderApp();
    await screen.findByRole("button", { name: "Sign In" });
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("shows the library and the top bar when signed in", async () => {
    signIn(makeUser({ username: "kim" }));
    renderApp();

    expect(
      await screen.findByRole("heading", { name: /Library/ }),
    ).toBeInTheDocument();
    // Scoped to the bar: Home renders its own "+ Scan" link too.
    const bar = within(screen.getByRole("navigation"));
    expect(bar.getByRole("link", { name: "Scan" })).toHaveAttribute(
      "href",
      "/scan",
    );
  });

  it("leaves room for the fixed bar rather than under it", async () => {
    // The bar is fixed, so the content needs padding of its own or the first
    // thing on every page sits behind it. Asserted against the exported
    // offset rather than a literal, so the two cannot drift apart here.
    signIn(makeUser({ username: "kim" }));
    const { container } = renderApp();
    await screen.findByRole("heading", { name: /Library/ });

    expect(container.querySelector(`.${BAR_OFFSET}`)).toBeInTheDocument();
  });

  it("survives a corrupt cached account", async () => {
    localStorage.setItem("token", "t");
    localStorage.setItem("user", "{not json");
    renderApp();

    // Falls back to signed-out rather than white-screening.
    expect(
      await screen.findByRole("button", { name: "Sign In" }),
    ).toBeInTheDocument();
  });
});

describe("App under proxy auth", () => {
  beforeEach(() => {
    api.on("/auth/config", {
      body: { auth_mode: AuthMode.proxy, registration_enabled: false },
    });
  });

  it("shows no auth screen at all", async () => {
    // The upstream authenticated the request and named the member in a
    // header. There is no password here to ask for.
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });
    renderApp();

    expect(
      await screen.findByRole("heading", { name: /Library/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sign In" }),
    ).not.toBeInTheDocument();
  });

  it("ignores a stale account in localStorage", async () => {
    signIn(makeUser({ username: "stale" }));
    api.on("/auth/me", { body: makeUser({ username: "kim" }) });
    renderApp();

    expect(await screen.findByRole("button", { name: /kim/ })).toBeInTheDocument();
  });

  it("reports an unidentified caller rather than a login form", async () => {
    // Almost always a deployment mistake, and a form nobody can use is worse
    // than saying so: this deployment has no local passwords to offer.
    api.on("/auth/me", { status: 401, body: { detail: "nope" } });
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Something broke" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sign In" }),
    ).not.toBeInTheDocument();
  });
});
