/**
 * Highlights out of a KOReader sidecar, in both of the shapes KOReader has
 * written. The fixtures are written here after KOReader's
 * `ReaderAnnotation` and `ReaderBookmark` modules, which name every field
 * used; none was taken off a device.
 */

import fc from "fast-check";
import { describe, expect, it } from "vitest";

import {
  readSidecar,
  type SidecarReading,
} from "../../src/lib/koreaderSidecar";
import { MAX_SOURCE_LENGTH } from "../../src/lib/luaTable";

import { holds, PROFILE, PROPERTY, witness } from "../property";

const DIGEST = "0123456789abcdef0123456789abcdef";

function highlights(source: string) {
  const reading = readSidecar(source);
  if (!reading.ok) throw new Error(`refused: ${reading.reason}`);
  return reading.highlights;
}

describe("the current annotations array", () => {
  const sidecar = `return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["annotations"] = {
    [1] = {
      ["chapter"] = "Book One",
      ["datetime"] = "2026-03-01 22:15:09",
      ["drawer"] = "lighten",
      ["note"] = "the litany",
      ["page"] = "/body/DocFragment[3]/body/p[2]/text().0",
      ["pageno"] = 12,
      ["pos0"] = "/body/DocFragment[3]/body/p[2]/text().0",
      ["pos1"] = "/body/DocFragment[3]/body/p[2]/text().41",
      ["text"] = "Fear is the mind-killer.",
    },
    [2] = {
      ["datetime"] = "2026-03-02 08:00:00",
      ["page"] = "/body/DocFragment[4]/body/p[1]",
      ["text"] = "in Book Two",
    },
  },
}`;

  it("reads a highlight with its note, chapter, page and time", () => {
    expect(highlights(sidecar)).toEqual([
      {
        pos0: "/body/DocFragment[3]/body/p[2]/text().0",
        pos1: "/body/DocFragment[3]/body/p[2]/text().41",
        text: "Fear is the mind-killer.",
        note: "the litany",
        chapter: "Book One",
        page: 12,
        highlightedAt: "2026-03-01 22:15:09",
      },
    ]);
  });

  it("leaves out a page bookmark, which has no drawer", () => {
    expect(highlights(sidecar)).toHaveLength(1);
  });

  it("is the whole truth where the older keys are still beside it", () => {
    const marks = highlights(
      sidecar.replace(
        /\}\s*$/,
        `  ["bookmarks"] = { [1] = { ["highlighted"] = true, ["notes"] = "stale", ["pos0"] = "a", ["pos1"] = "b" } },
}`,
      ),
    );
    expect(marks.map((mark) => mark.text)).toEqual([
      "Fear is the mind-killer.",
    ]);
  });

  it.each(["2026-03-01 25:00:00", "0000-03-01 22:15:09"])(
    "drops a time that does not exist, %s, from its mark alone",
    (when) => {
      const [mark] = highlights(sidecar.replace("2026-03-01 22:15:09", when));
      expect(mark?.highlightedAt).toBeNull();
    },
  );

  it("drops a date that does not exist from its mark alone", () => {
    const [mark] = highlights(
      sidecar.replace("2026-03-01 22:15:09", "2026-02-31 22:15:09"),
    );
    expect([mark?.text, mark?.highlightedAt]).toEqual([
      "Fear is the mind-killer.",
      null,
    ]);
  });
});

