/**
 * What a PDF says about the book, read in the member's own browser.
 *
 * **This is the format with the most files and the least metadata, and the
 * reader is built around that rather than in spite of it.** A PDF that yields
 * nothing is the ordinary outcome: it answers `ok` with a record of nulls, the
 * scan page sees no title and falls to `lib/fileName.ts`, and the catalogue
 * lookup does the work. Nothing here treats an empty file as a failure, and
 * `not-a-pdf` is reserved for a file that is not one at all.
 *
 * ## What was measured, and against what
 *
 * **The corpus is 123 PDFs from four folders of the household's books share**,
 * which is that share's 243 less the 120 inside the Calibre library.
 * Re-derived 2026-09-08.
 * They are mostly technical and non fiction books that publishers produced,
 * rather than the scanned case the format is otherwise known for. 9 of them are
 * scans, which is few but is not none, and the section below is what those 9
 * say.
 *
 * Three instruments over those same 123, run 2026-09-07 and 2026-09-08:
 * **pypdf 6.10.2**, a **byte scanning prototype** reaching for the `xpacket`
 * markers and the trailer only, and **this reader**, driven over the files
 * under jsdom. Every count below names which of the three produced it, because
 * they do not agree and the disagreements are the finding.
 *
 * | this reader, over the 123 | |
 * |---|---|
 * | a `/Title` string that is not empty | 71 |
 * | a title it keeps, after the refusals below | **66, 53.7%** |
 * | an author it keeps | 66, 53.7% |
 * | both | 61, 49.6% |
 * | neither | 52, 42.3% |
 * | an identifier of any kind, ISBN or DOI | **3, 2.4%** |
 * | an ISBN | 1, 0.8% |
 * | a publisher, a language, a year | 14, 13, 14 |
 *
 * **An identifier is what this format does not supply**, stated as the
 * exclusion the formats epic asks for: 3 of 123, and 2 of those 3 are DOIs.
 * Series and series index have no field in either metadata block, so they are
 * always null. Nothing here reads a page or an image.
 *
 * ## The scanned case, and the premise it does not support
 *
 * The ticket this was built for says a scan's metadata names the scanner. **It
 * is half right, and the half it gets wrong is worth more than the half it gets
 * right.**
 *
 * The instrument is a list of tool names, `paper capture`, `image capture`,
 * `abbyy`, `finereader`, `scantailor`, `photoshop`, `imagetopdf`, `djvu`,
 * `scan`, `internet archive`, `scribe`, `xerox`, `canon`, `epson`,
 * `nuance pdf create`, `acrobat N.N capture`, `mupdf`, `pymupdf`, `skimage`,
 * `luratech` and `jbig`, matched case insensitively against `/Producer`,
 * `/Creator` **and `/Title`** as pypdf 6.10.2 reads them. It is an enumeration
 * and it is a measuring instrument rather than anything this module applies. A
 * narrower list selects a different set, which is why the list is written out.
 *
 * **9 of the 123 are selected, and this reader gets a title from 4 of them.**
 * Which 4 is the finding:
 *
 * * **3 are Internet Archive digitisations**, and they carry library catalogue
 *   metadata: `Automating Linux and UNIX system administration` with
 *   `Campi, Nate;Bauer, Kirk;Bauer, Kirk. Automating UNIX and Linux
 *   administration`, which is a MARC record's author field with a uniform title
 *   hanging off it. A programme that digitises for a catalogue writes the
 *   catalogue's record back into the file, and those three are better described
 *   than many of the publisher produced PDFs here.
 * * **the 4th is `Text operators for PDF`**, which names a piece of software
 *   rather than the book.
 *
 * So among the 6 that somebody scanned rather than a digitisation programme,
 * the title yield is **1 of 6**, and it is that one. This reader keeps it:
 * `usableTitle` below lists it among what it deliberately does not refuse, so
 * within this module it is a title, and a member sees it in a draft and fixes
 * it.
 *
 * **What holds across all 9, and is the part the design rests on: 0 of them
 * yield an identifier, a publisher or a year**, against 3, 14 and 14 in the
 * other 114. Even the scan that names its book perfectly gives nothing to look
 * it up by, so the handover to the filename path and the catalogue is what
 * pays either way.
 *
 * **One of the 9 carries its book's ISBN and this reader does not take it.**
 * Its `/Title` is `0534243126.djvu`, refused below as the name of a file, and
 * that stem is a valid ISBN-10. Sniffing an identifier out of a refused title
 * is not done here: it is one file, the check digit is the only thing that
 * would stand behind it, and the same book's actual filename is a plain author
 * and title that the catalogue lookup answers. Recorded because the next person
 * to notice it should find the reason rather than the observation.
 *
 * ## Why this parses the object graph rather than scanning for markers
 *
 * The byte scanning prototype found **41 titles over the 123 where this reader
 * finds 71**, and the reason is structural rather than a matter of effort:
 * **39 of the 123 keep the information dictionary inside a compressed object
 * stream**, which no scan reaches. Following `startxref` needs both cross
 * reference shapes as well: **71 of the 123 have a stream at `startxref` and
 * 52 a classic table**, which is the whole corpus split in two, and 3 of those
 * 52 also carry a stream further back in the `/Prev` chain, so 74 carry one
 * somewhere.
 *
 * The scan is also the more expensive of the two, which is the opposite of what
 * it looks like. It has to read the whole file: measured by that prototype, the
 * first `<?xpacket` sits at a median 26.9% of the way in and at 64.7 MB in the
 * largest. **This reader fetches a median 219 kB, 2.9% of the file**, against
 * files of a median 8.0 MB, because it seeks to what the cross reference points
 * at.
 *
 * ## Why no library
 *
 * Priced 2026-09-07 in a scratch project, `bun build --minify` then `gzip -9`,
 * bytes gzipped:
 * **pdfjs-dist 6.3.289 costs 502,948** (128,791 for the entry plus 374,157 for
 * the worker it cannot run without) and **pdf-lib 1.17.1 costs 179,941**, which
 * this reader beats on yield anyway: pdf-lib reads the information dictionary
 * and not the XMP packet, so it cannot supply the publisher, language, date or
 * identifier that only XMP carries here, and it refuses an encrypted document
 * outright.
 *
 * **This module ships as 5,520 bytes gzipped**, its own chunk out of
 * `bun run build`, 14,720 raw, loaded only when a member picks a `.pdf`. That
 * is 32.6 times smaller than the cheaper of the two libraries and 91 times
 * smaller than the one that matches it on yield. It costs no dependency at all
 * because the two things a PDF needs beyond parsing are `DecompressionStream`,
 * which the platform supplies and `lib/zip.ts` already relies on, and
 * `DOMParser`, which `lib/opf.ts` already relies on.
 *
 * ## The custody rule, and where the bounds are
 *
 * The bytes stay in the browser, for the reason `lib/epub.ts` states once.
 *
 * **Every number this reader takes out of the file is bounded before it is
 * believed**, and the bounds are the constants below. **Most carry a
 * measurement and two do not**: `MAX_DEPTH` and `MAX_RESOLVE_STEPS` are chosen
 * rather than derived, and say so at their own site. A PDF is an object graph a
 * member supplied, so the shapes
 * that matter are not truncation: a reference cycle, a nest deep enough to
 * exhaust the stack, a `/Length` that runs past the end of the file, and a
 * stream that inflates to more than the machine holds. Each has its own bound
 * and its own test.
 */

import { parseIsbn } from "./isbn";
import type { OpfIdentifier, OpfRecord } from "./opf";

/**
 * Why a file yielded nothing.
 *
 * **Four reasons and only one of them is new**, which is the shape
 * `fileReaders.FileFailure` asks for: `damaged`, `protected` and `no-inflate`
 * already mean the same thing to a member whichever reader said them. Only
 * `not-a-pdf` is per format, because it is the one that tells somebody to look
 * at what they picked.
 *
 * **There is no reason here for "carried no metadata", and there must not
 * be.** That is `ok` with a record of nulls, which is how the scan page is told
 * to use the filename instead. A failure would put a sentence in front of a
 * member for the ordinary case.
 */
