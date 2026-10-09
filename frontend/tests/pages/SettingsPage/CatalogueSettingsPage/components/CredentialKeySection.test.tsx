/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/CredentialKeySection.tsx.
 *
 * **The phrase is the key, so what is pinned here is where it is not.** It
 * reaches the screen exactly once, from the response to the call that made it,
 * and nothing fetches it back: the server refuses to make a second one, so
 * there is no call that could. Dismissing it is final, which is why the notice
 * has to be read before the button that dismisses it is offered.
 *
 * The rest is the cost, which belongs beside the field rather than only in the
 * docs, and the location, which is a token the screen translates rather than
 * server prose it prints.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { SettingsOut } from "../../../../../src/api/generated/model";
import CredentialKeySection from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/CredentialKeySection";
import { mockApi, renderWithProviders, type MockApi } from "../../../../utils";

let api: MockApi;

const NO_KEY = {
  configured: false,
  location: "",
  can_generate: true,
  problem: "",
  unreadable_sources: [],
};

const PHRASE = Array.from({ length: 24 }, (_, index) => `word${index}`).join(
  " ",
);

beforeEach(() => {
  api = mockApi();
  api.on("/api/settings/credential-key", { body: NO_KEY }, "GET");
});

/** The roster, so the section can name a catalogue rather than print its id. */
const ROSTER = [
  { source: "bne" },
  { source: "dnb" },
] as unknown as SettingsOut["catalogue_sources"];

function render() {
  return renderWithProviders(
    <CredentialKeySection
      settings={{ catalogue_sources: ROSTER } as SettingsOut}
    />,
  );
}

describe("with no key yet", () => {
  it("says no login can be stored", async () => {
    render();
    expect(
      await screen.findByText(
        "No encryption key yet, so no login can be stored.",
      ),
    ).toBeInTheDocument();
  });

  it("offers to make one", async () => {
    render();
    expect(
      await screen.findByRole("button", { name: "Create an encryption key" }),
    ).toBeInTheDocument();
  });

  it("does not offer to make one where there is nowhere to keep it", async () => {
    api.on(
      "/api/settings/credential-key",
      { body: { ...NO_KEY, can_generate: false } },
      "GET",
    );
    render();
    await screen.findByText(
      "No encryption key yet, so no login can be stored.",
    );
    expect(
      screen.queryByRole("button", { name: "Create an encryption key" }),
    ).not.toBeInTheDocument();
  });

  it("states the cost before anything has been created", async () => {
    render();
    expect(
      await screen.findByText(
        /every catalogue login stored here has to be entered again/,
      ),
    ).toBeInTheDocument();
  });
});

describe("making one", () => {
  beforeEach(() => {
    api.on(
      "/api/settings/credential-key",
      { body: { phrase: PHRASE } },
      "POST",
    );
  });

  it("shows the words, once", async () => {
    render();
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "Create an encryption key" }),
      );
    expect(await screen.findByText(PHRASE)).toBeInTheDocument();
  });

  it("says they are shown only this once", async () => {
    render();
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "Create an encryption key" }),
      );
    expect(
      await screen.findByText(/only time they are shown/),
    ).toBeInTheDocument();
  });

  it("and they are gone for good once dismissed", async () => {
    const user = userEvent.setup();
    render();
    await user.click(
      await screen.findByRole("button", { name: "Create an encryption key" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "I have written it down" }),
    );
    // Two steps, because this is the irreversible one: the words are still
    // there after the first click, and the question is on screen. Discarding a
    // key is recoverable by anybody holding the phrase; this is not.
    expect(screen.getByText(PHRASE)).toBeInTheDocument();
    expect(
      screen.getByText(
        "These words will not be shown again. Have you written them down?",
      ),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "I have written it down" }),
    );
    await waitFor(() =>
      expect(screen.queryByText(PHRASE)).not.toBeInTheDocument(),
    );
  });

  it("never asks the server for a phrase", async () => {
    const user = userEvent.setup();
    render();
    await user.click(
      await screen.findByRole("button", { name: "Create an encryption key" }),
    );
    await screen.findByText(PHRASE);
    const reads = api.calls.filter(
      (call) => call.method === "GET" && call.url.includes("credential-key"),
    );
    expect(reads.length).toBeGreaterThan(0);
    expect(api.lastCall("/api/settings/credential-key", "POST")).toBeDefined();
  });
});

