/** Tests for src/pages/PatronsPage/types.ts: the draft and the expiry rule. */

import { describe, expect, it } from "vitest";

import type { PatronOut } from "../../../src/api/generated/model";
import {
  BLANK_DRAFT,
  calendarToday,
  draftOf,
  hasExpired,
} from "../../../src/pages/PatronsPage/types";

const withExpiry = (expires_on: string | null) => ({ expires_on }) as PatronOut;

const recorded = {
  name: "Ada Lovelace",
  card_number: "0042",
  email: "ada@example.org",
  phone: "020 7946 0000",
  street: "St James's Square",
  house_number: "12",
  postcode: "SW1Y 4JH",
  city: "London",
  expires_on: "2027-03-01",
};

describe("draftOf", () => {
  it("opens the form on every field the patron has recorded", () => {
    expect(draftOf({ ...recorded } as PatronOut)).toEqual(recorded);
  });

  it("opens an empty box for every optional field recorded as nothing", () => {
    const patron = {
      ...recorded,
      email: null,
      phone: null,
      street: null,
      house_number: null,
      postcode: null,
      city: null,
      expires_on: null,
    } as PatronOut;
    expect(draftOf(patron)).toEqual({
      ...BLANK_DRAFT,
      name: "Ada Lovelace",
      card_number: "0042",
    });
  });
});

describe("calendarToday", () => {
  it("names the reader's own calendar day, not the UTC one", () => {
    // Built from local fields, so this holds in any time zone the suite runs in.
    const late = new Date(2026, 0, 31, 23, 59);
    expect(calendarToday(late)).toBe("2026-01-31");
  });
});

describe("hasExpired", () => {
  it("still holds a registration on its expiry date", () => {
    expect(hasExpired(withExpiry("2026-05-04"), "2026-05-04")).toBe(false);
  });

  it("lapses a registration the day after its expiry date", () => {
    expect(hasExpired(withExpiry("2026-05-04"), "2026-05-05")).toBe(true);
  });

  it("never lapses a registration with no expiry date", () => {
    expect(hasExpired(withExpiry(null), "2999-01-01")).toBe(false);
  });
});