export type PdfFailure =
  /** No `%PDF-` header, or no cross reference this reader could follow. */
  | "not-a-pdf"
  /** A PDF whose own offsets, lengths or streams do not agree with itself. */
  | "damaged"
  /** Encrypted. The strings would decode to noise rather than to text. */
  | "protected"
  /** This browser has no `DecompressionStream("deflate")`. */
  | "no-inflate";

export type PdfReading =
  | { readonly ok: true; readonly metadata: OpfRecord }
  | { readonly ok: false; readonly failure: PdfFailure };

/**
 * The signal every malformed file raises, and the only one `readPdf` catches.
 *
 * **A throw rather than a `null` at forty call sites.** `lib/mobi.ts` reads a
 * fixed set of offsets and answers `null` past the end at each; a PDF is a
 * recursive grammar, so the same discipline there would be a `null` check
 * between every pair of tokens and the one that was forgotten would be the
 * bug. Here the parser throws, `readPdf` catches this class and nothing else,
 * and a throw of any other class is a defect rather than something a file did.
 * `pdf.test.ts` drives a sweep of malformed input and asserts no other escapes.
 */
class PdfError extends Error {
  constructor(
    readonly failure: PdfFailure,
    message: string,
  ) {
    super(message);
    this.name = "PdfError";
  }
}

/**
 * How far back from the end `startxref` is looked for.
 *
 * Measured: it begins 20 to 28 bytes before the end in 123 of 123, so this is
 * 146 times the largest. The headroom is for a producer that leaves junk after
 * `%%EOF`, which is legal in practice and is why every reader searches rather
 * than seeking.
 */
const TAIL_BYTES = 4096;

/**
 * How many cross reference sections the `/Prev` chain may visit.
 *
 * Measured: 1 to 12 across the 123, median 1. Sections are how an incremental
 * update is recorded, so the number is the file's own history and a crafted
 * file can make it a cycle. **Already visited offsets are refused as well**, so
 * this bounds a chain that grows rather than one that loops.
 */
const MAX_XREF_SECTIONS = 64;

/**
 * How many object offsets are kept.
 *
 * Measured by this reader over the 123: 49 to 41,588, median 5,528. A file
 * declares its own count, so this is what stops a `/Size` of four billion from
 * being believed.
 */
const MAX_XREF_ENTRIES = 500_000;

/**
 * How much is fetched at a cross reference section before it is looked at.
 *
 * A cross reference stream and its dictionary fit in this in 123 of 123, the
 * largest raw stream this reader opens measuring 296,556 bytes. A classic table
 * is the size of the file's object count: 20 bytes an entry, and the largest
 * subsection declared across the 123 is 51,418 entries, so the table alone can
 * want a megabyte. The window is grown
 * once, to `MAX_XREF_BYTES`, and only when a table has run past it.
 */
const XREF_WINDOW_BYTES = 256 * 1024;

/** The ceiling on one grown window, 4.1 times the largest table measured. */
const MAX_XREF_BYTES = 4 * 1024 * 1024;

/**
 * How much is fetched at an object's offset.
 *
 * The information dictionary is a few hundred bytes and the largest here is
 * under 4 kB; this is the window its dictionary and, for a stream, its header
 * are parsed out of. A stream's own bytes are fetched separately, against
 * `/Length`.
 */
const OBJECT_WINDOW_BYTES = 64 * 1024;

/**
 * How many raw bytes one stream may claim, and how many it may inflate to.
 *
 * Measured over the 123: the largest stream this reader opens is 296,556 bytes
 * raw, an XMP packet, and the largest any of them inflates to is 2,866,290, a
 * cross reference stream, so the inflated ceiling has 5.9 times the headroom.
 * It is what refuses a compression bomb: 300 kB of deflated zeroes inflates to
 * roughly 300 MB, and this stops at 16 MB with the stream cancelled rather than
 * drained.
 */
const MAX_STREAM_BYTES = 8 * 1024 * 1024;
const MAX_INFLATED_BYTES = 16 * 1024 * 1024;

/**
 * The total this reader will take out of the file, and how many reads.
 *
 * Measured by this reader over the 123: 129 kB to 1.23 MB fetched, median
 * 219 kB, against files of 146 kB to 65.1 MB. **The bound is on the total
 * rather than on any one read**, because the ways a crafted file can make this
 * expensive are a long `/Prev` chain, a deep reference chain and a large table,
 * and bounding each of those separately still multiplies. 32 MB is 27.4 times
 * the largest measured.
 */
const MAX_FETCH_BYTES = 32 * 1024 * 1024;

/**
 * How deep a nested container may go, and how long a reference chain may be.
 *
 * The parser is recursive, so the first of these is what stops
 * `[[[[[...]]]]]` from exhausting the stack; the second is what stops
 * `1 0 obj 2 0 R endobj  2 0 obj 1 0 R endobj` from looping. **A visited set
 * as well as a count**, because a two object cycle would otherwise be walked
 * to the limit every time rather than refused at the second step.
 *
 * **Both numbers are chosen and neither is measured**, which is the honest
 * label: nothing in the corpus nests or chains deep enough to be near either,
 * so there is no distribution to take a headroom from. What they are set
 * against is the stack and this reader's own patience, not a file.
 */
const MAX_DEPTH = 32;
const MAX_RESOLVE_STEPS = 16;

/**
 * How many objects one object stream may declare.
 *
 * Measured by this reader over the 123: 255 at the largest. An object stream
 * holds a header of number and offset pairs, so a declared count is a loop
 * bound a file chooses.
 */
const MAX_OBJSTM_OBJECTS = 8192;

/** The window a year in a date has to fall in. `lib/mobi.ts` states the rule. */
const YEAR_RANGE = [1450, 2100] as const;

// --- the object model -------------------------------------------------------

interface PdfName {
  readonly kind: "name";
  readonly value: string;
}
interface PdfString {
  readonly kind: "string";
  readonly value: Uint8Array;
}
interface PdfRef {
  readonly kind: "ref";
  readonly num: number;
}
interface PdfDict {
  readonly kind: "dict";
  readonly entries: ReadonlyMap<string, PdfValue>;
}
interface PdfArray {
  readonly kind: "array";
  readonly items: readonly PdfValue[];
}

type PdfValue =
  number | boolean | null | PdfName | PdfString | PdfRef | PdfDict | PdfArray;

function isDict(value: PdfValue): value is PdfDict {
  return typeof value === "object" && value !== null && value.kind === "dict";
}

function isRef(value: PdfValue): value is PdfRef {
  return typeof value === "object" && value !== null && value.kind === "ref";
}

// --- the lexer --------------------------------------------------------------

const SPACE = new Set([0x00, 0x09, 0x0a, 0x0c, 0x0d, 0x20]);
const DELIMITER = new Set([
  0x28, 0x29, 0x3c, 0x3e, 0x5b, 0x5d, 0x7b, 0x7d, 0x2f, 0x25,
]);

function isRegular(byte: number): boolean {
  return !SPACE.has(byte) && !DELIMITER.has(byte);
}

/**
 * One PDF object, read out of a buffer somebody else supplied.
 *
 * **Every method that advances the cursor checks the end first**, so the class
 * of bug this cannot have is a read past the buffer: a truncated object throws
 * `damaged` rather than returning whatever a `Uint8Array` answers off its end,
 * which is `undefined` and would flow silently into a comparison.
 */
class Lexer {
  at: number;

  constructor(
    private readonly bytes: Uint8Array,
    at = 0,
  ) {
    this.at = at;
  }

  private byte(offset = 0): number {
    const index = this.at + offset;
    // `undefined` past the end would compare false against every byte here and
    // turn a truncated file into an infinite loop rather than a refusal.
    return index >= 0 && index < this.bytes.length ? this.bytes[index]! : -1;
  }

