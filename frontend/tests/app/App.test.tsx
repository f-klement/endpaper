/** Tests for src/app/App.tsx: the session gate and route table. */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "../../src/app/App";
import { createTestQueryClient, mockApi, signIn, type MockApi } from "../utils";
import { makeBookPage, makeStats, makeUser, resetIds } from "../factories";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/auth/config", { body: { registration_enabled: true } });
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

  it("shows the library and sidebar when signed in", async () => {
    signIn(makeUser({ username: "kim" }));
    renderApp();

    expect(
      await screen.findByRole("heading", { name: /Library/ }),
    ).toBeInTheDocument();
    // Scoped to the sidebar: Home renders its own "+ Scan" link too.
    const sidebar = within(screen.getByRole("navigation"));
    expect(sidebar.getByRole("link", { name: /Scan/ })).toHaveAttribute(
      "href",
      "/scan",
    );
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
