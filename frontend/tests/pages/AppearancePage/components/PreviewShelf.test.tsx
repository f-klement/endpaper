/** Tests for src/pages/AppearancePage/components/PreviewShelf.tsx. */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import PreviewShelf from "../../../../src/pages/AppearancePage/components/PreviewShelf";
import { makeBook, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

describe("PreviewShelf", () => {
  it("draws the books it is given", () => {
    renderLocalised(
      <PreviewShelf books={[makeBook({ title: "Dune" })]} />,
    );

    expect(screen.getByText("Dune")).toBeInTheDocument();
  });

  it("says why it is empty rather than drawing a placeholder book", () => {
    // A fake book in a preview is what previewing on real content exists to
    // avoid, so an empty cache gets a sentence instead.
    renderLocalised(<PreviewShelf books={[]} />);

    expect(screen.getByText(/nothing real to preview/)).toBeInTheDocument();
  });
});