  private end(): boolean {
    return this.at >= this.bytes.length;
  }

  /** Whitespace and comments, which may separate any two tokens. */
  skip(): void {
    for (;;) {
      const byte = this.byte();
      if (byte >= 0 && SPACE.has(byte)) {
        this.at += 1;
      } else if (byte === 0x25) {
        while (!this.end() && this.byte() !== 0x0a && this.byte() !== 0x0d) {
          this.at += 1;
        }
      } else {
        return;
      }
    }
  }

  /** The literal at the cursor, without moving it. */
  looking(literal: string): boolean {
    for (let index = 0; index < literal.length; index += 1) {
      if (this.byte(index) !== literal.charCodeAt(index)) return false;
    }
    return true;
  }

  take(literal: string): boolean {
    if (!this.looking(literal)) return false;
    this.at += literal.length;
    return true;
  }

  /** The next run of regular characters, or `""` at a delimiter. */
  token(): string {
    let out = "";
    while (!this.end() && isRegular(this.byte())) {
      out += String.fromCharCode(this.byte());
      this.at += 1;
    }
    return out;
  }

  object(depth = 0): PdfValue {
    if (depth > MAX_DEPTH) {
      throw new PdfError("damaged", "objects nested past the depth limit");
    }
    this.skip();
    if (this.end()) throw new PdfError("damaged", "object ended early");

    if (this.take("<<")) return this.dictionary(depth);
    if (this.byte() === 0x3c) return this.hexString();
    if (this.byte() === 0x28) return this.literalString();
    if (this.byte() === 0x2f) return { kind: "name", value: this.name() };
    if (this.take("[")) return this.array(depth);

    const start = this.at;
    const token = this.token();
    if (token === "") {
      throw new PdfError("damaged", `unreadable byte ${this.byte()}`);
    }
    if (token === "true") return true;
    if (token === "false") return false;
    if (token === "null") return null;

    if (/^\d+$/.test(token)) {
      const reference = this.reference(Number(token));
      if (reference !== null) return reference;
    }
    if (/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(token)) return Number(token);

    // A keyword where a value belongs, such as `endobj` in an empty entry.
    this.at = start;
    throw new PdfError("damaged", `not a value: ${token}`);
  }

  /**
   * `N G R` when that is what follows a number, else nothing consumed.
   *
   * **The generation is read and thrown away.** Every entry this reader
   * resolves comes from a cross reference that already fixed the generation,
   * and matching on it would refuse a file whose table and body disagree by one
   * while gaining nothing: there is no second object here to confuse it with.
   */
  private reference(num: number): PdfRef | null {
    const save = this.at;
    this.skip();
    const generation = this.token();
    if (/^\d+$/.test(generation)) {
      this.skip();
      if (this.take("R") && !isRegular(this.byte())) {
        return { kind: "ref", num };
      }
    }
    this.at = save;
    return null;
  }

  private dictionary(depth: number): PdfDict {
    const entries = new Map<string, PdfValue>();
    for (;;) {
      this.skip();
      if (this.take(">>")) return { kind: "dict", entries };
      if (this.end()) throw new PdfError("damaged", "dictionary ended early");
      if (this.byte() !== 0x2f) {
        throw new PdfError("damaged", "dictionary key is not a name");
      }
      const key = this.name();
      const value = this.object(depth + 1);
      // **First wins**, which is what a duplicated key means in a file written
      // by two producers in turn: the corpus carries `Multiple definitions in
      // dictionary` on real files, and taking the later one would let an
      // appended entry override the original.
      if (!entries.has(key)) entries.set(key, value);
    }
  }

  private array(depth: number): PdfArray {
    const items: PdfValue[] = [];
    for (;;) {
      this.skip();
      if (this.take("]")) return { kind: "array", items };
      if (this.end()) throw new PdfError("damaged", "array ended early");
      if (items.length >= MAX_XREF_ENTRIES) {
        throw new PdfError("damaged", "array longer than anything real");
      }
      items.push(this.object(depth + 1));
    }
  }

  /** `/Name`, with `#xx` unescaped, which is how a name carries a space. */
  private name(): string {
    this.at += 1;
    const raw = this.token();
    return raw.replace(/#([0-9A-Fa-f]{2})/g, (_, hex: string) =>
      String.fromCharCode(parseInt(hex, 16)),
    );
  }

  private hexString(): PdfString {
    this.at += 1;
    let hex = "";
    while (!this.end() && this.byte() !== 0x3e) {
      const byte = this.byte();
      if (!SPACE.has(byte)) hex += String.fromCharCode(byte);
      this.at += 1;
      if (hex.length > MAX_STREAM_BYTES) {
        throw new PdfError("damaged", "hex string longer than anything real");
      }
    }
    if (this.end()) throw new PdfError("damaged", "hex string ended early");
    this.at += 1;
    // An odd digit count is padded with a zero, which the format says outright.
    const digits = hex.length % 2 === 0 ? hex : `${hex}0`;
    const out = new Uint8Array(digits.length / 2);
    for (let index = 0; index < out.length; index += 1) {
      const pair = digits.slice(index * 2, index * 2 + 2);
      const value = parseInt(pair, 16);
      // A non hex digit inside makes the whole string unreadable rather than
      // silently zero: `NaN` written into a `Uint8Array` is 0, which is a byte.
      if (Number.isNaN(value)) {
        throw new PdfError("damaged", "hex string holds a non hex digit");
      }
      out[index] = value;
    }
    return { kind: "string", value: out };
  }

  private literalString(): PdfString {
    this.at += 1;
    const out: number[] = [];
    let depth = 1;
    while (!this.end()) {
      if (out.length > MAX_STREAM_BYTES) {
        throw new PdfError("damaged", "string longer than anything real");
      }
      const byte = this.byte();
      this.at += 1;
      if (byte === 0x5c) {
        const escaped = this.byte();
        this.at += 1;
        const simple: Record<number, number> = {
          0x6e: 0x0a,
          0x72: 0x0d,
          0x74: 0x09,
          0x62: 0x08,
          0x66: 0x0c,
        };
        if (escaped in simple) {
          out.push(simple[escaped]!);
        } else if (escaped >= 0x30 && escaped <= 0x37) {
          let code = escaped - 0x30;
          for (let digit = 0; digit < 2; digit += 1) {
            const next = this.byte();
            if (next < 0x30 || next > 0x37) break;
            code = code * 8 + (next - 0x30);
            this.at += 1;
          }
          out.push(code & 0xff);
        } else if (escaped === 0x0d) {
          // A backslash before a line break is a continuation and adds nothing.
          if (this.byte() === 0x0a) this.at += 1;
        } else if (escaped === 0x0a) {
          // Same, for the other line ending.
        } else if (escaped < 0) {
          throw new PdfError("damaged", "string ended inside an escape");
        } else {
          out.push(escaped);
        }
      } else if (byte === 0x28) {
        depth += 1;
        out.push(byte);
      } else if (byte === 0x29) {
        depth -= 1;
        if (depth === 0) return { kind: "string", value: new Uint8Array(out) };
        out.push(byte);
      } else {
        out.push(byte);
      }
    }
    throw new PdfError("damaged", "string ended early");
  }
}

/**
 * The next token as a non negative integer, or `null` when it is not one.
 *
 * **Empty is `null` and not zero**, which is the point of the helper existing
 * at all: `Number("")` is `0` and passes every check a caller would write, so
 * every place that reads a count or an offset out of a token goes through here
 * rather than through `Number` and a range test.
 */
function numeric(lexer: Lexer): number | null {
  const token = lexer.token();
  if (!/^\d+$/.test(token)) return null;
  const value = Number(token);
  return Number.isSafeInteger(value) ? value : null;
}

// --- text -------------------------------------------------------------------

