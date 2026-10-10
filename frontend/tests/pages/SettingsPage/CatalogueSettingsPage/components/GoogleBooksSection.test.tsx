/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/GoogleBooksSection.tsx.
 *
 * The section rendered alone, with `onSave` as a spy, so what reaches the
 * server is read off the patch rather than off a mocked request. The page test
 * drives the same field through the API; this file pins the write only
 * contract at the component: the stored key is never in the box, a blank box
 * is never sent as a key, and a key the deployment supplies offers nothing to
 * edit or unmask.
 */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  type SettingsOut,
  type SettingsUpdate,
} from "../../../../../src/api/generated/model";
import GoogleBooksSection from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/GoogleBooksSection";
import { renderLocalised } from "../../../../utils";

function makeSettings(overrides: Partial<SettingsOut> = {}): SettingsOut {
  return {
    google_books_enabled: false,
    google_books_api_key_preview: "",
    has_google_books_api_key: false,
    goodreads_lookup_enabled: true,
    default_locale: Locale.en,
    ...overrides,
  };
}

function renderSection(
  settings: Partial<SettingsOut> = {},
  { isSaving = false }: { isSaving?: boolean } = {},
) {
  const onSave = vi.fn<(patch: SettingsUpdate) => void>();
  renderLocalised(
    <GoogleBooksSection
      settings={makeSettings(settings)}
      isSaving={isSaving}
      onSave={onSave}
    />,
  );
  return { onSave };
}

const STORED = {
  has_google_books_api_key: true,
  google_books_api_key_preview: "AIza...9f2c",
};

describe("GoogleBooksSection", () => {
  it("describes a stored key by its preview and leaves the box empty", () => {
    renderSection(STORED);
    expect(
      screen.getByText("A key is stored (AIza...9f2c)."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("API key")).toHaveValue("");
  });

  it("sends the typed key trimmed and then empties the box", async () => {
    const { onSave } = renderSection();
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "  typed-key  " },
    });
    await userEvent.setup().click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledExactlyOnceWith({
      google_books_api_key: "typed-key",
    });
    expect(screen.getByLabelText("API key")).toHaveValue("");
  });

  it("will not send a box holding only spaces", () => {
    // Trimmed it is the empty string, which the server reads as "clear the
    // key": a stray space must not wipe the stored one.
    renderSection(STORED);
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "   " },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("clears with an empty string, not an absent field", async () => {
    const { onSave } = renderSection(STORED);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Remove stored key" }));
    expect(onSave).toHaveBeenCalledExactlyOnceWith({
      google_books_api_key: "",
    });
  });

  it("reveals only what was typed, under the shared Show label", async () => {
    const user = userEvent.setup();
    renderSection(STORED);
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "typed-key" },
    });
    await user.click(screen.getByRole("button", { name: "Show" }));

    const box = screen.getByLabelText("API key");
    expect(box).toHaveAttribute("type", "text");
    expect(box).toHaveValue("typed-key");
  });

  it("holds both buttons while a save is in flight", () => {
    renderSection(STORED, { isSaving: true });
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Remove stored key" }),
    ).toBeDisabled();
  });

  describe("a key the deployment supplies", () => {
    const FROM_ENV = { ...STORED, google_books_api_key_from_env: true };

    it("offers nothing to type, unmask, save or remove", () => {
      renderSection(FROM_ENV);
      expect(screen.getByLabelText("API key")).toBeDisabled();
      expect(
        screen.queryByRole("button", { name: "Show" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Save" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Remove stored key" }),
      ).not.toBeInTheDocument();
    });

    it("still says what is stored, and where it comes from", () => {
      renderSection(FROM_ENV);
      expect(
        screen.getByText("A key is stored (AIza...9f2c)."),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/supplied by the server's configuration/),
      ).toBeInTheDocument();
    });
  });
});
