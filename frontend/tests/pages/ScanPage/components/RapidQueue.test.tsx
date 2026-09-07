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
    waiting: 0,
    deciding: 0,
    paceMinutes: 1,
    isLookingUp: false,
    onLookUp: vi.fn(),
    onStopLookUp: vi.fn(),
    onChoose: vi.fn(),
    onKeepName: vi.fn(),
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

/**
 * The rows the filename fallback puts in this queue.
 *
 * A derived entry is a book rather than a failure, so it is rendered as one:
 * the title it derived, in the same ink a found book gets, and a note saying
 * where the title came from.
 */
describe("RapidQueue and a book taken from its file name", () => {
  const MATCH = {
    google_books_id: "abc",
    title: "The Dispossessed",
    author: "Ursula K. Le Guin",
    year: 1974,
    isbn13: "9780060512750",
    suggested_tag_ids: [],
  };

  const derived: ScannedEntry = picked(
    {
      state: "derived",
      draft: {
        title: "The Dispossessed",
        isbn: "",
        suggested_tag_ids: [],
        notFound: true,
      },
      query: "The Dispossessed",
    },
    "The Dispossessed.pdf",
  );

  it("shows the title the name gave and says where it came from", () => {
    renderQueue({ entries: [derived] });

    expect(screen.getByText("The Dispossessed")).toBeInTheDocument();
    expect(screen.getByText(/From the file name/)).toBeInTheDocument();
  });

  it("says what the file itself could not say, beside it", () => {
    renderQueue({
      entries: [{ ...derived, reason: "Not an EPUB file." }],
    });

    expect(screen.getByText(/Not an EPUB file/)).toBeInTheDocument();
  });

  it("offers the lookup rather than running it, and says what it costs", () => {
    renderQueue({ entries: [derived], waiting: 1, paceMinutes: 3 });

    expect(
      screen.getByRole("button", { name: "Look up 1 by name" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Roughly 3 min/)).toBeInTheDocument();
  });

  it("offers nothing to look up when nothing is waiting", () => {
    renderQueue({ entries: [derived], waiting: 0 });

    expect(
      screen.queryByRole("button", { name: /Look up/ }),
    ).not.toBeInTheDocument();
  });

  it("offers a way out of a run that is already going", () => {
    // A run over three hundred files is minutes long, so it has to be
    // stoppable without discarding the queue.
    renderQueue({ entries: [derived], waiting: 1, isLookingUp: true });

    expect(
      screen.queryByRole("button", { name: /Look up/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Stop looking up" }),
    ).toBeInTheDocument();
  });

  it("holds the batch while a run is going", () => {
    // Adding halfway through would file the rows the run had not reached under
    // their file names.
    renderQueue({ entries: [derived], isLookingUp: true });

    expect(screen.getByRole("button", { name: "Add all" })).toBeDisabled();
  });

  it("says it is asking, per file", () => {
    renderQueue({ entries: [{ ...derived, state: "searching" }] });

    expect(screen.getByText("Asking the catalogues...")).toBeInTheDocument();
  });

  it("offers each record, for one file, to be taken or left", () => {
    const onChoose = vi.fn();
    const onKeepName = vi.fn();
    renderQueue({
      entries: [{ ...derived, state: "choosing", matches: [MATCH] }],
      onChoose,
      onKeepName,
    });

    expect(screen.getByText("Possible matches: 1")).toBeInTheDocument();
    expect(
      screen.getByText("The Dispossessed, Ursula K. Le Guin (1974)"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Use the record for The Dispossessed",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Keep the name" }),
    ).toBeInTheDocument();
  });

  it("names the record a member takes", async () => {
    const user = userEvent.setup();
    const onChoose = vi.fn();
    const entry = { ...derived, state: "choosing" as const, matches: [MATCH] };
    renderQueue({ entries: [entry], onChoose });

    await user.click(
      screen.getByRole("button", {
        name: "Use the record for The Dispossessed",
      }),
    );

    expect(onChoose).toHaveBeenCalledWith(entry.key, MATCH);
  });

  it("names the file whose records a member rejects", async () => {
    const user = userEvent.setup();
    const onKeepName = vi.fn();
    const entry = { ...derived, state: "choosing" as const, matches: [MATCH] };
    renderQueue({ entries: [entry], onKeepName });

    await user.click(screen.getByRole("button", { name: "Keep the name" }));

    expect(onKeepName).toHaveBeenCalledWith(entry.key);
  });

  it("says why a book stayed under its file name, once and not per row", () => {
    // Six of the eight sources a title search reaches refuse a record that says
    // it is electronic, so this is the ordinary outcome for a title that only
    // exists as a file. Said once a catalogue has actually answered nothing:
    // explaining beforehand would apologise for something that may not happen.
    renderQueue({
      entries: [
        {
          ...derived,
          answered: "nothing" as const,
          reason: "Not in the catalogues.",
        },
        {
          ...derived,
          key: "file:other.pdf:10:0",
          answered: "nothing" as const,
        },
      ],
    });

    expect(
      screen.getAllByText(/Most catalogues list printed books/),
    ).toHaveLength(1);
  });

  it("does not say it to a member who was offered records and refused", () => {
    // The catalogues answered, with records. Telling that member the catalogues
    // do not list ebooks describes something that did not happen.
    renderQueue({
      entries: [
        {
          ...derived,
          answered: "records" as const,
          reason: "Kept under its file name.",
        },
      ],
    });

    expect(
      screen.queryByText(/Most catalogues list printed books/),
    ).not.toBeInTheDocument();
  });

  it("says how many rows the batch is about to leave where they are", () => {
    // The cost of not filing an undecided row under its file name, named on
    // screen rather than left for somebody to notice afterwards.
    renderQueue({
      entries: [{ ...derived, state: "choosing", matches: [MATCH] }],
      deciding: 1,
    });

    expect(
      screen.getByText("1 still to decide. Add all leaves those in the queue."),
    ).toBeInTheDocument();
  });

  it("says nothing about deciding when nothing is being decided", () => {
    renderQueue({ entries: [derived] });

    expect(screen.queryByText(/still to decide/)).not.toBeInTheDocument();
  });

  it("says nothing about ebooks before a catalogue has answered", () => {
    renderQueue({ entries: [derived] });

    expect(
      screen.queryByText(/Most catalogues list printed books/),
    ).not.toBeInTheDocument();
  });
});
