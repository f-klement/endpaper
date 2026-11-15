/**
 * Tests for src/pages/BookDetail/components/HighlightList.tsx.
 *
 * The page's own tests drive sharing and deleting through the API; these pin
 * what each row draws and which control it offers in which state.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Locale, type HighlightOut } from "../../../../src/api/generated/model";
import { shortMonthDate } from "../../../../src/lib/date";
import HighlightList from "../../../../src/pages/BookDetail/components/HighlightList";
import { makeHighlight, makeUser } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderList(
  highlights: HighlightOut[],
  pendingIds: ReadonlySet<number> = new Set(),
) {
  const onSetShared = vi.fn<(highlightId: number, isShared: boolean) => void>();
  const onDelete = vi.fn<(highlightId: number) => void>();
  const view = renderLocalised(
    <HighlightList
      highlights={highlights}
      currentUser={makeUser({ id: 1 })}
      pendingIds={pendingIds}
      onSetShared={onSetShared}
      onDelete={onDelete}
    />,
  );
  return { ...view, onSetShared, onDelete };
}

describe("HighlightList", () => {
  it("draws nothing when there are no highlights", () => {
    const { container } = renderList([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the chapter, the page, the owner and the device's day", () => {
    renderList([
      makeHighlight({
        user_id: 2,
        author: makeUser({ id: 2, username: "ana" }),
        is_shared: true,
        chapter: "Gom Jabbar",
        page: 12,
        highlighted_at: "2026-03-01 22:15:09",
      }),
    ]);

    expect(
      screen.getByText(
        `Gom Jabbar · p. 12 · ana · ${shortMonthDate("2026-03-01", Locale.en)}`,
      ),
    ).toBeInTheDocument();
  });

  it("leaves the reader's own name and an absent day off the line", () => {
    renderList([
      makeHighlight({
        user_id: 1,
        chapter: "Gom Jabbar",
        highlighted_at: null,
      }),
    ]);
    expect(screen.getByText("Gom Jabbar")).toBeInTheDocument();
  });

  it("shows the remark under the passage", () => {
    renderList([makeHighlight({ note: "Litany" })]);
    expect(screen.getByText("Litany")).toBeInTheDocument();
  });

  it("offers to share a private passage of the reader's own", async () => {
    const mine = makeHighlight({ user_id: 1, is_shared: false });
    const { onSetShared } = renderList([mine]);

    expect(screen.getByText("Only visible to me")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    expect(onSetShared).toHaveBeenCalledWith(mine.id, true);
  });

  it("offers to stop sharing a shared passage of the reader's own", async () => {
    const mine = makeHighlight({ user_id: 1, is_shared: true });
    const { onSetShared } = renderList([mine]);

    expect(screen.getByText("Shared")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop sharing" }));

    expect(onSetShared).toHaveBeenCalledWith(mine.id, false);
  });

  it("says a passage over the limit is too long rather than offering a share", () => {
    renderList([makeHighlight({ user_id: 1, text: "a".repeat(2001) })]);

    expect(screen.getByText("Too long to share")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Share" }),
    ).not.toBeInTheDocument();
  });

  it("offers to share a passage of exactly the limit, counted in code points", () => {
    // Each emoji is one code point and two UTF-16 units, so a count by
    // `length` would call this 4000 and refuse it.
    renderList([makeHighlight({ user_id: 1, text: "\u{1F4D6}".repeat(2000) })]);

    expect(screen.getByRole("button", { name: "Share" })).toBeInTheDocument();
    expect(screen.queryByText("Too long to share")).not.toBeInTheDocument();
  });

  it("disables every control on a passage with a write in flight", () => {
    const mine = makeHighlight({ user_id: 1 });
    renderList([mine], new Set([mine.id]));

    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("deletes only once the reader confirms", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const mine = makeHighlight({ user_id: 1 });
    const { onDelete } = renderList([mine]);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith(mine.id);
  });
});
