/** Tests for src/pages/SettingsPage/SettingsPage.tsx. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Locale } from "../../../src/api/generated/model";
import SettingsPage from "../../../src/pages/SettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

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
      renderWithProviders(<SettingsPage />);

      expect(
        await screen.findByRole("button", { name: "German" }),
      ).toBeInTheDocument();
    });

    it("switches the whole page's language", async () => {
      renderWithProviders(<SettingsPage />);

      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));

      expect(
        await screen.findByRole("heading", { name: /Sprache/ }),
      ).toBeInTheDocument();
    });

    it("remembers the choice", async () => {
      renderWithProviders(<SettingsPage />);
      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));
      expect(localStorage.getItem("locale")).toBe(Locale.de);
    });

    it("sends nothing to the server", async () => {
      renderWithProviders(<SettingsPage />);
      await userEvent
        .setup()
        .click(await screen.findByRole("button", { name: "German" }));
      expect(api.lastCall(/\/api\/settings$/, "PUT")).toBeUndefined();
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
      renderWithProviders(<SettingsPage />);
      expect(
        await screen.findByText("Only an admin can change these."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("hides the admin sections", async () => {
      renderWithProviders(<SettingsPage />);
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
      renderWithProviders(<SettingsPage />);

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
      renderWithProviders(<SettingsPage />);
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
      renderWithProviders(<SettingsPage />);

      expect(
        await screen.findByText("A key is stored (AIza...9f2c)."),
      ).toBeInTheDocument();
      // The box is for typing a new key into, never for displaying the old one.
      expect(await screen.findByLabelText("API key")).toHaveValue("");
    });

    it("saves a typed key", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderWithProviders(<SettingsPage />);
      const user = userEvent.setup();

      await user.type(
        await screen.findByLabelText("API key"),
        "  secret-key  ",
      );
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
      renderWithProviders(<SettingsPage />);
      expect(
        await screen.findByRole("button", { name: "Save" }),
      ).toBeDisabled();
    });

    it("empties the box after saving, so the key is not left on screen", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      renderWithProviders(<SettingsPage />);
      const user = userEvent.setup();

      await user.type(await screen.findByLabelText("API key"), "secret-key");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(screen.getByLabelText("API key")).toHaveValue(""),
      );
    });

    it("offers removal only when there is something to remove", async () => {
      renderWithProviders(<SettingsPage />);
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
      renderWithProviders(<SettingsPage />);

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
      renderWithProviders(<SettingsPage />);

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
      renderWithProviders(<SettingsPage />);
      expect(
        await screen.findByText(/Goodreads, LibraryThing, StoryGraph/),
      ).toBeInTheDocument();
    });

    it("says the columns are shown before anything is saved", async () => {
      renderWithProviders(<SettingsPage />);
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
      renderWithProviders(<SettingsPage />);

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
    renderWithProviders(<SettingsPage />);

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
    renderWithProviders(<SettingsPage />);

    await userEvent
      .setup()
      .click(await screen.findByLabelText("Enable extra book details"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

describe("SettingsPage API key handling", () => {
  it("masks the typed key by default", async () => {
    renderWithProviders(<SettingsPage />);
    expect(await screen.findByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("reveals what was typed on request", async () => {
    // Only ever the value the admin just entered: the server never returns a
    // stored key, so there is nothing else here to reveal.
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("API key"), "typed-key");

    await user.click(screen.getByRole("button", { name: "Show" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "text");
  });

  it("hides it again", async () => {
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show" }));

    await user.click(screen.getByRole("button", { name: "Hide" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("offers the explanation next to the field", async () => {
    renderWithProviders(<SettingsPage />);

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
      renderWithProviders(<SettingsPage />);

      expect(await screen.findByLabelText("API key")).toBeDisabled();
    });

    it("offers no way to unmask it", async () => {
      // There is nothing to reveal: the field is empty and the real key is
      // managed outside the app.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderWithProviders(<SettingsPage />);

      await screen.findByLabelText("API key");
      expect(
        screen.queryByRole("button", { name: "Show" }),
      ).not.toBeInTheDocument();
    });

    it("explains where it comes from", async () => {
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderWithProviders(<SettingsPage />);

      expect(
        await screen.findByText(/supplied by the server's configuration/),
      ).toBeInTheDocument();
    });

    it("renders no save or remove buttons at all", async () => {
      // Not merely hidden: there is nothing here to save, and a disabled
      // control that cannot ever become enabled is just clutter.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      renderWithProviders(<SettingsPage />);

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
      renderWithProviders(<SettingsPage />);

      expect(
        await screen.findByLabelText("Enable extra book details"),
      ).toBeEnabled();
    });
  });
});
