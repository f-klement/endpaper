/**
 * The Lua table literal reader, over the spellings KOReader's dump writes and
 * the ones it refuses. The sidecar fixtures are written here in the shape a
 * KOReader sidecar has; none was taken off a device.
 */

import { describe, expect, it } from "vitest";

import { MAX_DEPTH, readLuaTable } from "../../src/lib/luaTable";

function read(source: string) {
  const reading = readLuaTable(source);
  if (!reading.ok) throw new Error(`refused: ${reading.reason}`);
  return reading.table;
}

describe("readLuaTable", () => {
  it("reads KOReader's own dump shape, with its leading comment", () => {
    const table = read(`-- we can read Lua syntax here!
return {
    ["partial_md5_checksum"] = "0123456789abcdef0123456789abcdef",
    ["percent_finished"] = 0.25,
    ["summary"] = {
        ["status"] = "reading",
    },
    [1] = true,
}
`);
    expect(table.get("partial_md5_checksum")).toBe(
      "0123456789abcdef0123456789abcdef",
    );
    expect(table.get("percent_finished")).toBe(0.25);
    expect((table.get("summary") as Map<string, unknown>).get("status")).toBe(
      "reading",
    );
    expect(table.get(1)).toBe(true);
  });

  it("keeps a numeric key apart from the same digits as a string", () => {
    const table = read('return { [1] = "a", ["1"] = "b" }');
    expect([table.get(1), table.get("1")]).toEqual(["a", "b"]);
  });

  it("numbers positional values from one", () => {
    const table = read('return { "a", "b"; x = 3, "c" }');
    expect([table.get(1), table.get(2), table.get(3), table.get("x")]).toEqual([
      "a",
      "b",
      "c",
      3,
    ]);
  });

  it("decodes the escapes Lua's %q writes, a backslash newline among them", () => {
    const table = read('return { ["t"] = "say \\"hi\\"\\\nnext\\9tab\\\\" }');
    expect(table.get("t")).toBe('say "hi"\nnext\ttab\\');
  });

  it("keeps UTF-8 text written directly", () => {
    expect(read('return { ["t"] = "Straße, café" }').get("t")).toBe(
      "Straße, café",
    );
  });

  it("reads a long bracket string and drops its first newline", () => {
    expect(read('return { ["t"] = [==[\nline ]] one]==] }').get("t")).toBe(
      "line ]] one",
    );
  });

  it("reads negative, exponent and hex numbers", () => {
    const table = read("return { a = -1.5, b = 2e3, c = 0x1F }");
    expect([table.get("a"), table.get("b"), table.get("c")]).toEqual([
      -1.5, 2000, 31,
    ]);
  });

  it("refuses a chunk that would run code rather than be read", () => {
    expect(readLuaTable('return { a = os.execute("x") }')).toEqual({
      ok: false,
      reason: "not-a-table",
    });
  });

  it("refuses anything after the table", () => {
    expect(readLuaTable("return {} print(1)").ok).toBe(false);
  });

  it("refuses nesting past its bound", () => {
    const deep = `return ${"{".repeat(MAX_DEPTH + 1)}${"}".repeat(MAX_DEPTH + 1)}`;
    expect(readLuaTable(deep)).toEqual({ ok: false, reason: "not-a-table" });
  });
});

/** The one string a `return { "..." }` chunk holds, `body` written raw. */
function decoded(body: string): unknown {
  return read(`return { "${body}" }`).get(1);
}

function refused(body: string): boolean {
  return !readLuaTable(`return { "${body}" }`).ok;
}

/** The named escapes of the Lua 5.4 manual, section 3.1, written out here. */
const NAMED: Readonly<Record<string, string>> = {
  a: "\x07",
  b: "\x08",
  f: "\x0c",
  n: "\x0a",
  r: "\x0d",
  t: "\x09",
  v: "\x0b",
  "\\": "\\",
  '"': '"',
  "'": "'",
};

