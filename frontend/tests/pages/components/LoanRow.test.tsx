/** Tests for src/pages/components/LoanRow.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LoanRow from "../../../src/pages/components/LoanRow";
import { makeBook, makeLoan, resetIds } from "../../factories";
import { renderLocalised } from "../../utils";

function row(overrides = {}) {
  resetIds();
  return renderLocalised(
    <LoanRow
      loan={makeLoan({ book: makeBook({ title: "Piranesi" }), ...overrides })}
      isReturning={false}
      onMarkReturned={vi.fn()}
    />,
  );
}

/** The card element, which is the thing the highlight is painted on. */
function card(container: HTMLElement): HTMLElement {
  const found = container.querySelector(".card");
  expect(found).not.toBeNull();
  return found as HTMLElement;
}

/**
 * The card's danger classes, as whole class names.
 *
 * **Split into tokens rather than matched as substrings, and that is the whole
 * of it.** `className.includes("border-danger-500")` is satisfied by
 * `dark:border-danger-500` alone: measured, deleting the light mode class left
 * this file at 5 passed and 0 failed, with the default mode reduced to the
 * card's own `paper-200` border. The reverse mutation passed too. That is
 * `grep -F ci` matching the middle of "decision", in a class list.
 *
 * Returned as the **whole set** rather than checked one at a time, so the
 * assertion fails on a class missing, a class renamed, and a further danger
 * class arriving beside them. An arm per spelling is the shape this repository
 * keeps having to rewrite.
 */
function dangerClasses(container: HTMLElement): string[] {
  return card(container)
    .className.split(/\s+/)
    .filter((name) => name.includes("danger"))
    .sort();
}

describe("LoanRow", () => {
  it("names the book and who has it", () => {
    row();
    expect(screen.getByText("Piranesi")).toBeInTheDocument();
    expect(screen.getByText(/borrower/)).toBeInTheDocument();
  });
});

describe("an overdue row is marked twice, and neither mark is colour alone", () => {
  it("says in words that the book is late, and since when", () => {
    // The mark a reader who cannot separate the two frames still gets. If this
    // ever becomes the border alone, the page is telling colour-blind readers
    // nothing.
    row({ is_overdue: true, due_at: "2026-01-05T00:00:00" });

    expect(screen.getByText(/Overdue since/)).toBeInTheDocument();
  });

  it("carries an edge bar in the measured danger rung, in both modes", () => {
    // `danger-500`, not the `danger-300` / `danger-700` pair this card used to
    // carry: measured on the default palette, that pair is 1.89:1 on the light
    // card and 2.18:1 on the dark one, against the 3.0 WCAG 1.4.11 asks of a
    // non-text indicator. `palettes.test.ts` asserts `danger-500` against both
    // card surfaces at 4.5 for every palette, so this class name is what ties
    // the row to a floor somebody is already measuring.
    //
    // Both spellings named, because a card that carried only the `dark:` one
    // would leave the default mode with no mark at all.
    const { container } = row({ is_overdue: true });

    expect(dangerClasses(container)).toEqual([
      "border-danger-500",
      "dark:border-danger-500",
    ]);
    expect(card(container).className.split(/\s+/)).toContain("border-l-4");
  });

  it("leaves a loan that is not late unmarked", () => {
    const { container } = row({ is_overdue: false });

    expect(dangerClasses(container)).toEqual([]);
    expect(screen.queryByText(/Overdue/)).not.toBeInTheDocument();
  });

  it("drops the mark once the book is back, however late it was", () => {
    // A returned loan is closed. Keeping it flagged would put a permanent red
    // edge on the history.
    const { container } = row({
      is_overdue: false,
      returned_at: "2026-02-20T00:00:00",
    });

    expect(dangerClasses(container)).toEqual([]);
  });
});
