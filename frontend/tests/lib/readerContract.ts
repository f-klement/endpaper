/**
 * The one contract a door of the reader family is held to, by its properties
 * and by every named case a property produces.
 *
 * **One function for both, and that is the point of it.** A property calls
 * `expectNamedOutcome(door, hostile)` for every value it draws; a counterexample
 * becomes an `it` calling the same function on the printed literal and
 * asserting the exact answer it returns. So the case cannot test something
 * narrower than the property that found it, and the input in the case is what
 * fast-check printed, because what it draws is a builder's spec and not bytes.
 *
 * **"Named" has one definition, read off the door's own module rather than
 * listed per door.** An outcome is named when the door returned it, or when it
 * threw an instance of an `Error` subclass **its own module exports**. Today
 * that admits `ZipError` from `openZip` and the archive's two reads, and
 * nothing anywhere else: `PdfError` and `AudioError` are not exported, so a
 * leak of either out of its reader is a failure here without being named. A
 * door module that re-exported `ZipError` for convenience would make a leaked
 * one legal there; none does.
 *
 * **The module must be a module**, a namespace object as `import * as` binds
 * it, and that is checked rather than trusted: a door handed `{ ...zip,
 * TypeError }` named a leaked `TypeError`, measured, because a plain object is
 * a list of whatever somebody put in it. **The residue, stated**: a real module
 * that is not the door's own, another reader's, is accepted.
 *
 * **What it does not hold, so nobody reads it as more.** That a returned
 * failure is a member of its door's union is the type checker's, not this:
 * there is no cast onto a failure union in `src/lib`, so a string outside one
 * cannot be returned without the compiler's say so. And a module's top level
 * runs once per worker under `isolate: false`, so a defect at module scope
 * (the `TextDecoder` a runtime may not carry) is out of reach of every input;
 * a parse rule in `houseRules.test.ts` is that instrument.
 *
 * **The meter is read first, whatever the door answered**, because a door may
 * turn the meter's own sentinel into a named failure of its own.
 *
 * **Every bound a driven door declares needs a positive control in the same
 * file**, and the ledger in `doorLedger.ts` refuses the difference when the
 * file ends: each call here records what the door's `ceilings` declared, and
 * `overrunBreach` records a bound it overran and the meter named.
 */

import fc from "fast-check";

import { type Total } from "../property";
import { declared, overran } from "./doorLedger";
import {
  Meter,
  MeteredFile,
  type Ceilings,
  type Counted,
  type DoorMeter,
} from "./meter";

/**
 * One byte overwritten in the built file. Negative counts from the end, where a
 * zip's directory and a PDF's trailer are. Out of range is ignored rather than
 * wrapped, so a printed patch means the byte it names.
 */
export interface Patch {
  readonly at: number;
  readonly byte: number;
}

/**
 * A builder's spec and the bytes no spec field can reach.
 *
 * **The spec is the structure and the patches are the rest.** A spec type
 * cannot express every header field a hostile file gets wrong, and a short list
 * of single byte patches reaches them while staying a literal a person can read
 * in a test.
 */
export interface Hostile<Spec> {
  readonly spec: Spec;
  readonly patches: readonly Patch[];
}

/** A few patches, mostly none, near either end of the file. */
export function patches(): fc.Arbitrary<readonly Patch[]> {
  const patch = fc.record({
    at: fc.oneof(fc.integer({ min: -256, max: -1 }), fc.nat({ max: 4096 })),
    byte: fc.oneof(
      fc.constantFrom(0x00, 0xff, 0x7f, 0x80),
      fc.integer({ min: 0, max: 0xff }),
    ),
  } satisfies Total<Patch>);
  return fc.oneof(
    { arbitrary: fc.constant([]), weight: 3 },
    { arbitrary: fc.array(patch, { minLength: 1, maxLength: 4 }), weight: 1 },
  );
}

/** A hostile value: the spec, with or without patches. */
export function hostile<Spec>(
  spec: fc.Arbitrary<Spec>,
): fc.Arbitrary<Hostile<Spec>> {
  return fc.record({ spec, patches: patches() });
}

/** The bytes with each patch applied, to a copy. */
export function applyPatches(
  bytes: Uint8Array<ArrayBuffer>,
  list: readonly Patch[],
): Uint8Array<ArrayBuffer> {
  if (list.length === 0) return bytes;
  const out = new Uint8Array(bytes);
  for (const { at, byte } of list) {
    const index = at < 0 ? out.length + at : at;
    if (index >= 0 && index < out.length) out[index] = byte;
  }
  return out;
}

