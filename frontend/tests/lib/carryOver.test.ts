/**
 * Tests for src/lib/carryOver.ts.
 *
 * The cases worth pinning are where a carried value must not survive: a
 * cleared field, a value this version cannot send, and a row that is gone.
 */

import { beforeEach, describe, expect, it } from "vitest";

import {
  BookCondition,
  BookFormat,
  OwnershipStatus,
} from "../../src/api/generated/model";
import { TEXT_CEILINGS } from "../../src/lib/bookBounds";
import {
  calendarDate,
  nothingCarried,
  readCarried,
  rememberCarried,
  withoutVanished,
  type Carried,
} from "../../src/lib/carryOver";
import { readLastLocation } from "../../src/lib/lastLocation";

import { whileStorageRefuses } from "../storageRefusal";

beforeEach(() => localStorage.clear());

/** The account carrying, and another one signing in on the same browser. */
const ME = 1;
const SOMEBODY_ELSE = 2;

const EVERYTHING: Carried = {
  location: "Loft box 2",
  isPrivate: true,
  collectionId: 4,
  format: BookFormat.paperback,
  condition: BookCondition.fair,
  tagIds: [7, 9],
  ownership: OwnershipStatus.not_owned,
  purchaseSource: "The Oxfam on the high street",
  purchasedAt: "2026-11-07",
};

describe("rememberCarried", () => {
  it("carries every field over to the next book", () => {
    rememberCarried(ME, EVERYTHING);
    expect(readCarried(ME)).toEqual(EVERYTHING);
  });

  it("forgets every field when the form is cleared", () => {
    rememberCarried(ME, EVERYTHING);
    rememberCarried(ME, nothingCarried());
    expect(readCarried(ME)).toEqual(nothingCarried());
    expect(localStorage.length).toBe(0);
  });

  it("stores no key for an owned book, which is the default", () => {
    rememberCarried(ME, { ownership: OwnershipStatus.owned });
    expect(localStorage.length).toBe(0);
  });

  it("leaves a field it is not given as it was", () => {
    rememberCarried(ME, EVERYTHING);
    rememberCarried(ME, { location: "Kitchen" });
    expect(readCarried(ME)).toEqual({ ...EVERYTHING, location: "Kitchen" });
  });

  it("keeps the shelf under the key the shelf already had", () => {
    rememberCarried(ME, { location: "  Kitchen  " });
    expect(readLastLocation()).toBe("Kitchen");
  });

  it("trims a shop name and caps it at the column", () => {
    rememberCarried(ME, { purchaseSource: `  ${"x".repeat(500)}  ` });
    expect(readCarried(ME).purchaseSource).toBe(
      "x".repeat(TEXT_CEILINGS.purchase_source),
    );
  });

  it("stores each tag once", () => {
    rememberCarried(ME, { tagIds: [7, 7, 9] });
    expect(readCarried(ME).tagIds).toEqual([7, 9]);
  });

  it("hands back tags the form may edit without touching the stored ones", () => {
    rememberCarried(ME, { tagIds: [7] });
    readCarried(ME).tagIds.push(9);
    expect(readCarried(ME).tagIds).toEqual([7]);
  });
});

describe("the carry on a browser two members share", () => {
  it("starts another member from nothing carried but the shelf", () => {
    rememberCarried(ME, EVERYTHING);
    expect(readCarried(SOMEBODY_ELSE)).toEqual({
      ...nothingCarried(),
      location: EVERYTHING.location,
    });
  });

  it("keeps a member's carry while another member adds a book", () => {
    rememberCarried(ME, EVERYTHING);
    rememberCarried(SOMEBODY_ELSE, {
      purchaseSource: "A market stall",
      tagIds: [3],
    });
    expect(readCarried(ME)).toEqual(EVERYTHING);
  });

  it("forgets only the clearing member's values", () => {
    rememberCarried(ME, EVERYTHING);
    rememberCarried(SOMEBODY_ELSE, EVERYTHING);
    rememberCarried(SOMEBODY_ELSE, nothingCarried());
    expect(readCarried(ME)).toEqual({ ...EVERYTHING, location: "" });
  });
});

