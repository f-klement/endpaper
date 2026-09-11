/**
 * Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/StoreImport.tsx.
 *
 * Two things this card must do that no other import card does: draw itself
 * from the registry rather than from a list of stores it names, and show a
 * member that one source was lost while the rest arrived. The second is the
 * rule `docs/device-libraries.md` states, and this is the first screen a person
 * can see it on.
 */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Locale } from "../../../../../src/api/generated/model";
import { de, en } from "../../../../../src/i18n";
import { STORES, STORE_IDS } from "../../../../../src/lib/stores";
import StoreImport from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/StoreImport";
import type {
  StorePreview,
  StoreSources,
} from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/hooks";
import { renderLocalised } from "../../../../utils";

function library(
  books: number,
  overrides: {
    skipped?: number;
    refused?: number;
    ownershipStated?: boolean;
  } = {},
) {
  return {
    books: Array.from({ length: books }, (_, index) => ({
      key: `book-${index}`,
      title: `Book ${index}`,
      authors: [],
      isbn: null,
      identifiers: [],
      publisher: null,
      year: null,
      language: null,
      description: null,
      seriesName: null,
      seriesIndex: null,
      format: null,
    })),
    // Defaulted to true, which is what four of the six stores say. A test
    // wanting the other answer asks for it, so nothing here quietly decides
    // what a store established about ownership.
    ownershipStated: overrides.ownershipStated ?? true,
    skipped: overrides.skipped ?? 0,
    refused: overrides.refused ?? 0,
  };
}

function preview(overrides: Partial<StorePreview> = {}): StorePreview {
  return { total: 41, importable: 41, ...overrides };
}

function renderCard(
  overrides: Partial<React.ComponentProps<typeof StoreImport>> = {},
  locale: Locale = Locale.en,
) {
  const props = {
    sources: {} as StoreSources,
    preview: null,
    progress: null,
    result: null,
    isReading: false,
    isImporting: false,
    onChoose: vi.fn(),
    onConfirm: vi.fn(),
    onStop: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  renderLocalised(<StoreImport {...props} />, { locale });
  return props;
}

describe("the card is the registry", () => {
  it("draws a row for every store, and names none of its own", async () => {
    renderCard();

    for (const id of STORE_IDS) {
      const store = STORES[id];
      expect(
        screen.getByRole("heading", { name: en[store.name] }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: en[store.choose] }),
      ).toBeInTheDocument();
    }
  });

  it("says before the first picker that nothing is uploaded", async () => {
    // The member is deciding whether to hand over a file holding their whole
    // library, so this is said where the decision is made rather than in a
    // document.
    renderCard();

    expect(screen.getByText(en["stores.explain"])).toBeInTheDocument();
    expect(en["stores.explain"]).toContain("No book file is uploaded");
  });

  it("hands a picked file to the store whose picker took it", async () => {
    const props = renderCard();
    const file = new File(["bytes"], "KoboReader.sqlite");

    await userEvent.upload(screen.getByLabelText(en[STORES.kobo.choose]), file);

    expect(props.onChoose).toHaveBeenCalledWith("kobo", file);
  });
});

describe("what a row says it has not been tested on", () => {
  it("puts the tolino sentence on the Kobo row and nowhere else", () => {
    renderCard();
    const kobo = screen.getByRole("heading", { name: "Kobo" }).parentElement!;

    expect(
      within(kobo).getByText(en["stores.kobo.tolino"]),
    ).toBeInTheDocument();
    // One row carries it, so a caveat cannot drift onto a store it is not
    // about: the sentence names a device and the row it sits on is what says
    // which reader the claim is about.
    expect(screen.getAllByText(en["stores.kobo.tolino"])).toHaveLength(1);
  });

  it("says it in German too, with the bound intact", () => {
    // A bound that survives only in English is a promise in the other
    // language. The German string carries the same two halves.
    renderCard({}, Locale.de);

    expect(screen.getByText(de["stores.kobo.tolino"])).toBeInTheDocument();
    expect(de["stores.kobo.tolino"]).toContain("tolino");
    expect(de["stores.kobo.tolino"]).toContain("nie an einem tolino");
  });
});