/**
 * The 32 characters where PDFDocEncoding is not Latin-1.
 *
 * **Measured rather than assumed**: reading these bytes as Latin-1 was wrong in
 * 3 of the 71 titles in the corpus, giving `VBA Developer's Handbook\x92` for
 * `…Handbook™` and dropping the en dash out of a third. The rest of the range
 * agrees with Latin-1, so this is the whole of the difference and not a sample
 * of it.
 */
const PDF_DOC_ENCODING =
  // The em dash and en dash are written as escapes, not because this file may
  // not hold one but because `tests/houseRules.test.ts` reads the source and
  // has no exemption list by design. Spelling them out keeps the rule total.
  "\u2022\u2020\u2021\u2026\u2014\u2013ƒ⁄‹›−‰„" + "“”‘’‚™ﬁﬂŁŒŠŸŽıłœšž�";

const utf16be = new TextDecoder("utf-16be");
const utf16le = new TextDecoder("utf-16le");
const utf8 = new TextDecoder("utf-8");

/**
 * A PDF text string as text.
 *
 * Three encodings and the file says which with its first two bytes: a UTF-16
 * byte order mark either way, and PDFDocEncoding when there is none. A
 * `TextDecoder` for `utf-16be` is not universal, so the failure is caught and
 * the bytes fall to the encoding they would have had.
 */
function decodeText(bytes: Uint8Array): string {
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    try {
      return utf16be.decode(bytes.subarray(2));
    } catch {
      /* falls through to PDFDocEncoding */
    }
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    try {
      return utf16le.decode(bytes.subarray(2));
    } catch {
      /* falls through to PDFDocEncoding */
    }
  }
  let out = "";
  for (const byte of bytes) {
    out +=
      byte >= 0x80 && byte <= 0x9f
        ? PDF_DOC_ENCODING[byte - 0x80]!
        : String.fromCharCode(byte);
  }
  return out;
}

/**
 * A value with its whitespace collapsed, or `null` when nothing is left.
 *
 * `null` rather than `""`, for the reason `lib/mobi.ts` gives: `OpfRecord` says
 * every field is absent rather than empty, and a caller reading `record.title`
 * to decide whether the file named one would take `""` for a title. **Six of
 * the 123 carry a `/Title` that is the empty string**, so this arm is the
 * ordinary case rather than a defensive one.
 */
function clean(value: string | null): string | null {
  if (value === null) return null;
  // Control characters go, including the NULs a producer pads with. Collapsing
  // the whitespace as well is what makes a title that a typesetter wrapped over
  // two lines compare equal to the one on the cover.
  const trimmed = value
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * A title, or `null` when what the file carries is not one.
 *
 * **Two refusals, both structural, and the exclusion is stated rather than
 * grown.** Measured over the 71 titles the corpus carries:
 *
 * * **empty**, which `clean` already answers `null` for: **6 of the 76
 *   `/Title` entries pypdf 6.10.2 finds across the 123 are the empty string**.
 * * **the name of a file**, 5 of the 71 titles this reader reads: `453777_1_En_Print.indd`, `0534243126.djvu`,
 *   `Algebra_Cheat_Sheet.doc` and `Sammelmappe1.pdf` twice. The rule is that the
 *   value has no whitespace, ends in a dot and two to five alphanumerics, and
 *   the part before that dot is not one run of letters. **The last clause is
 *   what keeps `Node.js` and `ASP.NET`**, which are titles in this very
 *   library's subject area and which a rule about dot extensions alone would
 *   throw away.
 *
 * **What it deliberately does not refuse**, stated as the exclusion because
 * every alternative is a list of spellings that goes stale in the first
 * language the corpus does not contain:
 *
 * * **A filename whose stem is one English word**, which is the largest class
 *   it lets through and the one a reader of the rule above will not see:
 *   `thesis.pdf`, `manuscript.docx` and `untitled.indd` are all kept, and the
 *   corpus's own `Sammelmappe1.pdf` is one character from the kept
 *   `Sammelmappe.pdf`. **The signal separating those from `Node.js` is not in
 *   the value**, it is whether the string is this file's own name, and
 *   `readPdf` takes a `Blob` and cannot see that. Pinned by a test, so the next
 *   person changing the rule is told what it accepts.
 * * `Untitled`, 2 of 71, and a typesetter's job name such as
 *   `amiajnl-2011-000464 544..551` or `Text operators for PDF`, 2 more.
 *
 * All of those reach the member as a draft they review before it is committed,
 * which is the trade this refusal is priced against.
 */
const FILENAME_SHAPED = /^(\S+)\.[A-Za-z0-9]{2,5}$/;

function usableTitle(value: string | null): string | null {
  if (value === null) return null;
  const shaped = FILENAME_SHAPED.exec(value);
  if (shaped !== null && !/^[A-Za-z]+$/.test(shaped[1]!)) return null;
  return value;
}

/**
 * An author, or `null` when what the file carries is not a name.
 *
 * One refusal: a value with no letter in it. **1 of the 67 names the corpus
 * carries in one block or the other**, `0007855`, a production system's
 * operator id, which leaves 66.
 *
 * **The scanner operator is not refused and cannot be**, which is the ticket's
 * own point rather than a gap here: `zywei`, `scholars` and `Paul` are the
 * `/Author` of three books in this corpus and nothing in the file says they are
 * not the writer.
 */
function usableAuthor(value: string | null): string | null {
  if (value === null) return null;
  return /\p{L}/u.test(value) ? value : null;
}

// --- reading the file -------------------------------------------------------

/**
 * The file, as bounded reads.
 *
 * **One place holds the running total**, so the ceiling is on what this reader
 * costs rather than on any single read: a crafted file's ways of being
 * expensive multiply, and bounding each separately still lets three of them
 * through together.
 */
class Source {
  private spent = 0;

  constructor(private readonly blob: Blob) {}

  get size(): number {
    return this.blob.size;
  }

  async read(from: number, length: number): Promise<Uint8Array> {
    if (from < 0 || length < 0 || from >= this.blob.size)
      return new Uint8Array();
    const to = Math.min(from + length, this.blob.size);
    this.spent += to - from;
    if (this.spent > MAX_FETCH_BYTES) {
      throw new PdfError("damaged", "reading this file wants too many bytes");
    }
    return new Uint8Array(await this.blob.slice(from, to).arrayBuffer());
  }
}

/**
 * Inflate, or say the browser cannot.
 *
 * **`deflate` and not `deflate-raw`**, which is where this differs from
 * `lib/zip.ts`: a PDF `FlateDecode` stream carries the zlib header a zip entry
 * does not.
 *
 * **The raw retry is not backed by a file in the corpus: 0 of the 123 reach
 * it**, and that is stated rather than left as an implied measurement. It is
 * kept because a producer omitting the header is a shape other readers carry
 * recovery for, and it costs one further attempt on a stream that has already
 * failed. `pdf.test.ts` exercises both attempts failing.
 */
async function inflate(raw: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream === "undefined") {
    throw new PdfError("no-inflate", "this browser cannot inflate");
  }
  for (const format of ["deflate", "deflate-raw"] as const) {
    let stream: DecompressionStream;
    try {
      stream = new DecompressionStream(format);
    } catch {
      continue;
    }
    const copy = new Uint8Array(raw);
    const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
      start(controller) {
        controller.enqueue(copy);
        controller.close();
      },
    });
    const reader = source.pipeThrough(stream).getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    let broke = false;
    for (;;) {
      let done: boolean;
      let value: Uint8Array | undefined;
      try {
        ({ done, value } = await reader.read());
      } catch {
        // Not a deflate stream under this format, or one that stops halfway.
        broke = true;
        break;
      }
      if (done || value === undefined) break;
      total += value.length;
      if (total > MAX_INFLATED_BYTES) {
        // **Cancelled rather than drained.** The bound is on what is held, so
        // reading the rest to find out how big it was would defeat it.
        release(reader);
        throw new PdfError("damaged", "a stream inflates past the limit");
      }
      chunks.push(value);
    }
    if (broke) {
      release(reader);
      continue;
    }
    const out = new Uint8Array(total);
    let at = 0;
    for (const chunk of chunks) {
      out.set(chunk, at);
      at += chunk.length;
    }
    return out;
  }
  throw new PdfError("damaged", "a stream is not deflate under either header");
}

