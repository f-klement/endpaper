/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/ProviderSection.tsx.
 *
 * The provider list: which catalogues are asked, and in what order.
 *
 * **Two properties carry the weight here.** A press must reach the server as a
 * whole roster rather than a patch, because a partial list would be read as an
 * instruction about the sources it omits; and a burst of presses must be one
 * request, because reordering is done by pressing a button four times.
 *
 * Fake timers with `fireEvent`, never `user-event`: it schedules its own async
 * work and deadlocks against them, which is the house rule for every debounce
 * test here.
 */

import { fireEvent, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CatalogueSource,
  type CatalogueSourceOut,
  type SettingsOut,
} from "../../../../../src/api/generated/model";
import { de, en } from "../../../../../src/i18n";
import ProviderSection from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/ProviderSection";
import { renderLocalised } from "../../../../utils";

/** The seeded roster, in the order a new install asks it. */
const ROSTER: CatalogueSourceOut[] = [
  row("dnb", { asked_first: true }),
  row("k10plus", { asked_first: true }),
  row("oenb"),
  row("open_library"),
  row("google_books", {
    needs_a_key: true,
    has_key: false,
    ready: false,
  }),
  row("bnf", { answers_lookup: false }),
  row("loc", { answers_lookup: false }),
];

function row(
  source: string,
  over: Partial<CatalogueSourceOut> = {},
): CatalogueSourceOut {
  return {
    source: source as CatalogueSourceOut["source"],
    enabled: true,
    answers_lookup: true,
    answers_search: true,
    asked_first: false,
    needs_a_key: false,
    has_key: true,
    ready: true,
    serves_groups: [],
    ...over,
  };
}

function draw(sources: CatalogueSourceOut[] = ROSTER) {
  const onSave = vi.fn();
  renderLocalised(
    <ProviderSection
      settings={{ catalogue_sources: sources } as SettingsOut}
      onSave={onSave}
    />,
  );
  return onSave;
}