describe("readCarried", () => {
  it("reads nothing carried from an empty browser", () => {
    expect(readCarried(ME)).toEqual(nothingCarried());
  });

  it("reads a format this version does not know as none", () => {
    localStorage.setItem("carryOver.format", JSON.stringify({ [ME]: "vinyl" }));
    expect(readCarried(ME).format).toBe("");
  });

  it("reads a value stored for no account as nothing carried", () => {
    localStorage.setItem("carryOver.private", JSON.stringify(true));
    expect(readCarried(ME).isPrivate).toBe(false);
  });

  it("reads a value that is not JSON as nothing carried", () => {
    localStorage.setItem("carryOver.collection", "{");
    expect(readCarried(ME).collectionId).toBeNull();
  });

  it("drops a stored tag that is not a row id", () => {
    localStorage.setItem(
      "carryOver.tags",
      JSON.stringify({ [ME]: [7, -1, 2.5, "9"] }),
    );
    expect(readCarried(ME).tagIds).toEqual([7]);
  });

  it("reads a stored date that names no day as none", () => {
    localStorage.setItem(
      "carryOver.purchasedAt",
      JSON.stringify({ [ME]: "2026-02-30" }),
    );
    expect(readCarried(ME).purchasedAt).toBe("");
  });

  it("reads as nothing carried rather than throwing when storage refuses", () => {
    rememberCarried(ME, EVERYTHING);
    whileStorageRefuses("getItem", () => {
      expect(readCarried(ME)).toEqual(nothingCarried());
    });
  });

  it("writes silently rather than failing the add when storage refuses", () => {
    whileStorageRefuses("setItem", () => {
      expect(() => rememberCarried(ME, EVERYTHING)).not.toThrow();
    });
  });
});

describe("calendarDate", () => {
  it("keeps a date that exists as the string it was", () => {
    expect(calendarDate("2026-11-07")).toBe("2026-11-07");
  });

  it("keeps the twenty ninth of February in a leap year", () => {
    expect(calendarDate("2024-02-29")).toBe("2024-02-29");
  });

  it("refuses the twenty ninth of February in a common year", () => {
    expect(calendarDate("1900-02-29")).toBe("");
  });

  it("refuses a thirteenth month", () => {
    expect(calendarDate("2026-13-01")).toBe("");
  });

  it("refuses the year zero, which the server cannot hold", () => {
    expect(calendarDate("0000-01-01")).toBe("");
  });

  it("refuses an instant, which is not a calendar date", () => {
    expect(calendarDate("2026-11-07T00:00:00Z")).toBe("");
  });

  it("refuses a value that is not a string", () => {
    expect(calendarDate(20261107)).toBe("");
  });
});

describe("withoutVanished", () => {
  it("drops a carried tag that no longer exists", () => {
    expect(
      withoutVanished(EVERYTHING, EVERYTHING, { tagIds: new Set([9]) }).tagIds,
    ).toEqual([9]);
  });

  it("drops a carried collection that no longer exists", () => {
    expect(
      withoutVanished(EVERYTHING, EVERYTHING, { collectionIds: new Set([5]) })
        .collectionId,
    ).toBeNull();
  });

  it("keeps a tag picked on this form whatever the list says", () => {
    const picked = { ...EVERYTHING, tagIds: [7, 9, 11] };
    expect(
      withoutVanished(picked, EVERYTHING, { tagIds: new Set([7, 9]) }).tagIds,
    ).toEqual([7, 9, 11]);
  });

  it("keeps a collection chosen on this form whatever the list says", () => {
    const chosen = { ...EVERYTHING, collectionId: 5 };
    expect(
      withoutVanished(chosen, EVERYTHING, { collectionIds: new Set() })
        .collectionId,
    ).toBe(5);
  });

  it("keeps every carried tag while the lists have not arrived", () => {
    expect(withoutVanished(EVERYTHING, EVERYTHING, {}).tagIds).toEqual(
      EVERYTHING.tagIds,
    );
  });

  it("holds back a carried collection the list has not confirmed", () => {
    expect(withoutVanished(EVERYTHING, EVERYTHING, {}).collectionId).toBeNull();
  });

  it("keeps a collection chosen on this form while the list has not arrived", () => {
    const chosen = { ...EVERYTHING, collectionId: 5 };
    expect(withoutVanished(chosen, EVERYTHING, {}).collectionId).toBe(5);
  });

  it("hands back the same object when nothing is gone", () => {
    expect(
      withoutVanished(EVERYTHING, EVERYTHING, {
        tagIds: new Set([7, 9]),
        collectionIds: new Set([4]),
      }),
    ).toBe(EVERYTHING);
  });
});
