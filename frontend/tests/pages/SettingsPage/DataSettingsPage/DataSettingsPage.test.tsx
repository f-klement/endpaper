/**
 * Tests for src/pages/SettingsPage/DataSettingsPage/DataSettingsPage.tsx.
 *
 * The archive, and the accounts an admin uses to see the library the way an
 * ordinary member does. What matters most here is the request that is **not**
 * made: the test accounts endpoint is admin only, so a member who cannot use it
 * must never be asked, or every visit is a 403 for everybody.
 *
 * A switch is a sign in on another account, so it ends where a login ends: the
 * handler the login form uses, and away from a screen the new account is not an
 * admin of.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthMode } from "../../../../src/api/generated/model";
import DataSettingsPage from "../../../../src/pages/SettingsPage/DataSettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";

let api: MockApi;

function render(
  props: Partial<React.ComponentProps<typeof DataSettingsPage>> = {},
) {
  return renderWithProviders(
    <DataSettingsPage mode={AuthMode.local} onSignIn={() => {}} {...props} />,
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
  // Every test that reaches the admin block asks for these, and an
  // unstubbed request throws.
  api.on("/api/users/test-accounts", { body: [] });
});

describe("DataSettingsPage", () => {
  describe("test accounts", () => {
    const TESTER = {
      id: 7,
      username: "tester",
      is_admin: false,
      created_at: "2026-01-01T00:00:00",
    };

    it("lists them for an admin", async () => {
      api.on("/api/users/test-accounts", { body: [TESTER] });
      render();

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
      render();

      await screen.findByText("Only an admin can change these.");
      expect(api.lastCall("/api/users/test-accounts")).toBeUndefined();
    });

    it("draws no card a member would be refused", async () => {
      // **This route's gate is the weakest of the six and this is what holds
      // it.** On the other admin screens every card consumes `settings`, so a
      // card moved out of `AdminSettings` and made a sibling does not compile.
      // Neither `BackupSection` nor `TestAccounts` takes that prop, so here the
      // same mistake typechecks and passes every other test on the file: a
      // member refused by `GET /api/settings` is then shown the sentence *and*,
      // above it, Download a backup and Restore. Both endpoints are
      // `require_admin`, so it is an offer the API refuses rather than a leak,
      // and an offer the API refuses is still a defect.
      api.on(
        /\/api\/settings$/,
        { status: 403, body: { detail: "Admins only" } },
        "GET",
      );
      render();

      await screen.findByText("Only an admin can change these.");
      expect(
        screen.queryByRole("heading", { name: "Backup" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "Test accounts" }),
      ).not.toBeInTheDocument();
    });

    it("creates one and asks for the list again", async () => {
      api.on("/api/users/test-accounts", { body: [] });
      render();
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
      render({ onSignIn });
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
      render({ onSignIn });
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
