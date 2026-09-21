import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

/**
 * The oxlint ratchet keeps its own suppression list honest.
 *
 * `bun run lint` already refuses a finding from any rule that is ON. What
 * nothing else refuses is the other direction: a rule listed as OFF in
 * `.oxlintrc.json` whose findings somebody has since fixed, which then sits
 * suppressed forever and quietly narrows the ratchet. So the list is
 * re-derived here on every run, stated as an exclusion, and a rule added to or
 * removed from the config is covered with no edit to this file.
 *
 * Which entries are off is asked of oxlint rather than read off the config's
 * own text, for the reason in `suppressedIn`.
 *
 * **The only evidence this test ever has for "stale" is an absence, and an
 * absence has two causes**: the rule has no findings, or the rule's findings
 * did not reach the test. The first version could not tell them apart, and on
 * one unchanged tree it gave three different verdicts across four runs, one of
 * them the empty set, while every rule it named was still firing. Its message
 * said to delete the entry. `docs/decisions.md`, under *An absence is not a
 * verdict*, carries the measurements and the candidate fixes that were not
 * taken.
 *
 * Four refusals stand between a run and a verdict. Removing any one of them
 * puts the conflation back:
 *
 * 1. **The report is JSON.** A document cut short fails to parse, where
 *    rendered output cut short still reads as a shorter list of findings.
 *    Rendered output is also a picture of a report rather than a report:
 *    oxlint prints the offending source under each finding, so the old
 *    `(rule):` scrape parsed 20 names out of 17 denied rules, with `one`,
 *    `source` and `walk` among them.
 * 2. **The exit status has to be 1**, which is what oxlint produces when a
 *    rule fires. `execFileSync` also throws for a binary it cannot execute
 *    and for output past `maxBuffer`, and reading `stdout` off those is how a
 *    run that never happened became a clean bill of health for every entry.
 * 3. **The denials have to have taken effect**, measured as `number_of_rules`
 *    rising by the number of rules denied. Without it an entry that is not a
 *    suppression at all reads as a suppression with no findings.
 * 4. **The run has to have walked the baseline's file count.** The weakest of
 *    the four, written down as such: it compares oxlint against oxlint, so a
 *    walk that came up short in every run agrees with itself.
 *
 * And no negative is believed off one run. A rule that looks clean is
 * confirmed by a second run denying it alone, so **a rule seen firing in
 * either run is not stale**: the residual error leaves a suppression standing
 * rather than accusing a live one.
 *
 * Cost on the `builder` worker: three invocations in the steady state, one of
 * which lints nothing, and this whole file measures 189ms against a frontend
 * suite of 46.66s to 50.93s over three runs. The ceiling is 20 invocations at
 * about 1.1s, reached when every entry looks clean in one run at once, or
 * when the run enabled fewer rules than it denied.
 */

const CONFIG = ".oxlintrc.json";
const OXLINT = "./node_modules/.bin/oxlint";
const TREES = ["src", "tests"];
const BATCH = "the run denying every suppressed rule";

/**
 * The fields of oxlint's JSON report this test reads.
 *
 * `number_of_rules` counts the rules that actually ran, which is the only way
 * a `-D` is shown to have done anything.
 */
type Report = {
  diagnostics: { code: string }[];
  number_of_files: number;
  number_of_rules: number;
};

/**
 * The rules the config names. `.oxlintrc.json` is JSONC, and `JSON.parse` does
 * not take comments.
 */
function rulesNamedInConfig(): string[] {
  const raw = readFileSync(CONFIG, "utf8");
  const withoutComments = raw
    .split("\n")
    .map((line) => line.replace(/(^|\s)\/\/.*$/, ""))
    .join("\n");
  const config = JSON.parse(withoutComments) as {
    rules?: Record<string, unknown>;
  };
  return Object.keys(config.rules ?? {});
}

