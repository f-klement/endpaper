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
 * One formatter per locale per format **per zone**, built on first use.
 *
 * Keyed on locale and format for the reason `lib/nameOrder.ts` states about its
 * collators: the app switches language without a reload, so a single instance
 * would carry the locale it happened to be built under into every later render.
 *
 * **The zone is in the key for exactly the same reason, and it was missing.** A
 * formatter with no `timeZone` option resolves the ambient zone **once, when it
 * is built**, and then renders every later date in that zone whatever the
 * platform now says. So a key of locale and format alone means the first render
 * of a given pair decides the zone for the rest of the session. A member can
 * move the device's zone while the app is open, which is the live case; the
 * latent one is any caller that builds a formatter before something else sets
 * the zone, and a test suite pinning its own zone is that caller.
 *
 * **The cost is one ambient zone read per format call, which is a fraction of
 * the formatter build it prevents and is of the same order as the `format()`
 * it sits in front of.** That second half is the part worth saying: the key is
 * affordable because of the ratio against the build, not because the read is
 * free against a render.
 *
 * **No figure is published here, deliberately, and the spread is why.**
 * Measured on bun 1.4.2 over 200,000 iterations by three seats: the zone read
 * came out anywhere between 0.82 and 2.12 `format()` calls, the build cost
 * disagreed across seats by a factor of 1.6, and the ratio against
 * `getTimezoneOffset()` by a factor of 8. Only the order of each survived
 * re-derivation, so a point or an interval written here would be one seat's run
 * presented as a property of the code. Re-derive on the machine in hand if the
 * cost ever matters.
 *
 * **Not keyed on `getTimezoneOffset()`, which is cheaper and wrong.** None of
 * the formats above renders a zone name, so two zones at the same offset agree
 * today and disagree for a date in the other half of the year: measured,
 * `Europe/London` and `Africa/Abidjan` are both 0 in January, and in July
 * London is an hour off where Abidjan has not moved. An offset key serves one
 * zone's formatter for the other's summer dates. The zone name is the thing
 * that decides the rendering, so it is the thing in the key.
 */
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(format: Format, locale: Locale): Intl.DateTimeFormat {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const key = `${locale}|${format}|${zone}`;
  const existing = formatters.get(key);
  if (existing) return existing;
  const built = new Intl.DateTimeFormat(locale, FORMATS[format]);
  formatters.set(key, built);
  return built;
}

