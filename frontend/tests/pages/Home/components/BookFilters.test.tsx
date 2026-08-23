/** Tests for src/pages/Home/components/BookFilters.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_FILTERS } from "../../../../src/pages/Home/types";
import BookFilters from "../../../../src/pages/Home/components/BookFilters";
import { makeCollection, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

function renderFilters(overrides: Record<string, unknown> = {}) {
  const props = {
    filters: DEFAULT_FILTERS,
    tags: [],
    showTagPanel: false,
    onToggleTagPanel: vi.fn(),
    onStatusChange: vi.fn(),
    onOwnershipChange: vi.fn(),
    onLocationChange: vi.fn(),
    onCollectionChange: vi.fn(),
    onFormatChange: vi.fn(),
    onLendingChange: vi.fn(),
    onDiscussChange: vi.fn(),
    onSeriesClear: vi.fn(),
    locations: [],
    collections: [],
    onSortChange: vi.fn(),
    onToggleTag: vi.fn(),
    onClearTags: vi.fn(),
    view: "grid" as const,
    onViewChange: vi.fn(),
    ...overrides,
  };
  renderLocalised(<BookFilters {...props} />);
  return props;
}

describe("the collection filter", () => {
  it("is absent until the household has divided its shelf", () => {
    renderFilters();

    expect(screen.queryByLabelText("Collection")).not.toBeInTheDocument();
  });

  it("offers each collection with the count the caller can see", () => {
    renderFilters({
      collections: [makeCollection({ id: 3, name: "Ebooks", book_count: 12 })],
    });

    expect(screen.getByRole("option", { name: "Ebooks (12)" })).toBeInTheDocument();
  });

  it("offers the unfiled books last, as their own answer", () => {
    renderFilters({ collections: [makeCollection({ id: 3, name: "Ebooks" })] });

    const options = within(screen.getByLabelText("Collection")).getAllByRole(
      "option",
    );
    expect(options.map((option) => option.getAttribute("value"))).toEqual([
      "",
      "3",
      "unfiled",
    ]);
  });

  it("reports a chosen collection as a number", async () => {
    const props = renderFilters({
      collections: [makeCollection({ id: 3, name: "Ebooks" })],
    });

    await userEvent.selectOptions(screen.getByLabelText("Collection"), "3");

    expect(props.onCollectionChange).toHaveBeenCalledWith(3);
  });

  it("reports the unfiled option as a word, not an id", async () => {
    const props = renderFilters({
      collections: [makeCollection({ id: 3, name: "Ebooks" })],
    });

    await userEvent.selectOptions(screen.getByLabelText("Collection"), "unfiled");

    expect(props.onCollectionChange).toHaveBeenCalledWith("unfiled");
  });

  it("stays on screen when the list empties under an active filter", () => {
    // An admin deleting the collection somebody else is browsing. The id stays
    // in filter state and keeps being sent, so a picker that hid itself would
    // leave an empty grid with no control to clear it. It is the same shape as
    // a `?collection=4` deep link with the list still in flight, which is why
    // the fix draws the picker rather than clearing an id the list lacks.
    renderFilters({
      collections: [],
      filters: { ...DEFAULT_FILTERS, collection: 4 },
    });

    expect(screen.getByLabelText("Collection")).toBeInTheDocument();
  });

  it("can clear a filter whose collection no longer exists", async () => {
    const props = renderFilters({
      collections: [],
      filters: { ...DEFAULT_FILTERS, collection: 4 },
    });

    await userEvent.selectOptions(screen.getByLabelText("Collection"), "");

    expect(props.onCollectionChange).toHaveBeenCalledWith(null);
  });
});
