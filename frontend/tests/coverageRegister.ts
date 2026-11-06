/**
 * What `COVERAGE.md` names, against what a run discovered and collected.
 *
 * The comparison only. Reading files and failing the run are the reporter's
 * job, so everything here is a function of two strings and a map, which is what
 * lets `coverageRegister.test.ts` drive it against censuses it made up.
 *
 * **A row is a glob, not a filename.** Several rows stand for a directory, and
 * every row is expanded before it is compared. **No row states a count**: a
 * count moved on every branch that added a test and nobody read it, so the run
 * prints its own.
 */

import { writeSync } from "node:fs";

/**
 * A row: a backticked pattern alone in the first cell.
 *
 * Read inside that cell, so a pattern quoted in a description is not a row of
 * its own.
 */
const ROW = /^\|[ \t]*`([^`]+)`[ \t]*\|/gm;

/**
 * The declaration the publish gate demands of an internal file and refuses to
 * publish, with the window it reads.
 *
 * Spelled here as well as in the backend's own census because this tree cannot
 * import that one, and because a published file may not read the gate's script
 * to learn either. Both halves are the gate's, transcribed: the anchor allows a
 * short run of non alphanumerics, so a comment or a list marker in front of the
 * sentence still counts. **The one copy in this tree**: `houseRules.test.ts`
 * imports it, and pins the window there.
 *
 * **A wrong window is quiet rather than loud.** A narrower one keeps a
 * document whose declaration sits below it; a wider one drops a document that
 * merely discusses the convention, which is what the gate's bound protects.
 */
const DECLARES_ITSELF_INTERNAL =
  /^[^A-Za-z0-9]{0,6}[ \t]*\*\*This file is internal\.\*\*/m;
export const HEADER_LINES = 30;

/** Whether `source` declares itself internal within the gate's window, in lines. */
export function declaresItselfInternal(source: string): boolean {
  return DECLARES_ITSELF_INTERNAL.test(
    source.split("\n").slice(0, HEADER_LINES).join("\n"),
  );
}

export interface Census {
  /**
   * Every test file vitest discovered, whether or not this run executed it.
   *
   * **The rules about which files the document names are asked of this**,
   * because whether every file in the tree has a row does not depend on
   * running any of them, so a narrowed run still checks it.
   */
  discovered: ReadonlySet<string>;
  /** Tests the run collected, per file it executed, relative to the test root. */
  counts: ReadonlyMap<string, number>;
  /**
   * The files this published register may not name.
   *
   * Empty today: no frontend test file is on the publish gate's strip list. It
   * exists because the backend register has such files, and without it the two
   * gates contradict each other on the day the first one appears here, this
   * file demanding a row for a file the publish gate refuses to let it name.
   */
  internal: ReadonlySet<string>;
  /**
   * Each test this run collected and did not run, or ran expecting it to
   * fail, as `file > full name (why)`.
   *
   * **Empty on a run vitest narrowed inside a file**, by a name pattern, a
   * line, a test id, a tag or a focus: vitest marks the tests its filter left
   * out exactly as it marks `it.skip`, so such a run cannot tell the two
   * apart. The reporter decides that and leaves this empty.
   */
  wouldNotRun: readonly string[];
}

/** Every row's pattern, in the document's own order. */
export function rowsOf(register: string): string[] {
  return [...register.matchAll(ROW)].flatMap(([, pattern]) =>
    pattern ? [pattern] : [],
  );
}

/** Whether a row's pattern covers a file. `*` crosses directories. */
export function covers(pattern: string, file: string): boolean {
  const expanded = pattern
    .split("*")
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${expanded}$`).test(file);
}

/**
 * Which rows cover each file the register is allowed to describe.
 *
 * A file it may not name is outside this map altogether, so it is never
 * reported as undescribed. That a row covers one anyway is a separate problem,
 * reported on its own.
 *
 * **Over what vitest discovered, not over what this run executed.** Keyed on
 * `counts` it was empty of every file a narrowed run skipped, so the row rules
 * read a tree of whatever size the command line asked for and found nothing
 * wrong with it.
 */
export function matched(
  census: Census,
  patterns: string[],
): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of census.discovered)
    if (!census.internal.has(file))
      found.set(
        file,
        patterns.filter((pattern) => covers(pattern, file)),
      );
  return found;
}

