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
