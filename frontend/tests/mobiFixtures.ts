/**
 * Building Palm Databases and MOBI headers byte by byte, for the tests that
 * read them.
 *
 * Support code, so it mirrors nothing: the mirrored files are the `*.test.ts`
 * ones. A builder rather than a checked in binary for the reason
 * `zipFixtures.ts` gives, and one more that is specific to this format: half of
 * what is worth testing is a header whose declared offsets disagree with the
 * bytes behind them, and a disagreement is easier to describe than to keep as
 * bytes nobody can read in a diff.
 *
 * **These fixtures were checked against real files rather than against the
 * specification.** A well formed `mobiBytes()` has the same field at the same
 * offset as the 69 files `src/lib/mobi.ts` names, which is the step a hand
 * written fixture cannot take on its own: a fixture written from the same
 * reading as the parser agrees with the parser whether or not either is right.
 * The numbers that were checked, and against how many files, are in that
 * module's own docstring; nothing here restates them.
 *
 * **Every override exists for one test.** A field a real writer would never get
 * wrong is exactly what a hostile file gets wrong on purpose.
 */

/** The fixed Palm Database header. */
const PDB_HEADER_BYTES = 78;
const PDB_ENTRY_BYTES = 8;

/**
 * The gap real files leave between the offset table and the first record.
 *
 * The size and the measurement behind it are `recordZeroExtent`'s in
 * `src/lib/mobi.ts`. Written here because a fixture that differs from every
 * real file in a way nobody noticed is a fixture that stops being evidence.
 */
const TABLE_GAP_BYTES = 2;

/**
 * The MOBI header length the fixture writes.
 *
 * Two lengths cover 66 of 69 real files: 264 in 36 and 232 in 30. The shorter
 * is taken, so every offset the reader uses is exercised at the tighter of the
 * two and a fixture cannot pass on room a real file would not have.
 */
const DEFAULT_HEADER_LENGTH = 232;

const UTF8 = 65001;

const encoder = new TextEncoder();

export function bytes(value: string): Uint8Array<ArrayBuffer> {
  return encoder.encode(value);
}

/** One EXTH record, with every part of it overridable. */
export interface ExthSpec {
  type: number;
  /** The value's bytes. A string is encoded as UTF-8. */
  value?: Uint8Array | string;
  /**
   * The length this record claims, which a real one spends on its own header
   * plus its value. Overridden to walk the reader off the end, or nowhere.
   */
  declaredLength?: number;
}

export interface MobiSpec {
  /** The eight bytes at offset 60. `BOOKMOBI` for a MOBI. */
  typeAndCreator?: string;
  /** What the header says the record count is, rather than what it is. */
  declaredRecords?: number;
  /** Where record 0 begins, rather than after the table. */
  recordZeroAt?: number;
  /** Where record 1 begins, which is where record 0 ends. */
  recordOneAt?: number;
  /** How many records the table actually holds. */
  records?: number;
  /** The PalmDOC encryption field. 0 is none, anything else is DRM. */
  encryption?: number;
  /** The four bytes at offset 16 of record 0. */
  magic?: string;
  /** How many bytes the MOBI header actually occupies. */
  headerLength?: number;
  /**
   * The length the MOBI header claims, rather than the bytes it occupies.
   *
   * Separate from `headerLength` because the EXTH block begins after the
   * claimed length: a fixture pointing it into the void must not have to
   * allocate the void to say so.
   */
  declaredHeaderLength?: number;
  codepage?: number;
  /** The title in the header, which is not the same field as EXTH 503. */
  fullName?: Uint8Array | string;
  /** Where the header says the full name is, rather than where it is. */
  fullNameAt?: number;
  /** How long the header says the full name is. */
  fullNameLength?: number;
  /** The EXTH records, or `null` for a file that carries no EXTH block. */
  exth?: ExthSpec[] | null;
  exthMagic?: string;
  /** The length the block claims, rather than what it spends. */
  exthDeclaredLength?: number;
  /** The record count the block claims, rather than how many it holds. */
  exthDeclaredCount?: number;
  /**
   * The EXTH flag word at record 0 offset 0x80.
   *
   * Real files set bit 0x40 to announce the block. The reader does not read it,
   * and this override is how that is shown rather than asserted: a fixture that
   * always set it could not tell a reader that ignores the flag from one that
   * requires it.
   */
  exthFlag?: number;
  /** Bytes after record 0, which is what makes record 1 exist. */
  trailingBytes?: number;
}

function asBytes(value: Uint8Array | string): Uint8Array {
  return typeof value === "string" ? bytes(value) : value;
}

