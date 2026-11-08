/**
 * Prices, which the API counts in minor units and people write with a decimal
 * point.
 *
 * The API stores an integer number of cents rather than a decimal, because
 * SQLite has no decimal type and a float round-trips 12.99 back as
 * 12.989999999999999. Somebody typing a price still writes "12.99", so the
 * conversion has to live somewhere, and one module is better than every form
 * that touches a price.
 */

import type { Locale } from "../api/generated/model";

/** Cents as a plain decimal string, or empty when there is no price. */
export function formatMinor(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "";
  return (minor / 100).toFixed(2);
}

/**
 * A typed price as cents, `null` when cleared, `undefined` when unusable.
 *
 * The three-way answer is the point. An empty field means "no price" and must
 * clear the stored one; "12,99" with a comma is what a German keyboard
 * produces and is the same number; anything else is a typo and must not be
 * silently stored as zero.
 */
export function parseMinor(raw: string): number | null | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  // A comma is a decimal separator in every language this app speaks.
  const normalised = trimmed.replace(",", ".");
  if (!/^\d+(\.\d{0,2})?$/.test(normalised)) return undefined;

  // Rounded rather than truncated, and computed on the string's own digits:
  // `Math.round(12.99 * 100)` is 1299 here but the same pattern is what makes
  // 8.29 come out as 828 in other currencies' worth of cases.
  return Math.round(Number(normalised) * 100);
}

/**
 * A stored total in its currency, spelled for the reader's locale.
 *
 * `minor` is hundredths whatever the currency, because that is what
 * `parseMinor` stores for every code. `Intl` then applies the currency's own
 * exponent, so yen show no decimals. The code is shown rather than a symbol:
 * `$` alone does not say which dollar.
 *
 * The stored code is any three characters and `Intl` throws on one that is
 * not three letters, so that case falls back to the plain amount and the code
 * as written, rather than losing the total.
 */
export function formatTotal(
  minor: number,
  currency: string,
  locale: Locale,
): string {
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      currencyDisplay: "code",
    }).format(minor / 100);
  } catch {
    return `${formatMinor(minor)} ${currency}`;
  }
}
