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
import { endOfDay } from "../factories";

// **Carries its offset, because the API does.** `schemas.common.UtcDateTime`
// puts one on every `date-time` field this server sends, so a bare wall clock
// here is a payload the server cannot produce. The arms below therefore read an
// instant rendered in the suite's zone rather than a string that parsed back to
// itself.
//
// **`date-time` and not every dated field**, which is the narrower claim and the
// true one. Four properties are `format: date`, and all four are the purchase
// date: a bare `YYYY-MM-DD` with no clock to carry an offset in the first place.
// Nothing in this file renders one.
//
// Midday, so the rendered day is the stamp's own day rather than its
// neighbour's: the suite's zone is pinned in `tests/setup.ts`, and midday UTC
// sits a few hours clear of a date boundary there. That is a property of the
// pin and not of midday, which is why the pin is named rather than restated.
const WHEN = "2026-08-19T12:00:00Z";

describe("numericDate", () => {
  it("renders the plainest date the app shows, per locale", () => {
    expect(numericDate(WHEN, Locale.en)).toBe("8/19/2026");
    expect(numericDate(WHEN, Locale.de)).toBe("19.8.2026");
  });

  it("renders in the zone the device is in now, not the one it was built in", () => {
    // **The formatter cache's zone key, which nothing else observes.** A
    // formatter with no `timeZone` option resolves the ambient zone once, when
    // it is built, so a cache keyed on locale and format alone lets the first
    // render of a pair decide the zone for the whole session. Reverting that key
    // leaves the full suite green, so without this arm the line rests on a
    // measurement and the figures beside it read as an invitation to undo it.
    //
    // The first call builds and caches under the pinned zone; the second asks
    // for the same locale and format from a different one. Kiritimati is +14
    // against the pin's -09:30, so midday UTC falls on the following day there
    // and a stale formatter answers with the wrong date rather than a wrong
    // clock time, which is the louder failure.
    expect(numericDate(WHEN, Locale.en)).toBe("8/19/2026");

    const pinned = process.env.TZ;
    try {
      process.env.TZ = "Pacific/Kiritimati";
      // **The second zone is proved to have taken, for the reason
      // `tests/setup.ts` proves the pin.** An unresolvable zone is ignored
      // silently, with no throw and no warning, so on a runtime shipping the
      // pinned zone but not this one the assertion below would fail with
      // `expected '8/19/2026' to be '8/20/2026'`, which is character for
      // character what a genuinely broken cache key produces. Without this
      // line the arm refuses a correct implementation and names the wrong
      // cause.
      expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(
        "Pacific/Kiritimati",
      );
      expect(numericDate(WHEN, Locale.en)).toBe("8/20/2026");
    } finally {
      // Restored here rather than left to the teardown, because every later
      // arm in this file reads the pinned zone. The teardown in
      // `tests/setup.ts` is the backstop that names a forgotten restore
      // instead of letting it poison the rest of the run.
      process.env.TZ = pinned;
    }
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
    //
    // **04:35 and not 14:05, because the stamp carries an offset and the suite
    // has a zone.** Both are properties of the tree rather than of this arm:
    // the server sends UTC with an offset, and `tests/setup.ts` pins where the
    // run is. The pair still differs by the twelve hour clock, which is what
    // this arm is for.
    expect(normalisedSpaces(clockTime("2026-08-19T14:05:07Z", Locale.en))).toBe(
      "4:35:07 AM",
    );
    expect(clockTime("2026-08-19T14:05:07Z", Locale.de)).toBe("04:35:07");
  });
});

describe("endOfDayInstant", () => {
  /**
   * The picked day, named once because three arms below have to agree with it.
   *
   * **Every expectation here is interpolated from this rather than written
   * beside it.** Two literals that have to agree are an arm one edit can
   * disarm: change the input day, leave the expected string, and the arm
   * passes while asserting nothing about the day it names. Driven on the first
   * version of the UTC arm below, which had exactly that shape.
   */
  const PICKED = "2026-08-19";
  const [YEAR, MONTH, DAY] = PICKED.split("-").map(Number);

  it("sends the end of the picked day as an instant", () => {
    // **Derived rather than written out, and it stays derived now that a
    // literal would work.** `tests/setup.ts` pins the suite's zone, so the
    // answer no longer depends on where the run is and could be spelled out.
    // It is not, because the derivation is also what states the rule: the end
    // of the picked day is 23:59:59 **where the viewer is**, and a literal
    // instant says that to nobody. It would also have to be re-derived by hand
    // the day the pin moves, which is the same work with a wrong answer
    // available.
    //
    // The numeric constructor rather than the parser the module uses, so this
    // states the intent in a second expression instead of calling the first.
    // Its parts come off `PICKED`, so there is no second day to disagree with
    // the first; the month is one based in the string and zero based here.
    //
    // **This is the arm that discriminates the regression**, and it does so
    // only because the pinned zone is not UTC: the two readings of the picked
    // day are the same function under UTC, so this equality was vacuous there.
    expect(endOfDayInstant(PICKED)).toBe(
      new Date(YEAR!, MONTH! - 1, DAY!, 23, 59, 59).toISOString(),
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
    // The arm below is what discriminates the UTC misreading, and it can
    // because the pinned zone is not UTC.
    expect(endOfDayInstant(PICKED)).toMatch(/Z$/);
  });

  it("reads the picked day where the viewer is, not as a UTC clock", () => {
    // **The regression named, rather than caught as a side effect.** The old
    // spelling sent `${day}T23:59:59` with no offset and the server read a
    // member's wall clock as a UTC clock, so the deadline landed late by the
    // viewer's offset. That mutant returns exactly the string below, in every
    // zone, because it is the UTC parse written out.
    //
    // The equality above already fails on it. This arm exists because that one
    // fails for a reason a reader has to derive, where this one fails by
    // naming the wrong answer.
    //
    // **What goes past it**: it says nothing about the offset being the right
    // one, only that the picked day was not read as UTC. The equality above is
    // what holds the value, and under a UTC pin this arm would be red rather
    // than vacuous, which is the failure mode worth having.
    expect(endOfDayInstant(PICKED)).not.toBe(`${PICKED}T23:59:59.000Z`);
  });

  it("is what the deadline fixtures are built to be", () => {
    // **The fixtures' own helper, pinned against the door it stands in for.**
    // `tests/factories.ts` builds `due_at` with its own numeric constructor
    // rather than by calling this module, so that an assertion over a fixture
    // cannot agree with the code by construction. That independence is right
    // and it leaves the two free to drift, and nothing observed the drift:
    // driven, with the helper rewritten to parse the day as UTC, which is this
    // branch's own regression, all three consumer files stayed green at 55 of
    // 55. The badge arm in `LoanRow` provably cannot see it, because its
    // expectation is derived from the helper and both sides move together.
    //
    // So the fixture keeps its own constructor and this is the one place the
    // two derivations are required to agree. It is what reds when they part.
    expect(endOfDay(PICKED)).toBe(endOfDayInstant(PICKED));
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
