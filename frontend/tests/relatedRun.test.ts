/**
 * @vitest-environment node
 */

/**
 * A related run that would skip `tests/setup.ts` for most of its files is
 * refused, and the same run isolated, or a plain run, is not.
 *
 * **The settings are handed in rather than read from a nested run**, because a
 * nested `vitest related` walks every test file's import graph before any
 * global setup runs: measured at 25 s for the two arms, on every full run,
 * and past a 25 s timeout on a slower host. The setting names are vitest's
 * own types, so a rename is a type error; the refusal reaching a real run was
 * measured once, exit 4 with this message, when the guard was written. What a
 * file can check without a run is that the configuration still names it.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { refusal } from "./relatedRun.globalSetup";

function settings(related: string[] | undefined, isolate: boolean) {
  return { globalConfig: { related }, config: { isolate } };
}

describe("refusal", () => {
  it("refuses a related run without isolation, naming --isolate", () => {
    expect(refusal(settings(["src/x.ts"], false))).toContain("Pass --isolate");
  });

  it("refuses a related run that named no path", () => {
    expect(refusal(settings([], false))).not.toBeNull();
  });

  it("lets a related run through when it is isolated", () => {
    expect(refusal(settings(["src/x.ts"], true))).toBeNull();
  });

  it("lets a plain run through without isolation", () => {
    expect(refusal(settings(undefined, false))).toBeNull();
  });
});

/**
 * The `globalSetup` list as the config file spells it. **Read as text, not
 * imported**: importing the config loads every plugin cold and runs `git
 * describe` in a subprocess, the cost `houseRules.test.ts` sizes a 30 s
 * timeout for.
 */
function globalSetups(): string[] {
  const config = readFileSync(
    join(import.meta.dirname, "..", "vite.config.ts"),
    "utf8",
  );
  const list = /globalSetup: \[([^\]]*)\]/.exec(config)?.[1] ?? "";
  return [...list.matchAll(/"([^"]+)"/g)].map((match) => match[1] ?? "");
}

describe("the configuration", () => {
  it("runs the refusal before anything else sets up for the run", () => {
    const setups = globalSetups();
    const at = setups.indexOf("./tests/relatedRun.globalSetup.ts");

    expect(at).toBeGreaterThanOrEqual(0);
    expect(at).toBeLessThan(
      setups.indexOf("./tests/coverageRegister.globalSetup.ts"),
    );
    expect(at).toBeLessThan(
      setups.indexOf("./tests/runConfiguration.globalSetup.ts"),
    );
  });
});
