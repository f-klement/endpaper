/**
 * The one module that runs a property, and the only one that may.
 *
 * **Every fast-check runner, global and plugin is reached from here and from
 * nowhere else in the test tree**, which `tests/propertyBudget.test.ts` holds
 * by parse. A property elsewhere calls `holds` inside a plain `it`, and so it
 * cannot pass its own example count, seed, replay path, corpus of examples or
 * time limit: those are fast-check parameters, and only this module passes
 * parameters. The backend's budget guard refuses a list of keywords; fast-check
 * 4.10 moved its time limits into plugins, so a list here would already be one
 * spelling short. Refusing the call outside one module is closed whatever the
 * next version renames.
 *
 * **What this owns**, each for a reason a test author would otherwise get
 * wrong once:
 *
 * - `fc.check` and never `fc.assert`, so the run's own details are read here
 *   rather than trusted: an interrupted run reads as a pass unless asked.
 * - The `await`. A property not awaited ends its test before it runs.
 * - The example count, from the profile below, and the seed.
 * - **Counting what executed rather than reading the settings.** A plugin
 *   installed globally is invisible to `readConfigureGlobal`, and one that
 *   answers without calling the predicate lowers the work without lowering
 *   any number a setting holds. So the predicate is counted as it runs, and a
 *   run that executed fewer examples than its profile fails.
 * - Refusing a global configuration. Under `isolate: false` a
 *   `configureGlobal` in any file reaches every later property in its worker,
 *   in an order nobody chose, and it is read by `fc.sample` as well, so the
 *   witnesses would drift with the properties and agree with them.
 *
 * **A fresh seed per property per run, as the backend draws one**, because a
 * fixed seed makes a property the same sweep on every run, which can never find
 * what it did not find the first time (`docs/decisions.md`, the property budget
 * entry). **The cost particular to this suite, and how it is paid**: no timer
 * can interrupt a synchronous loop in its runtimes, and fast-check reports only
 * on failure, so a fresh input that spins would hang the run with nothing
 * printed. So the runner writes where it is before each example, synchronously
 * and unbuffered on standard error: `property <name> seed <s>`, then `run <i>`.
 * The last line before a kill names the input, and `replay` below regenerates
 * it. `docs/testing.md` carries the rule for what a counterexample becomes.
 *
 * **And the vocabulary every arbitrary shares, whatever it draws**: `Total`,
 * `sometimes`, `edges`, and `Repeated` with `spelled` for a run of text. Here
 * rather than beside the byte builders, so a property over a JSON body or a
 * form needs nothing of the reader family.
 */

import { writeSync } from "node:fs";

import fc from "fast-check";
import * as fastCheck from "fast-check";
import { expect } from "vitest";

/** How many examples a property runs, by profile. */
export interface Profile {
  readonly runs: number;
}

/**
 * The profiles, by name.
 *
 * **One**, the gate's. A second with more examples was proposed for a run off
 * the gate, to explore with a random seed; the gate now draws a fresh seed
 * itself, so all a second profile would add is more examples per run, and a
 * profile nothing selects is a number nothing reads.
 *
 * 200 is the backend's `suite` profile, for the backend's reason: enough that a
 * rare branch is reached, few enough that the suite is not paying for it.
 */
export const PROFILES = {
  suite: { runs: 200 },
} as const satisfies Record<string, Profile>;

/**
 * The fewest examples any profile may run.
 *
 * The backend's floor and its argument: a profile lowered to one example is a
 * suite that passes in the usual time and tests nothing.
 */
export const FLOOR = 50;

/** The profile the gate runs. */
export const PROFILE: Profile = PROFILES.suite;

/**
 * The variable that pins one seed, for reproducing a red, and nothing else.
 *
 * **Never set in a committed file**: a seed pinned in the gate is the fixed
 * sweep this module exists not to be. `tests/propertyBudget.test.ts` refuses an
 * assignment to it anywhere it could reach a run.
 */
export const REPLAY = "ENDPAPER_PROPERTY_SEED";

/** A seed: the pinned one where somebody is reproducing, otherwise fresh. */
function drawSeed(): number {
  const pinned = process.env[REPLAY];
  if (pinned !== undefined && pinned !== "") {
    // **Refused in a pipeline**, which is the one place a pin can be made that
    // no file in this tree shows: a project's CI variables. GitLab sets `CI`
    // in every job.
    if (process.env["CI"]) {
      throw new Error(
        `${REPLAY} is set in a pipeline, which would run one sweep forever`,
      );
    }
    const seed = Number(pinned);
    if (!Number.isSafeInteger(seed)) {
      throw new Error(`${REPLAY} is ${pinned}, which is not a seed`);
    }
    return seed;
  }
  return crypto.getRandomValues(new Int32Array(1))[0]!;
}

