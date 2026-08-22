/** Tests for src/pages/BookDetail/components/ProgressPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  BookFormat,
  type BookOut,
  type ProgressOut,
} from "../../../../src/api/generated/model";
import ProgressPanel, {
  defaultUnit,
} from "../../../../src/pages/BookDetail/components/ProgressPanel";
import { makeBook, makeProgress } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderPanel(book: Partial<BookOut> = {}, entries: ProgressOut[] = []) {
  const onRecord = vi.fn();
  const onRemove = vi.fn();
  renderLocalised(
    <ProgressPanel
      book={makeBook(book)}
      entries={entries}
      isRecording={false}
      onRecord={onRecord}
      onRemove={onRemove}
    />,
  );
  return { onRecord, onRemove };
}

describe("defaultUnit", () => {
  it("offers pages when the book has a page count", () => {
    expect(defaultUnit(makeBook({ page_count: 412 }))).toBe("page");
  });

  it("offers a percentage when no page count is known", () => {
    // Asking for a page number the reader cannot check against anything is
    // asking for a number that means nothing.
    expect(defaultUnit(makeBook({ page_count: null }))).toBe("percent");
  });

  it("offers a percentage for an audiobook that carries a page count", () => {
    // The print edition's page count is not a position anybody listening can
    // report.
    expect(
      defaultUnit(makeBook({ page_count: 412, format: BookFormat.audiobook })),
    ).toBe("percent");
  });
});

describe("ProgressPanel", () => {
  it("says so when nothing has been recorded", () => {
    renderPanel();
    expect(screen.getByText("Nothing recorded yet.")).toBeInTheDocument();
  });

  it("shows the page against the page count", () => {
    renderPanel({ my_progress_page: 64, page_count: 412 });
    expect(screen.getByText("Page 64 of 412")).toBeInTheDocument();
  });

  it("shows the page alone when no page count is known", () => {
    renderPanel({ my_progress_page: 64, page_count: null });
    expect(screen.getByText("Page 64")).toBeInTheDocument();
  });

  it("draws a bar at the derived percentage", () => {
    renderPanel({
      my_progress_page: 64,
      my_progress_percent: 16,
      page_count: 412,
    });
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "16",
    );
  });

  it("draws no bar when nothing can be derived", () => {
    // A page with no page count. The alternative is a bar at a percentage
    // nobody computed.
    renderPanel({ my_progress_page: 64, my_progress_percent: null });
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("records a page", async () => {
    const user = userEvent.setup();
    const { onRecord } = renderPanel({ page_count: 412 });

    await user.type(screen.getByRole("spinbutton", { name: "Page" }), "120");
    await user.click(screen.getByRole("button", { name: "Record progress" }));

    expect(onRecord).toHaveBeenCalledWith({ page: 120 });
  });

  it("records a percentage when that unit is chosen", async () => {
    const user = userEvent.setup();
    const { onRecord } = renderPanel({ page_count: 412 });

    await user.click(screen.getByRole("button", { name: "Percent" }));
    await user.type(screen.getByRole("spinbutton", { name: "Percent" }), "40");
    await user.click(screen.getByRole("button", { name: "Record progress" }));

    expect(onRecord).toHaveBeenCalledWith({ percent: 40 });
  });

  it("never sends both units at once", async () => {
    // The API accepts exactly one, and the CHECK constraint behind it enforces
    // the same. The union is what stops the both-at-once request being
    // expressible at all.
    const user = userEvent.setup();
    const { onRecord } = renderPanel({ page_count: 412 });

    await user.type(screen.getByRole("spinbutton", { name: "Page" }), "120");
    await user.click(screen.getByRole("button", { name: "Record progress" }));

    expect(onRecord).toHaveBeenCalledTimes(1);
    expect(onRecord.mock.calls[0]![0]).not.toHaveProperty("percent");
  });

  it("carries the length of the sitting when one is given", async () => {
    const user = userEvent.setup();
    const { onRecord } = renderPanel({ page_count: 412 });

    await user.type(screen.getByRole("spinbutton", { name: "Page" }), "120");
    await user.type(
      screen.getByRole("spinbutton", { name: "Minutes read" }),
      "45",
    );
    await user.click(screen.getByRole("button", { name: "Record progress" }));

    expect(onRecord).toHaveBeenCalledWith({ page: 120, minutes: 45 });
  });

  it("cannot be submitted empty", () => {
    renderPanel({ page_count: 412 });
    expect(
      screen.getByRole("button", { name: "Record progress" }),
    ).toBeDisabled();
  });

  it("lists the history", () => {
    renderPanel({ page_count: 412 }, [
      makeProgress({ page: 120, minutes: 45 }),
      makeProgress({ page: 64 }),
    ]);

    expect(screen.getByText(/Page 120/)).toBeInTheDocument();
    expect(screen.getByText(/45 min/)).toBeInTheDocument();
    expect(screen.getByText(/Page 64/)).toBeInTheDocument();
  });

  it("removes one entry", async () => {
    const user = userEvent.setup();
    const entry = makeProgress({ page: 64 });
    const { onRemove } = renderPanel({ page_count: 412 }, [entry]);

    await user.click(screen.getByRole("button", { name: "Remove this entry" }));

    expect(onRemove).toHaveBeenCalledWith(entry.id);
  });
});
