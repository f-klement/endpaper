/** Tests for src/pages/OverduePage/components/DeliveryStatus.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  OverdueSender,
  type SenderHealth,
} from "../../../../src/api/generated/model";
import { de } from "../../../../src/i18n/de";
import { en } from "../../../../src/i18n/en";
import DeliveryStatus from "../../../../src/pages/OverduePage/components/DeliveryStatus";
import type { DeliveryChannel } from "../../../../src/pages/OverduePage/types";
import { renderLocalised } from "../../../utils";

/**
 * The clause this panel is not allowed to carry, in either language.
 *
 * A claim about where the loans appear, which is a fact about the in app
 * channel's switch, and this component is handed no such fact.
 */
const RETIRED_CLAIM = /appear here|erscheinen hier/;

function channel(overrides: Partial<SenderHealth> = {}): DeliveryChannel {
  const health: SenderHealth = {
    sender: OverdueSender.telegram,
    last_run_at: "2026-08-01T09:00:00",
    sent: false,
    reason: null,
    detail: null,
    failing_since: "2026-07-28T09:00:00",
    failures: 9,
    broken: true,
    ...overrides,
  };
  return { sender: health.sender, health };
}

describe("DeliveryStatus", () => {
  it("names the channel and says what it last did", () => {
    renderLocalised(
      <DeliveryStatus record={{ state: "channels", channels: [channel()] }} />,
    );

    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText(/Not working since/)).toBeInTheDocument();
  });

  it("renders nothing at all for a viewer who may not read the record", () => {
    // Hidden, not empty. A member gets a 403 from the endpoint, and that is
    // not evidence about how the household's channels are configured.
    const { container } = renderLocalised(
      <DeliveryStatus record={{ state: "hidden" }} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("says no channel pushes anywhere when an admin has none switched on", () => {
    renderLocalised(
      <DeliveryStatus record={{ state: "channels", channels: [] }} />,
    );

    expect(screen.getByText(en["overdue.deliveryNone"])).toBeInTheDocument();
  });

  it("claims nothing about this page in that sentence", () => {
    // It used to end "They appear here, and nowhere else", which is a claim
    // about the in app channel. `notifications.health` never consults that
    // channel's switch, so with the switch off the panel promised the loans
    // appeared here while the list below said the reminder was off.
    //
    // **The catalogues are pinned, not just the render.**
    // `queryByText(/appear here/)` has no subject once the string is gone: it
    // passes against any page, including one that never rendered anything.
    // Asserting the catalogues is the half that fails if somebody restores the
    // clause.
    for (const catalogue of [en, de]) {
      expect(catalogue["overdue.deliveryNone"]).not.toMatch(RETIRED_CLAIM);
    }

    renderLocalised(
      <DeliveryStatus record={{ state: "channels", channels: [] }} />,
    );

    expect(screen.queryByText(RETIRED_CLAIM)).not.toBeInTheDocument();
  });

  it("has a pattern that would catch the clause coming back", () => {
    // The other half of the pair above. A negative assertion is worth what its
    // pattern is worth, and a pattern matching nothing passes every negative
    // there is. Both retired sentences are quoted here so the pattern has a
    // subject that is not the thing under test.
    expect(
      "No channel sends these reminders anywhere. They appear here, and nowhere else.",
    ).toMatch(RETIRED_CLAIM);
    expect(
      "Kein Kanal verschickt diese Erinnerungen irgendwohin. Sie erscheinen hier und sonst nirgends.",
    ).toMatch(RETIRED_CLAIM);
    expect(en["overdue.deliveryNone"]).not.toMatch(RETIRED_CLAIM);
  });

  it("says so when the record could not be read at all", () => {
    // The third state. A 500 used to render exactly like a member's 403,
    // which on a page that suppresses this query's error meant an admin saw a
    // complete-looking page with no panel and no indication of a fault.
    renderLocalised(<DeliveryStatus record={{ state: "unreadable" }} />);

    expect(
      screen.getByText(en["overdue.deliveryUnreadable"]),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(en["overdue.deliveryNone"]),
    ).not.toBeInTheDocument();
  });
});

/**
 * Each catalogue's note, with the two clauses it is built from.
 *
 * A table rather than an alternation over both languages: an alternation
 * passes an English note that happens to contain the German phrase, and that
 * is the shape of guard this repository keeps finding vacuous.
 */
const CATALOGUES = [
  {
    name: "en",
    note: en["overdue.deliveryNote"],
    names: /last run/,
    denies: /does not record/,
  },
  {
    name: "de",
    note: de["overdue.deliveryNote"],
    names: /letzten lauf/,
    denies: /hält nicht fest/,
  },
];

describe("the wording cannot come to imply a per loan receipt", () => {
  // The single dishonest thing this page could ship. `SENDER_HEALTH` is
  // written once per sender per run and carries no loan id, so nothing here
  // can say a particular borrower was or was not told. The note is the only
  // thing that stops a reader taking a channel's state for one, and a tidy-up
  // that removed it would leave a screen that reads as a delivery receipt with
  // every test still green. So the note is pinned to the lines it qualifies.
  it("prints the note whenever it prints a channel's state", () => {
    renderLocalised(
      <DeliveryStatus record={{ state: "channels", channels: [channel()] }} />,
    );

    expect(screen.getByText(en["overdue.deliveryNote"])).toBeInTheDocument();
  });

  it("prints it beside the no-channel line too", () => {
    // The other arm that draws the heading. A note that appeared on only one
    // of the two would be a note somebody could reach the page without.
    renderLocalised(
      <DeliveryStatus record={{ state: "channels", channels: [] }} />,
    );

    expect(screen.getByText(en["overdue.deliveryNote"])).toBeInTheDocument();
  });

  it("keeps both clauses of the note in both catalogues", () => {
    // **Scoped to what a substring rule can decide, which is not honesty.** A
    // dishonest note carrying both phrases satisfies every assertion here, and
    // the shipped notes are honest because somebody wrote them so. What this
    // decides is narrower and still worth having: that neither of the two
    // clauses the note is built from has been dropped in a rewrite, in either
    // language. The clause that denies the per loan reading is the one with a
    // reader on the other side.
    for (const { name, note, names, denies } of CATALOGUES) {
      expect(note.toLowerCase(), name).toMatch(names);
      expect(note.toLowerCase(), name).toMatch(denies);
    }
  });

  it("has patterns that each fail on their own clause being dropped", () => {
    // **A diagonal, because the version this replaced could not fail.** It
    // asserted `note.match(a) && note.match(b)` was null against one fixture
    // matching neither pattern, so the `&&` short circuited on the first null:
    // measured, it passed with both patterns replaced by /xyzzy/ and /plugh/.
    //
    // One fixture per clause per language, each missing exactly one, asserted
    // separately. A fixture dropping both clauses at once cannot show that
    // either pattern pins anything.
    const dropped = [
      {
        name: "en, the denial dropped",
        text: "endpaper records what each channel did on its last run.",
        gone: /does not record/,
        kept: /last run/,
      },
      {
        name: "en, the run dropped",
        text: "endpaper does not record which reminder reached which borrower.",
        gone: /last run/,
        kept: /does not record/,
      },
      {
        name: "de, the denial dropped",
        text: "endpaper hält fest, was jeder kanal bei seinem letzten lauf getan hat.",
        gone: /hält nicht fest/,
        kept: /letzten lauf/,
      },
      {
        name: "de, the run dropped",
        text: "endpaper hält nicht fest, welche erinnerung wen erreicht hat.",
        gone: /letzten lauf/,
        kept: /hält nicht fest/,
      },
    ];

    for (const { name, text, gone, kept } of dropped) {
      expect(text, name).not.toMatch(gone);
      expect(text, name).toMatch(kept);
    }
  });

  it("does not let one language's evidence answer for the other", () => {
    // The alternation this file started with, `/last run|letzten lauf/`, is
    // satisfied by an English note containing the German phrase. Each
    // catalogue's patterns must reject the other's note outright.
    const [english, german] = CATALOGUES;
    for (const pattern of [english!.names, english!.denies]) {
      expect(german!.note.toLowerCase(), "de against en").not.toMatch(pattern);
    }
    for (const pattern of [german!.names, german!.denies]) {
      expect(english!.note.toLowerCase(), "en against de").not.toMatch(pattern);
    }
  });
});
