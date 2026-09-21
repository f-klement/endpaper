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
 */
describe("the reporter fails a run", () => {
  const root = join(import.meta.dirname, "..");
  let fixture: string;

  const write = (register: string) =>
    writeFileSync(join(fixture, "tests", "COVERAGE.md"), register);

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

  const runThere = (...flags: string[]) =>
    spawnSync(
      join(root, "node_modules", ".bin", "vitest"),
      ["run", "--root", fixture, ...flags],
      {
        cwd: root,
        encoding: "utf8",
        timeout: SPAWNED,
        killSignal: "SIGKILL",
      },
    );

  beforeAll(() => {
    fixture = mkdtempSync(join(tmpdir(), "endpaper-register-"));
    mkdirSync(join(fixture, "tests"));
    writeFileSync(
      join(fixture, "vitest.config.ts"),
      "export default { test: { globals: true, include: ['tests/**/*.test.ts'], " +
        "maxWorkers: 1, minWorkers: 1, " +
        `globalSetup: [${JSON.stringify(join(root, "tests", "coverageRegister.globalSetup.ts"))}], ` +
        `reporters: ['default', ${JSON.stringify(join(root, "tests", "coverageRegister.reporter.ts"))}] } };\n`,
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

  it(
    "passes a register that states what the run counted",
    () => {
      write(registerFor(body, rows));

      expect(runThere().status).toBe(0);
    },
    SPAWNED + 30_000,
  );

  it(
    "fails a run whose register is one test out, naming the row",
    () => {
      write(
        registerFor(body, rows).replace(
          "| `a.test.ts` | 2 |",
          "| `a.test.ts` | 3 |",
        ),
      );

      const run = runThere();

      expect(run.status).toBe(1);
      expect(run.stderr).toContain(
        "`a.test.ts`: the register says 3, the run counted 2",
      );
    },
    SPAWNED + 30_000,
  );

  it(
    "fails a run whose reporters a command line flag replaced",
    () => {
      write(registerFor(body, rows));

      const run = runThere("--reporter=default");

      expect(run.status).toBe(1);
      expect(run.stderr).toContain(
        "the coverage register reporter did not run",
      );
    },
    SPAWNED + 30_000,
  );

  it(
    "fails a run whose register has no row for a file",
    () => {
      write(registerFor(body, rows.slice(0, 1)));

      const run = runThere();

      expect(run.status).toBe(1);
      expect(run.stderr).toContain("these files have no row: b.test.ts");
    },
    SPAWNED + 30_000,
  );
});