describe("the older bookmarks and highlight pair", () => {
  it("takes the passage from notes and the member's note from text", () => {
    const [mark] = highlights(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["highlights_imported"] = true,
  ["bookmarks"] = {
    [1] = {
      ["datetime"] = "2019-05-01 10:00:00",
      ["highlighted"] = true,
      ["notes"] = "A passage",
      ["text"] = "my own words",
      ["pos0"] = "/body/p[1]/text().0",
      ["pos1"] = "/body/p[1]/text().9",
      ["page"] = "/body/p[1]/text().0",
    },
  },
}`);
    expect([mark?.text, mark?.note]).toEqual(["A passage", "my own words"]);
  });

  it("drops KOReader's own filler where a note would be", () => {
    const [mark] = highlights(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["highlights_imported"] = true,
  ["bookmarks"] = {
    [1] = {
      ["datetime"] = "2019-05-01 10:00:00",
      ["highlighted"] = true,
      ["notes"] = "A passage",
      ["text"] = "Page 12 A passage @ 2019-05-01 10:00:00",
      ["pos0"] = "/body/p[1]/text().0",
      ["pos1"] = "/body/p[1]/text().9",
    },
  },
}`);
    expect(mark?.note).toBeNull();
  });

  it("adds a fixed layout bookmark's page to its positions, as KOReader's migration does", () => {
    const [mark] = highlights(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["highlights_imported"] = true,
  ["bookmarks"] = {
    [1] = {
      ["highlighted"] = true,
      ["notes"] = "On a PDF page",
      ["page"] = 4,
      ["pos0"] = { ["x"] = 10.5, ["y"] = 20 },
      ["pos1"] = { ["x"] = 90, ["y"] = 30 },
    },
  },
}`);
    expect([mark?.pos0, mark?.pos1]).toEqual([
      "page=4;x=10.5;y=20",
      "page=4;x=90;y=30",
    ]);
  });

  it("reads nothing from the highlight table once KOReader says it imported it", () => {
    const marks = highlights(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["highlights_imported"] = true,
  ["highlight"] = {
    [3] = { [1] = { ["text"] = "Only here", ["pos0"] = "/p[5]", ["pos1"] = "/p[6]" } },
  },
}`);
    expect(marks).toEqual([]);
  });

  it("imports a highlight never added to the bookmarks, once", () => {
    const marks = highlights(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["bookmarks"] = {
    [1] = {
      ["highlighted"] = true,
      ["notes"] = "Seen in both",
      ["pos0"] = "/body/p[1]/text().0",
      ["pos1"] = "/body/p[1]/text().9",
    },
  },
  ["highlight"] = {
    [3] = {
      [1] = {
        ["text"] = "Seen in both",
        ["pos0"] = "/body/p[1]/text().0",
        ["pos1"] = "/body/p[1]/text().9",
      },
      [2] = {
        ["text"] = "Only here",
        ["datetime"] = "2013-01-01 09:00:00",
        ["pos0"] = "/body/p[5]/text().0",
        ["pos1"] = "/body/p[5]/text().4",
      },
    },
  },
}`);
    expect(marks.map((mark) => mark.text)).toEqual([
      "Seen in both",
      "Only here",
    ]);
  });

  it("writes a fixed layout position as one canonical string", () => {
    const [mark] = highlights(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["highlight"] = {
    [4] = {
      [1] = {
        ["text"] = "On a PDF page",
        ["pos0"] = { ["y"] = 20, ["x"] = 10.5 },
        ["pos1"] = { ["y"] = 30, ["x"] = 90 },
      },
    },
  },
}`);
    expect([mark?.pos0, mark?.pos1, mark?.page]).toEqual([
      "page=4;x=10.5;y=20",
      "page=4;x=90;y=30",
      4,
    ]);
  });
});

