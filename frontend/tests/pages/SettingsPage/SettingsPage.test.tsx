/** Tests for src/pages/SettingsPage/SettingsPage.tsx. */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthMode, Locale } from "../../../src/api/generated/model";
import SettingsPage from "../../../src/pages/SettingsPage";
import { WALLPAPER_OFF, type Appearance } from "../../../src/theme";
import {
  LIGHT_APPEARANCE,
  mockApi,
  renderWithProviders,
  type MockApi,
} from "../../utils";

let api: MockApi;

/**
 * The page with its two shell props supplied.
 *
 * `mode` decides one sentence in the test accounts section, and `onSignIn` is
 * where a switch lands. Neither is what most of these tests are about, so they
 * are defaulted here rather than repeated thirty times.
 */
function renderSettings(
  props: Partial<React.ComponentProps<typeof SettingsPage>> = {},
  appearance?: Appearance,
) {
  return renderWithProviders(
    <SettingsPage mode={AuthMode.local} onSignIn={() => {}} {...props} />,
    { appearance },
  );
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
  // The admin block asks for these. Stubbed here rather than per test: an
  // unstubbed request throws, and every test that reaches the admin block
  // would fail for a reason that has nothing to do with what it asserts.
  api.on("/api/users/test-accounts", { body: [] });
});

