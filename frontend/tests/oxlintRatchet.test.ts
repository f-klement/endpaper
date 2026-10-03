import { execFileSync, type StdioOptions } from "node:child_process";
import {
  closeSync,
  mkdtempSync,
  openSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, describe, expect, it } from "vitest";

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
 * **The report is read off a file and never off a pipe.** That is a discipline
 * and NOT a fifth refusal: nothing here reds if somebody puts it back on a
 * pipe, and the four refusals only convert the resulting loss into a failure
 * where the loss happens, which is the suite container and not a development
 * machine. So a local run is green on that regression. `REPORT` below carries
 * the measurement and why no arm is offered for it.
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
 * Cost on the `builder` worker: **six invocations in the steady state, of
 * which only two lint anything.** Two runs of the linter proper, two of the
 * config dump, one of the help, one of the rule catalogue. **The ceiling is
 * those six plus one per SUPPRESSED entry**, reached when every entry looks
 * clean in one run at once, or when the run enabled fewer rules than it
 * denied.
 *
 * **Recount both halves rather than trusting that sentence. Each has gone
 * stale within one commit of being written.** The ceiling was once a flat 20
 * over a list of 17; its replacement counted every line of `rules`, which
 * includes the configured rule that is never denied because it is never
 * suppressed; and the fixed count has now said three, then five, while the
 * file grew past both. Neither half is written as a product for that reason:
 * count the call sites, and count the entries that are off.
 *
 * `LINTED` below bounds a single invocation and `BUDGET` bounds the arm.
 */

const CONFIG = ".oxlintrc.json";
const OXLINT = "./node_modules/.bin/oxlint";
const BATCH = "the run denying every suppressed rule";

/**
 * The trees the linter walks, **read off the script CI runs rather than
 * written here a second time.**
 *
 * Both were `src tests` and nothing held them together. Narrow the script and
 * this file would have gone on re-deriving the suppression list over the wide
 * set while CI enforced the narrow one, with every arm green: measured,
 * dropping one of the two takes 222 files out of what is enforced and reds
 * nothing anywhere. An arm comparing the two would have been the obvious fix
 * and is the worse one, because it leaves two places to edit; deriving leaves
 * one.
 *
 * Refused rather than defaulted when the script cannot be read, for the same
 * reason `pluginsNamedInConfig` refuses: a quiet `["src", "tests"]` fallback
 * would restore the duplication at the moment it starts to matter.
 *
 * **THE WHOLE SCRIPT IS PINNED, NOT JUST ITS PATHS, AND THAT IS THE POINT.**
 * The first version kept the non-flag words and threw every flag away unread,
 * which made the script's argument space a suppression nobody could see:
 * driven with a live violation planted, `--allow=` and its short form each
 * took the lint to exit 0 with zero diagnostics and every arm here green, a
 * config flag in either spelling swapped the config entirely, and a different
 * binary passed unnoticed. One token in the manifest took CI to exit 0 on a
 * correctness violation. The equals forms are the ones the tool's own usage
 * line advertises.
 *
 * So the binary is pinned and any flag is refused. **This refuses a legitimate
 * future flag, loudly, at the line somebody writes it**, which is the same
 * bargain the key set arm makes further down and is worth the same price: a
 * flag that changes what the linter enforces is a decision, and it should cost
 * one deliberate edit here rather than nothing at all.
 */
const LINTER = "oxlint";

function treesTheScriptLints(): string[] {
  const manifest = JSON.parse(readFileSync("package.json", "utf8")) as {
    scripts?: Record<string, string>;
  };
  const script = manifest.scripts?.lint;
  if (script === undefined) {
    throw new Error(
      "package.json has no lint script, so what gets linted is unknown.",
    );
  }
  const [binary, ...rest] = script.trim().split(/\s+/);
  if (binary !== LINTER) {
    throw new Error(
      `the lint script runs "${String(binary)}" rather than ${LINTER}, so ` +
        `nothing this file derives describes what CI enforces.`,
    );
  }
  const flag = rest.find((word) => word.startsWith("-"));
  if (flag !== undefined) {
    throw new Error(
      `the lint script "${script}" carries the flag "${flag}". A flag can ` +
        `allow a rule, swap the config or change the renderer, and none of ` +
        `that is visible to any arm here: an --allow takes the lint to exit 0 ` +
        `on a live violation with this file still green. Decide here what ` +
        `re-derives it before adding one.`,
    );
  }
  if (rest.length === 0) {
    throw new Error(
      `the lint script "${script}" names no path to walk, so this file cannot ` +
        `re-derive anything over the tree CI enforces.`,
    );
  }
  return rest;
}

const TREES = treesTheScriptLints();

