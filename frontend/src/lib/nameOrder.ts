/**
 * How this app orders a list of names.
 *
 * The database cannot do it. SQLite has no locale aware collation without the
 * ICU extension, and this image does not build one, so every name list the API
 * returns is ordered by codepoint or by a case fold of one. Both put `Ä` at
 * U+00C4, above every ASCII letter, and neither is a bug in the fold: measured
 * against the deployment's own database, `order by lower(name)` and `order by
 * name collate nocase` both return `['apple', 'Banana', 'Zebra', 'Ästhetik']`.
 * A reader looking for "Ästhetik" finds it past every English name.
 *
 * So ordering by name happens here, where a locale is known and `Intl.Collator`
 * exists. The lists this applies to are a library's collections, tags, series
 * and authors: unpaginated, fully fetched, and small enough that sorting them
 * again in the browser costs nothing measurable.
 *
 * **The server's `ORDER BY` is not removed and is not a second opinion.** It
 * makes an unordered query deterministic, which the API's other consumers (the
 * export, the docs at `/docs`) still want. What it stopped being is the order a
 * reader sees: a screen drawing a name list calls this rather than trusting the
 * order it was handed.
 *
 * **Components call `useSortedByName` from `i18n`, not this.** It supplies the
 * locale and the memo, which are two of the three things needed and both easy
 * to forget. This stays exported for `groupTagsByCategory`, which is not React
 * and cannot use a hook.
 */

import type { Locale } from "../api/generated/model";

/**
 * One collator per locale, built once.
 *
 * Measured on node 24 per 1,000 operations, by two seats independently:
 * constructing a collator took 7.0 to 60.8ms, comparing two names 0.10 to
 * 0.31ms. Pairing each seat's own figures, the ratio ran from 28:1 to 243:1.
 * The spread is wide and the conclusion is not: construction costs one to two
 * orders of magnitude more than the comparison it exists to perform, so
 * building one per call would cost more than the sort.
 *
 * Keyed by locale rather than held as a single instance because the app can
 * switch language without a reload, and a collator carries the locale it was
 * built with.
 */
const collators = new Map<Locale, Intl.Collator>();

function collatorFor(locale: Locale): Intl.Collator {
  const existing = collators.get(locale);
  if (existing) return existing;
  // Default sensitivity, which is "variant": `Ästhetik` sorts with `A` because
  // the accent is a secondary difference, and `apple` and `Apple` stay two
  // distinct entries in a stable order rather than collapsing into one
  // arbitrary winner the way `sensitivity: "base"` would.
  const collator = new Intl.Collator(locale);
  collators.set(locale, collator);
  return collator;
}

/**
 * The names, in the order a reader of `locale` expects.
 *
 * **The locale is the chosen interface language, not the browser's.** It is the
 * one language this app knows the reader picked, `interpolate` already formats
 * numbers with it, and two people looking at the same library in the same
 * language then see the same order. Taking it from `navigator.language` instead
 * would order the page by something the reader never chose and cannot see, and
 * would disagree with the numbers printed beside it.
 *
 * Returns a new array. The input is a query cache entry at every call site, and
 * `Array.prototype.sort` mutates.
 */
export function sortByName<T extends { name: string }>(
  items: readonly T[],
  locale: Locale,
): T[] {
  const { compare } = collatorFor(locale);
  return [...items].sort((a, b) => compare(a.name, b.name));
}
