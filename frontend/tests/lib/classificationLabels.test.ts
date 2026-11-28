/** Tests for src/lib/classificationLabels. */

import { describe, expect, it } from "vitest";

import { HeadingKind } from "../../src/api/generated/model";
import {
  KIND_LABEL,
  headingKind,
  headingText,
} from "../../src/lib/classificationLabels";

describe("what a heading reads as", () => {
  it("shows the caption where the record carried one", () => {
    // The GND case, and the reason the fallback is this way round: `number` is
    // an authority id and the caption is what a person reads.
    expect(headingText({ number: "4203576-4", label: "Schatz" })).toBe(
      "Schatz",
    );
  });

  it("shows the identifier where the record carried no caption", () => {
    // Every MARC 082: the field holds the notation and the printed schedule
    // holds the words, so there is nothing else to show.
    expect(headingText({ number: "155.9042", label: null })).toBe("155.9042");
  });

  it("shows the identifier where the caption is absent rather than null", () => {
    expect(headingText({ number: "Stress management" })).toBe(
      "Stress management",
    );
  });
});

describe("what a heading asserts", () => {
  it("reads a heading no record ever declared for as a subject", () => {
    // The client's half of `classifications.kind_of`. The API sends null for
    // every row written before the column existed.
    expect(headingKind(null)).toBe(HeadingKind.subject);
    expect(headingKind(undefined)).toBe(HeadingKind.subject);
  });

  it("leaves a declared kind alone", () => {
    expect(headingKind(HeadingKind.carrier)).toBe(HeadingKind.carrier);
  });

  it("says nothing about a subject and names the other two", () => {
    // Marking every subject would put a word on almost every chip to
    // distinguish it from almost nothing.
    expect(KIND_LABEL[HeadingKind.subject]).toBeNull();
    expect(KIND_LABEL[HeadingKind.content]).toBe("classification.kind.content");
    expect(KIND_LABEL[HeadingKind.carrier]).toBe("classification.kind.carrier");
  });
});
