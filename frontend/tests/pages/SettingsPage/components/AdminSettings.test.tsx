/**
 * Tests for src/pages/SettingsPage/components/AdminSettings.tsx.
 *
 * Four routes read and write the same admin record, and the four states around
 * it used to be written out at each of them. One of the four is easy to get
 * subtly wrong and is the reason this component exists: **a 403 is a legitimate
 * answer, not a failure.** The settings endpoint is admin only, every member can
 * reach these screens, and rendering an error page at somebody who simply is not
 * an admin is the wrong sentence.
 *
 * Tested directly rather than only through the four pages, because a page test
 * proves the wiring on that page and this proves the rule.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SettingsOut } from "../../../../src/api/generated/model";
import AdminSettings from "../../../../src/pages/SettingsPage/components/AdminSettings";
import type { UseSettingsResult } from "../../../../src/pages/SettingsPage/hooks";
import { renderLocalised } from "../../../utils";

const SETTINGS = {
  google_books_enabled: false,
  google_books_api_key_preview: "",
  has_google_books_api_key: false,
  goodreads_lookup_enabled: false,
  default_locale: "en",
} as unknown as SettingsOut;

function state(patch: Partial<UseSettingsResult> = {}): UseSettingsResult {
  return {
    settings: undefined,
    isLoading: false,
    error: null,
    isForbidden: false,
    save: vi.fn(),
    isSaving: false,
    saveError: null,
    hasSaved: false,
    ...patch,
  };
}

function render(patch: Partial<UseSettingsResult> = {}) {
  renderLocalised(
    <AdminSettings state={state(patch)}>
      {(settings) => <p>default is {settings.default_locale}</p>}
    </AdminSettings>,
  );
}

describe("AdminSettings", () => {
  it("says a member is not an admin rather than showing an error", () => {
    render({ isForbidden: true, error: new Error("Admins only") });

    expect(
      screen.getByText("Only an admin can change these."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports a real failure as one", () => {
    // The distinction the whole component is for: 403 above, anything else here.
    render({ error: new Error("boom") });

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByText("Only an admin can change these."),
    ).not.toBeInTheDocument();
  });

  it("waits rather than claiming the record is missing", () => {
    render({ isLoading: true });

    // The spinner names itself with `aria-label`, not with text.
    expect(
      screen.getByRole("status", { name: "Loading..." }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/default is/)).not.toBeInTheDocument();
  });

  it("hands the record to its children only once it has one", () => {
    // A function of the record rather than a node, so no caller ever holds a
    // possibly undefined `settings` and there is nothing to narrow.
    render({ settings: SETTINGS });

    expect(screen.getByText("default is en")).toBeInTheDocument();
  });

  it("confirms a save", () => {
    render({ settings: SETTINGS, hasSaved: true });

    expect(screen.getByRole("status")).toHaveTextContent("Settings saved.");
  });

  it("says nothing about a save that failed and succeeded", () => {
    // React Query leaves `isSuccess` true from the previous save while the
    // next one is failing, so a banner keyed on it alone would report both.
    render({ settings: SETTINGS, hasSaved: true, saveError: new Error("no") });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
