/** Tests for src/app/components/NavBar.tsx: the top bar and its menu. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthMode } from "../../../src/api/generated/model";
import NavBar, {
  BAR_HEIGHT,
  BAR_OFFSET,
  BAR_STICKY,
} from "../../../src/app/components/NavBar";
import { makeUser, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

function renderNav(
  mode: AuthMode = AuthMode.local,
  onSignOut = vi.fn(),
  isSwitched = false,
) {
  renderWithProviders(
    <NavBar
      user={makeUser({ username: "kim" })}
      mode={mode}
      isSwitched={isSwitched}
      onSignOut={onSignOut}
    />,
  );
  return onSignOut;
}

/** The account menu, opened. */
async function openMenu() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /kim/ }));
  return { user, menu: within(screen.getByRole("menu")) };
}

describe("the bar's own height", () => {
  it("is the offset the content clears it by", () => {
    // Tailwind scans for whole class names, so these cannot be composed from
    // one number. This is what keeps them saying the same thing.
    expect(BAR_OFFSET).toBe(BAR_HEIGHT.replace("h-", "pt-"));
  });

  it("is where a sticky heading stops", () => {
    // The appearance picker's family headings stick under the bar. Composed
    // from the height they would generate no CSS, and a sticky heading with no
    // offset slides under the bar rather than stopping at it.
    expect(BAR_STICKY).toBe(BAR_HEIGHT.replace("h-", "top-"));
  });

  it("is applied to the bar", () => {
    renderNav();
    expect(screen.getByRole("navigation").className).toContain(BAR_HEIGHT);
  });
});

