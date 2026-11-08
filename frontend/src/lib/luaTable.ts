/**
 * A reader for one Lua table literal, the shape a KOReader sidecar is written in.
 *
 * **Parsed, never evaluated.** A sidecar is `return { ... }` and KOReader
 * loads it by running it; this reads the literal and nothing else, so a file
 * carrying a function call, an operator or a variable is refused rather than
 * run. What it accepts is what KOReader's own `dump` writes plus the spellings
 * a hand edit produces: `[key] = value`, `name = value` and positional
 * values, strings in either quote or a long bracket, numbers in decimal or
 * hex, `true`, `false` and `nil`, and comments.
 *
 * **Bounded**, because the file is whatever the member picked: past
 * `MAX_SOURCE_LENGTH` characters or `MAX_DEPTH` nested tables it is refused.
 *
 * An answer, never a throw: `readLuaTable` says why it refused.
 */

export type LuaKey = string | number | boolean;
export type LuaValue = string | number | boolean | null | LuaTable;
/** A table: keys as Lua has them, so `[1]` and `["1"]` stay two keys. */
export type LuaTable = Map<LuaKey, LuaValue>;

/** Sixteen MiB of text, far past any sidecar of a well marked book. */
export const MAX_SOURCE_LENGTH = 16 * 1024 * 1024;
/** A sidecar nests four deep; a table eight times that is not one. */
export const MAX_DEPTH = 32;

export type LuaReading =
  | { readonly ok: true; readonly table: LuaTable }
  | { readonly ok: false; readonly reason: "too-large" | "not-a-table" };

class Refusal extends Error {}

const ESCAPES: Readonly<Record<string, string>> = {
  a: "\u0007",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
  v: "\v",
  "\\": "\\",
  '"': '"',
  "'": "'",
  "\n": "\n",
};

