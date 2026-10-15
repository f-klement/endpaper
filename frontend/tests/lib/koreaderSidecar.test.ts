/**
 * Highlights out of a KOReader sidecar, in both of the shapes KOReader has
 * written. The fixtures are written here after KOReader's
 * `ReaderAnnotation` and `ReaderBookmark` modules, which name every field
 * used; none was taken off a device.
 */

import { describe, expect, it } from "vitest";

import { readSidecar } from "../../src/lib/koreaderSidecar";
import { MAX_SOURCE_LENGTH } from "../../src/lib/luaTable";

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
});
