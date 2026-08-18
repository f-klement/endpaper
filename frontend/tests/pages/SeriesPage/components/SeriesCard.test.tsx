/** Tests for src/pages/SeriesPage/components/SeriesCard.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SeriesOut } from "../../../../src/api/generated/model";
import SeriesCard from "../../../../src/pages/SeriesPage/components/SeriesCard";
import { renderLocalised } from "../../../utils";

function series(overrides: Partial<SeriesOut> = {}): SeriesOut {
  return { name: "Dune", book_count: 3, missing_indexes: [], ...overrides };
}

describe("SeriesCard", () => {
  it("names the series and counts it", () => {
    renderLocalised(<SeriesCard series={series({ book_count: 3 })} />);
    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("3 books")).toBeInTheDocument();
  });

  it("shows the gaps, which is why the page exists", () => {
    renderLocalised(
      <SeriesCard series={series({ missing_indexes: [2, 5] })} />,
    );
    expect(screen.getByText("Missing: 2, 5")).toBeInTheDocument();
  });

  it("says so when a series is complete", () => {
    // Staying silent would be indistinguishable from "not calculated".
    renderLocalised(<SeriesCard series={series({ missing_indexes: [] })} />);
    expect(screen.getByText("No gaps")).toBeInTheDocument();
  });

  it("links to the series, sorted in its own order", () => {
    renderLocalised(
      <SeriesCard series={series({ name: "A Song of Ice and Fire" })} />,
    );
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/?series=A%20Song%20of%20Ice%20and%20Fire&sort=series",
    );
  });
});
