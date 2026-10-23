/**
 * Refuses a run of this suite that nobody sanctioned, before a worker starts.
 *
 * **A global setup and not the configuration file**, because `vite.config.ts`
 * is also what `vite build` and the dev server load, and a refusal there would
 * have to tell those apart from a test run. Only vitest runs a global setup,
 * and it runs one in its main process after it has found the test files and
 * before it hands any to the pool, so a refusal here forks no worker. A run
 * that finds no test file never reaches this, and forks none either.
 *
 * **First in `globalSetup`**, so no other setup does its work for a run that
 * is about to be refused.
 *
 * **What never reaches it.** A vitest started where it finds no configuration,
 * such as one run through bunx from the repository root, loads none of this
 * and forks its workers unrefused: vitest looks for the configuration in its
 * root, not in a parent. And bun's own `test` subcommand is bun's runner, not
 * vitest, so it never reads this either.
 *
 * The twin of `pytest_configure` in `backend/tests/conftest.py`;
 * `docs/testing.md`, Running, says why both exist.
 */

import { writeSync } from "node:fs";

export const SANCTIONED = "ENDPAPER_SUITE_SANCTIONED";

/** pytest's usage error, as the backend refusal exits, and not a failed run's 1. */
export const REFUSED = 4;

export function setup(): void {
  if (process.env[SANCTIONED] === "1") return;
  // **An exit and not a throw.** vitest answers a thrown setup by printing "No
  // test files found" above it, and then runs every other global setup's
  // teardown, the coverage register's among them, which refuses a run it never
  // set up: three errors where the reader needs one sentence. No worker exists
  // yet, so there is nothing an exit leaves behind. `writeSync` because an
  // asynchronous write can be lost to the exit on a pipe.
  //
  // The runner comes before the variable because the reader follows the first
  // instruction given, and on a shared machine that has to be the runner
  // rather than the bypass.
  writeSync(
    2,
    `refusing to run: ${SANCTIONED} is not 1. Run this suite through the ` +
      "project's CPU limited suite runner, which sets it, or in CI. Only on a " +
      `machine of your own with nothing else on it, set ${SANCTIONED}=1 for ` +
      "the one command; docs/testing.md, Running, says why.\n",
  );
  process.exit(REFUSED);
}