/** The EXTH block, exactly as it sits inside record 0. */
function exthBlock(spec: MobiSpec): Uint8Array<ArrayBuffer> {
  const records = spec.exth;
  if (records === null || records === undefined) return new Uint8Array(0);

  const parts = records.map((record) => {
    const value = asBytes(record.value ?? "");
    const length = record.declaredLength ?? 8 + value.length;
    const out = new Uint8Array(8 + value.length);
    const view = new DataView(out.buffer);
    view.setUint32(0, record.type);
    view.setUint32(4, length);
    out.set(value, 8);
    return out;
  });

  const spent = parts.reduce((total, part) => total + part.length, 0);
  // Real writers pad the block to a four byte boundary and count the padding
  // in the declared length. The count is in `readExth`'s docstring.
  const padding = (4 - ((12 + spent) % 4)) % 4;
  const block = new Uint8Array(12 + spent + padding);
  const view = new DataView(block.buffer);
  block.set(bytes(spec.exthMagic ?? "EXTH"), 0);
  view.setUint32(4, spec.exthDeclaredLength ?? block.length);
  view.setUint32(8, spec.exthDeclaredCount ?? parts.length);

  let at = 12;
  for (const part of parts) {
    block.set(part, at);
    at += part.length;
  }
  return block;
}

/** Record 0: the PalmDOC header, the MOBI header, the EXTH block, the title. */
function recordZero(spec: MobiSpec): Uint8Array<ArrayBuffer> {
  const headerLength = spec.headerLength ?? DEFAULT_HEADER_LENGTH;
  const exth = exthBlock(spec);
  const fullName = asBytes(spec.fullName ?? "");
  const fullNameAt = 16 + headerLength + exth.length;

  const record = new Uint8Array(fullNameAt + fullName.length);
  const view = new DataView(record.buffer);

  // The PalmDOC header. Compression 2 and a 4096 byte record are what every
  // real file measured declares; nothing in the reader looks at either.
  view.setUint16(0, 2);
  view.setUint32(4, 0);
  view.setUint16(8, 1);
  view.setUint16(10, 4096);
  view.setUint16(12, spec.encryption ?? 0);

  record.set(bytes(spec.magic ?? "MOBI"), 16);
  view.setUint32(20, spec.declaredHeaderLength ?? headerLength);
  view.setUint32(24, 2);
  view.setUint32(28, spec.codepage ?? UTF8);
  view.setUint32(36, 6);
  // A header short enough to leave these off the end is itself a fixture, so
  // the writes are guarded rather than assumed to fit.
  if (record.length >= 0x5c) {
    view.setUint32(0x54, spec.fullNameAt ?? fullNameAt);
    view.setUint32(0x58, spec.fullNameLength ?? fullName.length);
  }
  // Set the way a real file sets it, so the well formed fixture is well formed.
  // `exthFlag` is what a test uses to clear it.
  if (record.length >= 0x84) view.setUint32(0x80, spec.exthFlag ?? 0x50);

  record.set(exth, 16 + headerLength);
  record.set(fullName, fullNameAt);
  return record;
}

/** A whole file, well formed unless the spec says otherwise. */
export function mobiBytes(spec: MobiSpec = {}): Uint8Array<ArrayBuffer> {
  const record = recordZero(spec);
  const records = spec.records ?? 2;
  const tableBytes = records * PDB_ENTRY_BYTES;
  const start = PDB_HEADER_BYTES + tableBytes + TABLE_GAP_BYTES;
  const trailing = spec.trailingBytes ?? 8;

  const file = new Uint8Array(start + record.length + trailing);
  const view = new DataView(file.buffer);

  file.set(bytes("Fixture"), 0);
  file.set(bytes(spec.typeAndCreator ?? "BOOKMOBI"), 60);
  view.setUint16(76, spec.declaredRecords ?? records);

  view.setUint32(PDB_HEADER_BYTES, spec.recordZeroAt ?? start);
  if (records > 1) {
    view.setUint32(
      PDB_HEADER_BYTES + PDB_ENTRY_BYTES,
      spec.recordOneAt ?? start + record.length,
    );
  }
  for (let index = 2; index < records; index += 1) {
    view.setUint32(
      PDB_HEADER_BYTES + index * PDB_ENTRY_BYTES,
      start + record.length,
    );
  }

  file.set(record, start);
  return file;
}

/** A Palm Database of some other format, which the reader has to refuse. */
export function palmDatabase(typeAndCreator: string): Uint8Array<ArrayBuffer> {
  return mobiBytes({
    typeAndCreator,
    exth: [{ type: 503, value: "Not this" }],
  });
}
