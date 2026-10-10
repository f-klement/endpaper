/**
 * @vitest-environment node
 *
 * The register guard, and the one thing a unit test cannot say about it: that
 * being wired into the config it is wired into actually fails a run.
 */
import { spawnSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdtempSync,
  openSync,
  readFileSync,
  mkdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseAst } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  BEGIN,
  END,
  type Census,
  REGISTER_PATH,
  WRITE_SENTINEL,
  blockOf,
  countWrittenOut,
  covers,
  isWhole,
  problems,
  render,
  rowsOf,
  writeInstruction,
  writeLine,
} from "./coverageRegister";
import {
  MARKER,
  registerReading,
  teardown,
} from "./coverageRegister.globalSetup";
import CoverageRegisterReporter, { SWITCH } from "./coverageRegister.reporter";

/**
 * A census this file made up.
 *
 * `discovered` defaults to the files that ran, which is what a whole run has.
 * Pass it to make a narrowed one, where the counts cannot be compared and the
 * rules about which files the document names still can.
 */
const census = (
  counts: Record<string, number>,
  writtenOut: Record<string, number> = counts,
  internal: string[] = [],
  discovered: string[] = Object.keys(counts),
): Census => ({
  discovered: new Set(discovered),
  counts: new Map(Object.entries(counts)),
  writtenOut: new Map(Object.entries(writtenOut)),
  internal: new Set(internal),
});

/**
 * Whether a line carries anything a person could read.
 *
 * **Lifted out of the filter it came from so that one arm holds it at no spawn
 * cost.** Inside `refusedLines` this predicate was at rung "stated": no refusal
 * this register throws has a whitespace only line, measured over every shape, so
 * arming it there would have meant making a child throw one, which is another
 * nested vitest for a guard on a guard. Here it is a pure function and the arm
 * below is free.
 *
 * `trim`, not a comparison against the empty string: `"\n \n"` splits to one
 * line of a single space, which passes a length check and is contained in any
 * stderr at all, so the readability pair would go green over nothing.
 */
const carriesText = (line: string): boolean => line.trim() !== "";

const registerFor = (body: Census, rows: [string, number][]): string =>
  [
    "# Coverage",
    "",
    BEGIN +
      render(
        body,
        rows.map(([pattern]) => pattern),
      ) +
      END,
    "",
    "| File | Tests | Covers |",
    "| --- | ---: | --- |",
    ...rows.map(
      ([pattern, stated]) => `| \`${pattern}\` | ${stated} | What it covers |`,
    ),
    "",
  ].join("\n");

/**
 * The plant harness's switch, cleared for this file and put back after it.
 *
 * **This file drives the reporter itself**, in process and through nested
 * runs that inherit this environment, so its arms are about the register
 * whether or not the outer run checks it. Left set, the arms needing the
 * reporter to speak went red on a plant baseline.
 */
let switchWas: string | undefined;
beforeAll(() => {
  switchWas = process.env[SWITCH];
  delete process.env[SWITCH];
});
afterAll(() => {
  if (switchWas !== undefined) process.env[SWITCH] = switchWas;
});

describe("reading the document", () => {
  it("reads a row whose columns are padded", () => {
    expect(rowsOf("| `lib/zip.test.ts`   |    50 | The zip seam |\n")).toEqual([
      { pattern: "lib/zip.test.ts", stated: 50 },
    ]);
  });

  it("does not read a number in the third column as the count", () => {
    expect(
      rowsOf("| `lib/pdf.test.ts` | 53 | 39 of 123 real files |\n"),
    ).toEqual([{ pattern: "lib/pdf.test.ts", stated: 53 }]);
  });

  it("reads no row out of a table whose first cell is not a path", () => {
    expect(rowsOf("| File | Tests | Covers |\n| --- | ---: | --- |\n")).toEqual(
      [],
    );
  });

  it("refuses a register with no measured block", () => {
    expect(() => blockOf("# Coverage\n\nNothing fenced here.\n")).toThrow(
      /no measured block/,
    );
  });
});

/**
 * The plant harness's switch, driven in process with the pipeline's own
 * variable as given. A run of `ran` over a discovery of `found`, both real
 * files here, whose sources the reporter reads.
 */
const underTheSwitch = async (
  found: string[],
  ran: string[],
  pipeline: string | undefined,
): Promise<{ thrown: unknown; said: string }> => {
  const frontend = join(import.meta.dirname, "..");
  const sink = mkdtempSync(join(tmpdir(), "register-switch-"));
  const out = openSync(join(sink, "out"), "w");
  const reporter = new CoverageRegisterReporter({ out });
  reporter.onInit({
    projects: [
      {
        config: { root: frontend },
        globTestFiles: () => Promise.resolve({ testFiles: found }),
      },
    ],
  });
  const pipelineWas = process.env.GITLAB_CI;
  if (pipeline === undefined) delete process.env.GITLAB_CI;
  else process.env.GITLAB_CI = pipeline;
  process.env[SWITCH] = "off";

  let thrown: unknown;
  try {
    await reporter.onTestRunEnd(
      ran.map((moduleId) => ({
        moduleId,
        children: { allTests: () => [1] },
      })),
      [],
      "passed",
    );
  } catch (error) {
    thrown = error;
  } finally {
    delete process.env[SWITCH];
    if (pipelineWas === undefined) delete process.env.GITLAB_CI;
    else process.env.GITLAB_CI = pipelineWas;
    closeSync(out);
  }
  const said = readFileSync(join(sink, "out"), "utf8");
  rmSync(sink, { recursive: true });
  return { thrown, said };
};

const testFile = (file: string) => join(import.meta.dirname, file);

/**
 * The write a run offers, which is the whole of what a deliberate write
 * applies.
 *
 * **Every arm here is about the write being the check's own figures.** A
 * writer that counted this suite a second way would be a second instrument,
 * and a second instrument agrees with the first on almost every tree: the run
 * where the two disagree is the run nobody is watching. So the write is read
 * off the same findings the reporter prints, and the thing that applies it
 * replaces bytes and computes nothing.
 */