/**
 * Let go of an inflater this reader has stopped reading.
 *
 * **Not awaited, and that is the point.** Two paths stop reading early, a
 * stream that is not deflate under the header being tried and one that inflates
 * past the ceiling, and both leave a reader holding a lock on a transform that
 * may never settle. Awaiting the cancel puts the reader's own bound at the
 * mercy of the thing it is bounding; the failure is reported either way, and
 * what the cancel is for is releasing the memory behind it.
 */
function release(reader: ReadableStreamDefaultReader<Uint8Array>): void {
  void reader.cancel().catch(() => {
    // A cancel on a stream that already errored rejects, and there is nothing
    // to do about it: this reader is finished with the stream either way.
  });
}

/**
 * Undo a PNG row predictor.
 *
 * Measured by this reader over the 123: **46 declare a predictor and all 46
 * declare `/Predictor 12`**, with `/Columns` between 3 and 7. Without this the
 * offsets come out as differences and every object is looked for in the wrong
 * place, which reads as a file that carries no metadata rather than as an
 * error.
 */
function unpredict(data: Uint8Array, columns: number): Uint8Array {
  // **Bounded against the data rather than only against zero.** `/Columns` is
  // a number the file chose, and `new Uint8Array(columns)` answers a
  // `RangeError` for a huge one and for `Infinity`, which is not a `PdfError`
  // and so escapes this module's stated contract. A predictor with more columns
  // than there are bytes to predict cannot describe this stream whatever it
  // says, and the largest real value across the 123 is 7.
  if (!Number.isInteger(columns) || columns <= 0 || columns > data.length) {
    throw new PdfError("damaged", `a predictor of ${columns} columns`);
  }
  const rows = Math.floor(data.length / (columns + 1));
  const out = new Uint8Array(rows * columns);
  const previous = new Uint8Array(columns);
  for (let row = 0; row < rows; row += 1) {
    const at = row * (columns + 1);
    const filter = data[at]!;
    const current = data.subarray(at + 1, at + 1 + columns);
    const decoded = out.subarray(row * columns, row * columns + columns);
    for (let index = 0; index < columns; index += 1) {
      const left = index > 0 ? decoded[index - 1]! : 0;
      const up = previous[index]!;
      const upLeft = index > 0 ? previous[index - 1]! : 0;
      const byte = current[index]!;
      switch (filter) {
        case 0:
          decoded[index] = byte;
          break;
        case 1:
          decoded[index] = (byte + left) & 0xff;
          break;
        case 2:
          decoded[index] = (byte + up) & 0xff;
          break;
        case 3:
          decoded[index] = (byte + ((left + up) >> 1)) & 0xff;
          break;
        case 4: {
          const estimate = left + up - upLeft;
          const dLeft = Math.abs(estimate - left);
          const dUp = Math.abs(estimate - up);
          const dUpLeft = Math.abs(estimate - upLeft);
          const best =
            dLeft <= dUp && dLeft <= dUpLeft
              ? left
              : dUp <= dUpLeft
                ? up
                : upLeft;
          decoded[index] = (byte + best) & 0xff;
          break;
        }
        default:
          throw new PdfError("damaged", `unknown row filter ${filter}`);
      }
    }
    previous.set(decoded);
  }
  return out;
}

/** Where an object lives: at a byte offset, or inside an object stream. */
type Entry =
  | { readonly in: "file"; readonly at: number }
  | { readonly in: "stream"; readonly stream: number; readonly index: number };

/**
 * One document, as much of it as six fields need.
 *
 * **The cross reference is read and the body is not.** Nothing here opens a
 * page, a font or an image; what it follows is `/Info` and `/Root /Metadata`,
 * which is why the reader costs a median 2.9% of the file.
 */
class Document {
  private readonly xref = new Map<number, Entry>();
  private readonly trailer = new Map<string, PdfValue>();
  private readonly streams = new Map<number, ReadonlyMap<number, PdfValue>>();

  constructor(private readonly source: Source) {}

  /** Walk the `/Prev` chain from `startxref`, newest section first. */
  async load(): Promise<void> {
    const tail = await this.source.read(
      Math.max(0, this.source.size - TAIL_BYTES),
      TAIL_BYTES,
    );
    const start = lastStartxref(
      tail,
      Math.max(0, this.source.size - TAIL_BYTES),
    );
    if (start === null) throw new PdfError("not-a-pdf", "no startxref");

    const seen = new Set<number>();
    let at: number | null = start;
    while (at !== null && !seen.has(at) && seen.size < MAX_XREF_SECTIONS) {
      seen.add(at);
      const section: PdfDict | null = await this.section(at);
      if (section === null) break;
      for (const [key, value] of section.entries) {
        if (!this.trailer.has(key)) this.trailer.set(key, value);
      }
      // **A hybrid file's `/XRefStm` is followed before `/Prev`**, because it
      // holds the entries the classic table beside it deliberately omits: a
      // reader that skipped it would find the table's own objects and none of
      // the ones in object streams.
      const hybrid = section.entries.get("XRefStm");
      if (typeof hybrid === "number" && !seen.has(hybrid)) {
        seen.add(hybrid);
        await this.section(hybrid);
      }
      const previous = section.entries.get("Prev");
      at = typeof previous === "number" ? previous : null;
    }
    if (this.xref.size === 0) {
      throw new PdfError(
        "not-a-pdf",
        "no cross reference this reader can read",
      );
    }
  }

  /**
   * One section, table or stream, adding its entries and answering its trailer.
   *
   * **An entry already known is never overwritten**, which is what makes the
   * newest section win: the chain is walked from the end of the file backwards,
   * so the first answer for an object number is the current one and an older
   * revision must not replace it.
   */
  private async section(at: number): Promise<PdfDict | null> {
    let window = await this.source.read(at, XREF_WINDOW_BYTES);
    if (window.length === 0) return null;

    const lexer = new Lexer(window);
    lexer.skip();
    if (lexer.looking("xref")) {
      // A classic table can want more than the first window holds.
      if (window.length === XREF_WINDOW_BYTES) {
        window = await this.source.read(at, MAX_XREF_BYTES);
      }
      return this.classicTable(new Lexer(window, 0));
    }
    return await this.crossReferenceStream(at, window);
  }

  /**
   * A classic table, and the trailer that ends it.
   *
   * This spun forever on a table whose subsection header was `(`:
   * `Lexer.token()` answers `""` at a delimiter without advancing,
   * `Number("")` is 0, and every check a count is given passes. It is a
   * synchronous loop, so it is a dead tab rather than a slow read, and **no
   * assertion inside a test can catch that**: the suite hung on this file for
   * 600 seconds rather than failing it, twice.
   *
   * **Two guards, and it is `numeric` that refuses this input.** The cursor
   * progress check below it cannot fire while `numeric` is the loop's first
   * act, because `numeric` cannot answer non null without consuming a digit.
   * It is a backstop for a later arm that forgets to consume, and it is a live
   * one rather than dead code: measured by both review seats independently, a
   * mutant with `numeric`'s digit test removed turns the hang into `damaged`
   * here instead. So each of the two is sufficient alone, and removing both is
   * what brings the hang back.
   */
  private classicTable(lexer: Lexer): PdfDict | null {
    lexer.skip();
    if (!lexer.take("xref")) return null;
    for (;;) {
      const before = lexer.at;
      lexer.skip();
      if (lexer.take("trailer")) {
        const value = lexer.object();
        return isDict(value) ? value : null;
      }
      // A `null` rather than a throw: a table that ends where a subsection
      // header should be is a truncated file and not a hostile one. The
      // docstring above carries the rest.
      const first = numeric(lexer);
      lexer.skip();
      const count = numeric(lexer);
      if (first === null || count === null) return null;
      // No check for a negative here and one in `crossReferenceStream`, which
      // is not an oversight either way: `numeric` matches digits only, so a
      // negative cannot arrive here, while a cross reference stream's `/Index`
      // is a parsed array and a file can put anything in it.
      if (count > MAX_XREF_ENTRIES) {
        throw new PdfError("damaged", "a cross reference run of no real size");
      }
      for (let index = 0; index < count; index += 1) {
        lexer.skip();
        const offset = numeric(lexer);
        lexer.skip();
        lexer.token(); // the generation, which the entry is not looked up by
        lexer.skip();
        const used = lexer.take("n");
        if (!used && !lexer.take("f")) {
          throw new PdfError("damaged", "a cross reference entry with no kind");
        }
        if (used && offset !== null && offset > 0) {
          this.remember(first + index, { in: "file", at: offset });
        }
      }
      if (lexer.at === before) {
        throw new PdfError("damaged", "a cross reference run consumed nothing");
      }
    }
  }