/** One door of the reader family, as the contract drives it. */
export interface Door<Spec, Answer> {
  /**
   * The module the door belongs to, as a namespace. Its exported `Error`
   * subclasses are the only things the door may throw.
   */
  readonly module: object;
  /** What the door declares it will spend, for a file of this many bytes. */
  readonly ceilings: (size: number) => Ceilings;
  /**
   * The bytes a spec describes. **It reads the spec and never writes it**:
   * fast-check prints a counterexample after the body ran, so a builder that
   * changed the spec would print an input other than the one that failed.
   */
  readonly build: (spec: Spec) => Promise<Uint8Array<ArrayBuffer>>;
  /**
   * Hand the door the file. The meter's narrow handle, `Meter.handle()` and
   * never the meter, is passed so a door with a bound that moves between
   * calls, or a promise of its own such as a charge, can say so, and the spec
   * so a door whose calls are part of what was drawn, which is the zip seam's,
   * can make them.
   *
   * **A `File`, named or not**, because a store's opener takes one; every
   * other door takes a `Blob` and is handed the same object.
   */
  readonly open: (file: File, meter: DoorMeter, spec: Spec) => Promise<Answer>;
  /** The file's name, for a door that is handed one. Empty otherwise. */
  readonly name?: string;
}

/**
 * One door that takes a value rather than a file: a string an XML reader
 * parses, a name, a picked entry.
 *
 * **The same contract and the same meter**, so a string door is held to the
 * parser door the meter counts, and to nothing on the two byte doors it never
 * reaches. What it may answer is whatever it returns; what it may throw is
 * what its module exports, which for every string door today is nothing.
 */
export interface ValueDoor<Input, Answer> {
  readonly module: object;
  readonly ceilings: (input: Input) => Ceilings;
  /**
   * Call the door. **It reads the input and never writes it**, for `build`'s
   * reason above.
   */
  readonly open: (input: Input, meter: DoorMeter) => Answer | Promise<Answer>;
}

/** What the door did with one file. */
export type Outcome<Answer> =
  { readonly answered: Answer } | { readonly threw: Error };

export interface Measured<Answer> {
  readonly outcome: Outcome<Answer>;
  readonly counted: Counted;
  /** The bytes the door was handed, patches applied. Zero for a value door. */
  readonly size: number;
}

/**
 * Drive one door with one hostile file, and refuse what the contract refuses.
 *
 * Throws when the meter recorded a breach, then when the door threw anything
 * its module does not export. Otherwise returns what happened, so a named case
 * can assert the exact answer and a control arm can ask what was counted.
 */
export async function expectNamedOutcome<Spec, Answer>(
  door: Door<Spec, Answer>,
  input: Hostile<Spec>,
): Promise<Measured<Answer>> {
  const bytes = applyPatches(await door.build(input.spec), input.patches);
  const ceilings = door.ceilings(bytes.length);
  declared(door.ceilings, ceilings);
  const meter = new Meter(ceilings);
  return drive(door.module, meter, bytes.length, () =>
    door.open(
      new MeteredFile(bytes, meter, door.name),
      meter.handle(),
      input.spec,
    ),
  );
}

/**
 * The same contract for a door handed a value rather than a file.
 *
 * **One body under both**, so a named case a string door produces is held to
 * exactly what its property held it to.
 */
export async function expectAnswer<Input, Answer>(
  door: ValueDoor<Input, Answer>,
  input: Input,
): Promise<Measured<Answer>> {
  const ceilings = door.ceilings(input);
  declared(door.ceilings, ceilings);
  const meter = new Meter(ceilings);
  return drive(door.module, meter, 0, () => door.open(input, meter.handle()));
}

async function drive<Answer>(
  module: object,
  meter: Meter,
  size: number,
  call: () => Answer | Promise<Answer>,
): Promise<Measured<Answer>> {
  if (Object.prototype.toString.call(module) !== "[object Module]") {
    throw new Error(
      "the door's module is not a module namespace, so the errors it may " +
        "throw are whatever was put in it: hand it `import * as` of the reader",
    );
  }
  let outcome: Outcome<Answer> | { readonly threwNonError: unknown };
  try {
    outcome = { answered: await meter.measure(call) };
  } catch (error) {
    outcome =
      error instanceof Error ? { threw: error } : { threwNonError: error };
  }

  if (meter.breach !== null) {
    throw new Error(
      `the door overran what it declares: ${meter.breach}. ` +
        `It ${"answered" in outcome ? "answered" : "threw"} afterwards, ` +
        "which is why the meter is read first.",
    );
  }
  if ("threwNonError" in outcome) {
    throw new Error(
      `the door threw a value that is not an Error: ${String(outcome.threwNonError)}`,
    );
  }
  if ("threw" in outcome && !isNamed(module, outcome.threw)) {
    throw new Error(
      `the door threw ${outcome.threw.name}: ${outcome.threw.message}, ` +
        "which its own module does not export, so no caller can name it",
      { cause: outcome.threw },
    );
  }
  return { outcome, counted: meter.counted, size };
}