describe("SettingsPage", () => {
  describe("language", () => {
    it("is offered before anything the server has to authorise", async () => {
      // Rendered above the admin section on purpose: it is per person and per
      // device, so it works for a member who can change nothing else.
      api.on(
        /\/api\/settings$/,
        { status: 403, body: { detail: "Admins only" } },
        "GET",
      );
      renderSettings();

      expect(
        await screen.findByRole("button", { name: "German" }),
      ).toBeInTheDocument();
    });

    it("switches the whole page's language", async () => {
      renderSettings();

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));

      expect(
        await screen.findByRole("heading", { name: /Sprache/ }),
      ).toBeInTheDocument();
    });

    it("remembers the choice", async () => {
      renderSettings();
      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));
      expect(localStorage.getItem("locale")).toBe(Locale.de);
    });

    it("sends nothing to the server", async () => {
      renderSettings();
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
      renderSettings();
      const link = await screen.findByRole("link", {
        name: /Endpaper, Light, Surprise me/,
      });

      expect(link).toHaveAttribute("href", "/settings/appearance");
      expect(screen.queryByRole("button", { name: "Dark" })).not.toBeInTheDocument();
    });

    it("does not print a wallpaper this build no longer has as though it were pinned", async () => {
      // `patternFor` degrades an unknown id to a random pattern, so asking it
      // for a name here would name whichever tile the dice chose. Membership in
      // `PATTERNS` is the test, and both ways of ending up with a different
      // wallpaper every visit are named as such.
      renderSettings({}, { ...LIGHT_APPEARANCE, wallpaper: "hollyhock" });

      expect(
        await screen.findByRole("link", { name: /Endpaper, Light, Surprise me/ }),
      ).toBeInTheDocument();
    });

    it("names a wallpaper that is turned off", async () => {
      renderSettings({}, { ...LIGHT_APPEARANCE, wallpaper: WALLPAPER_OFF });

      expect(
        await screen.findByRole("link", { name: /Endpaper, Light, None/ }),
      ).toBeInTheDocument();
    });

    it("says nothing about the wallpaper while it is on", async () => {
      renderSettings();
      await screen.findByRole("link", { name: /Endpaper/ });

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
      renderSettings();

      expect(await screen.findByText(/wallpaper is off/)).toBeInTheDocument();
      vi.unstubAllGlobals();
    });
  });

  describe("as a member rather than an admin", () => {
    beforeEach(() => {
      api.on(
        /\/api\/settings$/,
        { status: 403, body: { detail: "Admins only" } },
        "GET",
      );
    });

    it("says so plainly instead of showing an error", async () => {
      renderSettings();
      expect(
        await screen.findByText("Only an admin can change these."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("hides the admin sections", async () => {
      renderSettings();
      await screen.findByText("Only an admin can change these.");
      expect(screen.queryByText("Google Books")).not.toBeInTheDocument();
    });
  });

  describe("Google Books", () => {
    it("toggles the feature", async () => {
      api.on(
        /\/api\/settings$/,
        { body: { ...SETTINGS, google_books_enabled: true } },
        "PUT",
      );
      renderSettings();

      await userEvent
        .setup()
        .click(await screen.findByLabelText("Enable extra book details"));

      await waitFor(() =>
        expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
          google_books_enabled: true,
        }),
      );
    });

    it("says when no key is stored", async () => {
      renderSettings();
      expect(await screen.findByText("No key stored yet.")).toBeInTheDocument();
    });

    it("shows only a masked preview of a stored key", async () => {
      api.on(/\/api\/settings$/, {
        body: {
          ...SETTINGS,
          has_google_books_api_key: true,
          google_books_api_key_preview: "AIza...9f2c",
        },
      });
      renderSettings();

      expect(
        await screen.findByText("A key is stored (AIza...9f2c)."),
      ).toBeInTheDocument();
      // The box is for typing a new key into, never for displaying the old one.
      expect(await screen.findByLabelText("API key")).toHaveValue("");
    });

    it("saves a typed key", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderSettings();
      const user = userEvent.setup();

      fireEvent.change(await screen.findByLabelText("API key"), { target: { value: "  secret-key  " } });
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
          google_books_api_key: "secret-key",
        }),
      );
    });

    it("will not save an empty box", async () => {
      // An empty string means "clear the key", which is the Remove button's
      // job. Saving nothing must not silently wipe the stored one.
      renderSettings();
      expect(
        await screen.findByRole("button", { name: "Save" }),
      ).toBeDisabled();
    });

    it("empties the box after saving, so the key is not left on screen", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderSettings();
      const user = userEvent.setup();

      fireEvent.change(await screen.findByLabelText("API key"), { target: { value: "secret-key" } });
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(screen.getByLabelText("API key")).toHaveValue(""),
      );
    });

    it("offers removal only when there is something to remove", async () => {
      renderSettings();
      await screen.findByText("No key stored yet.");
      expect(
        screen.queryByRole("button", { name: "Remove stored key" }),
      ).not.toBeInTheDocument();
    });

    it("clears the key with an empty string, not by omitting the field", async () => {
      api.on(/\/api\/settings$/, {
        body: {
          ...SETTINGS,
          has_google_books_api_key: true,
          google_books_api_key_preview: "x",
        },
      });
      renderSettings();

      await userEvent
        .setup()
        .click(
          await screen.findByRole("button", { name: "Remove stored key" }),
        );

      await waitFor(() =>
        expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
          google_books_api_key: "",
        }),
      );
    });
  });

  describe("Goodreads", () => {
    it("toggles the lookup links", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderSettings();

      await userEvent
        .setup()
        .click(await screen.findByLabelText("Show Goodreads lookup links"));

      await waitFor(() =>
        expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
          goodreads_lookup_enabled: true,
        }),
      );
    });

    it("names the services a library can come from", async () => {
      // The import stopped being Goodreads-only. Somebody arriving from
      // LibraryThing or StoryGraph needs to see that this is for them too.
      renderSettings();
      expect(
        await screen.findByText(/Goodreads, LibraryThing, StoryGraph/),
      ).toBeInTheDocument();
    });

    it("says the columns are shown before anything is saved", async () => {
      renderSettings();
      expect(
        await screen.findByText(/shown before anything is saved/),
      ).toBeInTheDocument();
    });
  });

  describe("the default language for new visitors", () => {
    it("is saved to the server, unlike the personal one", async () => {
      api.on(
        /\/api\/settings$/,
        { body: { ...SETTINGS, default_locale: "de" } },
        "PUT",
      );
      renderSettings();

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

  it("confirms a successful save", async () => {
    api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
    renderSettings();

    await userEvent
      .setup()
      .click(await screen.findByLabelText("Enable extra book details"));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Settings saved.",
    );
  });

  it("reports a failed save", async () => {
    api.on(
      /\/api\/settings$/,
      { status: 500, body: { detail: "Nope" } },
      "PUT",
    );
    renderSettings();

    await userEvent
      .setup()
      .click(await screen.findByLabelText("Enable extra book details"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

describe("SettingsPage API key handling", () => {
  it("masks the typed key by default", async () => {
    renderSettings();
    expect(await screen.findByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("reveals what was typed on request", async () => {
    // Only ever the value the admin just entered: the server never returns a
    // stored key, so there is nothing else here to reveal.
    renderSettings();
    const user = userEvent.setup();
    fireEvent.change(await screen.findByLabelText("API key"), { target: { value: "typed-key" } });

    await user.click(screen.getByRole("button", { name: "Show" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "text");
  });

  it("hides it again", async () => {
    renderSettings();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show" }));

    await user.click(screen.getByRole("button", { name: "Hide" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("offers the explanation next to the field", async () => {
    renderSettings();

    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "How do I get a key?" }),
      );

    expect(
      await screen.findByRole("dialog", { name: "Google Books lookup" }),
    ).toBeInTheDocument();
  });

  describe("when the deployment supplies the key", () => {
    const FROM_ENV = {
      ...SETTINGS,
      has_google_books_api_key: true,
      google_books_api_key_preview: "env...key",
      google_books_api_key_from_env: true,
    };

    it("disables the field", async () => {
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();

      expect(await screen.findByLabelText("API key")).toBeDisabled();
    });

    it("offers no way to unmask it", async () => {
      // There is nothing to reveal: the field is empty and the real key is
      // managed outside the app.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();

      await screen.findByLabelText("API key");
      expect(
        screen.queryByRole("button", { name: "Show" }),
      ).not.toBeInTheDocument();
    });

    it("explains where it comes from", async () => {
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();

      expect(
        await screen.findByText(/supplied by the server's configuration/),
      ).toBeInTheDocument();
    });

    it("renders no save or remove buttons at all", async () => {
      // Not merely hidden: there is nothing here to save, and a disabled
      // control that cannot ever become enabled is just clutter.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();

      await screen.findByLabelText("API key");
      expect(
        screen.queryByRole("button", { name: "Save" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Remove stored key" }),
      ).not.toBeInTheDocument();
    });

    it("still allows the feature toggle", async () => {
      // The key is fixed; whether the feature is on is still a local decision.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();

      expect(
        await screen.findByLabelText("Enable extra book details"),
      ).toBeEnabled();
    });
  });

  describe("test accounts", () => {
    const TESTER = {
      id: 7,
      username: "tester",
      is_admin: false,
      created_at: "2026-01-01T00:00:00",
    };

    it("lists them for an admin", async () => {
      api.on("/api/users/test-accounts", { body: [TESTER] });
      renderSettings();

      expect(await screen.findByText("tester")).toBeInTheDocument();
    });

    it("is not asked for at all by a member who cannot use it", async () => {
      // The endpoint is admin only, and every member reaches this page for the
      // language switch. Asking anyway would be a 403 on every visit.
      api.on(
        /\/api\/settings$/,
        { status: 403, body: { detail: "Admins only" } },
        "GET",
      );
      renderSettings();

      await screen.findByText("Only an admin can change these.");
      expect(api.lastCall("/api/users/test-accounts")).toBeUndefined();
    });

    it("creates one and asks for the list again", async () => {
      api.on("/api/users/test-accounts", { body: [] });
      renderSettings();
      const user = userEvent.setup();

      fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "tester" } });
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw12345678" } });
      api.on("/api/users/test-accounts", { status: 201, body: TESTER }, "POST");
      await user.click(
        screen.getByRole("button", { name: "Create test account" }),
      );

      await waitFor(() =>
        expect(
          api.lastCall("/api/users/test-accounts", "POST")?.body,
        ).toEqual({ username: "tester", password: "pw12345678" }),
      );
    });

    it("switches with the password the admin supplies", async () => {
      api.on("/api/users/test-accounts", { body: [TESTER] });
      api.on("/auth/switch", {
        body: { access_token: "switch-token", token_type: "bearer", user: TESTER },
      });
      const onSignIn = vi.fn();
      renderSettings({ onSignIn });
      const user = userEvent.setup();

      await user.click(
        await screen.findByRole("button", { name: "Switch to tester" }),
      );
      fireEvent.change(screen.getByLabelText("Password for tester"), { target: { value: "pw12345678" } });
      await user.click(screen.getByRole("button", { name: "Switch" }));

      await waitFor(() =>
        expect(onSignIn).toHaveBeenCalledWith(TESTER, "switch-token"),
      );
      expect(api.lastCall("/auth/switch", "POST")?.body).toEqual({
        username: "tester",
        password: "pw12345678",
      });
    });

    it("reports a refused switch rather than pretending it worked", async () => {
      api.on("/api/users/test-accounts", { body: [TESTER] });
      api.on("/auth/switch", {
        status: 401,
        body: { detail: "Incorrect password for that account" },
      });
      const onSignIn = vi.fn();
      renderSettings({ onSignIn });
      const user = userEvent.setup();

      await user.click(
        await screen.findByRole("button", { name: "Switch to tester" }),
      );
      fireEvent.change(screen.getByLabelText("Password for tester"), { target: { value: "wrong" } });
      await user.click(screen.getByRole("button", { name: "Switch" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Incorrect password for that account",
      );
      expect(onSignIn).not.toHaveBeenCalled();
    });
  });
});