describe("the write a run offers", () => {
  it("offers nothing when the register already agrees with the run", () => {
    const body = census({ "a.test.ts": 4 });

    expect(writeInstruction(registerFor(body, [["a.test.ts", 4]]), body)).toBe(
      null,
    );
  });

  it("offers the row as the line the document has and the line to put there", () => {
    const body = census({ "a.test.ts": 7 });
    const register = registerFor(body, [["a.test.ts", 4]]);

    expect(writeInstruction(register, body)?.lines).toEqual([
      [
        "| `a.test.ts` | 4 | What it covers |",
        "| `a.test.ts` | 7 | What it covers |",
      ],
    ]);
  });

  it("writes the block the reporter compares against and no other", () => {
    const body = census({ "a.test.ts": 4 });
    const register = registerFor(body, [["a.test.ts", 4]]).replace(
      "**4 tests",
      "**400 tests",
    );

    expect(writeInstruction(register, body)?.block).toBe(
      render(body, ["a.test.ts"]),
    );
  });

  it("leaves a sentence carrying its own numbers alone", () => {
    const body = census({ "a.test.ts": 7 });
    const register = registerFor(body, [["a.test.ts", 4]]).replace(
      "What it covers",
      "12 shapes, and the 3 that are not",
    );

    expect(writeInstruction(register, body)?.lines).toEqual([
      [
        "| `a.test.ts` | 4 | 12 shapes, and the 3 that are not |",
        "| `a.test.ts` | 7 | 12 shapes, and the 3 that are not |",
      ],
    ]);
  });

  it("offers nothing at all from a run that took fewer files than the tree has", () => {
    // A narrowed run can say nothing about any count, so it has no write. The
    // rules it can still ask are reported rather than applied, and drawing
    // that line inside the write is what stops a caller reaching around it.
    const body = census(
      { "a.test.ts": 1 },
      { "a.test.ts": 1 },
      [],
      ["a.test.ts", "b.test.ts"],
    );

    expect(writeInstruction(registerFor(body, [["a.test.ts", 9]]), body)).toBe(
      null,
    );
  });

  it("refuses rather than writes when a row names nothing in the tree", () => {
    const body = census({ "a.test.ts": 4 });
    const register = registerFor(body, [
      ["a.test.ts", 4],
      ["gone.test.ts", 2],
    ]);

    const instruction = writeInstruction(register, body);

    expect(instruction?.lines).toEqual([]);
    expect(instruction?.refused).toEqual([
      "`gone.test.ts` matches no file in this test tree",
    ]);
  });

  it("refuses when the written out instrument saw more than the run did", () => {
    // The block calls a file generating when the two figures differ, which is
    // also true when written out is the larger. Writing the block then
    // publishes a sentence that is false in a way no row shows.
    const body = census({ "a.test.ts": 4 }, { "a.test.ts": 6 });

    const instruction = writeInstruction(
      registerFor(body, [["a.test.ts", 4]]),
      body,
    );

    expect(instruction?.lines).toEqual([]);
    expect(instruction?.refused.join()).toContain(
      "6 written out against 4 collected",
    );
    // **And no block, which is what keeps a minus sign out of one.** This is
    // the only state in which the generated figure goes negative, and the
    // applier refuses a block holding `-`, so a block written here would be a
    // write refused at merge rather than a figure published.
    expect(instruction?.block).toBeNull();
  });

  it("refuses when one file is summed into two rows", () => {
    const body = census({ "lib/a.test.ts": 4 });
    const register = registerFor(body, [
      ["lib/a.test.ts", 4],
      ["lib/*", 4],
    ]);

    expect(writeInstruction(register, body)?.refused.join()).toContain(
      "is matched by 2 rows",
    );
  });

  it("writes the figures even while a file is still owed a sentence", () => {
    // A file with no row needs prose a run cannot write, and the rule saying
    // so stays red until a person writes it. The figures around it are still
    // this run's own, so refusing the whole register would make a wave's
    // ordinary case unwritable.
    const body = census({ "a.test.ts": 4, "b.test.ts": 2 });
    const register = registerFor(body, [["a.test.ts", 9]]);

    const instruction = writeInstruction(register, body);

    expect(instruction?.refused).toEqual([]);
    expect(instruction?.lines).toEqual([
      [
        "| `a.test.ts` | 9 | What it covers |",
        "| `a.test.ts` | 4 | What it covers |",
      ],
    ]);
  });

  it("travels as one line and arrives unchanged", () => {
    const body = census({ "a.test.ts": 7 });
    const instruction = writeInstruction(
      registerFor(body, [["a.test.ts", 4]]),
      body,
    );
    if (instruction === null)
      throw new Error("this register is stale by one row");

    const line = writeLine(instruction);

    expect(line).not.toContain("\n");
    expect(line.startsWith(`${WRITE_SENTINEL} `)).toBe(true);
    expect(JSON.parse(line.slice(WRITE_SENTINEL.length + 1))).toEqual(
      instruction,
    );
  });

  it("names the register this tree actually has", () => {
    // **Resolved paths, not file contents.** The backend half of this rule
    // compares paths; comparing bytes is a weaker instrument for the same
    // claim, because two different documents with the same contents pass it
    // and the thing being checked is which document a write lands in.
    const named = join(import.meta.dirname, "..", "..", REGISTER_PATH);

    expect(named).toBe(join(import.meta.dirname, "COVERAGE.md"));
    // Anti vacuity: a derivation that resolved to nothing would satisfy an
    // equality against another derivation of the same nothing.
    expect(existsSync(named)).toBe(true);
  });

  /**
   * The gate's permission, which had no witness at all.
   *
   * **Planting the gate permanently closed left all 64 arms green at exit
   * zero.** Both assertions about the sentinel on a stream are negative and
   * every other arm calls the renderer directly, so nothing anywhere said a
   * write is ever offered. A vitest change or a root flag would have ended
   * the write path forever in silence, and the applier would then have said
   * there is no write and repeated its ambiguity sentence, which reads as
   * the other register being current.
   *
   * So this drives the real reporter's real hook with this repository's own
   * project root and requires a write on the stream. It is the one arm that
   * reds when the gate closes.
   *
   * **What it still cannot witness**, and this is the honest residue: that
   * the configuration names this reporter, and that vitest hands it this
   * project. A suite cannot watch its own wiring from inside itself. The
   * global setup's marker is what covers the first of those, by a different
   * route, and nothing covers the second.
   */
  it("offers a write when the run is about this repository's register", async () => {
    const frontend = join(import.meta.dirname, "..");
    const ran = join(import.meta.dirname, "withoutProse.test.ts");
    // **A file, never this worker's standard output**, which is the run's
    // artefact too: printed there, this arm's one file write was a real
    // write in the artefact, refusing every row.
    const sink = mkdtempSync(join(tmpdir(), "register-witness-"));
    const out = openSync(join(sink, "out"), "w");
    const reporter = new CoverageRegisterReporter({ out });
    reporter.onInit({
      projects: [
        {
          config: { root: frontend },
          globTestFiles: () => Promise.resolve({ testFiles: [ran] }),
        },
      ],
    });

    try {
      await reporter.onTestRunEnd(
        [{ moduleId: ran, children: { allTests: () => [1] } }],
        [],
        "passed",
      );
    } catch {
      // The register does not describe a run of one file, so the reporter
      // throws after printing. The throw is another arm's subject; the
      // printing is this one's.
    } finally {
      closeSync(out);
    }
    const said = readFileSync(join(sink, "out"), "utf8");
    rmSync(sink, { recursive: true });

    expect(said).toContain(WRITE_SENTINEL);
  });

  /**
   * The run below is one the register does not describe, so with the switch
   * on this same call throws, which the arm above relies on; off, it neither
   * throws nor offers a write.
   */
  it("reads no document and offers no write when the switch is off", async () => {
    const ran = [testFile("withoutProse.test.ts")];
    const { thrown, said } = await underTheSwitch(ran, ran, undefined);

    expect(thrown).toBeUndefined();
    expect(said).not.toContain(WRITE_SENTINEL);
  });

  it("still refuses a run that is not the discovered one when the switch is off", async () => {
    const { thrown } = await underTheSwitch(
      [testFile("withoutProse.test.ts"), testFile("licence.test.ts")],
      [testFile("withoutProse.test.ts"), testFile("storageRefusal.test.ts")],
      undefined,
    );

    expect(String(thrown)).toContain(
      "licence.test.ts was discovered and did not run",
    );
  });

  it("fails rather than skips when the switch is off in a pipeline", async () => {
    const ran = [testFile("withoutProse.test.ts")];
    const { thrown } = await underTheSwitch(ran, ran, "true");

    expect(String(thrown)).toContain(`${SWITCH}=off is for a plant copy`);
  });

  it("distinguishes a register from no register", () => {
    // The diagonal the backend reading has and this one did not. A reading
    // answering one constant would satisfy every refusal by never moving,
    // and the absent case is unreachable in this tree today, which is what
    // makes an arm the only thing that would catch it becoming reachable.
    expect(registerReading(join(import.meta.dirname, "no-such-file.md"))).toBe(
      "absent",
    );
    expect(registerReading(join(import.meta.dirname, "COVERAGE.md"))).not.toBe(
      "absent",
    );
  });
});

/** Past several pipe buffers, which is what a register write reaches. */
const LINE = 1 << 20;

/**
 * What a shell line puts in front of a child, so that no mutant of the
 * printer can hang the suite. A printer that retries every error and has no
 * deadline spins on `EPIPE` forever, and a `spawnSync` timeout would kill the
 * shell by pid and leave the child behind.
 *
 * **`KILL`, not the default `TERM`.** Measured in the suite container: such
 * a mutant outlived a plain `timeout 25` by twenty minutes and held the run,
 * and the node, the whole time. The same line on a development machine
 * ended it at the bound, so why the signal was lost there is not known;
 * `KILL` cannot be caught, ignored or deferred, which is the property this
 * needs whatever the cause.
 */
const BOUNDED = "timeout -s KILL 25";

/**
 * A bun child that prints through the real printer, on a pipe it has first
 * confirmed is non blocking, then runs `body`, with the child's `line` set to
 * the expression given.
 *
 * **Driven in a child because the loss is a property of the process, not of
 * the string.** Once a bun process touches `process.stdout` its pipe is non
 * blocking, and every printer this replaced was whole on a blocking one.
 *
 * **So the child refuses to print when its pipe is still blocking**, exiting 3
 * with a sentence: on a blocking pipe the first arm and the slow reader arm
 * would pass with their subjects deleted, and the stall arm would red for a
 * reason that is not its own. A bun that stops marking the pipe is a reason to revisit them,
 * not to keep them, and this reads `/proc`, so a suite run off Linux reds
 * here.
 */
function printerChild(
  body: string[],
  line = `"x".repeat(${String(LINE)})`,
): string {
  const printer = join(import.meta.dirname, "coverageRegister.ts");
  return [
    `import { readFileSync, writeFileSync } from "node:fs";`,
    `import { printWhole } from ${JSON.stringify(printer)};`,
    `process.stdout.write("");`,
    `const fd = readFileSync("/proc/self/fdinfo/1", "utf8");`,
    `const flags = /flags:\\s+([0-7]+)/.exec(fd);`,
    `if (!flags || (parseInt(flags[1], 8) & 0o4000) === 0) {`,
    `  process.stderr.write("standard output is blocking, so nothing here can be cut");`,
    `  process.exit(3);`,
    `}`,
    `const line = ${line};`,
    ...body,
  ].join("\n");
}