/** Run out the debounce the component collects a burst of presses with. */
function settle() {
  act(() => {
    vi.advanceTimersByTime(1000);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ProviderSection", () => {
  it("lists every catalogue in the order the server sent", () => {
    draw();
    const listed = screen
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "");
    expect(listed).toHaveLength(ROSTER.length);
    expect(listed[0]).toContain("German National Library");
    expect(listed[1]).toContain("K10plus");
    expect(listed[6]).toContain("Library of Congress");
  });

  it("names every catalogue on screen", () => {
    draw();
    for (const name of [
      "German National Library",
      "K10plus",
      "Austrian National Library",
      "Open Library",
      "Google Books",
      "National Library of France",
      "Library of Congress",
    ]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("sends the whole roster when one source moves up", () => {
    const onSave = draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    settle();

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(
      onSave.mock.calls[0]?.[0].catalogue_sources.map(
        (entry: { source: string }) => entry.source,
      ),
    ).toEqual([
      "dnb",
      "oenb",
      "k10plus",
      "open_library",
      "google_books",
      "bnf",
      "loc",
    ]);
  });

  it("sends every source rather than only the one that moved", () => {
    const onSave = draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    settle();
    expect(onSave.mock.calls[0]?.[0].catalogue_sources).toHaveLength(
      ROSTER.length,
    );
  });

  it("collects a burst of presses into one save", () => {
    const onSave = draw();
    const up = () =>
      fireEvent.click(screen.getByLabelText("Move Library of Congress up"));
    up();
    up();
    up();
    settle();
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("moves a source as many places as it was pressed", () => {
    const onSave = draw();
    const up = () =>
      fireEvent.click(screen.getByLabelText("Move Library of Congress up"));
    up();
    up();
    settle();
    const order = onSave.mock.calls[0]?.[0].catalogue_sources.map(
      (entry: { source: string }) => entry.source,
    );
    expect(order.indexOf("loc")).toBe(4);
  });

  it("cannot move the first source up", () => {
    draw();
    expect(
      screen.getByLabelText("Move German National Library up"),
    ).toBeDisabled();
  });

  it("cannot move the last source down", () => {
    draw();
    expect(
      screen.getByLabelText("Move Library of Congress down"),
    ).toBeDisabled();
  });

  it("announces where a source landed", () => {
    draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    expect(
      screen.getByText("Austrian National Library moved to position 2 of 7."),
    ).toBeInTheDocument();
  });

  it("keeps the saved banner unambiguous by not being a second status", () => {
    draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("switches a source off without reordering anything", () => {
    const onSave = draw();
    fireEvent.click(screen.getByLabelText("Google Books"));
    settle();
    const sent = onSave.mock.calls[0]?.[0].catalogue_sources;
    expect(sent.map((entry: { source: string }) => entry.source)).toEqual(
      ROSTER.map((entry) => entry.source),
    );
    expect(
      sent.find((entry: { source: string }) => entry.source === "google_books")
        .enabled,
    ).toBe(false);
  });

  it("names the card below when the key is there and the source is off", () => {
    // The symptom this section exists to remove, produced by its own first fix:
    // a library holding a Google Books key was told to add one.
    // Replaced in place rather than prepended: prepending left the original
    // google_books row further down the list, so both messages rendered and the
    // test would have passed on the wrong one.
    draw(
      ROSTER.map((entry) =>
        entry.source === "google_books" ? { ...entry, has_key: true } : entry,
      ),
    );
    expect(
      screen.getByText(
        "A key is stored, but this catalogue is switched off in its own card below.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Needs an API key. Add one below, or it cannot answer.",
      ),
    ).not.toBeInTheDocument();
  });

  it("keeps focus on the row when a move disables the button just pressed", () => {
    // A disabled element drops focus to the body, so without this the press
    // that lands a row at an end silently ends the run.
    draw();
    const up = screen.getByLabelText("Move K10plus up");
    up.focus();
    fireEvent.click(up);
    expect(document.activeElement).toBe(
      screen.getByLabelText("Move K10plus down"),
    );
  });

  it("keeps focus on the row at the other end too", () => {
    draw();
    const down = screen.getByLabelText("Move National Library of France down");
    down.focus();
    fireEvent.click(down);
    expect(document.activeElement).toBe(
      screen.getByLabelText("Move National Library of France up"),
    );
  });

  it("leaves focus alone for a move that lands in the middle", () => {
    draw();
    const up = screen.getByLabelText("Move Open Library up");
    up.focus();
    fireEvent.click(up);
    expect(document.activeElement).toBe(up);
  });

  it("says when a source cannot answer for want of a key", () => {
    draw();
    expect(
      screen.getByText("Needs an API key. Add one below, or it cannot answer."),
    ).toBeInTheDocument();
  });

  it("says when a source has no say in scanning a barcode", () => {
    draw();
    expect(
      screen.getAllByText(
        "Answers title searches only, so its position does not affect scanning.",
      ),
    ).toHaveLength(2);
  });

  it("says when a source has no say in a title search", () => {
    // **The mirror of the test above, missing until a source needed it.**
    // `answers_search` was on the wire and read by nothing, so a lookup-only
    // source rendered as "asked only when the ones above it find nothing", with
    // nothing saying its position never affects a title search. One row, and
    // the assertion is that it does not fall through to the ordering status.
    // **Its own rows, not the shared roster.** Adding a row there moved the
    // ordering assertions in four other tests, which is the shared-fixture trap:
    // a row added for one behaviour changes every test that counts or positions.
    draw([row("dnb"), row("nkp", { answers_search: false })]);
    expect(
      screen.getByText(
        "Answers scans only, so its position does not affect a title search.",
      ),
    ).toBeInTheDocument();
  });

  it("says a national catalogue is asked only for the ISBNs it could hold", () => {
    // **Its own rows rather than the shared roster**, for the reason the test
    // above states: a row added to `ROSTER` moves the ordering assertions in
    // four other tests. Two rows, so the NLG is not in the leading pair.
    draw([
      row("dnb"),
      row("k10plus"),
      row("nlg", { serves_groups: ["978-618", "978-960"] }),
    ]);
    expect(
      screen.getByText(
        "Asked only when the ones above it find nothing, and only for ISBNs " +
          "beginning 978-618 or 978-960.",
      ),
    ).toBeInTheDocument();
  });

  it("joins two groups with a disjunction rather than a comma", () => {
    // "beginning 978-618, 978-960" reads as "and" where the rule is "or", and a
    // reader checking a barcode against it would take it as needing both.
    // `Intl.ListFormat` also gets German's "oder" without a second string.
    draw([
      row("dnb"),
      row("k10plus"),
      row("nlg", { serves_groups: ["978-618", "978-960"] }),
    ]);
    expect(screen.getByText(/978-618 or 978-960/)).toBeInTheDocument();
    expect(screen.queryByText(/978-618, 978-960/)).not.toBeInTheDocument();
  });

  it("names a single group without a conjunction", () => {
    // The arm that stops the formatter being swapped for a hard coded " or ".
    draw([
      row("dnb"),
      row("k10plus"),
      row("oenb", { serves_groups: ["978-3"] }),
    ]);
    expect(
      screen.getByText(
        "Asked only when the ones above it find nothing, and only for ISBNs " +
          "beginning 978-3.",
      ),
    ).toBeInTheDocument();
  });

  it("says a lookup only catalogue is regional as well", () => {
    // **Both facts, where the screen used to show one.** `lookupOnly` returned
    // before the regional branch, so a catalogue that answers scans only and
    // collects one registration group rendered as though it were asked about
    // every ISBN. The Czech National Library is that shape today, and the
    // alternative fix, forbidding the combination in the backend constant,
    // would have barred the next lookup only national catalogue from a remit.
    draw([
      row("dnb"),
      row("k10plus"),
      row("nkp", { answers_search: false, serves_groups: ["978-80"] }),
    ]);
    expect(
      screen.getByText(
        "Answers scans only, and only for ISBNs beginning 978-80, so its " +
          "position does not affect a title search.",
      ),
    ).toBeInTheDocument();
  });

  it("does not claim a promoted lookup only catalogue is regional", () => {
    // **The rendered half of the sweep in `tests/lib/providerStatus.test.ts`.**
    // The combined line returned before `asked_first` was read, so a catalogue
    // in the leading pair was told it answers only for Czech ISBNs while
    // sitting in a tier nothing filters. Reachable: a plan of
    // `nkp, k10plus, dnb` gives the NKP exactly this row.
    draw([
      row("nkp", {
        answers_search: false,
        asked_first: true,
        serves_groups: ["978-80"],
      }),
      row("k10plus", { asked_first: true }),
      row("dnb"),
    ]);
    expect(
      screen.getByText(
        "Answers scans only, so its position does not affect a title search.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/978-80/)).not.toBeInTheDocument();
  });

  it("leaves a lookup only catalogue with no remit alone", () => {
    // The other half of the diagonal, or the branch above would swallow every
    // lookup only source.
    draw([row("dnb"), row("k10plus"), row("nkp", { answers_search: false })]);
    expect(
      screen.getByText(
        "Answers scans only, so its position does not affect a title search.",
      ),
    ).toBeInTheDocument();
  });

  it("says a promoted national catalogue is asked on every scan after all", () => {
    // **The arm that stops the rule above overreaching.** The leading tier is
    // never filtered by a remit, so a source a household has promoted into it
    // is asked about every ISBN, and the regional line would be the screen
    // promising something the server does not do.
    draw([row("nlg", { asked_first: true, serves_groups: ["978-960"] })]);
    expect(
      screen.getByText(
        "Asked on every scan, with the others at the top of this list.",
      ),
    ).toBeInTheDocument();
  });

  it("says which sources are asked on every scan", () => {
    draw();
    expect(
      screen.getAllByText(
        "Asked on every scan, with the others at the top of this list.",
      ),
    ).toHaveLength(2);
  });

  it("renders nothing rather than looping when the list is absent", () => {
    // `catalogue_sources` is optional on the generated type. A fresh `[]`
    // fallback would be a new array on every render, and the effect that
    // re-seeds from the server depends on its identity, so the pair would
    // render forever. This test times out rather than failing if that returns.
    const onSave = vi.fn();
    renderLocalised(
      <ProviderSection settings={{} as SettingsOut} onSave={onSave} />,
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("says plainly that a switched off source is never asked", () => {
    draw([row("dnb", { enabled: false }), ...ROSTER.slice(1)]);
    expect(
      screen.getByText("Off. This catalogue is never asked."),
    ).toBeInTheDocument();
  });

  // `sourceName` builds its key with a template literal and casts the result to
  // `MessageKey`, so the compiler cannot see a missing one and the screen would
  // draw the key itself. A source is added to the enum by regenerating the
  // client, which is a step that touches no message catalogue at all.
  it.each(Object.values(CatalogueSource))(
    "has a name in every catalogue for %s",
    (source) => {
      for (const [locale, messages] of Object.entries({ en, de })) {
        expect(
          Object.keys(messages),
          `providers.name.${source} is missing from ${locale}`,
        ).toContain(`providers.name.${source}`);
      }
    },
  );
});
