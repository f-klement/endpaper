/** Tests for src/pages/BookDetail/components/IdentifierChips. */

import { fireEvent, screen } from "@testing-library/react";
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
  onRemove: (identifier: BookIdentifierOut) => void = vi.fn(),
) {
  return renderLocalised(
    <IdentifierChips identifiers={identifiers} onRemove={onRemove} />,
    { locale },
  );
}

const anAsin: BookIdentifierOut = {
  id: 1,
  scheme: BookIdentifierScheme.asin,
  value: "B00J4YQKHY",
};

const aVolumeId: BookIdentifierOut = {
  id: 2,
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
    renderChips([anAsin, { ...anAsin, id: 3, value: "B00OTHER01" }, aVolumeId]);

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
    // **Not "there are no buttons", which is what this line said until a
    // remove control arrived and made it false.** What the structural arms are
    // for is that a way out of here cannot be added quietly, so the assertion
    // is that every button this component renders is one of the removals: a
    // third button, however it were labelled, fails here before anybody
    // reaches the sweep below.
    //
    // **By tag and over the whole document, and each half answers a different
    // escape.** By tag, because `getAllByRole` skips an `aria-hidden` subtree:
    // a vendor button carrying one passed this line and left the rule resting
    // on the sweep. Being blind to ARIA closes `role="presentation"`, `hidden`
    // and a wrapper carrying any of them together, rather than one arm per
    // spelling. Over the document, because `container` is not where a portal
    // renders: a `createPortal` button on `document.body` was seen by no arm
    // in this test at all, the sweep included, since that is `container`
    // rooted too. Both measured as mutants that pass every other arm.
    //
    // **What it does not catch is a `div` wearing `role="button"`**, which the
    // role query did. The sweep below catches that one instead, at
    // `opened`, so the rule holds and this line is not where it holds.
    expect(
      [...document.body.querySelectorAll("button")].map((node) =>
        node.getAttribute("aria-label"),
      ),
    ).toEqual([
      "Remove Amazon reference: B00J4YQKHY",
      "Remove Google Books reference: zyTCAlFPjgYC",
    ]);

    const before = window.location.href;
    // `document.body` and not `container`, for the reason the arm above gives:
    // a portal renders outside the container, so a sweep rooted there cannot
    // click what it put on the page.
    for (const element of document.body.querySelectorAll("*")) {
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
      { id: 4, scheme: "kobo" as BookIdentifierScheme, value: "a-kobo-token" },
    ]);

    expect(
      screen.getByText("kobo reference: a-kobo-token"),
    ).toBeInTheDocument();
  });

  it("says it in German too", () => {
    renderChips(
      [
        {
          id: 4,
          scheme: "kobo" as BookIdentifierScheme,
          value: "a-kobo-token",
        },
      ],
      Locale.de,
    );

    expect(screen.getByText("kobo-Referenz: a-kobo-token")).toBeInTheDocument();
  });
});

describe("removing one", () => {
  it("offers a control on every chip, named for the identifier it removes", () => {
    // Named rather than "Remove": two ASINs on one book is the ordinary output
    // of merging two Kindle entries, and two controls both called "Remove" are
    // one control as far as a screen reader is concerned.
    renderChips([anAsin, { ...anAsin, id: 3, value: "B00OTHER01" }]);

    expect(
      screen.getByRole("button", {
        name: "Remove Amazon reference: B00J4YQKHY",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Remove Amazon reference: B00OTHER01",
      }),
    ).toBeInTheDocument();
  });

  it("hands back the whole row, so the caller can name it in the question", () => {
    const onRemove = vi.fn();
    renderChips([anAsin, aVolumeId], Locale.en, onRemove);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove Google Books reference: zyTCAlFPjgYC",
      }),
    );

    // The row and not its id: `hooks.ts` asks before removing one and the
    // question carries the value.
    expect(onRemove).toHaveBeenCalledExactlyOnceWith(aVolumeId);
  });

  it("names the identifier in German too", () => {
    renderChips([anAsin], Locale.de);

    expect(
      screen.getByRole("button", {
        name: "Amazon-Referenz: B00J4YQKHY entfernen",
      }),
    ).toBeInTheDocument();
  });

  it("leaves the chip a plain box, so the value still breaks", () => {
    // **The one thing the control could quietly cost.** `min-w-0` on the chip
    // removes the content floor it gets as a flex item of the row, and the
    // value is up to 60 characters with no break in it. Spacing the button
    // with `inline-flex` makes the label an anonymous flex item with a floor
    // of its own, which `min-w-0` here cannot reach, so the token sets the
    // width again through a child nothing can select and the row leaves the
    // viewport.
    //
    // Asserted on the class rather than on a box, because there is no browser
    // on this node. What that buys is not a measurement: it is that the next
    // person reaching for `inline-flex` to get a gap meets this instead of
    // shipping it. The comment at the chip carries the reason.
    //
    // **Three arms, and the exact list alone is not enough.** Naming `min-w-0`
    // and refusing `flex` pinned one and a half of the pair: deleting
    // `break-words` went clean, and so did `inline-grid grid-flow-col`,
    // because a grid item takes the same `min-width: auto`, and a variant
    // prefix beat the regex. Both measured. So the list closes those open
    // sets by saying what the class list **is**.
    //
    // **But an exact list on its own invites the repair that re-greens the
    // bug**: the one edit a failing equality suggests is pasting in what was
    // observed, and doing that to admit `flex` would pass. Every token in it
    // has equal status, so nothing in it says which two are load bearing.
    // The named arms below are what a paste cannot repair, and they carry the
    // reason in their own failure message.
    const { container } = renderChips([anAsin]);
    const chip = container.querySelector("span")!;

    expect(chip.className.split(" ").sort()).toEqual([
      "bg-paper-100",
      "break-words",
      "dark:bg-paper-800",
      "dark:text-paper-400",
      "min-w-0",
      "px-2",
      "py-0.5",
      "rounded",
      "text-paper-600",
      "text-xs",
    ]);
    // The pair the chip's own comment is about: the floor removed, and the
    // wrap that the removed floor lets take effect. Neither works alone.
    expect(chip.className).toContain("min-w-0");
    expect(chip.className).toContain("break-words");
    // Any display that makes the label a flex or grid item, in any variant
    // spelling, because `min-w-0` on this box cannot reach an anonymous one.
    expect(chip.className).not.toMatch(
      /(?:^|[\s:])(?:inline-)?(?:flex|grid)(?:\s|$)/,
    );
  });

  it("asks nothing itself, so the question cannot be skipped by rendering", () => {
    // The confirmation lives in `hooks.ts` with every other mutation on this
    // page. A component that asked as well would ask twice through the page
    // and not at all through a second caller.
    const asked = vi.spyOn(window, "confirm");
    const onRemove = vi.fn();
    renderChips([anAsin], Locale.en, onRemove);

    fireEvent.click(screen.getAllByRole("button")[0]!);

    expect(asked).not.toHaveBeenCalled();
    expect(onRemove).toHaveBeenCalledOnce();
  });
});
