/**
 * Tests for src/pages/SettingsPage/components/LibraryImport.tsx.
 *
 * The point of the two steps is that nothing is written until somebody has
 * looked at what the file turned out to be, so that is what most of these
 * pin: choosing a file previews, and only confirming imports.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  ImportResultOut,
  ImportPreviewOut,
} from "../../../../../src/api/generated/model";
import LibraryImport from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/LibraryImport";
import { renderLocalised } from "../../../../utils";

function outcome(overrides: Partial<ImportResultOut> = {}): ImportResultOut {
  return {
    rows_read: 10,
    matched: 6,
    created: 2,
    statuses_updated: 4,
    skipped: 0,
    unmatched_titles: [],
    ...overrides,
  };
}

function preview(overrides: Partial<ImportPreviewOut> = {}): ImportPreviewOut {
  return {
    headers: ["Title", "Author", "Exclusive Shelf"],
    mapping: {
      title: "Title",
      author: "Author",
      status: "Exclusive Shelf",
      isbn13: null,
      rating: null,
      date_read: null,
      tags: null,
    },
    delimiter: ",",
    distinct_tags: 3,
    total_rows: 10,
    skipped: 0,
    rows: [
      { title: "Dune", author: "Frank Herbert", isbn: null, status: "read" },
    ],
    ...overrides,
  };
}

function renderImport(
  overrides: Partial<React.ComponentProps<typeof LibraryImport>> = {},
) {
  const props = {
    isPreviewing: false,
    isImporting: false,
    preview: null,
    result: null,
    error: null,
    onChoose: vi.fn(),
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    onReviewUnconfirmed: vi.fn(),
    ...overrides,
  };
  renderLocalised(<LibraryImport {...props} />);
  return props;
}

const FILE = new File(["Title\nDune\n"], "export.csv", { type: "text/csv" });

describe("LibraryImport", () => {
  it("names the services somebody might be arriving from", () => {
    renderImport();
    expect(screen.getByText(/Goodreads, LibraryThing/)).toBeInTheDocument();
  });

  it("previews rather than importing when a file is chosen", async () => {
    const props = renderImport();

    await userEvent
      .setup()
      .upload(screen.getByLabelText("Choose a file"), FILE);

    expect(props.onChoose).toHaveBeenCalledWith(FILE);
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it("accepts a tab separated file, which is what LibraryThing exports", () => {
    renderImport();
    expect(screen.getByLabelText("Choose a file")).toHaveAttribute(
      "accept",
      expect.stringContaining(".tsv"),
    );
  });

  describe("once the file has been read", () => {
    it("says which column filled which field", () => {
      renderImport({ preview: preview() });
      expect(screen.getByText("Exclusive Shelf")).toBeInTheDocument();
    });

    it("names the fields it could not find", () => {
      // The silent failure this whole step exists to catch.
      renderImport({ preview: preview() });
      expect(screen.getByText(/Not found in this file/)).toHaveTextContent(
        "ISBN",
      );
    });

    it("shows the first rows as the parser read them", () => {
      renderImport({ preview: preview() });
      expect(screen.getByText(/Dune/)).toBeInTheDocument();
    });

    it("imports on confirmation", async () => {
      const props = renderImport({ preview: preview() });

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Import 10 books" }));

      expect(props.onConfirm).toHaveBeenCalledWith({
        createMissing: true,
        applyTags: false,
      });
    });

    it("leaves the tags behind unless asked", async () => {
      // A Goodreads export's tag column is its shelves, often hundreds of
      // them, and they would bury the curated list.
      const props = renderImport({ preview: preview() });
      const user = userEvent.setup();

      await user.click(
        screen.getByRole("checkbox", { name: /Bring the tags across/ }),
      );
      await user.click(screen.getByRole("button", { name: "Import 10 books" }));

      expect(props.onConfirm).toHaveBeenCalledWith({
        createMissing: true,
        applyTags: true,
      });
    });

    it("says how many tags this particular file would create", async () => {
      // A count of the file in hand beats "often hundreds", which is a fact
      // about Goodreads rather than about what is being imported.
      renderImport({ preview: preview({ distinct_tags: 142 }) });

      await userEvent
        .setup()
        .click(screen.getByRole("checkbox", { name: /Bring the tags across/ }));

      expect(
        screen.getByText(/This file has 142 different tags/),
      ).toBeInTheDocument();
    });

    it("can be abandoned without writing anything", async () => {
      const props = renderImport({ preview: preview() });

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Cancel" }));

      expect(props.onCancel).toHaveBeenCalledOnce();
      expect(props.onConfirm).not.toHaveBeenCalled();
    });

    it("names the reader for an ordinary book list too", () => {
      // Said only when it was not the ordinary reader, a wrong reading looked
      // exactly like the common case: the screen went quiet on the one
      // occasion somebody needed it to speak.
      renderImport({ preview: preview() });
      expect(
        screen.getByText("Read as a plain table, with the columns guessed."),
      ).toBeInTheDocument();
    });

    it("says which service's export it was read as, where that is not obvious", () => {
      renderImport({ preview: preview({ reader: "librarything" }) });
      expect(
        screen.getByText("Read as a LibraryThing export."),
      ).toBeInTheDocument();
    });

    it("says how many rows the file itself marks as deleted, and by which column", () => {
      // The one number on this screen about books that will not arrive, and
      // it is said before the write rather than after it. The column is named
      // because it is honoured wherever it appears rather than for one
      // service, so a member has to be able to find it in their own file.
      renderImport({
        preview: preview({ excluded: 3, exclusion_column: "HasBeenDeleted" }),
      });
      expect(
        screen.getByText(
          /3 rows are marked as deleted in this file's HasBeenDeleted column/,
        ),
      ).toBeInTheDocument();
    });

    it("says a count of zero rather than nothing when the file has such a column", () => {
      // Zero and "no such column" are different answers, and a line shown only
      // above zero says the same nothing for both.
      renderImport({
        preview: preview({ excluded: 0, exclusion_column: "HasBeenDeleted" }),
      });
      expect(
        screen.getByText(/0 rows are marked as deleted/),
      ).toBeInTheDocument();
    });

    it("says the file marks nothing as deleted when it has no such column", () => {
      renderImport({ preview: preview({ excluded: 0 }) });
      expect(
        screen.getByText(/No column in this file marks a row as deleted/),
      ).toBeInTheDocument();
    });

    it("will not import a file with no rows in it", () => {
      renderImport({ preview: preview({ total_rows: 0, rows: [] }) });
      expect(
        screen.getByRole("button", { name: "Import 0 books" }),
      ).toBeDisabled();
    });
  });

  describe("afterwards", () => {
    it("says how many rows the file itself marked as deleted", () => {
      // The preview is cleared the moment the import succeeds, so the number
      // has to be said again here, and in the past tense.
      renderImport({ result: outcome({ excluded: 3 }) });
      expect(
        screen.getByText(/3 rows were marked as deleted in this file/),
      ).toBeInTheDocument();
    });

    it("says nothing about deleted rows when the file marked none", () => {
      renderImport({ result: outcome() });
      expect(screen.queryByText(/marked as deleted/)).not.toBeInTheDocument();
    });

    it("reports what the import did", () => {
      renderImport({ result: outcome() });
      expect(screen.getByText(/10 rows read/)).toBeInTheDocument();
    });

    it("offers to review the books it added, which arrive unconfirmed", async () => {
      const props = renderImport({ result: outcome({ created: 2 }) });

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: /Review/i }));

      expect(props.onReviewUnconfirmed).toHaveBeenCalledOnce();
    });

    it("lists what it could not find", () => {
      renderImport({ result: outcome({ unmatched_titles: ["Solaris"] }) });
      expect(screen.getByText("Solaris")).toBeInTheDocument();
    });

    it("surfaces a refused file", () => {
      renderImport({ error: new Error("No title column was found.") });
      expect(screen.getByRole("alert")).toHaveTextContent("No title column");
    });
  });
});
