/**
 * What the add form carries from one book to the next, and how each value is
 * normalised on the way.
 *
 * **One table, so a carried field is one row rather than one module.** The
 * shelf was the first and lives in `lastLocation.ts` with its own reasoning; the
 * rest arrived together, by the owner's decision of 2026-11-07: collection,
 * format, condition, tags, ownership, where it was bought, when, and whether it
 * is private. Cataloguing is done a shelf at a time and a shelf is usually one
 * shop, one condition and one collection, so retyping them per book is the same
 * repetition the shelf carry removed.
 *
 * **Every value is shown on the form and is clearable there**, and that is the
 * condition the carry was granted on: a value carried silently is a book filed
 * somewhere nobody chose. Privacy is the sharp case, because a private book
 * carried unnoticed hides from every other member with nothing to say so; the
 * form states it in words rather than only ticking a box (`CarriedFields`).
 *
 * **Kept through the preference door**, so it survives a reload halfway along
 * a shelf and neither a read nor a write can throw. One key per field: writing
 * one cannot touch another, and the shelf keeps the key it already has.
 *
 * **The shelf is per browser and the rest are per account**, by the owner's
 * decision of 2026-11-07. A shelf records where somebody is standing, whoever
 * they are. The rest record who filed the last book: a shop, a purchase and a
 * privacy flag belong to a member, and on a shared browser the next member
 * would otherwise start from them and be told "the last one you added was"
 * private about a book they never added. So each of those keys holds one value
 * per account id, and a member who signs out and back in finds their own.
 *
 * **A blank value clears its key**, the shelf's rule applied to all of them:
 * somebody who clears a field is saying the next book has none, and restoring
 * the old one would file it where they had just refused to.
 */

import {
  BookCondition,
  BookFormat,
  OwnershipStatus,
} from "../api/generated/model";
import { TEXT_CEILINGS } from "./bookBounds";
import { lastLocationPreference } from "./lastLocation";
import { declarePreference } from "./preference";

/** Everything one book hands the next. Each field is a `PendingBook` field. */
export interface Carried {
  location: string;
  isPrivate: boolean;
  /** Null for none: `BookCreate.collection_id` is a nullable row id. */
  collectionId: number | null;
  format: BookFormat | "";
  condition: BookCondition | "";
  tagIds: number[];
  ownership: OwnershipStatus;
  purchaseSource: string;
  /** A calendar date, `YYYY-MM-DD`, or `""`. Never an instant: see `calendarDate`. */
  purchasedAt: string;
}

/** What a form starts from when nothing was carried. */
export function nothingCarried(): Carried {
  return {
    location: "",
    isPrivate: false,
    collectionId: null,
    format: "",
    condition: "",
    tagIds: [],
    // The server's own default for an add, and what somebody holding the book
    // means. Blank here, so an owned book clears the key.
    ownership: OwnershipStatus.owned,
    purchaseSource: "",
    purchasedAt: "",
  };
}

/** A member of an enumeration this version knows, or the blank. */
function oneOf<T extends string, B extends T | "">(
  values: Record<string, T>,
  blank: B,
): (value: unknown) => T | B {
  const known = new Set<unknown>(Object.values(values));
  return (value) => (known.has(value) ? (value as T) : blank);
}

function rowId(value: unknown): number | null {
  return Number.isSafeInteger(value) && (value as number) > 0
    ? (value as number)
    : null;
}

function rowIds(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  const ids = value.map(rowId).filter((id): id is number => id !== null);
  return [...new Set(ids)];
}

/** Trim, cap, trim again, as the shelf is: the cap can leave a space. */
function shopName(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, TEXT_CEILINGS.purchase_source).trim();
}

const CALENDAR_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * The string itself when it names a day that exists, otherwise `""`.
 *
 * **Checked by arithmetic and kept as the string**, never through `new Date`:
 * that reads a bare `YYYY-MM-DD` as UTC midnight, which renders the day before
 * west of Greenwich (`lib/date.ts`), and a purchase date is a day on a
 * calendar, not an instant. A stored `2026-02-30` would otherwise reach the
 * server, which refuses it, as a 422 on the press that adds a book.
 */