/**
 * What one oxlint invocation may take before it is a wedge, and the arm's own
 * budget above it.
 *
 * **`execFileSync` with no timeout waits forever**, which is what both calls
 * below did: a hung oxlint hung the arm, then the file, then the suite, and said
 * nothing while it did. A timeout makes the call throw with a null status, which
 * `outputOfFailedRun` and `parseReport` already refuse by name, so this adds a
 * bound and no new failure path.
 *
 * 10s is far above one invocation: this whole file, including every invocation
 * it makes, measures around a second on `builder` in a run of the file alone,
 * and over a second in some runs. **"Well under a second" is what stood here
 * and it was not true of one run in five.** No tighter figure is written: the
 * one that was moved with the arm count twice, and the bound does not turn on
 * it. What matters is the order, which is a second against a ten second bound
 * on a single invocation.
 *
 * **The arm's budget is that plus 30s**, so that one wedged invocation is
 * reported by this bound rather than killed by vitest's default of 5s, and 30s
 * covers the rest of them at many times their measured cost. Before this the
 * arm ran on that default with **no margin written down anywhere**, which
 * passed and was not something anybody chose. A second invocation wedging in
 * the same run is reported by the budget instead, which is a poorer message for
 * a state one wedge already explains.
 */
const LINTED = 10_000;

/**
 * The budget of the one arm that invokes oxlint, kept above `LINTED` so that the
 * bound reports a wedge rather than vitest killing the arm mid refusal. Derived
 * there; no second figure lives here.
 */
const BUDGET = LINTED + 30_000;

/**
 * Where a run writes its report. **oxlint loses its own buffered output when
 * that output is a pipe, in the suite container. It is not the process helper,
 * not `maxBuffer`, and not a fixed length.**
 *
 * The first version of this comment named a helper and a buffer that are not
 * the cause and quoted a bound that is a sample. All three were wrong, and
 * wrong in the direction that invites somebody to put a large document back on
 * a pipe because theirs is under the number. What settled it was a control.
 *
 * **Every reading below is the suite container's.** None of it reproduces on a
 * development machine, where ten of ten through the helper and five of five
 * through a shell pipe deliver the whole report. So none of this is checkable
 * where it is read, and a green local run says nothing about it.
 *
 * | in the container, identical call, identical worker | delivered |
 * |---|---|
 * | a non oxlint child emitting the report's byte count, exit 0 | **all of it** |
 * | the same child, exit 1 | **all of it** |
 * | the same child against a genuinely too small buffer | throws `ENOBUFS`, status null |
 * | oxlint, ten repetitions at one buffer size | 219264 six times, 475072 twice, 255808 once, 219262 once |
 *
 * So the helper carries the whole report through a pipe perfectly well at
 * either exit status, and a real overflow has a signature this does not have:
 * `ENOBUFS` and a null status, where oxlint's throw is status 1, its own.
 * **Nor is the loss deterministic**: four distinct lengths in ten, written out
 * above rather than summarised, because the summary of them that stood here
 * described five runs and there were ten.
 *
 * **The only stable anchor is one pipe buffer.** Put oxlint behind a shell pipe
 * in that container and it delivers exactly 65536 bytes, five runs out of five,
 * against a whole report over 1.6 MB. That is the number to reason with: assume
 * a pipe carries one buffer and no more.
 *
 * **No total for the report is written here, and that is the point of the last
 * sentence.** This file is inside the tree the run lints, so every assertion
 * added to it moves that total, and the figure quoted here was already stale in
 * the commit that corrected it. An order of magnitude is all the argument needs.
 *
 * It surfaced the day the config named a plugin list, which took the batch
 * report past 1.6 MB, but it was never about a threshold being crossed: the
 * report on the base tree measures 184291 bytes, already far over one pipe
 * buffer, and was arriving whole by luck.
 *
 * **No arm is offered, and that is a stated gap rather than an oversight.** The
 * loss happens in the container and not on a development machine, so a guard
 * written here would be green locally on the very regression it exists for, and
 * a guard that passes where it is read is worse than a comment that is read.
 */
const REPORTS = mkdtempSync(join(tmpdir(), "endpaper-oxlint-ratchet-"));
const REPORT = join(REPORTS, "report.json");
/** The help text, off a descriptor for the same reason the report is. */
const HELP = join(REPORTS, "help.txt");
/** The rule catalogue, 83716 bytes, well past the one buffer anchor above. */
const CATALOGUE = join(REPORTS, "catalogue.md");

afterAll(() => {
  rmSync(REPORTS, { recursive: true, force: true });
});

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
 * The config, parsed. `.oxlintrc.json` is JSONC, and `JSON.parse` does not take
 * comments.
 */
function readConfig(): {
  rules?: Record<string, unknown>;
  plugins?: unknown;
  categories?: unknown;
  ignorePatterns?: unknown;
} {
  const raw = readFileSync(CONFIG, "utf8");
  const withoutComments = raw
    .split("\n")
    .map((line) => line.replace(/(^|\s)\/\/.*$/, ""))
    .join("\n");
  return JSON.parse(withoutComments) as {
    rules?: Record<string, unknown>;
    plugins?: unknown;
    categories?: unknown;
    ignorePatterns?: unknown;
  };
}