/**
 * A bare `YYYY-MM-DD`, which is a calendar date and not an instant.
 *
 * **Derived from what the wire says rather than from what callers look like.**
 * The API declares a field `format: date` exactly when it sends this shape, and
 * RFC 3339 spells a `full-date` as these ten characters and a `date-time` with a
 * `T` in the middle, so **no value carrying a clock can match this, whatever the
 * schema grows**. That half needs no census. The half that does is which fields
 * are date-only, and today it is one:
 *
 * ```sh
 * jq '[paths(type=="object" and .format=="date")] | length' frontend/openapi.json
 * ```
 *
 * answers 4, and dropping the `length` names them: `purchased_at` on each of
 * `BookColumns`, `BookDetailsUpdate`, `BookOut` and `CopyCreate`, which is one
 * field reaching the wire through four models.
 *
 * **The alternative was to declare the kind at the caller, and it was refused on
 * that count.** Those four properties are one field. Against it, from
 * `frontend/`:
 *
 * ```sh
 * grep -rnoE '\b(numericDate|shortMonthDate|longMonthDate|clockTime)\(' \
 *   src --include='*.ts' --include='*.tsx' | grep -cv '^src/lib/date.ts:'
 * ```
 *
 * answers 20 call sites, the four it excludes being these functions' own
 * declarations. **A second parameter would have to be passed at every one of
 * them, to change the answer at the sites `numericDate` names below**, which is
 * where that second number lives rather than here: two figures over one corpus
 * drift apart, and this paragraph has already been wrong about this count
 * twice. `monthLabel` below already reads its own date-only shape here rather
 * than at the statistics page, for the same reason.
 *
 * **What it cannot see**: a date-only string that genuinely means UTC midnight
 * would now render a day late west of Greenwich. There is no such field, and
 * that is a property of the wire rather than of this pattern, so it is stated
 * rather than guarded.
 */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * A calendar date at local midnight, anything else as the instant it is.
 *
 * **`new Date` reads a bare `YYYY-MM-DD` as UTC midnight**, which is the day
 * before for every viewer west of Greenwich. This module has three readers of a
 * date-only value and the other two were already right: `endOfDayInstant`
 * appends a clock and `monthLabel` builds from numbers, and `monthLabel`'s
 * comment refuses the UTC parse in those words. `render` was the one that did
 * it, so the Bought on column of `pages/Home/components/BookTable.tsx` was a
 * day early for anybody west of UTC.
 *
 * **Appending a clock rather than the numeric constructor, and the two are not
 * interchangeable.** Both put the value at local midnight, and `monthLabel`
 * below reaches for the other one. Splitting the string into three numbers
 * would inherit two of the residuals that function's docstring records, and it
 * would do so here where the value comes off the wire rather than out of a
 * bucket key. Measured, both ways:
 *
 * | input | appended | three numbers |
 * |---|---|---|
 * | `0026-08-19`, a year under 100 | the year 26 | **1926** |
 * | `2026-13-01`, an impossible month | `""`, refused | **January 2027** |
 * | `2026-02-30`, an impossible day | March 2nd | March 2nd |
 *
 * **The third row is the one worth writing down, because it is the residual
 * appending does not close.** An impossible day rolls into the next month
 * either way, which `endOfDayInstant` already records one function up for the
 * same mechanism. What appending buys is the year and the month, by keeping the
 * engine's own validation of the date instead of handing `Date` three numbers
 * it will roll without complaint.
 *
 * **What this now refuses that the bare parse accepted, and why the set is the
 * size it is.** The engines' legacy parser reads the three fields of a string
 * it does not recognise as month, day and year, so `0001-01-32` is the first of
 * January 2032 and `0012-01-99` is the first of December 1999. A month is 1 to
 * 12, so the divergent band is **years `0001` to `0012` and nothing outside
 * them**: `0013-01-32` is already unparseable to both.
 *
 * Swept over the whole population, every one of the 100,000,000 strings this
 * pattern matches: **2,728 in each of those twelve years, 32,736 in all**, are
 * read by the bare parse and refused here, and zero in any other year. None is
 * a well formed calendar date. Over the well formed strings, in month 01 to 12
 * and day 01 to 31, the two agree on every one, and nothing is accepted here
 * that the bare parse refused.
 *
 * **Two engines, because exactly one half of that is specified.** The well
 * formed half is ECMA-262's own date time string format and does not vary; the
 * 32,736 live entirely in the fallback every engine is free to write itself, so
 * that figure is a property of the engines measured and not of the language.
 * V8 through node 24 and JavaScriptCore through bun 1.4 agree on both halves
 * exactly. Re-derive before quoting it for a third engine.
 *
 * **Local midnight is always the day it names.** Enumerated over all 418 IANA
 * zones the runtime lists, for every day of 2026 and 2027, 305,140 pairs: zero
 * land on another day. A zone whose clocks move at midnight shifts the instant
 * and not the date. The same sweep with one clock changed, which is the only
 * like for like comparison, puts `endOfDayInstant`'s 23:59:59 at **four** off
 * day pairs in two zones, `America/Godthab` and `America/Scoresbysund` on the
 * spring transition of each year. That function's own docstring counts absent
 * and ambiguous evenings instead, fourteen in five zones, which is a different
 * question: it says itself that every ambiguous one reads back on the right
 * day, so those are not off day pairs at all.
 */
function parsed(iso: string): Date {
  return DATE_ONLY.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
}

