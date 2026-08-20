/** Tests for src/pages/ScanPage/components/RapidQueue.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import RapidQueue from "../../../../src/pages/ScanPage/components/RapidQueue";
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

const found: ScannedEntry = {
  isbn: "9780441013593",
  state: "found",
  draft: { isbn: "9780441013593", title: "Dune", suggested_tag_ids: [] },
};

describe("RapidQueue", () => {
  it("says when nothing has been scanned", () => {
    renderQueue();
    expect(screen.getByText("Nothing scanned yet")).toBeInTheDocument();
  });

  it("counts what is queued", () => {
    renderQueue({ entries: [found] });
    expect(screen.getByText("1 scanned")).toBeInTheDocument();
  });

  it("names a book once it is looked up", () => {
    renderQueue({ entries: [found] });
    expect(screen.getByText("Dune")).toBeInTheDocument();
  });

  it("shows a lookup still in flight", () => {
    renderQueue({
      entries: [{ isbn: "9780441013593", state: "looking-up", draft: null }],
    });
    expect(screen.getByText("Looking up...")).toBeInTheDocument();
  });

  it("keeps a book neither source knew, visibly", () => {
    // It is still a book on the shelf. Dropping it silently is how a catalogue
    // ends up quietly incomplete.
    renderQueue({
      entries: [{ isbn: "9780441013593", state: "not-found", draft: null }],
    });
    expect(screen.getByText(/Not found/)).toBeInTheDocument();
  });

  it("drops one entry", async () => {
    const props = renderQueue({ entries: [found] });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Remove .* from the queue/ }));

    expect(props.onRemove).toHaveBeenCalledWith(found.isbn);
  });

  it("adds the batch", async () => {
    const props = renderQueue({ entries: [found] });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Add all" }));

    expect(props.onAddAll).toHaveBeenCalledOnce();
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
        {
          isbn: "9780441013593",
          state: "failed",
          draft: { isbn: "9780441013593", title: "Dune", suggested_tag_ids: [] },
          reason: "Book with this ISBN already in catalog",
        },
      ],
      result: { added: 12, failed: 1 },
    });

    expect(screen.getByText(/Dune/)).toBeInTheDocument();
    expect(screen.getByText(/already in catalog/)).toBeInTheDocument();
  });

  it("keeps the banner above whatever is left, rather than replacing it", () => {
    renderQueue({
      entries: [
        {
          isbn: "9780441013593",
          state: "failed",
          draft: null,
          reason: "Nope",
        },
      ],
      result: { added: 1, failed: 1 },
    });

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("9780441013593")).toBeInTheDocument();
  });
});
