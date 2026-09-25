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

import { existsSync, mkdtempSync, rmSync } from "node:fs";
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

export function setup(): void {
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
  rmSync(dirname(marker), { recursive: true, force: true });
  delete process.env[MARKER];
  delete process.env[OWNER];
  if (!reported)
    throw new Error(
      "the coverage register reporter did not run, so tests/COVERAGE.md was " +
        "checked against nothing. A `--reporter` on the command line replaces " +
        "the reporters vite.config.ts configures rather than adding to them: " +
        "name ./tests/coverageRegister.reporter.ts alongside yours, or set the " +
        "reporter in the config.",
    );
}