const NAME = /[A-Za-z_][A-Za-z0-9_]*/y;
const NUMBER =
  /(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(?![A-Za-z0-9_.])/y;

class Reader {
  private at = 0;

  constructor(private readonly source: string) {}

  /** The chunk: optional comments, `return`, one table, and nothing after. */
  chunk(): LuaTable {
    this.space();
    if (this.word() !== "return") throw new Refusal();
    const value = this.value(0);
    this.space();
    if (this.source[this.at] === ";") this.at += 1;
    this.space();
    if (this.at !== this.source.length || !(value instanceof Map))
      throw new Refusal();
    return value;
  }

  private space(): void {
    for (;;) {
      const rest = this.source.slice(this.at, this.at + 4);
      const char = this.source[this.at];
      if (char !== undefined && /\s/.test(char)) {
        this.at += 1;
      } else if (rest.startsWith("--")) {
        this.at += 2;
        const level = this.longOpening();
        if (level >= 0) {
          this.longBody(level);
        } else {
          const end = this.source.indexOf("\n", this.at);
          this.at = end < 0 ? this.source.length : end + 1;
        }
      } else {
        return;
      }
    }
  }

  private word(): string | null {
    NAME.lastIndex = this.at;
    const match = NAME.exec(this.source);
    if (!match) return null;
    this.at += match[0].length;
    return match[0];
  }

  private value(depth: number): LuaValue {
    this.space();
    const char = this.source[this.at];
    if (char === "{") return this.table(depth + 1);
    if (char === '"' || char === "'") return this.quoted(char);
    if (char === "[" && this.longOpening() >= 0) {
      return this.longBody(this.lastLevel);
    }
    if (char === "-") return this.negative();
    return this.number() ?? this.keyword();
  }

  /** A minus sign, which Lua allows only before a number here. */
  private negative(): number {
    this.at += 1;
    this.space();
    const number = this.number();
    if (number === null) throw new Refusal();
    return -number;
  }

  /** `true`, `false` or `nil`; any other name is a variable, and refused. */
  private keyword(): boolean | null {
    const word = this.word();
    if (word === "true") return true;
    if (word === "false") return false;
    if (word === "nil") return null;
    throw new Refusal();
  }

  private number(): number | null {
    NUMBER.lastIndex = this.at;
    const match = NUMBER.exec(this.source);
    if (!match) return null;
    this.at += match[0].length;
    const text = match[0];
    return /^0[xX]/.test(text) ? parseInt(text.slice(2), 16) : Number(text);
  }

  private table(depth: number): LuaTable {
    if (depth > MAX_DEPTH) throw new Refusal();
    this.at += 1;
    const table: LuaTable = new Map();
    let next = 1;
    for (;;) {
      this.space();
      if (this.source[this.at] === "}") {
        this.at += 1;
        return table;
      }
      // The key first, because a field spells it first: `[k] = v`, `name = v`,
      // or a bare `v` that takes the next position.
      const key = this.fieldKey(depth);
      const value = this.value(depth);
      if (key === null) {
        table.set(next, value);
        next += 1;
      } else {
        table.set(key, value);
      }
      this.separator();
    }
  }

  /**
   * The key of the field starting here, consuming it and its `=`, or null for
   * a positional value. A long bracket is a string value rather than a key.
   */
  private fieldKey(depth: number): LuaKey | null {
    if (this.source[this.at] === "[" && this.longOpeningAhead() < 0) {
      return this.bracketKey(depth);
    }
    return this.nameKey();
  }

  /** `[key] =`: a key is a string, a number or a boolean, never nil or a table. */
  private bracketKey(depth: number): LuaKey {
    this.at += 1;
    const key = this.value(depth);
    if (key === null || key instanceof Map) throw new Refusal();
    this.space();
    if (this.source[this.at] !== "]") throw new Refusal();
    this.at += 1;
    this.expect("=");
    return key;
  }

  /**
   * `name =`, or null with nothing consumed: a name before `==` or before no
   * `=` at all is the start of a positional value, which `value` refuses.
   */
  private nameKey(): string | null {
    const mark = this.at;
    const word = this.word();
    this.space();
    if (
      word !== null &&
      this.source[this.at] === "=" &&
      this.source[this.at + 1] !== "="
    ) {
      this.at += 1;
      return word;
    }
    this.at = mark;
    return null;
  }

  /** The `,` or `;` between fields, or the `}` that closes the table. */
  private separator(): void {
    this.space();
    const separator = this.source[this.at];
    if (separator === "," || separator === ";") {
      this.at += 1;
    } else if (separator !== "}") {
      throw new Refusal();
    }
  }

  private expect(char: string): void {
    this.space();
    if (this.source[this.at] !== char) throw new Refusal();
    this.at += 1;
  }

  private quoted(quote: string): string {
    this.at += 1;
    let out = "";
    for (;;) {
      const char = this.source[this.at];
      if (char === undefined || char === "\n") throw new Refusal();
      this.at += 1;
      if (char === quote) return out;
      if (char !== "\\") {
        out += char;
        continue;
      }
      out += this.escape();
    }
  }

  private escape(): string {
    const char = this.source[this.at];
    if (char === undefined) throw new Refusal();
    if (char in ESCAPES) {
      this.at += 1;
      return ESCAPES[char]!;
    }
    if (char === "\r") return this.lineBreakEscape();
    if (char === "z") return this.skippedSpace();
    if (char === "x") return this.hexEscape();
    if (char === "u") return this.unicodeEscape();
    return this.decimalEscape();
  }

  /** A backslash before a line break: `\r\n` or a lone `\r` is one newline. */
  private lineBreakEscape(): string {
    this.at += this.source[this.at + 1] === "\n" ? 2 : 1;
    return "\n";
  }

  /** `\z`, which drops the whitespace after it, line breaks included. */
  private skippedSpace(): string {
    this.at += 1;
    while (/\s/.test(this.source[this.at] ?? "")) this.at += 1;
    return "";
  }

  /** `\xXX`: exactly two hex digits, one byte. */
  private hexEscape(): string {
    const hex = this.source.slice(this.at + 1, this.at + 3);
    if (!/^[0-9a-fA-F]{2}$/.test(hex)) throw new Refusal();
    this.at += 3;
    return this.byte(parseInt(hex, 16));
  }

  /** `\u{XXX}`: one to six hex digits, no further than U+10FFFF. */
  private unicodeEscape(): string {
    const match = /^\{([0-9a-fA-F]{1,6})\}/.exec(
      this.source.slice(this.at + 1, this.at + 9),
    );
    const point = match ? parseInt(match[1]!, 16) : NaN;
    if (!match || point > 0x10ffff) throw new Refusal();
    this.at += 1 + match[0].length;
    return String.fromCodePoint(point);
  }

  /** `\ddd`: up to three decimal digits, one byte, so no higher than 255. */
  private decimalEscape(): string {
    const digits = /^\d{1,3}/.exec(this.source.slice(this.at, this.at + 3));
    if (!digits) throw new Refusal();
    const value = Number(digits[0]);
    if (value > 255) throw new Refusal();
    this.at += digits[0].length;
    return this.byte(value);
  }

  /**
   * One byte written as an escape. Lua strings are bytes and KOReader's dump
   * writes text as UTF-8 directly, escaping only control characters, so a
   * byte past ASCII here is a hand edit and is kept as the Latin-1 character
   * rather than refused.
   */
  private byte(value: number): string {
    return String.fromCharCode(value);
  }

  /** The level of the long bracket `longOpening` last consumed. */
  private lastLevel = 0;

  /** The level of a long bracket opening here, consuming it, or -1. */
  private longOpening(): number {
    const level = this.longOpeningAhead();
    if (level >= 0) {
      this.at += level + 2;
      this.lastLevel = level;
    }
    return level;
  }

  private longOpeningAhead(): number {
    const match = /^\[(=*)\[/.exec(this.source.slice(this.at, this.at + 64));
    return match ? match[1]!.length : -1;
  }

  /** A long bracket's body; a newline straight after the opening is dropped. */
  private longBody(level: number): string {
    const close = `]${"=".repeat(level)}]`;
    const end = this.source.indexOf(close, this.at);
    if (end < 0) throw new Refusal();
    let body = this.source.slice(this.at, end);
    this.at = end + close.length;
    if (body.startsWith("\r\n")) body = body.slice(2);
    else if (body.startsWith("\n")) body = body.slice(1);
    return body;
  }
}

/** The table a `return { ... }` chunk holds, or why it was refused. */
export function readLuaTable(source: string): LuaReading {
  if (source.length > MAX_SOURCE_LENGTH)
    return { ok: false, reason: "too-large" };
  try {
    return { ok: true, table: new Reader(source).chunk() };
  } catch (error) {
    // A refusal is the answer; a stack overflow on a pathological input is
    // too, and anything else is a defect here that should surface.
    if (error instanceof Refusal || error instanceof RangeError)
      return { ok: false, reason: "not-a-table" };
    throw error;
  }
}