describe("the printer a write travels through", () => {
  /**
   * **The child kills itself the moment the call returns**, with a signal
   * nothing can flush on. What survives is only what the kernel already
   * holds, which is the property the reporter needs and the one a printer
   * returning before its bytes are written cannot have, however it waits.
   * A printer awaiting the stream's write callback was whole in one full
   * run of two and lost its last 10,937 bytes in the other. No child
   * reproduced that loss, so this arm does not chase it; it asks for the
   * property that rules it out.
   *
   * **The line is three byte characters, counted in bytes**, because a
   * printer advancing through a string by the bytes the pipe took is whole
   * on ASCII and cut on anything else: such a printer passed this arm on a
   * line of `x` and delivered a third of this one. A register's cells are
   * prose a person wrote, so the first one past ASCII would be that cut.
   */
  it("is whole in the pipe when the printer returns", () => {
    const expected = Buffer.from(`${"\u2026".repeat(LINE / 2)}\n`);
    const run = spawnSync(
      process.execPath,
      [
        "-e",
        printerChild(
          [`printWhole(line);`, `process.kill(process.pid, "SIGKILL");`],
          `"\\u2026".repeat(${String(LINE / 2)})`,
        ),
      ],
      { maxBuffer: 1 << 24, timeout: 25_000, killSignal: "SIGKILL" },
    );

    expect(run.stderr.toString()).toBe("");
    expect(run.signal).toBe("SIGKILL");
    expect(run.stdout.length).toBe(expected.length);
    expect(run.stdout.equals(expected)).toBe(true);
  });

  /**
   * **A reader that closed is a write that can never arrive**, and only
   * `EAGAIN` is worth retrying. A printer that retried everything would spin
   * here until its deadline and then report a stall that never happened,
   * which is the wrong reason for the right failure.
   *
   * `true` closes the pipe's read end by exiting, so the child's write meets
   * `EPIPE` whether it starts before or after that.
   */
  it("throws on a reader that has closed rather than retrying", () => {
    const run = spawnSync(
      "sh",
      [
        "-c",
        `${BOUNDED} "$0" -e "$1" | true`,
        process.execPath,
        printerChild([
          `try {`,
          `  printWhole(line, 1, 2000);`,
          `  process.stderr.write("returned");`,
          `} catch (error) {`,
          `  process.stderr.write("threw " + String(error.code));`,
          `}`,
        ]),
      ],
      { encoding: "utf8" },
    );

    expect(run.stderr).toBe("threw EPIPE");
  });

  /**
   * **A reader that stays open and never reads is the silent loss this
   * deadline makes loud.** The reader here is a loop that never touches its
   * input and leaves once the child says it is done, so the arm costs at most
   * a second past the deadline.
   *
   * **The reader leaves after twenty seconds whatever the child does**, and
   * the child is bounded as the arm above bounds it. A printer with no
   * deadline then meets `EPIPE` when the reader goes, and the arm reds on
   * the reason.
   */
  it("fails the run when no byte moves for the deadline", () => {
    const dir = mkdtempSync(join(tmpdir(), "register-stall-"));
    const done = join(dir, "done");
    const run = spawnSync(
      "sh",
      [
        "-c",
        `${BOUNDED} "$0" -e "$1" | (i=0; until [ -e "$2" ] || [ $i -ge 20 ]; do sleep 1; i=$((i + 1)); done)`,
        process.execPath,
        printerChild([
          `try {`,
          `  printWhole(line, 1, 200);`,
          `  process.stderr.write("returned");`,
          `} catch (error) {`,
          `  process.stderr.write(String(error.message));`,
          `} finally {`,
          `  writeFileSync(${JSON.stringify(done)}, "");`,
          `}`,
        ]),
        done,
      ],
      { encoding: "utf8" },
    );
    rmSync(dir, { recursive: true });

    expect(run.stderr).toMatch(
      new RegExp(
        `stalled: \\d+ of ${String(LINE + 1)} bytes .* none moved for 200 ms`,
      ),
    );
  });

  /**
   * **The deadline is a gap with nothing moving, not a limit on the whole
   * write.** A reader that keeps draining, slowly, is a reader the printer
   * must wait for. Here it takes 32 KiB every 100 ms, so the line takes
   * about three seconds to drain against a deadline of one, and no gap
   * comes near it. A deadline measured from the start of the write fails
   * this reader at one second, saying no byte moved while bytes were moving.
   *
   * The reader stops at the line's length or at the end of its input, and
   * both children are bounded as the arms above bound them.
   */
  it("waits on a reader that is slow and never stops", () => {
    const reader = [
      `import { readSync } from "node:fs";`,
      `const pause = new Int32Array(new SharedArrayBuffer(4));`,
      `const chunk = Buffer.alloc(32768);`,
      `let total = 0;`,
      `while (total < ${String(LINE + 1)}) {`,
      `  Atomics.wait(pause, 0, 0, 100);`,
      `  const took = readSync(0, chunk, 0, chunk.length, null);`,
      `  if (took === 0) break;`,
      `  total += took;`,
      `}`,
      `process.stdout.write(String(total));`,
    ].join("\n");
    const run = spawnSync(
      "sh",
      [
        "-c",
        `${BOUNDED} "$0" -e "$1" | ${BOUNDED} "$0" -e "$2"`,
        process.execPath,
        printerChild([
          `try {`,
          `  printWhole(line, 1, 1000);`,
          `  process.stderr.write("returned");`,
          `} catch (error) {`,
          `  process.stderr.write(String(error.message));`,
          `}`,
        ]),
        reader,
      ],
      { encoding: "utf8" },
    );

    expect(run.stderr).toBe("returned");
    expect(run.stdout).toBe(String(LINE + 1));
  });
});

describe("what counts as a line carrying something", () => {
  it("keeps a line with text and drops every whitespace only one", () => {
    expect(["a refusal", "", " ", "\t", "  \t "].filter(carriesText)).toEqual([
      "a refusal",
    ]);
  });
});

describe("counting what a file writes out", () => {
  const ts = (source: string) => countWrittenOut(source, "a.test.ts");

  it("does not count a call written inside a string literal", () => {
    expect(ts(`const fixture = "it('one', () => {});";\n`)).toBe(0);
  });

  it("does not count a call written inside a comment", () => {
    expect(
      ts("// it('once', () => {});\n/* test('twice', () => {}) */\n"),
    ).toBe(0);
  });

  it("counts a call inside a template substitution, which is code", () => {
    expect(ts('const x = `${it("a", () => {})}`;\n')).toBe(1);
  });

  it("leaves a generated case out, so it falls to the residual", () => {
    expect(ts("it.each([1, 2])('case %d', () => {});\n")).toBe(0);
  });

  it("counts the `test` spelling of the pair as well as `it`", () => {
    // Without this the `test` half is at rung "stated" inside the one function
    // whose subject is the pair: dropping it from the name check moves no figure,
    // because a bare `test(` call appears nowhere in the 198 files this counts.
    expect(ts("test('a', () => {});\n")).toBe(1);
  });

  it("reads a file named .tsx as JSX rather than as TypeScript", () => {
    const source = `const prose = <p>don't</p>;\nit("after", () => {});\n`;

    expect(countWrittenOut(source, "a.test.tsx")).toBe(1);
  });

  it("reads a file named .ts as TypeScript rather than as JSX", () => {
    // The other direction, and the one the arm above cannot hold. Forcing `"ts"`
    // breaks 119 of the 198 files and is caught by any of them; forcing `"tsx"`
    // breaks none, so `langOf` was armed one way only. A prefix type assertion
    // is the syntax the two grammars disagree about: `tsx` reads `<number>` as a
    // tag that is never closed.
    const cast = "const n = <number>(x as unknown);\nit('a', () => {});\n";

    expect(countWrittenOut(cast, "a.test.ts")).toBe(1);
    expect(() => countWrittenOut(cast, "a.test.tsx")).toThrow(/a\.test\.tsx/);
  });

  it("refuses a source it cannot parse rather than returning a figure", () => {
    expect(() => ts("it('unclosed', () => {\n")).toThrow("did not parse");
  });
});

describe("a row is a glob", () => {
  it("covers a file named outright", () => {
    expect(covers("lib/zip.test.ts", "lib/zip.test.ts")).toBe(true);
  });

  it("covers a file nested below the directory it names", () => {
    expect(
      covers(
        "pages/SettingsPage/*",
        "pages/SettingsPage/components/Api.test.tsx",
      ),
    ).toBe(true);
  });

  it("does not cover a sibling whose name merely starts the same", () => {
    expect(covers("pages/Home/*", "pages/HomeSearch/Bar.test.tsx")).toBe(false);
  });

  it("does not let a dot in a pattern match any character", () => {
    expect(covers("lib/zip.test.ts", "libXzip.test.ts")).toBe(false);
  });
});

describe("what the run says the register has wrong", () => {
  const counts = { "a.test.ts": 10, "dir/b.test.tsx": 5, "dir/c.test.tsx": 2 };
  const rows: [string, number][] = [
    ["a.test.ts", 10],
    ["dir/*", 7],
  ];

  it("finds nothing when every figure is the run's own", () => {
    const body = census(counts);
    expect(problems(registerFor(body, rows), body)).toEqual([]);
  });

  it("names the row, both numbers and the files it expanded to", () => {
    const body = census(counts);
    const stale = registerFor(body, rows).replace(
      "| `dir/*` | 7 |",
      "| `dir/*` | 6 |",
    );

    expect(problems(stale, body)[0]).toBe(
      "`dir/*`: the register says 6, the run counted 7 over 2 files",
    );
  });

  it("names a row that matches nothing, where a sum would read as agreement", () => {
    const body = census(counts);
    const gone = registerFor(body, [...rows, ["gone/*", 0]]);

    expect(problems(gone, body)).toContainEqual(
      "`gone/*` matches no file in this test tree",
    );
  });

  it("names a file two rows both claim, because its tests are counted twice", () => {
    const body = census(counts);
    const twice = registerFor(body, [...rows, ["dir/b*", 5]]);

    expect(problems(twice, body).join("\n")).toContain(
      "dir/b.test.tsx is matched by 2 rows",
    );
  });

  it("leaves a file the register may not name out of both directions", () => {
    const body = census(
      { ...counts, "stripped.test.ts": 4 },
      { ...counts, "stripped.test.ts": 4 },
      ["stripped.test.ts"],
    );

    expect(problems(registerFor(body, rows), body)).toEqual([]);
  });

  it("names a row that covers a file the register may not name", () => {
    const body = census(
      { ...counts, "dir/stripped.test.tsx": 4 },
      { ...counts, "dir/stripped.test.tsx": 4 },
      ["dir/stripped.test.tsx"],
    );

    expect(problems(registerFor(body, rows), body).join("\n")).toContain(
      "dir/stripped.test.tsx declares itself internal",
    );
  });

  /**
   * The state that would otherwise make the block's own sentence false: such a
   * file generates nothing and is published as one of the files generating any.
   * `coverageRegister.test.ts` was in it at `fee91e9`.
   *
   * **Four arms because four planted mutations survived one**, and each is a
   * property the refusal's comment claims: that it is reported before anything
   * else, that it names every offender, that it does not need a collected test to
   * fire, and that it fires in one direction only.
   */
  it("reports it before anything else the register has wrong", () => {
    const body = census(
      { "a.test.ts": 2, "b.test.ts": 4 },
      { "a.test.ts": 3, "b.test.ts": 4 },
    );
    const rows: [string, number][] = [
      ["a.test.ts", 2],
      ["b.test.ts", 4],
    ];
    const alsoStale = registerFor(body, rows).replace(
      "| `b.test.ts` | 4 |",
      "| `b.test.ts` | 9 |",
    );

    const found = problems(alsoStale, body);

    expect(found[0]).toContain("a.test.ts: 3 written out against 2 collected");
    expect(found.join("\n")).toContain("`b.test.ts`: the register says 9");
  });

  it("names every file in that state rather than only the first", () => {
    const body = census(
      { "a.test.ts": 2, "b.test.ts": 1 },
      { "a.test.ts": 3, "b.test.ts": 5 },
    );
    const rows: [string, number][] = [
      ["a.test.ts", 2],
      ["b.test.ts", 1],
    ];

    const found = problems(registerFor(body, rows), body).join("\n");

    expect(found).toContain("a.test.ts: 3 written out against 2 collected");
    expect(found).toContain("b.test.ts: 5 written out against 1 collected");
  });

  it("names a file that collected nothing while writing a test out", () => {
    // The purest instance of what this refuses, and the one a `count > 0` guard
    // would silently exempt: a call in a helper nothing invokes, in a file where
    // every call is one, so the run collects nothing and the source still writes.
    //
    // **This census is deliberately one file, and that is what preserves the arm
    // these four replaced.** That arm carried one file too, so a refusal firing
    // only where a census holds several would have slipped past the other three,
    // which carry two. Adding a second file here closes that hole by accident.
    const body = census({ "a.test.ts": 0 }, { "a.test.ts": 1 });

    expect(
      problems(registerFor(body, [["a.test.ts", 0]]), body).join("\n"),
    ).toContain("a.test.ts: 1 written out against 0 collected");
  });

  it("leaves a file that genuinely generates out of it", () => {
    // The other direction, which is the whole point: `!==` here would name a file
    // whose cases a generator produced, which is every `it.each` in the tree.
    const body = census(
      { "a.test.ts": 4, "b.test.ts": 2 },
      { "a.test.ts": 1, "b.test.ts": 3 },
    );
    const rows: [string, number][] = [
      ["a.test.ts", 4],
      ["b.test.ts", 2],
    ];

    const found = problems(registerFor(body, rows), body).join("\n");

    expect(found).not.toContain("a.test.ts:");
    // Not vacuous: the sibling in the same census is named, so the refusal did
    // run over both and chose.
    expect(found).toContain("b.test.ts: 3 written out against 2 collected");
  });

  it("names a file no row covers rather than counting it", () => {
    const body = census({ ...counts, "orphan.test.ts": 3 });
    const register = registerFor(census(counts), rows);

    expect(problems(register, body).join("\n")).toContain(
      "these files have no row: orphan.test.ts",
    );
  });
});

