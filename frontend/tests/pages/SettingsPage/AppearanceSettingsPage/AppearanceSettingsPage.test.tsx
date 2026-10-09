/**
 * Tests for src/pages/SettingsPage/AppearanceSettingsPage/AppearanceSettingsPage.tsx.
 *
 * Three settings that read as one screen: what the app looks like, and what
 * language it speaks. The two language ones are not the pair their names
 * suggest, and both halves of that are asserted here. **Language is per person
 * and per device**, so it sends nothing to the server and works for a member
 * who can change nothing else. **Default language is the interface language for
 * a visitor who has not chosen one**, so it is saved to the server and is admin
 * only.
 *
 * The palette and the wallpaper are a link rather than controls. What is
 * asserted about the link is the summary it carries: it names the choice, not
 * this visit's pattern, so somebody who picked Surprise me reads "Surprise me"
 * rather than whichever tile the dice chose.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale } from "../../../../src/api/generated/model";
import AppearanceSettingsPage from "../../../../src/pages/SettingsPage/AppearanceSettingsPage";
import { WALLPAPER_OFF, type Appearance } from "../../../../src/theme";
import {
  LIGHT_APPEARANCE,
  mockApi,
  renderWithProviders,
  type MockApi,
} from "../../../utils";

let api: MockApi;

/** The appearance is a parameter: two tests are about what the summary names. */
function render(appearance?: Appearance) {
  return renderWithProviders(<AppearanceSettingsPage />, { appearance });
}

const SETTINGS = {
  google_books_enabled: false,
  google_books_api_key_preview: "",
  has_google_books_api_key: false,
  goodreads_lookup_enabled: false,
  default_locale: "en",
};

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
  api.on("/api/settings/features", {
    body: {
      google_books_enabled: false,
      goodreads_lookup_enabled: false,
      default_locale: "en",
    },
  });
  api.on(/\/api\/settings$/, { body: SETTINGS });
});

describe("AppearanceSettingsPage", () => {
  describe("language", () => {
    it("is offered before anything the server has to authorise", async () => {
      // Rendered above the admin section on purpose: it is per person and per
      // device, so it works for a member who can change nothing else.
      api.on(
        /\/api\/settings$/,
        { status: 403, body: { detail: "Admins only" } },
        "GET",
      );
      render();

      expect(
        await screen.findByRole("button", { name: "German" }),
      ).toBeInTheDocument();
    });

    it("switches the whole page's language", async () => {
      render();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));

      expect(
        await screen.findByRole("heading", { name: /Sprache/ }),
      ).toBeInTheDocument();
    });

    it("remembers the choice", async () => {
      render();
      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));
      expect(localStorage.getItem("locale")).toBe(Locale.de);
    });

    it("sends nothing to the server", async () => {
      render();
      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));
      expect(api.lastCall(/\/api\/settings$/, "PUT")).toBeUndefined();
    });
  });

  describe("appearance", () => {
    it("names what is set without offering the controls", async () => {
      // The controls moved to their own route, because the only honest preview
      // of a wallpaper is the page. What stays here is the summary.
      render();
      const link = await screen.findByRole("link", {
        name: /Endpaper, Light, Surprise me/,
      });

      expect(link).toHaveAttribute("href", "/settings/appearance/theme");
      expect(
        screen.queryByRole("button", { name: "Dark" }),
      ).not.toBeInTheDocument();
    });

    it("does not print a wallpaper this build no longer has as though it were pinned", async () => {
      // `patternFor` degrades an unknown id to a random pattern, so asking it
      // for a name here would name whichever tile the dice chose. Membership in
      // `PATTERNS` is the test, and both ways of ending up with a different
      // wallpaper every visit are named as such.
      render({ ...LIGHT_APPEARANCE, wallpaper: "hollyhock" });

      expect(
        await screen.findByRole("link", {
          name: /Endpaper, Light, Surprise me/,
        }),
      ).toBeInTheDocument();
    });

    it("names a wallpaper that is turned off", async () => {
      render({ ...LIGHT_APPEARANCE, wallpaper: WALLPAPER_OFF });

      expect(
        await screen.findByRole("link", { name: /Endpaper, Light, None/ }),
      ).toBeInTheDocument();
    });

    it("says nothing about the wallpaper while it is on", async () => {
      render();
      // Waits for the summary rather than asserting on it: the negative below
      // would pass on an empty page.
      await screen.findByRole("link", { name: /Endpaper, Light/ });

      expect(screen.queryByText(/wallpaper is off/)).not.toBeInTheDocument();
    });

    it("says why the wallpaper is off when the system asks for contrast", async () => {
      // Otherwise decoration vanishes with no explanation, which reads as a
      // fault in this app rather than as the preference being honoured.
      vi.stubGlobal(
        "matchMedia",
        vi.fn((query: string) => ({
          matches: query.includes("prefers-contrast"),
          addEventListener: () => {},
          removeEventListener: () => {},
        })),
      );
      render();

      expect(await screen.findByText(/wallpaper is off/)).toBeInTheDocument();
      vi.unstubAllGlobals();
    });
  });

  describe("the default language for new visitors", () => {
    it("is saved to the server, unlike the personal one", async () => {
      api.on(
        /\/api\/settings$/,
        { body: { ...SETTINGS, default_locale: "de" } },
        "PUT",
      );
      render();

      const group = await screen.findByRole("group", {
        name: "Default language for new visitors",
      });
      await userEvent
        .setup()
        .click(within(group).getByRole("button", { name: "German" }));

      await waitFor(() =>
        expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
          default_locale: "de",
        }),
      );
    });
  });
});
