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

import { screen, waitFor, within } from "@testing-library/react";
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
  from_directory: false,
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
    expect(screen.getByText(/comes from the directory/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your address")).not.toBeInTheDocument();
  });

  // #103. An empty editable box left "nobody set one" and "it did not load"
  // looking the same, and the member who was never asked for an address is the
  // one who most needs telling that the field is theirs.
  it("says plainly when no address is set", async () => {
    api.on("/api/users/me/email", { body: MINE });
    render();

    expect(await screen.findByText("None set.")).toBeInTheDocument();
  });

  it("says nothing about none when an address is set", async () => {
    api.on("/api/users/me/email", {
      body: { ...MINE, email: "kim@example.org" },
    });
    render();

    await screen.findByDisplayValue("kim@example.org");
    expect(screen.queryByText(/None set/)).not.toBeInTheDocument();
  });

  it("tells a directory member the directory supplies none and this is theirs", async () => {
    // Editable **and** from a directory: the account appeared at a first sign
    // in and the directory carries no address attribute. `editable` alone reads
    // the same as a local account that has not set one.
    api.on("/api/users/me/email", {
      body: { ...MINE, from_directory: true },
    });
    render();

    expect(
      await screen.findByText(/The directory supplies none/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Your address")).toBeInTheDocument();
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
          {
            id: 2,
            username: "sam",
            email: null,
            editable: true,
            from_directory: false,
          },
          {
            id: 3,
            username: "alex",
            email: "alex@directory.example",
            editable: false,
            from_directory: true,
          },
          // The middle case, and the admin list had no row of it, which is why
          // nothing caught the sentence being second person: sam is local and
          // empty, alex is a directory row the directory owns.
          {
            id: 4,
            username: "robin",
            email: null,
            editable: true,
            from_directory: true,
          },
        ],
      });
    });

    // #103. An admin looking for the row whose reminders go nowhere reads a
    // word rather than hunting for the box that happens to be empty.
    it("names the rows that have no address", async () => {
      render(true);

      // **Three, not two**, and the third is the reason to say so here: an
      // admin's own address is drawn twice on this page, once in their own
      // section and once as their row of the member list, which is every
      // member and includes them. So the plain "None set." rows are the
      // caller's own twice and sam's once. Alex has an address, and robin's
      // row carries the directory sentence instead.
      expect(await screen.findAllByText("None set.")).toHaveLength(3);
      expect(
        screen.getByText(/The directory supplies none/),
      ).toBeInTheDocument();
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
      // **Sam's own Save, found through sam's own form**, rather than the last
      // of the "Save" buttons on the page. That positional locator meant this
      // test asserted about whichever member the fixture happened to list last,
      // and it broke the moment a fourth member was added for a different
      // reason. Every row draws the same accessible name, so the form is the
      // only handle that says which row.
      const row = field.closest("form");
      expect(row).not.toBeNull();
      await userEvent.click(within(row!).getByRole("button", { name: "Save" }));

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
