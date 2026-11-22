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

import { fireEvent, screen, waitFor } from "@testing-library/react";
import fc from "fast-check";
import { beforeEach, describe, expect, it } from "vitest";

import LibrarySettingsPage from "../../../../src/pages/SettingsPage/LibrarySettingsPage";
import { mockApi, renderWithProviders, type MockApi } from "../../../utils";
import { answersOf } from "../../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../../property";
import { forget, overSchema } from "../../../schemaPage";

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
      goodreads_lookup_enabled: false,
      default_locale: "en",
    },
  });
  api.on(/\/api\/settings$/, { body: SETTINGS });
  api.on("/api/books/custom-fields", { body: [] });
});

describe("LibrarySettingsPage", () => {
  /** The feature flags, with library mode where a test wants it. */
  function stubLibraryMode(on: boolean) {
    api.on("/api/settings/features", {
      body: {
        goodreads_lookup_enabled: false,
        default_locale: "en",
        library_mode: on,
      },
    });
  }

  it("checks the files saved from the Calibre library folder when it is picked", async () => {
    // The scan page's Calibre door by another way in, and the same sweep.
    stubLibraryMode(true);
    api.on(
      "/api/books/digital-references",
      { body: { items: [], total: 0, page: 1, page_size: 200 } },
      "GET",
    );
    const file = new File(["text"], "metadata.opf");
    Object.defineProperty(file, "webkitRelativePath", {
      value: "Calibre Library/metadata.opf",
    });
    render();

    fireEvent.change(await screen.findByLabelText("Pick the library folder"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(api.lastCall("root_label=Calibre", "GET")).toBeDefined(),
    );
  });

  it("offers the store import to every member, not only in library mode", async () => {
    // The card the whole store surface hangs from. Two readers shipped before
    // it existed and no member could reach either, so a route with the readers
    // and no card is the failure this asserts against, not the layout.
    stubLibraryMode(false);
    render();

    expect(
      await screen.findByRole("heading", {
        name: "Bring a library across from a device or a store",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Choose KoboReader.sqlite" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Choose a Takeout archive" }),
    ).toBeInTheDocument();
  });

  it("does not offer the MARC card to a household", async () => {
    // The server refuses both MARC routes without library mode, so this is
    // about not showing a household an exchange format nobody in it can use.
    stubLibraryMode(false);
    render();

    await screen.findByRole("heading", { name: "Bring a library across" });
    expect(
      screen.queryByRole("heading", { name: "Take a catalogue across" }),
    ).not.toBeInTheDocument();
  });

  it("offers the MARC card in library mode", async () => {
    stubLibraryMode(true);
    render();

    expect(
      await screen.findByRole("heading", { name: "Take a catalogue across" }),
    ).toBeInTheDocument();
  });

  it("offers the harvester to an admin in library mode", async () => {
    stubLibraryMode(true);
    render();

    expect(
      await screen.findByRole("heading", { name: "Harvest another catalogue" }),
    ).toBeInTheDocument();
  });

  it("does not offer the harvester to a household", async () => {
    // The anti vacuity arm: the settings record answers here too, so the card
    // is withheld by library mode and not by the record.
    stubLibraryMode(false);
    render();

    await screen.findByRole("heading", { name: "Bring a library across" });
    await waitFor(() =>
      expect(api.lastCall(/\/api\/settings$/, "GET")).toBeDefined(),
    );
    expect(
      screen.queryByRole("heading", { name: "Harvest another catalogue" }),
    ).not.toBeInTheDocument();
  });

  it("switches the heading field off from library mode", async () => {
    stubLibraryMode(true);
    api.on(/\/api\/settings$/, { body: SETTINGS }, "GET");
    api.on(/\/api\/settings$/, { body: SETTINGS }, "PUT");
    render();

    const toggle = await screen.findByRole("checkbox", {
      name: "Offer headings from the local vocabularies",
    });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(api.lastCall(/\/api\/settings$/, "PUT")?.body).toEqual({
        headings_from_vocabulary: false,
      }),
    );
  });

  it("does not offer the heading field switch to a household", async () => {
    stubLibraryMode(false);
    render();

    await waitFor(() =>
      expect(api.lastCall(/\/api\/settings$/, "GET")).toBeDefined(),
    );
    await screen.findByRole("heading", { name: "Bring a library across" });
    expect(
      screen.queryByRole("checkbox", {
        name: "Offer headings from the local vocabularies",
      }),
    ).not.toBeInTheDocument();
  });

  it("offers a harvest once the harvester is switched on", async () => {
    stubLibraryMode(true);
    api.on(/\/api\/settings$/, {
      body: {
        ...SETTINGS,
        oai_harvest_enabled: true,
        oai_harvest_base_url: "http://catalogue.lan/oai",
      },
    });
    render();

    expect(
      await screen.findByRole("heading", { name: "Harvest now" }),
    ).toBeInTheDocument();
  });

  it("does not offer a harvest to a household with the harvester on", async () => {
    stubLibraryMode(false);
    api.on(/\/api\/settings$/, {
      body: {
        ...SETTINGS,
        oai_harvest_enabled: true,
        oai_harvest_base_url: "http://catalogue.lan/oai",
      },
    });
    render();

    // Drawn from the settings answer, so the card has had its chance to appear.
    await screen.findByRole("heading", { name: "Classification schemes" });
    expect(
      screen.queryByRole("heading", { name: "Harvest now" }),
    ).not.toBeInTheDocument();
  });

  it("does not offer a harvest to a member in library mode", async () => {
    stubLibraryMode(true);
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    render();

    await screen.findByRole("heading", { name: "Take a catalogue across" });
    await waitFor(() =>
      expect(api.lastCall(/\/api\/settings$/, "GET")).toBeDefined(),
    );
    expect(
      screen.queryByRole("heading", { name: "Harvest now" }),
    ).not.toBeInTheDocument();
  });

  it("withdraws a preview once another repository address is saved", async () => {
    // The apply harvests whatever address is stored when it runs, so a
    // preview of the old one confirmed a harvest nobody previewed.
    stubLibraryMode(true);
    const harvesting = {
      ...SETTINGS,
      oai_harvest_enabled: true,
      oai_harvest_base_url: "http://catalogue.lan/oai",
    };
    api.on(/\/api\/settings$/, { body: harvesting }, "GET");
    api.on(
      /\/api\/settings$/,
      { body: { ...harvesting, oai_harvest_base_url: "http://other.lan/oai" } },
      "PUT",
    );
    api.on(
      "/api/imports/harvest/preview",
      {
        body: {
          already_held: 0,
          deleted: 0,
          metadata_prefix: "marc21",
          pages_read: 1,
          readable: 2,
          records_seen: 2,
          repository_name: null,
          skipped: 0,
          total_records: 2,
          truncated: false,
        },
      },
      "POST",
    );
    render();
    fireEvent.click(
      await screen.findByRole("button", { name: "Read the repository" }),
    );
    await screen.findByRole("button", { name: "Harvest 2 records" });

    fireEvent.change(screen.getByLabelText("Repository address"), {
      target: { value: "http://other.lan/oai" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Harvest 2 records" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Read the repository" }),
    ).toBeInTheDocument();
  });

  it("does not offer a harvest while the harvester is off", async () => {
    // The anti vacuity arm: library mode and an admin, so only the switch
    // withholds the card.
    stubLibraryMode(true);
    render();

    await screen.findByRole("heading", { name: "Harvest another catalogue" });
    expect(
      screen.queryByRole("heading", { name: "Harvest now" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the CSV import in library mode too", async () => {
    // An archive still has people who arrive from Goodreads. The MARC card is
    // an addition rather than a replacement.
    stubLibraryMode(true);
    render();

    expect(
      await screen.findByRole("heading", { name: "Bring a library across" }),
    ).toBeInTheDocument();
  });

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

  it("draws an admin the subject vocabularies and the classification schemes", async () => {
    api.on("/api/settings/vocabularies", { body: [] }, "GET");
    api.on("/api/settings/classification-schemes", { body: [] }, "GET");
    render();

    expect(
      await screen.findByRole("heading", { name: "Subject vocabularies" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Classification schemes" }),
    ).toBeInTheDocument();
  });

  it("neither draws a member the vocabularies and schemes nor asks for them", async () => {
    // Both routes answer a member 403. Drawn anyway, the cards would stand
    // empty under an alert, and asked anyway, they would cost two refusals.
    api.on(
      /\/api\/settings$/,
      { status: 403, body: { detail: "Admins only" } },
      "GET",
    );
    render();

    await screen.findByRole("heading", { name: "Bring a library across" });
    await waitFor(() =>
      expect(api.lastCall(/\/api\/settings$/, "GET")).toBeDefined(),
    );

    expect(
      screen.queryByRole("heading", { name: "Subject vocabularies" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Classification schemes" }),
    ).not.toBeInTheDocument();
    expect(
      api.calls.filter(
        (call) =>
          call.url.includes("/api/settings/vocabularies") ||
          call.url.includes("/api/settings/classification-schemes"),
      ),
    ).toEqual([]);
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

/** How many entries an answer holds, or -1 for one that is not a list. */
const entries = (body: unknown) => (Array.isArray(body) ? body.length : -1);

describe("LibrarySettingsPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do. Every
  // request this page makes for a signed in account declares a 401 beside its
  // 200, and an admin only one a 403, so both are drawn as well.
  it("is drawn no custom field and one", async () => {
    await witness(answersOf("list_custom_fields"), {
      "is no custom field": (answer) => entries(answer.body) === 0,
      "is a custom field": (answer) => entries(answer.body) > 0,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(<LibrarySettingsPage />, answers);
            expect(rendered.problems).toEqual([]);
            return rendered;
          } finally {
            forget();
          }
        },
        {
          "showed a value an answer carried": (_, rendered) =>
            rendered.echoed > 0,
        },
      ),
    ).toBe(PROFILE.runs);
  });
});