/** One thing this run says the register, or the tree under it, has wrong. */
export type Finding =
  | { kind: "patternMatchesNothing"; pattern: string }
  | { kind: "fileMatchedBySeveralRows"; file: string; patterns: string[] }
  | { kind: "internalFileCovered"; file: string }
  | { kind: "filesWithNoRow"; files: string[] }
  | { kind: "fileCollectsNothing"; file: string }
  | { kind: "testsThatWouldNotRun"; tests: readonly string[] };

/**
 * Everything this run says the register has wrong, in the order it is read.
 *
 * A list rather than the first failure, because what a person needs when a wave
 * lands is every row that is wrong, not the alphabetically first one.
 */
export function findings(register: string, census: Census): Finding[] {
  const patterns = rowsOf(register);
  const hits = matched(census, patterns);
  const found: Finding[] = [];

  for (const pattern of patterns)
    if (
      ![...hits.values()].some((patternsHit) => patternsHit.includes(pattern))
    )
      found.push({ kind: "patternMatchesNothing", pattern });

  for (const [file, patternsHit] of hits)
    if (patternsHit.length > 1)
      found.push({
        kind: "fileMatchedBySeveralRows",
        file,
        patterns: patternsHit,
      });

  for (const file of census.internal)
    if (patterns.some((pattern) => covers(pattern, file)))
      found.push({ kind: "internalFileCovered", file });

  // **Named, never absorbed into a count.** A figure for the files nothing
  // describes is satisfied by any file, so a new one lands by editing a digit;
  // this way the only two answers are a row or a deliberate deletion.
  const unnamed = [...hits]
    .filter(([, patternsHit]) => patternsHit.length === 0)
    .map(([file]) => file);
  if (unnamed.length > 0)
    found.push({ kind: "filesWithNoRow", files: unnamed });

  // **A belt behind vitest's own rule, and armed by a unit arm rather than by
  // the tree.** vitest fails a file with no test unless `passWithNoTests` is
  // set, so on this config a file that ran collected at least one; this is
  // what still says so the day that option is turned on. Asked of the files
  // that ran, so a narrowed run judges what it executed and nothing else.
  for (const [file, count] of census.counts)
    if (count === 0) found.push({ kind: "fileCollectsNothing", file });

  // **The twin of the backend's marker arm.** A file whose every test is
  // skipped still collects them, so the rule above passes it; this is what
  // closes that. Read off the run's own results rather than off the source, so
  // `skipIf`, `runIf`, `ctx.skip()`, a skipped block and a runner reached
  // through a local name are one rule, where oxlint's `no-disabled-tests`
  // reads only the direct spellings.
  if (census.wouldNotRun.length > 0)
    found.push({ kind: "testsThatWouldNotRun", tests: census.wouldNotRun });

  return found;
}

/** One finding as the line a person reads. */
function sentence(finding: Finding): string {
  switch (finding.kind) {
    case "patternMatchesNothing":
      return `\`${finding.pattern}\` matches no file in this test tree`;
    case "fileMatchedBySeveralRows":
      return `${finding.file} is matched by ${finding.patterns.length} rows (${finding.patterns.join(", ")}), so two descriptions of it can drift apart`;
    case "internalFileCovered":
      return (
        `${finding.file} declares itself internal, so the publish gate strips it and a ` +
        "row naming it fails that gate, but a row covers it"
      );
    case "filesWithNoRow":
      return (
        `these files have no row: ${finding.files.join(", ")}. A row says what the file ` +
        "covers."
      );
    case "fileCollectsNothing":
      return `${finding.file} collected no test, so a row describing it describes nothing that runs`;
    case "testsThatWouldNotRun":
      return (
        `these tests are collected and would not run: ${finding.tests.join(", ")}. ` +
        "A skipped, todo or expected to fail test reads as coverage it does not " +
        "give; make it run or delete it"
      );
  }
}

/**
 * Everything this run says the register has wrong, one line each.
 */
export function problems(register: string, census: Census): string[] {
  return findings(register, census).map(sentence);
}