/**
 * Every rule the config names, less the ones oxlint says are on.
 *
 * **The levels are oxlint's, not the config's text.** `"off"`, `"allow"`, `0`
 * and `["off"]` all mean off, and `"error"`, `"warn"`, `"deny"`, `2`, `1` and
 * the array forms of those all mean on: eleven spellings accepted by 1.83.0,
 * measured. The first version of this test compared against one of them and
 * every other spelling fell out of the ratchet in silence. Growing that list
 * by one more is the move this repository has watched fail before, so the
 * question is put to `--print-config` instead, which echoes each key exactly
 * as the config wrote it and normalises every level to `allow`, `warn` or
 * `deny`.
 *
 * **The value is that word, or a pair carrying it.** A rule given options
 * comes back as `["deny", [{ "max": 500 }]]` rather than as `"deny"`, so the
 * word is read out of the pair. Reading the value whole classified every rule
 * with options as suppressed and turned the gate red on a config `bun run
 * lint` passes.
 *
 * Anything not on is counted suppressed, a key oxlint did not echo included,
 * because the two directions are not symmetric. Counting an enabled rule as
 * suppressed costs a loud failure: denying a rule that is already on does not
 * move `number_of_rules`, which `shortCountBlames` reports by name. Counting a
 * suppressed rule as enabled costs nothing and leaves the ratchet smaller.
 */
function suppressedIn(
  named: string[],
  effective: Record<string, unknown>,
): string[] {
  const on = new Set(["deny", "warn"]);
  return named.filter((rule) => {
    const level = effective[rule];
    return !on.has(String(Array.isArray(level) ? level[0] : level));
  });
}

/**
 * The config writes `plugin/rule` or a bare `rule`; oxlint's `code` reads
 * `plugin(rule)` and spells an unprefixed rule `eslint(rule)`. Both sides are
 * reduced to the bare name rather than matched whole, because the two plugin
 * vocabularies are not guaranteed to agree and a name shared by two plugins
 * can only make a rule look like it is still firing. That is the safe
 * direction; matching whole would fail the other way.
 */
function bareName(configKey: string): string {
  const slash = configKey.lastIndexOf("/");
  return slash === -1 ? configKey : configKey.slice(slash + 1);
}

/** The rule out of a diagnostic's `code`, which reads `plugin(rule)`. */
function ruleOf(code: string): string {
  const open = code.indexOf("(");
  return open === -1 ? code : code.slice(open + 1, code.lastIndexOf(")"));
}

/**
 * The report, or a refusal. A document that does not parse, or that is missing
 * a field this test reads, is not partial evidence about the rules it happens
 * to mention: it is a run whose output did not arrive.
 *
 * The opening of the document goes in the message because oxlint prints its
 * own refusals to the same stream: an entry naming a rule it does not have
 * gets `Failed to parse oxlint configuration file` and the rule's name there,
 * which is the whole diagnosis and is otherwise thrown away.
 */
function parseReport(raw: string, label: string): Report {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    const opening = raw.trim().slice(0, 200);
    throw new Error(
      `${label} produced ${String(raw.length)} bytes that are not a whole ` +
        `JSON report, so nothing in it is evidence about any rule.` +
        (opening === "" ? "" : ` It begins: ${opening}`),
    );
  }
  const report = parsed as Partial<Report>;
  if (
    !Array.isArray(report.diagnostics) ||
    typeof report.number_of_files !== "number" ||
    typeof report.number_of_rules !== "number"
  ) {
    throw new Error(
      `${label} produced a JSON report missing the fields this test reads.`,
    );
  }
  return report as Report;
}

/**
 * The output of a run that exited non zero, or a refusal.
 *
 * oxlint exits 1 when a rule fires, which is the expected case here. Node also
 * throws for a binary it could not execute and for output past `maxBuffer`,
 * and the `stdout` carried by those is missing or cut short. Reading it is how
 * this test once reported every suppression clean at once.
 */
function outputOfFailedRun(thrown: unknown, label: string): string {
  const failure = thrown as {
    status?: number | null;
    code?: string;
    message?: string;
    stdout?: string;
  };
  if (failure.status !== 1) {
    throw new Error(
      `${label} did not reach oxlint: status ${String(failure.status)}, ` +
        `code ${String(failure.code)}, ` +
        `${String(failure.message).slice(0, 200)}`,
    );
  }
  return failure.stdout ?? "";
}