describe("a string escape", () => {
  it("decodes every byte alike in decimal, padded decimal, hex and a code point", () => {
    // Bytes past 127 pin byte()'s Latin-1 choice rather than Lua: in Lua
    // `\u{80}` is two UTF-8 bytes and `\x80` is one.
    const wrong: string[] = [];
    for (let byte = 0; byte <= 255; byte += 1) {
      const hex = byte.toString(16).padStart(2, "0");
      const spellings = [
        `\\${byte}`,
        `\\${String(byte).padStart(3, "0")}`,
        `\\x${hex}`,
        `\\x${hex.toUpperCase()}`,
        `\\u{${hex}}`,
      ];
      for (const spelling of spellings) {
        if (decoded(spelling) !== String.fromCharCode(byte))
          wrong.push(spelling);
      }
    }
    expect(wrong).toEqual([]);
  });

  it("decodes each named escape the Lua manual lists", () => {
    for (const [letter, meant] of Object.entries(NAMED)) {
      expect(decoded(`\\${letter}`)).toBe(meant);
    }
  });

  it("refuses a backslash before any other ASCII character", () => {
    const leads = new Set([...Object.keys(NAMED), "x", "u", "z", "\n", "\r"]);
    const accepted: number[] = [];
    for (let code = 0; code < 128; code += 1) {
      const char = String.fromCharCode(code);
      if (leads.has(char) || /\d/.test(char)) continue;
      if (!refused(`\\${char}`)) accepted.push(code);
    }
    expect(accepted).toEqual([]);
  });

  it("reads a backslash before a line break as one newline, whatever the ending", () => {
    expect(["a\\\nb", "a\\\r\nb", "a\\\rb"].map(decoded)).toEqual([
      "a\nb",
      "a\nb",
      "a\nb",
    ]);
  });

  it("drops the whitespace after a z escape, line breaks included", () => {
    expect(decoded("a\\z \t\n  b")).toBe("ab");
  });

  it("stops a decimal escape at three digits", () => {
    expect(decoded("\\0659")).toBe("A9");
  });

  it("refuses a decimal escape past 255", () => {
    expect(refused("\\256")).toBe(true);
  });

  it("refuses a hex escape short of two hex digits", () => {
    expect([refused("\\x4"), refused("\\xg0")]).toEqual([true, true]);
  });

  it("reads a code point up to U+10FFFF and refuses one past it", () => {
    expect(decoded("\\u{10FFFF}")).toBe(String.fromCodePoint(0x10ffff));
    expect(refused("\\u{110000}")).toBe(true);
  });

  it("refuses a code point escape with no braces, no digits or seven", () => {
    expect([
      refused("\\u41"),
      refused("\\u{}"),
      refused("\\u{1234567}"),
    ]).toEqual([true, true, true]);
  });

  it("refuses a backslash that ends the source", () => {
    expect(readLuaTable('return { "a\\').ok).toBe(false);
  });
});

describe("a table field", () => {
  it("takes true, false and a number as a bracket key", () => {
    const table = read("return { [true] = 1, [false] = 2, [-2] = 3 }");
    expect([table.get(true), table.get(false), table.get(-2)]).toEqual([
      1, 2, 3,
    ]);
  });

  it("refuses nil or a table as a bracket key", () => {
    expect([
      readLuaTable("return { [nil] = 1 }").ok,
      readLuaTable("return { [{}] = 1 }").ok,
    ]).toEqual([false, false]);
  });

  it("refuses a bracket key with no closing bracket or no equals sign", () => {
    expect([
      readLuaTable("return { [1 = 2 }").ok,
      readLuaTable("return { [1] 2 }").ok,
    ]).toEqual([false, false]);
  });

  it("reads a long bracket string as a positional value, not a key", () => {
    expect(read("return { [[x]], [=[y]=] }")).toEqual(
      new Map([
        [1, "x"],
        [2, "y"],
      ]),
    );
  });

  it("reads true, false and nil as values", () => {
    expect(read("return { a = true, b = false, c = nil }")).toEqual(
      new Map<string, boolean | null>([
        ["a", true],
        ["b", false],
        ["c", null],
      ]),
    );
  });

  it("refuses a comparison where a field was expected", () => {
    expect(readLuaTable("return { a == 1 }").ok).toBe(false);
  });

  it("refuses two fields with no separator between them", () => {
    expect(readLuaTable("return { 1 2 }").ok).toBe(false);
  });

  it("refuses a minus sign before anything but a number", () => {
    expect(readLuaTable("return { -x }").ok).toBe(false);
  });

  it("refuses a symbol that starts no value", () => {
    expect(readLuaTable("return { @ }").ok).toBe(false);
  });
});
