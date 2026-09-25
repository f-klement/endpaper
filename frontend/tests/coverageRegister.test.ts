/**
 * @vitest-environment node
 *
 * The register guard, and the one thing a unit test cannot say about it: that
 * being wired into the config it is wired into actually fails a run.
 */
import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  mkdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  BEGIN,
  END,
  type Census,
  blockOf,
  covers,
  problems,
  render,
  rowsOf,
} from "./coverageRegister";
import { MARKER } from "./coverageRegister.globalSetup";

const census = (
  counts: Record<string, number>,
  writtenOut: Record<string, number> = counts,
  internal: string[] = [],
): Census => ({
  counts: new Map(Object.entries(counts)),
  writtenOut: new Map(Object.entries(writtenOut)),
  internal: new Set(internal),
});

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
      "`gone/*` matches no file this run collected",
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

  it("names a file no row covers rather than counting it", () => {
    const body = census({ ...counts, "orphan.test.ts": 3 });
    const register = registerFor(census(counts), rows);

    expect(problems(register, body).join("\n")).toContain(
      "these files have no row: orphan.test.ts",
    );
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
    expect(render(body, ["a.test.ts"])).toContain(
      "**12 are written out and 4 are generated**, over the 1 file that generate",
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
 * below passes only if the half it names threw the message it names. Three arms
 * read the child's stderr for that instead, and it is the wrong instrument for
 * that question: the text an `Error` prints is built when something first reads
 * its `.stack`, by whichever `Error.prepareStackTrace` is installed at that
 * moment, and vitest reassigns that global while it runs. So a refusal thrown
 * here was formatted there.
 *
 * **Whether a refusal is readable is a different question, and it keeps two
 * arms of its own at the bottom**, one for each of the two routes vitest prints
 * by. Their docstring holds the measurement, and the second of them is the only
 * arm in this file that notices the failure that opened this subject.
 */
describe("the reporter fails a run", () => {
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

  let spawned = 0;

  type Refusal = { from: string; message: string };
  type Run = { status: number | null; stderr: string; refusals: Refusal[] };

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
   * cores rather than the pod's limit, and these forks are grandchildren the
   * timeout above does not reach. Two files need no parallelism at all.
   */
  const SPAWNED = 60_000;

  const runThere = (...flags: string[]): Run => {
    const channel = join(fixture, `refusals.${(spawned += 1)}.jsonl`);
    writeFileSync(channel, "");
    const run = spawnSync(
      join(root, "node_modules", ".bin", "vitest"),
      ["run", "--root", fixture, ...flags],
      {
        cwd: root,
        encoding: "utf8",
        timeout: SPAWNED,
        killSignal: "SIGKILL",
        env: { ...process.env, [CHANNEL]: channel },
      },
    );
    return {
      status: run.status,
      stderr: run.stderr,
      refusals: readFileSync(channel, "utf8")
        .split("\n")
        .filter((line) => line !== "")
        .map((line) => JSON.parse(line) as Refusal),
    };
  };

  /** Every message that half of the guard threw, and nothing else's. */
  const refused = (run: Run, from: string): string =>
    run.refusals
      .filter((refusal) => refusal.from === from)
      .map((refusal) => refusal.message)
      .join("\n");

  beforeAll(() => {
    fixture = mkdtempSync(join(tmpdir(), "endpaper-register-"));
    mkdirSync(join(fixture, "tests"));

    const real = (name: string) => JSON.stringify(join(root, "tests", name));

    // **These three files are strings, and nothing in the gate reads them.**
    // prettier does not format a template literal's contents, oxlint sees no
    // code there and `tsc` sees a string, so the middle of this guard is the
    // one part of the tree no check covers.
    //
    // The annotation in the reporter wrapper looks like a compile time link to
    // the hook's name and is not one. The wrapper spells `onTestRunEnd` as a
    // literal, so a vitest release renaming that hook, correctly followed in
    // `coverageRegister.reporter.ts`, leaves the wrapper's `catch` unreached:
    // the two arms that read the channel then redden on an empty file while
    // the guard itself is working. **That is what a red on an empty channel
    // means**, and it is a false red rather than a miss. The same upgrade was
    // green while those arms read the child's stderr, so this is a cost of the
    // channel and not a defect in it.

    writeFileSync(
      join(fixture, "record.ts"),
      `import { appendFileSync } from "node:fs";

export function record(from: string, error: unknown): void {
  const channel = process.env[${JSON.stringify(CHANNEL)}];
  if (channel === undefined) return;
  const message = error instanceof Error ? error.message : String(error);
  appendFileSync(channel, JSON.stringify({ from, message }) + "\\n");
}
`,
    );

    // **The fixture config names these wrappers, and the real files are what
    // run inside them.** The reporter wrapper extends the real class, so it is
    // the real `onTestRunEnd` that decides; the setup wrapper re-exports the
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
  async onTestRunEnd(
    ...args: Parameters<InstanceType<typeof Real>["onTestRunEnd"]>
  ): Promise<void> {
    try {
      await super.onTestRunEnd(...args);
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

    writeFileSync(
      join(fixture, "vitest.config.ts"),
      "export default { test: { globals: true, include: ['tests/**/*.test.ts'], " +
        "maxWorkers: 1, minWorkers: 1, " +
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
   * The arms above ask which refusal fired, which the stream cannot answer
   * without also answering for vitest's formatting. These ask the different
   * question the block would otherwise stop covering: that a refusal reaches a
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
   * That is measured rather than supposed. Assigning
   * `Error.prepareStackTrace = () => "Error"` inside the child reduces the
   * second arm's stream to `error during close [Error]` and leaves the first
   * arm's untouched. **The second arm is the only thing in this file that goes
   * red under it**, which is why it is here rather than left to the channel.
   */
  it(
    "prints the reporter's refusal where an operator reads it",
    () => {
      write(oneTestOut());

      const { stderr } = runThere();

      expect(stderr).toContain("tests/COVERAGE.md does not describe this run");
      expect(stderr).toContain(
        "`a.test.ts`: the register says 3, the run counted 2 over 1 file",
      );
    },
    SPAWNED + 30_000,
  );

  it(
    "prints the global setup's refusal where an operator reads it",
    () => {
      write(registerFor(body, rows));

      expect(runThere("--reporter=default").stderr).toContain(
        "the coverage register reporter did not run, so tests/COVERAGE.md was",
      );
    },
    SPAWNED + 30_000,
  );
});
