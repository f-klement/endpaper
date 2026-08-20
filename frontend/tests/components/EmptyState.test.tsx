/** Tests for src/components/EmptyState.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../utils";
import { describe, expect, it } from "vitest";

import EmptyState from "../../src/components/EmptyState";

describe("EmptyState", () => {
  it("shows the title", () => {
    renderLocalised(<EmptyState icon="inbox" title="No books found" />);
    expect(screen.getByText("No books found")).toBeInTheDocument();
  });

  it("renders its icon as decoration, not as content", () => {
    // The icon repeats what the title already says, so announcing it makes a
    // screen reader read the empty state twice.
    const { container } = renderLocalised(
      <EmptyState icon="inbox" title="No books found" />,
    );
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("shows a hint when given one", () => {
    renderLocalised(
      <EmptyState
        icon="inbox"
        title="No books found"
        hint="Try adjusting your filters"
      />,
    );
    expect(screen.getByText("Try adjusting your filters")).toBeInTheDocument();
  });

  it("omits the hint element entirely when there is none", () => {
    const { container } = renderLocalised(
      <EmptyState icon="inbox" title="No active loans" />,
    );
    expect(container.querySelectorAll("p")).toHaveLength(1);
  });
});
