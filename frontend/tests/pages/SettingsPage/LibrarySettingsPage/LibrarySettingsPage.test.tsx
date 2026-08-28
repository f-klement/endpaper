/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/LibrarySettingsPage.tsx.
 *
 * The one settings route that is **not** admin gated, and that is the property
 * worth pinning rather than the layout. An import writes the importing member's
 * own reading statuses and nobody else's, the cover backfill only touches books
 * the caller can see, and defining a field is additive. All three were once
 * inside an admin block, where a member could not reach them although the
 * endpoints had always allowed it.
 *
 * Only the field delete is admin only, so the settings record is read for that
 * one fact and a 403 changes nothing else on the screen.
 */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import LibrarySettingsPage from "../../../../src/pages/SettingsPage/LibrarySettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";

let api: MockApi;

function render() {
  return renderWithProviders(<LibrarySettingsPage />);
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
  api.on("/api/books/custom-fields", { body: [] });
});

describe("LibrarySettingsPage", () => {
  it("draws all three cards", async () => {
    render();

    expect(
      await screen.findByRole("heading", { name: "Bring a library across" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Covers" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Custom fields" }),
    ).toBeInTheDocument();
  });

  it("is open to a member who is not an admin", async () => {
    // The endpoints have always allowed this. Sitting inside the admin block
    // meant a member could not import their own reading history at all.
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    render();

    expect(
      await screen.findByRole("heading", { name: "Bring a library across" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Only an admin can change these."),
    ).not.toBeInTheDocument();
  });

  it("names the services a library can come from", async () => {
    // The import stopped being Goodreads-only. Somebody arriving from
    // LibraryThing or StoryGraph needs to see that this is for them too.
    render();
    expect(
      await screen.findByText(/Goodreads, LibraryThing, StoryGraph/),
    ).toBeInTheDocument();
  });

  it("says the columns are shown before anything is saved", async () => {
    render();
    expect(
      await screen.findByText(/shown before anything is saved/),
    ).toBeInTheDocument();
  });
});