/**
 * The one place an API dated field becomes a rendered string.
 *
 * **Absent in, empty out**, which is `lib/year.ts`'s shape for a value that may
 * not be there, and which two call sites had each written for themselves.
 *
 * **An unparseable value is empty too, rather than `Invalid Date`.** Every
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
  return formatted(format, parsed(iso), locale);
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

/**
 * The date a value falls on, at its plainest: `8/19/2026`, `19.8.2026`.
 *
 * **The one renderer here fed a calendar date as well as an instant**, for
 * `purchased_at`, by `pages/Home/components/BookTable.tsx` and
 * `pages/components/BookCard.tsx`, which are the two sites that render that
 * field and are now both through this module. `parsed` above tells the two
 * kinds apart; that the signature cannot is the cost `DATE_ONLY`'s comment
 * weighs against changing every call site.
 */
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
 * The instant a day somebody picked ends, where that person is.
 *
 * **The one function here that reads a date rather than writing one**, and the
 * only place this app turns a chosen day into a timestamp. A `<input
 * type="date">` gives a bare `YYYY-MM-DD` and the API wants an instant. End of
 * day rather than midnight, or a book due "today" is overdue from the moment it
 * is lent.
 *
 * **The offset is what makes the day the member's own, and it rests on the same
 * rule that used to make a rendered timestamp wrong.** `new Date` reads a
 * date-time form carrying no offset as **local** time. Above, that rule is the
 * hazard: a server instant written without an offset rendered as the UTC clock
 * face wearing a local label. Here it is the mechanism: it builds the instant at
 * which 23:59:59 happens where the viewer is, and `toISOString` writes that
 * instant as UTC. Sent without an offset instead, the server reads the member's
 * wall clock as a UTC clock and the deadline lands late by the viewer's offset,
 * which is what `backend/lending.py` then compares against.
 *
 * **The zone is the browser's, because this app has no other.** No timezone is
 * stored against an account, here or on the server, so the platform's answer at
 * the moment of the lend is the only statement of where the member is. The day
 * **counts** stay the server's for the opposite reason, which
 * `pages/components/LoanRow.tsx` records: two definitions of a whole day in two
 * zones is how a row and a reminder come to disagree about one loan. This
 * decides an instant, not a count.
 *
 * **Deadlines written before this are left alone, deliberately.** They were sent
 * as a wall clock and stored as though it were UTC, so for a library away from
 * UTC an old deadline is off by the offset and one near midnight reads as the
 * neighbouring day. Reinterpreting them would mean guessing which zone each was
 * written in, which nothing records. Accepted as a one off rather than migrated.
 *
 * **An evening when the clocks change is bounded rather than left open.**
 * Enumerated over all 418 IANA zones for every day of 2026 and 2027: 23:59:59
 * is **absent** on 4 zone and day pairs, in `America/Godthab` and
 * `America/Scoresbysund`, and **happens twice** on 10, in those two plus
 * `Africa/Cairo`, `America/Santiago` and `Asia/Beirut`. Five zones, fourteen
 * evenings in two years, and the engine resolves every one: the absent case
 * lands on 00:59:59 the next morning, each ambiguous one takes the earlier
 * instant and reads back as 23:59:59 on the right day. **So the worst case is
 * one hour**, on one or two evenings a year, in five zones, which is not worth
 * the zone arithmetic closing it would need.
 *
 * **Absent in, null out, and an unusable date too.** `toISOString` raises
 * `RangeError` on an invalid date, and past year 9999 it emits the expanded form
 * `+010000-01-01T00:00:00.000Z`, which the server answers 422 for.
 * `lib/digitalReference.ts` carries both guards for both reasons over a
 * `File.lastModified`; this is the same pair over a picked day, and the year is
 * read in **UTC** at both sites because the expanded form is a property of the
 * spelling `toISOString` produces rather than of the local date. Thrown from a
 * click handler, either one replaces the whole app shell: `app/providers.tsx`
 * holds the only error boundary.
 *
 * **One residual is left open and named.** `2026-02-30` is an impossible day
 * that `Date` rolls into March, so it returns an instant rather than null. A
 * date input cannot produce one, and the string this replaced rolled it
 * identically.
 */
export function endOfDayInstant(day: string | null | undefined): string | null {
  if (!day) return null;
  const when = new Date(`${day}T23:59:59`);
  if (Number.isNaN(when.getTime())) return null;
  const year = when.getUTCFullYear();
  if (year < 1 || year > 9999) return null;
  return when.toISOString();
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
