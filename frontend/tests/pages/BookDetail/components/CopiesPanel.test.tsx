/** Tests for src/pages/BookDetail/components/CopiesPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { BookOut } from "../../../../src/api/generated/model";
import CopiesPanel from "../../../../src/pages/BookDetail/components/CopiesPanel";
import { makeBook, makeLoan } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderPanel(
  book: BookOut,
  copies: BookOut[],
  listError: unknown = null,
) {
  const onAdd = vi.fn();
  renderLocalised(
    <CopiesPanel
      book={book}
      copies={copies}
      isAdding={false}
      error={null}
      listError={listError}
      onAdd={onAdd}
    />,
  );
  return onAdd;
}

describe("CopiesPanel", () => {
  it("offers to add a copy to a book that has only one", () => {
    const book = makeBook();
    renderPanel(book, [book]);

    expect(
      screen.getByRole("button", { name: "Add another copy" }),
    ).toBeInTheDocument();
  });

  it("lists nothing when there is only one copy", () => {
    const book = makeBook({ location: "Loft" });
    renderPanel(book, [book]);

    expect(screen.queryByText("Loft")).not.toBeInTheDocument();
  });

  it("names each copy by its shelf", () => {
    const book = makeBook({ location: "Living room" });
    const second = makeBook({ location: "Loft" });
    renderPanel(book, [book, second]);

    expect(screen.getByText(/Living room/)).toBeInTheDocument();
    expect(screen.getByText(/Loft/)).toBeInTheDocument();
  });

  it("marks the copy being looked at", () => {
    const book = makeBook();
    renderPanel(book, [book, makeBook()]);

    expect(screen.getByText("This one")).toBeInTheDocument();
  });

  it("links to the other copies and not to this one", () => {
    const book = makeBook();
    const second = makeBook();
    renderPanel(book, [book, second]);

    const links = screen.getAllByRole("link", { name: "Open" });
    expect(links).toHaveLength(1);
    expect(links[0]!).toHaveAttribute("href", `/book/${second.id}`);
  });

  it("says which copy is out on loan", () => {
    // The sentence the whole rows-versus-a-count decision was made for.
    const book = makeBook();
    const second = makeBook({ location: "Loft", active_loan: makeLoan() });
    renderPanel(book, [book, second]);

    expect(screen.getByText(/Out on loan/)).toBeInTheDocument();
  });

  it("counts the copies", () => {
    const book = makeBook();
    renderPanel(book, [book, makeBook(), makeBook()]);

    expect(screen.getByText("3 copies of this book")).toBeInTheDocument();
  });

  it("says so when the copies could not be read", () => {
    // Otherwise the panel is indistinguishable from a book that has one copy,
    // which is a wrong answer rather than a missing one.
    const book = makeBook();
    renderPanel(book, [], new Error("Network is down"));

    expect(screen.getByRole("alert")).toHaveTextContent("Network is down");
  });

  it("asks for another copy when pressed", async () => {
    const book = makeBook();
    const onAdd = renderPanel(book, [book]);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Add another copy" }));

    expect(onAdd).toHaveBeenCalled();
  });
});
