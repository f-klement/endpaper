/**
 * Tests for src/pages/SettingsPage/LendingSettingsPage/LendingSettingsPage.tsx.
 *
 * What each card does is covered by its own test. What is only visible here is
 * that the two arrive together: the digest decides what is sent and when, the
 * senders decide where it goes, and a household that could reach one without
 * the other could turn the reminder on and never find out that nothing is
 * configured to carry it.
 */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import LendingSettingsPage from "../../../../src/pages/SettingsPage/LendingSettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";

let api: MockApi;

function render() {
  return renderWithProviders(<LendingSettingsPage />);
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

describe("LendingSettingsPage", () => {
  it("puts the reminder and the senders that carry it on one screen", async () => {
    render();

    expect(
      await screen.findByRole("heading", { name: "Overdue reminders" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Mail and chat reminders" }),
    ).toBeInTheDocument();
  });

  it("says plainly that it is admin only rather than showing an error", async () => {
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    render();

    expect(
      await screen.findByText("Only an admin can change these."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
