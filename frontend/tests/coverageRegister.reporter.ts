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
 * **Only its counts answer for a run that collected the whole tree.** A
 * narrowed run would report every filtered file's own count as a fraction of
 * its row, which is a guard that cries wolf until somebody deletes it. The
 * rules about which files the document names do not depend on running any of
 * them, so they are asked of vitest's discovery and hold on any green run.
 * `isWhole` is where that line is drawn and `problems` is what honours it.
 *
 * **The two sides can disagree, and both branches below are for a way they
 * do.** A run can take fewer files than were discovered, which is an ordinary
 * narrowing; and it can take as many under different names, which is the two
 * instruments having stopped spelling the same tree and is refused outright.
 * A sentence here saying they cannot is read as covering both, and what it
 * costs is a size test nobody keeps.
 *
 * **The backend half's own fail open has no twin here, and that is measured
 * rather than assumed.** Two things of vitest's make it so. A name pattern
 * marks a matching task `skip` rather than removing it, and `allTests()`
 * yields a skipped task, so no count moves; the backend's equivalent
 * deselects the item outright and leaves its gate open on a figure that is
 * one low. And the per file slot is created for every file discovered, so a
 * file collecting nothing is present with a count of 0 rather than absent,
 * which is the whole reason the backend half needs a row of 0 and this one
 * does not. **A caveat missing beside a twin that carries one reads as
 * forgotten**, so both are written here rather than left out as inapplicable.
 *
 * **The always on rules fire at different moments in the two halves.** There
 * they are arms inside a file a narrowed run may not collect at all; here
 * they are a reporter, so they run on every invocation, a single file debug
 * run included. The asymmetry is wanted: a register this run can already
 * contradict reaches a person sooner on this side.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import {
  type Census,
  THIS_REGISTER,
  countWrittenOut,
  declaresItselfInternal,
  isWhole,
  printWhole,
  problems,
  writeInstruction,
  writeLine,
} from "./coverageRegister";
import { MARKER, OWNER } from "./coverageRegister.globalSetup";

/**
 * Set to `off` by the plant harness for every arm it runs: the register is
 * red by construction on a branch that adds a test, so a plant's baseline
 * would refuse exactly there. Only that word turns this reporter off; the
 * suite runner refuses any other value before a run starts.
 */
export const SWITCH = "ENDPAPER_COVERAGE_REGISTER";

export default class CoverageRegisterReporter {
  private vitest: {
    projects?: {
      config: { root: string };
      globTestFiles?: () => Promise<{ testFiles: string[] }>;
    }[];
  } = {};

  /**
   * Where the write goes: standard output in a run, a file in the arm that
   * drives this hook in process, because a worker's own standard output is
   * the run's artefact too. A write printed there is read as a second write
   * for this register and refuses the real one at merge.
   */
  private readonly out: number;

  constructor(options: { out?: number } = {}) {
    this.out = options.out ?? 1;
  }

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
    const found = (await project.globTestFiles()).testFiles;
    const discovered = found.map(here);
    const ran = modules.map((module) => here(module.moduleId));

    // **Whether a file is one the register may not name is a property of the
    // file**, so it is read for everything vitest discovered rather than for
    // what this run executed. Read once and keyed by the relative path,
    // because the loop below wants the same bytes for the files that ran.
    const sources = new Map<string, string>();
    for (const file of found)
      sources.set(here(file), readFileSync(file, "utf8"));
    const internal = new Set(
      [...sources]
        .filter(([, source]) => declaresItselfInternal(source))
        .map(([file]) => file),
    );

    const counts = new Map<string, number>();
    const writtenOut = new Map<string, number>();
    for (const module of modules) {
      const file = here(module.moduleId);
      // A module outside what the glob discovered has no entry above. It is
      // read here rather than defaulted, because a figure counted off an empty
      // string is a wrong number where a second read is the right one.
      const source = sources.get(file) ?? readFileSync(module.moduleId, "utf8");
      counts.set(file, [...module.children.allTests()].length);
      writtenOut.set(file, countWrittenOut(source, file));
    }

    const census: Census = {
      discovered: new Set(discovered),
      counts,
      writtenOut,
      internal,
    };