/**
 * One line on standard error, written now.
 *
 * **`writeSync` on the descriptor, never `console`**: vitest captures what a
 * test logs and relays it later, and a worker spinning in a synchronous loop
 * never relays anything again. A write that has returned is in the pipe.
 */
function progress(line: string): void {
  writeAll(2, `${line}\n`);
}

/** A cell to wait on, for a pause no timer is needed for. */
const PAUSE = new Int32Array(new SharedArrayBuffer(4));

/** How many one millisecond pauses a full pipe is waited out for. */
const PATIENCE = 2000;

/**
 * Write the whole of `text` to `fd`, waiting out a full pipe.
 *
 * **The suite pod's standard error is a non blocking pipe**, so a write into
 * it while full throws `EAGAIN` rather than waiting, and a write may take
 * part of what it was handed. Measured: two properties in a row, four
 * hundred lines in quick succession, and one property failed on `EAGAIN`
 * with nothing wrong with what it tested. So a full pipe is waited out, a
 * millisecond at a time and synchronously, because the line exists for the
 * case where the event loop never turns again, and what a partial write left
 * is written next. A pipe still full after `PATIENCE` is a reader that has
 * stopped, and that is thrown.
 */
export function writeAll(
  fd: number,
  text: string,
  write: (fd: number, bytes: Uint8Array) => number = writeSync,
): void {
  const bytes = new TextEncoder().encode(text);
  let at = 0;
  let waited = 0;
  while (at < bytes.length) {
    try {
      at += write(fd, bytes.subarray(at));
    } catch (error) {
      const code = (error as { code?: unknown }).code;
      if (code !== "EAGAIN" || waited >= PATIENCE) throw error;
      Atomics.wait(PAUSE, 0, 0, 1);
      waited += 1;
    }
  }
}

/** What the running test is called, for the progress line. */
function testName(): string {
  return expect.getState().currentTestName ?? "a property outside a test";
}

let last: number | null = null;

/**
 * The seed the most recent `holds` in this worker drew. For the budget guard,
 * which asks whether a property and `replay` at one seed see one sequence.
 */
export function lastSeed(): number | null {
  return last;
}

/**
 * The options every property's `it` takes, as `it(name, PROPERTY, body)`.
 *
 * **A ceiling on the whole property, not a deadline per example**, which
 * `docs/decisions.md` refuses for the backend for a reason that holds here: the
 * same example passes at 40 ms and fails at 210 ms on a shared node. What
 * bounds the cost is the example count and the size of what the arbitraries
 * draw. This only stops a property that has gone wrong from holding a worker,
 * and it is above vitest's five second default because 200 examples of a
 * reader are not one test's worth of work.
 *
 * **Chosen, not measured**, and it cannot interrupt a synchronous loop: no
 * timer can, in any runtime this suite runs on. The meter in
 * `tests/lib/meter.ts` is what notices a stall it can see, and the progress
 * lines are what name one it cannot.
 */
export const PROPERTY = { timeout: 120_000 } as const;

/**
 * What a run must have reached, by name: each must hold for some example the
 * run drew, given the example and what the predicate answered for it.
 */
export type Reaches<T, R> = Readonly<
  Record<string, (value: T, answered: R) => boolean>
>;

/**
 * Run a property: `predicate` must resolve for every value `arbitrary` draws.
 *
 * Throws with fast-check's own report when it does not, which prints the seed
 * and the shrunk counterexample as a literal, and with a sentence when the run
 * was interrupted or executed fewer examples than the profile.
 *
 * **And when the run reached nothing a `reaches` entry names.** A witness says
 * a generator can draw a class, at a seed of its own; this says the run that
 * just passed did, and that what it drew got as far as the property is about.
 * The second half is what a witness over the spec cannot see: a bomb behind a
 * header the reader refuses first is drawn, satisfies every predicate over the
 * spec, and reaches no inflater. So a reach is asked of what the predicate
 * answered, which for a reader is what the meter counted, and it follows the
 * run's own seed. Each is weighted so a run reaches it at any seed; a red here
 * names the seed, and is a generator or a door that stopped reaching its
 * subject, not bad luck worth a rerun.
 *
 * **Answers how many examples executed**, which each property's `it` asserts
 * is the profile's: `expect(await holds(...)).toBe(PROFILE.runs)`. The check
 * below already refuses fewer, so this is the arm saying so in its own body,
 * where a reader and the linter's rule that every test asserts both look.
 *
 * **Each example is announced before it runs**, `run <i>` from zero in the
 * order generated. Once one has failed, what follows is fast-check shrinking
 * it and is announced as `shrink <k>`: a shrunk value is not the `i`th of
 * anything, so `replay` cannot regenerate it, and the line does not pretend to
 * be one it could. The failing example's own `run` line is the one before the
 * first `shrink`.
 */