  private async crossReferenceStream(
    at: number,
    window: Uint8Array,
  ): Promise<PdfDict | null> {
    const header = new Lexer(window);
    header.skip();
    header.token(); // the object number
    header.skip();
    header.token(); // the generation
    header.skip();
    if (!header.take("obj")) return null;
    const dictionary = header.object();
    if (!isDict(dictionary)) return null;

    const data = await this.streamBytes(at, dictionary, header.at, window);
    if (data === null) return dictionary;

    const widths = dictionary.entries.get("W");
    if (
      widths === undefined ||
      typeof widths !== "object" ||
      widths === null ||
      widths.kind !== "array"
    ) {
      return dictionary;
    }
    const w = widths.items.map((item) =>
      typeof item === "number" &&
      Number.isInteger(item) &&
      item >= 0 &&
      item <= 8
        ? item
        : -1,
    );
    if (w.length !== 3 || w.some((width) => width < 0)) return dictionary;
    const record = w[0]! + w[1]! + w[2]!;
    if (record === 0) return dictionary;

    const size = dictionary.entries.get("Size");
    const declared = dictionary.entries.get("Index");
    const index: number[] =
      declared !== undefined &&
      typeof declared === "object" &&
      declared !== null &&
      declared.kind === "array"
        ? declared.items.map((item) => (typeof item === "number" ? item : -1))
        : [0, typeof size === "number" ? size : 0];

    let cursor = 0;
    for (let pair = 0; pair + 1 < index.length; pair += 2) {
      const first = index[pair]!;
      const count = index[pair + 1]!;
      if (!Number.isInteger(first) || !Number.isInteger(count)) break;
      if (first < 0 || count < 0 || count > MAX_XREF_ENTRIES) {
        throw new PdfError("damaged", "a cross reference run of no real size");
      }
      for (let step = 0; step < count; step += 1) {
        if (cursor + record > data.length) break;
        const fields = [0, 0, 0];
        for (let field = 0; field < 3; field += 1) {
          let value = 0;
          for (let byte = 0; byte < w[field]!; byte += 1) {
            // Multiplication rather than a shift: a five byte offset is past
            // what `<<` keeps, and it would wrap to a small number silently.
            value = value * 256 + data[cursor]!;
            cursor += 1;
          }
          fields[field] = value;
        }
        // A zero width first field means the type is 1, which the format says.
        const kind = w[0] === 0 ? 1 : fields[0]!;
        const num = first + step;
        if (kind === 1 && fields[1]! > 0) {
          this.remember(num, { in: "file", at: fields[1]! });
        } else if (kind === 2) {
          this.remember(num, {
            in: "stream",
            stream: fields[1]!,
            index: fields[2]!,
          });
        }
      }
    }
    return dictionary;
  }

  private remember(num: number, entry: Entry): void {
    if (this.xref.has(num)) return;
    if (this.xref.size >= MAX_XREF_ENTRIES) {
      throw new PdfError("damaged", "more objects than anything real declares");
    }
    this.xref.set(num, entry);
  }

  /**
   * A stream's bytes, decoded, or `null` when this reader does not do its
   * filter.
   *
   * `null` rather than a throw for an unknown filter, because a `/Metadata`
   * stream this cannot open is a field that is absent and not a broken file.
   */
  private async streamBytes(
    at: number,
    dictionary: PdfDict,
    after: number,
    window: Uint8Array,
  ): Promise<Uint8Array | null> {
    const lexer = new Lexer(window, after);
    lexer.skip();
    if (!lexer.take("stream")) return null;
    // The keyword is followed by CRLF or LF, and by nothing else.
    if (lexer.take("\r\n")) {
      /* consumed */
    } else if (!lexer.take("\n")) {
      throw new PdfError("damaged", "a stream keyword with no line break");
    }
    const from = at + lexer.at;

    const length = await this.resolve(dictionary.entries.get("Length"));
    let raw: Uint8Array;
    if (
      typeof length === "number" &&
      Number.isInteger(length) &&
      length >= 0 &&
      length <= MAX_STREAM_BYTES &&
      from + length <= this.source.size
    ) {
      raw =
        from + length <= at + window.length
          ? window.subarray(lexer.at, lexer.at + length)
          : await this.source.read(from, length);
    } else {
      // **A declared length that is absent, a reference this reader has not
      // resolved yet, or a lie is not fatal**: the format's own recovery is to
      // read to `endstream`. **0 of the 123 reach it**, so this arm has a test
      // behind it and no file; what it stops is a wrong `/Length` costing the
      // whole document rather than one stream.
      const search = await this.source.read(from, MAX_STREAM_BYTES);
      const end = indexOfAscii(search, "endstream");
      if (end < 0) throw new PdfError("damaged", "a stream with no end");
      raw = search.subarray(0, end);
    }

    const filter = dictionary.entries.get("Filter");
    const names: string[] = [];
    if (typeof filter === "object" && filter !== null) {
      if (filter.kind === "name") names.push(filter.value);
      if (filter.kind === "array") {
        for (const item of filter.items) {
          if (
            typeof item === "object" &&
            item !== null &&
            item.kind === "name"
          ) {
            names.push(item.value);
          }
        }
      }
    }
    if (names.length === 0) return raw;
    // One filter only. A chain means a stream that has been encoded twice,
    // which no metadata stream in the corpus is, and applying the first of two
    // would hand back bytes that look like data and are not.
    if (names.length > 1 || names[0] !== "FlateDecode") return null;

    const inflated = await inflate(raw);
    let parms = await this.resolve(dictionary.entries.get("DecodeParms"));
    if (typeof parms === "object" && parms !== null && parms.kind === "array") {
      parms = parms.items[0] ?? null;
    }
    if (!isDict(parms)) return inflated;
    const predictor = await this.resolve(parms.entries.get("Predictor"));
    if (typeof predictor !== "number" || predictor < 10) return inflated;
    const columns = await this.resolve(parms.entries.get("Columns"));
    return unpredict(inflated, typeof columns === "number" ? columns : 1);
  }

  /**
   * Follow a reference to a value.
   *
   * **A visited set and a step count**, and both are needed: the count bounds a
   * chain that grows, and the set refuses a cycle at its second step rather
   * than walking it sixteen times. A file can write `1 0 obj 2 0 R` and
   * `2 0 obj 1 0 R`, and every field this reader reads goes through here.
   */
  async resolve(value: PdfValue | undefined): Promise<PdfValue> {
    if (value === undefined) return null;
    const seen = new Set<number>();
    let current = value;
    for (let step = 0; step < MAX_RESOLVE_STEPS; step += 1) {
      if (!isRef(current)) return current;
      if (seen.has(current.num)) return null;
      seen.add(current.num);
      current = await this.object(current.num);
    }
    return null;
  }

