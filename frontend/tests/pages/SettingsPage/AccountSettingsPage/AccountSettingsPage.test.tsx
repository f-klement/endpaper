/**
 * Tests for src/pages/SettingsPage/AccountSettingsPage/AccountSettingsPage.tsx.
 *
 * One field for the member, and the whole list for an admin. What is worth
 * pinning here is the boundary rather than the form: **a member is shown no
 * member list at all, not a refusal**, because announcing that other people's
 * addresses exist somewhere is the disclosure this feature was scoped to avoid.
 *
 * And the 409, which is the one refusal this screen explains rather than
 * reports: an admin has every right and still cannot write an address the
 * directory owns, so an error banner would send them looking for a permission
 * that does not exist.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import AccountSettingsPage from "../../../../src/pages/SettingsPage/AccountSettingsPage";
import { makeUser } from "../../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";

let api: MockApi;

const MINE = {
  id: 1,
  username: "kim",
  email: null as string | null,
  editable: true,
};

function render(isAdmin = false) {
  return renderWithProviders(
    <AccountSettingsPage currentUser={makeUser({ is_admin: isAdmin })} />,
  );
}

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
  api.on("/api/users/me/email", { body: MINE });
  // Stubbed as a 403 so that a member reaching it would meet the real answer.
  // Nothing should reach it: see the request count assertion below.
  api.on("/api/users/emails", { status: 403, body: { detail: "Admins only" } });
});

describe("AccountSettingsPage", () => {
  it("offers the caller their own address", async () => {
    render();

    expect(await screen.findByLabelText("Your address")).toHaveValue("");
  });

  it("shows a member no member list and no refusal about one", async () => {
    render();
    await screen.findByLabelText("Your address");

    expect(screen.queryByText("Member addresses")).not.toBeInTheDocument();
    expect(screen.queryByText(/Only an admin/)).not.toBeInTheDocument();
  });

  it("does not ask an admin endpoint on a member's behalf", async () => {
    // It did, and the 403 was thrown away: a guaranteed refusal per page load,
    // in the server log and the browser console, on the one settings screen
    // every member is meant to use. The prop gates the request; `require_admin`
    // is still what allows it.
    render();
    await screen.findByLabelText("Your address");

    expect(
      api.calls.filter((call) => call.url.includes("/api/users/emails")),
    ).toEqual([]);
  });

  it("sends what was typed", async () => {
    render();
    const field = await screen.findByLabelText("Your address");

    await userEvent.type(field, "kim@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(api.lastCall("/api/users/me/email", "PUT")?.body).toEqual({
        email: "kim@example.org",
      });
    });
  });

  it("sends null for an emptied field, which is what clears it", async () => {
    api.on("/api/users/me/email", {
      body: { ...MINE, email: "kim@example.org" },
    });
    render();
    const field = await screen.findByLabelText("Your address");
    await waitFor(() => expect(field).toHaveValue("kim@example.org"));

    await userEvent.clear(field);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(api.lastCall("/api/users/me/email", "PUT")?.body).toEqual({
        email: null,
      });
    });
  });

  it("cannot save a field nobody has changed", async () => {
    api.on("/api/users/me/email", {
      body: { ...MINE, email: "kim@example.org" },
    });
    render();
    await waitFor(() =>
      expect(screen.getByLabelText("Your address")).toHaveValue(
        "kim@example.org",
      ),
    );

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("draws a directory owned address as text with where to change it", async () => {
    api.on("/api/users/me/email", {
      body: { ...MINE, email: "kim@directory.example", editable: false },
    });
    render();

    expect(
      await screen.findByText("kim@directory.example"),
    ).toBeInTheDocument();
    expect(screen.getByText(/comes from your directory/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your address")).not.toBeInTheDocument();
  });

  it("explains a 409 rather than reporting it as an error", async () => {
    api.on(
      "/api/users/me/email",
      {
        status: 409,
        body: { detail: "This address comes from the directory." },
      },
      "PUT",
    );
    render();
    const field = await screen.findByLabelText("Your address");

    await userEvent.type(field, "kim@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(/the directory's to set/),
    ).toBeInTheDocument();
  });

  describe("as an admin", () => {
    beforeEach(() => {
      api.on("/api/users/emails", {
        body: [
          MINE,
          { id: 2, username: "sam", email: null, editable: true },
          {
            id: 3,
            username: "alex",
            email: "alex@directory.example",
            editable: false,
          },
        ],
      });
    });

    it("lists every member beside their address", async () => {
      render(true);

      expect(await screen.findByText("Member addresses")).toBeInTheDocument();
      expect(screen.getByLabelText("sam")).toHaveValue("");
      expect(screen.getByText("alex@directory.example")).toBeInTheDocument();
    });

    it("writes one member's address to that member's route", async () => {
      render(true);
      const field = await screen.findByLabelText("sam");

      await userEvent.type(field, "sam@example.org");
      const rows = screen.getAllByRole("button", { name: "Save" });
      await userEvent.click(rows[rows.length - 1]!);

      await waitFor(() => {
        expect(api.lastCall("/api/users/2/email", "PUT")?.body).toEqual({
          email: "sam@example.org",
        });
      });
    });

    it("offers no field at all for a directory owned row", async () => {
      render(true);
      await screen.findByText("Member addresses");

      expect(screen.queryByLabelText("alex")).not.toBeInTheDocument();
    });
  });
});
