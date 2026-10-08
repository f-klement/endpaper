/**
 * Counting the work a reader does, at the two doors every byte comes through.
 *
 * **The oracle a fuzz property here needs, and "did it throw" is not one.** The
 * PDF reader once charged bytes read and not bytes inflated: a 1,562,153 byte
 * file drove 1,593,843,488 bytes through the decompressor and answered `ok` in
 * 801 ms, by `pdf.ts`'s own record. No throw, no hang, no failure a caller
 * could see. Only a count of what came out of the inflater sees it, held
 * against the bound the reader itself declares.
 *
 * **The two doors.** Every byte a reader holds arrives through a read of the
 * `Blob` it was handed or out of a `DecompressionStream`. So a `MeteredFile` is
 * handed in, whose slices share its meter, and the global inflater is replaced
 * by a counting one **for the length of one call** and put back in a
 * `finally`, the shape `withoutDecompression.ts` already has. `tests/setup.ts`
 * refuses a replacement left installed by identity, not only by presence.
 *
 * **And a third, which is not a door bytes come through but a door expansion
 * happens behind**: every string handed to `DOMParser.parseFromString`, counted
 * the same way for the same call. An entity declaration expands inside the
 * engine's parser, before any code here sees a node, so what a reader hands
 * the parser is the last point anything can observe it. Counted by length and
 * by whether it declares, never kept: a document at a cap is sixteen
 * mebibytes.
 *
 * **What it does not see, stated as a mechanism and with no extent claimed**:
 * anything a reader allocates from bytes it already counted (a parse, a copy,
 * a string), a `Blob` a reader builds for itself and reads, and wasm memory.
 *
 * **A count, then a sentinel.** Each counted event reads the clock and the
 * counts synchronously, inside the door, which needs no event loop: a timer
 * starves under a loop awaiting a `Blob` read in every runtime this suite runs
 * on. Past a ceiling it records a breach and throws a sentinel, and every later
 * event throws it again so a runaway stops. **The breach is the finding, not
 * the throw**, because a reader may turn the sentinel into one of its own named
 * failures: `zip.ts` answers any inflater rejection as `truncated`. The
 * contract reads the breach after the call, whatever the reader answered.
 *
 * **What the residue is**: a synchronous loop that touches neither door is
 * seen by nothing here, and by nothing in vitest.
 */

import { realDecompressionStream } from "./withoutDecompression";

/**
 * How long one call may run before the meter calls it stalled.
 *
 * **A stall cap and not a deadline**, and the difference is the whole of why it
 * is allowed here when `docs/decisions.md` refuses a per example deadline: it
 * sits far above any honest call, so it fires on a loop that will never end
 * rather than on a slow node. **Chosen, not measured.** It is read at every
 * door and once when the call ends, so finite work after the last read is
 * seen; a loop that never ends and touches no door is not.
 */
export const STALL_MS = 20_000;

/** The bounds a reader declares, as the meter holds them. */
export interface Ceilings {
  /** Bytes any one inflater may emit before it must stop being pulled. */
  readonly perInflate?: number;
  /** Bytes all inflaters together may emit before none may be pulled. */
  readonly inflated?: number;
  /**
   * Bytes read and inflated together, before nothing more may arrive. A read is
   * charged before it happens, so a read that would cross this is a breach.
   */
  readonly total?: number;
  /** Bytes read altogether. Exact, because a read is not chunked. */
  readonly read?: number;
  /** Bytes any one read may ask for. For a reader whose reads are each bounded. */
  readonly perRead?: number;
  /** How many reads a call may make. For a reader bounded by a count of slices. */
  readonly reads?: number;
  /**
   * The longest string any XML parse may be handed, in code units, which is
   * the unit a reader's own length check compares.
   */
  readonly parsed?: number;
  /**
   * That no XML parse is handed a string carrying `<!ENTITY`, which is
   * `xmlEntities.ts`'s rule seen from the parser's side. **Opt in, per door**,
   * because `pdf.ts` hands the parser a packet cut to its root element without
   * the rule, and says at its own site why that is sound.
   */
  readonly refusesEntities?: true;
}

