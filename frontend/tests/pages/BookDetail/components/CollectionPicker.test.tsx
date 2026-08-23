/** Tests for src/pages/BookDetail/components/CollectionPicker.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CollectionPicker from "../../../../src/pages/BookDetail/components/CollectionPicker";
import { makeBook, makeCollection, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

function renderPicker(overrides = {}) {
  const props = {
    book: makeBook({ collection_id: null }),
    collections: [
      makeCollection({ id: 3, name: "Ebooks" }),
      makeCollection({ id: 4, name: "Sold" }),
    ],
    isSaving: false,
    onChange: vi.fn(),
    onCreate: vi.fn(),
    ...overrides,
  };
  renderLocalised(<CollectionPicker {...props} />);
  return props;
}

describe("CollectionPicker", () => {
  it("shows an unfiled book as being in none", () => {
    renderPicker();

    expect(screen.getByLabelText("Collection")).toHaveValue("");
  });

  it("shows the collection a book is filed in", () => {
    renderPicker({ book: makeBook({ collection_id: 4 }) });

    expect(screen.getByLabelText("Collection")).toHaveValue("4");
  });

  it("files the book when one is chosen", async () => {
    const props = renderPicker();

    await userEvent.selectOptions(screen.getByLabelText("Collection"), "3");

    expect(props.onChange).toHaveBeenCalledWith(3);
  });

  it("sends null when the book is taken out of every collection", async () => {
    const props = renderPicker({ book: makeBook({ collection_id: 3 }) });

    await userEvent.selectOptions(screen.getByLabelText("Collection"), "");

    expect(props.onChange).toHaveBeenCalledWith(null);
  });

  it("creates a collection from a typed name", async () => {
    const props = renderPicker();

    await userEvent.type(screen.getByLabelText("Name"), "Loft box");
    await userEvent.click(
      screen.getByRole("button", { name: "Add collection" }),
    );

    expect(props.onCreate).toHaveBeenCalledWith("Loft box");
  });

  it("will not create one from an empty name", async () => {
    renderPicker();

    expect(
      screen.getByRole("button", { name: "Add collection" }),
    ).toBeDisabled();
  });

  it("says filing a book changes nothing about who can see it", () => {
    renderPicker();

    expect(
      screen.getByText(/never hides them/i),
    ).toBeInTheDocument();
  });
});
