/**
 * How this app spells a date and a time, for the locale the member chose.
 *
 * **One home for the format, and the reason is a defect rather than tidiness.**
 * Ten modules each held their own `toLocaleDateString` call, and six of those
 * calls passed no locale at all, so the trash page, the reset request queue and
 * the security record rendered in whatever locale the browser guessed while
 * every other screen rendered in the app's. Measured on this machine: a bare
 * call gives `19/08/2026`, against `8/19/2026` for `en` and `19.8.2026` for
 * `de`. The browser's guess is not a third preference the app tolerates, it is
 * a format belonging to neither catalogue.
 *
 * **The locale is required, and what that buys is narrower than it looks.** It
 * is tempting to say the type checker now refuses the defect, and that is
 * false: every one of the six bare calls was a platform method invoked straight
 * on a `Date`, so no signature in this tree was in their way and a required
 * parameter here is invisible to code that never imports this module. What the
 * requirement actually buys is that the two helpers this module replaces took
 * `locale?`, an affordance whose only use anywhere was one test calling without
 * one, and that affordance is now gone. **The enforcement is the house rule in
 * `frontend/tests/houseRules.test.ts` and nothing else.** Saying otherwise
 * would leave the next reader trusting a check that does not run.
 *
 * **`Intl.DateTimeFormat` rather than `Date.prototype.toLocaleDateString`**, for
 * the reason `lib/nameOrder.ts` reaches for `Intl.Collator`: a formatter carries
 * the locale it was built with, so it can be built once per locale and reused,
 * where the method rebuilds one per call and `BookTable` renders a date per row
 * per page. It is also what makes the house rule's subject one name in one
 * module rather than a family of method spellings.
 *
 * **Every format here renders exactly what the call site it replaced rendered,
 * for every input either spelling could render at all, and that is a constraint
 * rather than an accident.** It makes this a refactor a reviewer can read as one, with the three
 * locale fixes as the only visible change in what a member sees. Verified before
 * the move, over five dates in `en` and `de`: `Intl.DateTimeFormat` with these
 * options equals the `toLocale*String` spelling it replaces in all fifty
 * comparisons, and spelling the numeric options out equals passing none.
 *
 * **An input that is not a timestamp is the one deliberate difference, and it
 * runs in both directions.** `toLocaleDateString` answers `Invalid Date` where
 * `Intl.DateTimeFormat.format` raises `RangeError`, so keeping the old rendering
 * was never available: one of the two is a string on a page and the other is a
 * page down. Both are answered with `""` here, which is neither, and the throw is
 * the reason that decision could not be left to the call sites.
 *
 * **Two of the widths below are drift, and preserving them is deliberate.**
 * `BookDetail` renders an abbreviated month in two panels and a written out
 * month in a third, on one screen, and no decision produced that. Collapsing
 * them is very likely right and it changes what members see on a page nobody
 * filed anything about, so it is not this module's to take: it is in the tracker
 * as the question of whether the book detail screen should spell a month three
 * ways. What is written here is what the app rendered.
 *
 * **What does not live here.** Which timestamp is worth rendering at all stays
 * with the caller: `TrashRow` drops a whole element when there is no date, where
 * a table cell wants an empty string. Absence is answered here, with `""`, so
 * the two local helpers that existed only to pair a null check with a format
 * call are gone; the decision to render nothing at all is still the caller's.
 */

import type { Locale } from "../api/generated/model";

/**
 * The formats this app renders.
 *
 * Named for what a reader sees rather than for the screen that asked, so a
 * second caller of the same shape has a name to reuse instead of a reason to
 * write a sixth.
 *
 * **Spelled out rather than left to the defaults `toLocale*String` applies.**
 * `date` is the one that could have been an empty object and is not: the options
 * a bare call implies live in the specification rather than in this tree, so
 * writing them here is what lets a reader see the format without knowing
 * ECMA-402 by heart. Measured equal to passing none, over four dates in both
 * locales.
 *
 * **`time` carries seconds because the calls it replaces did.** A reset code
 * expiry reading `14:35:07` is noise and probably wants `2-digit` minutes and no
 * seconds, which is in the tracker rather than here: this module changes no
 * rendered string outside the three files whose locale was wrong, and dropping a
 * field is a rendered change.
 */
const FORMATS = {
  date: { year: "numeric", month: "numeric", day: "numeric" },
  shortMonth: { year: "numeric", month: "short", day: "numeric" },
  longMonth: { year: "numeric", month: "long", day: "numeric" },
  monthLabel: { year: "numeric", month: "short" },
  time: { hour: "numeric", minute: "numeric", second: "numeric" },
} as const;

type Format = keyof typeof FORMATS;

/**
 * One formatter per locale per format, built on first use.
 *
 * Keyed on both, for the reason `lib/nameOrder.ts` states about its collators:
 * the app switches language without a reload, so a single instance would carry
 * the locale it happened to be built under into every later render.
 */
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(format: Format, locale: Locale): Intl.DateTimeFormat {
  const key = `${locale}|${format}`;
  const existing = formatters.get(key);
  if (existing) return existing;
  const built = new Intl.DateTimeFormat(locale, FORMATS[format]);
  formatters.set(key, built);
  return built;
}

