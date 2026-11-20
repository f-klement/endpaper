import type { PatronCreate, PatronOut } from "../../api/generated/model";

/**
 * A patron as the form holds it: every field a string, an empty one meaning
 * nothing recorded.
 *
 * A form input cannot hold `null`, so the draft does not either, and
 * `patronBody` is the one place an empty box becomes one.
 */
export interface PatronDraft {
  name: string;
  card_number: string;
  email: string;
  phone: string;
  street: string;
  house_number: string;
  postcode: string;
  city: string;
  /** `YYYY-MM-DD`, what `<input type="date">` reads and writes. */
  expires_on: string;
}

/** The form for a patron nobody has registered yet. */
export const BLANK_DRAFT: PatronDraft = {
  name: "",
  card_number: "",
  email: "",
  phone: "",
  street: "",
  house_number: "",
  postcode: "",
  city: "",
  expires_on: "",
};

/** The form opened on a patron already registered. */
export function draftOf(patron: PatronOut): PatronDraft {
  return {
    name: patron.name,
    card_number: patron.card_number,
    email: patron.email ?? "",
    phone: patron.phone ?? "",
    street: patron.street ?? "",
    house_number: patron.house_number ?? "",
    postcode: patron.postcode ?? "",
    city: patron.city ?? "",
    expires_on: patron.expires_on ?? "",
  };
}

/**
 * Whether the draft can be sent: a name and a card number with more than
 * spaces in them.
 *
 * The server refuses a whitespace only value with a 422. Refusing it here
 * first keeps that refusal for the writer this form is not.
 */
export function isSendable(draft: PatronDraft): boolean {
  return draft.name.trim() !== "" && draft.card_number.trim() !== "";
}

/** A box's value trimmed, or `null` for a box holding nothing but spaces. */
function optional(value: string): string | null {
  return value.trim() === "" ? null : value.trim();
}

/**
 * The body for both the create and the edit.
 *
 * **Every optional field is sent, an empty one as `null`**, because the edit
 * is a PATCH where `null` clears a field and an absent key leaves it: a field
 * left out when emptied would keep the old phone number on a record whose
 * form shows none. Every value is trimmed, so a box holding only spaces
 * clears its field rather than meeting the server's 422.
 */
export function patronBody(draft: PatronDraft): PatronCreate {
  return {
    name: draft.name.trim(),
    card_number: draft.card_number.trim(),
    email: optional(draft.email),
    phone: optional(draft.phone),
    street: optional(draft.street),
    house_number: optional(draft.house_number),
    postcode: optional(draft.postcode),
    city: optional(draft.city),
    expires_on: optional(draft.expires_on),
  };
}

/** A month or a day as the two digits an ISO date writes. */
function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * Today's date where the reader is, as `YYYY-MM-DD`.
 *
 * Built from the local calendar fields, never from `toISOString`, which is
 * UTC: east of Greenwich that names yesterday for the first hours of a day,
 * and a registration expiring today would read as current or lapsed by the
 * hour the page was opened.
 */
export function calendarToday(now: Date): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * Whether a registration has lapsed: its expiry date is before today.
 *
 * The expiry date is the last day the registration holds, as Koha reads its
 * `dateexpiry`, so a card expiring today still lends today and the page
 * says "Registered until" that date.
 * Compared as strings, which for two `YYYY-MM-DD` dates is the calendar
 * order. A patron with no expiry date never lapses.
 */
export function hasExpired(patron: PatronOut, today: string): boolean {
  return patron.expires_on != null && patron.expires_on < today;
}
