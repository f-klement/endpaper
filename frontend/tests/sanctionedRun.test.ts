/**
 * @vitest-environment node
 */

/**
 * A run of this suite that nobody sanctioned refuses before a worker loads a
 * test file.
 *
 * The rule is `tests/sanctionedRun.globalSetup.ts`. Both runs are the same
 * command over this tree's own configuration, differing only in the variable,
 * so the variable is the one thing either verdict can be about, and a
 * configuration that stopped naming the setup reddens the refused arm.
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";

import { REFUSED, SANCTIONED } from "./sanctionedRun.globalSetup";

const ROOT = join(import.meta.dirname, "..");

/**
 * Where a nested run records that a worker loaded this file.
 *
 * **What a run did, not its exit status**, because a sanctioned run of one
 * file still ends red whenever `tests/COVERAGE.md` lags the tree, which is
 * every branch that adds a test, and this arm is not about the register.
 */
const LOADED = "ENDPAPER_SANCTIONED_RUN_LOADED";

const loadedAt = process.env[LOADED];
if (loadedAt !== undefined) writeFileSync(loadedAt, "");

/**
 * This file, with a name filter no test carries, so a run that proceeds loads
 * it in a worker and runs nothing, which keeps it cheap and keeps it from
 * spawning itself again.
 */
const NOTHING = [
  "tests/sanctionedRun.test.ts",
  "-t",
  "^no test is named this$",
];

function nestedRun(sanctioned: boolean, marker: string) {
  // `ENDPAPER_JUNIT` goes as well: the configuration writes a junit report to
  // that path, and the pipeline's own report would be overwritten by this one.
  const env: NodeJS.ProcessEnv = { ...process.env, [LOADED]: marker };
  delete env[SANCTIONED];
  delete env.ENDPAPER_JUNIT;
  if (sanctioned) env[SANCTIONED] = "1";
  // `--pool=threads` so a timeout, which kills by pid, takes the workers with it:
  // a forked worker has a pid of its own and would outlive the kill.
  return spawnSync(
    join(ROOT, "node_modules", ".bin", "vitest"),
    ["run", "--pool=threads", ...NOTHING],
    {
      cwd: ROOT,
      env,
      encoding: "utf8",
      timeout: 25_000,
      killSignal: "SIGKILL",
    },
  );
}

it("refuses a run without the variable and proceeds with it", () => {
  const dir = mkdtempSync(join(tmpdir(), "sanctioned-run-"));
  try {
    const refusedMarker = join(dir, "refused");
    const allowedMarker = join(dir, "allowed");
    const refused = nestedRun(false, refusedMarker);
    const allowed = nestedRun(true, allowedMarker);
    const output = (run: typeof refused) => run.stdout + run.stderr;

    expect(refused.status, output(refused)).toBe(REFUSED);
    expect(existsSync(refusedMarker), output(refused)).toBe(false);
    // **The runner is offered before the variable**, on the line that names
    // it: the reader follows the first instruction given, and on a shared
    // machine that has to be the runner rather than turning the guard off.
    expect(refused.stderr).toMatch(
      new RegExp(`^(?:(?!${SANCTIONED}=1).)*suite runner`, "m"),
    );

    expect(existsSync(allowedMarker), output(allowed)).toBe(true);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}, 60_000);
