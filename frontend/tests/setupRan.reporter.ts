/**
 * Fails the run when a test passed without `tests/setup.ts` having run for it.
 *
 * **Every guard in that setup is silent in exactly the case where the setup is
 * missing**, because the guard is the setup. Under `vitest related` with
 * `isolate: false`, vitest 5.0.5 evaluated it once per worker and environment
 * rather than once per file, so most files ran with no cleanup, no storage
 * cleared and no guard, and nothing said so: the symptom was a test red only
 * in company. `relatedRun.globalSetup.ts` refuses that command by name; this
 * asks the symptom, so a vitest upgrade that spreads it to another command is
 * red rather than quiet.
 *
 * **How**: the setup's first `beforeEach` sets `setUp` on the test's meta, and
 * this reads it back from every test that **passed**, because a passed test
 * ran its `beforeEach` hooks. A failed test may have stopped in a `beforeAll`
 * before any hook, and a skipped one ran none, so neither is asked: the first
 * is red already and the second proves nothing.
 *
 * A reporter, not a test, for the reason `coverageRegister.reporter.ts` gives:
 * only a reporter sees every file's tests. A `--reporter` on the command line
 * drops it together with that one. `coverageRegister.globalSetup.ts` fails
 * such a run, and its refusal names both to keep; but it checks only for its
 * own, so a run naming that one back alone drops this one silently.
 */

import { relative } from "node:path";

import { printWhole } from "./coverageRegister";

declare module "vitest" {
  export interface TaskMeta {
    /** Set by `tests/setup.ts` before each test it saw; read here. */
    setUp?: true;
  }
}

/** One test as much of vitest's `TestCase` as this reads. */
type Finished = {
  meta(): { setUp?: true };
  result(): { state: string };
};

/** One test file of the run, as much of vitest's `TestModule` as this reads. */
export type FinishedModule = {
  moduleId: string;
  children: { allTests(): Iterable<Finished> };
};

/**
 * Each file holding a test that passed with no setup, and how many did,
 * relative to `root`.
 */
export function withoutSetup(
  modules: readonly FinishedModule[],
  root: string,
): string[] {
  return modules.flatMap((module) => {
    const bare = [...module.children.allTests()].filter(
      (test) => test.result().state === "passed" && test.meta().setUp !== true,
    ).length;
    return bare === 0
      ? []
      : [`${relative(root, module.moduleId)} (${bare} test(s))`];
  });
}

export default class SetupRanReporter {
  private readonly err: number;

  /** `err` is for an arm driving this in process; standard error otherwise. */
  constructor(options: { err?: number } = {}) {
    this.err = options.err ?? 2;
  }

  onTestRunEnd(modules: readonly FinishedModule[]): void {
    const bare = withoutSetup(modules, process.cwd());
    if (bare.length === 0) return;
    const message =
      "these files ran tests without tests/setup.ts, so with no cleanup, " +
      "no storage cleared and none of its guards; a green among them " +
      "proves nothing. vitest stopped evaluating the setup per file for " +
      "this command, as `vitest related` without --isolate does; " +
      "tests/setupRan.reporter.ts says why. Pass --isolate:\n  " +
      bare.join("\n  ");
    printWhole(`the setup guard refused this run:\n${message}`, this.err);
    throw new Error(message);
  }
}