/**
 * How long the printer waits with no byte moving before it fails the run.
 *
 * **A reader that has stopped reading would otherwise be a lost refusal, and
 * this makes it a loud one.** Measured 2026-10-08: in the suite container an
 * 800,000 byte line needed 12 pauses of 1 ms in all, and on a development
 * machine an 801,461 byte line into a reader that slept a second before
 * reading was whole after under 200 pauses of 5 ms. A gap of thirty seconds
 * with nothing moving is a stall rather than a slow reader. It must stay well
 * under any time limit a caller puts on a suite run, the shortest of which is
 * minutes, so the run fails here with the reason rather than being killed
 * with none.
 */
export const STALLED_FOR = 30_000;

/**
 * How long the printer sleeps after the pipe refuses a byte, before trying
 * again.
 *
 * **It is the latency added per refill**: about this long passes between
 * the reader draining and the next write, since `Atomics.wait` sleeps at
 * least its timeout rather than at most. Each pause costs one thrown
 * `EAGAIN`, so a whole stall of `STALLED_FOR` is about thirty thousand of
 * them, which is cheap against a run that is failing anyway.
 */
export const PAUSE_MS = 1;

/**
 * Print one line, and return only once the kernel holds every byte of it.
 *
 * **Not `console.log` and not the stream, and both are measured.** vitest's own
 * logger touches `process.stdout` before any reporter runs, and bun then marks
 * the pipe non blocking, on the open file description every later writer in
 * that session shares. `console.log` then keeps what the pipe takes at once
 * and drops the rest without an error. Awaiting the stream's write callback
 * was whole in one full run of two and lost its last 10,937 bytes in the
 * other. Turning this back into either returns a cut refusal, which is a
 * reason a person cannot read.
 *
 * **So it loops on `EAGAIN` until the kernel has taken every byte**, which
 * leaves nothing in any buffer of this process to lose when the run exits.
 * Every other error is thrown: a reader that closed (`EPIPE`) is a write that
 * can never arrive, and retrying it would spin until the deadline instead of
 * saying so.
 *
 * **Synchronous on purpose**: nothing else in this process runs while the
 * loop does, so no output of this process lands inside the line. **Another
 * process writing to the same descriptor is not excluded.** vitest 5 forks its
 * workers with their output piped back through this process, so none of them
 * can; a process this one starts with inherited output, or a changed pool
 * setting, could.
 *
 * **The deadline needs a non blocking descriptor to fire.** On a blocking one
 * the kernel holds the call itself until the reader drains, which is whole and
 * cannot be timed out from here. A run's pipe is non blocking by the time a
 * reporter runs, which is why the stall is reachable at all.
 */
export function printWhole(
  line: string,
  fd = 1,
  stalledFor = STALLED_FOR,
): void {
  const bytes = Buffer.from(`${line}\n`);
  const pause = new Int32Array(new SharedArrayBuffer(4));
  let written = 0;
  let moved = Date.now();
  while (written < bytes.length) {
    let took = 0;
    try {
      took = writeSync(fd, bytes, written, bytes.length - written);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EAGAIN") throw error;
    }
    if (took > 0) {
      written += took;
      moved = Date.now();
      continue;
    }
    if (Date.now() - moved > stalledFor)
      throw new Error(
        `the coverage register's print stalled: ${written} of ${bytes.length} ` +
          `bytes reached the reader and none moved for ${stalledFor} ms, so ` +
          "the run fails here rather than ending with half a refusal.",
      );
    Atomics.wait(pause, 0, 0, PAUSE_MS);
  }
}

/** The line every refusal of this guard opens with on standard error. */
export const REFUSED = "the coverage register refused this run:";

/**
 * A refusal of this guard, printed by the guard itself and then returned to
 * throw.
 *
 * **Printed here because how vitest prints a thrown error is vitest's, not
 * ours.** A reporter's throw arrives as an Unhandled Error and a global
 * setup's through vitest's `close()`, each rendered by the runner and by
 * whatever stack formatter is installed when it reads the error, and one full
 * run in three once printed a teardown stack where the text should have been.
 * The throw still fails the run; what reaches a person is this print, whole,
 * under `REFUSED`, which is what `coverageRegister.test.ts` reads off a nested
 * run's standard error.
 *
 * `fd` is for the arms that drive the reporter in process, where standard
 * error is the outer run's own log and a refusal there would read as one of
 * the run's. **Every `throw` in the reporter and the global setup throws a
 * call to this function**, held by an arm over both files.
 */
export function refusal(message: string, fd = 2): Error {
  printWhole(`${REFUSED}\n${message}`, fd);
  return new Error(message);
}