describe("a sidecar that cannot be imported", () => {
  it("says so when it carries no fingerprint", () => {
    expect(readSidecar('return { ["annotations"] = {} }')).toEqual({
      ok: false,
      reason: "no-fingerprint",
    });
  });

  it("says so when it is past the size the reader takes", () => {
    expect(readSidecar("x".repeat(MAX_SOURCE_LENGTH + 1))).toEqual({
      ok: false,
      reason: "too-large",
    });
  });

  it("says so when it is not a Lua table", () => {
    expect(readSidecar("not lua at all")).toEqual({
      ok: false,
      reason: "unreadable",
    });
  });

  it("counts a passage too long to store instead of sending it", () => {
    const reading = readSidecar(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["annotations"] = {
    [1] = {
      ["drawer"] = "lighten",
      ["pos0"] = "a",
      ["pos1"] = "b",
      ["text"] = "${"x".repeat(10_001)}",
    },
  },
}`);
    expect(reading).toMatchObject({ ok: true, highlights: [], oversized: 1 });
  });

  it("counts a mark the server would refuse for a NUL, and still sends the others", () => {
    // The server refuses a NUL in a position, the passage, the note or the
    // chapter, and one such mark sent would refuse the whole sidecar.
    const reading = readSidecar(`return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["annotations"] = {
    [1] = { ["drawer"] = "lighten", ["pos0"] = "a", ["pos1"] = "b", ["text"] = "kept" },
    [2] = { ["drawer"] = "lighten", ["pos0"] = "c", ["pos1"] = "d", ["text"] = "x\\0y" },
    [3] = { ["drawer"] = "lighten", ["pos0"] = "e", ["pos1"] = "f", ["text"] = "z", ["note"] = "n\\000" },
    [4] = { ["drawer"] = "lighten", ["pos0"] = "g", ["pos1"] = "h", ["text"] = "also kept", ["chapter"] = "c\\0" },
  },
}`);
    expect(reading).toMatchObject({
      ok: true,
      highlights: [
        { text: "kept", chapter: null },
        { text: "also kept", chapter: null },
      ],
      oversized: 2,
    });
  });
});

/** One mark as the property writes it into an `annotations` array. */
interface Mark {
  readonly drawer: boolean;
  readonly pos0: string;
  readonly pos1: string;
  readonly text: string;
  readonly note: string | null;
}

/** Text cut into a sidecar somewhere, written as fields so it prints as them. */
interface Splice {
  readonly at: number;
  readonly cut: number;
  readonly insert: string;
}

interface Drawn {
  readonly marks: readonly Mark[];
  readonly splice: Splice | null;
}

/** What a field's text is drawn from: any code point, and the ones a dump escapes. */
const FIELD = fc.string({
  unit: fc.oneof(
    fc.constantFrom('"', "\\", "\n", "\r", " ", "\u0000"),
    fc.string({ unit: "binary", minLength: 1, maxLength: 1 }),
  ),
  maxLength: 12,
});

/** Lua tokens, whole and broken, that a splice cuts into a sidecar. */
const FRAGMENTS = [
  "",
  '"',
  "'",
  "\\",
  "\n",
  "{",
  "}",
  "[",
  "]",
  "[[",
  "]]",
  "=",
  "==",
  ",",
  ";",
  "--",
  "--[[",
  "-",
  "\\x4",
  "\\u{110000}",
  "\\999",
  "\\z",
  "0x",
  "1e",
  "nil",
  "true",
  "return",
  "x",
];

const DRAWN: fc.Arbitrary<Drawn> = fc.record({
  marks: fc.array(
    fc.record({
      drawer: fc.boolean(),
      pos0: FIELD,
      pos1: FIELD,
      text: FIELD,
      note: fc.option(FIELD),
    }),
    { minLength: 1, maxLength: 4 },
  ),
  splice: fc.option(
    fc.record({
      at: fc.nat({ max: 4_000 }),
      cut: fc.nat({ max: 3 }),
      insert: fc.constantFrom(...FRAGMENTS),
    }),
    { freq: 2 },
  ),
});

/** A Lua string literal, escaped as KOReader's dump escapes one. */
function lua(value: string): string {
  // A line break as a backslash before a real one, and a NUL as three digits.
  const spelled: Readonly<Record<string, string>> = {
    "\n": "\\\n",
    "\r": "\\r",
    "\u0000": "\\000",
    '"': '\\"',
    "\\": "\\\\",
  };
  return `"${Array.from(value, (char) => spelled[char] ?? char).join("")}"`;
}

function sidecarOf({ marks, splice }: Drawn): string {
  const entries = marks.map((mark, index) => {
    const fields = [
      ...(mark.drawer ? ['["drawer"] = "lighten"'] : []),
      `["pos0"] = ${lua(mark.pos0)}`,
      `["pos1"] = ${lua(mark.pos1)}`,
      `["text"] = ${lua(mark.text)}`,
      ...(mark.note === null ? [] : [`["note"] = ${lua(mark.note)}`]),
    ];
    return `    [${index + 1}] = { ${fields.join(", ")} },`;
  });
  const whole = `return {
  ["partial_md5_checksum"] = "${DIGEST}",
  ["annotations"] = {
${entries.join("\n")}
  },
}`;
  if (splice === null) return whole;
  const at = splice.at % (whole.length + 1);
  return whole.slice(0, at) + splice.insert + whole.slice(at + splice.cut);
}

function trimmed(value: string | null): string | null {
  const kept = value?.trim() ?? "";
  return kept === "" ? null : kept;
}

/** The marks a well formed sidecar of these holds: highlights with a key. */
function keyed(marks: readonly Mark[]): Mark[] {
  return marks.filter(
    (mark) =>
      mark.drawer &&
      mark.pos0 !== "" &&
      mark.pos1 !== "" &&
      trimmed(mark.text) !== null,
  );
}

/** What a well formed sidecar of these marks reads as. */
function writtenAs(marks: readonly Mark[]): SidecarReading {
  // The fields the server refuses a NUL in, each as the property writes it.
  const stored = (mark: Mark) =>
    ![mark.pos0, mark.pos1, mark.text, mark.note ?? ""].some((field) =>
      field.includes("\u0000"),
    );
  return {
    ok: true,
    partialMd5: DIGEST,
    title: null,
    highlights: keyed(marks)
      .filter(stored)
      .map((mark) => ({
        pos0: mark.pos0,
        pos1: mark.pos1,
        text: trimmed(mark.text) ?? "",
        note: trimmed(mark.note),
        chapter: null,
        page: null,
        highlightedAt: null,
      })),
    oversized: keyed(marks).filter((mark) => !stored(mark)).length,
  };
}

/**
 * What is wrong with an answer to a sidecar something was cut into: only a
 * refusal the reader declares, or highlights the server can key.
 */
function faults(reading: SidecarReading): string[] {
  if (!reading.ok)
    return ["unreadable", "no-fingerprint"].includes(reading.reason)
      ? []
      : [`refused as ${reading.reason}`];
  const found = /^[0-9a-f]{32}$/.test(reading.partialMd5)
    ? []
    : [`a fingerprint of ${reading.partialMd5}`];
  for (const mark of reading.highlights) {
    if ([mark.pos0, mark.pos1, mark.text].includes(""))
      found.push("a highlight with an empty field");
    for (const field of [
      mark.pos0,
      mark.pos1,
      mark.text,
      mark.note,
      mark.chapter,
    ])
      if (field?.includes("\u0000")) found.push("a field carrying a NUL");
  }
  return found;
}

describe("any sidecar a member picks", () => {
  it(
    "reads back what it was written with, and answers for any cut into it",
    PROPERTY,
    async () => {
      expect(
        await holds(
          DRAWN,
          async (drawn) => {
            const reading = readSidecar(sidecarOf(drawn));
            const whole = drawn.splice === null;
            expect(whole ? reading : null).toEqual(
              whole ? writtenAs(drawn.marks) : null,
            );
            expect(whole ? [] : faults(reading)).toEqual([]);
            return reading;
          },
          {
            "is a whole sidecar read to a highlight": (drawn, reading) =>
              drawn.splice === null &&
              reading.ok &&
              reading.highlights.length > 0,
            "is a cut sidecar refused as unreadable": (drawn, reading) =>
              drawn.splice !== null &&
              !reading.ok &&
              reading.reason === "unreadable",
          },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("draws passages a dump escapes, and marks that are not highlights", async () => {
    await witness(DRAWN, {
      "writes a passage with a quote, a backslash or a line break": ({
        marks,
      }) => marks.some((mark) => /["\\\n\r]/.test(mark.text)),
      "writes a page bookmark, which has no drawer": ({ marks }) =>
        marks.some((mark) => !mark.drawer),
      "writes a NUL into a passage or a note": ({ marks }) =>
        marks.some((mark) =>
          `${mark.text}${mark.note ?? ""}`.includes("\u0000"),
        ),
    });
  });
});