/** The rules the config names. */
function rulesNamedInConfig(): string[] {
  return Object.keys(readConfig().rules ?? {});
}

/**
 * The same rules, read off the file's raw text instead of its parse.
 *
 * **Two instruments that call one helper are one instrument.** Everything here
 * that asks which rules the config names goes through `readConfig`, including
 * the floor that is supposed to prove the question was asked at all. Narrow
 * that helper by one filter token and the whole file narrows with it: measured,
 * twenty five suppressions became seventeen, the floor saw seventeen and
 * cleared, eight entries including a planted stale one stopped being
 * re-derived, and the run was green at exit 0. The on set and option arms
 * stayed green too, because they read the same narrowed helper.
 *
 * So the set is derived a second time by a route that shares no code with the
 * first: the quoted key at the start of a line inside the `rules` block. It is
 * a cruder reader and that is the point; it cannot be narrowed by the same
 * edit. The two are asserted equal, which is a floor that a narrowing cannot
 * satisfy by narrowing both.
 */
function rulesNamedInTheText(): string[] {
  const lines = readFileSync(CONFIG, "utf8").split("\n");
  const opens = lines.findIndex((line) => /^\s*"rules"\s*:\s*\{/.test(line));
  if (opens === -1) {
    throw new Error(`${CONFIG} has no rules block, so nothing can be read.`);
  }
  const names: string[] = [];
  for (const line of lines.slice(opens + 1)) {
    if (/^\s{2}\}/.test(line)) break;
    const match = /^\s{4}"([^"]+)"\s*:/.exec(line);
    if (match?.[1] !== undefined) names.push(match[1]);
  }
  return names;
}

/**
 * The plugins the config names.
 *
 * **Refused rather than defaulted when the key is absent.** An empty list would
 * make the plugin census below pass over a config that had gone back to the
 * default set, which is the one state that census exists to notice.
 */
