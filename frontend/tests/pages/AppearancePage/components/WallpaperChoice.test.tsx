/** Tests for src/pages/AppearancePage/components/WallpaperChoice.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import WallpaperChoice from "../../../../src/pages/AppearancePage/components/WallpaperChoice";
import { PATTERNS } from "../../../../src/theme/patterns";
import { renderLocalised } from "../../../utils";

describe("WallpaperChoice", () => {
  it("offers the ten patterns plus off and surprise me", () => {
    renderLocalised(<WallpaperChoice />);

    expect(screen.getAllByRole("button")).toHaveLength(PATTERNS.length + 2);
  });

  it("puts every pattern under the heading for its family", () => {
    // `Pattern.family` scoped a density rule and named nothing until this
    // screen existed. The two headings are what it is for.
    renderLocalised(<WallpaperChoice />);
    const headings = screen
      .getAllByRole("heading")
      .map((heading) => heading.textContent);

    expect(headings).toEqual(["William Morris", "Decorated papers"]);
  });

  it("draws the tiles at the opacity they are painted at", () => {
    // Not brightened for the picker. A swatch at three times the page's opacity
    // is a lie about what is being chosen. `contain` is what makes it legible
    // instead: the motif, not the stroke weight, is what identifies a tile.
    const { container } = renderLocalised(<WallpaperChoice />);
    const tiles = [...container.querySelectorAll("[style]")].filter((element) =>
      element.getAttribute("style")?.includes("background-image"),
    );

    expect(tiles.length).toBeGreaterThan(0);
    for (const tile of tiles) {
      expect(tile.getAttribute("style")).toContain("background-size: contain");
    }
  });

  it("chooses one on a click", async () => {
    renderLocalised(<WallpaperChoice />);

    await userEvent.setup().click(screen.getByRole("button", { name: /Plait/ }));

    expect(screen.getByRole("button", { name: /Plait/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
