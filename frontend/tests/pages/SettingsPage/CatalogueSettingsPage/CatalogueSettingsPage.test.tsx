/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/CatalogueSettingsPage.tsx.
 *
 * Where a book's details come from. Everything on this route is admin only,
 * which makes it the screen that pins the shared gate: **a 403 is a legitimate
 * answer here, not a failure**, and it is said in a sentence rather than
 * rendered as an error page.
 *
 * The rest is the Google Books key, which is a write only field. The server
 * never sends a stored key back, so what is asserted is that the box stays
 * empty, that only what was typed here can be unmasked, and that clearing sends
 * an empty string rather than omitting the field, which would mean "leave it
 * alone".
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import CatalogueSettingsPage from "../../../../src/pages/SettingsPage/CatalogueSettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";

let api: MockApi;

function render() {
  return renderWithProviders(<CatalogueSettingsPage />);
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

describe("CatalogueSettingsPage", () => {
  describe("as a member rather than an admin", () => {
    beforeEach(() => {
      api.on(
        /\/api\/settings$/,
        { status: 403, body: { detail: "Admins only" } },
        "GET",
      );
    });

    it("says so plainly instead of showing an error", async () => {
      render();
      expect(
        await screen.findByText("Only an admin can change these."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("shows no controls it would refuse", async () => {
      render();
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
      render();

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
      render();
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
      render();

      expect(
        await screen.findByText("A key is stored (AIza...9f2c)."),
      ).toBeInTheDocument();
      // The box is for typing a new key into, never for displaying the old one.
      expect(await screen.findByLabelText("API key")).toHaveValue("");
    });

    it("saves a typed key", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      render();
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
      render();
      expect(
        await screen.findByRole("button", { name: "Save" }),
      ).toBeDisabled();
    });

    it("empties the box after saving, so the key is not left on screen", async () => {
      api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
      render();
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
      render();
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
      render();

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
      render();

      await userEvent
        .setup()
        .click(await screen.findByLabelText("Show Goodreads lookup links"));

      await waitFor(() =>
        expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
          goodreads_lookup_enabled: true,
        }),
      );
    });
  });

  it("confirms a successful save", async () => {
    api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
    render();

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
    render();

    await userEvent
      .setup()
      .click(await screen.findByLabelText("Enable extra book details"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
  });
});

describe("CatalogueSettingsPage API key handling", () => {
  it("masks the typed key by default", async () => {
    render();
    expect(await screen.findByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("reveals what was typed on request", async () => {
    // Only ever the value the admin just entered: the server never returns a
    // stored key, so there is nothing else here to reveal.
    render();
    const user = userEvent.setup();
    fireEvent.change(await screen.findByLabelText("API key"), {
      target: { value: "typed-key" },
    });

    await user.click(screen.getByRole("button", { name: "Show" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "text");
  });

  it("hides it again", async () => {
    render();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show" }));

    await user.click(screen.getByRole("button", { name: "Hide" }));

    expect(screen.getByLabelText("API key")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("offers the explanation next to the field", async () => {
    render();

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
      render();

      expect(await screen.findByLabelText("API key")).toBeDisabled();
    });

    it("offers no way to unmask it", async () => {
      // There is nothing to reveal: the field is empty and the real key is
      // managed outside the app.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      render();

      await screen.findByLabelText("API key");
      expect(
        screen.queryByRole("button", { name: "Show" }),
      ).not.toBeInTheDocument();
    });

    it("explains where it comes from", async () => {
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      render();

      expect(
        await screen.findByText(/supplied by the server's configuration/),
      ).toBeInTheDocument();
    });

    it("renders no save or remove buttons at all", async () => {
      // Not merely hidden: there is nothing here to save, and a disabled
      // control that cannot ever become enabled is just clutter.
      api.on(/\/api\/settings$/, { body: FROM_ENV });
      render();

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
      render();

      expect(
        await screen.findByLabelText("Enable extra book details"),
      ).toBeEnabled();
    });
  });
});
