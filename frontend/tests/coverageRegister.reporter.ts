/**
 * Fails the run when `tests/COVERAGE.md` disagrees with it.
 *
 * **A reporter rather than a test, and the reason is measured.** A test file
 * can see its own tasks and nothing else, so no test in this suite can count
 * the suite. The only listing vitest offers without running, `vitest list`, is
 * a static read: it answers 7 for `api/query-client.test.ts` where the run
 * collects 16, and 3,399 for the tree where the run collects 3,885, because it
 * counts an `it.each` as one. Measured 2026-09-20 on vitest 5.0.0. A register
 * checked against that instrument would be wrong about every generated case,
 * which is most of what this one gets wrong by hand.
 *
 * **Throwing here fails the run**, measured on the same day: vitest awaits each
 * reporter's hook and reports what it throws as an unhandled error, exiting 1.
 * `coverageRegister.test.ts` drives a whole vitest run against a fixture tree
 * to hold that, because a reporter wired up wrong is silent in exactly the
 * direction that matters.
 *
 * **It answers only for a run that collected the whole tree.** A narrowed run
 * would report every other row as missing and every filtered file's own count
 * as a fraction of its row, which is a guard that cries wolf until somebody
 * deletes it. The file set comes from vitest's own discovery rather than from a
 * second glob, so it cannot disagree with what a full run would have collected.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import {
  type Census,
  WRITTEN_OUT,
  declaresItselfInternal,
  problems,
} from "./coverageRegister";
import { MARKER, OWNER } from "./coverageRegister.globalSetup";

export default class CoverageRegisterReporter {
  private vitest: {
    projects?: {
      config: { root: string };
      globTestFiles?: () => Promise<{ testFiles: string[] }>;
    }[];
  } = {};

  onInit(vitest: typeof this.vitest): void {
    this.vitest = vitest;
  }

  async onTestRunEnd(
    modules: readonly {
      moduleId: string;
      children: { allTests(): Iterable<unknown> };
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
      throw new Error(
        "the coverage register reporter could not read this run's project. It " +
          "is reading vitest's own test discovery, so a vitest upgrade that " +
          "moves it has to be followed here rather than silently skipped.",
      );

    const testRoot = join(project.config.root, "tests");
    const here = (file: string) =>
      relative(testRoot, file).replaceAll("\\", "/");
    const discovered = (await project.globTestFiles()).testFiles.map(here);
    const ran = modules.map((module) => here(module.moduleId));

    if (ran.length !== discovered.length) {
      console.log(
        `coverage register: not checked, this run took ${ran.length} of ` +
          `${discovered.length} test files`,
      );
      return;
    }

    // **Counted first, then compared, and the order is what decides which
    // failure is silent.** A narrowed run is ordinary and says so; a run of the
    // right size over a different set of names means the two sides have stopped
    // spelling the same tree, and comparing sets first would turn that into a
    // guard that skips every run from then on with nothing said.
    const missing = discovered.filter((file) => !ran.includes(file));
    if (missing.length > 0)
      throw new Error(
        "the coverage register reporter ran over as many files as vitest " +
          `discovered and not the same ones: ${missing.join(", ")} was ` +
          "discovered and did not run.",
      );

    const counts = new Map<string, number>();
    const writtenOut = new Map<string, number>();
    const internal = new Set<string>();
    for (const module of modules) {
      const file = here(module.moduleId);
      const source = readFileSync(module.moduleId, "utf8");
      counts.set(file, [...module.children.allTests()].length);
      writtenOut.set(file, (source.match(WRITTEN_OUT) ?? []).length);
      if (declaresItselfInternal(source)) internal.add(file);
    }

    const census: Census = { counts, writtenOut, internal };
    const found = problems(
      readFileSync(join(testRoot, "COVERAGE.md"), "utf8"),
      census,
    );
    if (found.length > 0)
      throw new Error(
        `tests/COVERAGE.md does not describe this run:\n\n${found.join("\n\n")}`,
      );
  }
}