describe("what a narrowed run may still say", () => {
  /**
   * The fold the backend half of this register already had.
   *
   * Every rule used to sit downstream of the reporter's early return, so a run
   * over fewer files than vitest discovered checked **nothing**: not the
   * counts, not whether every file has a row, not whether a row names a file
   * the publish gate strips. The counts genuinely cannot answer on such a run.
   * The rest never needed to.
   */
  const counts = { "a.test.ts": 10 };
  const everything = ["a.test.ts", "dir/b.test.tsx"];

  it("knows a census built from fewer files than were discovered", () => {
    expect(isWhole(census(counts))).toBe(true);
    expect(isWhole(census(counts, counts, [], everything))).toBe(false);
  });

  it("names a discovered file no row covers, though it did not run", () => {
    const body = census(counts, counts, [], everything);

    expect(
      problems(registerFor(body, [["a.test.ts", 10]]), body).join("\n"),
    ).toContain("these files have no row: dir/b.test.tsx");
  });

  it("names a row covering a file the register may not name, though it did not run", () => {
    const body = census(counts, counts, ["dir/b.test.tsx"], everything);

    expect(
      problems(
        registerFor(body, [
          ["a.test.ts", 10],
          ["dir/*", 0],
        ]),
        body,
      ).join("\n"),
    ).toContain("dir/b.test.tsx declares itself internal");
  });

  it("compares no count and renders no block, because neither can answer", () => {
    const body = census(counts, counts, [], everything);
    const wrong = registerFor(body, [
      ["a.test.ts", 99],
      ["dir/b.test.tsx", 99],
    ]);

    // Both rows are wrong and the block is a whole run's. On a whole census
    // the same register gives three problems; here it gives none, which is
    // the line this fold draws.
    expect(problems(wrong, body)).toEqual([]);
    expect(
      problems(wrong, census({ ...counts, "dir/b.test.tsx": 10 })).length,
    ).toBe(3);
  });
});

describe("the block, rendered from one census", () => {
  const body = census(
    { "a.test.ts": 10, "b.test.ts": 6 },
    { "a.test.ts": 10, "b.test.ts": 2 },
  );

  it("states the total and the file count", () => {
    expect(render(body, ["a.test.ts"])).toContain(
      "**16 tests, in 2 files**, counted by the run that reads this line.",
    );
  });

  it("states how many rows stand below it", () => {
    expect(render(body, ["a.test.ts", "b.test.ts"])).toContain(
      "**2 rows below, and every file this run collected has one.**",
    );
  });

  it("states what a file it may not name holds, in place of that claim", () => {
    const body = census(
      { "a.test.ts": 10, "b.test.ts": 6 },
      { "a.test.ts": 10, "b.test.ts": 2 },
      ["b.test.ts"],
    );

    expect(render(body, ["a.test.ts"])).toContain(
      "**1 row below.** The other 6 tests are in 1 file this register may not name.",
    );
  });

  it("splits written out from generated, counting the files that generate", () => {
    // The whole clause, and its fixture has exactly one generating file on
    // purpose: that is where a finite verb would have to agree with the noun and
    // could not. **This arm used to stop one word short, so it was pinning the
    // disagreement it stood on** rather than the rule, which is the part of this
    // a future reader needs.
    expect(render(body, ["a.test.ts"])).toContain(
      "**12 are written out and 4 are generated**, over the 1 file generating any.",
    );
  });
});

/**
 * The wiring, which the fixture runs below deliberately do not exercise.
 *
 * Each of those names the reporter and the global setup in a config it writes
 * itself, so all four would stay green with both lines deleted from
 * `vite.config.ts` and the register then checked nowhere, which is the defect
 * the global setup exists to catch, one level up. These two are the only
 * assertions here about **this** suite's own configuration.
 */
describe("the guard is wired into the suite it guards", () => {
  it("is named in the config, reporter and global setup both", () => {
    const config = readFileSync(
      join(import.meta.dirname, "..", "vite.config.ts"),
      "utf8",
    );

    expect(config).toContain('"./tests/coverageRegister.reporter.ts"');
    expect(config).toContain('"./tests/coverageRegister.globalSetup.ts"');
  });

  it("ran that global setup before this file, so a marker is waiting", () => {
    expect(process.env[MARKER]).toBeDefined();
  });
});

/**
 * A global setup refusal keeps its text whatever formats stacks after it is
 * thrown.
 *
 * **One sighting, and this is what it shows and no more.** A full run once
 * printed a teardown stack where the refusal's text should have been. A stack
 * string is built on first read under whichever `Error.prepareStackTrace` is
 * installed then, and vitest prints this half's refusal from its stack, later.
 * These arms force that order in process: the refusal is built, a formatter
 * that drops every message is installed, and only then is the stack read.
 * Whether that is what happened in the sighting is not established.
 *
 * **`stackTraceLimit` is not raced here, because it is not lazy**: measured
 * 2026-10-08 under bun 1.4.2 and node 24, a limit set to 0 after construction
 * left the stack's frames in place, while a formatter installed after
 * construction replaced the whole string.
 */
describe("a global setup refusal is printed with its text", () => {
  it("keeps its text when a formatter is installed after it is thrown", () => {
    const marker = process.env[MARKER];
    const formatter = Error.prepareStackTrace;
    let thrown: unknown = undefined;
    // **The one refusal that throws before teardown touches anything**, so
    // driving it in this worker removes nothing of the run's own: with the
    // marker unset it refuses on its first line.
    delete process.env[MARKER];
    try {
      teardown();
    } catch (error) {
      thrown = error;
    } finally {
      if (marker !== undefined) process.env[MARKER] = marker;
    }
    if (!(thrown instanceof Error))
      throw new Error("teardown with no marker refused nothing");

    let stack: string | undefined;
    Error.prepareStackTrace = () => "Error";
    try {
      stack = thrown.stack;
    } finally {
      Error.prepareStackTrace = formatter;
    }

    expect(stack).toContain(thrown.message);
    expect(thrown.message).toContain("unset at teardown");
  });

  /**
   * **The arm above drives one of the file's refusals**, so this is what
   * stops the others being built some other way: every `throw` in the file
   * throws a call to `refusal`. Read off the parse, so a comment naming the
   * constructor is not counted.
   *
   * **Throws, not constructions, because a construction can be spelled many
   * ways.** A count of `new Error` missed `throw Error(...)` and
   * `new globalThis.Error`, measured, and refused the helper written as an
   * arrow function bound to a `const`. What this cannot see is the helper's
   * own body, which the arm above holds by driving it.
   *
   * **And exactly one declaration binds that name**, as a function or as a
   * variable, because a second one declared in a block shadows the helper
   * there: a `const refusal` building a bare `Error` passed the throw rule
   * alone, measured. A shadow through a function parameter or a `catch`
   * binding still passes, since neither is a declaration this counts.
   */
  it("throws nothing but a call to the one helper that formats it", () => {
    const path = join(import.meta.dirname, "coverageRegister.globalSetup.ts");
    const thrown: string[] = [];
    let declared = 0;
    const walk = (node: unknown): void => {
      if (Array.isArray(node)) {
        for (const child of node) walk(child);
        return;
      }
      if (typeof node !== "object" || node === null) return;
      const here = node as {
        type?: string;
        id?: { type?: string; name?: string } | null;
        argument?: { type?: string; callee?: { type?: string; name?: string } };
      };
      if (
        (here.type === "FunctionDeclaration" ||
          here.type === "VariableDeclarator") &&
        here.id?.type === "Identifier" &&
        here.id.name === "refusal"
      )
        declared += 1;
      if (here.type === "ThrowStatement")
        thrown.push(
          here.argument?.type === "CallExpression" &&
            here.argument.callee?.type === "Identifier"
            ? (here.argument.callee.name ?? "")
            : (here.argument?.type ?? ""),
        );
      for (const value of Object.values(node)) walk(value);
    };
    walk(parseAst(readFileSync(path, "utf8"), { lang: "ts" }));

    expect(thrown).not.toHaveLength(0);
    expect(new Set(thrown)).toEqual(new Set(["refusal"]));
    expect(declared).toBe(1);
  });
});

