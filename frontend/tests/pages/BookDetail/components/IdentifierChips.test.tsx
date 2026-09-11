/** Tests for src/pages/BookDetail/components/IdentifierChips. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  BookIdentifierScheme,
  Locale,
  type BookIdentifierOut,
} from "../../../../src/api/generated/model";
import IdentifierChips from "../../../../src/pages/BookDetail/components/IdentifierChips";
import { renderLocalised } from "../../../utils";

function renderChips(
  identifiers: BookIdentifierOut[],
  locale: Locale = Locale.en,
) {
  return renderLocalised(<IdentifierChips identifiers={identifiers} />, {
    locale,
  });
}

const anAsin: BookIdentifierOut = {
  scheme: BookIdentifierScheme.asin,
  value: "B00J4YQKHY",
};

const aVolumeId: BookIdentifierOut = {
  scheme: BookIdentifierScheme.google_books,
  value: "zyTCAlFPjgYC",
};

describe("what a store calls this book", () => {
  it("names the store and what the number is for, never the acronym", () => {
    renderChips([anAsin]);

    expect(
      screen.getByText("Amazon reference: B00J4YQKHY"),
    ).toBeInTheDocument();
    // The word this app does not put on screen, because it names nothing to
    // somebody who has not met Amazon's catalogue.
    expect(screen.queryByText(/ASIN/i)).toBeNull();
  });

  it("says the same in German", () => {
    renderChips([anAsin], Locale.de);

    expect(screen.getByText("Amazon-Referenz: B00J4YQKHY")).toBeInTheDocument();
  });

  it("names Google Books for a volume id", () => {
    renderChips([aVolumeId]);

    expect(
      screen.getByText("Google Books reference: zyTCAlFPjgYC"),
    ).toBeInTheDocument();
  });

  it("gives every identifier its own chip", () => {
    // Two ASINs on one book is what a merge of two Kindle entries produces,
    // which is why the unique index carries the value and not just the scheme.
    renderChips([anAsin, { ...anAsin, value: "B00OTHER01" }, aVolumeId]);

    expect(screen.getAllByText(/reference:/)).toHaveLength(3);
  });

  it("renders nothing at all for a book carrying none", () => {
    const { container } = renderChips([]);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("an identifier is text and not a link", () => {
  it("sends nobody to a vendor", async () => {
    // The decision, pinned rather than described: the marketplace an ASIN
    // belongs to is not stored, the value's shape is unchecked, and the one
    // outbound vendor link this app has is gated by an admin setting. A future
    // way out of here has to argue past all three, and this is where it finds
    // out.
    //
    // **Three instruments on one rule, because listing spellings does not
    // hold, and the list grew twice before it stopped being a list.** The
    // first draft asserted the anchor and the `href`, and a span wearing
    // `role="link"` with an `onClick` calling `window.open` passed it. The
    // second added the role and a `window.open` spy, and a span with no role
    // that assigned `window.location.href` passed that. Both were found by the
    // security seat and the second is the first one API over.
    //
    // So the last instrument asks the rendered result what it **did** rather
    // than what it is made of: after clicking every node this component
    // renders, nothing was opened and this document is where it was.
    //
    // **Both of those, because neither covers the other**, and the pair is not
    // the list this comment warns about. `window.open` puts the member in
    // front of a vendor without moving this document's URL, so the location
    // arm cannot see it; assigning `location.href` calls nothing, so the spy
    // cannot see that. Measured under this test's own name: the first fails
    // only at the `opened` line, the second only at the `location.href` line.
    // What is forbidden is answering each new bypass with another arm. An arm
    // that covers a way of leaving nothing else can observe is the rule
    // working.
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const { container } = renderChips([anAsin, aVolumeId]);

    expect(
      screen.getByText("Amazon reference: B00J4YQKHY"),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(container.querySelectorAll("[href]")).toHaveLength(0);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryAllByRole("button")).toHaveLength(0);

    const before = window.location.href;
    for (const element of container.querySelectorAll("*")) {
      await userEvent.click(element);
    }
    expect(opened).not.toHaveBeenCalled();
    expect(window.location.href).toBe(before);
  });
});

describe("a scheme this build has no name for", () => {
  it("still shows the value, under the scheme the server sent", () => {
    // Reachable whenever the generated model and the server are a commit
    // apart: the enum is a snapshot of a committed schema, so the type saying
    // this cannot happen is the type describing the older of the two.
    renderChips([
      { scheme: "kobo" as BookIdentifierScheme, value: "a-kobo-token" },
    ]);

    expect(
      screen.getByText("kobo reference: a-kobo-token"),
    ).toBeInTheDocument();
  });

  it("says it in German too", () => {
    renderChips(
      [{ scheme: "kobo" as BookIdentifierScheme, value: "a-kobo-token" }],
      Locale.de,
    );

    expect(screen.getByText("kobo-Referenz: a-kobo-token")).toBeInTheDocument();
  });
});