/** Whether `thrown` is an instance of an `Error` class `module` exports. */
function isNamed(module: object, thrown: Error): boolean {
  return Object.values(module).some(
    (value) =>
      typeof value === "function" &&
      value.prototype instanceof Error &&
      thrown instanceof value,
  );
}

/**
 * Whether the reader stopped some inflater past `bound` and within the chunk
 * that crossed it: a read refused at exactly that bound, which is what a
 * property's reach asks of a bomb.
 *
 * **Stopped, and not only large**, because an entry holding exactly the bound
 * is read whole and ends there; only a read the reader cut off is a refusal.
 */
export function stoppedAt(counted: Counted, bound: number): boolean {
  return counted.pulls.some(
    (pulled, at) =>
      counted.ended[at] === false &&
      pulled > bound &&
      pulled <= bound + counted.largestChunk,
  );
}

/**
 * One bound a door declares, and how far past it a positive control goes.
 *
 * `each` is what one inflater may emit, for an aggregate held over several:
 * the control spreads its overrun over inflaters of that size, so only the
 * aggregate can be what refuses it. Absent on `total`, the control reads
 * rather than inflates, which is the half of that sum a reader charging only
 * inflation would leave unheld.
 *
 * `size` is the file the door's `ceilings` are asked for, one byte otherwise,
 * for a door whose aggregate grows with the file and sits under the per
 * inflater bound for a small one: Takeout's does below about 1.5 MB.
 */
export type Overrun =
  | {
      readonly ceiling: "perInflate";
      readonly bound: number;
      readonly size?: number;
    }
  | {
      readonly ceiling: "inflated";
      readonly bound: number;
      readonly each: number;
    }
  | {
      readonly ceiling: "total";
      readonly bound: number;
      readonly each?: number;
    }
  | {
      readonly ceiling: "read" | "perRead" | "reads" | "parsed";
      readonly bound: number;
    }
  | { readonly ceiling: "refusesEntities" };

/**
 * How far past a bound a control inflates: four of the largest chunk any
 * engine here emits, so the chunk that crosses is followed by one the meter
 * must refuse under either runtime. `zipFixtures.FAR_PAST` makes the same
 * argument for a bomb; restated here, because this module must not reach for
 * the byte builders.
 */
const PAST = 4 * 64 * 1024;

/** The most a control's read charges at once, where nothing bounds a read. */
const PIECE = 1024 * 1024;

/** Deflated runs of zeroes by length, built once per worker. */
const DEFLATED = new Map<number, Uint8Array<ArrayBuffer>>();

/**
 * A stream of one chunk. **Not `Blob.stream()`**, which jsdom's `Blob` does
 * not carry, and three doors run under jsdom.
 */
function streamOf(
  bytes: Uint8Array<ArrayBuffer>,
): ReadableStream<Uint8Array<ArrayBuffer>> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

async function drain(stream: ReadableStream<Uint8Array>): Promise<number> {
  const reader = stream.getReader();
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return total;
    total += value.byteLength;
  }
}

async function deflatedZeroes(
  length: number,
): Promise<Uint8Array<ArrayBuffer>> {
  const known = DEFLATED.get(length);
  if (known) return known;
  const parts: Uint8Array[] = [];
  // Fed a chunk at a time rather than as one buffer of `length`, which for the
  // Takeout control is 32 MiB held at once in a shared worker.
  let left = length;
  const zeroes = new ReadableStream<Uint8Array<ArrayBuffer>>({
    pull(controller) {
      if (left === 0) {
        controller.close();
        return;
      }
      const piece = Math.min(left, 64 * 1024);
      left -= piece;
      controller.enqueue(new Uint8Array(piece));
    },
  });
  const reader = zeroes
    .pipeThrough(new CompressionStream("deflate-raw"))
    .getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
  }
  const built = new Uint8Array(
    parts.reduce((sum, part) => sum + part.length, 0),
  );
  let at = 0;
  for (const part of parts) {
    built.set(part, at);
    at += part.length;
  }
  DEFLATED.set(length, built);
  return built;
}

/** Pull `length` zeroes out of one inflater, the global one the meter wraps. */
async function inflate(deflated: Uint8Array<ArrayBuffer>): Promise<number> {
  return drain(
    streamOf(deflated).pipeThrough(new DecompressionStream("deflate-raw")),
  );
}

/**
 * The words the meter's own breach uses for each bound, so a control is
 * credited only where the bound that refused it is the one it aimed at.
 */