  private async object(num: number): Promise<PdfValue> {
    const entry = this.xref.get(num);
    if (entry === undefined) return null;
    if (entry.in === "stream") {
      const contents = await this.objectStream(entry.stream);
      return contents?.get(num) ?? null;
    }
    const window = await this.source.read(entry.at, OBJECT_WINDOW_BYTES);
    if (window.length === 0) return null;
    const lexer = new Lexer(window);
    lexer.skip();
    const declared = Number(lexer.token());
    lexer.skip();
    lexer.token();
    lexer.skip();
    if (!lexer.take("obj")) return null;
    // **The object at the offset has to be the object asked for.** A table that
    // points at the wrong place is how an incremental update goes wrong, and
    // taking whatever is there would put another book's title on this one.
    if (declared !== num) return null;
    return lexer.object();
  }

  /**
   * The objects inside one object stream.
   *
   * **An object stream is looked for in the file and never inside another
   * one**, which the format forbids and which is also what makes this
   * terminate: `object` calls this, and this calls nothing that calls back.
   */
  private async objectStream(
    num: number,
  ): Promise<ReadonlyMap<number, PdfValue> | null> {
    const known = this.streams.get(num);
    if (known !== undefined) return known;

    const entry = this.xref.get(num);
    if (entry === undefined || entry.in !== "file") return null;

    // **Registered before a byte of it is read, and that is what terminates.**
    // `/Length` may be an indirect reference to an object inside this very
    // stream, so resolving it re-enters here; with the cache set afterwards a
    // 349 byte file drove 98,690 reads in 3.7 seconds before the total fetch
    // budget stopped it. A member's picked folder is read one file after
    // another on the page's thread, so seconds per file is the cost.
    const contents = new Map<number, PdfValue>();
    this.streams.set(num, contents);

    const window = await this.source.read(entry.at, OBJECT_WINDOW_BYTES);
    const header = new Lexer(window);
    header.skip();
    header.token();
    header.skip();
    header.token();
    header.skip();
    if (!header.take("obj")) return contents;
    const dictionary = header.object();
    if (!isDict(dictionary)) return contents;

    const data = await this.streamBytes(
      entry.at,
      dictionary,
      header.at,
      window,
    );
    if (data === null) return contents;

    const count = await this.resolve(dictionary.entries.get("N"));
    const first = await this.resolve(dictionary.entries.get("First"));
    if (typeof count !== "number" || typeof first !== "number") return contents;
    if (count < 0 || count > MAX_OBJSTM_OBJECTS || first < 0) {
      throw new PdfError("damaged", "an object stream of no real size");
    }

    const pairs = new Lexer(data);
    for (let index = 0; index < count; index += 1) {
      pairs.skip();
      // Empty checked before `Number`, for the reason `classicTable` states.
      // Bounded by `MAX_OBJSTM_OBJECTS` rather than unbounded here, so this one
      // was a wrong answer rather than a hang; it is the same defect.
      const number = numeric(pairs);
      pairs.skip();
      const offset = numeric(pairs);
      if (number === null || offset === null) break;
      if (first + offset >= data.length) break;
      try {
        contents.set(number, new Lexer(data, first + offset).object());
      } catch {
        // One unreadable member does not cost the rest of the stream. The
        // failure this refuses is a whole file reporting `damaged` because an
        // object nobody asked for is malformed.
      }
    }
    return contents;
  }

  async trailerValue(key: string): Promise<PdfValue> {
    return await this.resolve(this.trailer.get(key));
  }

  /**
   * The catalogue's `/Metadata` stream, decoded, or `null`.
   *
   * **Reached through the cross reference and not by scanning for
   * `<?xpacket`.** The markers are findable in 94 of the 123 by reading the
   * whole file, and the first of them is not always the document's own: an
   * embedded image carries a packet too, and taking it would describe the
   * photograph rather than the book.
   */
  async metadataBytes(root: PdfDict): Promise<Uint8Array | null> {
    const reference = root.entries.get("Metadata") ?? null;
    if (!isRef(reference)) return null;
    const entry = this.xref.get(reference.num);
    // In an object stream it cannot be a stream, which is what a `/Metadata`
    // has to be, so there is nothing here to read.
    if (entry === undefined || entry.in !== "file") return null;
    const window = await this.source.read(entry.at, OBJECT_WINDOW_BYTES);
    const lexer = new Lexer(window);
    lexer.skip();
    const declared = Number(lexer.token());
    lexer.skip();
    lexer.token();
    lexer.skip();
    if (!lexer.take("obj") || declared !== reference.num) return null;
    const dictionary = lexer.object();
    if (!isDict(dictionary)) return null;
    return await this.streamBytes(entry.at, dictionary, lexer.at, window);
  }

  /**
   * Whether the document is encrypted.
   *
   * **The key resolving to a dictionary, not the key being present.** Measured:
   * 1 of the 123 carries `/Encrypt null` in its trailer, a reference left
   * behind by a revision that removed the encryption, and its strings are
   * plaintext. pypdf 6.10.2 does not make this distinction and fails that file
   * with an unhandled `AttributeError`; refusing on the key alone would lose
   * its title and author, which are both correct.
   */
  async encrypted(): Promise<boolean> {
    return isDict(await this.trailerValue("Encrypt"));
  }
}

/** The last `startxref` in a buffer, as an offset into the file. */
function lastStartxref(tail: Uint8Array, base: number): number | null {
  const at = lastIndexOfAscii(tail, "startxref");
  if (at < 0) return null;
  const lexer = new Lexer(tail, at + "startxref".length);
  lexer.skip();
  const offset = Number(lexer.token());
  if (!Number.isInteger(offset) || offset < 0) return null;
  // The offset is absolute in the file, so it is only usable when the whole
  // file was searched or the offset lands before the window that was.
  return offset < base + tail.length ? offset : null;
}

function indexOfAscii(haystack: Uint8Array, needle: string): number {
  outer: for (let at = 0; at + needle.length <= haystack.length; at += 1) {
    for (let index = 0; index < needle.length; index += 1) {
      if (haystack[at + index] !== needle.charCodeAt(index)) continue outer;
    }
    return at;
  }
  return -1;
}

function lastIndexOfAscii(haystack: Uint8Array, needle: string): number {
  outer: for (let at = haystack.length - needle.length; at >= 0; at -= 1) {
    for (let index = 0; index < needle.length; index += 1) {
      if (haystack[at + index] !== needle.charCodeAt(index)) continue outer;
    }
    return at;
  }
  return -1;
}

// --- the XMP packet ---------------------------------------------------------

/**
 * What an XMP packet adds over the information dictionary.
 *
 * **Measured, and it is not the title.** Across the 123 the packet adds 0
 * titles and 1 author to what the dictionary already carries, so it is not read
 * for either. What it is read for is **publisher in 14, language in 13, a date
 * in 14 and an identifier in 3**, and the dictionary has no field at all for
 * the publisher, the language or the identifier.
 *
 * **The date is the one where it does, and `/CreationDate` is still not read.**
 * 112 of the 123 carry one with a plausible year, which looks like a large
 * gain. It is the date the *file* was made: where a file carries both, the two
 * years disagree in 5 of the 13, and a scan of a 1960s book made in 2015 would
 * be filed under 2015. A publication year this reader cannot supply is one the
 * catalogue lookup answers.
 */
interface XmpRecord {
  readonly title: string | null;
  readonly creators: readonly string[];
  readonly identifiers: readonly string[];
  readonly publisher: string | null;
  readonly language: string | null;
  readonly date: string | null;
  readonly description: string | null;
}

/**
 * Where the RDF starts and ends, as a substring of the packet.
 *
 * **This is the whole of the entity guard, and it is structural rather than a
 * scan for `<!ENTITY`.** A document type declaration is only legal in the
 * prolog, before the root element; cutting the packet down to its root element
 * leaves no prolog for one to be in, so the parser is handed a document that
 * *cannot* declare an entity rather than one that was checked for not doing so.
 * An entity reference with no declaration is then a well formedness error, and
 * a malformed document is `null` here. `lib/opf.ts` states the same rule for a
 * package document, which arrives as a whole file and so has to scan instead.
 */
