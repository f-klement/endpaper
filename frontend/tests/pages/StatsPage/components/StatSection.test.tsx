/** Tests for src/pages/StatsPage/components/StatSection.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../../../utils";
import { describe, expect, it } from "vitest";

import StatSection from "../../../../src/pages/StatsPage/components/StatSection";

describe("StatSection", () => {
  it("renders a row per entry", () => {
    renderLocalised(
      <StatSection
        title="By Genre"
        rows={[
          { label: "Fantasy", count: 3 },
          { label: "Horror", count: 1 },
        ]}
        colorClass="bg-accent-400"
      />,
    );
    expect(screen.getByText("Fantasy")).toBeInTheDocument();
    expect(screen.getByText("Horror")).toBeInTheDocument();
  });

  it("renders nothing at all when there are no rows", () => {
    // Returning null rather than an empty section is what keeps StatsPage from
    // showing a bare heading with nothing under it.
    const { container } = renderLocalised(
      <StatSection title="By Genre" rows={[]} colorClass="bg-accent-400" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("scales bars against the largest row in its own group", () => {
    const { container } = renderLocalised(
      <StatSection
        title="By Genre"
        rows={[
          { label: "Fantasy", count: 10 },
          { label: "Horror", count: 5 },
        ]}
        colorClass="bg-accent-400"
      />,
    );
    const bars = container.querySelectorAll<HTMLElement>(".bg-accent-400");
    expect(bars[0]!.style.width).toBe("100%");
    expect(bars[1]!.style.width).toBe("50%");
  });

  it("survives an all-zero group without producing NaN widths", () => {
    const { container } = renderLocalised(
      <StatSection
        title="By Genre"
        rows={[{ label: "Fantasy", count: 0 }]}
        colorClass="bg-accent-400"
      />,
    );
    expect(
      container.querySelector<HTMLElement>(".bg-accent-400")!.style.width,
    ).toBe("0%");
  });
});
