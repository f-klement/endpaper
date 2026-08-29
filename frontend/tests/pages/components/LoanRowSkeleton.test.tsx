/** Tests for src/pages/components/LoanRowSkeleton.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LoanRowSkeleton from "../../../src/pages/components/LoanRowSkeleton";
import { renderLocalised } from "../../utils";

describe("LoanRowSkeleton", () => {
  it("draws the requested number of placeholder rows", () => {
    renderLocalised(<LoanRowSkeleton count={5} testId="loan-skeletons" />);

    expect(
      screen.getByTestId("loan-skeletons").querySelectorAll(".animate-pulse"),
    ).toHaveLength(5);
  });

  it("draws three when the caller does not say", () => {
    renderLocalised(<LoanRowSkeleton testId="loan-skeletons" />);

    expect(
      screen.getByTestId("loan-skeletons").querySelectorAll(".animate-pulse"),
    ).toHaveLength(3);
  });

  it("carries the test id it was given, because the two pages differ", () => {
    // Not a constant. The loans page and the overdue page name their lists
    // separately and their tests assert on those names, so a shared component
    // that hard-coded one would have silently broken the other's assertion.
    renderLocalised(<LoanRowSkeleton testId="overdue-skeletons" />);

    expect(screen.getByTestId("overdue-skeletons")).toBeInTheDocument();
  });

  it("stands in for a LoanRow rather than for a generic card", () => {
    // The reason this component exists. Both pages once carried these fifteen
    // lines verbatim, so a change to LoanRow's shape would have been made in
    // one placeholder and not the other, and the list would jump on the page
    // that was missed. The cover block and the two text lines are the parts
    // that mirror the row, so they are what is pinned.
    renderLocalised(<LoanRowSkeleton count={1} testId="loan-skeletons" />);
    const card = screen.getByTestId("loan-skeletons").firstElementChild!;

    expect(card.querySelector(".w-12.h-16")).not.toBeNull();
    expect(card.querySelectorAll(".flex-1 > *")).toHaveLength(2);
  });
});
