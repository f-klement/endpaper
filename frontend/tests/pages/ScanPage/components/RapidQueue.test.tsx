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
    keptForNow: 0,
    paceMinutes: 1,
    keptPaceMinutes: 1,
    isLookingUp: false,
    onLookUp: vi.fn(),
    onStopLookUp: vi.fn(),
    onChoose: vi.fn(),
    onKeepName: vi.fn(),
    onKeepAllForNow: vi.fn(),
    onLookUpKept: vi.fn(),
    onSplit: vi.fn(),
    ...overrides,
  };
  const { container, rerender } = renderLocalised(<RapidQueue {...props} />);
  return {
    ...props,
    container,
    /** Render again with some props changed, into the same mounted tree. */
    again: (next: Partial<Parameters<typeof RapidQueue>[0]>) =>
      rerender(<RapidQueue {...props} {...next} />),
  };
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

/**
 * One audiobook candidate, of several files.
 *
 * The shape `entryForGroup` builds: the book's own title as the label, the
 * files it claims carried on `group`, and the format the container answers.
 */
function grouped(names: readonly string[], title: string): ScannedEntry {
  return {
    key: `audio:file:${names[0]}:10:0:${names.length}`,
    label: title,
    isbn: "",
    format: BookFormat.audiobook,
    state: "derived",
    draft: { isbn: "", title, suggested_tag_ids: [], notFound: true },
    group: {
      by: "album",
      album: title,
      authors: [],
      title: null,
      files: names.map((name) => ({
        key: `file:${name}:10:0`,
        name,
        folders: [title],
        tags: null,
        whole: false,
      })),
    },
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
  it("says how many files an audiobook row was made of", () => {
    // **The confirm this ticket is about.** For every other format one file is
    // one book, so a row standing for twenty of them has to say so before the
    // batch runs, and nothing here is written until "Add all".
    renderQueue({
      entries: [grouped(["01.mp3", "02.mp3", "03.mp3"], "Robinson Crusoe")],
    });

    expect(
      screen.getByText("3 files, as one audiobook. Show them."),
    ).toBeInTheDocument();
  });

  it("lists the files that row claims", () => {
    renderQueue({ entries: [grouped(["01.mp3", "02.mp3"], "Dune")] });

    expect(screen.getByText("01.mp3")).toBeInTheDocument();
    expect(screen.getByText("02.mp3")).toBeInTheDocument();
  });

  it("offers to file them separately, naming the book it is about", () => {
    // The visible words are the same on every grouped row and the accessible
    // name is not, which is the convention the match rows already follow.
    renderQueue({ entries: [grouped(["01.mp3", "02.mp3"], "Dune")] });

    expect(
      screen.getByRole("button", {
        name: "Add the files of Dune as separate books instead",
      }),
    ).toBeInTheDocument();
  });

  it("splits the row the member pressed", async () => {
    const props = renderQueue({
      entries: [grouped(["01.mp3", "02.mp3"], "Dune")],
    });

    await userEvent.click(
      screen.getByRole("button", {
        name: "Add the files of Dune as separate books instead",
      }),
    );

    expect(props.onSplit).toHaveBeenCalledWith(props.entries[0]!.key);
  });

  it("says none of it for a row that is one file", () => {
    // One file is one book for every other format, and a row that says "1 file,
    // as one audiobook" is a screen explaining something that did not happen.
    renderQueue({ entries: [grouped(["Mort.m4b"], "Mort")] });

    expect(screen.queryByText(/as one audiobook/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /separate books/ }),
    ).not.toBeInTheDocument();
  });

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
      screen.getByRole("button", {
        name: "Keep this name and stop asking",
      }),
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

    await user.click(
      screen.getByRole("button", {
        name: "Keep this name and stop asking",
      }),
    );

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

  it("offers one press for every row still to decide", async () => {
    // 250 presses for a folder of 300 files that matched 250 is what this
    // replaces. The count beside it is the one the batch will leave.
    const user = userEvent.setup();
    const onKeepAllForNow = vi.fn();
    renderQueue({
      entries: [{ ...derived, state: "choosing", matches: [MATCH] }],
      deciding: 1,
      onKeepAllForNow,
    });

    await user.click(
      screen.getByRole("button", { name: "Keep those file names for now (1)" }),
    );

    expect(onKeepAllForNow).toHaveBeenCalledTimes(1);
  });

  it("says what the press costs before it is pressed", () => {
    // **Recoverability is the reason this control exists**, so the sentence
    // that says nothing is discarded, and the one that says a second pass may
    // be paid for, sit on the control rather than after the press.
    renderQueue({
      entries: [{ ...derived, state: "choosing", matches: [MATCH] }],
      deciding: 1,
    });

    expect(
      screen.getByText(
        "Nothing is discarded: those rows keep their file names and Add all takes them. Asking the catalogues again is offered afterwards, and a second pass may spend that budget again.",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer the press when nothing is being decided", () => {
    // Matched loosely, because the exact name carries the count: asserting the
    // absence of "(1)" would pass on a button offering to keep nothing.
    renderQueue({ entries: [derived] });

    expect(
      screen.queryByRole("button", { name: /Keep those file names for now/ }),
    ).not.toBeInTheDocument();
  });

  it("says how many rows are standing under their names after the press", () => {
    // **The acknowledgement the press gets**, in the place the press was: the
    // control unmounts when the last row is decided, and a control that
    // disappears says nothing to anybody.
    renderQueue({
      entries: [{ ...derived, answered: "records-for-now" as const }],
      keptForNow: 1,
    });

    expect(
      screen.getByText(
        "Kept under their file names for now (1). Add all takes them.",
      ),
    ).toBeInTheDocument();
  });

  it("mounts the announcement before there is anything to announce", () => {
    // **A live region inserted with its content already in it is the one that
    // is not spoken**, so the acknowledgement this was written for would never
    // reach the member who cannot see the queue. Asserted as the behaviour, one
    // node across the change, rather than as the attribute that is only what
    // the element is made of.
    //
    // Not observable here: the region is out of the flow while it is empty, so
    // the queue's own spacing does not open a gap for a paragraph with nothing
    // in it. This environment has no layout engine to measure that with.
    const { again, container } = renderQueue({ entries: [derived] });

    const region = container.querySelector('[aria-live="polite"]');
    expect(region).not.toBeNull();
    expect(region).toHaveTextContent("");
    expect(region).toHaveAttribute("aria-atomic", "true");

    again({ keptForNow: 2 });

    expect(container.querySelector('[aria-live="polite"]')).toBe(region);
    expect(region).toHaveTextContent(
      "Kept under their file names for now (2). Add all takes them.",
    );
  });

  it("offers a second pass over the names kept in bulk", async () => {
    const user = userEvent.setup();
    const onLookUpKept = vi.fn();
    renderQueue({
      entries: [{ ...derived, answered: "records-for-now" as const }],
      keptForNow: 2,
      keptPaceMinutes: 4,
      onLookUpKept,
    });

    await user.click(
      screen.getByRole("button", {
        name: "Ask the catalogues again about those names (2)",
      }),
    );

    expect(onLookUpKept).toHaveBeenCalledTimes(1);
  });

  it("says the names leave the browser on the second pass too", () => {
    // The disclosure belongs on every control that sends a name, and this one
    // sends the same names to the same catalogues as the first pass.
    renderQueue({
      entries: [{ ...derived, answered: "records-for-now" as const }],
      keptForNow: 2,
      keptPaceMinutes: 4,
    });

    expect(
      screen.getByText(/The same file names go to the same catalogues/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Roughly 4 min/)).toBeInTheDocument();
  });

  it("says a different thing on each of the two lookup presses", () => {
    // Both controls are on screen together after a run is stopped partway and
    // the rows it did reach are kept. One paragraph printed twice is read once,
    // and the half that goes is the half saying this press is a repeat.
    renderQueue({
      entries: [
        derived,
        {
          ...derived,
          key: "file:other.pdf:10:0",
          answered: "records-for-now" as const,
        },
      ],
      waiting: 1,
      keptForNow: 1,
    });

    expect(
      screen.getAllByText(/The file names, not the files, are sent/),
    ).toHaveLength(1);
    expect(
      screen.getAllByText(/The same file names go to the same catalogues/),
    ).toHaveLength(1);
  });

  it("offers no second pass while a run is going", () => {
    // One run at a time, and the stop above is the control that ends it.
    renderQueue({
      entries: [{ ...derived, answered: "records-for-now" as const }],
      keptForNow: 2,
      isLookingUp: true,
    });

    expect(
      screen.queryByRole("button", {
        name: /Ask the catalogues again about those names/,
      }),
    ).not.toBeInTheDocument();
  });

  it("offers no press while the queue is being added", () => {
    renderQueue({
      entries: [{ ...derived, state: "choosing", matches: [MATCH] }],
      deciding: 1,
      isAdding: true,
    });

    expect(
      screen.getByRole("button", { name: "Keep those file names for now (1)" }),
    ).toBeDisabled();
  });

  it("offers no press while a lookup is running", () => {
    // The other three controls here dim while a run is going, and a member
    // cannot tell which press the page will honour if a fourth stays live.
    renderQueue({
      entries: [{ ...derived, state: "choosing", matches: [MATCH] }],
      deciding: 1,
      isLookingUp: true,
    });

    expect(
      screen.getByRole("button", { name: /Keep those file names for now/ }),
    ).toBeDisabled();
  });

  it("counts only the rows still to decide on the press", () => {
    // **Three rows, one of them being decided**, because the count and the
    // queue agree at one row and disagree at three: a figure read off the queue
    // would offer to keep three names and clear one.
    renderQueue({
      entries: [
        { ...derived, state: "choosing", matches: [MATCH] },
        { ...derived, key: "file:b.pdf:10:0" },
        { ...derived, key: "file:c.pdf:10:0" },
      ],
      deciding: 1,
    });

    expect(
      screen.getByRole("button", { name: "Keep those file names for now (1)" }),
    ).toBeInTheDocument();
  });

  it("tells a member which kept rows can come back and which are answered", () => {
    // **The distinction the owner asked to be visible**, not only held in the
    // data: one of these rows is a member's answer about that book and the
    // other is a queue they cleared, and only the second is offered again.
    renderQueue({
      entries: [
        {
          ...derived,
          answered: "records" as const,
          reason: "Kept under its file name.",
        },
        {
          ...derived,
          key: "file:other.pdf:10:0",
          answered: "records-for-now" as const,
          reason:
            "Kept under its file name for now, and can be looked up again.",
        },
      ],
    });

    expect(screen.getByText(/Kept under its file name\./)).toBeInTheDocument();
    expect(screen.getByText(/can be looked up again/)).toBeInTheDocument();
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