export async function holds<T, R = void>(
  arbitrary: fc.Arbitrary<T>,
  predicate: (value: T) => Promise<R>,
  reaches: Reaches<T, R> = {},
): Promise<number> {
  const configured = fc.readConfigureGlobal();
  if (Object.keys(configured).length > 0) {
    throw new Error(
      `fast-check has a global configuration (${Object.keys(configured).join(", ")}). ` +
        "Under isolate: false that reaches every later property in this " +
        "worker; only tests/property.ts sets what a property runs.",
    );
  }

  const seed = drawSeed();
  last = seed;
  progress(`property ${testName()} seed ${seed}`);
  let executed = 0;
  let shrinks = 0;
  let failed = false;
  const reached = new Set<string>();
  const details = await fc.check(
    fc.asyncProperty(arbitrary, async (value) => {
      if (failed) {
        progress(`shrink ${shrinks}`);
        shrinks += 1;
      } else {
        progress(`run ${executed}`);
        executed += 1;
      }
      let answered: R;
      try {
        answered = await predicate(value);
      } catch (error) {
        failed = true;
        throw error;
      }
      if (failed) return;
      for (const [name, reach] of Object.entries(reaches)) {
        if (!reached.has(name) && reach(value, answered)) reached.add(name);
      }
    }),
    { numRuns: PROFILE.runs, seed },
  );

  if (details.failed) {
    throw new Error(
      `${fc.defaultReportMessage(details)}\n\n` +
        "Land the counterexample above as a named it in this file, its input " +
        "that literal, asserting the exact answer, in the same commit as the " +
        "fix and never ahead of it. Do not pin the seed or the path. " +
        "docs/testing.md has the rule.",
      { cause: details.errorInstance },
    );
  }
  if (details.interrupted) {
    throw new Error(
      `the property was interrupted after ${details.numRuns} examples, ` +
        "and an interrupted run is not a pass",
    );
  }
  if (details.numRuns < PROFILE.runs || executed < PROFILE.runs) {
    throw new Error(
      `the property executed ${executed} examples and fast-check reports ` +
        `${details.numRuns}, against a profile of ${PROFILE.runs}: something ` +
        "lowered the run without changing a number this module passes",
    );
  }
  const missed = Object.keys(reaches).filter((name) => !reached.has(name));
  if (missed.length > 0) {
    throw new Error(
      `the property passed at seed ${seed} and drew no example that ` +
        `${missed.join(", nor any that ")}. A run that never reaches what ` +
        "the property is about passes over a generator, or a door, that " +
        "stopped reaching it; weight the class until any seed draws it.",
    );
  }
  return executed;
}

/**
 * The value a property drew as its `index`th example at `seed`: what the last
 * `run <i>` line before a kill names, regenerated rather than recovered.
 *
 * **The same values `holds` runs, and that is what makes this worth having.**
 * fast-check derives both from the seed and the example count, and
 * `tests/propertyBudget.test.ts` asserts the two agree rather than trusting it.
 */
export function replay<T>(
  arbitrary: fc.Arbitrary<T>,
  seed: number,
  index: number,
): T {
  return fc.sample(arbitrary, { numRuns: index + 1, seed })[index]!;
}

/**
 * That `arbitrary` draws each class `reaches` names, at a fresh seed of the
 * witness's own: as many values as a property runs, and for every entry at
 * least one satisfying it.
 *
 * **It asserts, and returns nothing**, which is the backend's
 * `strategies.witness` and the reason this is a call rather than a sampler: a
 * sampler handed back is a corpus a test can loop over under the floor, and a
 * call whose result nobody filters asserts nothing while being counted as a
 * witness. Throws naming the class that was not drawn and the seed it missed
 * at, which is the sentence a red here should read as.
 *
 * **A witness asserts a class appears at any seed, not at one**: a witness
 * that passes only at a chosen seed is a witness of that seed. What it says
 * about the gate is a rate rather than a guarantee: a property and its
 * witness draw independently. **What it cannot say is whether a drawn value
 * reached anything**, because it is asked of the value and never of the door;
 * that half is `holds`' `reaches`, which reads what the door did.
 *
 * A predicate may be asynchronous, so a class can be asked of the reader
 * rather than of the spec: whether a drawn document is one a reader reads is
 * the reader's to say. Values are asked in order and the asking stops once
 * every class has been seen.
 */
