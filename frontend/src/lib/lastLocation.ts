/**
 * The shelf location most recently used when adding a book.
 *
 * Cataloguing happens a shelf at a time: somebody stands in front of one
 * bookcase and scans thirty books that all live in the same place. Typing that
 * place thirty times is the most repetitive act in the whole app, so the last
 * one used is remembered and offered as the default for the next book.
 *
 * localStorage rather than component state, so it survives a reload halfway
 * along a shelf, and per browser rather than per account, because it records
 * where somebody is standing and not who they are.
 */

import { declarePreference } from "./preference";

/** Matches the `location` column, so a remembered value is always sendable. */
export const MAX_LOCATION_LENGTH = 120;

/** Trim, cap, trim again: cutting at the cap can leave a trailing space. */
export function normaliseLocation(raw: string | null | undefined): string {
  return (raw ?? "").trim().slice(0, MAX_LOCATION_LENGTH).trim();
}

/**
 * The last shelf used, behind the door every stored choice goes through.
 *
 * What the door supplies: neither reading nor writing throws, and a private
 * window that refuses to answer reads as no shelf. A forgotten default is not
 * worth failing an add over.
 *
 * **`encode` returns null on an empty value, which clears the key.** Somebody
 * who clears the field is saying the next book has no shelf yet, and silently
 * restoring the old one would file it somewhere they had just refused to name.
 *
 * **Normalised on the way in and on the way out**, so a value stored by an
 * earlier version without the trim still reads back sendable.
 *
 * **This preference is deliberately not read through `usePreference`**, and the
 * reason is not that it could not be. The scanner reads it once as the starting
 * value of a field the member then edits, and stores it only after a book is
 * actually added. Those are two parties editing one value, so a reactive read
 * would overwrite what somebody is typing the moment another shelf committed.
 * A seed is not a subscription.
 */
export const lastLocationPreference = declarePreference<string>(
  "lastLocation",
  {
    decode: (raw) => normaliseLocation(raw),
    encode: (value) => normaliseLocation(value) || null,
    fallback: () => "",
  },
);

export function readLastLocation(): string {
  return lastLocationPreference.read();
}

/** Remember a location for the next book, or forget it when cleared. */
export function rememberLastLocation(raw: string | null | undefined): void {
  lastLocationPreference.write(normaliseLocation(raw));
}
