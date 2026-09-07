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
 *
 * **A login this build ships is a fourth**, and it is the one this screen must
 * never draw as a stored one. A library told it has a login stored has no
 * reason to enter the account it actually holds, which is the confusion the
 * whole shipped default rests on not creating. `credential_provenance` is the
 * one field that answers it and every case below binds to that field.
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
    credential_provenance: "none",
    credential_username_preview: "",
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
        credential_provenance: "stored",
        credential_username_preview: "••••••••rary",
      }),
    ]);
    expect(
      screen.getByText("A login is stored (••••••••rary)."),
    ).toBeInTheDocument();
  });

  it("offers to remove it", () => {
    render([source({ credential_provenance: "stored" })]);
    expect(
      screen.getByRole("button", { name: "Remove stored login" }),
    ).toBeInTheDocument();
  });

  it("removes it by the source in the path", async () => {
    api.on(/credential$/, { body: { catalogue_sources: [] } }, "DELETE");
    render([source({ credential_provenance: "stored" })]);

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
    render([
      source({ credential_provenance: "stored", credential_unreadable: true }),
    ]);
    expect(
      screen.getByText(
        "A login is stored for this catalogue and cannot be read. See the encryption key below.",
      ),
    ).toBeInTheDocument();
  });

  it("shows no masked username, because there is none to show", () => {
    render([
      source({
        credential_provenance: "stored",
        credential_unreadable: true,
        credential_username_preview: "",
      }),
    ]);
    expect(screen.queryByText(/A login is stored \(/)).not.toBeInTheDocument();
  });
});

describe("with one the deployment pinned", () => {
  it("names the variable and offers no edit", () => {
    render([source({ credential_provenance: "env" })]);
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
    render([source({ credential_provenance: "env" })]);
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
      source({
        credential_provenance: "stored",
        credential_username_preview: "••••ice",
      }),
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
    render([source({ credential_provenance: "stored" })]);
    expect(
      screen.getByRole("button", { name: "Change login" }),
    ).toBeInTheDocument();
  });

  it("is not offered again in the picker", () => {
    render([source({ credential_provenance: "stored" })]);
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
        credential_provenance: "env",
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

describe("with one this build ships", () => {
  it("says the catalogue publishes it rather than that one is stored", () => {
    render([source({ credential_provenance: "shipped" })]);
    expect(
      screen.getByText(/This catalogue publishes a login for everyone/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/A login is stored \(/)).not.toBeInTheDocument();
  });

  it("offers to replace it, in words that say it is not this library's", () => {
    render([source({ credential_provenance: "shipped" })]);
    expect(
      screen.getByRole("button", { name: "Use this library's own login" }),
    ).toBeInTheDocument();
  });

  it("offers no way to remove it, because there is no stored row to remove", () => {
    render([source({ credential_provenance: "shipped" })]);
    expect(
      screen.queryByRole("button", { name: "Remove stored login" }),
    ).not.toBeInTheDocument();
  });

  it("is not offered again in the picker", () => {
    render([source({ credential_provenance: "shipped" })]);
    const chooser = screen.getByLabelText(
      "Add a login for",
    ) as HTMLSelectElement;
    expect([...chooser.options].map((option) => option.value)).toEqual([""]);
  });

  it("takes the same form as any other login when it is replaced", async () => {
    const user = userEvent.setup();
    api.on(/credential$/, { body: { catalogue_sources: [] } }, "PUT");
    render([source({ credential_provenance: "shipped" })]);

    await user.click(
      screen.getByRole("button", { name: "Use this library's own login" }),
    );
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: "Save login" }));

    await waitFor(() =>
      expect(api.lastCall(/credential$/, "PUT")?.url).toContain(
        "/api/settings/catalogue-sources/bne/credential",
      ),
    );
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

  it("closes the row's own button too, which a shipped login is the first to reach", async () => {
    // **The picker was the only guard and it held by accident.** A keyless
    // install had nothing in the held list at all, so no row rendered a button;
    // a shipped default puts one there on every install, and an enabled Save
    // behind it is the 409 the line above exists to answer.
    api.on("/api/settings/credential-key", {
      body: {
        configured: false,
        location: "",
        can_generate: true,
        problem: "",
        unreadable_sources: [],
      },
    });
    render([source({ credential_provenance: "shipped" })]);
    // The hint first, exactly as the picker's arm does: the row renders before
    // the key query settles, so asserting on the button straight away asks it
    // while `needsKeyFirst` is still undecided and passes on any component.
    await screen.findByText(
      "Make an encryption key below before storing a login.",
    );
    expect(
      screen.getByRole("button", { name: "Use this library's own login" }),
    ).toBeDisabled();
  });

  it("closes it for a stored login as well, which is the same rule", async () => {
    api.on("/api/settings/credential-key", {
      body: {
        configured: false,
        location: "",
        can_generate: true,
        problem: "",
        unreadable_sources: [],
      },
    });
    render([source({ credential_provenance: "stored" })]);
    await screen.findByText(
      "Make an encryption key below before storing a login.",
    );
    expect(screen.getByRole("button", { name: "Change login" })).toBeDisabled();
  });
});

describe("a row from a page older than the provenance field", () => {
  it("is not drawn as a login that is stored with an empty username", () => {
    // The field is optional on the wire, so `undefined` is reachable on version
    // skew, and `!== "none"` reads it as "has one". The pair this replaced
    // failed closed here.
    render([source({ credential_provenance: undefined })]);
    expect(screen.getByText("No login stored.")).toBeInTheDocument();
    expect(screen.queryByText(/A login is stored \(/)).not.toBeInTheDocument();
  });
});