export async function witness<T>(
  arbitrary: fc.Arbitrary<T>,
  reaches: Readonly<Record<string, (value: T) => boolean | Promise<boolean>>>,
): Promise<void> {
  const names = Object.keys(reaches);
  if (names.length === 0) {
    throw new Error("a witness names no class, so it witnesses nothing");
  }
  const seed = drawSeed();
  progress(`witness ${testName()} seed ${seed}`);
  const missing = new Set(names);
  for (const value of fc.sample(arbitrary, { numRuns: PROFILE.runs, seed })) {
    for (const name of names) {
      if (missing.has(name) && (await reaches[name]!(value))) {
        missing.delete(name);
      }
    }
    if (missing.size === 0) return;
  }
  throw new Error(
    `at seed ${seed} the generator drew ${PROFILE.runs} values and none ` +
      `that ${[...missing].join(", nor any that ")}`,
  );
}

/**
 * One arbitrary per field of a spec, **total over the spec by type**.
 *
 * `Required` is the point: a field added to a spec as optional is a compile
 * error in its arbitrary, not a field the generator silently never draws. A
 * spec's overrides exist because a hostile input gets that field wrong on
 * purpose, so an override the generator skips is the dangerous shape. Written
 * as `fc.record({...} satisfies Total<Spec>)`.
 */
export type Total<Spec> = {
  readonly [K in keyof Required<Spec>]: fc.Arbitrary<Spec[K]>;
};

/**
 * An override, mostly absent. A real writer never sets one, so an input with
 * every field wrong at once tests the first check and nothing behind it.
 */
export function sometimes<T>(
  arbitrary: fc.Arbitrary<T>,
): fc.Arbitrary<T | undefined> {
  return fc.oneof(
    { arbitrary: fc.constant(undefined), weight: 3 },
    { arbitrary, weight: 1 },
  );
}

/**
 * One under a bound, the bound, and one over it: where an off by one lives,
 * in whatever unit the bound counts. `zipFixtures.around` adds a far atom in
 * bytes, for a bound a chunked inflater crosses.
 */
export function edges(bound: number): number[] {
  return [bound - 1, bound, bound + 1].filter((value) => value >= 0);
}

/**
 * Text with one part repeated, named rather than spelled.
 *
 * **Rule 4's text atom**: a string at a bound is hundreds or thousands of code
 * points, and a counterexample carrying it as a string prints as that string,
 * which `docs/testing.md` refuses to land. This prints as its four fields.
 * `zipFixtures.Zeroes` is the byte half, and lives with the byte builders.
 */
export interface Repeated {
  readonly before: string;
  readonly unit: string;
  readonly times: number;
  readonly after: string;
}

/**
 * Spelled `Repeated`s by identity. **Kept because an arbitrary hands back the
 * same constant on every draw**, and spelling a mebibyte of filler per example
 * is garbage a shared worker pays for at its peak.
 */
const SPELLED = new WeakMap<Repeated, string>();

/** The text a `Repeated` stands for. */
export function spelled(text: string | Repeated): string {
  if (typeof text === "string") return text;
  const known = SPELLED.get(text);
  if (known !== undefined) return known;
  const built = `${text.before}${text.unit.repeat(text.times)}${text.after}`;
  SPELLED.set(text, built);
  return built;
}

/**
 * The name of the method an arbitrary draws a value for itself by, which a
 * test may never reach: it is a run of a property at a random source of the
 * test's own. **Here so the guard refusing it names it without spelling it**,
 * since the guard reads its own source and refuses the name standing alone.
 */
export const DRAWS_FOR_ITSELF = "generate";

/**
 * Whether a string names the property generator or its random source as a
 * module: a specifier, or a path into `node_modules`.
 *
 * **One home for both guards that ask**, the house rule keeping it out of
 * `src/` and the door rule keeping its runners in this module, so a third
 * package joining it joins both. **The whole string is the name**: a
 * specifier from its start, or a path holding no space or quote. A sentence
 * or a fixture's source text that mentions the package is not a module
 * naming it, and the first version, which let a path sit anywhere in the
 * string, refused this guard's own rows.
 */
export function namesTheGenerator(value: string): boolean {
  return (
    /^(?:@fast-check\/|(?:fast-check|pure-rand)(?:\/|$))/.test(value) ||
    /^[^\s"'`]*?(?:^|[\\/])node_modules[\\/](?:@fast-check[\\/]|(?:fast-check|pure-rand)(?:[\\/]|$))[^\s"'`]*$/.test(
      value,
    )
  );
}

/**
 * Every name the installed fast-check exports, sorted.
 *
 * **Here because reading the namespace is a reference to it**, which the one
 * door rule refuses everywhere but this module. `tests/propertyBudget.test.ts`
 * pins the list by equality, so a version that adds a runner, a plugin or a
 * global reds once and somebody decides which side of the door it is on.
 */
export function fastCheckExports(): string[] {
  const names = Object.keys(fastCheck);
  names.sort();
  return names;
}
