/**
 * @vitest-environment jsdom
 *
 * The suite runs on happy-dom, which is much faster to construct. This file is
 * pinned back to jsdom because **happy-dom does not inherit CSS custom
 * properties down the tree**: a `--color-*` token set on `documentElement`
 * reads back on that element and resolves to "" on every descendant. Measured
 * 2026-08-22 with a two line probe.
 *
 * The wallpaper resolves its ink, bloom and page off the document from a child
 * element, so under happy-dom `isColour()` sees empty strings, `applyWallpaper`
 * returns before painting, and seven tests fail asserting on a background that
 * was never drawn. Nothing is wrong with the app or the tests; the engine lacks
 * the cascade they depend on.
 */
/** Tests for src/pages/AppearancePage/components/WallpaperChoice.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import WallpaperChoice from "../../../../src/pages/AppearancePage/components/WallpaperChoice";
import { PATTERNS } from "../../../../src/theme/patterns";
import { renderLocalised } from "../../../utils";

describe("WallpaperChoice", () => {
  it("offers every pattern plus off and surprise me", () => {
    // Named for the property rather than for a count. The assertion was always
    // `PATTERNS.length`, so the name went stale on its own the first time the
    // catalogue grew and nothing failed.
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

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Plait/ }));

    expect(screen.getByRole("button", { name: /Plait/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
