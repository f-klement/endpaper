/** Tests for src/pages/SettingsPage/SettingsPage.tsx. */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthMode, Locale } from "../../../src/api/generated/model";
import SettingsPage from "../../../src/pages/SettingsPage";
import { SETTINGS_SECTIONS } from "../../../src/pages/SettingsPage/hooks";
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

/**
 * Make sure a card is open, by its handle.
 *
 * A closed panel is `hidden`, which takes everything inside it out of the
 * accessibility tree, so a test that reaches for a control by role has to open
 * its card first, exactly as a reader does.
 *
 * **Idempotent on purpose.** A test about the Google Books key is not a test
 * about the defaults table, so it says what it needs rather than what today's
 * table happens to give it: moving a card from open to closed, or back, must
 * not break a test that has nothing to do with folding.
 */
async function openSection(title: string) {
  const handle = await screen.findByRole("button", { name: title });
  if (handle.getAttribute("aria-expanded") === "true") return;
  await userEvent.setup().click(handle);
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
  // The custom fields card asks for this one, and it is outside the admin
  // block, so every test on this page reaches it.
  api.on("/api/books/custom-fields", { body: [] });
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
      expect(
        screen.queryByRole("button", { name: "Dark" }),
      ).not.toBeInTheDocument();
    });

    it("does not print a wallpaper this build no longer has as though it were pinned", async () => {
      // `patternFor` degrades an unknown id to a random pattern, so asking it
      // for a name here would name whichever tile the dice chose. Membership in
      // `PATTERNS` is the test, and both ways of ending up with a different
      // wallpaper every visit are named as such.
      renderSettings({}, { ...LIGHT_APPEARANCE, wallpaper: "hollyhock" });

      expect(
        await screen.findByRole("link", {
          name: /Endpaper, Light, Surprise me/,
        }),
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
      // Named tightly: the About card links to Ko-fi, so /Endpaper/ alone now
      // matches two links.
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
      await openSection("Google Books");

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
      await openSection("Google Books");
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
      await openSection("Google Books");

      expect(
        await screen.findByText("A key is stored (AIza...9f2c)."),
      ).toBeInTheDocument();
      // The box is for typing a new key into, never for displaying the old one.
      expect(await screen.findByLabelText("API key")).toHaveValue("");
    });

    it("saves a typed key", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderSettings();
      await openSection("Google Books");
      const user = userEvent.setup();

      fireEvent.change(await screen.findByLabelText("API key"), {
        target: { value: "  secret-key  " },
      });
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
      await openSection("Google Books");
      expect(
        await screen.findByRole("button", { name: "Save" }),
      ).toBeDisabled();
    });

    it("empties the box after saving, so the key is not left on screen", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderSettings();
      await openSection("Google Books");
      const user = userEvent.setup();

      fireEvent.change(await screen.findByLabelText("API key"), {
        target: { value: "secret-key" },
      });
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(screen.getByLabelText("API key")).toHaveValue(""),
      );
    });

    it("offers removal only when there is something to remove", async () => {
      renderSettings();
      await openSection("Google Books");
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
      await openSection("Google Books");

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
    await openSection("Google Books");

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
    await openSection("Google Books");

    await userEvent
      .setup()
      .click(await screen.findByLabelText("Enable extra book details"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

describe("SettingsPage API key handling", () => {
  it("masks the typed key by default", async () => {
    renderSettings();
    await openSection("Google Books");
    expect(await screen.findByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("reveals what was typed on request", async () => {
    // Only ever the value the admin just entered: the server never returns a
    // stored key, so there is nothing else here to reveal.
    renderSettings();
    await openSection("Google Books");
    const user = userEvent.setup();
    fireEvent.change(await screen.findByLabelText("API key"), {
      target: { value: "typed-key" },
    });

    await user.click(screen.getByRole("button", { name: "Show" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "text");
  });

  it("hides it again", async () => {
    renderSettings();
    await openSection("Google Books");
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
    await openSection("Google Books");

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
      await openSection("Google Books");

      expect(await screen.findByLabelText("API key")).toBeDisabled();
    });

    it("offers no way to unmask it", async () => {
      // There is nothing to reveal: the field is empty and the real key is
      // managed outside the app.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();
      await openSection("Google Books");

      await screen.findByLabelText("API key");
      expect(
        screen.queryByRole("button", { name: "Show" }),
      ).not.toBeInTheDocument();
    });

    it("explains where it comes from", async () => {
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();
      await openSection("Google Books");

      expect(
        await screen.findByText(/supplied by the server's configuration/),
      ).toBeInTheDocument();
    });

    it("renders no save or remove buttons at all", async () => {
      // Not merely hidden: there is nothing here to save, and a disabled
      // control that cannot ever become enabled is just clutter.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderSettings();
      await openSection("Google Books");

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
      await openSection("Google Books");

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
      await openSection("Test accounts");

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
      await openSection("Test accounts");
      const user = userEvent.setup();

      fireEvent.change(await screen.findByLabelText("Username"), {
        target: { value: "tester" },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "pw12345678" },
      });
      api.on("/api/users/test-accounts", { status: 201, body: TESTER }, "POST");
      await user.click(
        screen.getByRole("button", { name: "Create test account" }),
      );

      await waitFor(() =>
        expect(api.lastCall("/api/users/test-accounts", "POST")?.body).toEqual({
          username: "tester",
          password: "pw12345678",
        }),
      );
    });

    it("switches with the password the admin supplies", async () => {
      api.on("/api/users/test-accounts", { body: [TESTER] });
      api.on("/auth/switch", {
        body: {
          access_token: "switch-token",
          token_type: "bearer",
          user: TESTER,
        },
      });
      const onSignIn = vi.fn();
      renderSettings({ onSignIn });
      await openSection("Test accounts");
      const user = userEvent.setup();

      await user.click(
        await screen.findByRole("button", { name: "Switch to tester" }),
      );
      fireEvent.change(screen.getByLabelText("Password for tester"), {
        target: { value: "pw12345678" },
      });
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
      await openSection("Test accounts");
      const user = userEvent.setup();

      await user.click(
        await screen.findByRole("button", { name: "Switch to tester" }),
      );
      fireEvent.change(screen.getByLabelText("Password for tester"), {
        target: { value: "wrong" },
      });
      await user.click(screen.getByRole("button", { name: "Switch" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Incorrect password for that account",
      );
      expect(onSignIn).not.toHaveBeenCalled();
    });
  });
});

/**
 * Every card on this page folds, and which ones arrive open is the design.
 *
 * The rule: open when the current setting is the whole of the card and reading
 * it is why you are here, closed when it starts a job or holds a form. The
 * table itself is asserted in hooks.test.ts; what is checked here is that the
 * page draws it, and that About is one open card among several rather than the
 * page's only expanded thing.
 */
describe("SettingsPage folds", () => {
  const OPEN = ["Language", "Appearance", "Google Books", "About Endpaper"];
  const CLOSED = [
    "Bring a library across",
    "Covers",
    "Overdue reminders",
    "Test accounts",
    "Backup",
  ];

  /** Every card, in draw order. Also the accessible name of its handle. */
  const HANDLES = [
    "Language",
    "Appearance",
    "Bring a library across",
    "Covers",
    "Google Books",
    "Goodreads",
    "Default language for new visitors",
    "Overdue reminders",
    "Test accounts",
    "Backup",
    "About Endpaper",
  ];

  it("opens the cards that answer a question", async () => {
    renderSettings();
    await screen.findByRole("button", { name: "Google Books" });

    for (const title of OPEN) {
      expect(screen.getByRole("button", { name: title })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    }
  });

  it("closes the cards that start a job", async () => {
    renderSettings();
    await screen.findByRole("button", { name: "Backup" });

    for (const title of CLOSED) {
      expect(screen.getByRole("button", { name: title })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    }
  });

  it("keeps a closed card's controls out of reach until it is opened", async () => {
    renderSettings();
    await screen.findByRole("button", { name: "Backup" });
    expect(
      screen.queryByRole("button", { name: "Download a backup" }),
    ).not.toBeInTheDocument();

    await openSection("Backup");

    expect(
      screen.getByRole("button", { name: "Download a backup" }),
    ).toBeInTheDocument();
  });

  it("remembers a fold on the next visit", async () => {
    // Clicked directly rather than through `openSection`, which only ever
    // opens: this test is about closing a card the table opens.
    const first = renderSettings();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Language" }));
    first.unmount();

    renderSettings();

    expect(
      await screen.findByRole("button", { name: "Language" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("draws the cards in the order its own id list gives", async () => {
    // The list in hooks.ts claims a draw order that the JSX actually decides,
    // so it is asserted rather than trusted. This is also what pins About last.
    renderSettings();
    await screen.findByRole("button", { name: "Google Books" });

    const ids = [
      ...document.querySelectorAll("h2 > button[aria-expanded]"),
    ].map((handle) => handle.id);

    expect(ids).toEqual(
      SETTINGS_SECTIONS.map((section) => `${section}-handle`),
    );
  });

  it("gives every card a handle no other control answers to", async () => {
    // Two controls sharing a name is how a reader following a screen reader
    // ends up on the wrong one. Measured on the rendered page, including the
    // controls inside closed panels, which is where a collision would hide.
    renderSettings();
    await screen.findByRole("button", { name: "Backup" });

    for (const title of HANDLES) {
      expect(
        screen.getAllByRole("button", { name: title, hidden: true }),
      ).toHaveLength(1);
    }
  });

  it("leaves About one open card among six, not the page's only one", async () => {
    // A settings page whose one expanded card asks for money is a donation
    // prompt wearing a settings page.
    renderSettings();
    // The admin cards, four of the six, arrive with the settings request.
    await screen.findByRole("button", { name: "Google Books" });

    const expanded = screen
      .getAllByRole("button", { expanded: true })
      .map((handle) => handle.textContent);

    expect(expanded).toHaveLength(6);
    expect(expanded).toContain("About Endpaper");
  });
});

describe("SettingsPage About card", () => {
  it("is there for a member who is not an admin", async () => {
    // Outside the admin block: it says what this app is, which is not an
    // admin's business alone.
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    renderSettings();

    expect(
      await screen.findByRole("img", { name: "Support Endpaper on Ko-fi" }),
    ).toBeInTheDocument();
  });
});