function pluginsNamedInConfig(): string[] {
  const plugins = readConfig().plugins;
  if (!Array.isArray(plugins) || plugins.length === 0) {
    throw new Error(
      `${CONFIG} names no plugins array, so which plugins run is oxlint's ` +
        `default rather than this repository's decision, and the census of ` +
        `what is excluded has nothing to census.`,
    );
  }
  return plugins.map(String);
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
 * The output of a run that exited non zero, or a refusal. `lint` calls it for
 * the refusal alone, because its report is on disk rather than in `stdout`.
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

  // The report goes to the descriptor, for the reason at `REPORT`. Only
  // stderr comes back through a pipe, and oxlint's own complaints are short.
  const fd = openSync(REPORT, "w");
  try {
    const stdio: StdioOptions = ["ignore", fd, "pipe"];
    execFileSync(OXLINT, args, { stdio, timeout: LINTED });
  } catch (thrown) {
    // Called for its refusal and not for its value: the report is on disk, and
    // every status but 1 means the run did not happen. Dropping this call
    // turns a binary that could not be executed into an empty file, which
    // `parseReport` would then refuse with the wrong diagnosis.
    outputOfFailedRun(thrown, label);
  } finally {
    closeSync(fd);
  }
  return parseReport(readFileSync(REPORT, "utf8"), label);
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
 *
 * **This one still reads a pipe**, unlike `lint`, and the margin is against one
 * pipe buffer rather than against any figure a truncated run produced: the
 * printed config is one line per rule and runs 10176 bytes over the 221 rules
 * the five named plugins reach, against 65536 in the container `REPORT`
 * describes. The margin is measured in the dimension that moves, the plugin
 * list, and naming all fourteen still leaves it four times under one buffer.
 *
 * **Read `REPORT` before trusting that margin on anything bigger.** The earlier
 * version of this sentence measured itself against 219264, which is a sample of
 * a loss and not a bound, and would have waved through a document three times
 * this one's size. If this output ever approaches one buffer, move it to a
 * descriptor; the failure would be a short document, which
 * `rulesFromPrintConfig` refuses rather than reads.
 *
 * **No `maxBuffer` is set, and its absence is the honest state.** The override
 * that was here outlived the comment justifying it, leaving a 64 MiB literal
 * defended by a paragraph arguing about 10 KB against one pipe buffer, which
 * are different quantities: a reader would reasonably conclude the buffer was
 * the thing holding this up. It is not. The default is a hundred times this
 * output, and the bound that matters is the pipe above. If the default is ever
 * exceeded the call throws `ENOBUFS` with a null status, which
 * `outputOfFailedRun` refuses by name.
 */
function effectiveLevels(): Record<string, unknown> {
  let raw: string;
  try {
    raw = execFileSync(OXLINT, ["--print-config"], {
      encoding: "utf8",
      timeout: LINTED,
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
  it(
    "turns off no rule that this tree would now pass",
    () => {
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

      // A config with nothing suppressed would make the rest of this vacuous,
      // so the floor is asserted rather than assumed. **Both halves are load
      // bearing and the second is the one that holds.** A greater-than-zero
      // floor is cleared by a reader that finds seventeen of twenty five, and
      // every arm in this file reads the same helper, so narrowing it narrows
      // the floor too. The equality against a second, textual derivation is
      // what a narrowing cannot satisfy.
      expect(suppressed.length).toBeGreaterThan(0);
      expect(
        named,
        `the parse of ${CONFIG} and a plain read of its text disagree about ` +
          `which rules it names. Until they agree, nothing below is evidence ` +
          `about the config: every arm here reads the parse, so a reader that ` +
          `quietly drops entries drops them from the ratchet and from its own ` +
          `floor at the same time.`,
      ).toEqual(rulesNamedInTheText());

      const baseline = lint([]);

      // **The walk and the linter describe one population, by two routes with
      // no shared code.** `filesNamed` recurses the trees from the script and
      // skips the ignored paths; `number_of_files` is oxlint's own count of
      // what it opened. They agree, and that is what the directive census and
      // the nested config arm stand on, rather than on the ignore derivation
      // inside the walk, which strips one glob shape and would widen the walk
      // silently for any other. A wider walk only ever reds falsely, so this
      // is the safe direction made checkable. `EXTENSIONS` carries the
      // condition it holds under.
      expect(
        filesNamed(LINTABLE).length,
        `this file's own walk and oxlint disagree about how many files are ` +
          `under ${TREES.join(" and ")}. Every arm that walks the tree is ` +
          `then reporting on a population the linter does not have.`,
      ).toEqual(baseline.number_of_files);

      const denied = lint(suppressed);

      expect(differentTree(baseline, denied, BATCH)).toBeNull();
      expect(
        shortCountBlames(suppressed, baseline, denied, (rule) => lint([rule])),
      ).toBeNull();

      const firing = new Set(
        denied.diagnostics.map(({ code }) => ruleOf(code)),
      );
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
    },
    BUDGET,
  );
});

/**
 * The rules the config names and leaves ON, which the arm above cannot see.
 *
 * **A suppression list cannot police a configured rule, by construction, and
 * that is a surviving mutant rather than a worry.** Turn the `maxArgs` entry
 * on `vitest/valid-expect` back into `"off"`: it is one token, and everything
 * above stays green. `off` makes it a suppression, so the batch run denies it,
 * it reports its findings like any other entry, and the ratchet reads it as
 * an honest backlog row. Re-driven at this tip: it now reds **two** arms, this
 * one and the option arm below, where when it was first measured it reds none.
 * No pass count is written, because the one that was here described a
 * collection two arms smaller than the file had already grown to. What the
 * mutant costs is the rule, which catches an expect with no matcher call and
 * an expect with no arguments as well as the bound; only one of its classes is
 * caught anywhere else, by a core rule.
 *
 * So the on set is pinned by name here. This arm reds on that mutant, and it
 * reds when a second configured rule arrives without somebody coming to this
 * list to say why, which is what the config's header already demands of every
 * suppression and could not demand of an option.
 *
 * It costs one more `--print-config`, which lints nothing.
 */
const CONFIGURED_ON = ["vitest/valid-expect"];

/**
 * The exact option each configured rule carries.
 *
 * **Pinning the name pins nothing that matters, and the arm above did exactly
 * that.** Raise the bound to a nonsense value and oxlint reports the rule as
 * denied, it stays in the on set, it finds nothing, and **not one arm in this
 * tree reds.** The config's whole justification is that two is the signature's
 * own bound rather than a number chosen to clear the tree, and that three
 * arguments are still refused; with the name alone pinned, nothing refuses
 * three arguments if somebody writes a larger number here.
 *
 * So the value is held literally. Changing a bound on purpose means changing
 * it here too, next to the sentence in the config saying where the bound comes
 * from, which is the point rather than the friction.
 */
const CONFIGURED_OPTIONS: Record<string, unknown> = {
  "vitest/valid-expect": ["error", { maxArgs: 2 }],
};

/** oxlint's own help, read off a descriptor for the reason at `REPORT`. */
function helpText(): string {
  const fd = openSync(HELP, "w");
  try {
    const stdio: StdioOptions = ["ignore", fd, "pipe"];
    execFileSync(OXLINT, ["--help"], { stdio, timeout: LINTED });
  } catch (thrown) {
    // `--help` exits 0 here, but a tool that chose 1 or 2 for it would
    // otherwise make this census silently empty rather than loud.
    const failure = thrown as { status?: number | null };
    if (failure.status === null || failure.status === undefined) {
      throw new Error(
        `oxlint --help did not run: status ${String(failure.status)}`,
      );
    }
  } finally {
    closeSync(fd);
  }
  return readFileSync(HELP, "utf8");
}

/**
 * Every plugin oxlint ships, read off its own help.
 *
 * A default plugin is advertised as `--disable-<name>-plugin` and the rest as
 * `--<name>-plugin`, so the prefix is stripped and the two families become one
 * vocabulary. That vocabulary is the one a config's `plugins` array uses.
 */
function pluginsTheToolShips(help: string): string[] {
  const names = [...help.matchAll(/--([a-z0-9-]+)-plugin\b/g)]
    // The group is always there when the pattern matched, but the checker is
    // right that nothing here says so, and a silent `undefined` would reach
    // the census as a plugin named "undefined".
    .flatMap((match) => (match[1] === undefined ? [] : [match[1]]))
    .map((name) => name.replace(/^disable-/, ""));
  return [...new Set(names)].sort();
}

/**
 * oxlint's rule catalogue, off a descriptor because it is over one buffer.
 *
 * **The renderer is named, because leaving it implicit makes this arm's input
 * an undeclared ambient.** The implicit renderer and the named default one are
 * different renderers, which this file already records for two calls one
 * function away: with no flag the catalogue is the full table in the suite
 * container and **zero bytes on a development machine, three runs of three**.
 * So the arm was armed where it runs and would have read empty where somebody
 * debugs it, and an empty catalogue is a census that agrees with anything.
 * Named, all three spellings give the same 870 rows in the container.
 */
function ruleCatalogue(): string {
  const fd = openSync(CATALOGUE, "w");
  try {
    const stdio: StdioOptions = ["ignore", fd, "pipe"];
    execFileSync(OXLINT, ["--rules", "--format=default"], {
      stdio,
      timeout: LINTED,
    });
  } catch (thrown) {
    const failure = thrown as { status?: number | null };
    if (failure.status === null || failure.status === undefined) {
      throw new Error(
        `oxlint --rules did not run: status ${String(failure.status)}`,
      );
    }
  } finally {
    closeSync(fd);
  }
  return readFileSync(CATALOGUE, "utf8");
}

/**
 * The same vocabulary, derived a second way: the Source column of oxlint's own
 * rule catalogue.
 *
 * **The help was the single spelling this census stood on, and that was named
 * as its gap rather than closed.** The catalogue closes it, because it is a
 * different instrument: it lists every rule the binary has with the scope each
 * belongs to, and it is **independent of the configured plugin list**. 870
 * rules across 15 scopes, identical under three plugins, under five, and under
 * no config at all; only the Enabled column moves. Drop the core scope, which
 * is not a plugin, and the remaining 14 are exactly what the help advertises.
 *
 * Driven against a plugin advertised in a spelling the help regex does not
 * know: the help route returns fourteen with no arm red, the catalogue returns
 * fifteen, and the equality below reds. Two instruments, and they are genuinely
 * two, because neither reads the other's output.
 *
 * The catalogue spells a compound scope with an underscore where the help and
 * a config's `plugins` array use a hyphen, so it is normalised to the config's
 * vocabulary rather than the other way round.
 */
const CORE_SCOPE = "eslint";

function pluginsInTheCatalogue(catalogue: string): string[] {
  const scopes = new Set<string>();
  for (const line of catalogue.split("\n")) {
    const cells = line.split("|").map((cell) => cell.trim());
    // | Rule name | Source | Default | Enabled? | Fixable? |
    if (cells.length < 6) continue;
    const name = cells[1];
    const source = cells[2];
    if (name === undefined || source === undefined) continue;
    if (name === "" || name === "Rule name" || /^-+$/.test(name)) continue;
    if (source === "" || /^-+$/.test(source)) continue;
    if (source === CORE_SCOPE) continue;
    scopes.add(source.replaceAll("_", "-"));
  }
  return [...scopes].sort();
}

/**
 * The plugins this repository does not run, and why not. Counts are the
 * MARGINAL cost of naming one on top of the five, measured 2026-10-03 over the
 * same 487 files under the three enforced categories.
 *
 * **This list exists because naming a plugin list narrowed the ratchet and
 * nothing recorded what it narrowed.** The config promises that a rule a future
 * version adds arrives enforced rather than silently off. With an explicit list
 * that promise holds inside the five named plugins and nowhere else, and oxlint
 * ships fourteen. Nine were simply absent, with no reason written down, in the
 * one file whose whole discipline is that a list carries its reason.
 *
 * So the census below restores most of that property: a plugin that exists is
 * named, or it is here saying why not, and one a future oxlint adds reds by
 * name rather than arriving off in silence.
 *
 * **The help was once the only route and is no longer.** What follows is kept
 * because it is still true of the help arm alone, and the catalogue arm beside
 * it is what stops that being the whole story. The help census knows only the
 * one spelling oxlint uses today, `--<name>-plugin` and
 * its `--disable-` form, so a plugin advertised any other way is invisible to
 * it. The catalogue arm does not share that blind spot, which is the whole
 * reason for running two.
 *
 * **The counts below are a measurement, not a guard. Nothing re-derives them.**
 * That is the real difference from a suppression, whose reason is a finding the
 * ratchet re-derives on every run: an exclusion's reason is a number, no arm
 * reads it, and it goes stale in silence. One of them already did, between two
 * commits on this branch, with every arm green. Re-measure before relying on
 * one.
 *
 * Three of the nine are a different technology and are permanent. The rest are
 * candidates carrying what they would cost.
 */
const NOT_NAMED: Record<string, string> = {
  jest: "the wrong test runner. Its rules restate the vitest ones against an API this tree does not use, so naming it would double-report the require-to-throw-message and no-conditional-expect families at 18 and 6, and the valid-expect family at a number that moves with every two-argument assertion anybody writes. Permanent, so the total is not worth tracking.",
  nextjs:
    "not a Next.js application. 21 rules for 8 findings, every one of them about a framework that is not here. Permanent.",
  vue: "not a Vue application. 33 rules and 0 findings, which is the shape of a plugin that cannot say anything about this tree. Permanent.",
  node: "0 rules in the three enforced categories, so naming it buys nothing today. Revisit if that stops being true.",
  import:
    "a candidate, not a refusal. 8 rules for 7 findings: four on the default export, one self import, two unassigned imports. The cheapest of the nine to adopt.",
  promise:
    "a candidate, not a refusal. 6 rules for 4 findings, all always-return.",
  jsdoc:
    "52 findings, 51 of them check-tag-names, over a tree that carries its types in TypeScript rather than in tags. Mostly one rule disagreeing with the house docstring style.",
  "jsx-a11y":
    "54 findings, 45 of them prefer-tag-over-role. Worth doing and not free: the other 9 are real accessibility findings across five rules.",
  "react-perf":
    "533 findings over 4 rules, 361 of them a new function passed as a prop. That is a rewrite rather than a ratchet, which is the same ground on which pedantic, style and restriction are not enforced.",
};

describe("the plugins the config does not name", () => {
  it(
    "accounts for every plugin the tool ships",
    () => {
      const shipped = pluginsTheToolShips(helpText());
      const named = pluginsNamedInConfig();

      // Half of the floor. A parse that collapses to nothing fails here,
      // because the config names five plugins and none of them would be found.
      expect(
        named.filter((plugin) => !shipped.includes(plugin)),
        `${CONFIG} names a plugin oxlint's help does not advertise, so either ` +
          `the config is wrong or this census is reading the help wrongly. ` +
          `Shipped: ${shipped.join(", ")}`,
      ).toEqual([]);

      expect(
        shipped.filter(
          // `hasOwn`, not `in`, which walks the prototype chain: a plugin named
          // `constructor` or `toString` would otherwise read as accounted for.
          // Its sibling below reads `Object.keys`, so the two disagreed.
          (plugin) =>
            !named.includes(plugin) && !Object.hasOwn(NOT_NAMED, plugin),
        ),
        `oxlint ships these and ${CONFIG} neither names them nor says why not. ` +
          `Naming a plugin list is what makes this possible: a rule in an ` +
          `unnamed plugin is off and nothing else here would notice. Add it to ` +
          `the list, or to NOT_NAMED with its marginal cost.`,
      ).toEqual([]);

      // The other half of the floor, and the half that does the work. Requiring
      // every excluded plugin to still be shipped forces the parse to recover
      // the FULL set, not merely a non empty one, and a degraded parse reds here
      // by name with up to nine of them. Simulated over eight ways the parse can
      // degrade, a count comparison never reddened on its own; this does. The
      // comparison used to sit above and has been deleted rather than kept as
      // decoration with a comment crediting it with the arming.
      expect(
        Object.keys(NOT_NAMED).filter(
          (plugin) => !shipped.includes(plugin) || named.includes(plugin),
        ),
        `these are recorded as not named, and are either no longer shipped by ` +
          `oxlint or are now in ${CONFIG}'s own list. Either way the row no ` +
          `longer describes anything, so delete it or move it. Note this says ` +
          `nothing about whether the row's COUNT is still right.`,
      ).toEqual([]);
    },
    BUDGET,
  );

  it(
    "is the same set the rule catalogue names, derived without the help",
    () => {
      expect(
        pluginsInTheCatalogue(ruleCatalogue()),
        `oxlint's help and its rule catalogue disagree about which plugins ` +
          `exist. The catalogue is the one that does not depend on how a flag ` +
          `is spelled, so believe it: a plugin only it knows about is one the ` +
          `census above cannot see, and the list in ${CONFIG} needs it or ` +
          `NOT_NAMED does.`,
      ).toEqual(pluginsTheToolShips(helpText()));
    },
    BUDGET,
  );
});

describe("the rules the config leaves on", () => {
  it(
    "is exactly the list of configured rules, and no other",
    () => {
      const named = rulesNamedInConfig();
      const suppressed = new Set(suppressedIn(named, effectiveLevels()));

      expect(
        named.filter((rule) => !suppressed.has(rule)),
        `a rule ${CONFIG} names and does not suppress is configuration rather ` +
          `than a suppression, and nothing else in this file can see it. Add it ` +
          `to CONFIGURED_ON with the reason its default is wrong here, or, if a ` +
          `configured rule has become a plain suppression, take it out of both.`,
      ).toEqual(CONFIGURED_ON);
    },
    BUDGET,
  );

  it("carries the exact option each configured rule was reasoned about with", () => {
    const rules = readConfig().rules ?? {};

    expect(
      Object.fromEntries(CONFIGURED_ON.map((rule) => [rule, rules[rule]])),
      `the option on a configured rule is the whole of what makes it ` +
        `configuration rather than a suppression, and the arm above pins only ` +
        `the name. A bound moved to anything else reads as denied, finds ` +
        `nothing, and reds nothing. Change the reason in ${CONFIG} and the ` +
        `value here together, or not at all.`,
    ).toEqual(CONFIGURED_OPTIONS);
  });
});

/**
 * The whole shape of the config, because **a suppression has five spellings
 * and only one of them is a rule set to `off`.**
 *
 * Every one below was driven with a real violation planted in the tree, and
 * each left `bun run lint` at **exit 0 on that violation** while this file
 * stayed green. Refusing the `overrides` key alone closed one of them.
 *
 * | spelling | what it does to the arms above |
 * |---|---|
 * | `overrides` | the rule never enters the named set; the dump still calls it denied |
 * | `extends` | a second config moves the rule to allowed and drops the rule count by one |
 * | a category at `warn` | **every field these arms read is identical**; only the exit status moves |
 * | a nested config file | reds only by accident: the dump emits a null rule count, so the parse refuses naming neither the file nor the rule |
 * | an ignore pattern or ignore file | shortens BOTH walks, so the tree comparison compares the short walk against itself, which is the weakness that comparison's own docstring already names |
 *
 * So the refusal is spelled as **the key set**, not one key. The tool refuses
 * an unknown top level key outright and names the twelve it accepts, so
 * holding the config to the four it uses closes `extends`, `overrides`,
 * `settings`, `env`, `globals`, `options`, `jsPlugins` and `$schema` together,
 * and closes the next one a version adds. The two keys that had no arm at all
 * are pinned by value, which is what closes the warn downgrade and the ignore
 * pattern. The two that are files rather than keys get an arm each.
 *
 * **This refuses a legitimate settings block, loudly, at the line somebody
 * writes it.** That is the intended direction: the cost is one deliberate edit
 * here, against a suppression nothing re-derives.
 */
const CONFIG_KEYS = ["categories", "ignorePatterns", "plugins", "rules"];

/** The categories that must be enforced, and at what level. */
const CATEGORIES = {
  correctness: "error",
  suspicious: "error",
  perf: "error",
};

/** The only paths the linter may be told to skip. */
const IGNORED = ["src/api/generated/**"];

/** Anything oxlint would read as a config or an ignore file beside this one. */
const CONFIG_FILENAMES =
  /^\.oxlintrc\.(json|jsonc)$|^\.oxlintignore$|^\.eslintignore$/;

/** What this file assumes the linter reads. */
const LINTABLE = /\.tsx?$/;

/**
 * Every extension present under the linted trees.
 *
 * **This is the condition the walk's equality with the linter's own file count
 * rests on**, and without it that equality is the floor mistake again: the two
 * agree today because every file the linter could read is a `.ts` or a `.tsx`,
 * not because the walk is right in general. Add one `.js` and the counts part
 * company, which reds honestly. Add one and widen `LINTABLE` to match without
 * thinking, and the equality goes on passing while meaning less. So the mix is
 * pinned here, and a new extension asks the question out loud: does the linter
 * read this, and should the walk?
 */
const EXTENSIONS = [".css", ".md", ".ts", ".tsx"];

/** The distinct extensions under the linted trees, ignored paths aside. */
function extensionsInTheTrees(): string[] {
  const seen = new Set<string>();
  for (const path of filesNamed(/./)) {
    const dot = path.lastIndexOf(".");
    seen.add(dot === -1 ? path : path.slice(dot));
  }
  return [...seen].sort();
}

/**
 * Every file under the linted trees whose name matches, less the ignored
 * paths.
 *
 * **The skip is derived from `IGNORED` and that derivation is weaker than it
 * looks**, so it is not what this walk's correctness rests on. It strips a
 * trailing glob of one shape; a deeper or trailing slash spelling strips
 * nothing and the walk silently widens past the linter's population. The
 * direction is safe, because a wider walk only ever produces a false red, but
 * it is an extent claim the code does not hold.
 *
 * **What holds it is an equality against the linter's own count**, asserted in
 * the suppression arm: this walk and `number_of_files` agree at the same
 * figure by two routes with no shared code. `EXTENSIONS` carries the condition
 * that equality rests on.
 */
function filesNamed(pattern: RegExp): string[] {
  const skipped = IGNORED.map((glob) => glob.replace(/\/\*+$/, ""));
  const found: string[] = [];
  const walk = (dir: string): void => {
    if (skipped.includes(dir)) return;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules") continue;
        walk(path);
      } else if (pattern.test(entry.name)) {
        found.push(path);
      }
    }
  };
  for (const tree of TREES) walk(tree);
  return found.sort();
}

describe("a suppression the ratchet could not see", () => {
  it("cannot be written as a key, because the key set is held exactly", () => {
    expect(
      Object.keys(readConfig()).sort(),
      `${CONFIG}'s top level keys are not the four this file reasons about. ` +
        `Several of the keys oxlint accepts suppress a rule in a way no arm ` +
        `here can see: overrides scopes one to a path, extends moves it to ` +
        `another file, and both leave the dump calling it denied. If a new ` +
        `key is genuinely wanted, decide here what re-derives it first.`,
    ).toEqual([...CONFIG_KEYS].sort());
  });

  it("cannot be written as a category downgraded to a warning", () => {
    expect(
      readConfig().categories,
      `a category at anything but "error" leaves every field the arms above ` +
        `read identical and takes the lint to exit 0 on a real violation, ` +
        `which is a suppression of the whole category written in one word.`,
    ).toEqual(CATEGORIES);
  });

  it("cannot be written as an ignore pattern", () => {
    expect(
      readConfig().ignorePatterns,
      `an ignore pattern shortens the baseline run and the denied run alike, ` +
        `so the tree comparison compares the short walk against the short ` +
        `walk and agrees with itself. That is the weakness differentTree's ` +
        `own docstring names, and this is what keeps it theoretical.`,
    ).toEqual(IGNORED);
  });

  it("leaves the linted trees carrying only the extensions this file knows", () => {
    expect(
      extensionsInTheTrees(),
      `a file extension appeared under ${TREES.join(" or ")} that this file ` +
        `has no opinion about. The walk reads ${String(LINTABLE)} and is ` +
        `compared against oxlint's own file count; that comparison is only ` +
        `evidence while those are the files oxlint reads. Decide whether the ` +
        `linter reads the new one, widen the walk if it does, and list it here.`,
    ).toEqual(EXTENSIONS);
  });

  it("cannot be written as a second config or an ignore file in the tree", () => {
    expect(
      filesNamed(CONFIG_FILENAMES),
      `a config file nested under a linted tree silences rules for everything ` +
        `below it, and reds here only because the dump then emits a null rule ` +
        `count, which refuses naming neither the file nor the rule. An ignore ` +
        `file shortens both walks the same way an ignore pattern does. ` +
        `Neither belongs under ${TREES.join(" or ")}.`,
    ).toEqual([]);
  });
});

/**
 * Every inline disable directive in the linted trees, and why each stands.
 *
 * **A directive is the sixth spelling of a suppression, and it is the one the
 * config cannot see at all.** It suppresses a rule for one line, carries no
 * count, and is re-derived by nothing. oxlint's unused-directive report does
 * not reach these.
 *
 * **This branch made two of them load bearing and said nothing.** Both
 * `exhaustive-deps` directives were inert while the react plugin was off.
 * Enabling it turned them live: removing all three takes the tree from 0
 * findings to 2, and both are that rule. So a plugin was adopted and two of
 * its findings were suppressed in the same change, invisibly.
 *
 * **One of them also falsified a refusal.** `no-control-regex` is documented
 * in the config as one site; the directive in `lib/pdf.ts` is the second,
 * masked, so the entry read as one easy fix. It is inert only while the rule
 * is off at top level, and becomes a defect the moment somebody acts on that
 * entry.
 *
 * The set is pinned by equality, with a reason beside each, which is the
 * contract the suppression list already has. A new directive reds here.
 */
const DIRECTIVES: Record<string, string> = {
  "src/pages/components/SearchBar.tsx":
    "exhaustive-deps. The debounce effect omits onSearch on purpose, because Home passes an inline callback and including it would restart the debounce on every render. LIVE since the react plugin was named.",
  "src/pages/ScanPage/components/BarcodeScanner.tsx":
    "exhaustive-deps. The teardown effect omits the deps the rule wants, which would restart the camera. LIVE since the react plugin was named.",
  "src/lib/pdf.ts":
    "no-control-regex, and it is the SECOND site of a refusal the config documents. Stripping the control characters a PDF producer pads metadata with is the point of that function. Inert while the rule is off at top level.",
};

const DIRECTIVE = /\b(?:oxlint|eslint)-disable(?:-next-line|-line)?\b/;

describe("an inline disable directive", () => {
  it("exists only where this file says it does, and says why", () => {
    const carrying = filesNamed(LINTABLE).filter((path) =>
      DIRECTIVE.test(readFileSync(path, "utf8")),
    );

    expect(
      carrying.sort(),
      `an inline directive suppresses a rule for one line, carries no count, ` +
        `and nothing re-derives it: it is the one suppression neither ${CONFIG} ` +
        `nor any arm in this file can see. Enabling a plugin can turn a dead ` +
        `one live without a word, which is exactly what naming the react ` +
        `plugin did to two of these. Add it here with its reason, or remove it.`,
    ).toEqual(Object.keys(DIRECTIVES).sort());
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