/** Why two runs cannot be compared, or null when they can. */
function differentTree(
  baseline: Report,
  run: Report,
  label: string,
): string | null {
  if (run.number_of_files === baseline.number_of_files) return null;
  return (
    `${label} walked ${String(run.number_of_files)} files where the ` +
    `baseline walked ${String(baseline.number_of_files)}, so the two do not ` +
    `describe one tree and neither is evidence about this one`
  );
}

/** Why a run's denials did not all take effect, or null when they did. */
function deniedNothing(
  baseline: Report,
  run: Report,
  denied: number,
  label: string,
): string | null {
  const expected = baseline.number_of_rules + denied;
  if (run.number_of_rules === expected) return null;
  return (
    `${label} ran ${String(run.number_of_rules)} rules where denying ` +
    `${String(denied)} on top of the baseline's ` +
    `${String(baseline.number_of_rules)} should give ${String(expected)}, ` +
    `so at least one denial enabled nothing`
  );
}

function lint(deny: string[]): Report {
  const args = [...TREES];
  for (const rule of deny) args.push("-D", rule);
  args.push("--format", "json");

  const label =
    deny.length === 0
      ? "the baseline run"
      : `the run denying ${String(deny.length)} rule(s)`;

  let raw: string;
  try {
    raw = execFileSync(OXLINT, args, {
      encoding: "utf8",
      // Set rather than left at Node's 1 MiB. The JSON report is 122 KB and
      // the rendered one 298 KB on a suite worker, so this is headroom and not
      // a fix: an overflow arrives as a throw whose `stdout` is truncated,
      // which `outputOfFailedRun` refuses and `parseReport` refuses again.
      maxBuffer: 64 * 1024 * 1024,
    });
  } catch (thrown) {
    raw = outputOfFailedRun(thrown, label);
  }
  return parseReport(raw, label);
}

/** The pure half of `effectiveLevels`: the parse and its two refusals. */
function rulesFromPrintConfig(raw: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    const opening = raw.trim().slice(0, 200);
    throw new Error(
      `the effective config is ${String(raw.length)} bytes that are not ` +
        `JSON, so which rules are off is not known.` +
        (opening === "" ? "" : ` It begins: ${opening}`),
    );
  }
  const rules = (parsed as { rules?: unknown }).rules;
  if (typeof rules !== "object" || rules === null) {
    throw new Error(
      "the effective config carries no rules object, so which rules are off " +
        "is not known.",
    );
  }
  return rules as Record<string, unknown>;
}

/**
 * Every rule oxlint would run, and the level it would run it at.
 *
 * `--print-config` lints nothing: it is oxlint answering which rules are on,
 * which is the question `suppressedIn` has and the one the config's own text
 * answers in eleven spellings.
 */
function effectiveLevels(): Record<string, unknown> {
  let raw: string;
  try {
    raw = execFileSync(OXLINT, ["--print-config"], {
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    });
  } catch (thrown) {
    raw = outputOfFailedRun(thrown, "the effective config");
  }
  return rulesFromPrintConfig(raw);
}

/**
 * Why a run denying every suppressed rule enabled fewer rules than it denied,
 * or null when it did not.
 *
 * The count alone names no entry, and which entry is inert decides what to do
 * about it, so the entries are probed one at a time before anything is
 * reported. Paid only on a run that is already failing. An entry naming a rule
 * oxlint does not have never reaches here: oxlint refuses that config outright
 * and `parseReport` carries its complaint.
 */
function shortCountBlames(
  suppressed: string[],
  baseline: Report,
  denied: Report,
  probe: (rule: string) => Report,
): string | null {
  const short = deniedNothing(baseline, denied, suppressed.length, BATCH);
  if (short === null) return null;

  const inert = suppressed.filter(
    (rule) =>
      deniedNothing(baseline, probe(rule), 1, `the run denying ${rule}`) !==
      null,
  );
  if (inert.length > 0) {
    return (
      `${inert.join(", ")} enabled nothing when denied alone, so the ratchet ` +
      `does not cover them: each is a rule that is already on and is not a ` +
      `suppression at all`
    );
  }
  return (
    `${short}, and yet every entry enabled a rule when denied on its own, ` +
    `which is two entries naming one rule between them`
  );
}

