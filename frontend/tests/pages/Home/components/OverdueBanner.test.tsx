/** Tests for src/pages/Home/components/OverdueBanner.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OverdueBanner from "../../../../src/pages/Home/components/OverdueBanner";
import { renderLocalised } from "../../../utils";

describe("OverdueBanner", () => {
  it("says how many of the reader's own loans are overdue", () => {
    renderLocalised(<OverdueBanner count={3} />);

    expect(screen.getByText(/3 loans need chasing/)).toBeInTheDocument();
  });

  it("renders nothing when none are", () => {
    // Not an empty box and not a "nothing overdue" line: the ordinary state of
    // this page is that there is nothing to say, and a banner saying so every
    // day is the one people learn to stop reading.
    const { container } = renderLocalised(<OverdueBanner count={0} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("sends the reader to the overdue page, not the loans list", () => {
    // A count and no titles, so what it can offer is the list. The link is a
    // route rather than a button, so the back button works afterwards.
    //
    // **The destination is load bearing (#102).** This banner counts through
    // `overdue_for_viewer` and the loans list does not, so `/loans` handed a
    // member a screen with more rows on it than the sentence they had just
    // read. The overdue page asks the endpoint that applies the same rule.
    renderLocalised(<OverdueBanner count={1} />);

    expect(screen.getByRole("link", { name: "See them" })).toHaveAttribute(
      "href",
      "/loans/overdue",
    );
  });
});
