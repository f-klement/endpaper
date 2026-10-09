/**
 * @vitest-environment node
 *
 * A JSON file and one pure function, so this needs no DOM. `File` is a global
 * in node's own runtime.
 */
/**
 * Tests for src/lib/digitalReference.ts.
 *
 * **The bounds are recomputed from `openapi.json` rather than restated**, which
 * is `tests/lib/bookBounds.test.ts`'s arrangement and its reason: a ceiling
 * copied out of a schema stops being true the first time the schema moves, and
 * it does so in the direction that looks safe, because a ceiling too small only
 * drops references and nothing goes red.
 *
 * **One of the two rules the budget carries has no schema behind it.** Each
 * half's `maxLength` is recomputed below; the pair bound is a model validator
 * that no schema states, so it is driven by its boundary rather than read.
 *
 * **The arms hand it real `File` objects on purpose.** `referenceFor` takes
 * three scalars rather than a file, so that nothing in `lib/` holding a
 * member's bytes is what sends anything; a `File` is structurally one of those,
 * and driving it with the type the picker actually produces is what says the
 * caller needs no adapter.
 *
 * **What this file cannot check is the half the server cannot enforce**: that
 * the picked directory's own name is the `root_label` and not the head of the
 * `relative_path`. Two clients disagreeing about that write two rows for one
 * file and both are inside every bound here. It is checked by the arms naming
 * the two halves of a real `webkitRelativePath`, which is the only instrument
 * there is for a rule no schema states.
 */

import { describe, expect, it } from "vitest";

import { PATH_BUDGET, referenceFor } from "../../src/lib/digitalReference";

