/** Tests for src/components/Spinner.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../utils";
import { describe, expect, it } from "vitest";

import Spinner from "../../src/components/Spinner";

describe("Spinner", () => {
  it("exposes its label to assistive tech", () => {
    // A spinner with no accessible name is invisible to a screen reader, which
    // is the audience that most needs to be told the page is busy.
    renderLocalised(<Spinner label="Loading book" />);
    expect(
      screen.getByRole("status", { name: "Loading book" }),
    ).toBeInTheDocument();
  });

  it("accepts extra classes", () => {
    renderLocalised(<Spinner label="Loading" className="w-4" />);
    expect(screen.getByRole("status")).toHaveClass("w-4");
  });
});
