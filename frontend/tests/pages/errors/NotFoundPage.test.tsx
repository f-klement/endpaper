/** Tests for src/pages/errors/NotFoundPage.tsx and ForbiddenPage.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../../utils";
import { describe, expect, it } from "vitest";

import ForbiddenPage from "../../../src/pages/errors/ForbiddenPage";
import NotFoundPage from "../../../src/pages/errors/NotFoundPage";

describe("NotFoundPage", () => {
  it("says what happened", () => {
    renderLocalised(<NotFoundPage />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Error 404")).toBeInTheDocument();
  });

  it("offers a way back to the library", () => {
    // This replaced a silent redirect to "/", which hid every dead link.
    renderLocalised(<NotFoundPage />);
    expect(
      screen.getByRole("link", { name: "Back to the library" }),
    ).toHaveAttribute("href", "/");
  });
});

describe("ForbiddenPage", () => {
  it("says what happened", () => {
    renderLocalised(<ForbiddenPage />);
    expect(screen.getByText("Not allowed")).toBeInTheDocument();
    expect(screen.getByText("Error 403")).toBeInTheDocument();
  });
});