/**
 * The one place a timestamp becomes a rendered string.
 *
 * **Absent in, empty out**, which is `lib/year.ts`'s shape for a value that may
 * not be there, and which two call sites had each written for themselves.
 *
 * **An unparseable timestamp is empty too, rather than `Invalid Date`.** Every
 * input is an ISO field the API sent, so this is not expected to fire; it is
 * here because this is the only place that can decide it, and the alternative
 * puts the words `Invalid Date` on a page.
 */
function render(
  format: Format,
  iso: string | null | undefined,
  locale: Locale,
): string {
  if (iso === null || iso === undefined || iso === "") return "";
  return formatted(format, new Date(iso), locale);
}

/**
 * The only place in this module that formats a `Date`, and therefore the only
 * place the invalid date guard is written.
 *
 * **One site by construction rather than two by inspection**, which is the same
 * rule this whole module exists to apply, turned on itself. The guard was written
 * twice, once here and once in `monthLabel`, and two copies of a rule are correct
 * exactly until somebody adds the third call: `Intl.DateTimeFormat.format` throws
 * on an invalid date, and a throw from inside a render replaces the whole app
 * shell. Removing this indirection puts that back.
 */
function formatted(format: Format, when: Date, locale: Locale): string {
  if (Number.isNaN(when.getTime())) return "";
  return formatterFor(format, locale).format(when);
}

/** The date a timestamp falls on, at its plainest: `8/19/2026`, `19.8.2026`. */
export function numericDate(
  iso: string | null | undefined,
  locale: Locale,
): string {
  return render("date", iso, locale);
}

/** The date a timestamp falls on, month abbreviated: `Aug 19, 2026`. */
export function shortMonthDate(
  iso: string | null | undefined,
  locale: Locale,
): string {
  return render("shortMonth", iso, locale);
}

/** The date a timestamp falls on, month written out: `August 19, 2026`. */
export function longMonthDate(
  iso: string | null | undefined,
  locale: Locale,
): string {
  return render("longMonth", iso, locale);
}

/** The clock time a timestamp falls at: `10:00:00 AM`, `10:00:00`. */
export function clockTime(
  iso: string | null | undefined,
  locale: Locale,
): string {
  return render("time", iso, locale);
}

/**
 * A `YYYY-MM` bucket as a month a reader recognises: `Aug 2026`.
 *
 * **The bucket key is parsed here rather than at its caller, and that is the one
 * seam decision in this module worth arguing.** `lib/year.ts` draws the line the
 * other way for its readers: a rule that has to know how to get a string out of
 * a SQLite cell is a fact about that container and stays at the reader. A
 * `YYYY-MM` key is not a container though, it is a date written short, so
 * reading it is part of what a date is. Leaving it at the caller would put a
 * formatting call back outside this module and cost the house rule an exemption,
 * and an exemption stating an opinion about one file's input is the row that
 * makes a rule stop closing its class.
 *
 * **Built at local midnight rather than parsed as UTC**, which is what the
 * statistics page did and is right for a label: a month bucket has no instant,
 * and parsing `2026-01` as UTC puts it in December for anybody west of
 * Greenwich.
 *
 * A key that is not two parts renders as nothing, which is also what that page
 * did with it: a bucket label is not worth an error boundary.
 *
 * **Neither guard stops a malformed key rendering the wrong month, and only the
 * throw is closed.** A key can pass both and still mislead: `2026-13` is
 * January 2027 and `2026-00` December 2025, because month arithmetic rolls into
 * the neighbouring year; `2026-08-19` silently drops the day, the split taking
 * its first two parts; and `0026-08` is August **1926**, because the two argument
 * `Date` constructor maps years 0 to 99 onto 1900 to 1999. Every one of these
 * rendered identically before this module existed, from the same arithmetic, so
 * the residual is inherited rather than introduced, and it is written down because
 * a reader who sees two guards will otherwise take them for "a malformed bucket
 * key cannot mislead". It cannot mislead only by throwing.
 *
 * **And a key that is two parts which are not numbers renders as nothing too,
 * which the two part check alone did not give.** `Intl.DateTimeFormat.format`
 * raises `RangeError` on an invalid date where `toLocaleDateString` returned the
 * string `Invalid Date`, so `2026-XX` passed the split, reached the formatter and
 * **threw from inside a `map` during render**. The only error boundary is the
 * outermost wrapper in `app/providers.tsx`, outside every provider and every
 * route, so what a malformed bucket replaced was the **whole app shell**, nav
 * included, until the member reloaded. That is the one way this module could be
 * worse than the code it replaced, which rendered a bad label instead, and it is
 * why the guard is on the built date rather than on the string.
 */
export function monthLabel(yearMonth: string, locale: Locale): string {
  const [year, month] = yearMonth.split("-");
  if (!year || !month) return "";
  return formatted(
    "monthLabel",
    new Date(Number(year), Number(month) - 1),
    locale,
  );
}
