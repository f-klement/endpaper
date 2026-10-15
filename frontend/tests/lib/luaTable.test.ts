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
