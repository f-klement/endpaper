/** Tests for src/pages/AuthorsPage/components/AuthorCard. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AuthorCard from "../../../../src/pages/AuthorsPage/components/AuthorCard";
import { renderLocalised } from "../../../utils";

function author(overrides: Record<string, unknown> = {}) {
  return {
    key: "frank herbert",
    name: "Frank Herbert",
    book_count: 3,
    spellings: ["Frank Herbert"],
    merged: [],
    ...overrides,
  };
}

describe("AuthorCard", () => {
  it("links by the name, which is what the filter chip then shows", () => {
    // The API takes the name or the key and resolves a folded spelling either
    // way, so neither is more durable. The name is what a reader recognises in
    // the chip: linking the key made the same filter describe itself as
    // "Author: frank herbert" here and "Author: Frank Herbert" from a book.
    renderLocalised(
      <AuthorCard
        author={author()}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Show these books" }),
    ).toHaveAttribute("href", "/?author=Frank%20Herbert");
  });

  it("shows the other spellings, because they are why a merge is wanted", () => {
    renderLocalised(
      <AuthorCard
        author={author({ spellings: ["Frank Herbert", "frank herbert"] })}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(screen.getByText("Also spelled: frank herbert")).toBeInTheDocument();
  });

  it("offers an undo per folded spelling, not one for the author", async () => {
    const onUndo = vi.fn();
    renderLocalised(
      <AuthorCard
        author={author({
          merged: [
            { alias_id: 4, spelling: "F. Herbert" },
            { alias_id: 5, spelling: "Herbert, Frank" },
          ],
        })}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={onUndo}
      />,
    );

    const undos = screen.getAllByRole("button", { name: "Undo this merge" });
    expect(undos).toHaveLength(2);
    await userEvent.setup().click(undos[1]!);

    expect(onUndo).toHaveBeenCalledWith(5);
  });

  it("does not repeat a folded spelling as an ordinary one", () => {
    renderLocalised(
      <AuthorCard
        author={author({
          spellings: ["Frank Herbert", "F. Herbert"],
          merged: [{ alias_id: 4, spelling: "F. Herbert" }],
        })}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Also spelled/)).not.toBeInTheDocument();
    expect(screen.getByText("Folded in: F. Herbert")).toBeInTheDocument();
  });
});
