/** Tests for src/pages/Home/components/ClassificationPicker. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ClassificationScheme,
  type ClassificationFacets,
} from "../../../../src/api/generated/model";
import ClassificationPicker, {
  headingKey,
} from "../../../../src/pages/Home/components/ClassificationPicker";
import { renderLocalised } from "../../../utils";

const FACETS: ClassificationFacets = {
  divisions: [
    { division: "150", label: "Psychology", book_count: 3 },
    // 080 is quotations and maps to no seeded tag. An absent label is a real
    // answer there rather than a gap.
    { division: "080", label: null, book_count: 1 },
  ],
  headings: [
    {
      scheme: ClassificationScheme.lcsh,
      number: "Stress management",
      label: null,
      book_count: 2,
    },
  ],
};

function renderPicker(
  overrides: Partial<Parameters<typeof ClassificationPicker>[0]> = {},
) {
  const props = {
    facets: FACETS,
    selectedHeadings: [],
    selectedDivisions: [],
    onToggleHeading: vi.fn(),
    onToggleDivision: vi.fn(),
    ...overrides,
  };
  renderLocalised(<ClassificationPicker {...props} />);
  return props;
}

describe("when the library carries nothing to filter on", () => {
  it("says so rather than drawing two empty groups", () => {
    renderPicker({ facets: { divisions: [], headings: [] } });

    expect(
      screen.getByText("Nothing in the library carries one yet."),
    ).toBeInTheDocument();
  });

  it("says the same while the request is still in flight", () => {
    renderPicker({ facets: undefined });

    expect(
      screen.getByText("Nothing in the library carries one yet."),
    ).toBeInTheDocument();
  });
});

describe("the two groups", () => {
  it("offers the shelf and the subjects separately", () => {
    // Two groups because the two take different operators: a division is ORed
    // and a heading is ANDed. See docs/decisions.md.
    renderPicker();

    expect(
      screen.getByRole("group", { name: "Dewey shelf" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Subjects and numbers" }),
    ).toBeInTheDocument();
  });

  it("shows a division with no label as its number alone", () => {
    renderPicker();

    expect(screen.getByRole("button", { name: /^080/ })).toBeInTheDocument();
  });

  it("carries the count each facet was measured at", () => {
    renderPicker();

    expect(
      screen.getByRole("button", { name: /150.*Psychology.*3/ }),
    ).toBeInTheDocument();
  });
});

describe("picking one", () => {
  it("reports a division by its number", async () => {
    const props = renderPicker();

    await userEvent.click(screen.getByRole("button", { name: /150/ }));

    expect(props.onToggleDivision).toHaveBeenCalledWith("150");
  });

  it("reports a heading as scheme and number, which is the wire spelling", async () => {
    const props = renderPicker();

    await userEvent.click(
      screen.getByRole("button", { name: /Stress management/ }),
    );

    expect(props.onToggleHeading).toHaveBeenCalledWith(
      "lcsh:Stress management",
    );
  });

  it("marks what is already chosen, so a selection is visible", () => {
    renderPicker({ selectedDivisions: ["150"] });

    expect(screen.getByRole("button", { name: /150/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

describe("the wire spelling", () => {
  it("is assembled in exactly one place", () => {
    expect(
      headingKey({
        scheme: ClassificationScheme.lcsh,
        number: "Mental health, Public",
        label: null,
        book_count: 1,
      }),
    ).toBe("lcsh:Mental health, Public");
  });
});