/** What the meter counted, for a control arm to ask about. */
export interface Counted {
  readonly read: number;
  readonly reads: number;
  /** The most any one read asked for. */
  readonly largestRead: number;
  readonly inflated: number;
  readonly inflaters: number;
  readonly largestChunk: number;
  /**
   * What each inflater emitted, in the order they were built. **The only
   * attribution the meter has**: it cannot see which entry an inflater serves,
   * so a door that needs one read's share reads it here by position, where it
   * knows the order its reader reads in.
   */
  readonly pulls: readonly number[];
  /**
   * Whether each inflater's output ended, by the same position: `false` for
   * one the reader stopped pulling, which is what a refusal at a bound looks
   * like, or one whose stream broke.
   */
  readonly ended: readonly boolean[];
  /** Strings handed to `DOMParser.parseFromString`, of any media type. */
  readonly parses: number;
}

/**
 * What a door is handed of the meter: a breach it noticed itself, what was
 * counted so far, and the one bound that moves within a call.
 *
 * **Narrow at run time, not only in its type.** A door holding the whole
 * meter could rewrite the bound it is held to: one setting the per inflater
 * bound to nothing passed a mebibyte past a kibibyte ceiling, and, while the
 * door was handed the meter typed as this, writing `ceilings` through
 * `Reflect`, emptying the ceilings object in place, reaching the meter off
 * the file, and clearing `reason` after swallowing the sentinel each let a
 * four mebibyte read past a one mebibyte ceiling, measured. So a door is
 * handed `Meter.handle()`, a frozen object of three closures, and every field
 * of the meter and of `MeteredFile` is a `#` field, which nothing outside
 * the class reaches. **What it still allows, stated**: a door handing the
 * meter a larger finite bound than it hands its reader. The zip seam is the
 * one door that sets it, from the same value at the same line.
 */
export interface DoorMeter {
  require(holds: boolean, breach: string): void;
  readonly counted: Counted;
  boundEachInflater(bytes: number): void;
}

/** What the meter throws once a ceiling is crossed. Exported by no door. */
export class MeterSentinel extends Error {
  constructor(breach: string) {
    super(`the meter stopped this call: ${breach}`);
    this.name = "MeterSentinel";
  }
}

export class Meter implements DoorMeter {
  #readBytes = 0;
  #readCount = 0;
  #largestReadBytes = 0;
  #inflatedBytes = 0;
  #inflaterCount = 0;
  #largest = 0;
  readonly #pulled: number[] = [];
  readonly #finished: boolean[] = [];
  #parseCount = 0;
  #started = performance.now();
  #reason: string | null = null;
  /** A frozen copy, so the object a door's `ceilings` returned is not this. */
  readonly #ceilings: Readonly<Ceilings>;
  /**
   * The per inflater bound at this point in the call. Each inflater takes it
   * at construction. **Set only by `boundEachInflater`**, for the reason
   * `DoorMeter` gives.
   */
  #perInflate: number | undefined;

  constructor(ceilings: Ceilings = {}) {
    this.#ceilings = Object.freeze({ ...ceilings });
    this.#perInflate = ceilings.perInflate;
  }

  /**
   * What a door is handed: three closures over this meter, frozen, and
   * nothing else of it. `DoorMeter` says why.
   */
  handle(): DoorMeter {
    // An arrow, so the getter below reads this meter without naming it.
    const counted = (): Counted => this.counted;
    return Object.freeze({
      require: (holds: boolean, breach: string) => this.require(holds, breach),
      get counted() {
        return counted();
      },
      boundEachInflater: (bytes: number) => this.boundEachInflater(bytes),
    });
  }

  /**
   * The per inflater bound from here on, for a door whose bound is its
   * caller's argument and so moves between two reads of one call. Refuses a
   * bound that is not a finite size, which is what disarming would take.
   */
  boundEachInflater(bytes: number): void {
    if (!Number.isFinite(bytes) || bytes < 0) {
      throw new Error(`a door asked for an inflater bound of ${bytes}`);
    }
    this.#perInflate = bytes;
  }

  /** The first ceiling crossed, or `null`. */
  get breach(): string | null {
    return this.#reason;
  }