    // **Counted first, then compared, and the order is what decides which
    // failure is silent.** A narrowed run is ordinary and says so; a run of the
    // right size over a different set of names means the two sides have stopped
    // spelling the same tree, and comparing sets first would turn that into a
    // guard that skips every run from then on with nothing said.
    if (!isWhole(census))
      console.log(
        `coverage register: counts not checked, this run took ${ran.length} ` +
          `of ${discovered.length} test files. The rules about which files ` +
          "the document names still ran.",
      );
    else {
      const missing = discovered.filter((file) => !ran.includes(file));
      if (missing.length > 0)
        throw new Error(
          "the coverage register reporter ran over as many files as vitest " +
            `discovered and not the same ones: ${missing.join(", ")} was ` +
            "discovered and did not run.",
        );
    }

    // **Here, where the document is read**, so the checks above about the run
    // itself still run under the switch, as they do in the backend half.
    // Printed, so the run's own output says what it did not check. A pipeline
    // runs vitest directly rather than through the suite runner, so there a CI
    // variable carrying the switch fails the run instead of passing it unchecked.
    if (process.env[SWITCH] === "off") {
      if (process.env.GITLAB_CI !== undefined)
        throw new Error(
          `${SWITCH}=off is for a plant copy, and this run is a pipeline.`,
        );
      console.log(
        `coverage register: not checked, ${SWITCH}=off. No write is offered.`,
      );
      return;
    }

    const itsRegister = join(testRoot, "COVERAGE.md");
    const register = readFileSync(itsRegister, "utf8");

    // **Printed, never applied.** This process is the one checking the
    // register, so it is the one process that must not write it: a guard that
    // heals itself asserts nothing. What it does instead is put the whole
    // write on one line of the run's own output, where a separate and
    // deliberate invocation can pick it up. `printWhole` is what makes that
    // line whole at any length; its comment says what `console.log` lost
    // here. Nothing here opens the register
    // for writing, and the global setup fails the run if anything else does.
    //
    // **And only a run about this repository's own register offers one.** A
    // write names a fixed path while these figures are whichever run's they
    // are, and this suite spawns runs over fixture libraries that import
    // this very module. Without this question such a child printed a well
    // formed write naming the real register and carrying the fixture's
    // counts, onto a stream two arms assert against and therefore into an
    // artefact. The problems below are still reported, because they are
    // true about the document this run read.
    //
    // **What this question catches and what it does not**, because a cross
    // check written here caught neither and claimed both.
    //
    // It catches a run that wrongly believes a register is its own, which
    // is the direction that writes a figure into the wrong document. That
    // is driven end to end by a nested run over a fixture library.
    //
    // **It does not catch the gate wrongly closed**, which is a write
    // withheld forever and reads downstream as the other register being
    // current. A change to this code is covered by the in process witness
    // in `coverageRegister.test.ts`, which drives this hook with this
    // repository's own root and requires a write. **A change to the
    // environment is covered by nothing**: a root the comparison never
    // recognises, a symlinked checkout being the measured case, is silence
    // at exit 0 and no arm here sees it.
    //
    // A second derivation from the working directory was tried and
    // deleted. Gated on the question being open it cannot see the closed
    // direction at all, and ungated it throws on every nested run, because
    // the working directory does not follow a root flag and the two
    // disagree there by construction.
    //
    // **What keeps this true today is a condition the runner guarantees by
    // accident**: it ships the tree into a container and starts the suite
    // with the project root as the real path this module resolves to, so
    // the comparison holds without anything asserting that it must.
    const instruction =
      itsRegister === THIS_REGISTER ? writeInstruction(register, census) : null;
    // **This is the one print site, and nothing holds that it stays one.** A
    // second print beside it is seen by no arm here, and it matters in one
    // shape: a `console.log` of a write past 65,536 bytes, kept for debugging
    // say, puts a cut copy beside the whole one, and the applier refuses the
    // artefact at merge rather than the run failing. A second `printWhole`,
    // or a shorter write, prints two identical copies, which are read as one.
    if (instruction !== null) printWhole(writeLine(instruction), this.out);

    const wrong = problems(register, census);
    if (wrong.length > 0)
      throw new Error(
        `tests/COVERAGE.md does not describe this run:\n\n${wrong.join("\n\n")}`,
      );
  }
}
