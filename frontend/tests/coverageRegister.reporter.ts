/**
 * Fails the run when `tests/COVERAGE.md` does not describe it.
 *
 * **A reporter rather than a test, and the reason is measured.** A test file
 * can see its own tasks and nothing else, so no test in this suite can see
 * which files the suite holds and which of them collected a test. vitest's
 * own discovery and the run's own modules are both here.
 *
 * **Throwing here fails the run**, measured 2026-09-20 on vitest 5.0.0: vitest
 * awaits each reporter's hook and reports what it throws as an unhandled
 * error, exiting 1. `coverageRegister.test.ts` drives a whole vitest run
 * against a fixture tree to hold that, because a reporter wired up wrong is
 * silent in exactly the direction that matters.
 *
 * **Every rule here but one holds on a narrowed run.** Which files the
 * document names is asked of vitest's discovery rather than of what ran, so a
 * run of one file still refuses a row naming nothing and a file with no row;
 * and a file collecting nothing is asked of the files that ran. So those rules
 * run on every invocation, a single file debug run included, where the backend
 * half's are arms inside a file a narrowed run may not collect. **The one that
 * does not** is the refusal of a test that would not run, which a run vitest
 * narrowed inside a file cannot ask: see `narrowedInside`.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import {
  type Census,
  declaresItselfInternal,
  problems,
  refusal,
} from "./coverageRegister";
import { MARKER, OWNER } from "./coverageRegister.globalSetup";

/** One collected test, as much of vitest's `TestCase` as this reads. */
type Collected = {
  fullName: string;
  options: { mode: string; fails?: boolean };
  result(): { state: string };
};

/** The parts of a test specification that narrow a run inside a file. */
type Specification = {
  testLines?: readonly number[];
  testIds?: readonly string[];
  testNamePattern?: RegExp;
  testTagsFilter?: readonly string[];
};

/** Why a collected test would not run, or `undefined` for one that runs. */
function whyItWouldNotRun(test: Collected): string | undefined {
  if (test.options.fails === true) return "expected to fail";
  if (test.result().state !== "skipped") return undefined;
  return test.options.mode === "todo" ? "todo" : "skipped";
}

export default class CoverageRegisterReporter {
  private vitest: {
    projects?: {
      config: { root: string };
      globTestFiles?: () => Promise<{ testFiles: string[] }>;
    }[];
    getGlobalTestNamePattern?: () => RegExp | undefined;
    config?: { tagsFilter?: readonly string[] };
  } = {};

  /**
   * Whether a specification of this run narrows it inside a file, which
   * `onTestRunStart` is the one hook to see.
   */
  private specified = false;

  /**
   * Where a refusal is printed: standard error in a run, a file in the arms
   * that drive this hook in process, because a worker's own standard error is
   * the outer run's log and a refusal there would read as one of the run's.
   */
  private readonly err: number;

  constructor(options: { err?: number } = {}) {
    this.err = options.err ?? 2;
  }

  onInit(vitest: typeof this.vitest): void {
    this.vitest = vitest;
  }

  onTestRunStart(specifications: readonly Specification[]): void {
    this.specified = specifications.some(
      (specification) =>
        (specification.testLines?.length ?? 0) > 0 ||
        (specification.testIds?.length ?? 0) > 0 ||
        specification.testNamePattern !== undefined ||
        (specification.testTagsFilter?.length ?? 0) > 0,
    );
  }

  /**
   * Whether vitest narrowed this run inside a file.
   *
   * **vitest marks a test its filter left out exactly as it marks `it.skip`**,
   * so on such a run every filtered test would read as one that would not run.
   * The conditions are vitest 5's own for a partial run (`isPartialRun`): a
   * name pattern, a line, a test id or a tag, on the command line or on a
   * specification. Its last, a focused test, is left to `onTestRunEnd`,
   * because a focus narrows only the file holding it: that file is left out
   * and every other one judged, so one focus does not hide a skip elsewhere.
   * A vitest that moves the global pattern is refused rather than read as
   * unfiltered, which is the direction that would refuse every `-t` run.
   */
  private narrowedInside(): boolean {
    if (typeof this.vitest.getGlobalTestNamePattern !== "function")
      throw refusal(
        "the coverage register reporter could not read this run's test name " +
          "pattern, so it cannot tell a test vitest filtered out from one a " +
          "file skips. A vitest upgrade that moves it has to be followed here.",
        this.err,
      );
    return (
      this.specified ||
      this.vitest.getGlobalTestNamePattern() !== undefined ||
      (this.vitest.config?.tagsFilter?.length ?? 0) > 0
    );
  }

  async onTestRunEnd(
    modules: readonly {
      moduleId: string;
      task?: { containsOnly?: boolean };
      children: { allTests(): Iterable<Collected> };
    }[],
    _errors: readonly unknown[],
    reason: string,
  ): Promise<void> {
    // **Written before anything below decides, the early return included.** The
    // marker says this hook ran, which is the one thing a global setup can ask
    // and a command line `--reporter` can take away; what the hook then finds is
    // this reporter's own to report.
    const marker = process.env[MARKER];
    if (marker !== undefined && process.env[OWNER] === String(process.pid))
      writeFileSync(marker, "");

    // A red run has already failed, and a register checked against an
    // interrupted one would compare against whatever had finished. The next
    // green run is where this speaks.
    if (reason !== "passed") return;

    const [project, ...rest] = this.vitest.projects ?? [];
    if (
      !project ||
      rest.length > 0 ||
      typeof project.globTestFiles !== "function"
    )
      throw refusal(
        "the coverage register reporter could not read this run's project. It " +
          "is reading vitest's own test discovery, so a vitest upgrade that " +
          "moves it has to be followed here rather than silently skipped.",
        this.err,
      );

    const testRoot = join(project.config.root, "tests");
    const here = (file: string) =>
      relative(testRoot, file).replaceAll("\\", "/");
    const found = (await project.globTestFiles()).testFiles;
    const discovered = new Set(found.map(here));

    // **A module that ran and was not discovered escapes every row rule**,
    // which reads discovery, so it is refused rather than judged. It means the
    // two instruments have stopped spelling the same tree.
    const strays = modules
      .map((module) => here(module.moduleId))
      .filter((file) => !discovered.has(file));
    if (strays.length > 0)
      throw refusal(
        "the coverage register reporter saw files run that vitest's discovery " +
          `did not return: ${strays.join(", ")}.`,
        this.err,
      );

    // **Whether a file is one the register may not name is a property of the
    // file**, so it is read for everything vitest discovered rather than for
    // what this run executed.
    const internal = new Set(
      found
        .filter((file) => declaresItselfInternal(readFileSync(file, "utf8")))
        .map(here),
    );
    const counts = new Map(
      modules.map((module) => [
        here(module.moduleId),
        [...module.children.allTests()].length,
      ]),
    );
    const wouldNotRun = this.narrowedInside()
      ? []
      : modules
          .filter((module) => module.task?.containsOnly !== true)
          .flatMap((module) =>
            [...module.children.allTests()].flatMap((test) => {
              const why = whyItWouldNotRun(test);
              return why === undefined
                ? []
                : [`${here(module.moduleId)} > ${test.fullName} (${why})`];
            }),
          );
    const census: Census = { discovered, counts, internal, wouldNotRun };

    const register = readFileSync(join(testRoot, "COVERAGE.md"), "utf8");
    const wrong = problems(register, census);
    if (wrong.length > 0)
      throw refusal(
        `tests/COVERAGE.md does not describe this run:\n\n${wrong.join("\n\n")}`,
        this.err,
      );
  }
}
