import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

/**
 * The oxlint ratchet keeps its own suppression list honest.
 *
 * `bun run lint` already refuses a finding from any rule that is ON. What
 * nothing else refuses is the other direction: a rule listed as OFF in
 * `.oxlintrc.json` whose findings somebody has since fixed, which then sits
 * suppressed forever and quietly narrows the ratchet. That is the shape this
 * repository keeps paying for, a list nobody re-derives, so the list is
 * re-derived here on every run.
 *
 * The rule is stated as an exclusion: every rule the config turns off must
 * still have at least one finding. Nothing here enumerates which rules those
 * are, so a rule added to or removed from the config is covered with no edit
 * to this file.
 */

const CONFIG = ".oxlintrc.json";

/** `.oxlintrc.json` is JSONC, and `JSON.parse` does not take comments. */
function readConfig(): { rules?: Record<string, string> } {
  const raw = readFileSync(CONFIG, "utf8");
  const withoutComments = raw
    .split("\n")
    .map((line) => line.replace(/(^|\s)\/\/.*$/, ""))
    .join("\n");
  return JSON.parse(withoutComments) as { rules?: Record<string, string> };
}

/** oxlint reports `plugin(rule)`, where the config writes `plugin/rule`. */
function bareName(configKey: string): string {
  const slash = configKey.lastIndexOf("/");
  return slash === -1 ? configKey : configKey.slice(slash + 1);
}

describe("the oxlint suppression list", () => {
  it("turns off no rule that this tree would now pass", () => {
    const suppressed = Object.entries(readConfig().rules ?? {})
      .filter(([, level]) => level === "off")
      .map(([key]) => key);

    // A config with nothing suppressed would make the loop below vacuous, so
    // the floor is asserted rather than assumed.
    expect(suppressed.length).toBeGreaterThan(0);

    const args = ["src", "tests"];
    for (const rule of suppressed) args.push("-D", rule);

    let output = "";
    try {
      output = execFileSync("./node_modules/.bin/oxlint", args, {
        encoding: "utf8",
      });
    } catch (thrown) {
      // A finding makes oxlint exit non zero, which is the expected case here.
      const withOutput = thrown as { stdout?: string; stderr?: string };
      output = (withOutput.stdout ?? "") + (withOutput.stderr ?? "");
    }

    const stillFiring = new Set(
      [...output.matchAll(/\(([a-z0-9-]+)\):/g)].map((match) => match[1]),
    );

    const clean = suppressed.filter((rule) => !stillFiring.has(bareName(rule)));
    expect(
      clean,
      "these rules are off in .oxlintrc.json and this tree no longer breaks " +
        "them, so turn them on and delete the entry",
    ).toEqual([]);
  });
});