describe("one source that cannot be read costs that source", () => {
  const oneReadOneLost: StoreSources = {
    kobo: {
      status: "read",
      fileName: "KoboReader.sqlite",
      library: library(41),
    },
    playBooks: {
      status: "failed",
      fileName: "takeout.zip",
      failure: "not-an-archive",
    },
  };

  it("names the store that was lost, and the reason, in one sentence", () => {
    // **By name.** The heading above it names the store too, and that is not
    // enough: a member reading "was skipped" with no name stops the import to
    // find out which one, which is the outcome this rule exists to avoid.
    renderCard({ sources: oneReadOneLost, preview: preview() });

    expect(screen.getByRole("alert").textContent).toBe(
      `${en["stores.playBooks.name"]} was skipped: ${en["stores.failureNotAnArchive"]}`,
    );
  });

  it("still offers the import, counting only what read", () => {
    renderCard({ sources: oneReadOneLost, preview: preview() });

    expect(
      screen.getByText("41 books in all, 41 with a title."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Import 41 books" }),
    ).toBeEnabled();
  });

  it("reports a reader that threw as that one source too", () => {
    // A reader answers rather than throws, so this is a bug in one. It still
    // costs one source: the card has a state for it and the other source's
    // books are still on offer.
    renderCard({
      sources: {
        kobo: {
          status: "read",
          fileName: "KoboReader.sqlite",
          library: library(41),
        },
        playBooks: {
          status: "error",
          fileName: "takeout.zip",
          error: new Error("a bug"),
        },
      },
      preview: preview(),
    });

    expect(screen.getByRole("alert").textContent).toContain(
      en["stores.playBooks.name"],
    );
    expect(
      screen.getByRole("button", { name: "Import 41 books" }),
    ).toBeEnabled();
  });
});

describe("what a source turned out to hold", () => {
  it("reports the rows that were not this member's books", () => {
    renderCard({
      sources: {
        kobo: {
          status: "read",
          fileName: "KoboReader.sqlite",
          library: library(41, { skipped: 3, refused: 2 }),
        },
      },
      preview: preview(),
    });

    expect(screen.getByText("41 books read.")).toBeInTheDocument();
    expect(
      screen.getByText("3 more entries were not books on this account."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("2 books were named and could not be opened."),
    ).toBeInTheDocument();
  });

  it("says nothing about a count of zero", () => {
    // A device that skipped nothing is not a device that skipped 0, and a line
    // per zero would bury the one number that matters.
    renderCard({
      sources: {
        kobo: {
          status: "read",
          fileName: "KoboReader.sqlite",
          library: library(41),
        },
      },
      preview: preview(),
    });

    expect(
      screen.queryByText("0 more entries were not books on this account."),
    ).toBeNull();
  });

  it("offers nothing to import when no source has read", () => {
    renderCard();

    expect(screen.queryByRole("button", { name: /^Import/ })).toBeNull();
  });
});

describe("writing what was read", () => {
  it("names a duplicate as the ordinary outcome it is", () => {
    // Importing the same device twice is what a second run is, and a member
    // who reads "not added" for six hundred books believes something broke.
    renderCard({
      result: {
        added: 2,
        failures: [{ title: "Dune", status: 409 }],
        stopped: false,
      },
    });

    expect(
      screen.getByText(`Dune · ${en["stores.duplicate"]}`),
    ).toBeInTheDocument();
  });

  it("says a short count was the member's own doing", () => {
    renderCard({
      result: { added: 2, failures: [], stopped: true },
    });

    expect(
      screen.getByText("Stopped. 2 books were added before that."),
    ).toBeInTheDocument();
  });
});
