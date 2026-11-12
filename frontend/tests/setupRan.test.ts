/**
 * @vitest-environment node
 */

/**
 * A test that passed without `tests/setup.ts` fails the run, by file.
 *
 * **The reporter is driven in process here and on a real run by hand.** A
 * nested run of the defect would need `vitest related`, whose graph walk was
 * measured at 25 s on every full run (`relatedRun.test.ts` says so). The
 * real run was measured when this was written: setup planted to register its
 * mark once per worker under `vitest run`, and a related run with the refusal
 * removed, each red naming every later file.
 */

import {
  closeSync,
  mkdtempSync,
  openSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import SetupRanReporter, {
  type FinishedModule,
  withoutSetup,
} from "./setupRan.reporter";

function test(state: string, setUp: boolean) {
  return {
    meta: () => (setUp ? { setUp: true as const } : {}),
    result: () => ({ state }),
  };
}

function file(
  name: string,
  tests: ReturnType<typeof test>[],
  root = "/root",
): FinishedModule {
  return { moduleId: join(root, name), children: { allTests: () => tests } };
}

describe("withoutSetup", () => {
  it("passes a run whose every passed test was set up", () => {
    expect(
      withoutSetup([file("tests/a.test.ts", [test("passed", true)])], "/root"),
    ).toEqual([]);
  });

  it("names a file whose tests passed without the setup, with the count", () => {
    expect(
      withoutSetup(
        [
          file("tests/a.test.ts", [test("passed", true)]),
          file("tests/b.test.ts", [
            test("passed", false),
            test("passed", false),
          ]),
        ],
        "/root",
      ),
    ).toEqual(["tests/b.test.ts (2 test(s))"]);
  });

  it("does not ask a failed or skipped test, which may have run no hook", () => {
    expect(
      withoutSetup(
        [
          file("tests/a.test.ts", [
            test("failed", false),
            test("skipped", false),
          ]),
        ],
        "/root",
      ),
    ).toEqual([]);
  });
});

describe("the reporter", () => {
  it("throws at the end of a run that holds a test without setup, naming it", () => {
    const dir = mkdtempSync(join(tmpdir(), "setup-ran-"));
    const out = join(dir, "err");
    const fd = openSync(out, "w");
    try {
      const reporter = new SetupRanReporter({ err: fd });
      expect(() =>
        reporter.onTestRunEnd([
          file("tests/b.test.ts", [test("passed", false)], process.cwd()),
        ]),
      ).toThrow("Pass --isolate");
      expect(readFileSync(out, "utf8")).toContain(
        "the setup guard refused this run:\nthese files",
      );
      expect(readFileSync(out, "utf8")).toContain(
        "  tests/b.test.ts (1 test(s))",
      );
    } finally {
      closeSync(fd);
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("the guard is wired into the suite it guards", () => {
  it("marks a test the setup ran for", ({ task }) => {
    expect(task.meta.setUp).toBe(true);
  });

  it("is a reporter of this configuration", () => {
    const config = readFileSync(
      join(import.meta.dirname, "..", "vite.config.ts"),
      "utf8",
    );

    expect(config).toContain('"./tests/setupRan.reporter.ts"');
  });
});