function names(breach: string, overrun: Overrun): boolean {
  switch (overrun.ceiling) {
    case "perInflate":
      return breach.endsWith(`against a bound of ${overrun.bound}`);
    case "inflated":
      return breach.endsWith(`inflated against a ceiling of ${overrun.bound}`);
    case "total":
      return breach.includes(`total of ${overrun.bound}`);
    case "read":
      return (
        /^read \d+ bytes against/.test(breach) &&
        breach.endsWith(`a ceiling of ${overrun.bound}`)
      );
    case "perRead":
      return breach.endsWith(`at once against a ceiling of ${overrun.bound}`);
    case "reads":
      return (
        /^made read \d+ against/.test(breach) &&
        breach.endsWith(`a ceiling of ${overrun.bound}`)
      );
    case "parsed":
      return breach.endsWith(
        `code units against a ceiling of ${overrun.bound}`,
      );
    case "refusesEntities":
      return breach.endsWith("declaring an entity");
  }
}

/**
 * Drive a door's own ceilings with a stub that overruns `overrun`, and answer
 * the breach the meter recorded, or `null` where it let it pass.
 *
 * **The positive control a property's green needs.** A property passes over a
 * correct reader whatever its door declares, so nothing reds when a door's
 * ceilings are deleted or loosened: measured, every door emptied, every arm
 * green, and a reader defect live behind two of them. This keeps the door's
 * `ceilings` and replaces only what reads, so a ceiling that went or moved
 * answers `null` or a breach naming another bound, and the arm asserting the
 * breach names this one reds. **And the ledger is told** when the breach
 * names the bound aimed at, which is what lets a file's end refuse a declared
 * bound no control overran.
 *
 * **A file door or a value door**: `input` is what a value door's `ceilings`
 * are asked of, and a file door is asked for a file of `size`. A read is
 * charged to the meter as the file would charge it rather than made, so a
 * bound of tens of mebibytes is overrun without a buffer of that size, and an
 * inflation is real, through the meter's own inflater. A parse hands the
 * meter's parser a string past the bound, which the meter refuses before the
 * engine sees it.
 *
 * **What it does not hold**: a breach the door's own `open` records, such as
 * EPUB's charge relation, and a bound a door sets while it reads, which is
 * the zip seam's. Those are held by the reach a property asserts.
 */
export async function overrunBreach<Spec, Answer>(
  door: Door<Spec, Answer> | ValueDoor<Spec, Answer>,
  overrun: Overrun,
  input?: Spec,
): Promise<string | null> {
  const size = overrun.ceiling === "perInflate" ? (overrun.size ?? 1) : 1;
  const ceilings =
    "build" in door
      ? door.ceilings(size)
      : (door.ceilings as (value: Spec | undefined) => Ceilings)(input);
  const meter = new Meter(ceilings);
  const deflated =
    overrun.ceiling === "perInflate"
      ? await deflatedZeroes(overrun.bound + PAST)
      : overrun.ceiling === "inflated" ||
          (overrun.ceiling === "total" && overrun.each !== undefined)
        ? await deflatedZeroes(overrun.each!)
        : null;
  /** Charge `bytes` read in pieces of at most `piece`, as a file would. */
  const charge = (bytes: number, piece: number): void => {
    for (let left = bytes; left > 0; left -= piece) {
      meter.read(Math.min(left, piece));
    }
  };
  const act = async (): Promise<number> => {
    switch (overrun.ceiling) {
      case "perInflate":
        return inflate(deflated!);
      case "inflated":
      case "total": {
        let total = 0;
        while (total <= overrun.bound + PAST) {
          if (deflated === null) {
            const piece = Math.min(ceilings.perRead ?? PIECE, PIECE);
            charge(piece, piece);
            total += piece;
          } else {
            total += await inflate(deflated);
          }
        }
        return total;
      }
      case "read": {
        // One read where the door bounds how many it makes, so the count is
        // not what refuses it; otherwise pieces no larger than one read may.
        const piece =
          ceilings.reads !== undefined
            ? Math.ceil((overrun.bound + 1) / ceilings.reads)
            : Math.min(ceilings.perRead ?? PIECE, PIECE);
        charge(overrun.bound + 1, piece);
        return overrun.bound + 1;
      }
      case "perRead":
        charge(overrun.bound + 1, overrun.bound + 1);
        return overrun.bound + 1;
      case "reads":
        charge(overrun.bound + 1, 1);
        return overrun.bound + 1;
      case "parsed":
        new DOMParser().parseFromString(
          "x".repeat(overrun.bound + 1),
          "application/xml",
        );
        return 0;
      case "refusesEntities":
        new DOMParser().parseFromString(
          '<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>',
          "application/xml",
        );
        return 0;
    }
  };
  try {
    await drive(door.module, meter, size, act);
    return null;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const breach =
      /^the door overran what it declares: (.*?)\. It (?:answered|threw) afterwards/s.exec(
        message,
      );
    if (breach === null) throw error;
    if (names(breach[1]!, overrun)) overran(door.ceilings, overrun.ceiling);
    return breach[1]!;
  }
}
