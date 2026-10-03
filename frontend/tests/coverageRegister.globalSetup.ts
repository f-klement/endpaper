/**
 * Fails the run when the coverage register reporter did not report.
 *
 * **A reporter can be switched off from the command line, and silently.** A
 * `--reporter` on the CLI **replaces** the configured set rather than adding to
 * it, so `vitest run --reporter=junit` runs with none of the reporters
 * `vite.config.ts` names. Measured on vitest 5.0.0 against a fixture library:
 * with the flag, the marker below is absent and the register is checked
 * nowhere; without it, present. The pipeline's frontend job passed that flag
 * for its junit output, so the guard would have run nowhere that matters, and
 * its own end to end test would have stayed green, because that test names the
 * reporter explicitly.
 *
 * A global setup is not replaceable from the command line, which is the whole
 * reason this half exists rather than a rule about how the pipeline invokes the
 * suite. It asserts only that the reporter's hook **ran**: what it found is the
 * reporter's own to report, and it writes the marker before it decides, so a
 * stale register fails once rather than twice.
 *
 * The path travels in the environment rather than being a fixed name, so the
 * nested runs `coverageRegister.test.ts` spawns cannot satisfy or clear the
 * outer run's marker. A child inherits the variable and its own setup replaces
 * it before its own reporter reads it. The count of those runs is deliberately
 * not written here: it moves whenever an arm is added, and a figure beside a
 * rule is read as current long after it stops being so.
 */

import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

export const MARKER = "ENDPAPER_COVERAGE_REGISTER_MARKER";

/**
 * The process whose setup made that path.
 *
 * **A child inherits the variable, and only a convention stops it satisfying
 * its parent's marker.** Every nested run this suite spawns reaches this setup,
 * through the wrapper that fixture writes around it, so each replaces the path
 * in its own process before its own reporter reads it, and the guarantee rests
 * on every future one remembering to. The pid makes it structural: a reporter
 * writes only where its own setup ran.
 */
export const OWNER = "ENDPAPER_COVERAGE_REGISTER_OWNER";

/**
 * The register this run is about to check, as it stood when the run began.
 *
 * **A run must not write the document it is checking. A guard that heals
 * itself asserts nothing**, so the write is a separate invocation and this is
 * what makes that true rather than saying it. The figures a run measures are
 * printed, and whether anything then applies them is somebody else's
 * deliberate act.
 *
 * **Closed over the mechanism rather than over the spelling.** A rule
 * forbidding one way of writing a file is a list of the ways somebody has
 * thought of; this compares the bytes either side of the run, so a write from
 * the reporter, from a test, from a setup file or from a plugin is one
 * failure with one name. What it does not cover is said at the refusal.
 *
 * `null` where the file is absent, which is what a fixture tree has, so the
 * comparison is between two readings rather than between a reading and an
 * assumption.
 */
let registerWhenTheRunBegan: string | null = null;

/**
 * The register of the run in hand, which is not always this tree's.
 *
 * **Read off the project vitest is running**, so a run over a fixture library
 * guards that library's register rather than this repository's. That is what
 * makes the rule drivable end to end: a nested run can be made to rewrite its
 * own document, which is the attempt, and no arm has to rewrite the register
 * this suite is checking to show that the refusal works.
 *
 * **Refused rather than defaulted when vitest does not offer it.** A default
 * here is a path somebody will believe, and the one it would fall back to is
 * this repository's own register, so a vitest change that moved this would
 * leave every run guarding the wrong file and saying nothing. The reporter
 * takes the same stance about the same object and for the same reason.
 */
let register: string | null = null;

/**
 * One document as one short string, or the word for not having one.
 *
 * **Exported so it has a diagonal, and shaped like the backend's.** That half
 * answers `"absent"` for a missing file and has an arm driving both answers;
 * this one returned `null` and had none, so a reading that answered one
 * constant would have satisfied every arm by never moving. The absent case is
 * not reachable in this tree today, which is exactly why the arm is what
 * would catch it becoming so.
 *
 * Size beside the digest because a refusal naming two hashes says a file
 * moved and nothing else, and the direction is usually the first question.
 */
export function registerReading(path: string): string {
  if (!existsSync(path)) return "absent";
  const bytes = readFileSync(path);
  return `${bytes.length} bytes, ${createHash("sha256").update(bytes).digest("hex")}`;
}

function registerDigest(): string | null {
  return register === null ? null : registerReading(register);
}

export function setup(project?: { config?: { root?: string } }): void {
  const root = project?.config?.root;
  if (typeof root !== "string")
    throw new Error(
      "the coverage register guard could not read this run's project root, " +
        "so it cannot say which COVERAGE.md this run is checking. It is " +
        "reading vitest's own global setup argument, so a vitest upgrade " +
        "that moves it has to be followed here rather than silently skipped.",
    );
  register = join(root, "tests", "COVERAGE.md");
  registerWhenTheRunBegan = registerDigest();
  process.env[MARKER] = join(
    mkdtempSync(join(tmpdir(), "endpaper-register-run-")),
    "reported",
  );
  process.env[OWNER] = String(process.pid);
}

export function teardown(): void {
  const marker = process.env[MARKER];
  if (marker === undefined)
    throw new Error(
      `${MARKER} is unset at teardown, so this run cannot say whether the ` +
        "coverage register was checked.",
    );
  const reported = existsSync(marker);
  const moved = registerDigest();
  const began = registerWhenTheRunBegan;
  const named = register;
  rmSync(dirname(marker), { recursive: true, force: true });
  delete process.env[MARKER];
  delete process.env[OWNER];
  registerWhenTheRunBegan = null;
  register = null;
  // **Before the reporter check, because this invalidates it.** A reporter
  // that reported against a document the run then rewrote has checked
  // nothing, and saying the reporter ran would read as the stronger claim.
  //
  // **What this does not cover, which is three things and not two**: a write
  // landing after this hook, a write by a process this one did not start,
  // and a write landing BEFORE the baseline reading. The third is the one a
  // sentence here used to leave out while calling the others unreachable:
  // this module is imported and the config module is evaluated before
  // `setup` runs, so a self heal written in either precedes the reading. No
  // claim of unreachability is made about any of the three.
  if (moved !== began)
    throw new Error(
      `${named ?? "tests/COVERAGE.md"} changed while the run that checks it ` +
        `was running, from ${began ?? "absent"} to ${moved ?? "absent"}. A ` +
        "run must not write the register it is checking: a guard that heals " +
        "itself asserts nothing, and the figures a run measures are printed " +
        "for a separate invocation to apply.",
    );
  if (!reported)
    throw new Error(
      "the coverage register reporter did not run, so tests/COVERAGE.md was " +
        "checked against nothing. A `--reporter` on the command line replaces " +
        "the reporters vite.config.ts configures rather than adding to them: " +
        "name ./tests/coverageRegister.reporter.ts alongside yours, or set the " +
        "reporter in the config.",
    );
}
