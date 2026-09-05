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

describe("how long the book has been out", () => {
  it("reads the day count off the server rather than the lending date", () => {
    // The whole point of the field. `loaned_at` is right there in the payload
    // and a browser could subtract it, which is what would put a second
    // definition of a whole day in a second timezone.
    row({ loaned_at: "2026-02-01T00:00:00", days_out: 9 });

    expect(screen.getByText("Out for 9 days")).toBeInTheDocument();
  });

  it("says one day in the singular", () => {
    // There is no plural engine here on purpose, so the two forms are two
    // whole phrases and the component picks. A missing branch reads "Out for
    // 1 days".
    row({ days_out: 1 });

    expect(screen.getByText("Out for 1 day")).toBeInTheDocument();
  });

  it("says nothing on a book lent today", () => {
    // Zero is true and unhelpful: the lending date one line below already says
    // today. It is also what a loan read off a book payload carries, because
    // `loan_summary` fills nothing dated.
    row({ days_out: 0 });

    expect(screen.queryByText(/Out for/)).not.toBeInTheDocument();
  });

  it("says nothing once the book is back", () => {
    // The row reports the date it came back instead. A closed loan that went
    // on counting would be a lie about a book on the shelf.
    row({ days_out: 3, returned_at: "2026-02-20T00:00:00" });

    expect(screen.queryByText(/Out for/)).not.toBeInTheDocument();
  });
});

describe("how far past its deadline a loan is", () => {
  it("puts the day count in the badge, ahead of the date", () => {
    // What tells a week from a year at a glance, which the date alone does
    // not: a reader has to know today's date to read "Overdue since 5 Jan".
    row({ is_overdue: true, days_overdue: 14, due_at: "2026-01-05T00:00:00" });

    expect(screen.getByText(/^14 days overdue, since/)).toBeInTheDocument();
  });

  it("keeps the deadline beside the count", () => {
    // **The badge is the only place the deadline can appear on an overdue
    // row.** The `dueOn` line is gated on the loan not being overdue, so a
    // badge carrying the count alone takes the date off every overdue row past
    // its first day, which is what the first version of this did. The count is
    // for triage and the date is what somebody writes to a borrower.
    row({ is_overdue: true, days_overdue: 14, due_at: "2026-01-05T00:00:00" });

    const badge = screen.getByText(/days overdue/);
    expect(badge.textContent).toContain(
      new Date("2026-01-05T00:00:00").toLocaleDateString("en"),
    );
  });

  it("says one day in the singular", () => {
    row({ is_overdue: true, days_overdue: 1, due_at: "2026-01-05T00:00:00" });

    expect(screen.getByText(/^1 day overdue, since/)).toBeInTheDocument();
  });

  it("falls back to the date alone within the first day", () => {
    // `days_overdue` is 0 for a loan that went overdue this morning, and 0
    // says nothing. The date carries that case on its own.
    row({ is_overdue: true, days_overdue: 0, due_at: "2026-01-05T00:00:00" });

    expect(screen.getByText(/^Overdue since/)).toBeInTheDocument();
  });

  it("falls back to the bare word for a loan with no deadline", () => {
    // A loan with no `due_at` can still be flagged by something other than a
    // date, and there is no date to name.
    row({ is_overdue: true, days_overdue: 0, due_at: null });

    expect(screen.getByText("Overdue")).toBeInTheDocument();
  });
});