/**
 * Split the suppressed rules into the ones two observations call stale and the
 * ones the first observation lost.
 *
 * `firing` is what a single run denying every suppressed rule reported.
 * `confirm` denies one rule on its own and returns what that run reported. A
 * rule is stale only when neither names it. An absence from `firing` alone is
 * the conflation this file exists to refuse, and a rule that reappears under
 * `confirm` is lost rather than stale.
 */
function staleRules(
  suppressed: string[],
  firing: ReadonlySet<string>,
  confirm: (rule: string) => ReadonlySet<string>,
): { stale: string[]; lost: string[] } {
  const stale: string[] = [];
  const lost: string[] = [];
  for (const rule of suppressed) {
    if (firing.has(bareName(rule))) continue;
    if (confirm(rule).has(bareName(rule))) lost.push(rule);
    else stale.push(rule);
  }
  return { stale, lost };
}

describe("the oxlint suppression list", () => {
  it("turns off no rule that this tree would now pass", () => {
    // Our own parse of the config runs BEFORE oxlint is asked anything, and
    // the order is a statement rather than argument evaluation order. A
    // config that is not JSON is refused here, by a reader that quotes no
    // path, rather than by oxlint, whose parse error cites the config's
    // absolute path and would land in the 200 bytes a refusal carries.
    //
    // It closes that class and not the question. A config that is valid JSON
    // and that oxlint still refuses, an `extends` that does not resolve, is
    // outside this order and does cite the path, well inside the 200 bytes a
    // refusal carries. Neither a length nor an offset is quoted for it, and
    // the reason is not that both drift: oxlint interpolates the absolute
    // path into that message, so the total varies with where the checkout
    // sits while the offset does not, being a fixed prefix. Quoting the
    // stable half is what invites the next reader to quote the unstable one
    // beside it. The refusals that carry no path are an unknown rule, an
    // unknown plugin and a malformed value.
    const named = rulesNamedInConfig();
    const suppressed = suppressedIn(named, effectiveLevels());

    // A config with nothing suppressed would make the rest of this vacuous, so
    // the floor is asserted rather than assumed.
    expect(suppressed.length).toBeGreaterThan(0);

    const baseline = lint([]);
    const denied = lint(suppressed);

    expect(differentTree(baseline, denied, BATCH)).toBeNull();
    expect(
      shortCountBlames(suppressed, baseline, denied, (rule) => lint([rule])),
    ).toBeNull();

    const firing = new Set(denied.diagnostics.map(({ code }) => ruleOf(code)));
    const confirmed = new Map<string, Report>();

    const { stale, lost } = staleRules(suppressed, firing, (rule) => {
      const alone = lint([rule]);
      expect(
        differentTree(baseline, alone, `the run denying ${rule}`),
      ).toBeNull();
      expect(
        deniedNothing(baseline, alone, 1, `the run denying ${rule}`),
      ).toBeNull();
      confirmed.set(rule, alone);
      return new Set(alone.diagnostics.map(({ code }) => ruleOf(code)));
    });

    // Not a failure. The verdict on the entry is right either way and leaving
    // a suppression standing is the harmless direction. It is printed because
    // it is the only evidence anybody gets of a batch run losing findings,
    // which nobody has yet caught in the act, and the counts are printed with
    // it because the surviving signature is about how few findings a lost rule
    // has.
    for (const rule of lost) {
      const alone = confirmed.get(rule)!;
      const mine = alone.diagnostics.filter(
        ({ code }) => ruleOf(code) === bareName(rule),
      ).length;
      console.warn(
        `oxlint lost ${rule} in a run of ${String(denied.diagnostics.length)} ` +
          `diagnostics over ${String(denied.number_of_files)} files, and ` +
          `reported ${String(mine)} finding(s) for it when denying it alone ` +
          `over ${String(alone.number_of_files)} files.`,
      );
    }

    expect(
      stale,
      `these rules are off in ${CONFIG} and no finding for them reached ` +
        `either of two oxlint runs over the same ` +
        `${String(baseline.number_of_files)} files. Reproduce the clean ` +
        `result by hand before deleting an entry, then turn the rule on.`,
    ).toEqual([]);
  });
});