describe("with a key in place", () => {
  it("names where it is held, translated rather than printed", async () => {
    api.on(
      "/api/settings/credential-key",
      { body: { ...NO_KEY, configured: true, location: "keychain" } },
      "GET",
    );
    render();
    expect(
      await screen.findByText(
        "A key is in place, held in this machine's keychain.",
      ),
    ).toBeInTheDocument();
  });

  it("counts the logins it cannot open", async () => {
    api.on(
      "/api/settings/credential-key",
      {
        body: {
          ...NO_KEY,
          configured: true,
          location: "file",
          unreadable_sources: ["bne", "dnb"],
        },
      },
      "GET",
    );
    render();
    expect(
      await screen.findByText(/2 stored logins cannot be read as things stand/),
    ).toBeInTheDocument();
  });

  it("reports a configuration problem rather than swallowing it", async () => {
    api.on(
      "/api/settings/credential-key",
      {
        body: {
          ...NO_KEY,
          problem: "Different encryption keys are configured in two places.",
        },
      },
      "GET",
    );
    render();
    expect(
      await screen.findByText(
        "Different encryption keys are configured in two places.",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer to discard a key the deployment pinned", async () => {
    api.on(
      "/api/settings/credential-key",
      { body: { ...NO_KEY, configured: true, location: "env" } },
      "GET",
    );
    render();
    await screen.findByText(/A key is in place/);
    expect(
      screen.queryByRole("button", { name: "Discard this key" }),
    ).not.toBeInTheDocument();
  });

  it("asks before discarding one it can", async () => {
    api.on(
      "/api/settings/credential-key",
      { body: { ...NO_KEY, configured: true, location: "file" } },
      "GET",
    );
    render();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Discard this key" }));
    expect(
      await screen.findByText(/Only if the recovery phrase is lost/),
    ).toBeInTheDocument();
    expect(
      api.lastCall("/api/settings/credential-key", "DELETE"),
    ).toBeUndefined();
  });
});

describe("typing a phrase back in", () => {
  it("sends what was typed", async () => {
    const user = userEvent.setup();
    api.on("/api/settings/credential-key", { body: NO_KEY }, "PUT");
    render();
    await user.click(
      await screen.findByRole("button", { name: "Enter a recovery phrase" }),
    );
    await user.type(
      screen.getByLabelText("Enter a recovery phrase"),
      "one two three",
    );
    await user.click(screen.getByRole("button", { name: "Use this phrase" }));

    await waitFor(() =>
      expect(api.lastCall("/api/settings/credential-key", "PUT")?.body).toEqual(
        {
          phrase: "one two three",
        },
      ),
    );
  });

  it("says capitals and spacing do not matter", async () => {
    render();
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "Enter a recovery phrase" }),
      );
    expect(
      await screen.findByText(/Capitals and extra spaces do not matter/),
    ).toBeInTheDocument();
  });
});

describe("when the server refuses", () => {
  it("shows the refusal rather than swallowing it", async () => {
    api.on(
      "/api/settings/credential-key",
      {
        status: 409,
        body: { detail: "This deployment already has an encryption key." },
      },
      "POST",
    );
    render();
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "Create an encryption key" }),
      );
    expect(
      await screen.findByText("This deployment already has an encryption key."),
    ).toBeInTheDocument();
  });

  it("keeps the typed phrase when the checksum fails", async () => {
    // The refusal the checksum exists to produce. Clearing the box on failure
    // threw away all 24 words and said nothing, which is the whole property
    // undone at the last step.
    const user = userEvent.setup();
    api.on(
      "/api/settings/credential-key",
      {
        status: 422,
        body: { detail: "The recovery phrase failed its checksum." },
      },
      "PUT",
    );
    render();
    await user.click(
      await screen.findByRole("button", { name: "Enter a recovery phrase" }),
    );
    await user.type(
      screen.getByLabelText("Enter a recovery phrase"),
      "one two three",
    );
    await user.click(screen.getByRole("button", { name: "Use this phrase" }));

    expect(
      await screen.findByText("The recovery phrase failed its checksum."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Enter a recovery phrase")).toHaveValue(
      "one two three",
    );
  });

  it("clears the box only once the server took it", async () => {
    const user = userEvent.setup();
    api.on("/api/settings/credential-key", { body: NO_KEY }, "PUT");
    render();
    await user.click(
      await screen.findByRole("button", { name: "Enter a recovery phrase" }),
    );
    await user.type(
      screen.getByLabelText("Enter a recovery phrase"),
      "one two three",
    );
    await user.click(screen.getByRole("button", { name: "Use this phrase" }));
    await waitFor(() =>
      expect(
        screen.queryByLabelText("Enter a recovery phrase"),
      ).not.toBeInTheDocument(),
    );
  });
});

describe("the field the key is typed into", () => {
  it("is not sent to a spell checker", async () => {
    render();
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "Enter a recovery phrase" }),
      );
    const field = screen.getByLabelText("Enter a recovery phrase");
    expect(field).toHaveAttribute("spellcheck", "false");
    expect(field).toHaveAttribute("autocorrect", "off");
  });
});

describe("naming what cannot be opened", () => {
  it("uses the catalogue's name where the roster has it", async () => {
    api.on(
      "/api/settings/credential-key",
      {
        body: {
          ...NO_KEY,
          configured: true,
          location: "file",
          unreadable_sources: ["bne"],
        },
      },
      "GET",
    );
    render();
    expect(
      await screen.findByText("Spanish National Library"),
    ).toBeInTheDocument();
  });

  it("and the raw source where it does not, rather than a message key", async () => {
    // The orphan is the case this field was changed for, and `t()` falls back
    // to the key, so a blanket lookup would print `providers.name.<source>`.
    api.on(
      "/api/settings/credential-key",
      {
        body: {
          ...NO_KEY,
          configured: true,
          location: "file",
          unreadable_sources: ["a-catalogue-that-went-away"],
        },
      },
      "GET",
    );
    render();
    expect(
      await screen.findByText("a-catalogue-that-went-away"),
    ).toBeInTheDocument();
  });
});

describe("removing a login that blocks a new key", () => {
  it("offers a remove beside each one it names", async () => {
    api.on(
      "/api/settings/credential-key",
      { body: { ...NO_KEY, unreadable_sources: ["bne"] } },
      "GET",
    );
    render();
    await screen.findByText("Spanish National Library");
    expect(
      screen.getByRole("button", { name: "Remove stored login" }),
    ).toBeInTheDocument();
  });

  it("removes it by source, which is the only place a pinned one can be reached", async () => {
    // The logins list hides both controls on a pinned row, and a client cannot
    // tell a pinned row has a sealed row behind it, so this list is the one
    // surface that can act on it.
    api.on(
      "/api/settings/credential-key",
      { body: { ...NO_KEY, unreadable_sources: ["bne"] } },
      "GET",
    );
    api.on(/credential$/, { body: { catalogue_sources: [] } }, "DELETE");
    render();
    await screen.findByText("Spanish National Library");

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
