/**
 * PDFs built byte by byte, for tests of `src/lib/pdf.ts`.
 *
 * **Assembled rather than captured**, for the reason `mobiFixtures.ts` gives:
 * a file a writer produced agrees with that writer's reader, and what this
 * module is for is the files no writer produces. The offsets in the cross
 * reference are computed from where the objects actually land, so a fixture
 * cannot drift out of agreement with itself; every test that wants a wrong
 * offset asks for one.
 *
 * **Both cross reference shapes are here because the corpus has both**: of the
 * household's 123 PDFs, 71 have a cross reference stream at `startxref` and 52
 * a classic table, and 3 of those 52 also carry a stream further back in the
 * `/Prev` chain, so 74 carry one somewhere. A reader tested against only one
 * shape misses at least 42% of the field.
 */

/**
 * A string as bytes, one byte per character.
 *
 * Not `TextEncoder`, which is UTF-8: a PDF body is bytes, and a fixture that
 * wants `\x92` in a string means that byte and not two of them.
 */
export function latin(text: string): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index += 1) {
    out[index] = text.charCodeAt(index) & 0xff;
  }
  return out;
}

/**
 * The inverse of `latin`, one character per byte.
 *
 * **Not a `TextDecoder`.** The Encoding Standard makes `latin1` an alias for
 * windows-1252, so 27 of the 256 byte values do not survive a round trip
 * through it, and every one of those is a byte a deflate stream contains.
 * Measured under bun 1.4.2: a 361 byte fixture lost 5 bytes and the reader
 * then answered `damaged` where the test expected a title. node round trips
 * the same call clean, so which runtime runs vitest decided whether the test
 * tested what it claimed.
 */
export function text(bytes: Uint8Array): string {
  let out = "";
  for (const byte of bytes) out += String.fromCharCode(byte);
  return out;
}

export function concat(
  ...parts: (Uint8Array | string)[]
): Uint8Array<ArrayBuffer> {
  const bytes = parts.map((part) =>
    typeof part === "string" ? latin(part) : part,
  );
  const total = bytes.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of bytes) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

/** Deflate, with the zlib header a PDF `FlateDecode` stream carries. */
export async function deflate(
  raw: Uint8Array,
): Promise<Uint8Array<ArrayBuffer>> {
  const copy = new Uint8Array(raw);
  const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(copy);
      controller.close();
    },
  });
  const reader = source
    .pipeThrough<Uint8Array<ArrayBuffer>>(new CompressionStream("deflate"))
    .getReader();
  const chunks: Uint8Array[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done || value === undefined) break;
    chunks.push(value);
  }
  return concat(...chunks);
}

/** One numbered object, as the bytes between `N 0 obj` and `endobj`. */
export interface PdfObject {
  readonly num: number;
  readonly body: Uint8Array | string;
}

export function object(num: number, body: Uint8Array | string): PdfObject {
  return { num, body };
}

/** A stream object: its dictionary, then its bytes. */
export function streamObject(
  num: number,
  dictionary: string,
  data: Uint8Array,
): PdfObject {
  const head = dictionary.replace(
    />>\s*$/,
    ` /Length ${data.length} >>\nstream\n`,
  );
  return { num, body: concat(head, data, "\nendstream") };
}

interface Assembled {
  readonly bytes: Uint8Array<ArrayBuffer>;
  readonly offsets: ReadonlyMap<number, number>;
}

function assemble(
  objects: readonly PdfObject[],
  header: Uint8Array | string,
): Assembled {
  const parts: (Uint8Array | string)[] = [header];
  const offsets = new Map<number, number>();
  let at = typeof header === "string" ? latin(header).length : header.length;
  for (const item of objects) {
    offsets.set(item.num, at);
    const chunk = concat(`${item.num} 0 obj\n`, item.body, "\nendobj\n");
    parts.push(chunk);
    at += chunk.length;
  }
  return { bytes: concat(...parts), offsets };
}

/**
 * A PDF whose cross reference is a classic table.
 *
 * The trailer is written from `trailer`, which is a dictionary body without its
 * `<<` and `>>`, so a test can put anything in it including something wrong.
 */