const RDF_OPEN = /<([A-Za-z_][\w.-]*:)?RDF[\s>]/;

function readXmp(packet: string): XmpRecord | null {
  const open = RDF_OPEN.exec(packet);
  if (open === null) return null;
  const prefix = open[1] ?? "";
  const closing = `</${prefix}RDF>`;
  const end = packet.lastIndexOf(closing);
  if (end < open.index) return null;
  const xml = packet.slice(open.index, end + closing.length);

  const document = new DOMParser().parseFromString(xml, "application/xml");
  const root = document.documentElement;
  if (!root || root.localName !== "RDF") return null;

  /** Every value under the first `dc:` element of this name, in order. */
  function values(local: string): string[] {
    const found = root!.getElementsByTagNameNS(
      "http://purl.org/dc/elements/1.1/",
      local,
    );
    const element = found[0];
    if (element === undefined) return [];
    const items = element.getElementsByTagNameNS(
      "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
      "li",
    );
    const raw =
      items.length > 0
        ? Array.from(items, (item) => item.textContent ?? "")
        : [element.textContent ?? ""];
    return raw
      .map((value) => clean(value))
      .filter((value): value is string => value !== null);
  }

  const [publisher] = values("publisher");
  const [language] = values("language");
  const [date] = values("date");
  const [description] = values("description");
  const [title] = values("title");
  return {
    title: title ?? null,
    creators: values("creator"),
    identifiers: values("identifier"),
    publisher: publisher ?? null,
    language: language ?? null,
    date: date ?? null,
    description: description ?? null,
  };
}

// --- the fields -------------------------------------------------------------

/**
 * The four digits of a date, when they are a plausible year.
 *
 * One candidate and not a list: the XMP date is the only thing here that is a
 * publication date. `XmpRecord` says why `/CreationDate` is not a second one.
 */
function readYear(candidate: string | null): number | null {
  const match = candidate === null ? null : /(\d{4})/.exec(candidate);
  if (match === null) return null;
  const year = Number(match[1]);
  const [low, high] = YEAR_RANGE;
  return year >= low && year <= high ? year : null;
}

/**
 * The identifiers, from XMP's `dc:identifier` alone.
 *
 * **The information dictionary has no identifier field**, so there is nothing
 * to fall back to and nothing to sniff: `/Subject` and `/Keywords` are prose.
 * Measured 3 of 123, and 2 of those 3 are DOIs rather than ISBNs, which is why
 * `parseIsbn` decides which of them is an ISBN rather than the field's name.
 */
function readIdentifiers(xmp: XmpRecord | null): OpfIdentifier[] {
  if (xmp === null) return [];
  return xmp.identifiers.map((value) => ({
    scheme: parseIsbn(value) === null ? null : "ISBN",
    value,
  }));
}

/**
 * The authors, separately and in the order the file gave them.
 *
 * The dictionary's `/Author` wins when it carries a name, and XMP's
 * `dc:creator` is a sequence, so **every one of its entries is kept**.
 *
 * **Nothing in the corpus exercises that**, which is worth stating rather than
 * implying: 5 of the 123 carry more than one `dc:creator`, one of them five,
 * and every one of those 5 also carries an `/Author`, so the list is never
 * reached. The 1 file that reaches it names `Zamzar`, a file conversion
 * service. Keeping the whole sequence is right because the format says it is a
 * list, not because a file here proves it.
 *
 * **Never split on a separator.** The dictionary's `/Author` is one string and
 * a producer may have put several names in it: this corpus carries
 * `Foster Provost and Tom Fawcett`, `Bengfort, Benjamin; Bilbro, Rebecca` and
 * `Peter Bruce;Andrew Bruce;Peter Gedeck;` in the same field, on three
 * different separators, and one of those separators is also how a single name
 * is written surname first. Splitting would file `Bruce, Peter` as two people.
 * XMP's `dc:creator` is already a sequence of separate names, so nothing has
 * to be split there either.
 */
function readAuthors(author: string | null, xmp: XmpRecord | null): string[] {
  const kept = usableAuthor(author);
  if (kept !== null) return [kept];
  return (xmp?.creators ?? [])
    .map((value) => usableAuthor(clean(value)))
    .filter((value): value is string => value !== null);
}

// --- the reader -------------------------------------------------------------

/**
 * Read one PDF's metadata.
 *
 * Never throws for anything the file did, for the reason `readEpub` states: a
 * picked file that is not what it claimed is one entry's failure, which is what
 * lets a member point at a folder and get a queue rather than an error page.
 * **A file that carries nothing is `ok` with a record of nulls**, which is the
 * ordinary outcome for this format and is what hands it to the filename path.
 */
export async function readPdf(file: Blob): Promise<PdfReading> {
  try {
    const source = new Source(file);
    const head = await source.read(0, 8);
    // **The header is checked before anything else is believed**, so a file of
    // another kind that a member picked is refused before an offset inside it
    // has been read. `%PDF-` and not `%PDF-1.`, because PDF 2.0 exists.
    if (indexOfAscii(head, "%PDF-") !== 0) {
      return { ok: false, failure: "not-a-pdf" };
    }

    const document = new Document(source);
    await document.load();

    // **Before any string is decoded.** Under encryption every string in the
    // file is ciphertext, and decoding one would put noise in front of a member
    // as though it were a title.
    if (await document.encrypted()) {
      return { ok: false, failure: "protected" };
    }

    const info = await document.trailerValue("Info");
    const dictionary = isDict(info) ? info : null;
    async function field(name: string): Promise<string | null> {
      const value = await document.resolve(dictionary?.entries.get(name));
      if (typeof value !== "object" || value === null) return null;
      if (value.kind !== "string") return null;
      return clean(decodeText(value.value));
    }

    // The packet's bytes come back through the same path every other stream
    // takes, so its bound is `MAX_INFLATED_BYTES` and not a second one here.
    const root = await document.trailerValue("Root");
    const packet = isDict(root) ? await document.metadataBytes(root) : null;
    const xmp = packet === null ? null : readXmp(utf8.decode(packet));

    const title =
      usableTitle(await field("Title")) ?? usableTitle(xmp?.title ?? null);
    const description = (await field("Subject")) ?? xmp?.description ?? null;

    return {
      ok: true,
      metadata: {
        // A PDF has no package document, so there is no version to name. Not
        // the `%PDF-1.7` header, which is a different fact under one word.
        version: null,
        title,
        // No field in either block means a subtitle, and no separator in a
        // title is reliably one: `Practical Guide to: Oracle SQL` is a whole
        // title with a colon in it.
        subtitle: null,
        authors: readAuthors(await field("Author"), xmp),
        identifiers: readIdentifiers(xmp),
        isbn: firstIsbn(xmp),
        publisher: xmp?.publisher ?? null,
        year: readYear(xmp?.date ?? null),
        language: xmp?.language ?? null,
        description,
        // Neither block has a field for either, so these are absent by the
        // format rather than unread here. A book whose series matters arrives
        // from the catalogue lookup or from the member.
        seriesName: null,
        seriesIndex: null,
      },
    };
  } catch (error) {
    // **Only this class**, so a defect in the reader stays a defect: the scan
    // page catches anything else and still reaches the filename path, and a
    // blanket catch here would make a bug indistinguishable from a bad file.
    if (error instanceof PdfError) {
      return { ok: false, failure: error.failure };
    }
    throw error;
  }
}

function firstIsbn(xmp: XmpRecord | null): string | null {
  for (const value of xmp?.identifiers ?? []) {
    const isbn = parseIsbn(value);
    if (isbn !== null) return isbn;
  }
  return null;
}
