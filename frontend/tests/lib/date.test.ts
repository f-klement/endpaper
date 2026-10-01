/**
 * Tests for src/lib/date.
 *
 * @vitest-environment node
 *
 * **The German arm is the point of this file, not a second case.** Every format
 * is asserted in both locales, because the defect this module was written for
 * was three screens rendering in the browser's locale while the rest of the app
 * rendered in the app's, and a suite that only ever asserts English cannot see
 * that. The two rendered strings differ for every one of the five formats below,
 * which is what makes each pair an observation rather than a restatement.
 *
 * **Exact strings rather than a pattern**, so a rendering change is loud. The
 * cost is that an ICU version bump can redden this file over something nobody
 * decided: a month abbreviation can gain a letter between versions, `Sep.` to
 * `Sept.` in German being the one that has actually moved. That is the right
 * trade, because the alternative is the `toMatch(/2026/)` that the test this
 * replaced used, which passes on every format this module could possibly
 * return. Where the difference is a separator rather than a word it is
 * normalised instead; see `normalisedSpaces` below for the one case and why.
 *
 * **August throughout, deliberately.** It is spelled the same in every ICU
 * version either locale has shipped, so a red arm here is this module changing
 * rather than its runtime.
 */

import { describe, expect, it } from "vitest";

import { Locale } from "../../src/api/generated/model";
import {
  clockTime,
  endOfDayInstant,
  longMonthDate,
  monthLabel,
  numericDate,
  shortMonthDate,
} from "../../src/lib/date";

// Midday, so no timezone offset can move the day and make a date assertion
// depend on where the suite runs.
const WHEN = "2026-08-19T12:00:00";

describe("numericDate", () => {
  it("renders the plainest date the app shows, per locale", () => {
    expect(numericDate(WHEN, Locale.en)).toBe("8/19/2026");
    expect(numericDate(WHEN, Locale.de)).toBe("19.8.2026");
  });
});

describe("shortMonthDate", () => {
  it("abbreviates the month, per locale", () => {
    expect(shortMonthDate(WHEN, Locale.en)).toBe("Aug 19, 2026");
    expect(shortMonthDate(WHEN, Locale.de)).toBe("19. Aug. 2026");
  });
});

describe("longMonthDate", () => {
  it("writes the month out, per locale", () => {
    expect(longMonthDate(WHEN, Locale.en)).toBe("August 19, 2026");
    expect(longMonthDate(WHEN, Locale.de)).toBe("19. August 2026");
  });
});

/**
 * The space before `AM` is an ICU version detail, not a decision this app made.
 *
 * ICU 72 changed it from a plain space to a narrow no break space, U+202F, and
 * which one a run gets depends on the runtime the suite happens to ship. So the
 * separator is normalised and everything else is compared exactly: asserting the
 * codepoint would make this file red on a bun bump that changed nothing anybody
 * can see, and loosening the whole assertion instead would give up the part that
 * is worth pinning.
 */
function normalisedSpaces(value: string): string {
  return value.replace(/\s/g, " ");
}

describe("clockTime", () => {
  it("renders a clock time, per locale", () => {
    // The twelve hour clock is the observable difference here, and it is the
    // one that made a bare call visibly wrong rather than merely inconsistent.
    expect(normalisedSpaces(clockTime("2026-08-19T14:05:07", Locale.en))).toBe(
      "2:05:07 PM",
    );
    expect(clockTime("2026-08-19T14:05:07", Locale.de)).toBe("14:05:07");
  });
});

describe("endOfDayInstant", () => {
  it("sends the end of the picked day as an instant", () => {
    // **Derived rather than written out, and that is forced.** The answer
    // depends on where the run is: measured, `2026-08-19T21:59:59.000Z` in
    // `Europe/Berlin` against `2026-08-19T23:59:59.000Z` under the suite's own
    // UTC. A literal pins whichever zone the run happened to be in.
    //
    // The numeric constructor rather than the parser the module uses, so this
    // states the intent in a second expression instead of calling the first.
    // Month 7 is August.
    expect(endOfDayInstant("2026-08-19")).toBe(
      new Date(2026, 7, 19, 23, 59, 59).toISOString(),
    );
  });

  it("carries an offset, which is the whole reason it exists", () => {
    // The old spelling sent the bare wall clock and the server read it as a
    // UTC clock, so a deadline landed late by the viewer's offset.
    //
    // **This restates the intent; it does not discriminate a case the equality
    // admits.** It cannot fail while that one passes, because the comparison's
    // right hand side is a `toISOString()` and every one of those ends in `Z`.
    // It is kept because it names the behaviour as a sentence, and because it
    // is the floor if somebody later weakens the equality to a looser match.
    //
    // **And no further assertion can say more here**, which is written down so
    // the next reader stops trying. Under `TZ=UTC`, which is what the suite
    // container runs, this function and the one regression it exists to
    // prevent, parsing the picked day as UTC rather than as local, are the
    // same function: no expression over their output tells them apart, and a
    // round trip through `Date` does not either. Pinning the suite's zone is
    // the only thing that can catch it and is filed as work of its own.
    expect(endOfDayInstant("2026-08-19")).toMatch(/Z$/);
  });

  it("answers nothing for a day that is not there", () => {
    expect(endOfDayInstant(null)).toBeNull();
    expect(endOfDayInstant(undefined)).toBeNull();
    expect(endOfDayInstant("")).toBeNull();
  });

  it("answers nothing for a day it cannot read", () => {
    // `toISOString` raises `RangeError` on an invalid date, and this is called
    // from a click handler: thrown from there it replaces the app shell, since
    // `app/providers.tsx` holds the only error boundary.
    expect(endOfDayInstant("not a date")).toBeNull();
    expect(endOfDayInstant("2026-13-01")).toBeNull();
    expect(endOfDayInstant("2026-")).toBeNull();
  });

  it("answers nothing for a year the server cannot parse", () => {
    // Past 9999 `toISOString` emits the expanded form,
    // `+010000-01-01T00:00:00.000Z`, and the server answers 422 for that
    // spelling. `lib/digitalReference.ts` carries the same bound over a
    // `File.lastModified`, and the year is read in UTC at both sites because
    // the expanded form is a property of the spelling rather than of the local
    // date.
    //
    // **One residual is left open rather than closed**: `2026-02-30` is an
    // impossible day that `Date` rolls over into March, so it returns an
    // instant rather than null. A date input cannot produce one, and the
    // string this function replaced rolled it identically.
    expect(endOfDayInstant("10000-01-01")).toBeNull();
    expect(endOfDayInstant("275760-09-13")).toBeNull();
  });
});