export function classicPdf(
  objects: readonly PdfObject[],
  trailer: string,
  options: {
    readonly header?: string;
    readonly startxref?: number;
    /**
     * Bytes to sit in front, which is how an incremental update is written: the
     * whole earlier file, then this one's objects and its own table.
     *
     * **Bytes and never a string.** Round tripping a PDF through
     * `TextDecoder("latin1")` corrupts it: the Encoding Standard makes `latin1`
     * an alias for windows-1252, so bytes 0x80 to 0x9F come back as typographic
     * characters and re-encode to something else. A deflate stream carries
     * those bytes, so the file that came back would not inflate.
     */
    readonly prefix?: Uint8Array;
  } = {},
): Uint8Array<ArrayBuffer> {
  const header = options.prefix ?? options.header ?? "%PDF-1.4\n";
  const { bytes, offsets } = assemble(objects, header);
  const highest = Math.max(0, ...offsets.keys());
  let table = `xref\n0 ${highest + 1}\n0000000000 65535 f \n`;
  for (let num = 1; num <= highest; num += 1) {
    const offset = offsets.get(num);
    table +=
      offset === undefined
        ? "0000000000 65535 f \n"
        : `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  const tableAt = bytes.length;
  return concat(
    bytes,
    table,
    `trailer\n<< /Size ${highest + 1} ${trailer} >>\nstartxref\n${options.startxref ?? tableAt}\n%%EOF\n`,
  );
}

/** Where a packed object ended up: which object stream, and at which index. */
interface Packing {
  readonly stream: number;
  readonly index: number;
}

/**
 * A PDF whose cross reference is a stream, optionally under a PNG predictor.
 *
 * The object streams and then the cross reference stream number themselves past
 * the highest given object, which is what a real writer does, and the cross
 * reference is written last so its own offset is known.
 */
export async function streamPdf(
  objects: readonly PdfObject[],
  trailer: string,
  options: {
    readonly predictor?: boolean;
    /**
     * Which objects live in object streams, **one object stream per group**.
     *
     * A group rather than a flat list, because the number of streams is a fact
     * a test needs to choose: what one of them costs is bounded per stream, so
     * how many of them there are is the other half of what a file can spend.
     */
    readonly packed?: readonly (readonly number[])[];
    /**
     * Pad every object stream so it inflates to exactly this many bytes.
     *
     * Zeroes, appended after the objects, which is where nothing reads: an
     * object stream is addressed by the offsets in its own header, so a tail it
     * never points at changes what the stream costs to open and nothing else.
     * They deflate to roughly a thousandth of their size, so this is how a
     * fixture asks for a large inflate out of a small file.
     */
    readonly inflateTo?: number;
    /**
     * The pairs header to write, as `[object number, offset]` rows, instead of
     * the one derived from where the bodies land.
     *
     * **A file writes that header, so a test has to be able to write a wrong
     * one.** Nothing in the format requires two rows to name different offsets,
     * and a header naming one offset `/N` times is how an object stream costs
     * `/N` parses for the one inflation it is charged. One group only, since it
     * describes one stream.
     */
    readonly packedHeader?: readonly (readonly [number, number])[];
    readonly header?: string;
    /**
     * What to write as the object stream's `/Length`, instead of its size.
     *
     * For the one shape a length has to be able to take: a reference to an
     * object that lives inside the very stream whose length it is. One group
     * only, since it names one stream.
     */
    readonly objStmLength?: string;
  } = {},
): Promise<Uint8Array<ArrayBuffer>> {
  const header = options.header ?? "%PDF-1.5\n";
  const groups = options.packed ?? [];
  if (options.objStmLength !== undefined && groups.length !== 1) {
    throw new Error("objStmLength names one object stream, so pass one group");
  }
  if (options.packedHeader !== undefined && groups.length !== 1) {
    throw new Error("packedHeader describes one object stream, so pass one");
  }
  const inStream = new Set(groups.flat());
  const all: PdfObject[] = objects.filter((item) => !inStream.has(item.num));
  const highest = Math.max(0, ...objects.map((item) => item.num));

  const inside = new Map<number, Packing>();
  let next = highest + 1;
  for (const group of groups) {
    const packed = objects.filter((item) => group.includes(item.num));
    if (packed.length === 0) continue;
    const objStmNum = next;
    next += 1;
    let bodies: Uint8Array<ArrayBuffer> = new Uint8Array();
    const derived: [number, number][] = [];
    for (const item of packed) {
      derived.push([item.num, bodies.length]);
      bodies = concat(bodies, item.body, " ");
    }
    const pairRows = options.packedHeader ?? derived;
    const pairs = pairRows.map(([num, at]) => `${num} ${at} `).join("");
    const first = latin(pairs).length;
    let payload = concat(pairs, bodies);
    if (options.inflateTo !== undefined) {
      if (payload.length > options.inflateTo) {
        throw new Error("inflateTo is under what the objects themselves take");
      }
      payload = concat(
        payload,
        new Uint8Array(options.inflateTo - payload.length),
      );
    }
    const packedBytes = await deflate(payload);
    all.push(
      options.objStmLength === undefined
        ? streamObject(
            objStmNum,
            `<< /Type /ObjStm /N ${pairRows.length} /First ${first} /Filter /FlateDecode >>`,
            packedBytes,
          )
        : object(
            objStmNum,
            concat(
              `<< /Type /ObjStm /N ${pairRows.length} /First ${first}` +
                ` /Filter /FlateDecode /Length ${options.objStmLength} >>\nstream\n`,
              packedBytes,
              "\nendstream",
            ),
          ),
    );
    packed.forEach((item, index) =>
      inside.set(item.num, { stream: objStmNum, index }),
    );
  }
  const xrefNum = next;

  const { bytes, offsets } = assemble(all, header);
  const xrefAt = bytes.length;

  const rows: number[][] = [[0, 0, 65535]];
  for (let num = 1; num <= xrefNum; num += 1) {
    const packing = inside.get(num);
    if (num === xrefNum) rows.push([1, xrefAt, 0]);
    else if (packing !== undefined)
      rows.push([2, packing.stream, packing.index]);
    else if (offsets.has(num)) rows.push([1, offsets.get(num)!, 0]);
    else rows.push([0, 0, 0]);
  }

  const width = [1, 4, 2];
  const columns = width[0]! + width[1]! + width[2]!;
  const flat = new Uint8Array(
    rows.length * (columns + (options.predictor === false ? 0 : 1)),
  );
  let at = 0;
  for (const row of rows) {
    // Filter 0, which is "this row is literal": the reader has to undo the
    // predictor either way, and a row filter it never sees is one it could get
    // wrong without a test noticing.
    if (options.predictor !== false) {
      flat[at] = 0;
      at += 1;
    }
    for (let field = 0; field < 3; field += 1) {
      for (let byte = width[field]! - 1; byte >= 0; byte -= 1) {
        flat[at] = (row[field]! / 256 ** byte) & 0xff;
        at += 1;
      }
    }
  }

  const parms =
    options.predictor === false
      ? ""
      : ` /DecodeParms << /Predictor 12 /Columns ${columns} >>`;
  const xref = streamObject(
    xrefNum,
    `<< /Type /XRef /Size ${xrefNum + 1} /W [${width.join(" ")}]${parms} /Filter /FlateDecode ${trailer} >>`,
    await deflate(flat),
  );

  return concat(
    bytes,
    `${xref.num} 0 obj\n`,
    xref.body,
    `\nendobj\n`,
    `startxref\n${xrefAt}\n%%EOF\n`,
  );
}

/**
 * A value as XML text.
 *
 * **A producer escapes and so does this.** `Taylor & Francis` is a real
 * publisher in the corpus, and a bare ampersand makes the whole packet
 * malformed, so a fixture that did not escape would be testing the parse error
 * rather than the field.
 */
function escapeXml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
}

/** An XMP packet carrying the `dc:` fields a test names. */
export function xmpPacket(
  fields: Readonly<Record<string, string | readonly string[]>>,
  options: {
    readonly doctype?: string;
    readonly prefix?: string;
    /**
     * Write the values through without escaping them.
     *
     * For the one test that needs an entity reference to survive into the
     * packet. Escaping is the default because a producer escapes, and the
     * entity guard's own test silently stopped exercising the guard when this
     * module started escaping: `&secret;` became `&amp;secret;`, the parse
     * succeeded, and the assertion was about a literal rather than about an
     * entity.
     */
    readonly raw?: boolean;
  } = {},
): string {
  const prefix = options.prefix ?? "rdf";
  let body = "";
  for (const [name, value] of Object.entries(fields)) {
    const items = typeof value === "string" ? [value] : value;
    const list = items
      .map(
        (item) =>
          `<${prefix}:li>${options.raw === true ? item : escapeXml(item)}</${prefix}:li>`,
      )
      .join("");
    body += `<dc:${name}><${prefix}:Seq>${list}</${prefix}:Seq></dc:${name}>`;
  }
  return (
    `<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n` +
    (options.doctype ?? "") +
    `<${prefix}:RDF xmlns:${prefix}="http://www.w3.org/1999/02/22-rdf-syntax-ns#">` +
    `<${prefix}:Description xmlns:dc="http://purl.org/dc/elements/1.1/">${body}</${prefix}:Description>` +
    `</${prefix}:RDF>\n<?xpacket end="w"?>`
  );
}
