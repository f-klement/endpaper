/** Tests for src/app/components/AppearanceSync.tsx. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import AppearanceSync from "../../../src/app/components/AppearanceSync";
import { useTheme } from "../../../src/theme";
import { cacheAppearance } from "../../../src/theme/appearance";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

const APPEARANCE = "/api/users/me/appearance";

let api: MockApi;

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
});

function Probe({
  accountId = 1,
  signedIn = true,
}: {
  accountId?: number;
  signedIn?: boolean;
}) {
  const { appearance, setAppearance } = useTheme();
  return (
    <>
      {signedIn && <AppearanceSync accountId={accountId} />}
      <p data-testid="palette">{appearance.palette}</p>
      <p data-testid="mode">{appearance.mode}</p>
      <button onClick={() => setAppearance({ palette: "nord" })}>go nord</button>
    </>
  );
}

describe("AppearanceSync", () => {
  it("takes the appearance the account has stored", async () => {
    api.on(APPEARANCE, {
      body: { palette: "gruvbox", mode: "dark", wallpaper: null },
    });
    renderWithProviders(<Probe />);

    await waitFor(() =>
      expect(screen.getByTestId("palette")).toHaveTextContent("gruvbox"),
    );
    expect(document.documentElement.dataset.theme).toBe("gruvbox");
  });

  it("caches it, so the next boot paints it before the server answers", async () => {
    api.on(APPEARANCE, {
      body: { palette: "gruvbox", mode: "dark", wallpaper: null },
    });
    renderWithProviders(<Probe />);

    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem("appearance") ?? "{}").last).toBe("1"),
    );
  });

  it("paints this account's cached appearance before the server answers", async () => {
    // Two members on one laptop. Signing in as the second must not leave the
    // first one's palette on screen while the request is in flight.
    cacheAppearance(2, { palette: "solarized", mode: "light", wallpaper: null });
    api.on(APPEARANCE, {
      body: { palette: "solarized", mode: "light", wallpaper: null },
    });

    renderWithProviders(<Probe accountId={2} />);

    expect(screen.getByTestId("palette")).toHaveTextContent("solarized");
  });

  it("pushes a change back to the account", async () => {
    api.on(APPEARANCE, {
      body: { palette: "endpaper", mode: "light", wallpaper: null },
    });
    renderWithProviders(<Probe />);
    await waitFor(() => expect(api.lastCall(APPEARANCE, "GET")).toBeDefined());

    await userEvent.setup().click(screen.getByRole("button", { name: "go nord" }));

    await waitFor(() => {
      const call = api.lastCall(APPEARANCE, "PUT");
      expect(call?.body).toEqual({
        palette: "nord",
        mode: "light",
        wallpaper: null,
      });
    });
  });

  it("does not push the value it was just given", async () => {
    // The two directions would otherwise chase each other: adopting the
    // server's answer would count as a change and be written straight back.
    api.on(APPEARANCE, {
      body: { palette: "gruvbox", mode: "dark", wallpaper: null },
    });
    renderWithProviders(<Probe />);

    await waitFor(() =>
      expect(screen.getByTestId("palette")).toHaveTextContent("gruvbox"),
    );
    expect(api.lastCall(APPEARANCE, "PUT")).toBeUndefined();
  });

  it("does not push this device's cache over a stored choice", async () => {
    // The cache is a guess at what the server will say. Pushing it before the
    // answer arrives would overwrite the account's real preference with
    // whatever this browser happened to remember.
    cacheAppearance(1, { palette: "nord", mode: "dark", wallpaper: null });
    api.on(APPEARANCE, () => ({
      body: { palette: "gruvbox", mode: "dark", wallpaper: null },
    }));

    renderWithProviders(<Probe />);
    await waitFor(() =>
      expect(screen.getByTestId("palette")).toHaveTextContent("gruvbox"),
    );

    expect(api.lastCall(APPEARANCE, "PUT")).toBeUndefined();
  });

  it("keeps a change made while the request was in flight", async () => {
    // A fast hand on the settings page: the choice is newer than the answer,
    // so it wins and is pushed, rather than being reverted by a value that was
    // already on its way when it was made.
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      answer = resolve;
    });
    api.on(APPEARANCE, {
      body: { palette: "endpaper", mode: "light", wallpaper: null },
    });
    api.on(
      APPEARANCE,
      async () => {
        await held;
        return { body: { palette: "gruvbox", mode: "dark", wallpaper: null } };
      },
      "GET",
    );

    renderWithProviders(<Probe />);
    await userEvent.setup().click(screen.getByRole("button", { name: "go nord" }));
    answer();

    await waitFor(() =>
      expect(api.lastCall(APPEARANCE, "PUT")?.body).toMatchObject({
        palette: "nord",
      }),
    );
    expect(screen.getByTestId("palette")).toHaveTextContent("nord");
  });

  it("does not hand one account the answer cached for another", async () => {
    // The path carries no member id, so on the generated key every account
    // shares one cache entry. The client outlives a sign-out, so on a shared
    // device the next person in would be given the previous one's palette.
    api.on(APPEARANCE, (_url, init) =>
      (init.method ?? "GET") === "GET"
        ? { body: { palette: "gruvbox", mode: "dark", wallpaper: null } }
        : { body: { palette: "nord", mode: "dark", wallpaper: null } },
    );
    const { rerender } = renderWithProviders(<Probe accountId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("palette")).toHaveTextContent("gruvbox"),
    );
    const first = api.calls.filter(
      (call) => call.url.includes(APPEARANCE) && call.method === "GET",
    ).length;

    rerender(<Probe accountId={2} />);

    await waitFor(() =>
      expect(
        api.calls.filter(
          (call) => call.url.includes(APPEARANCE) && call.method === "GET",
        ).length,
      ).toBe(first + 1),
    );
  });

  it("stops writing to an account once it is gone", async () => {
    // The provider sits above the session gate and does not unmount on sign
    // out; this component does. Without the release, a change made from a
    // signed-out screen would be filed under whoever was last signed in and
    // would move `last` to them. Phase 3 puts a picker on that screen.
    api.on(APPEARANCE, {
      body: { palette: "gruvbox", mode: "dark", wallpaper: null },
    });
    const { rerender } = renderWithProviders(<Probe />);
    await waitFor(() =>
      expect(screen.getByTestId("palette")).toHaveTextContent("gruvbox"),
    );

    rerender(<Probe signedIn={false} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "go nord" }));

    const cache = JSON.parse(localStorage.getItem("appearance") ?? "{}");
    expect(cache.accounts["1"].palette).toBe("gruvbox");
  });

  it("leaves the look alone when the request fails", async () => {
    // The page is already painted from the cache by the time this asks, so a
    // failure means the reader keeps what they had rather than seeing anything
    // go wrong.
    cacheAppearance(1, { palette: "nord", mode: "dark", wallpaper: null });
    api.on(APPEARANCE, { status: 500, body: { detail: "no" } });

    renderWithProviders(<Probe />);

    await waitFor(() =>
      expect(screen.getByTestId("palette")).toHaveTextContent("nord"),
    );
    expect(api.lastCall(APPEARANCE, "PUT")).toBeUndefined();
  });
});