const SCHEMA = import.meta.glob("../../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

interface Constraint {
  maxLength?: number;
  minLength?: number;
  maximum?: number;
  minimum?: number;
  anyOf?: Constraint[];
}

/** A nullable field is `anyOf: [{the real thing}, {null}]`, so flatten first. */
function flatten(property: Constraint): Constraint {
  const parts = [property, ...(property.anyOf ?? [])];
  return {
    maxLength: parts.find((part) => part.maxLength !== undefined)?.maxLength,
    minLength: parts.find((part) => part.minLength !== undefined)?.minLength,
    maximum: parts.find((part) => part.maximum !== undefined)?.maximum,
    minimum: parts.find((part) => part.minimum !== undefined)?.minimum,
  };
}

/** `DigitalReferenceIn`'s properties, as the committed schema declares them. */
function schema(): Record<string, Constraint> {
  const raw = SCHEMA["../../openapi.json"] ?? "";
  // A glob that matched nothing would make every assertion below pass forever.
  expect(raw.length).toBeGreaterThan(1000);
  const parsed = JSON.parse(raw) as {
    components: {
      schemas: Record<string, { properties: Record<string, Constraint> }>;
    };
  };
  const model = parsed.components.schemas["DigitalReferenceIn"];
  expect(model, "DigitalReferenceIn is in the committed schema").toBeDefined();
  return model!.properties;
}

/**
 * A picked file, with the path a folder pick gives it.
 *
 * `webkitRelativePath` is read only and a `File` cannot be constructed with
 * one, which is why every test in this tree that needs a folder pick defines
 * the property afterwards.
 */
function picked(name: string, path: string, size = 10, modified = 0): File {
  const file = new File([], name, { lastModified: modified });
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("the reference a picked file makes", () => {
  it("gives the picked folder's own name as the root and the rest beneath it", () => {
    // The rule the server cannot enforce. A client sending the whole path as
    // the `relative_path` and a client sending this one write two rows for the
    // same file, because the pair is the location's identity.
    const reference = referenceFor(
      picked("Dune.epub", "Books/Frank Herbert/Dune.epub"),
    );

    expect(reference).toEqual({
      root_label: "Books",
      relative_path: "Frank Herbert/Dune.epub",
      root_confirmed: true,
      size_bytes: 10,
      file_modified_at: "1970-01-01T00:00:00.000Z",
    });
  });

  it("says the root was confirmed, because a member picked the folder", () => {
    const reference = referenceFor(picked("Dune.epub", "Books/Dune.epub"));

    expect(reference?.root_confirmed).toBe(true);
  });

  it("sends nothing for a file picked one at a time", () => {
    // **The honest answer rather than a guess.** A bare pick gives a name and
    // no path, so this browser has no root to name and no screen in which a
    // member names one. A reference invented here would be a claim about a
    // location nobody looked at.
    // Node's own `File` carries no `webkitRelativePath` at all, and a browser
    // gives `""`, so both spellings of "no path" reach this arm.
    expect(referenceFor(new File([], "Dune.epub"))).toBeNull();
  });

  it("sends nothing where either half of the pair would be empty", () => {
    // Both are a 422 on the member's own batch, which is the outcome every
    // bound in this module exists to take instead.
    expect(referenceFor(picked("Dune.epub", "Dune.epub"))).toBeNull();
    expect(referenceFor(picked("Dune.epub", "/Dune.epub"))).toBeNull();
    expect(referenceFor(picked("Dune.epub", "Books/"))).toBeNull();
  });

  it("drops a pair over the budget rather than cutting it to fit", () => {
    // A cut path names a different file or none, which is `bookBounds.ts`'s
    // rule for `location` and the reason it is kept whole there too.
    //
    // **The point immediately outside the end, and the end itself.** A pair far
    // over the budget is refused by any bound at all; the pair one character
    // over and the pair exactly on it are what say this is the budget.
    //
    // **In an astral character, which is what makes this an instrument.** The
    // server counts code points and `String.length` counts UTF-16 units, so a
    // pair built out of `a` is the one case where the two agree and a count in
    // the wrong unit reads clean. Each of these is two units and one point.
    const over = "𝔞".repeat(PATH_BUDGET - "Books".length + 1);
    expect(referenceFor(picked("a", `Books/${over}`))).toBeNull();

    const exactly = [...over].slice(0, -1).join("");
    const reference = referenceFor(picked("a", `Books/${exactly}`));
    expect(reference?.root_label).toBe("Books");
    expect(
      [...reference!.root_label].length + [...reference!.relative_path].length,
    ).toBe(PATH_BUDGET);
    // The pair the arm above accepts is over the budget when it is counted the
    // wrong way, so this arm goes red on a count spelled `.length`.
    expect(
      reference!.root_label.length + reference!.relative_path.length,
    ).toBeGreaterThan(PATH_BUDGET);
  });

  it("drops a pair carrying a NUL, which the server refuses", () => {
    expect(referenceFor(picked("a", "Bo\0oks/Dune.epub"))).toBeNull();
    expect(referenceFor(picked("a", "Books/Du\0ne.epub"))).toBeNull();
  });

  it("sends the folder's own text, uncleaned", () => {
    // **The asymmetry, and it runs the other way from every label on screen.**
    // A folder really named with a bidirectional override in it is a folder of
    // that name, and a reference cleaned to read nicely points at nothing. What
    // gets cleaned is the value rendered, through `fileName.plainName`.
    // Escaped rather than typed: the two characters this is about are the two
    // a reader of this file cannot see.
    const reference = referenceFor(
      picked("Dune.epub", "Bo\u202Eoks/Dune\u200B.epub"),
    );

    expect(reference?.root_label).toBe("Bo\u202Eoks");
    expect(reference?.relative_path).toBe("Dune\u200B.epub");
  });
});

describe("what the browser knew about the file itself", () => {
  it("sends the modification time as a timestamp the server parses", () => {
    const reference = referenceFor(
      picked("Dune.epub", "Books/Dune.epub", 4096, Date.UTC(2019, 4, 1)),
    );

    expect(reference?.file_modified_at).toBe("2019-05-01T00:00:00.000Z");
    expect(reference?.size_bytes).toBe(4096);
  });

  it("sends no time rather than throwing on a file that has none", () => {
    // `new Date(undefined).toISOString()` throws `RangeError`. Thrown from the
    // batch it would mark a book that had just been created as failed, and the
    // member would add it again into a duplicate.
    const file = picked("Dune.epub", "Books/Dune.epub");
    Object.defineProperty(file, "lastModified", { value: undefined });

    expect(() => referenceFor(file)).not.toThrow();
    expect(referenceFor(file)?.file_modified_at).toBeNull();
    // The reference itself survives: a sighting with no date still says where
    // the file is, which is the whole of what it is for.
    expect(referenceFor(file)?.relative_path).toBe("Dune.epub");
  });

  it("sends no time for a year the server cannot parse, at either end", () => {
    // **Both ends, and only one of them announces itself.** Past 9999
    // `toISOString` writes the expanded form and the shape says something is
    // wrong; below 1 it writes four digits like any other year, and
    // `0000-01-01T00:00:00.000Z` is the same 422 because Python's `MINYEAR` is
    // 1. A rule reading the shape closes the loud end and leaves the quiet one.
    const far = picked("Dune.epub", "Books/Dune.epub", 10, Date.UTC(10000, 0));
    expect(new Date(Date.UTC(10000, 0)).toISOString()).toMatch(/^\+/);
    expect(referenceFor(far)?.file_modified_at).toBeNull();

    const zero = picked("Dune.epub", "Books/Dune.epub", 10, -62167219200000);
    expect(new Date(-62167219200000).toISOString()).toBe(
      "0000-01-01T00:00:00.000Z",
    );
    expect(referenceFor(zero)?.file_modified_at).toBeNull();

    // The year immediately inside that end, which is what says the rule is a
    // bound rather than a refusal of anything old.
    const first = picked("Dune.epub", "Books/Dune.epub", 10, -62135596800000);
    expect(referenceFor(first)?.file_modified_at).toBe(
      "0001-01-01T00:00:00.000Z",
    );
  });

  it("sends a size of zero, which the contract takes", () => {
    // **The floor is a value and not an absence.** An empty file, a truncated
    // download and a `touch`ed placeholder are all 0 bytes, and dropping the
    // field there loses the half of the fingerprint that would let a re-check
    // notice the file is empty. `size_bytes` has `minimum: 0` for that reason.
    const empty = picked("Dune.epub", "Books/Dune.epub", 0);

    expect(referenceFor(empty)?.size_bytes).toBe(0);
  });

  it("sends no size rather than one the wire cannot carry", () => {
    const huge = picked("Dune.epub", "Books/Dune.epub", Number.MAX_VALUE);

    expect(referenceFor(huge)?.size_bytes).toBeNull();
    expect(referenceFor(huge)?.relative_path).toBe("Dune.epub");
  });
});

describe("the bounds, read off the committed schema", () => {
  it("budgets the pair at the width the schema declares for each half", () => {
    const properties = schema();
    const root = flatten(properties["root_label"]!);
    const beneath = flatten(properties["relative_path"]!);

    expect(root.maxLength).toBe(PATH_BUDGET);
    expect(beneath.maxLength).toBe(PATH_BUDGET);
    expect(root.minLength).toBe(1);
    expect(beneath.minLength).toBe(1);
  });

  it("takes no size the schema refuses", () => {
    const size = flatten(schema()["size_bytes"]!);

    expect(size.minimum).toBe(0);
    // The largest integer that survives being a JSON number, which is what the
    // server chose the bound as. Written as the computation rather than as the
    // digits, so this cannot agree with a wrong literal.
    expect(size.maximum).toBe(Number.MAX_SAFE_INTEGER);
  });
});