describe("the bar itself", () => {
  it("keeps the library, scanning and loans on the bar", () => {
    renderNav();
    const bar = within(screen.getByRole("navigation"));

    expect(bar.getByRole("link", { name: "Library" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(bar.getByRole("link", { name: "Scan" })).toHaveAttribute(
      "href",
      "/scan",
    );
    expect(bar.getByRole("link", { name: "Loans" })).toHaveAttribute(
      "href",
      "/loans",
    );
  });

  it("names the scan page Scan, whatever glyph it wears", () => {
    // The icon is a magnifying glass because that screen is a lookup. The
    // label must not follow it to "Search", which is the library search box.
    renderNav();
    expect(
      screen.queryByRole("link", { name: "Search" }),
    ).not.toBeInTheDocument();
  });

  it("keeps everything else off the bar", () => {
    renderNav();
    const bar = screen.getByRole("navigation");
    for (const name of ["Stats", "Settings", "Trash"]) {
      expect(
        within(bar).queryByRole("link", { name }),
      ).not.toBeInTheDocument();
    }
  });

  it("marks the current section by more than colour", () => {
    // A bar marker under the active link, and aria-current with it, so the
    // current page is not a hue two people cannot tell apart.
    renderNav();
    const active = screen.getByRole("link", { name: "Library" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toContain("after:");
  });

  it("shows who is signed in without opening anything", () => {
    renderNav();
    expect(screen.getByRole("button", { name: /kim/ })).toBeInTheDocument();
  });

  it("announces the trigger as a menu button", () => {
    renderNav();
    const trigger = screen.getByRole("button", { name: /kim/ });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});

describe("the menu", () => {
  it("stays closed until the trigger is used", () => {
    renderNav();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("reports itself as expanded once open", async () => {
    renderNav();
    await openMenu();
    expect(screen.getByRole("button", { name: /kim/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("holds everything that left the bar", async () => {
    renderNav();
    const { menu } = await openMenu();

    for (const [name, href] of [
      ["Series", "/series"],
      ["Stats", "/stats"],
      ["Settings", "/settings"],
      ["Possible duplicates", "/duplicates"],
      ["Trash", "/trash"],
    ] as const) {
      expect(menu.getByRole("menuitem", { name })).toHaveAttribute(
        "href",
        href,
      );
    }
  });

  it("keeps the wishlist as a filtered library view", async () => {
    renderNav();
    const { menu } = await openMenu();
    expect(menu.getByRole("menuitem", { name: "Wishlist" })).toHaveAttribute(
      "href",
      "/?status=want_to_read&ownership=not_owned",
    );
  });

  it("closes after a destination is chosen", async () => {
    renderNav();
    const { user, menu } = await openMenu();

    await user.click(menu.getByRole("menuitem", { name: "Trash" }));

    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });

  it("closes when a click lands outside it", async () => {
    renderNav();
    const { user } = await openMenu();

    await user.click(document.body);

    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
  });

  it("closes on Escape and hands focus back to the trigger", async () => {
    // Without this the only way out by keyboard is to tab through every item.
    renderNav();
    const { user } = await openMenu();

    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /kim/ })).toHaveFocus();
  });
});

describe("the account entries", () => {
  it("signs out through its callback", async () => {
    const onSignOut = renderNav();
    const { user, menu } = await openMenu();

    await user.click(menu.getByRole("menuitem", { name: "Logout" }));

    expect(onSignOut).toHaveBeenCalled();
  });

  it("switches account without ending the current session", async () => {
    // Deliberately keeps the session until a new login succeeds.
    const onSignOut = renderNav();
    const { menu } = await openMenu();

    expect(
      menu.getByRole("menuitem", { name: "Switch Account" }),
    ).toHaveAttribute("href", "/login");
    expect(onSignOut).not.toHaveBeenCalled();
  });

  describe("under proxy auth", () => {
    it("offers no sign out", async () => {
      // The upstream owns the session. Signing out here would clear local
      // state and the app would re-identify the same person immediately.
      renderNav(AuthMode.proxy);
      const { menu } = await openMenu();
      expect(
        menu.queryByRole("menuitem", { name: "Logout" }),
      ).not.toBeInTheDocument();
    });

    it("offers no switch account", async () => {
      renderNav(AuthMode.proxy);
      const { menu } = await openMenu();
      expect(
        menu.queryByRole("menuitem", { name: "Switch Account" }),
      ).not.toBeInTheDocument();
    });

    it("still offers everything that is not about the session", async () => {
      renderNav(AuthMode.proxy);
      const { menu } = await openMenu();
      expect(menu.getByRole("menuitem", { name: "Settings" })).toBeVisible();
      expect(
        menu.getByRole("menuitem", { name: /Export Library/ }),
      ).toBeVisible();
    });

    it("still says who is signed in", async () => {
      renderNav(AuthMode.proxy);
      expect(screen.getByRole("button", { name: /kim/ })).toBeInTheDocument();
    });

    it("offers no way back when there is nothing to come back from", async () => {
      renderNav(AuthMode.proxy);
      const { menu } = await openMenu();
      expect(
        menu.queryByRole("menuitem", { name: "Return to my account" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("switched into a test account", () => {
    it("offers the way back", async () => {
      // A test account is not an admin, so the Settings section that started
      // the switch is not there to end it, and this mode offers nothing else.
      // Without this the admin is somebody else with no control on screen.
      renderNav(AuthMode.proxy, vi.fn(), true);
      const { menu } = await openMenu();
      expect(
        menu.getByRole("menuitem", { name: "Return to my account" }),
      ).toBeVisible();
    });

    it("hands the session back when it is chosen", async () => {
      const onSignOut = renderNav(AuthMode.proxy, vi.fn(), true);
      const { user, menu } = await openMenu();

      await user.click(menu.getByRole("menuitem", { name: "Return to my account" }));

      expect(onSignOut).toHaveBeenCalled();
    });

    it("does not call it a logout", async () => {
      // Nothing here signs anybody out: it drops the switch token, and the
      // upstream names the admin again on the next request.
      renderNav(AuthMode.proxy, vi.fn(), true);
      const { menu } = await openMenu();
      expect(
        menu.queryByRole("menuitem", { name: "Logout" }),
      ).not.toBeInTheDocument();
    });
  });
});

describe("export", () => {
  it("reveals the format picker", async () => {
    renderNav();
    const { user, menu } = await openMenu();
    await user.click(menu.getByRole("menuitem", { name: /Export Library/ }));

    expect(screen.getByRole("button", { name: "csv" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "txt" })).toBeInTheDocument();
  });

  it("exports in the chosen format", async () => {
    api.on("/api/books/export", {
      body: "txt",
      headers: { "content-type": "text/plain" },
    });
    renderNav();

    const { user, menu } = await openMenu();
    await user.click(menu.getByRole("menuitem", { name: /Export Library/ }));
    await user.click(screen.getByRole("button", { name: "txt" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/export")?.url).toContain("format=txt"),
    );
  });
});
