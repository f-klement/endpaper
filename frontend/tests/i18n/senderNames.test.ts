/** Tests for src/i18n/senderNames.ts. */

import { describe, expect, it } from "vitest";

import {
  OverdueNotifyReason,
  OverdueSender,
} from "../../src/api/generated/model";
import { en } from "../../src/i18n/en";
import { de } from "../../src/i18n/de";
import { SENDER_LABELS, SENDER_ROW_REASONS } from "../../src/i18n/senderNames";

describe("SENDER_LABELS", () => {
  it("names every channel the server can report", () => {
    expect(Object.keys(SENDER_LABELS).sort()).toEqual(
      Object.values(OverdueSender).sort(),
    );
  });

  it("gives each channel its own name", () => {
    // Two channels sharing a label is a screen that cannot say which one broke,
    // which is the whole job of the banner that reads this.
    const names = Object.values(SENDER_LABELS);
    expect(new Set(names).size).toBe(names.length);
  });

  it("resolves in both catalogues", () => {
    for (const key of Object.values(SENDER_LABELS)) {
      expect(en, key).toHaveProperty(key);
      expect(de, key).toHaveProperty(key);
    }
  });
});

describe("SENDER_ROW_REASONS", () => {
  it("names every reason the server can send", () => {
    // The `Record` type already makes a missing arm a compile error. This is
    // the half a type cannot state: that the union it is keyed on is the
    // server's, read off the generated model rather than retyped.
    expect(Object.keys(SENDER_ROW_REASONS).sort()).toEqual(
      Object.values(OverdueNotifyReason).sort(),
    );
  });

  it("gives each reason its own fragment", () => {
    // A table mapping six reasons onto four sentences reports less than it
    // looks like it does, and nothing about the type would say so.
    const fragments = Object.values(SENDER_ROW_REASONS);
    expect(new Set(fragments).size).toBe(fragments.length);
  });

  it("points every fragment at a message that exists", () => {
    // `MessageKey` is a union of the catalogue's keys, so a wrong key is a
    // compile error; a key that exists in the type and not at runtime is not,
    // and that is what a stale catalogue looks like.
    for (const key of Object.values(SENDER_ROW_REASONS)) {
      expect(en, key).toHaveProperty(key);
      expect(de, key).toHaveProperty(key);
    }
  });

  it("reads as a fragment after a channel's name, not as a sentence", () => {
    // The defect this table exists for: printed per channel, the whole-run
    // sentences named the webhook in the email row and pointed the Telegram
    // row at itself. A fragment starts lower case and is not a full sentence.
    for (const key of Object.values(SENDER_ROW_REASONS)) {
      const text = en[key];
      expect(text[0], key).toBe(text[0]!.toLowerCase());
    }
  });
});
