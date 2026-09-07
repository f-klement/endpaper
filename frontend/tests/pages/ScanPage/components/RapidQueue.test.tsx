/** Tests for src/pages/ScanPage/components/RapidQueue.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import RapidQueue from "../../../../src/pages/ScanPage/components/RapidQueue";
import { BookFormat } from "../../../../src/api/generated/model";
import type { ScannedEntry } from "../../../../src/pages/ScanPage/hooks";
import { renderLocalised } from "../../../utils";

function renderQueue(
  overrides: Partial<Parameters<typeof RapidQueue>[0]> = {},
) {
  const props = {
    entries: [] as ScannedEntry[],
    isAdding: false,
    result: null,
    onRemove: vi.fn(),
    onAddAll: vi.fn(),
    onDiscard: vi.fn(),
    ...overrides,
  };
  renderLocalised(<RapidQueue {...props} />);
  return props;
}

/**
 * A scanned entry, keyed and labelled the way `capture` keys and labels one.
 *
 * The queue identifies an entry by `key` rather than by ISBN, because a picked
 * file usually has no ISBN. A scan's key and label are both its ISBN, and its
 * format is blank because a barcode answers nothing about one, so writing all
 * three out at every fixture would say the same thing four times.
 */
function scanned(
  entry: Omit<ScannedEntry, "key" | "label" | "format">,
): ScannedEntry {
  return {
    ...entry,
    key: `isbn:${entry.isbn}`,
    label: entry.isbn,
    format: "",
  };
}

/** A picked file's entry, keyed and labelled the way `pickFiles` does. */
function picked(
  entry: Omit<ScannedEntry, "key" | "label" | "format" | "isbn">,
  name: string,
): ScannedEntry {
  return {
    ...entry,
    key: `file:${name}:10:0`,
    label: name,
    isbn: "",
    format: BookFormat.ebook,
  };
}

const found: ScannedEntry = scanned({
  isbn: "9780441013593",
  state: "found",
  draft: { isbn: "9780441013593", title: "Dune", suggested_tag_ids: [] },
});

describe("RapidQueue", () => {
  it("says when nothing has been scanned", () => {
    renderQueue();
    expect(screen.getByText("Nothing scanned yet")).toBeInTheDocument();
  });

  it("counts what is queued", () => {
    renderQueue({ entries: [found] });
    expect(screen.getByText("1 in the queue")).toBeInTheDocument();
  });

  it("names a book once it is looked up", () => {
    renderQueue({ entries: [found] });
    expect(screen.getByText("Dune")).toBeInTheDocument();
  });

  it("shows a lookup still in flight", () => {
    renderQueue({
      entries: [
        scanned({ isbn: "9780441013593", state: "looking-up", draft: null }),
      ],
    });
    expect(screen.getByText("Looking up...")).toBeInTheDocument();
  });

  it("keeps a book neither source knew, visibly", () => {
    // It is still a book on the shelf. Dropping it silently is how a catalogue
    // ends up quietly incomplete.
    renderQueue({
      entries: [
        scanned({ isbn: "9780441013593", state: "not-found", draft: null }),
      ],
    });
    expect(screen.getByText(/Not found/)).toBeInTheDocument();
  });

  it("drops one entry", async () => {
    const props = renderQueue({ entries: [found] });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Remove .* from the queue/ }));

    expect(props.onRemove).toHaveBeenCalledWith(found.key);
  });

  it("adds the batch", async () => {
    const props = renderQueue({ entries: [found] });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Add all" }));

    expect(props.onAddAll).toHaveBeenCalledOnce();
  });

  it("shows a file still being read", () => {
    renderQueue({
      entries: [picked({ state: "reading", draft: null }, "dune.epub")],
    });
    expect(screen.getByText("dune.epub is being read...")).toBeInTheDocument();
  });

  it("names a failed file by its filename, since it has no ISBN", () => {
    // The failed arm used to fall back to the ISBN, which for a picked file is
    // empty: the row would have said nothing at all about which file it was.
    renderQueue({
      entries: [
        picked(
          { state: "failed", draft: null, reason: "Not an EPUB file." },
          "broken.epub",
        ),
      ],
    });
    expect(screen.getByText(/broken.epub/)).toBeInTheDocument();
  });

  it("names a removal by the label rather than by the ISBN", () => {
    renderQueue({
      entries: [picked({ state: "reading", draft: null }, "dune.epub")],
    });
    expect(
      screen.getByRole("button", { name: "Remove dune.epub from the queue" }),
    ).toBeInTheDocument();
  });

  it("disables the actions while adding", () => {
    renderQueue({ entries: [found], isAdding: true });
    expect(screen.getByRole("button", { name: "Adding..." })).toBeDisabled();
  });

  it("reports the outcome, failures included", () => {
    renderQueue({ result: { added: 12, failed: 2 } });
    expect(screen.getByRole("status")).toHaveTextContent("12 added");
  });

  it("names the books that could not be added, and why", () => {
    // "6 could not be added" after a shelf of thirty is unrecoverable:
    // nothing says which six, and the queue that knew has been cleared.
    renderQueue({
      entries: [
        scanned({
          isbn: "9780441013593",
          state: "failed",
          draft: {
            isbn: "9780441013593",
            title: "Dune",
            suggested_tag_ids: [],
          },
          reason: "Book with this ISBN already in catalog",
        }),
      ],
      result: { added: 12, failed: 1 },
    });

    expect(screen.getByText(/Dune/)).toBeInTheDocument();
    expect(screen.getByText(/already in catalog/)).toBeInTheDocument();
  });

  it("keeps the banner above whatever is left, rather than replacing it", () => {
    renderQueue({
      entries: [
        scanned({
          isbn: "9780441013593",
          state: "failed",
          draft: null,
          reason: "Nope",
        }),
      ],
      result: { added: 1, failed: 1 },
    });

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("9780441013593")).toBeInTheDocument();
  });
});
