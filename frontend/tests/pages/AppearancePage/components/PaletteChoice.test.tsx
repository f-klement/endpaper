/** Tests for src/pages/AppearancePage/components/PaletteChoice.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import PaletteChoice from "../../../../src/pages/AppearancePage/components/PaletteChoice";
import { PALETTES } from "../../../../src/theme";
import { renderLocalised } from "../../../utils";

describe("PaletteChoice", () => {
  it("offers all seven", () => {
    renderLocalised(<PaletteChoice />);

    expect(screen.getAllByRole("button")).toHaveLength(PALETTES.length);
  });

  it("leaves the document on the palette in force after reading the others", () => {
    // The swatches are read by putting each palette on the document in turn,
    // which is the only way to draw one without a second copy of its hexes.
    // Leaving the last one there would repaint the whole app in Nord.
    renderLocalised(<PaletteChoice />);

    expect(document.documentElement.dataset.theme).toBe("endpaper");
  });

  it("draws no colour where the stylesheet says nothing", () => {
    // jsdom loads no stylesheet, so most tokens read empty. An empty `fill` is
    // black rather than invisible, so a tile with a gap in it draws nothing at
    // all rather than part of itself.
    const { container } = renderLocalised(<PaletteChoice />);

    expect(container.querySelector("[style]")).toBeNull();
  });

  it("applies a palette on a click", async () => {
    renderLocalised(<PaletteChoice />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Rose Pine/ }));

    expect(document.documentElement.dataset.theme).toBe("rosepine");
  });
});