export function calendarDate(value: unknown): string {
  if (typeof value !== "string") return "";
  const match = CALENDAR_DATE.exec(value);
  if (match === null) return "";
  const [year, month, day] = match.slice(1).map(Number) as [
    number,
    number,
    number,
  ];
  const length = daysIn(year, month);
  return year >= 1 && length !== undefined && day >= 1 && day <= length
    ? value
    : "";
}

/** How many days `month` (1 to 12) of `year` has; undefined for any other month. */
function daysIn(year: number, month: number): number | undefined {
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  const lengths = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return lengths[month - 1];
}

/** One carried field, read and written for the account adding the book. */
interface Carry<T> {
  read: (account: number) => T;
  write: (account: number, value: T) => void;
}

/** A row id as it is spelled as a JSON key, which is how an account is kept. */
const ACCOUNT_KEY = /^[1-9]\d*$/;

/**
 * What `value` holds per account, each value through `accept`, blanks and keys
 * that are not account ids dropped; `{}` for anything but a plain record.
 */
function accountsIn<T>(
  value: unknown,
  accept: (value: unknown) => T,
  blank: T,
): Readonly<Record<string, T>> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return {};
  const isBlank = (held: T) =>
    Array.isArray(held) ? held.length === 0 : held === blank;
  return Object.fromEntries(
    Object.entries(value).flatMap(([account, held]) => {
      if (!ACCOUNT_KEY.test(account)) return [];
      const accepted = accept(held);
      if (isBlank(accepted)) return [];
      // The door freezes the record and not what is inside it, so the tags
      // are frozen here: a reader editing them would edit every reader's.
      // `accept` builds a fresh array, so the caller's is never frozen.
      return [
        [account, Array.isArray(accepted) ? Object.freeze(accepted) : accepted],
      ];
    }),
  );
}

/**
 * One carried field under its own key, one value per account, stored as JSON.
 *
 * `accept` is the whole of the field's rule: it runs on what is read, so a
 * value an older version stored, or one edited by hand, reads back sendable or
 * not at all, and on what is written, so a blank is recognised after it is
 * normalised rather than before. A blank drops its account from the record,
 * and the last account to go clears the key.
 *
 * **Anything stored that is not a record over accounts reads as nothing
 * carried**, a bare value included: a value nobody can be named as owning is
 * not one to hand to whoever is signed in.
 */
function declareCarry<T>(
  key: string,
  accept: (value: unknown) => T,
  blank: T,
): Carry<T> {
  const perAccount = (value: unknown) => accountsIn(value, accept, blank);
  const preference = declarePreference<Readonly<Record<string, T>>>(key, {
    // A parse failure throws, and the door answers the blank for it.
    decode: (raw) => perAccount(JSON.parse(raw)),
    encode: (value) => {
      const kept = perAccount(value);
      return Object.keys(kept).length === 0 ? null : JSON.stringify(kept);
    },
    fallback: () => ({}),
  });
  return {
    // `Object.hasOwn`, so an account can only ever read its own entry.
    read: (account) => {
      const held = preference.read();
      const own = String(account);
      return Object.hasOwn(held, own) ? (held[own] as T) : blank;
    },
    write: (account, value) =>
      preference.write({ ...preference.read(), [String(account)]: value }),
  };
}

/** The shelf, which is per browser: the account is not part of its key. */
const SHELF: Carry<string> = {
  read: () => lastLocationPreference.read(),
  write: (_account, value) => lastLocationPreference.write(value),
};

const NONE = nothingCarried();

/**
 * Every carried field, and the preference that keeps it.
 *
 * **Total over `Carried`**, so a field added there is a compile error until it
 * has a rule here.
 */
