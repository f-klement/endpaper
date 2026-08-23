/** Tests for src/pages/CollectionsPage/components/CollectionCard.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CollectionCard from "../../../../src/pages/CollectionsPage/components/CollectionCard";
import { makeCollection, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

function renderCard(overrides = {}) {
  const props = {
    collection: makeCollection({ id: 3, name: "Ebooks", book_count: 12 }),
    isBusy: false,
    onRename: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  renderLocalised(<CollectionCard {...props} />);
  return props;
}

describe("CollectionCard", () => {
  it("links into the library filtered to this collection", () => {
    renderCard();

    expect(
      screen.getByRole("link", { name: "Show these books" }),
    ).toHaveAttribute("href", "/?collection=3");
  });

  it("sends the new name once", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("  Digital  ");
    const props = renderCard();

    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(props.onRename).toHaveBeenCalledWith(props.collection, "Digital");
  });

  it("does nothing when the rename is cancelled", async () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    const props = renderCard();

    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(props.onRename).not.toHaveBeenCalled();
  });

  it("does nothing when the rename is left empty", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("   ");
    const props = renderCard();

    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(props.onRename).not.toHaveBeenCalled();
  });

  it("says how many books a delete would unfile", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const props = renderCard();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(confirm.mock.calls[0]?.[0]).toContain("12 books");
    expect(props.onDelete).not.toHaveBeenCalled();
  });
});
