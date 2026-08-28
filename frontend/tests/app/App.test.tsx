/** Tests for src/app/App.tsx: the session gate and route table. */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  // The shell asks for it as soon as it knows who is signed in. Stubbed here
  // rather than left unhandled, because an unhandled request in this suite is
  // meant to be a failure and this one would be swallowed by the hook.
  api.on("/api/users/me/appearance", {
    body: { palette: null, mode: null, wallpaper: null },
  });
  api.on(/\/api\/books\?/, { body: makeBookPage([]) });
  api.on("/api/stats", { body: makeStats() });
  // App owns a real BrowserRouter, so the path is jsdom's own and survives
  // between tests. Reset it, or one test's deep link decides the next one.
  window.history.pushState({}, "", "/");
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

  it("puts no appearance picker in front of the login screen", async () => {
    // `ThemeProvider` sits above the session gate and does not unmount on sign
    // out, so a picker reachable from here would write a choice into the cache
    // of the member who left and move `last` to them. That is the failure
    // `ThemeProvider.release` exists to prevent, and the route table is what
    // keeps it out of reach: every path renders the login page signed out.
    window.history.pushState({}, "", "/settings/appearance/theme");
    renderApp();
    await screen.findByRole("button", { name: "Sign In" });

    expect(
      screen.queryByRole("group", { name: "Palette" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Wallpaper" }),
    ).not.toBeInTheDocument();
  });

  it("reaches the appearance picker once there is a session", async () => {
    signIn(makeUser({ username: "kim" }));
    window.history.pushState({}, "", "/settings/appearance/theme");
    renderApp();

    expect(
      await screen.findByRole("group", { name: "Palette" }),
    ).toBeInTheDocument();
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

    expect(
      await screen.findByRole("button", { name: /kim/ }),
    ).toBeInTheDocument();
  });

  it("offers a proxy admin every settings screen", async () => {
    // The regression this exists for: the settings index took `is_admin` from
    // `localStorage["user"]` for one round. Under proxy that key is written
    // only by `signIn`, which fires only on a switch into a test account, and
    // a test account is never an admin, so it is null for a proxy admin
    // always. They were offered three of the six entries, the other three
    // reachable only by typing the URL.
    //
    // It has to be asserted here rather than in `SettingsPage.test.tsx`,
    // because the account is a prop now and a unit test can only assert what
    // it passed in. What was wrong was where `AppRoutes` reads the identity,
    // and under proxy that is `me.data`.
    api.on("/auth/me", { body: makeUser({ username: "kim", is_admin: true }) });
    window.history.pushState({}, "", "/settings");
    renderApp();

    await screen.findByRole("heading", { name: "Settings" });
    // Scoped to the index's own nav: the whole app is rendered here, so the
    // bar's links are on the page too.
    const index = screen.getByRole("navigation", { name: "Settings" });
    expect(
      within(index)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual([
      "/settings/appearance",
      "/settings/catalogue",
      "/settings/library",
      "/settings/lending",
      "/settings/data",
      "/settings/about",
    ]);
    expect(localStorage.getItem("user")).toBeNull();
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

describe("a session that ended at the reverse proxy", () => {
  // The bug this describes was reported live: a page that reloaded for ever
  // behind a spinner, with two tabs open. Two faults composed to make it, and
  // neither was wrong on its own, which is why a header assertion and a config
  // assertion would both have passed while the app looped. So it is asserted
  // as behaviour: given the answer an expired portal session gives, the app
  // must end up somewhere a person can act on, having reloaded at most once.
  //
  // Fault 1 was the request: with no Accept header the browser sends a
  // wildcard, and Authelia redirects anything that accepts text/html rather
  // than answering 401. Fault 2 was the reload: the service worker precached
  // index.html, so `/` was served from cache and the portal never saw the
  // navigation that would have let it sign the reader back in.

  /** The key `mutator.ts` records its reload under, per tab. */
  const MARKER = "endpaper.edge-reload";

  beforeEach(() => {
    // Replaced wholesale rather than spied on, because a reload in a test
    // environment is not a reload. `search` and `hash` are part of the stub
    // because App owns a real BrowserRouter, which reads all three to build
    // its first entry: without them the initial path is "/undefinedundefined".
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        href: "http://localhost/",
        origin: "http://localhost",
        pathname: "/",
        search: "",
        hash: "",
        reload: vi.fn(),
      },
    });
  });

  /**
   * Mount a fresh copy of the app, standing in for a fresh document.
   *
   * `mutator.ts` remembers in module state whether this page load has already
   * asked for a reload, because its lifetime is meant to be the document's. A
   * second test is a second page load, so it needs a second module.
   */
  async function renderFreshApp(queryClient = createTestQueryClient()) {
    vi.resetModules();
    const { default: FreshApp } = await import("../../src/app/App");
    return render(<FreshApp queryClient={queryClient} />);
  }

  /** What an expired portal cookie does to every request, not just the API. */
  function expireEverything() {
    // Under `redirect: "manual"` the 302 arrives as an opaque redirect.
    // Registered last, so it wins over the stubs in the outer beforeEach.
    api.on(/./, { status: 0, type: "opaqueredirect" });
  }

  it("reloads once for the whole batch, and claims nothing yet", async () => {
    // Six requests are in flight on this screen, so an expiry resolves six
    // opaque redirects together. Counting calls rather than page loads made
    // five of them believe they were looping, and put up a screen saying
    // reloading had not helped before the reload had even happened.
    signIn(makeUser({ username: "kim" }));
    expireEverything();

    await renderFreshApp();

    await waitFor(() =>
      expect(window.location.reload).toHaveBeenCalledTimes(1),
    );
    expect(
      screen.queryByRole("heading", { name: "Your session ended" }),
    ).not.toBeInTheDocument();
  });

  it("says so instead of reloading again, once a page load already has", async () => {
    // The marker is what survives a reload, so a marker plus a fresh module is
    // the state a reloaded tab boots into. This is the loop, broken: the
    // reader gets a sentence and a button rather than another reload.
    sessionStorage.setItem(MARKER, String(Date.now() - 1000));
    signIn(makeUser({ username: "kim" }));
    expireEverything();

    await renderFreshApp();

    expect(
      await screen.findByRole("heading", { name: "Your session ended" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sign in again" }),
    ).toBeInTheDocument();
    expect(window.location.reload).not.toHaveBeenCalled();
  });

  it("does not leave the reader on the spinner", async () => {
    // The reported symptom, and the reason this screen exists at all. The
    // shell was showing "Signing you in" when the requests started being
    // redirected, and nothing ever replaced it.
    sessionStorage.setItem(MARKER, String(Date.now() - 1000));
    signIn(makeUser({ username: "kim" }));
    expireEverything();

    await renderFreshApp();

    await screen.findByRole("heading", { name: "Your session ended" });
    expect(screen.queryByText("Signing you in")).not.toBeInTheDocument();
  });

  it("does not keep the library in memory behind the dead end", async () => {
    // This branch neither reloads nor navigates, so it is the only way a
    // session ends while the document lives on. Without emptying the cache the
    // QueryClient goes on holding every book the reader fetched, behind a
    // screen telling them their session is over.
    sessionStorage.setItem(MARKER, String(Date.now() - 1000));
    signIn(makeUser({ username: "kim" }));
    const client = createTestQueryClient();

    await renderFreshApp(client);
    await screen.findByRole("heading", { name: /Library/ });
    const fetched = () =>
      client
        .getQueryCache()
        .getAll()
        .filter((query) => query.state.data !== undefined);
    // Or the assertion below is true of an empty cache and proves nothing.
    expect(fetched().length).toBeGreaterThan(0);

    expireEverything();
    // Inside act: the refetch is driven from the test rather than from a user
    // event, and its rejection is what flips the shell to the dead end.
    await act(async () => {
      await client.refetchQueries();
    });

    await screen.findByRole("heading", { name: "Your session ended" });
    expect(fetched()).toEqual([]);
  });
});
