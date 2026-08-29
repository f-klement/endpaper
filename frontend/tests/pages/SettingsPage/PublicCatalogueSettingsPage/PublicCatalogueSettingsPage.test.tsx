/**
 * Tests for
 * src/pages/SettingsPage/PublicCatalogueSettingsPage/PublicCatalogueSettingsPage.tsx.
 *
 * The screen that publishes a catalogue, which is the one setting in this
 * application that makes rows readable with no session at all. Three things are
 * asserted and the third is the one that matters:
 *
 * 1. publishing is disabled until library mode is on, which is advice to this
 *    client (the guarantee is on the server, in
 *    `settings_store.public_catalogue_is_published`);
 * 2. turning it **off** is immediate, because making something less public is
 *    not a decision anybody needs protecting from;
 * 3. turning it **on** goes through a confirmation that **names what becomes
 *    public**, rather than asking "are you sure".
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import PublicCatalogueSettingsPage from "../../../../src/pages/SettingsPage/PublicCatalogueSettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";

let api: MockApi;

const BASE = {
  google_books_enabled: false,
  google_books_api_key_preview: "",
  has_google_books_api_key: false,
  goodreads_lookup_enabled: false,
  default_locale: "en",
  library_mode: false,
  public_catalogue_enabled: false,
  public_catalogue_indexing_enabled: false,
  public_catalogue_published: false,
};

function settings(overrides: Record<string, unknown> = {}) {
  api.on(/\/api\/settings$/, { body: { ...BASE, ...overrides } });
}

function render() {
  return renderWithProviders(<PublicCatalogueSettingsPage />);
}

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
  settings();
});

describe("PublicCatalogueSettingsPage", () => {
  it("refuses a member who is not an admin in a sentence", async () => {
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    render();

    expect(
      await screen.findByText("Only an admin can change these."),
    ).toBeInTheDocument();
  });

  it("cannot publish while library mode is off", async () => {
    render();
    expect(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    ).toBeDisabled();
  });

  it("says why, rather than leaving a dead control", async () => {
    render();
    expect(
      await screen.findByText(
        "Turn on library mode first. A catalogue cannot be published without it.",
      ),
    ).toBeInTheDocument();
  });

  it("turns library mode on without a confirmation, since it publishes nothing", async () => {
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Catalogue this library as a library",
      }),
    );

    const write = api.calls.find((call) => call.method === "PUT");
    expect(write?.body).toEqual({ library_mode: true });
  });

  it("asks before publishing, and names what becomes public", async () => {
    settings({ library_mode: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    );

    expect(
      await screen.findByText(/Publish this catalogue\?/),
    ).toBeInTheDocument();
    // The four sentences the dialog exists for. A dialog that only asked "are
    // you sure" would move the decision without informing it.
    expect(screen.getByText(/^Shown:/)).toBeInTheDocument();
    expect(screen.getByText(/^Not shown:/)).toBeInTheDocument();
    expect(screen.getByText(/Private books stay private/)).toBeInTheDocument();
    expect(
      screen.getByText(/Search engines are told to stay away/),
    ).toBeInTheDocument();
  });

  it("writes nothing until the confirmation is accepted", async () => {
    settings({ library_mode: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    );

    expect(api.calls.filter((call) => call.method === "PUT")).toEqual([]);
  });

  it("publishes once the confirmation is accepted", async () => {
    settings({ library_mode: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Publish" }),
    );

    const write = api.calls.find((call) => call.method === "PUT");
    expect(write?.body).toEqual({ public_catalogue_enabled: true });
  });

  it("writes nothing when the confirmation is cancelled", async () => {
    settings({ library_mode: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel" }),
    );

    expect(api.calls.filter((call) => call.method === "PUT")).toEqual([]);
  });

  it("unpublishes with no confirmation at all", async () => {
    // Making something less public is not a decision anybody needs protecting
    // from, and a confirmation here would put a step between a household and
    // taking its catalogue back down.
    settings({
      library_mode: true,
      public_catalogue_enabled: true,
      public_catalogue_published: true,
    });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    );

    const write = api.calls.find((call) => call.method === "PUT");
    expect(write?.body).toEqual({ public_catalogue_enabled: false });
  });

  it("confirms when library mode republishes a catalogue in one click", async () => {
    // **The second route into publishing, which had no confirmation.** With
    // the publish row stored true and library mode off, turning library mode
    // on republishes immediately, and #95's "publishing takes two deliberate
    // acts" held only on the other route.
    settings({ library_mode: false, public_catalogue_enabled: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Catalogue this library as a library",
      }),
    );

    expect(
      await screen.findByText(/Publish this catalogue\?/),
    ).toBeInTheDocument();
    expect(api.calls.filter((call) => call.method === "PUT")).toEqual([]);
  });

  it("writes only the switch that was touched when that is confirmed", async () => {
    // The confirmation is shared, so it has to write the row the reader
    // actually reached for rather than the one it was first written for.
    settings({ library_mode: false, public_catalogue_enabled: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Catalogue this library as a library",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Publish" }),
    );

    const write = api.calls.find((call) => call.method === "PUT");
    expect(write?.body).toEqual({ library_mode: true });
  });

  it("does not claim library mode publishes nothing when it would", async () => {
    // The hint is true in every state but this one, and this is the state a
    // household reads immediately before publishing by accident.
    settings({ library_mode: false, public_catalogue_enabled: true });
    render();

    expect(
      await screen.findByText(/turning this back on republishes/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/It publishes nothing/)).not.toBeInTheDocument();
  });

  it("still says library mode publishes nothing when it does not", async () => {
    // The diagonal. Without it the rule above is satisfied by deleting the
    // reassuring sentence altogether.
    settings({ library_mode: false, public_catalogue_enabled: false });
    render();

    expect(await screen.findByText(/It publishes nothing/)).toBeInTheDocument();
  });

  it("turns library mode off without a confirmation", async () => {
    // Only publishing is confirmed. Making something less public never is.
    settings({ library_mode: true, public_catalogue_enabled: true });
    render();
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Catalogue this library as a library",
      }),
    );

    const write = api.calls.find((call) => call.method === "PUT");
    expect(write?.body).toEqual({ library_mode: false });
  });

  it("cannot invite a crawler to a catalogue that is not published", async () => {
    settings({ library_mode: true });
    render();
    expect(
      await screen.findByRole("checkbox", {
        name: "Let search engines index it",
      }),
    ).toBeDisabled();
  });

  it("offers a look at what a visitor sees once it is live", async () => {
    settings({
      library_mode: true,
      public_catalogue_enabled: true,
      public_catalogue_published: true,
    });
    render();

    expect(
      await screen.findByRole("link", { name: "See what a visitor sees" }),
    ).toHaveAttribute("href", "/catalogue");
  });

  it("reads the stored rows, not the conjunction, for the switches", async () => {
    // A publish row stored true while library mode is off is treated as off by
    // the server. The screen still has to show it as stored, or an admin turns
    // it on twice and watches it come back off.
    settings({ library_mode: false, public_catalogue_enabled: true });
    render();

    expect(
      await screen.findByRole("checkbox", {
        name: "Let anyone search this catalogue",
      }),
    ).toBeChecked();
  });
});
