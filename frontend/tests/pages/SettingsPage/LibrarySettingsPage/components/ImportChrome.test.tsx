/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/components/ImportChrome.tsx.
 *
 * `TitleList` is pinned here, and the one fact about `OutcomePanel` its cards'
 * tests cannot see: the failure row is not clipped. The other parts are drawn
 * through the import cards, whose tests cover them.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { en } from "../../../../../src/i18n/en";
import {
  OutcomePanel,
  TitleList,
} from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/ImportChrome";
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

describe("OutcomePanel", () => {
  it("draws a failure row's whole reason, wrapping rather than clipping it", () => {
    // happy-dom lays nothing out, so a clipped row still holds its full text.
    // What cuts the reason at phone width is a utility on the row, and the in
    // trash reason ends in what to do next, which is the part a cut drops.
    renderLocalised(
      <OutcomePanel
        outcome={{
          added: 0,
          stopped: false,
          failures: [{ title: "Dune", status: 409, inTrash: true }],
        }}
        messages={{
          result: "calibre.result",
          resultStopped: "calibre.resultStopped",
          resultFailures: "calibre.resultFailures",
          duplicate: "calibre.duplicate",
          notAdded: "calibre.notAdded",
          inTrash: "calibre.inTrash",
        }}
      />,
    );

    const row = screen.getByRole("listitem");
    expect(row.textContent).toBe(`Dune · ${en["calibre.inTrash"]}`);
    expect(row.className).not.toMatch(
      /(?:^|[\s:])(?:truncate|text-ellipsis|text-clip|text-nowrap|overflow-hidden|overflow-clip|overflow-x-(?:hidden|clip)|whitespace-nowrap|line-clamp-\S+)(?:\s|$)/,
    );
    // Above the row only what inherits can stop it wrapping: `white-space`,
    // which `truncate` also sets, and `text-wrap`. An ancestor's own overflow
    // clips nothing that wraps, so a rounded card's `overflow-hidden` passes.
    for (let el = row.parentElement; el; el = el.parentElement) {
      expect(el.getAttribute("class") ?? "").not.toMatch(
        /(?:^|[\s:])(?:truncate|text-nowrap|whitespace-nowrap)(?:\s|$)/,
      );
    }
  });
});
