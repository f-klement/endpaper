/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/CatalogueLoginsSection.tsx.
 *
 * A login here is somebody else's, so what is pinned is what the screen may
 * say about one: that it exists, enough of the username to tell one from
 * another, and nothing else. The password is write only, exactly as the Google
 * Books key beside it is, because the server never sends one back.
 *
 * **Held and unopenable is a third state**, not a variant of "stored". The
 * screen says so and points at the key, because for three of the four causes
 * the remedy is on the key and recovers every login at once.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import CatalogueLoginsSection from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/CatalogueLoginsSection";
import { mockApi, renderWithProviders, type MockApi } from "../../../../utils";

let api: MockApi;

function source(over: Record<string, unknown> = {}) {
  return {
    source: "bne",
    enabled: true,
    answers_lookup: true,
    answers_search: false,
    slow: false,
    asked_first: false,
    needs_a_key: false,
    has_key: false,
    ready: true,
    serves_groups: [],
    has_credential: false,
    credential_username_preview: "",
    credential_from_env: false,
    credential_unreadable: false,
    ...over,
  };
}

function render(rows: ReturnType<typeof source>[]) {
  return renderWithProviders(
    <CatalogueLoginsSection settings={{ catalogue_sources: rows } as never} />,
  );
}

beforeEach(() => {
  api = mockApi();
});

describe("with nothing stored", () => {
  it("says so rather than showing an empty list", () => {
    render([source()]);
    expect(screen.getByText("No login stored.")).toBeInTheDocument();
  });

  it("still offers to add one to any catalogue", () => {
    render([source()]);
    expect(screen.getByLabelText("Add a login for")).toBeInTheDocument();
  });
});

describe("with one stored", () => {
  it("shows the masked username and never a password", () => {
    render([
      source({
        has_credential: true,
        credential_username_preview: "••••••••rary",
      }),
    ]);
    expect(
      screen.getByText("A login is stored (••••••••rary)."),
    ).toBeInTheDocument();
  });

  it("offers to remove it", () => {
    render([source({ has_credential: true })]);
    expect(
      screen.getByRole("button", { name: "Remove stored login" }),
    ).toBeInTheDocument();
  });

  it("removes it by the source in the path", async () => {
    api.on(/credential$/, { body: { catalogue_sources: [] } }, "DELETE");
    render([source({ has_credential: true })]);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Remove stored login" }));

    await waitFor(() =>
      expect(api.lastCall(/credential$/, "DELETE")?.url).toContain(
        "/api/settings/catalogue-sources/bne/credential",
      ),
    );
  });
});

describe("with one that cannot be read", () => {
  it("says so and points at the key rather than saying to retype it", () => {
    render([source({ has_credential: true, credential_unreadable: true })]);
    expect(
      screen.getByText(
        "A login is stored for this catalogue and cannot be read. See the encryption key below.",
      ),
    ).toBeInTheDocument();
  });

  it("shows no masked username, because there is none to show", () => {
    render([
      source({
        has_credential: true,
        credential_unreadable: true,
        credential_username_preview: "",
      }),
    ]);
    expect(screen.queryByText(/A login is stored \(/)).not.toBeInTheDocument();
  });
});

describe("with one the deployment pinned", () => {
  it("names the variable and offers no edit", () => {
    render([source({ has_credential: true, credential_from_env: true })]);
    expect(
      screen.getByText(
        /Change CATALOGUE_CREDENTIAL_BNE where the app is deployed/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove stored login" }),
    ).not.toBeInTheDocument();
  });

  it("and does not offer it as somewhere to add one", async () => {
    render([source({ has_credential: true, credential_from_env: true })]);
    const chooser = screen.getByLabelText("Add a login for");
    expect(chooser).not.toHaveTextContent("Spanish National Library");
  });
});

describe("saving one", () => {
  it("sends both halves to the source that was chosen", async () => {
    const user = userEvent.setup();
    api.on(/credential$/, { body: { catalogue_sources: [] } }, "PUT");
    render([source()]);

    await user.selectOptions(screen.getByLabelText("Add a login for"), "bne");
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: "Save login" }));

    await waitFor(() =>
      expect(api.lastCall(/credential$/, "PUT")?.body).toEqual({
        username: "alice",
        password: "hunter2",
      }),
    );
  });

  it("will not send half a login", async () => {
    const user = userEvent.setup();
    render([source()]);

    await user.selectOptions(screen.getByLabelText("Add a login for"), "bne");
    await user.type(screen.getByLabelText("Username"), "alice");

    expect(screen.getByRole("button", { name: "Save login" })).toBeDisabled();
  });

  it("keeps the password field write only", async () => {
    const user = userEvent.setup();
    render([
      source({ has_credential: true, credential_username_preview: "••••ice" }),
    ]);

    await user.click(screen.getByRole("button", { name: "Change login" }));
    expect(screen.getByLabelText("Username")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("keeps the typed halves when the server refuses", async () => {
    const user = userEvent.setup();
    api.on(
      /credential$/,
      { status: 409, body: { detail: "Make a key first." } },
      "PUT",
    );
    render([source()]);

    await user.selectOptions(screen.getByLabelText("Add a login for"), "bne");
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: "Save login" }));

    expect(await screen.findByText("Make a key first.")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveValue("alice");
  });
});

describe("a catalogue that already has one", () => {
  it("is changed from its own row rather than from a control saying Add", () => {
    render([source({ has_credential: true })]);
    expect(
      screen.getByRole("button", { name: "Change login" }),
    ).toBeInTheDocument();
  });

  it("is not offered again in the picker", () => {
    render([source({ has_credential: true })]);
    const chooser = screen.getByLabelText(
      "Add a login for",
    ) as HTMLSelectElement;
    expect([...chooser.options].map((option) => option.value)).toEqual([""]);
  });
});

describe("a pinned variable that is not a credential", () => {
  it("says so rather than reporting it as supplied and working", () => {
    render([
      source({
        has_credential: true,
        credential_from_env: true,
        credential_unreadable: true,
      }),
    ]);
    expect(
      screen.getByText(
        /is set to something that is not a username and a password/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/supplied by the server's configuration/),
    ).not.toBeInTheDocument();
  });
});

describe("before there is a key", () => {
  it("says so and closes the picker rather than letting the save 409", async () => {
    api.on("/api/settings/credential-key", {
      body: {
        configured: false,
        location: "",
        can_generate: true,
        problem: "",
        unreadable_sources: [],
      },
    });
    render([source()]);
    expect(
      await screen.findByText(
        "Make an encryption key below before storing a login.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Add a login for")).toBeDisabled();
  });
});