describe("monthLabel", () => {
  it("renders a bucket key as a month, per locale", () => {
    expect(monthLabel("2026-08", Locale.en)).toBe("Aug 2026");
    expect(monthLabel("2026-08", Locale.de)).toBe("Aug. 2026");
  });

  it("builds the month at local midnight, not as UTC", () => {
    // **The bucket the naive parse gets wrong.** `new Date("2026-01")` is
    // parsed as UTC midnight, which is the previous December for anybody west
    // of Greenwich, so a January bucket would be labelled December. Asserting
    // January is asserting the local construction the statistics page had and
    // this module kept.
    expect(monthLabel("2026-01", Locale.en)).toBe("Jan 2026");
  });

  it("answers nothing for a key that is not a year and a month", () => {
    expect(monthLabel("", Locale.en)).toBe("");
    expect(monthLabel("2026", Locale.en)).toBe("");
  });

  it("answers nothing for a two part key whose parts are not numbers", () => {
    // **The one way this module could be worse than the code it replaced.**
    // `Intl.DateTimeFormat.format` raises `RangeError` on an invalid date where
    // `toLocaleDateString` returned the string `Invalid Date`, so a key that
    // passes the two part split and then fails to parse threw from inside a
    // `map` during render. The only error boundary is the outermost wrapper in
    // `app/providers.tsx`, so that replaced the whole app shell rather than one
    // page. A bad label is not worth the app, which is what the split check
    // already said and what this extends to the half it did not cover.
    //
    // **Only the throw is closed.** `2026-13`, `2026-08-19` and `0026-08` all
    // pass both guards and render a misleading month; the module docstring names
    // them, and every one behaved the same way before this module existed.
    expect(monthLabel("2026-XX", Locale.en)).toBe("");
    expect(monthLabel("not-here", Locale.en)).toBe("");
    expect(monthLabel("2026-", Locale.en)).toBe("");
  });
});

describe("every format", () => {
  it("answers nothing for a timestamp that is not there", () => {
    // One rule for absence, here, rather than the null check two call sites had
    // each written beside their own format call.
    for (const format of [
      numericDate,
      shortMonthDate,
      longMonthDate,
      clockTime,
    ]) {
      expect(format(null, Locale.en)).toBe("");
      expect(format(undefined, Locale.en)).toBe("");
      expect(format("", Locale.en)).toBe("");
    }
  });

  it("answers nothing for a timestamp it cannot read", () => {
    // Not expected from the API, and here because this is the only place that
    // can decide it: the alternative renders the words `Invalid Date` onto a
    // page.
    for (const format of [
      numericDate,
      shortMonthDate,
      longMonthDate,
      clockTime,
    ]) {
      expect(format("not a date", Locale.en)).toBe("");
    }
  });

  it("gives a different answer per locale, so the pairs above are observations", () => {
    // **The diagonal over the formats, and it earns its place twice.** It fails
    // if any format stops depending on the locale it is handed, which is the
    // defect in one line; and it fails if two formats collapse into one, which
    // is what a refactor unifying the two month widths would do silently.
    const rendered = [
      numericDate(WHEN, Locale.en),
      shortMonthDate(WHEN, Locale.en),
      longMonthDate(WHEN, Locale.en),
      clockTime(WHEN, Locale.en),
      monthLabel("2026-08", Locale.en),
    ];
    expect(new Set(rendered).size).toBe(rendered.length);

    for (const [render, argument] of [
      [numericDate, WHEN],
      [shortMonthDate, WHEN],
      [longMonthDate, WHEN],
      [clockTime, WHEN],
      [monthLabel, "2026-08"],
    ] as const) {
      expect(render(argument, Locale.en)).not.toBe(render(argument, Locale.de));
    }
  });
});
