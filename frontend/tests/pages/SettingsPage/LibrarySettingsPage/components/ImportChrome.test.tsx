/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/components/ImportChrome.tsx.
 *
 * Only `TitleList` is pinned here: the other parts are drawn through the import
 * cards, whose tests cover them.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TitleList } from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/ImportChrome";
import { renderLocalised } from "../../../../utils";

describe("TitleList", () => {
  it("draws nothing for an empty or missing list", () => {
    const { container, rerender } = renderLocalised(
      <TitleList heading="Not found" titles={[]} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<TitleList heading="Not found" titles={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws the heading and every title in order", () => {
    renderLocalised(
      <TitleList heading="Not found" titles={["Dune", "Emma"]} />,
    );
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(
      screen.getAllByRole("listitem").map((item) => item.textContent),
    ).toEqual(["Dune", "Emma"]);
  });

  it("draws both rows when a file names one book twice", () => {
    renderLocalised(
      <TitleList heading="Not found" titles={["Dune", "Dune", "Dune"]} />,
    );
    expect(screen.getAllByText("Dune")).toHaveLength(3);
  });
});
