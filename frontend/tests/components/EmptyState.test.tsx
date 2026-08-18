/** Tests for src/components/EmptyState.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../utils";
import { describe, expect, it } from "vitest";

import EmptyState from "../../src/components/EmptyState";

describe("EmptyState", () => {
  it("shows the glyph and title", () => {
    renderLocalised(<EmptyState glyph="📭" title="No books found" />);
    expect(screen.getByText("📭")).toBeInTheDocument();
    expect(screen.getByText("No books found")).toBeInTheDocument();
  });

  it("shows a hint when given one", () => {
    renderLocalised(
      <EmptyState
        glyph="📭"
        title="No books found"
        hint="Try adjusting your filters"
      />,
    );
    expect(screen.getByText("Try adjusting your filters")).toBeInTheDocument();
  });

  it("omits the hint element entirely when there is none", () => {
    const { container } = renderLocalised(
      <EmptyState glyph="✅" title="No active loans" />,
    );
    expect(container.querySelectorAll("p")).toHaveLength(2);
  });
});