const CARRIED: {
  readonly [Field in keyof Carried]-?: Carry<Carried[Field]>;
} = {
  location: SHELF,
  isPrivate: declareCarry(
    "carryOver.private",
    (value) => value === true,
    false,
  ),
  collectionId: declareCarry("carryOver.collection", rowId, NONE.collectionId),
  format: declareCarry("carryOver.format", oneOf(BookFormat, ""), NONE.format),
  condition: declareCarry(
    "carryOver.condition",
    oneOf(BookCondition, ""),
    NONE.condition,
  ),
  tagIds: declareCarry("carryOver.tags", rowIds, NONE.tagIds),
  ownership: declareCarry(
    "carryOver.ownership",
    oneOf(OwnershipStatus, NONE.ownership),
    NONE.ownership,
  ),
  purchaseSource: declareCarry(
    "carryOver.purchaseSource",
    shopName,
    NONE.purchaseSource,
  ),
  purchasedAt: declareCarry(
    "carryOver.purchasedAt",
    calendarDate,
    NONE.purchasedAt,
  ),
};

const FIELDS = Object.keys(CARRIED) as (keyof Carried)[];

/** What the last book this account added left for this one. */
export function readCarried(account: number): Carried {
  const read = Object.fromEntries(
    FIELDS.map((field) => [field, CARRIED[field].read(account)]),
  ) as unknown as Carried;
  // A copy: a preference's value is frozen and shared, and the form edits this.
  return { ...read, tagIds: [...read.tagIds] };
}

/**
 * Keep these for the next book, field by field.
 *
 * **Partial, because not every add files every field.** A copy inherits its
 * tags and its privacy from the book it copies, so remembering what the form
 * held for those would carry a value nothing was filed with.
 */
export function rememberCarried(
  account: number,
  values: Partial<Carried>,
): void {
  for (const field of FIELDS) {
    if (!(field in values)) continue;
    (CARRIED[field] as Carry<unknown>).write(account, values[field]);
  }
}

/**
 * The rows that still exist, where the lists have arrived to say so.
 *
 * Undefined for a list that has not loaded or has failed. That keeps every
 * carried tag, since pruning against an empty list would drop them all on
 * every slow network, and holds back a carried collection until the list
 * names it: see `withoutVanished`.
 */
export interface StillThere {
  tagIds?: ReadonlySet<number>;
  collectionIds?: ReadonlySet<number>;
}

/**
 * The form's values, without a carried tag or collection that is gone.
 *
 * **Only the two that name a row are checked, because only those can stop
 * meaning anything.** A tag or a collection deleted since the last book is an
 * id the server refuses: a collection with a 400 on the add itself, a tag with a
 * failed attach the member is never told about. Dropping it before the form is
 * drawn means what the form shows is what is sent. A shelf, a shop and a date
 * are free text the member may use for the first time, and the enumerations and
 * the date are checked when they are read.
 *
 * **Only what was carried is checked, not what the form holds.** A tag picked
 * or suggested on this form came from a list that was current when it was
 * offered, and judging it against a list still in flight would drop it.
 *
 * Hands back the same object when nothing went, so a caller rendering it keeps
 * its identity.
 */
export function withoutVanished<T extends Carried>(
  values: T,
  carried: Carried,
  there: StillThere,
): T {
  const tags = there.tagIds;
  const collections = there.collectionIds;
  const tagIds = values.tagIds.filter(
    (id) => tags === undefined || tags.has(id) || !carried.tagIds.includes(id),
  );
  // **A carried collection waits for the list, where a carried tag does not.**
  // The collection select draws only the listed collections, so an id the
  // list has not confirmed is drawn as "No collection". Posting it would file
  // the book where the form said it was not, and choosing "No collection"
  // could not clear it, being already selected. Held back rather than
  // dropped: `values` still holds it, so it returns once the list names it.
  const collectionId =
    values.collectionId !== null &&
    values.collectionId === carried.collectionId &&
    (collections === undefined || !collections.has(values.collectionId))
      ? null
      : values.collectionId;
  if (
    tagIds.length === values.tagIds.length &&
    collectionId === values.collectionId
  )
    return values;
  return { ...values, tagIds, collectionId };
}
