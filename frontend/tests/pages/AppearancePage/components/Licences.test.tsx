/** Tests for src/pages/AppearancePage/components/Licences.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Licences from "../../../../src/pages/AppearancePage/components/Licences";
import { PALETTES } from "../../../../src/theme";
import { renderLocalised } from "../../../utils";

describe("Licences", () => {
  it("credits every palette this project did not write", () => {
    // Generated from the catalogue, so a new palette cannot ship without a
    // notice by somebody forgetting to add one here.
    renderLocalised(<Licences />);

    for (const palette of PALETTES) {
      if (palette.attribution === null) continue;
      expect(screen.getByText(palette.attribution)).toBeInTheDocument();
    }
  });

  it("says this project is not Morris & Co", () => {
    // The five designs are public domain and the five names are current
    // product names of a live trading brand, which is a trademark question
    // rather than a copyright one.
    renderLocalised(<Licences />);

    expect(
      screen.getByText(/not affiliated with, or endorsed by, Morris & Co/),
    ).toBeInTheDocument();
  });
});
