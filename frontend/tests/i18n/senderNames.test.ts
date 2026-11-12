/**
 * Tests for src/i18n/senderNames.ts.
 *
 * @vitest-environment node
 */

import { describe, expect, it } from "vitest";

import { en } from "../../src/i18n/en";
import { SENDER_LABELS, SENDER_ROW_REASONS } from "../../src/i18n/senderNames";

describe("SENDER_LABELS", () => {
  it("gives each channel its own name", () => {
    // Two channels sharing a label is a screen that cannot say which one broke,
    // which is the whole job of the banner that reads this.
    const names = Object.values(SENDER_LABELS);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("SENDER_ROW_REASONS", () => {
  it("gives each reason its own fragment", () => {
    // A table mapping six reasons onto four sentences reports less than it
    // looks like it does, and nothing about the type would say so.
    const fragments = Object.values(SENDER_ROW_REASONS);
    expect(new Set(fragments).size).toBe(fragments.length);
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