  get counted(): Counted {
    return {
      read: this.#readBytes,
      reads: this.#readCount,
      largestRead: this.#largestReadBytes,
      inflated: this.#inflatedBytes,
      inflaters: this.#inflaterCount,
      largestChunk: this.#largest,
      pulls: [...this.#pulled],
      ended: [...this.#finished],
      parses: this.#parseCount,
    };
  }

  /**
   * Record a breach a door noticed by itself, such as a charge short of what
   * was inflated. Never overwrites the first, which is the one to report.
   */
  require(holds: boolean, breach: string): void {
    if (!holds && this.#reason === null) this.#reason = breach;
  }

  /**
   * Run `call` with the inflater and the parser counted, and the clock started
   * now. The parser only where the environment has one: a file running under
   * node has none, and a reader there that reaches for it throws on its own.
   */
  async measure<T>(call: () => Promise<T> | T): Promise<T> {
    this.#started = performance.now();
    const real = Object.getOwnPropertyDescriptor(
      globalThis,
      "DecompressionStream",
    );
    // **Loud rather than vacuous**, `withoutDecompressionStream`'s reason: an
    // environment with no inflater would count nothing and every inflation
    // ceiling would hold over zero.
    if (real === undefined || real.value !== realDecompressionStream()) {
      throw new Error(
        "the meter found no original DecompressionStream to wrap, so it " +
          "would count nothing",
      );
    }
    const Real = real.value as typeof DecompressionStream;
    // Arrows, so `this` inside the class below stays the stream it builds.
    const open = (): { index: number; bound: number | undefined } => {
      this.#inflaterCount += 1;
      this.#pulled.push(0);
      this.#finished.push(false);
      return { index: this.#pulled.length - 1, bound: this.#perInflate };
    };
    const ended = (index: number): void => {
      this.#finished[index] = true;
    };
    const chunk = (
      index: number,
      bytes: number,
      pulled: number,
      bound?: number,
    ): void => this.chunk(index, bytes, pulled, bound);
    class CountingDecompressionStream {
      readonly writable: WritableStream<BufferSource>;
      readonly readable: ReadableStream<Uint8Array<ArrayBuffer>>;
      constructor(format: CompressionFormat) {
        // Constructed first, so a format the engine refuses throws what the
        // engine throws and the reader's own guard sees the same thing.
        const inner = new Real(format);
        const { index, bound } = open();
        let pulled = 0;
        this.writable = inner.writable;
        // **A transform behind the real one, so the count is of what the
        // reader pulls.** A transform runs only when its readable is read,
        // measured under node and bun: seven reads counted seven chunks, and
        // the inflater's own read ahead is never counted.
        this.readable = inner.readable.pipeThrough(
          new TransformStream<Uint8Array<ArrayBuffer>, Uint8Array<ArrayBuffer>>(
            {
              transform: (piece, controller) => {
                chunk(index, piece.byteLength, pulled, bound);
                pulled += piece.byteLength;
                controller.enqueue(piece);
              },
              // Runs only once the inner stream has ended and every chunk
              // before it was pulled, so a read the reader stopped never
              // reaches it.
              flush: () => ended(index),
            },
          ),
        );
      }
    }
    // **Read through the global and put back by its own descriptor**, because
    // a test DOM installs `DOMParser` as an accessor rather than a value, and
    // a descriptor carrying both is refused by `defineProperty`. Measured: the
    // first version spread the accessor's descriptor, threw after the inflater
    // was already swapped, and left it swapped for every later file.
    const parser = Object.getOwnPropertyDescriptor(globalThis, "DOMParser");
    const Parser = (globalThis as { DOMParser?: typeof DOMParser }).DOMParser;
    // Loud for a door that asked for the parser to be counted, for the
    // inflater's reason above: a ceiling held over no parses holds over zero.
    if (
      (parser === undefined || Parser === undefined) &&
      (this.#ceilings.parsed !== undefined ||
        this.#ceilings.refusesEntities === true)
    ) {
      throw new Error(
        "the meter found no DOMParser to wrap on the global, so the parse " +
          "ceilings this door declares would hold over nothing",
      );
    }
    try {
      Object.defineProperty(globalThis, "DecompressionStream", {
        ...real,
        value: CountingDecompressionStream,
      });
      if (parser !== undefined && Parser !== undefined) {
        Object.defineProperty(globalThis, "DOMParser", {
          configurable: true,
          enumerable: parser.enumerable ?? false,
          writable: true,
          value: this.countingParser(Parser),
        });
      }
      return await call();
    } finally {
      // **The clock once more, after the call, whichever way it ended**,
      // because a reader parses after its last read and a parse is where
      // finite but quadratic work runs: the cap read only at a door never sees
      // it. Recorded, not thrown: the contract reads the breach first.
      const elapsed = performance.now() - this.#started;
      this.require(
        elapsed <= STALL_MS,
        `the call ended after ${Math.round(elapsed)} ms, past the stall cap of ${STALL_MS}`,
      );
      Object.defineProperty(globalThis, "DecompressionStream", real);
      if (parser !== undefined) {
        Object.defineProperty(globalThis, "DOMParser", parser);
      }
    }
  }

  /**
   * A `DOMParser` that counts what it is handed and delegates the parse.
   *
   * **A wrapper and not a subclass**: jsdom's interfaces are generated
   * wrappers, and every reader here writes `new DOMParser().parseFromString`,
   * which is the one method this needs to carry.

   */
  private countingParser(Real: typeof DOMParser): unknown {
    const parse = (string: string, type: string): void =>
      this.parse(string, type);
    return class CountingDOMParser {
      private readonly inner = new Real();
      parseFromString(string: string, type: DOMParserSupportedType): Document {
        parse(string, type);
        return this.inner.parseFromString(string, type);
      }
    };
  }

  /**
   * One string handed to the parser. **An XML parse is every media type but
   * `text/html`**, which has no internal subset to expand: `text/xml` and
   * `image/svg+xml` are XML to the engine whatever a reader calls them.
   */
  private parse(string: string, type: string): void {
    this.step();
    this.#parseCount += 1;
    if (type === "text/html") return;
    if (this.#ceilings.parsed !== undefined) {
      this.refuseIf(
        string.length > this.#ceilings.parsed,
        `an XML parse was handed ${string.length} code units against a ceiling of ${this.#ceilings.parsed}`,
      );
    }
    if (this.#ceilings.refusesEntities === true) {
      this.refuseIf(
        string.includes("<!ENTITY"),
        "an XML parse was handed a document declaring an entity",
      );
    }
  }

  /** One read of `bytes`, charged before it is handed over. */
  read(bytes: number): void {
    this.step();
    const total = this.#readBytes + this.#inflatedBytes + bytes;
    if (this.#ceilings.reads !== undefined) {
      this.refuseIf(
        this.#readCount + 1 > this.#ceilings.reads,
        `made read ${this.#readCount + 1} against a ceiling of ${this.#ceilings.reads}`,
      );
    }
    if (this.#ceilings.perRead !== undefined) {
      this.refuseIf(
        bytes > this.#ceilings.perRead,
        `read ${bytes} bytes at once against a ceiling of ${this.#ceilings.perRead}`,
      );
    }
    if (this.#ceilings.read !== undefined) {
      this.refuseIf(
        this.#readBytes + bytes > this.#ceilings.read,
        `read ${this.#readBytes + bytes} bytes against a ceiling of ${this.#ceilings.read}`,
      );
    }
    if (this.#ceilings.total !== undefined) {
      this.refuseIf(
        total > this.#ceilings.total,
        `read past the total of ${this.#ceilings.total}: ${total} read and inflated`,
      );
    }
    this.#readBytes += bytes;
    this.#readCount += 1;
    this.#largestReadBytes = Math.max(this.#largestReadBytes, bytes);
  }

  /**
   * One chunk out of an inflater that had emitted `pulled` before it.
   *
   * **"No chunk pulled after the bound was crossed", never "at most the
   * bound".** Both inflaters here count a chunk before refusing, so what they
   * hold exceeds the bound by up to one chunk of whatever size the engine
   * chose, and a property asserting the total would refuse a correct reader.
   * So the chunk that crosses is allowed and the next one is the breach.
   */
  private chunk(
    index: number,
    bytes: number,
    pulled: number,
    bound: number | undefined,
  ): void {
    this.step();
    if (bound !== undefined) {
      this.refuseIf(
        pulled > bound,
        `an inflater was pulled again after emitting ${pulled} bytes against a bound of ${bound}`,
      );
    }
    // **The aggregate's slack is one chunk for itself, and one for every
    // earlier inflater the reader stopped.** A reader keeping a total charges
    // a refused read the ceiling it granted, and the inflater it stopped was
    // allowed the chunk that crossed that ceiling, so each refusal leaves at
    // most one chunk inflated and never charged. One chunk in all refused a
    // correct Takeout reader whose sidecars were refused at their ceiling
    // before a book's package overspent, measured by the named case in
    // `takeout.test.ts`. **What the slack does not grow with** is a read that
    // ended, which was charged what it inflated. The largest chunk seen,
    // because the engine chooses it: 16 KiB under node, 64 KiB under bun.
    if (this.#ceilings.inflated !== undefined) {
      const stopped = this.#finished
        .slice(0, index)
        .filter((ended) => !ended).length;
      this.refuseIf(
        this.#inflatedBytes >
          this.#ceilings.inflated + (1 + stopped) * this.#largest,
        `an inflater was pulled again after ${this.#inflatedBytes} bytes inflated against a ceiling of ${this.#ceilings.inflated}`,
      );
    }
    // A total is one chunk of slack and no more: the reader it was written
    // for charges every chunk as it arrives, so a refusal leaves nothing
    // uncharged behind it.
    if (this.#ceilings.total !== undefined) {
      const total = this.#readBytes + this.#inflatedBytes;
      this.refuseIf(
        total > this.#ceilings.total + this.#largest,
        `an inflater was pulled again after ${total} bytes read and inflated against a total of ${this.#ceilings.total}`,
      );
    }
    this.#inflatedBytes += bytes;
    this.#pulled[index] = pulled + bytes;
    this.#largest = Math.max(this.#largest, bytes);
  }

  /** The clock, and a breach already recorded, at every event. */
  private step(): void {
    if (this.#reason !== null) throw new MeterSentinel(this.#reason);
    const elapsed = performance.now() - this.#started;
    this.refuseIf(
      elapsed > STALL_MS,
      `the call was still reading after ${Math.round(elapsed)} ms, past the stall cap of ${STALL_MS}`,
    );
  }

  private refuseIf(crossed: boolean, breach: string): void {
    if (!crossed) return;
    this.#reason ??= breach;
    throw new MeterSentinel(this.#reason);
  }
}

/**
 * A file whose reads are counted, and whose slices count on the same meter.
 *
 * **A `File` because the store openers take one**, and a `File` is a `Blob`,
 * so every other door sees what it always saw. A slice is a `File` too, which
 * the platform's is not; no reader here asks.
 *
 * **A subclass handed in, and no global touched for reads.** No reader here
 * checks `instanceof Blob`, so a subclass is what they see. **`stream()` is
 * not counted and throws instead**, so a reader that starts reading a stream
 * is a loud failure at this file rather than a quiet hole in every property.
 * **Two routes are neither counted nor refused**: a `FileReader`, and a
 * `Response` built over the file, whose reads are the platform's and are not
 * claimed either way. No reader under `src/lib` uses either; one that moved to
 * one would show as a control arm counting no reads.
 */
export class MeteredFile extends File {
  /** `#`, for the reason `DoorMeter` gives: the reader is handed this file. */
  readonly #held: Uint8Array<ArrayBuffer>;
  readonly #meter: Meter;

  constructor(
    held: Uint8Array<ArrayBuffer>,
    meter: Meter,
    name = "",
    type = "",
  ) {
    super([held], name, { type });
    this.#held = held;
    this.#meter = meter;
  }

  override slice(start?: number, end?: number, contentType?: string): Blob {
    const length = this.#held.length;
    const from = clamp(start ?? 0, length);
    const to = clamp(end ?? length, length);
    return new MeteredFile(
      this.#held.subarray(from, Math.max(from, to)),
      this.#meter,
      "",
      contentType,
    );
  }

  override arrayBuffer(): Promise<ArrayBuffer> {
    this.#meter.read(this.size);
    return super.arrayBuffer();
  }

  override text(): Promise<string> {
    this.#meter.read(this.size);
    return super.text();
  }

  /** Declared without `override`: not every lib this compiles against has it. */
  bytes(): Promise<Uint8Array<ArrayBuffer>> {
    this.#meter.read(this.size);
    return super.arrayBuffer().then((buffer) => new Uint8Array(buffer));
  }

  override stream(): ReadableStream<Uint8Array<ArrayBuffer>> {
    throw new Error(
      "a reader called stream() on a metered file, which the meter does not " +
        "count; teach tests/lib/meter.ts the route before trusting a property",
    );
  }
}

/** `Blob.slice`'s own rule for one index: negative counts from the end. */
function clamp(index: number, length: number): number {
  const whole = Math.trunc(index);
  return whole < 0 ? Math.max(length + whole, 0) : Math.min(whole, length);
}