describe("a report that did not arrive whole", () => {
  const whole = JSON.stringify({
    diagnostics: [{ code: "eslint(no-shadow)" }],
    number_of_files: 468,
    number_of_rules: 117,
  });

  it("is refused when the document is cut short", () => {
    expect(() => parseReport(whole.slice(0, 40), "a probe")).toThrow(
      /not a whole/,
    );
  });

  it("is refused when the invocation left no output at all", () => {
    expect(() => parseReport("", "a probe")).toThrow(/not a whole/);
  });

  it("is refused when the file count is absent", () => {
    const missing = JSON.stringify({ diagnostics: [], number_of_rules: 117 });

    expect(() => parseReport(missing, "a probe")).toThrow(/missing the fields/);
  });

  it("carries the opening of what did arrive, being oxlint's own complaint", () => {
    const refusal =
      "Failed to parse oxlint configuration file.\n\n" +
      "  x Rule 'no-such-rule' not found in plugin 'eslint'";

    expect(() => parseReport(refusal, "a probe")).toThrow(/no-such-rule/);
  });

  it("names no opening when there was no output to open with", () => {
    expect(() => parseReport("", "a probe")).toThrow(/any rule\.$/);
  });

  it("is read when every field this test needs is there", () => {
    expect(parseReport(whole, "a probe").number_of_files).toBe(468);
  });
});

describe("a run that threw", () => {
  it("is refused when the binary could not be executed", () => {
    expect(() =>
      outputOfFailedRun(
        { status: null, code: "ENOENT", message: "spawn ENOENT" },
        "a probe",
      ),
    ).toThrow(/did not reach oxlint/);
  });

  it("is refused when Node stopped reading at maxBuffer", () => {
    expect(() =>
      outputOfFailedRun(
        { status: null, code: "ENOBUFS", stdout: '{ "diagnostics": [' },
        "a probe",
      ),
    ).toThrow(/did not reach oxlint/);
  });

  it("is read when oxlint itself reported findings", () => {
    expect(
      outputOfFailedRun({ status: 1, stdout: "a report" }, "a probe"),
    ).toBe("a report");
  });
});

const BASELINE: Report = {
  diagnostics: [],
  number_of_files: 467,
  number_of_rules: 116,
};

describe("two runs over one tree", () => {
  it("are refused when they walked different numbers of files", () => {
    const short = { ...BASELINE, number_of_files: 460, number_of_rules: 133 };

    expect(differentTree(BASELINE, short, "a probe")).toMatch(/460.*467/);
  });

  it("are accepted when they walked the same number of files", () => {
    const same = { ...BASELINE, number_of_rules: 133 };

    expect(differentTree(BASELINE, same, "a probe")).toBeNull();
  });
});

describe("a run whose denials took effect", () => {
  it("is refused when denying seventeen rules enabled fewer", () => {
    const one = { ...BASELINE, number_of_rules: 132 };

    expect(deniedNothing(BASELINE, one, 17, "a probe")).toMatch(/132.*133/);
  });

  it("is accepted when denying seventeen rules enabled seventeen", () => {
    const all = { ...BASELINE, number_of_rules: 133 };

    expect(deniedNothing(BASELINE, all, 17, "a probe")).toBeNull();
  });
});