/**
 * The mechanism, driven end to end against a tree this test builds.
 *
 * Everything above would pass just as well with the reporter deleted from the
 * config, or with vitest having renamed the hook it is written against. This
 * runs a whole vitest with the real reporter over a fixture library and asserts
 * the exit code both ways, which is the only assertion here that fails when the
 * guard stops being connected to anything.
 *
 * **Which refusal fired is read from a file the fixture writes, never from the
 * child's stderr.** The fixture wraps the real reporter and the real global
 * setup, records the message of whatever they throw and rethrows it, so an arm
 * below passes only if the half it names threw the message it names. The child's
 * stderr is the wrong instrument for that question: the text an `Error` prints
 * is built when something first reads its `.stack`, by whichever
 * `Error.prepareStackTrace` is installed at that moment, and vitest reassigns
 * that global while it runs. So a refusal thrown here was formatted there, and
 * the two fields the fixture records beside each message say under what.
 *
 * **Whether a refusal is readable is a different question, and it keeps two
 * arms of its own at the bottom**, one for each of the two routes vitest prints
 * by. Their docstring holds the measurement, and the second of them is the only
 * arm in this file that notices the failure that opened this subject.
 */
describe("the guard fails a run", () => {
  const root = join(import.meta.dirname, "..");
  let fixture: string;

  const write = (register: string) =>
    writeFileSync(join(fixture, "tests", "COVERAGE.md"), register);

  /**
   * Where the fixture's wrappers record what the real halves threw.
   *
   * The path travels in the environment and carries the spawn's own number, so
   * the file belongs to the run that is reading it and no arm can be satisfied
   * by what an earlier one left behind. One shared name would rest that on the
   * truncation below and on these arms running serially, and neither of those
   * is a property of this file.
   */
  const CHANNEL = "ENDPAPER_REGISTER_REFUSALS";

  /**
   * Where the fixture's setup file records the process a test file ran in.
   *
   * A channel of its own rather than a field on the one above, for two reasons
   * that both bite. `asRefusal` refuses a line its `record` did not write, so a
   * foreign line there reddens every spawn. And the refusal channel is written
   * only when a half throws, where this one is written by every run, including
   * the passing ones.
   */
  const PROCESSES = "ENDPAPER_REGISTER_PROCESSES";

  let spawned = 0;

  /**
   * One refusal, plus the state of the two globals that decide what an `Error`
   * prints.
   *
   * **`stackTraceLimit` is a string because JSON has neither `Infinity` nor
   * `NaN`**, and this field may hold either. `JSON.stringify` writes both as
   * `null`, which is also what an unset field reads as, so a number here would
   * collapse three different states into one. Measured with `node -e`, frames in
   * `error.stack`: `Infinity` keeps **every** frame, `NaN` keeps **none**, and
   * `0` keeps none. So `NaN` is the setting under which a stack arrives with no
   * frames at all while looking like an ordinary reassignment, and it is exactly
   * the one a number could not have told apart from unset.
   */
  type Refusal = {
    from: string;
    message: string;
    prepareStackTrace: boolean;
    stackTraceLimit: string;
    engine: string;
  };
  type Run = {
    pid: number;
    status: number | null;
    stdout: string;
    stderr: string;
    refusals: Refusal[];
    ranTestsIn: Where[];
  };

  /**
   * **Bounded twice, and neither bound is decoration.**
   *
   * `spawnSync` blocks this worker, so vitest's own per test budget cannot
   * interrupt it: the timeout here is the only thing that ends a wedged child,
   * and `SPAWNED` on each `it` below is what keeps vitest's budget above it
   * rather than expiring under it. Without the pair, a run that hangs is killed
   * by whatever is above the suite, and a SIGKILL there skips the runner's
   * cleanup and leaves a pod holding a node lock.
   *
   * One worker, because the fixture config would otherwise read the host's
   * cores rather than the pod's limit. Two files need no parallelism at all.
   * **How many workers is that bound's business; what a worker IS belongs to
   * the bound above it**, and `runThere` holds that with the measurement.
   */
  const SPAWNED = 60_000;

  /**
   * Everything the spawn below asks for except its environment, in one place so
   * that the arm can read the bound back.
   *
   * **Removing the bound was green on every arm before this const existed**, and
   * that is worse than it sounds: `--pool=threads` makes a kill total and the
   * timeout is what delivers a kill, so with the timeout gone the pool buys
   * nothing against the defect it is here for. Only one of the two halves was
   * armed.
   *
   * Two shapes fail. Editing either value reddens the arm. Deleting either field
   * is a type error at the arm's own read, measured: `Property 'timeout' does not
   * exist`.
   *
   * **A third does not, and it is the one a reader will assume.** Replacing the
   * spread below with an inline object that still carries `cwd` and `encoding`,
   * and no bound, passes the type check and the arm: this const stays used by the
   * arm that reads it, so nothing is unused, and `encoding` being present is what
   * keeps `stderr` a `string`. Measured, both directions. So what lives here is
   * the bound's **values and its fields**, not the fact that the call still
   * spreads them. Closing that needs the arm the next paragraph refuses to write.
   *
   * **It holds presence, not delivery.** Nothing here says the kill lands or
   * that it lands on everything: that needs a nested run wedged under a
   * deliberately small timeout with its signal asserted, which needs a fixture
   * root of its own.
   */
  const SPAWN = {
    cwd: root,
    encoding: "utf8",
    timeout: SPAWNED,
    killSignal: "SIGKILL",
  } as const;

  /**
   * The hook the fixture's reporter wrapper overrides, held against the class it
   * overrides it on.
   *
   * The wrapper is a string, so nothing in the gate checks this name: prettier
   * does not format a template literal's contents, oxlint sees no code there and
   * `tsc` sees a string. Interpolated into all three of the wrapper's spellings
   * so the name has one home, and asserted below against the real reporter's own
   * prototype. Deleting either half restores a rename that goes unnoticed.
   */
  const HOOK = "onTestRunEnd";

  /**
   * One recorded line, refused rather than trusted.
   *
   * **The probe is held here rather than in an arm of its own, which is what
   * makes it free.** All four fields are what the fixture's `record` writes, so
   * a line short of any of them means the wrapper and this reader have stopped
   * agreeing, and refusing at the read reddens whichever of the spawns below
   * produced it. An arm would have cost another nested vitest to say the same
   * thing.
   */
  const asRefusal = (line: string, channel: string): Refusal => {
    const parsed = JSON.parse(line) as Partial<Refusal>;
    if (
      typeof parsed.from !== "string" ||
      typeof parsed.message !== "string" ||
      typeof parsed.prepareStackTrace !== "boolean" ||
      typeof parsed.stackTraceLimit !== "string" ||
      typeof parsed.engine !== "string"
    )
      throw new Error(
        `${channel} carries a line the fixture's record() did not write, so ` +
          `this run cannot say what formatted its refusal: ${line}`,
      );
    return {
      from: parsed.from,
      message: parsed.message,
      prepareStackTrace: parsed.prepareStackTrace,
      stackTraceLimit: parsed.stackTraceLimit,
      engine: parsed.engine,
    };
  };

  /** One test file, and the process and thread the pool gave it. */
  type Where = { pid: number; ppid: number; isMainThread: boolean };

  /**
   * One recorded process, refused rather than trusted, for the reason
   * `asRefusal` is.
   *
   * **`isMainThread` is refused here rather than defaulted**, because a line
   * short of it is a probe that has moved somewhere the pool does not decide,
   * and defaulting it would make that move green.
   */
  const asWhere = (line: string, channel: string): Where => {
    const parsed = JSON.parse(line) as Partial<Where>;
    if (
      typeof parsed.pid !== "number" ||
      typeof parsed.ppid !== "number" ||
      typeof parsed.isMainThread !== "boolean"
    )
      throw new Error(
        `${channel} carries a line the fixture's setup file did not write, so ` +
          `this run cannot say which process ran its tests: ${line}`,
      );
    return {
      pid: parsed.pid,
      ppid: parsed.ppid,
      isMainThread: parsed.isMainThread,
    };
  };

  /**
   * The nested runner, bounded, with its workers inside the process the bound
   * can reach.
   *
   * **`timeout` kills this child by pid, and a pool that forks leaves the worker
   * behind.** Measured 2026-09-26 with `node` against a child that starts one
   * long lived grandchild and waits: under `timeout` with
   * `killSignal: "SIGKILL"` the child dies and the grandchild is still alive
   * after it, and `detached: true` does not change that, because the kill is
   * aimed at the pid either way. So `--pool=threads` here is not about speed. It
   * is what makes the worker a thread of this pid rather than a process of its
   * own. The arm below holds it by asking the child which process ran its tests.
   *
   * **The flag does work rather than restate a default.** Measured by removing
   * it: the arm reddens with the test file in pid 147 against the runner's 126,
   * so the installed vitest 5 resolves to a pool that forks when nothing asks
   * otherwise.
   *
   * **What an orphan here costs depends on where this file was run, and one of
   * the two is unbounded.** Inside the suite container it holds memory against
   * that pod's limit until the pod goes, so the symptom is somebody else's run
   * dying on 137. Run on the machine the suite is invoked from, which nothing in
   * this file can prevent, it is bounded by nothing: the sibling of this defect
   * in the harness written in the other language here sat at 8.6 GB for 53
   * minutes, and an orphan is by definition not being waited on, so neither case
   * reports itself.
   *
   * **`detached` is the fix that reads as right and measures worse.** Its own
   * group is a group nothing here signals: `spawnSync` offers no way to signal
   * one, so reaching the workers would mean an async `spawn`, a timer of this
   * file's own and `process.kill(-pid)`, none of which exists on a platform
   * without process groups. That timer also dies with this worker, and leaving
   * the outer run's group is what would stop a signal aimed at the suite
   * reaching this child at all. Inside that group, with no worker process to
   * lose, nothing here needs a process group to exist.
   *
   * On the command line rather than in the fixture config, because this is where
   * the timeout it pairs with lives and the two are only safe read together.
   */
  const runThere = (...flags: string[]): Run => {
    const channel = join(fixture, `refusals.${(spawned += 1)}.jsonl`);
    const processes = join(fixture, `processes.${String(spawned)}.jsonl`);
    writeFileSync(channel, "");
    writeFileSync(processes, "");
    const run = spawnSync(
      join(root, "node_modules", ".bin", "vitest"),
      ["run", "--root", fixture, "--pool=threads", ...flags],
      {
        ...SPAWN,
        env: {
          ...process.env,
          [CHANNEL]: channel,
          [PROCESSES]: processes,
        },
      },
    );
    return {
      pid: run.pid,
      status: run.status,
      // **Kept because one branch of the reporter reports through it and not
      // through the refusal channel.** A narrowed run says what it did not
      // check on stdout and exits 0, so without this field the arm for it
      // could only assert that nothing went wrong, which a reporter that
      // returned at the top would also satisfy.
      stdout: run.stdout,
      stderr: run.stderr,
      refusals: readFileSync(channel, "utf8")
        .split("\n")
        .filter((line) => line !== "")
        .map((line) => asRefusal(line, channel)),
      ranTestsIn: readFileSync(processes, "utf8")
        .split("\n")
        .filter((line) => line !== "")
        .map((line) => asWhere(line, processes)),
    };
  };

  /** Every message that half of the guard threw, and nothing else's. */
  const refused = (run: Run, from: string): string =>
    run.refusals
      .filter((refusal) => refusal.from === from)
      .map((refusal) => refusal.message)
      .join("\n");

  /**
   * That half's refusal as lines, blank and whitespace only ones dropped.
   *
   * **The readability arms assert each line separately rather than the message in
   * one piece, and the reason is indentation.** Both forms are positive
   * containment, so neither is in the fragile class and this was never a choice
   * about that. What separates them is what a runner does to a multi-line error
   * block, and the likeliest thing it does is **prepend**: indenting the block
   * destroys a whole message substring and leaves every per line substring
   * intact.
   *
   * Asserting only the first line is the other end and gives up too much. The
   * reporter's refusal is 110 characters over two non blank lines of **45** and
   * **63**, and those 63 are the only characters naming the row, which the
   * literal these arms replaced asserted outright. A global setup refusal is
   * one line, and there all three forms are the same assertion. **No figure
   * for that half**: there are two of those refusals now, of different
   * lengths, and a count beside one of them reads as a count of both.
   *
   * **What per line gives up, in full**: the blank line between the parts,
   * contiguity, order, and that the lines arrived as one block. All four are
   * right to give up, because the subject of these two arms is that a refusal
   * reaches a person and not how it was laid out.
   *
   * **The caveat is that per line is only as strong as its shortest line, and
   * that is not a constant.** Over every refusal shape this register can throw,
   * driven with the fixture's own row patterns, the shortest non blank line is
   * the 45 character `tests/COVERAGE.md does not describe this run:` that every
   * reporter refusal carries, including the five line block mismatch. But the
   * "matches no file" shape is a row pattern plus 37 characters, and a row
   * pattern is data in a document anybody can edit: against this register's own
   * rows the shortest is `app/*`, which makes that line **42**. So the mechanism
   * is that the floor tracks the shortest row rather than sitting at a figure,
   * and no figure here is a bound. What makes the trade safe is that no shape
   * approaches a length a stderr would carry by accident.
   */
  const refusedLines = (run: Run, from: string): string[] =>
    refused(run, from).split("\n").filter(carriesText);

  /**
   * Why the vacuity line above each stream assertion exists.
   *
   * An arm handed an empty channel would assert nothing and go **green over
   * nothing** rather than red. This is the one line in each pair a reviewer
   * should try to delete first.
   */
  const EMPTY_CHANNEL =
    "the channel carries no refusal from this half, so the stream assertions " +
    "after it would have run over nothing";

  /**
   * The same line for the process channel, and it guards more here.
   *
   * The comparison below runs over the recorded lines, so an empty channel is a
   * loop that executes nothing: green, with the pool unexamined. The setup file
   * is silent when the variable does not reach it, deliberately, so that a
   * channel that never arrives reddens this arm rather than every spawn.
   */
  const NOTHING_RECORDED =
    "no test file recorded the process it ran in, so the comparison after this " +
    "line would have run over nothing";

  /** What the child's process tree was, for the assertion that has just failed. */
  const topology = (run: Run, where: Where): string =>
    `a test file ran in pid ${String(where.pid)}, whose parent is ` +
    `${String(where.ppid)}, on ${where.isMainThread ? "the main thread" : "a worker thread"}, ` +
    `where the spawn's own child is ${String(run.pid)}. A test body in a ` +
    `process of its own is a process the timeout's kill does not reach, so a ` +
    `run that hits SPAWNED leaves it behind. A test body on the main thread is ` +
    `a probe that is no longer asking the pool anything`;

  /**
   * What the child was when that half threw, as a sentence for whichever
   * assertion is failing: its runtime, and the two globals that decide what an
   * `Error` prints.
   *
   * **Named for the child and not for the formatter, because the child is a
   * process boundary away from the runner** and forgetting that is what sent
   * three rounds of this review to the wrong subject.
   *
   * **This is the one place the probe's value reaches a person, and that is
   * deliberate.** No arm pins either field: `prepareStackTrace` being installed
   * is the precondition of the bare `Error` below, so an arm pinning it would
   * redden on the vitest release that stopped reassigning, which is red on a
   * repair rather than on a defect. So the fields are recorded, their **shape**
   * is held by `asRefusal` at the channel read, where its own docstring says
   * why, and their value is printed where it explains something: beside a stream
   * assertion that has just failed.
   *
   * Measured through this sentence on 2026-09-26: at the moment the global
   * setup's teardown throws, `prepareStackTrace` is installed and
   * `stackTraceLimit` is 10. So the reassignment is live here and the path that
   * reduces the limit to 1 is not the one these runs take.
   */
  const childState = (run: Run, from: string): string => {
    const recorded = run.refusals.find((refusal) => refusal.from === from);
    if (recorded === undefined)
      return `nothing was recorded from ${from}, so this stream has no refusal to carry`;
    return (
      `the child at throw time: ${recorded.engine}, ` +
      `Error.prepareStackTrace installed ` +
      `${recorded.prepareStackTrace}, Error.stackTraceLimit ` +
      `${recorded.stackTraceLimit}. A stack string is built on first read under ` +
      `whichever of those two are installed then, which is how a refusal thrown ` +
      `here can print with its text gone`
    );
  };

  beforeAll(() => {
    fixture = mkdtempSync(join(tmpdir(), "endpaper-register-"));
    mkdirSync(join(fixture, "tests"));

    const real = (name: string) => JSON.stringify(join(root, "tests", name));

    // **These three files are strings, and nothing in the gate reads them.**
    // prettier does not format a template literal's contents, oxlint sees no
    // code there and `tsc` sees a string, so the middle of this guard is the
    // one part of the tree no check covers.
    //
    // The `Parameters<...>` annotation in the reporter wrapper looks like a
    // compile time link to the hook's name and is not one, for the same reason:
    // `tsc` sees a string. `HOOK` above gives that name one home and the arm
    // below fails on it by name.
    //
    // **A rename can still empty the channel. What changed is that the two
    // causes are now told apart.** Trace it: vitest renames the hook, the real
    // reporter follows, and `HOOK` still spells the old name. The wrapper then
    // overrides a name nothing calls, `Recording` inherits the new one from the
    // real class, vitest calls that, the real hook runs **unwrapped**, and its
    // throw is never recorded. So the channel is empty while the half did throw.
    // Read off the override rule rather than measured, because vitest's own call
    // site is what would have to move.
    //
    // A rename only half followed leaves a **third** state, and this one is
    // measured: with the real class renamed and vitest still calling the old
    // name, the wrapper runs, `super[HOOK]` is undefined, and the channel carries
    // a `TypeError` from `super` where a refusal should be.
    //
    // **The state is the point. The wording belongs to the child's engine, and
    // the child's engine is a property of where the suite runs rather than of
    // this repository.** Read off the channel on a real run: **the child is bun
    // 1.4.2**, inside the suite container. The same shebang resolves the other way
    // on the machine this is written on, where `node_modules/.bin/vitest` is
    // `env node` and `node` inside a `bun run` script is node 24.10.0, verified.
    // So the two engines word this failure differently, the child takes the one
    // its own environment gives it, and **three rounds of review settled it
    // locally and were each correct about the wrong process.** Nothing in the
    // tree decides it and no local check can, which is why `record` reports the
    // child's runtime beside every refusal and `childState` prints it into any
    // failing stream assertion. Why the container resolves it that way is not
    // established here and is not claimed.
    //
    // **Pin no spelling of that message**, here or in an arm: it is an engine's
    // diagnostic, it moves with an image nobody diffs, and this comment names the
    // state rather than the text for that reason.
    //
    // **In both rename shapes the arm below reddens and names the hook; where the
    // half simply did not throw it stays green, and that difference is the
    // diagnosis.** Beside the four channel arms below, the `status` assertion says
    // it a second way; the readability pair after them carries no status
    // assertion and never did. A fixture config that stopped loading reddens
    // **every spawning arm** at once rather than emptying the channel quietly.
    // Not the hook arm: it reads the prototype in process, loads no fixture
    // config and stays green, which is the same reason it is the discriminator.

    writeFileSync(
      join(fixture, "record.ts"),
      `import { appendFileSync } from "node:fs";

// **Never read \`error.stack\` here, and this is the one line that cannot be
// simplified away.** V8 formats a stack on first access and caches the string,
// so reading it in this wrapper would freeze it under the throw time formatter
// and repair the bare \`Error\` that the last arm of this block is the tree's
// only detector of. The two fields below are the formatter's state and not the
// formatted text, which is why they are safe to read and \`stack\` is not.
export function record(from: string, error: unknown): void {
  const channel = process.env[${JSON.stringify(CHANNEL)}];
  if (channel === undefined) return;
  const message = error instanceof Error ? error.message : String(error);
  appendFileSync(
    channel,
    JSON.stringify({
      from,
      message,
      prepareStackTrace: typeof Error.prepareStackTrace === "function",
      stackTraceLimit: String(Error.stackTraceLimit),
      // **The child is a process boundary away from whatever spawned it**, and
      // three attempts to reason from the runner's engine to this one settled the
      // question on the wrong subject. Asked here instead, where the answer is.
      engine:
        process.versions.bun === undefined
          ? "node " + process.versions.node
          : "bun " + process.versions.bun,
    }) + "\\n",
  );
}
`,
    );

    // **A setup file, because it is the only half of a nested run that executes
    // where the pool put it.** The two wrappers below run in the runner's own
    // process whatever the pool is, so neither can answer the question the arm
    // on `--pool=threads` asks.
    //
    // **That sentence used to be the whole guarantee, and moving this probe into
    // the global setup wrapper was green on every arm with the pool flag also
    // gone.** A pid recorded from the runner's own main process equals the
    // spawn's pid under any pool, so the comparison held while its subject was
    // no longer being observed. `isMainThread` is what closes it: the pool is the
    // only thing that decides it, so a probe that moved out of the pool's reach
    // reports `true` and reddens. The one shape it would wrongly refuse is a pool
    // that runs test files on the main thread of the main process, which no
    // vitest 5 pool does.
    //
    // Silent without the variable rather than throwing: a channel that does not
    // reach here would otherwise redden every spawn with a setup file failure,
    // where what it means is that one arm's instrument is missing. That arm
    // carries the vacuity line for it.
    writeFileSync(
      join(fixture, "processes.ts"),
      `import { appendFileSync } from "node:fs";
import { isMainThread } from "node:worker_threads";

const channel = process.env[${JSON.stringify(PROCESSES)}];
if (channel !== undefined)
  appendFileSync(
    channel,
    JSON.stringify({
      pid: process.pid,
      ppid: process.ppid,
      isMainThread,
    }) + "\\n",
  );
`,
    );

    // **The fixture config names these wrappers, and the real files are what
    // run inside them.** The reporter wrapper extends the real class, so it is
    // the real hook that decides; the setup wrapper re-exports the
    // real `setup` and calls the real `teardown`. Swallowing instead of
    // rethrowing would change the child's exit code, which every arm below
    // still asserts, so a wrapper that stopped rethrowing reddens rather than
    // quietly weakening the block.
    //
    // What this no longer exercises is vitest resolving the real reporter from
    // a `reporters` entry naming its own path, and **nothing in this file
    // detects that**. Measured: delete the reporter from `vite.config.ts` and
    // leave the quoted path in a comment beside it, and both wiring arms above
    // pass, because one reads the config as text and the other reads a marker
    // the GLOBAL SETUP writes. What fails the outer run is that global setup's
    // own teardown, and its refusal prints through the close path the last arm
    // below is about. So the two are the same detector, and the last arm is
    // what keeps it readable.
    writeFileSync(
      join(fixture, "reporter.ts"),
      `import Real from ${real("coverageRegister.reporter.ts")};
import { record } from "./record";

export default class Recording extends Real {
  async ${HOOK}(
    ...args: Parameters<InstanceType<typeof Real>["${HOOK}"]>
  ): Promise<void> {
    try {
      await super.${HOOK}(...args);
    } catch (error) {
      record("reporter", error);
      throw error;
    }
  }
}
`,
    );

    writeFileSync(
      join(fixture, "globalSetup.ts"),
      `import { setup, teardown as refuse } from ${real("coverageRegister.globalSetup.ts")};
import { record } from "./record";

export { setup };

export function teardown(): void {
  try {
    refuse();
  } catch (error) {
    record("globalSetup", error);
    throw error;
  }
}
`,
    );

    // **`.mjs`, and it buys nothing against the failure rate.** The fixture lands
    // in a temporary directory with no `package.json` anywhere above it, so under
    // `.ts` Vite reads the file as CommonJS and prints a **374 byte**
    // incompatibility warning above every one of these runs. Measured in process
    // against this exact config body through Vite's own `loadConfigFromFile`: one
    // `esm-syntax-in-cjs` finding and 374 bytes under `.ts`, and none at all
    // under `.mjs`. The 1,154 bytes recorded elsewhere for this are the child's
    // **whole** stderr, byte identical over 400 green runs, of which this warning
    // is a third. No `toContain` can be displaced by extra bytes on a stream
    // either way. **So this is noise removal and not a fix for a flake**, and
    // reading it as one is how the wrong mechanism was written the first time.
    //
    // It is also the less coupled spelling, not the more: Vite names a `.mjs`
    // extension as its own remedy and says the native loader is planned to become
    // the default, so `.ts` here loads only while the bundling loader tolerates
    // the mismatch. The body has no TypeScript syntax, and `.mjs` is in vitest's
    // own config candidate list.
    //
    // No arm guards the extension. A fixture config that stops loading reddens
    // every spawning arm at once, and a negative assertion on a stream a third
    // party writes into is the one shape extra bytes really can change, which is
    // the defect this block exists to stay clear of.
    writeFileSync(
      join(fixture, "vitest.config.mjs"),
      "export default { test: { globals: true, include: ['tests/**/*.test.ts'], " +
        "maxWorkers: 1, minWorkers: 1, " +
        `setupFiles: [${JSON.stringify(join(fixture, "processes.ts"))}], ` +
        `globalSetup: [${JSON.stringify(join(fixture, "globalSetup.ts"))}], ` +
        `reporters: ['default', ${JSON.stringify(join(fixture, "reporter.ts"))}] } };\n`,
    );
    writeFileSync(
      join(fixture, "tests", "a.test.ts"),
      "it('one', () => { expect(1).toBe(1); });\nit('two', () => { expect(2).toBe(2); });\n",
    );
    writeFileSync(
      join(fixture, "tests", "b.test.ts"),
      "it('alone', () => { expect(1).toBe(1); });\n" +
        "it.each([1, 2, 3])('case %d', (n) => { expect(n).toBe(n); });\n",
    );
  });

  afterAll(() => rmSync(fixture, { recursive: true, force: true }));

  it("wraps a hook the real reporter has", () => {
    // **Read through the prototype chain, because `super[HOOK]` is**, where
    // `Object.getOwnPropertyNames` is not: a hook the real reporter inherited
    // would leave the wrapper working and this arm red. Not live today, vitest's
    // `Reporter` being an interface. `toBeTypeOf` also catches the name present
    // as something not callable, which a name listing cannot.
    //
    // **Evaded once, and this arm is what caught it.** Renaming the hook in
    // `coverageRegister.reporter.ts` and changing nothing else fails this arm on
    // `expected undefined to be type of 'function'`. Three channel arms redden
    // with it, by the teardown noticing its marker was never written, and their
    // wording sends the reader to a `--reporter` flag: this one names the thing
    // that actually moved, which is why it is not redundant with them.
    expect(CoverageRegisterReporter.prototype[HOOK]).toBeTypeOf("function");
  });

  const body = census(
    { "a.test.ts": 2, "b.test.ts": 4 },
    { "a.test.ts": 2, "b.test.ts": 1 },
  );
  const rows: [string, number][] = [
    ["a.test.ts", 2],
    ["b.test.ts", 4],
  ];

  const oneTestOut = () =>
    registerFor(body, rows).replace(
      "| `a.test.ts` | 2 |",
      "| `a.test.ts` | 3 |",
    );

  it(
    "passes a register that states what the run counted",
    () => {
      write(registerFor(body, rows));

      const run = runThere();

      expect(run.refusals).toEqual([]);
      expect(run.status).toBe(0);
    },
    SPAWNED + 30_000,
  );

  /**
   * That the tests of a nested run ran in the process this file can kill.
   *
   * **The instrument is the spawn's own pid against the pid the child reports**,
   * and the first half of that is why it is not the child's opinion of its own
   * topology: `spawnSync` returns the pid its timeout would signal. Equal means
   * the pool put the test body in that pid. Different means a worker process,
   * which that signal does not reach and nothing then waits on.
   *
   * Delete `--pool=threads` from `runThere` and this arm reddens, naming both
   * pids and the worker's parent. **It is the only arm here that does**: the
   * other spawning arms pass under either pool, because a forked worker runs the
   * tests correctly and is only a problem once something has to kill it.
   *
   * **The thread half is not a second way of saying the first.** A pid comparison
   * is satisfied by anything recorded from the runner's own main process,
   * whatever the pool is, so it cannot tell a pool of threads from a probe that
   * stopped asking the pool. `isMainThread` can, and the fixture's comment holds
   * what that closed.
   *
   * **Both halves of the bound, because the pool only makes a kill total and the
   * timeout is what delivers one.** Read off `SPAWN`, whose docstring says which
   * two shapes that catches and which one it does not.
   *
   * **The dependency this rests on, stated rather than assumed**: that the vitest
   * launcher execs in place, so the pid `spawnSync` returns is the runner's own
   * main process. A launcher that forks, a shell wrapper around it, or a future
   * vitest that re executes itself to pass a flag would redden this arm on a
   * correct tree. That is the same class of mistake this file records three
   * review rounds lost to, one process boundary further out.
   *
   * **What it does not hold**: that the runner has no other descendant. It reads
   * the processes that ran a test file and enumerates nothing else, so a
   * transform service or a coverage helper the runner starts is outside it, and
   * this arm says nothing about how many of those there are.
   */
  it(
    "runs a nested run's tests in the process the timeout can kill",
    () => {
      write(registerFor(body, rows));

      expect(SPAWN.timeout, "the spawn asks for no timeout").toBe(SPAWNED);
      expect(SPAWN.killSignal, "the spawn names no signal").toBe("SIGKILL");

      const run = runThere();

      expect(run.ranTestsIn, NOTHING_RECORDED).not.toHaveLength(0);
      for (const where of run.ranTestsIn) {
        expect(where.pid, topology(run, where)).toBe(run.pid);
        expect(where.isMainThread, topology(run, where)).toBe(false);
      }
    },
    SPAWNED + 30_000,
  );

  it(
    "fails a run whose register is one test out, naming the row",
    () => {
      write(oneTestOut());

      const run = runThere();

      expect(refused(run, "reporter")).toContain(
        "`a.test.ts`: the register says 3, the run counted 2",
      );
      expect(run.status).toBe(1);
    },
    SPAWNED + 30_000,
  );

  /**
   * A narrowed run, which used to check nothing and now checks the document.
   *
   * **Until this pair, no end to end arm in this file narrowed a run**, so
   * both branches of the reporter's size test were on the "stated" rung: the
   * arms above drive a correct register, a one test out register, a missing
   * row and a replaced reporter, and not one of them takes fewer files than
   * vitest discovered.
   *
   * The counts cannot answer here and are not asked. What the run still says
   * is that `b.test.ts` has no row, which is a fact about the tree rather
   * than about what ran, and which the same spawn reported nowhere before.
   */
  it(
    "fails a narrowed run whose register has no row for a file it did not run",
    () => {
      write(registerFor(body, [["a.test.ts", 2]]));

      const run = runThere("tests/a.test.ts");

      expect(refused(run, "reporter")).toContain(
        "these files have no row: b.test.ts",
      );
      expect(run.status).toBe(1);
    },
    SPAWNED + 30_000,
  );

  /**
   * The other direction, so the arm above is not satisfied by a guard that
   * reds on every narrowed run.
   *
   * **The log line is the assertion, because exiting 0 is also what a
   * reporter that returned at the top of the hook does.** A positive
   * containment on a stream this run owns, which is the direction extra bytes
   * from a third party cannot displace, where a negative one on the same
   * stream is the shape they can.
   */
  it(
    "passes a narrowed run whose register describes the tree, and says what it skipped",
    () => {
      write(registerFor(body, rows));

      const run = runThere("tests/a.test.ts");

      expect(run.refusals).toEqual([]);
      expect(run.status).toBe(0);
      expect(run.stdout).toContain(
        "coverage register: counts not checked, this run took 1 of 2 test files",
      );
    },
    SPAWNED + 30_000,
  );

  /**
   * The property this half's safety rests on, which nothing pinned.
   *
   * **The backend half withholds its write when anything was deselected,
   * because its gate is a file set and a name filter leaving one test in
   * every file opens it on counts that are floors. This half needs no such
   * counter, and that is a measurement rather than a judgement**: vitest
   * marks a non matching task `skip` rather than removing it, and
   * `allTests()` yields a skipped task, so a name filter moves no count and
   * the register still describes the run.
   *
   * Measured over the real suite, `bun run test -t zip`: `Test Files 8
   * passed | 194 skipped (202)`, `Tests 36 passed | 4381 skipped (4417)`,
   * exit 0, no write printed and no complaint. The total is the collection's
   * and not the execution's.
   *
   * **So the thing to guard is the vitest behaviour, not a narrowing.** A
   * counter here would be armed by nothing and would read to the next person
   * as a case somebody had seen. If this arm ever reddens, the counter is
   * what the fix is, and the backend half already has one to copy.
   */
  it(
    "offers no write and loses no count when a name filter narrows a run",
    () => {
      write(registerFor(body, rows));

      const run = runThere("-t", "alone");

      expect(run.refusals).toEqual([]);
      // The constant, never the word written out: a literal here would put
      // this file into the derived population that holds the three
      // spellings of it equal.
      expect(run.stdout).not.toContain(WRITE_SENTINEL);
      expect(run.status).toBe(0);
    },
    SPAWNED + 30_000,
  );

  /**
   * The witness the arm above cannot be.
   *
   * **No refusal, no sentinel and exit zero are all satisfied when nothing
   * was checked at all**, so that arm cannot tell the counts surviving the
   * filter from the counts never being asked. Its own neighbour twenty five
   * lines up argues against exactly that shape, on a stream rather than on a
   * channel.
   *
   * So this one is a **positive containment** on the channel this file
   * prefers: the same name filter, a register stale by one row, and the
   * reporter's refusal required to name the file and both counts. Only a run
   * that counted under the filter can produce that sentence.
   */
  it(
    "counts under a name filter, and says both figures when the row is stale",
    () => {
      write(oneTestOut());

      const run = runThere("-t", "alone");

      expect(refused(run, "reporter")).toContain(
        "`a.test.ts`: the register says 3, the run counted 2 over 1 file",
      );
      expect(run.status).toBe(1);
    },
    SPAWNED + 30_000,
  );

  /**
   * The write a nested run must not offer, driven rather than reasoned.
   *
   * **A child of this suite imports the real guard**, so the register path
   * that guard derives from its own location was this repository's while
   * every figure was the fixture's. The child pipes and two arms assert on
   * its standard output, so a failing one prints what it received: a well
   * formed write naming the real register, carrying another tree's counts,
   * into an artefact.
   *
   * The reporter now asks whether the run's own register is the module's
   * before offering a write at all. This drives a child whose register is
   * stale, which is precisely when a write would have been printed, and
   * requires none.
   */
  it(
    "prints no write from a run over somebody else's library",
    () => {
      write(oneTestOut());

      const run = runThere();

      expect(refused(run, "reporter")).toContain("does not describe this run");
      expect(run.stdout).not.toContain(WRITE_SENTINEL);
      expect(run.stderr).not.toContain(WRITE_SENTINEL);
      expect(run.status).toBe(1);
    },
    SPAWNED + 30_000,
  );

  it(
    "fails a run whose reporters a command line flag replaced",
    () => {
      write(registerFor(body, rows));

      const run = runThere("--reporter=default");

      expect(refused(run, "globalSetup")).toContain(
        "the coverage register reporter did not run",
      );
      expect(run.status).toBe(1);
    },
    SPAWNED + 30_000,
  );

  /**
   * The attempt the whole arrangement refuses, driven rather than described.
   *
   * **A guard that heals itself asserts nothing**, so what a run measures is
   * printed and applying it is a separate invocation. The way a future edit
   * undoes that is to make the run write the document it is checking, and
   * this plants exactly that: a test file in the fixture library that
   * rewrites the fixture's own register while the run is going.
   *
   * **Closed over the mechanism rather than over the spelling.** The refusal
   * compares the register's bytes either side of the run, so it does not
   * matter whether the write came from a test, from the reporter, from a
   * setup file or from a plugin. A rule naming one way of writing a file
   * would be a list of the ways somebody has thought of, and the next one is
   * written by somebody who has not read the list.
   *
   * **It plants in the fixture and never in this tree**, which is what the
   * global setup reading its own project's root buys: the attempt is real and
   * the register this suite is checking is never touched by it.
   */
  it(
    "fails a run that rewrote the register it was checking",
    () => {
      write(registerFor(body, rows));
      const planted = join(fixture, "tests", "heals.test.ts");
      writeFileSync(
        planted,
        `import { writeFileSync } from "node:fs";\n` +
          `it("rewrites the register under the run", () => {\n` +
          `  writeFileSync(${JSON.stringify(join(fixture, "tests", "COVERAGE.md"))}, "# Coverage\\n");\n` +
          `  expect(1).toBe(1);\n});\n`,
      );

      try {
        const run = runThere();

        expect(refused(run, "globalSetup")).toContain(
          "changed while the run that checks it was running",
        );
        expect(run.status).toBe(1);
      } finally {
        // Removed whatever happened above, because every other spawning arm
        // here counts the files in this library and a leftover one moves
        // every figure they assert.
        rmSync(planted, { force: true });
      }
    },
    SPAWNED + 30_000,
  );

  it(
    "fails a run whose register has no row for a file",
    () => {
      write(registerFor(body, rows.slice(0, 1)));

      const run = runThere();

      expect(refused(run, "reporter")).toContain(
        "these files have no row: b.test.ts",
      );
      expect(run.status).toBe(1);
    },
    SPAWNED + 30_000,
  );

  /**
   * The two arms whose subject is the child's stderr, and the only two.
   *
   * The four channel arms above ask which refusal fired, which the stream
   * cannot answer without also answering for vitest's formatting. These ask the
   * different question the block would otherwise stop covering: that a refusal reaches a
   * person, and not only the file the fixture records it in. A guard nobody
   * can read is a guard nobody acts on.
   *
   * **One arm for each half, because vitest prints them by different routes,
   * and only one of the two routes can lose the message.** A reporter's throw
   * arrives as an Unhandled Error, printed from `message`. The global setup's
   * arrives through vitest's `close()`, which logs the error object, so what
   * prints is the `stack` string; a stack string is built when something first
   * reads it, by whichever `Error.prepareStackTrace` is installed at that
   * moment, and vitest reassigns that global while it runs.
   *
   * **Each asserts, line by line, the message the channel recorded, not a
   * literal of its own.**
   * The wording then has one home, at the site that throws it, where before two
   * of these literals were a strict prefix of another arm's and rewording either
   * refusal reddened an arm that does not care what the refusal says. It is also
   * the stronger claim: it holds that the **same** message reached both routes,
   * where two independent literals would pass while the child recorded one
   * refusal and printed another.
   *
   * That is measured rather than supposed. Assigning
   * `Error.prepareStackTrace = () => "Error"` inside the child reduces the
   * second arm's stream to `error during close [Error]` and leaves the first
   * arm's untouched. **The second arm is the only thing in this file that goes
   * red under it**, which is why it is here rather than left to the channel.
   *
   * **That measurement predates the global setup reading its own stack where
   * it builds the refusal**, and has not been driven again since. A formatter
   * in place before the throw still reaches the text; one installed after it
   * no longer does, which the block named for a global setup refusal being
   * printed with its text holds in process.
   */
  it(
    "prints the reporter's refusal where an operator reads it",
    () => {
      write(oneTestOut());

      const run = runThere();
      const recorded = refusedLines(run, "reporter");

      expect(recorded, EMPTY_CHANNEL).not.toHaveLength(0);
      for (const line of recorded)
        expect(run.stderr, childState(run, "reporter")).toContain(line);
    },
    SPAWNED + 30_000,
  );

  it(
    "prints the global setup's refusal where an operator reads it",
    () => {
      write(registerFor(body, rows));

      const run = runThere("--reporter=default");
      const recorded = refusedLines(run, "globalSetup");

      expect(recorded, EMPTY_CHANNEL).not.toHaveLength(0);
      for (const line of recorded)
        expect(run.stderr, childState(run, "globalSetup")).toContain(line);
    },
    SPAWNED + 30_000,
  );
});
