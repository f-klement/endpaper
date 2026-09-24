/** Tests for src/pages/Home/components/BookFilters.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ClassificationScheme,
  type ClassificationFacets,
} from "../../../../src/api/generated/model";
import { DEFAULT_FILTERS } from "../../../../src/pages/Home/types";
import BookFilters from "../../../../src/pages/Home/components/BookFilters";
import { makeCollection, makeTag, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

const FACETS: ClassificationFacets = {
  divisions: [{ division: "150", label: "Psychology", book_count: 3 }],
  headings: [
    {
      scheme: ClassificationScheme.lcsh,
      number: "Stress management",
      label: null,
      book_count: 2,
    },
  ],
};

function renderFilters(overrides: Record<string, unknown> = {}) {
  const props = {
    filters: DEFAULT_FILTERS,
    tags: [],
    showTagPanel: false,
    onToggleTagPanel: vi.fn(),
    onFilterChange: vi.fn(),
    locations: [],
    collections: [],
    classifications: undefined,
    showClassificationPanel: false,
    onToggleClassificationPanel: vi.fn(),
    view: {
      value: "grid" as const,
      set: vi.fn(),
      setFromScope: vi.fn(),
      canSet: true,
    },
    ...overrides,
  };
  renderLocalised(<BookFilters {...props} />);
  return props;
}

describe("the collection filter", () => {
  it("is absent until the library has divided its shelf", () => {
    renderFilters();

    expect(screen.queryByLabelText("Collection")).not.toBeInTheDocument();
  });

  it("offers each collection with the count the caller can see", () => {
    renderFilters({
      collections: [makeCollection({ id: 3, name: "Ebooks", book_count: 12 })],
    });

    expect(
      screen.getByRole("option", { name: "Ebooks (12)" }),
    ).toBeInTheDocument();
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

    expect(props.onFilterChange).toHaveBeenCalledWith({ collection: 3 });
  });

  it("reports the unfiled option as a word, not an id", async () => {
    const props = renderFilters({
      collections: [makeCollection({ id: 3, name: "Ebooks" })],
    });

    await userEvent.selectOptions(
      screen.getByLabelText("Collection"),
      "unfiled",
    );

    expect(props.onFilterChange).toHaveBeenCalledWith({
      collection: "unfiled",
    });
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

    expect(props.onFilterChange).toHaveBeenCalledWith({ collection: null });
  });
});

describe("the author chip", () => {
  it("is absent until a link filtered by one", () => {
    renderFilters();

    expect(screen.queryByText(/^Author:/)).not.toBeInTheDocument();
  });

  it("names the author and can be taken off", async () => {
    const props = renderFilters({
      filters: { ...DEFAULT_FILTERS, author: "ursula k le guin" },
    });

    expect(screen.getByText("Author: ursula k le guin")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByLabelText("Clear selection"));

    expect(props.onFilterChange).toHaveBeenCalledWith({ author: null });
  });
});

describe("the tag panel", () => {
  it("reports a picked tag as a patch on the tag list", async () => {
    // Selected rather than clicked open: a category holding a selection opens
    // itself, which is how `TagPicker`'s own tests reach a chip. So the click
    // here is the one that takes a tag off again.
    const tag = makeTag({ name: "Fantasy" });
    const props = renderFilters({
      tags: [tag],
      showTagPanel: true,
      filters: { ...DEFAULT_FILTERS, tagIds: [tag.id] },
    });

    await userEvent.click(screen.getByRole("button", { name: "Fantasy" }));

    expect(props.onFilterChange).toHaveBeenCalledWith({ tagIds: [] });
  });

  it("clears every tag through the same one callback", async () => {
    const tag = makeTag({ name: "Fantasy" });
    const props = renderFilters({
      tags: [tag],
      filters: { ...DEFAULT_FILTERS, tagIds: [tag.id] },
    });

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(props.onFilterChange).toHaveBeenCalledWith({ tagIds: [] });
  });
});

describe("the classification panel", () => {
  it("puts a division in the divisions", async () => {
    const props = renderFilters({
      classifications: FACETS,
      showClassificationPanel: true,
    });

    await userEvent.click(screen.getByRole("button", { name: /150/ }));

    expect(props.onFilterChange).toHaveBeenCalledWith({
      ddcDivisions: ["150"],
    });
  });

  it("puts a heading in the headings, as the wire spelling", async () => {
    // The two facets take different operators and are two fields, so a patch
    // naming the other one is a filter that narrows the wrong way and still
    // answers 200.
    const props = renderFilters({
      classifications: FACETS,
      showClassificationPanel: true,
    });

    await userEvent.click(
      screen.getByRole("button", { name: /Stress management/ }),
    );

    expect(props.onFilterChange).toHaveBeenCalledWith({
      headings: ["lcsh:Stress management"],
    });
  });

  it("clears both facets at once, because the badge counts both", async () => {
    const props = renderFilters({
      classifications: FACETS,
      filters: {
        ...DEFAULT_FILTERS,
        headings: ["lcsh:Stress management"],
        ddcDivisions: ["150"],
      },
    });

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(props.onFilterChange).toHaveBeenCalledWith({
      headings: [],
      ddcDivisions: [],
    });
  });
});

describe("the view group", () => {
  it("offers every view while the mode is known", () => {
    renderFilters();

    for (const name of ["Covers", "List", "Table"]) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
  });

  it("disables the group until the mode is known", async () => {
    // A pick made in that window would be filed under the wrong mode's key,
    // so the hook refuses it. Disabled rather than inert, because a button
    // that answers a press with nothing teaches the reader the page lies.
    const props = renderFilters({
      view: {
        value: "grid",
        set: vi.fn(),
        setFromScope: vi.fn(),
        canSet: false,
      },
    });

    const table = screen.getByRole("button", { name: "Table" });
    expect(table).toBeDisabled();
    await userEvent.setup().click(table);
    expect(props.view.set).not.toHaveBeenCalled();
  });

  it("no pressed control carries an opacity class", () => {
    // The same rule as `ColumnPicker`'s, and this panel had nothing to trip at
    // all until this test: a pressed button is `on-accent` on `accent-fill`,
    // the pair `palettes.test.ts` floors at 4.5:1, and `opacity` composites a
    // button's fill and its text together, halving it to 2.83:1 light and
    // 3.52:1 dark. The unpressed arm is exempt at 2.15:1, which is where every
    // other `disabled:opacity-50` control in this app already sits and what
    // `index.css` records a disabled control as not owing.
    //
    // **Read off `aria-pressed` across the whole panel**, not off the three
    // view buttons by name. A name list is what let the `ColumnPicker` version
    // of this guard cover one element while a dim on every other chosen chip
    // passed clean. This covers the status pills and the ownership pills too,
    // which carry the same pair, and a fourth view inherits it.
    //
    // Rendered disabled because that is the state the class exists for. The
    // class list does not depend on it, so either state would read the same:
    // `disabled:opacity-50` is in the string whether or not it applies.
    renderFilters({
      view: {
        value: "list",
        set: vi.fn(),
        setFromScope: vi.fn(),
        canSet: false,
      },
    });

    const pressed = screen.getAllByRole("button", { pressed: true });
    expect(pressed.length).toBeGreaterThan(1);
    for (const button of pressed) {
      expect(button.className).not.toMatch(/\bopacity-/);
    }
  });

  it("still says which view is on while it is disabled", () => {
    // The buttons are the only thing that names the current view, so a
    // disabled group has to keep answering that question.
    renderFilters({
      view: {
        value: "list",
        set: vi.fn(),
        setFromScope: vi.fn(),
        canSet: false,
      },
    });

    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