describe("a run that enabled fewer rules than it denied", () => {
  const two = ["a/one", "two"];
  const shortByOne = { ...BASELINE, number_of_rules: 117 };
  const enabled = { ...BASELINE, number_of_rules: 117 };
  const enabledNothing = { ...BASELINE, number_of_rules: 116 };

  it("spends no probe when the count is right", () => {
    let probes = 0;

    const blame = shortCountBlames(
      two,
      BASELINE,
      { ...BASELINE, number_of_rules: 118 },
      () => {
        probes += 1;
        return enabled;
      },
    );

    expect(blame).toBeNull();
    expect(probes).toBe(0);
  });

  it("names the entry that enabled nothing on its own", () => {
    const blame = shortCountBlames(two, BASELINE, shortByOne, (rule) =>
      rule === "two" ? enabledNothing : enabled,
    );

    expect(blame).toMatch(/^two enabled nothing/);
  });

  it("blames two entries naming one rule when each enabled one alone", () => {
    const blame = shortCountBlames(two, BASELINE, shortByOne, () => enabled);

    expect(blame).toMatch(/two entries naming one rule/);
  });
});

describe("the suppression list read off oxlint's effective config", () => {
  it("holds every rule oxlint says is allowed", () => {
    const effective = { "a/one": "allow", two: "allow" };

    expect(suppressedIn(["a/one", "two"], effective)).toEqual(["a/one", "two"]);
  });

  it("holds no rule oxlint says is denied or warned", () => {
    const effective = { hot: "deny", warm: "warn" };

    expect(suppressedIn(["hot", "warm"], effective)).toEqual([]);
  });

  it("holds a rule oxlint did not echo, which is the loud direction", () => {
    expect(suppressedIn(["unechoed"], {})).toEqual(["unechoed"]);
  });

  it("reads the level out of a rule that carries options", () => {
    const effective = { capped: ["deny", [{ max: 500 }]], off: "allow" };

    expect(suppressedIn(["capped", "off"], effective)).toEqual(["off"]);
  });
});

describe("the effective config oxlint prints", () => {
  it("is refused when it is not JSON, carrying what did arrive", () => {
    const refusal =
      "Failed to parse oxlint configuration file.\n\n" +
      "  x Rule 'no-such-rule' not found in plugin 'eslint'";

    expect(() => rulesFromPrintConfig(refusal)).toThrow(/no-such-rule/);
  });

  it("names no opening when there was no output to open with", () => {
    expect(() => rulesFromPrintConfig("")).toThrow(/not known\.$/);
  });

  it("is refused when it carries no rules", () => {
    expect(() => rulesFromPrintConfig('{"plugins":[]}')).toThrow(
      /no rules object/,
    );
  });

  it("is read when it carries rules", () => {
    const printed = '{"rules":{"no-shadow":"allow"}}';

    expect(rulesFromPrintConfig(printed)).toEqual({ "no-shadow": "allow" });
  });
});

describe("a rule named in a diagnostic", () => {
  it("is read out of the plugin's parentheses", () => {
    expect(ruleOf("typescript(no-extraneous-class)")).toBe(
      "no-extraneous-class",
    );
  });

  it("is read from an unprefixed rule's eslint spelling", () => {
    expect(ruleOf("eslint(no-shadow)")).toBe("no-shadow");
  });

  it("is the whole code when there are no parentheses", () => {
    expect(ruleOf("no-shadow")).toBe("no-shadow");
  });
});

describe("a rule absent from the run that denied everything", () => {
  const suppressed = ["unicorn/no-useless-spread", "no-useless-concat"];

  it("is not stale when a run denying it alone reports it", () => {
    const { stale, lost } = staleRules(
      suppressed,
      new Set(),
      () => new Set(["no-useless-spread", "no-useless-concat"]),
    );

    expect(stale).toEqual([]);
    expect(lost).toEqual(suppressed);
  });

  it("is stale only when neither run reports it", () => {
    const { stale, lost } = staleRules(
      suppressed,
      new Set(["no-useless-concat"]),
      () => new Set(),
    );

    expect(stale).toEqual(["unicorn/no-useless-spread"]);
    expect(lost).toEqual([]);
  });

  it("costs no confirming run for a rule the first run reported", () => {
    let confirmations = 0;

    staleRules(
      suppressed,
      new Set(["no-useless-spread", "no-useless-concat"]),
      () => {
        confirmations += 1;
        return new Set();
      },
    );

    expect(confirmations).toBe(0);
  });
});
