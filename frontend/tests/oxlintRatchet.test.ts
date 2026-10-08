import { execFileSync, type StdioOptions } from "node:child_process";
import {
  closeSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readdirSync,
  linkSync,
  lstatSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve, sep } from "node:path";

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
 * Cost on the `builder` worker: **one invocation per call site in the steady
 * state, except the census loop over the blanked copy, which runs twice while
 * the tree holds a directive.** Only the `lint` calls walk the tree, and the
 * census rounds are `lint` calls that run no rule. **The ceiling adds one per
 * SUPPRESSED entry**, reached when every entry looks clean in one run at once,
 * or when the run enabled fewer rules than it denied, **and one more census
 * round while any range of lines stands**, whatever the number of ranges,
 * since every closing directive goes in one round and every opening one in
 * the next. `ROUNDS` bounds it.
 *
 * **No total is written, because every one written here went stale within a
 * commit.** The ceiling was once a flat 20 over a list of 17; its replacement
 * counted every line of `rules`, which includes the configured rule that is
 * never denied because it is never suppressed; and the fixed count said three,
 * then five, then six over a file making seven calls. Count the call sites,
 * and count the entries that are off.
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
  diagnostics: Finding[];
  number_of_files: number;
  number_of_rules: number;
};

/**
 * One diagnostic. `code` is absent on an unused directive, which only the
 * census run asks for and `directivesIn` reads; the span is in bytes.
 */
type Finding = {
  code: string;
  filename?: string;
  message?: string;
  labels?: { span: { offset?: number; length?: number } }[];
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
  const names: string[] = [];
  for (const line of linesOfTheRulesBlock(readFileSync(CONFIG, "utf8"))) {
    const match = /^\s{4}"([^"]+)"\s*:/.exec(line);
    if (match?.[1] !== undefined) names.push(match[1]);
  }
  return names;
}

/**
 * The lines between the config's `rules` opening and the line that closes it,
 * which both text readers walk. Shared, and safely: each reader is held equal
 * to a different instrument, `rulesNamedInTheText` to the parse and
 * `backlogIn` to oxlint's own levels, so a narrowing here reds both.
 */
function linesOfTheRulesBlock(raw: string): string[] {
  const lines = raw.split("\n");
  const opens = lines.findIndex((line) => /^\s*"rules"\s*:\s*\{/.test(line));
  if (opens === -1) {
    throw new Error(`${CONFIG} has no rules block, so nothing can be read.`);
  }
  const block: string[] = [];
  for (const line of lines.slice(opens + 1)) {
    if (/^\s{2}\}/.test(line)) break;
    block.push(line);
  }
  return block;
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

/**
 * One run over the trees, read off a file. `tree` is the directory the run
 * stands in, and so the one whose config it reads: the checkout by default, or
 * the blanked copy `treeWithEveryDirectiveBlanked` builds. `flags` go after
 * the denials and before the format.
 */
function lint(
  deny: string[],
  tree = ".",
  flags: string[] = [],
  label = deny.length === 0
    ? "the baseline run"
    : `the run denying ${String(deny.length)} rule(s)`,
): Report {
  const args = [...TREES];
  for (const rule of deny) args.push("-D", rule);
  args.push(...flags, "--format", "json");

  // The report goes to the descriptor, for the reason at `REPORT`. Only
  // stderr comes back through a pipe, and oxlint's own complaints are short.
  const fd = openSync(REPORT, "w");
  try {
    const stdio: StdioOptions = ["ignore", fd, "pipe"];
    // Resolved here, because a relative binary under another `cwd` is looked
    // up from that directory, where the copy carries no `node_modules`.
    execFileSync(resolve(OXLINT), args, {
      stdio,
      timeout: LINTED,
      cwd: tree,
    });
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
 * The refusals: the entries that are off for good, because the rule is wrong
 * about this codebase rather than unpaid. Every other suppression is a backlog
 * entry and carries its count.
 *
 * **Held by value, because a count arm opens a new door.** With every backlog
 * count held, the cheapest way past one is to drop it and call the row a
 * refusal. That is a decision, and here it costs an edit to this list, with
 * the reason written above the entry in the config, rather than nothing. The
 * reasons live there alone, so this is a bare list rather than a record.
 *
 * **Which refusals carry a count is the config's rule**, stated once above
 * its refusals. This file holds it: `SITED` names the refusals argued from
 * their sites, the arm below refuses one that has lost its count or a refusal
 * outside it that carries one, and the count arm holds each count and each
 * set of files.
 */
const REFUSALS = [
  "no-await-in-loop",
  "no-control-regex",
  "no-loss-of-precision",
  "react/react-in-jsx-scope",
];

/**
 * The refusals argued from their sites, each with the files its findings sit
 * in over the blanked copy, held by equality in the count arm.
 *
 * **The files, and not only the total**, because the file is what the reason
 * is about. A named site removed and a new one added in another file leave
 * the total where it was: measured, a lossy literal moved out of
 * `lib/bookBounds.ts` into a page passed every arm while this held totals
 * alone. The backend's bandit shares are held per file for the same reason.
 */
const SITED: Record<string, string[]> = {
  "no-await-in-loop": [
    "src/lib/audiobook.ts",
    "src/lib/bulkWrite.ts",
    "src/lib/pdf.ts",
    "src/lib/takeout.ts",
    "src/lib/zip.ts",
    "src/pages/ScanPage/hooks.ts",
    "src/pages/SettingsPage/LibrarySettingsPage/hooks.ts",
    "tests/api/mutator.test.ts",
    "tests/houseRules.test.ts",
    "tests/lib/adobeDigitalEditions.test.ts",
    "tests/lib/audiobook.test.ts",
    "tests/lib/fileReaders.test.ts",
    "tests/lib/mobi.test.ts",
    "tests/lib/pdf.test.ts",
    "tests/lib/readerContract.ts",
    "tests/lib/stores.test.ts",
    "tests/lib/takeoutFixtures.ts",
    "tests/lib/xmlEntities.test.ts",
    "tests/lib/zip.test.ts",
    "tests/pages/BookDetail/BookDetail.test.tsx",
    "tests/pages/BookDetail/components/IdentifierChips.test.tsx",
    "tests/pages/SettingsPage/LibrarySettingsPage/hooks.test.tsx",
    "tests/pages/SettingsPage/SettingsPage.test.tsx",
    "tests/pdfFixtures.ts",
    "tests/property.ts",
    "tests/propertyBudget.test.ts",
    "tests/zipFixtures.ts",
  ],
  "no-control-regex": ["src/lib/pdf.ts", "src/lib/safeHref.ts"],
  "no-loss-of-precision": ["src/lib/bookBounds.ts"],
};

/**
 * Each rule of `SITED` with the set of files a report finds it in. A set, so
 * the comparison ignores order without a sort, which this tree's backlog
 * counts.
 */
function filesOfSited(report: Report): Record<string, Set<string>> {
  return Object.fromEntries(
    Object.keys(SITED).map((rule) => [
      rule,
      new Set(
        report.diagnostics
          .filter(({ code }) => code === codeOf(rule))
          .map(({ filename }) => String(filename)),
      ),
    ]),
  );
}

/**
 * A backlog entry's line: the rule, its level, and its count as the whole of a
 * trailing comment, `"rule": "off", // 12`.
 *
 * **Anything after the digits drops the line from this reader, on purpose.** A
 * breakdown beside a total, a file count or a share, is a figure nothing
 * holds, and it goes stale under a total that is held. Dropping the line reds
 * the equality with oxlint's own levels, so the breakdown is refused rather
 * than read.
 */
const BACKLOG_LINE = /^\s*"([^"]+)"\s*:[^/]*\/\/\s*(\d+)\s*$/;

type Stated = { rule: string; stated: number };

/** Every line of the rules block carrying a count, as the rule and its figure. */
function backlogIn(raw: string): Stated[] {
  const backlog: Stated[] = [];
  for (const line of linesOfTheRulesBlock(raw)) {
    const match = BACKLOG_LINE.exec(line);
    if (match?.[1] !== undefined && match[2] !== undefined) {
      backlog.push({ rule: match[1], stated: Number(match[2]) });
    }
  }
  return backlog;
}

/**
 * The `code` oxlint reports a config key under: `plugin/rule` as
 * `plugin(rule)`, and a bare rule as `eslint(rule)`.
 *
 * **Exact, unlike `bareName`, because the safe direction is reversed.** For
 * staleness a shared bare name can only keep an entry standing. For a count it
 * adds another rule's findings to this one's, so two entries sharing a name
 * would each be held to the sum, and both could be stated at it.
 *
 * **An alias reads zero here.** oxlint accepts a key under an alias plugin
 * prefix, `react-hooks/`, `@typescript-eslint/`, `eslint-plugin-unicorn/` and
 * others, and reports its findings under the canonical code, so such a key
 * finds nothing under this spelling. That reds only because a stated zero is
 * refused: stated anything else, the count differs; stated zero, the entry arm
 * refuses it. So the key is not canonicalised here, which would make an alias
 * work rather than red, and nothing needs it to.
 */
function codeOf(configKey: string): string {
  const slash = configKey.indexOf("/");
  if (slash === -1) return `eslint(${configKey})`;
  return `${configKey.slice(0, slash)}(${configKey.slice(slash + 1)})`;
}

/** Every `(rule, stated, found)` where the count is not oxlint's. */
function countsThatDiffer(
  backlog: Stated[],
  report: Report,
): [string, number, number][] {
  const found = new Map<string, number>();
  for (const { code } of report.diagnostics) {
    found.set(code, (found.get(code) ?? 0) + 1);
  }
  return backlog.flatMap(({ rule, stated }): [string, number, number][] => {
    const count = found.get(codeOf(rule)) ?? 0;
    return count === stated ? [] : [[rule, stated, count]];
  });
}

/** A finding as one string, so two reports can be compared as sets. */
function findingKey({ code, filename, labels }: Finding): string {
  return `${code} ${String(filename)} ${String(labels?.[0]?.span.offset)}`;
}

/**
 * The findings of `honoured` that `copy` does not have. Blanking a
 * directive can only add a finding, so anything here means the copy is not
 * the tree.
 */
function findingsMissingFrom(copy: Report, honoured: Report): string[] {
  const present = new Set(copy.diagnostics.map(findingKey));
  return honoured.diagnostics
    .map(findingKey)
    .filter((key) => !present.has(key));
}

/** One disable directive, where oxlint says it is. */
type Directive = { filename: string; offset: number; length: number };

/**
 * The directives a census run reported, or a refusal.
 *
 * The census allows every rule and asks for unused directives, so every
 * directive is unused and every one is reported. **That holds only while no
 * rule runs**: a directive suppressing a live finding counts as used and is
 * not reported, so a run that enabled anything is refused rather than read.
 * And a diagnostic carrying a rule's `code` is a finding rather than a
 * directive, which the same condition makes impossible and this refuses anyway.
 */
function directivesIn(report: Report, label: string): Directive[] {
  if (report.number_of_rules !== 0) {
    throw new Error(
      `${label} ran ${String(report.number_of_rules)} rules where it allowed ` +
        `all of them, so a directive suppressing one of their findings counts ` +
        `as used and goes unreported.`,
    );
  }
  return report.diagnostics.map((diagnostic) => {
    const { code, filename } = diagnostic as Partial<Finding>;
    const span = diagnostic.labels?.[0]?.span;
    if (
      code !== undefined ||
      typeof filename !== "string" ||
      typeof span?.offset !== "number" ||
      typeof span.length !== "number"
    ) {
      throw new Error(
        `${label} reported something that is not a directive with a span: ` +
          `${JSON.stringify(diagnostic).slice(0, 200)}`,
      );
    }
    return { filename, offset: span.offset, length: span.length };
  });
}

/**
 * The byte range to blank for one reported directive: the comment it is, or a
 * refusal.
 *
 * **The span is in bytes, not characters**, measured on a file carrying non
 * ASCII text before its directive, where the same offset read as characters
 * lands in code. So the file is handled as bytes.
 *
 * **Two shapes are accepted, and nothing else.** A span opening a comment is
 * the comment, which is every disable oxlint reports. And an unused enable is
 * reported by a span INSIDE its comment: the body after the opener for a bare
 * enable closing a named range, which is the range form ESLint documents, and
 * the rule name for an enable naming a rule the range never disabled. That
 * span is widened to the whole comment when the comment is the first thing on
 * its line, a JSX brace aside, and its text begins with the enable keyword. Anything else is
 * refused, because it means either the offset is not what this reads it as or
 * the span is not a directive, and blanking it would edit code.
 */
function commentToBlank(
  source: Buffer,
  { filename, offset, length }: Directive,
): [number, number] {
  const refusal = new Error(
    `the directive oxlint reported in ${filename} at byte ${String(offset)} ` +
      `neither opens a comment nor sits inside an enable comment, so either ` +
      `the offset is not a byte offset or the span is not a directive, and ` +
      `blanking it would edit code.`,
  );
  if (offset + length > source.length) throw refusal;

  const opener = source.subarray(offset, offset + 2).toString("latin1");
  if (opener === "//" || opener === "/*") return [offset, offset + length];

  const lineStart = source.lastIndexOf(0x0a, offset - 1) + 1;
  // A brace may precede the opener, because inside JSX children a comment can
  // only be written as `{/* ... */}`.
  const lead = /^[ \t]*\{?[ \t]*(\/\/|\/\*)/.exec(
    source.subarray(lineStart, offset).toString("latin1"),
  );
  if (lead?.[1] === undefined) throw refusal;
  const start = lineStart + lead[0].length - 2;

  let stop: number;
  let body: string;
  if (lead[1] === "//") {
    const newline = source.indexOf(0x0a, start);
    stop = newline === -1 ? source.length : newline;
    body = source.subarray(start + 2, stop).toString("latin1");
  } else {
    const close = source.indexOf("*/", start + 2, "latin1");
    if (close === -1) throw refusal;
    stop = close + 2;
    body = source.subarray(start + 2, close).toString("latin1");
  }
  if (offset + length > stop) throw refusal;
  if (!/^\s*(?:eslint|oxlint)-enable\b/.test(body)) throw refusal;
  return [start, stop];
}

/**
 * The file with every range overwritten by spaces, line breaks kept.
 *
 * Every range is resolved against the same unmodified bytes before any is
 * written, by the caller, because two reports can fall in one comment: the
 * second resolved after the first was blanked would no longer sit in a comment
 * and be refused.
 */
function blankedRanges(source: Buffer, ranges: [number, number][]): Buffer {
  const copy = Buffer.from(source);
  for (const [from, to] of ranges) {
    for (let at = from; at < to; at += 1) {
      if (copy[at] !== 0x0a && copy[at] !== 0x0d) copy[at] = 0x20;
    }
  }
  return copy;
}

/** Where the blanked copy is built, inside the directory `afterAll` removes. */
const BLANKED = join(REPORTS, "blanked");

/**
 * How many census rounds a copy may take before it is a refusal.
 *
 * A round blanks every directive oxlint reports, and the last round must
 * report none. **One blanking round is not always enough**: oxlint reports a
 * range by its closing directive while that stands, and the opening one only
 * once it is gone. Measured on a range pair, round one named the closing
 * comment and round two the opening one. Five covers that, the confirming
 * round, and room; a tree needing more is behaving in a way nobody measured.
 */
const ROUNDS = 5;

/**
 * Each named path under `from`, copied to the same path under `to`, links
 * followed.
 *
 * **`dereference` is load bearing.** Without it a symlink is copied as a link
 * to its target's absolute path in the checkout, so blanking a directive in
 * the copy writes through the link and edits the checkout: measured, the
 * directive in a linked component was gone from the source after one run.
 * oxlint follows both kinds of link, so the dereferenced copy holds what it
 * reads in the checkout. `sharedWithItsSource` is the arm that reds if a link
 * or a shared file ever survives into the copy.
 */
function copyBeside(from: string, to: string, paths: string[]): void {
  for (const path of paths) {
    cpSync(join(from, path), join(to, path), {
      recursive: true,
      dereference: true,
      filter: (source) => basename(source) !== "node_modules",
    });
  }
}

/**
 * Every path in the copy that is a link, or that is the same file as its
 * source, so that writing to it would write to the checkout. A walk of the
 * copy by `lstat`, which does not follow what it is asking about, and a
 * comparison of device and inode with the source by `stat`.
 */
function sharedWithItsSource(
  copy: string,
  source: string,
  paths: string[],
): string[] {
  const shared: string[] = [];
  const visit = (path: string): void => {
    const here = lstatSync(join(copy, path));
    if (here.isSymbolicLink()) {
      shared.push(path);
      return;
    }
    if (here.isDirectory()) {
      for (const entry of readdirSync(join(copy, path))) {
        visit(join(path, entry));
      }
      return;
    }
    const there = statSync(join(source, path));
    if (there.ino === here.ino && there.dev === here.dev) shared.push(path);
  };
  for (const path of paths) visit(path);
  return shared.sort();
}

/**
 * The config and the linted trees, copied side by side into `BLANKED`.
 *
 * **The config is copied beside the trees** because `ignorePatterns` resolves
 * against the config's own directory: one left behind would walk the whole
 * generated client. Whether the copy is the tree is then asked rather than
 * assumed, by the arm that reads it.
 */
function copyOfTheCheckout(): string {
  rmSync(BLANKED, { recursive: true, force: true });
  mkdirSync(BLANKED);
  copyBeside(".", BLANKED, [CONFIG, ...TREES]);
  return BLANKED;
}

/**
 * Every disable directive in `copy` blanked, which is the tree the backlog
 * counts are read over.
 *
 * **Which comments are directives is oxlint's answer, not a pattern's.** Each
 * census run allows every rule and reports unused directives, so every
 * directive oxlint honours is reported with its span; `directivesIn` refuses a
 * run where that does not hold.
 *
 * **And no write leaves the copy.** `copyBeside` follows links and the arm
 * checks none survived; this refuses a path that resolves outside the copy all
 * the same, so a regression names its cause here rather than reddening some
 * other arm on a checkout that has been edited.
 */
function blankEveryDirective(copy: string, baseline: Report): void {
  const inside = realpathSync(copy) + sep;
  for (let round = 1; round <= ROUNDS; round += 1) {
    const label = `census round ${String(round)} over the blanked copy`;
    const census = lint(
      [],
      copy,
      ["-A", "all", "--report-unused-disable-directives"],
      label,
    );
    const elsewhere = differentTree(baseline, census, label);
    if (elsewhere !== null) throw new Error(elsewhere);

    const directives = directivesIn(census, label);
    if (directives.length === 0) return;
    const byFile = new Map<string, Directive[]>();
    for (const directive of directives) {
      byFile.set(directive.filename, [
        ...(byFile.get(directive.filename) ?? []),
        directive,
      ]);
    }
    for (const [filename, inFile] of byFile) {
      const path = join(copy, filename);
      if (!realpathSync(path).startsWith(inside)) {
        throw new Error(
          `${filename} in the blanked copy resolves outside it, so blanking ` +
            `it would edit the checkout.`,
        );
      }
      const source = readFileSync(path);
      const ranges = inFile.map((directive) =>
        commentToBlank(source, directive),
      );
      writeFileSync(path, blankedRanges(source, ranges));
    }
  }
  throw new Error(
    `oxlint still reported a directive after ${String(ROUNDS)} rounds of ` +
      `blanking every one it named, so the copy cannot be cleared and no count ` +
      `read over it is evidence.`,
  );
}

/**
 * What the blanked copy reports that the checkout does not, outside the
 * backlog, as `[code, file, message]` triples.
 *
 * **This is what a directive waives in an enforced rule**, and it is held by
 * equality with `WAIVED`. The backlog's share is held by the counts instead.
 */
function waivedIn(
  counted: Report,
  honoured: Report,
  backlogCodes: ReadonlySet<string>,
): [string, string, string][] {
  const present = new Set(honoured.diagnostics.map(findingKey));
  return counted.diagnostics
    .filter(
      (finding) =>
        !present.has(findingKey(finding)) && !backlogCodes.has(finding.code),
    )
    .map(({ code, filename, message }): [string, string, string] => [
      code,
      String(filename),
      String(message),
    ]);
}

/**
 * **A count beside a backlog entry is a measurement unless something
 * re-derives it**, and so is one beside a refusal in `SITED`, which these arms
 * read as one more counted line. The staleness arm above fires only when an entry reports
 * nothing, so a count could move either way with every arm green, and most
 * had: the first run of this arm found the stated figures wrong on most rows,
 * in both directions.
 *
 * **Equality, not a ceiling.** With found at most stated, a fix that lowers a
 * count without editing it leaves slack, and the next new site fills it green.
 * So every fix and every new site moves a number in the config, and the
 * failure prints each `(rule, stated, found)` that differs, so the repair is
 * one edit per row.
 *
 * **The count reads a tree with no directive text in it.** A directive
 * naming a backlog rule hides its site from any run that honours it, and the
 * directive census further down is per file, so one more in a file it already
 * names passes there too. So the count reads the copy `copyOfTheCheckout`
 * builds and `blankEveryDirective` clears.
 *
 * **Removing the text is the only thing that works, and a flag is not a
 * substitute.** A hooks disable directive switches off every React compiler
 * based rule in its whole enclosing component, enforced rules included,
 * because those rules read the comment text themselves rather than going
 * through directive suppression. The config option
 * `respectEslintDisableDirectives: false` was measured: it brings back the
 * named rule's own sites and leaves the three react backlog rows exactly where
 * the honouring run reads them. So a future oxlint flag that ignores
 * directives is measured against those rows before it replaces the copy.
 *
 * **What the copy adds outside the backlog is held too**, by equality with
 * `WAIVED` as `(code, file)` pairs. That is where the compiler rules a hooks
 * directive stands down appear, and where a second directive in a named file
 * hiding any enforced rule appears, which the per file directive census cannot
 * see. A second waived site in a named file reds by name, and so does a waiver
 * that has gone.
 *
 * **No finding is covered twice.** Every finding carries one rule, and the key
 * set arm refuses any per path scoping, so a directive is the only cover a
 * backlog finding can have besides its own entry, and the copy removes it.
 *
 * **What the copy is checked against**: no link or shared file with the
 * checkout, the baseline's file count and rule count, every finding the
 * honouring run reports, and the directive pattern,
 * which reads the copy's text with no help from oxlint. The last is the second
 * instrument for the census: a spelling oxlint honours without reporting it as
 * unused survives the blanking and reds there, if the pattern knows it. A
 * spelling both miss is past this arm.
 *
 * **What equality on a total cannot see**: a fix and a new site of the same
 * rule in one change, which leaves the total where it was, and the same for
 * one waived site swapped for another in the same file. For a refusal in
 * `SITED` the files are held too, so that swap passes only within one file. And a count edited to
 * match a new site is green: the edit is in the diff beside the reason, and
 * review is what reads it.
 */
describe("every backlog count", () => {
  it(
    "sits on its own entry's line, and the entries carrying one are the backlog and the sited refusals",
    () => {
      const suppressed = suppressedIn(rulesNamedInConfig(), effectiveLevels());
      const counted = backlogIn(readFileSync(CONFIG, "utf8")).map(
        ({ rule }) => rule,
      );

      // A sited refusal without its count reads as uncounted and reds below,
      // and one that is not a refusal at all reds here.
      expect(
        Object.keys(SITED).filter((rule) => !REFUSALS.includes(rule)),
        `SITED names a rule REFUSALS does not, so it would be counted as a ` +
          `backlog row under a refusal's name.`,
      ).toEqual([]);
      const stated = [
        ...REFUSALS.filter((rule) => !(rule in SITED)),
        ...counted,
      ];
      // Named in the message, because the equality's own diff truncates a list
      // this long before the entry that differs.
      const uncounted = suppressed.filter((rule) => !stated.includes(rule));
      const unexpected = stated.filter(
        (rule, at) => !suppressed.includes(rule) || stated.indexOf(rule) !== at,
      );

      expect(
        stated.sort(),
        `${CONFIG}'s suppressed rules are not exactly the refusals outside ` +
          `SITED plus the entries whose line ends in a count. Off with neither ` +
          `a count nor an uncounted refusal, or in SITED without its count: ` +
          `[${uncounted.join(", ")}]. Counted or refused and not off, named ` +
          `twice, or a refusal outside SITED carrying a count: ` +
          `[${unexpected.join(", ")}]. A counted entry ` +
          `carries its count as the whole of a trailing comment on its own line, ` +
          `"rule": "off", // N. A count on another line, anything after the ` +
          `digits, or an entry written twice reads as a different list here. ` +
          `A rule that is wrong about this codebase rather than unpaid is a ` +
          `refusal: add it to REFUSALS and write its reason above the entry in ` +
          `the config. A reason about its named sites puts it in SITED with ` +
          `their count; a reason about the codebase gives it none.`,
      ).toEqual([...suppressed].sort());
    },
    BUDGET,
  );

  it("is never zero", () => {
    expect(
      backlogIn(readFileSync(CONFIG, "utf8"))
        .filter(({ stated }) => stated === 0)
        .map(({ rule }) => rule),
      `a backlog entry stating 0 is either stale, a rule with no findings that ` +
        `should be turned on, or a key spelled under an alias plugin prefix, ` +
        `which oxlint accepts and reports under the canonical code, so the ` +
        `count reads zero and would agree with it. Delete a stale entry; spell ` +
        `an alias the way the report's code reads.`,
    ).toEqual([]);
  });

  it(
    "is the number oxlint finds with every disable directive blanked",
    () => {
      const backlog = backlogIn(readFileSync(CONFIG, "utf8"));
      const rules = backlog.map(({ rule }) => rule);
      const baseline = lint([]);
      const honoured = lint(rules);
      const copy = copyOfTheCheckout();

      expect(
        sharedWithItsSource(copy, ".", [CONFIG, ...TREES]),
        `these paths in the copy are links, or the same file as in the ` +
          `checkout, so blanking a directive in them writes to the checkout ` +
          `this file is measuring. The copy must follow every link.`,
      ).toEqual([]);

      blankEveryDirective(copy, baseline);
      const label = "the run denying the backlog over the blanked copy";
      const counted = lint(rules, copy, [], label);

      expect(differentTree(baseline, counted, label)).toBeNull();
      expect(deniedNothing(baseline, counted, rules.length, label)).toBeNull();
      expect(
        findingsMissingFrom(counted, honoured),
        `the blanked copy lacks findings the checkout reports. Blanking a ` +
          `directive can only add one, so the copy is not the tree and no ` +
          `count read over it describes ${CONFIG}.`,
      ).toEqual([]);
      expect(
        filesNamed(LINTABLE).filter((path) =>
          DIRECTIVE.test(readFileSync(join(copy, path), "utf8")),
        ),
        `these files in the blanked copy still carry text the directive ` +
          `pattern reads, which oxlint's census did not report. Either oxlint ` +
          `honours a spelling it does not report as unused, and a count here ` +
          `would miss what it hides, or the pattern reads text oxlint ignores.`,
      ).toEqual([]);

      expect(
        waivedIn(counted, honoured, new Set(rules.map(codeOf))).sort(),
        `with every disable directive blanked, these findings outside the ` +
          `backlog appear that the checkout does not report, so a directive ` +
          `waives them, and WAIVED does not say so. A hooks directive stands ` +
          `down every React compiler based rule in its component, enforced ` +
          `ones included. The message names what an omitted dependency ` +
          `waiver omits, so a new or swapped dependency reds here too. Remove ` +
          `the finding, or list the triple in WAIVED ` +
          `beside the directive's reason in DIRECTIVES.`,
      ).toEqual([...WAIVED].sort());

      expect(
        filesOfSited(counted),
        `a refusal in SITED is argued from its sites, so the files its findings ` +
          `sit in over the blanked copy are held as well as its count: a site ` +
          `moved to another file keeps the count and leaves the reason. Fix the ` +
          `new site, or argue it at the entry in ${CONFIG} and add its file here.`,
      ).toEqual(
        Object.fromEntries(
          Object.entries(SITED).map(([rule, files]) => [rule, new Set(files)]),
        ),
      );

      const wrong = countsThatDiffer(backlog, counted);
      expect(
        wrong,
        `(rule, stated, found): ${JSON.stringify(wrong)}. Each count in ` +
          `${CONFIG}, a backlog row's or a sited refusal's, is held equal to what oxlint finds with every disable ` +
          `directive blanked. Write the found figure on the entry's own line, ` +
          `in the commit that moved it. A found 0 means the entry is stale, ` +
          `or its key is under an alias prefix the report does not use: ` +
          `delete it, or spell the key as the report's code reads.`,
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
const CONFIGURED_ON = ["vitest/valid-expect", "vitest/expect-expect"];

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
  "vitest/expect-expect": [
    "error",
    {
      assertFunctionNames: [
        "expect",
        "expectTypeOf",
        "assert",
        "assertType",
        "witness",
      ],
    },
  ],
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
 * That is the real difference from a suppression, whose reason is a finding,
 * and whose count, the ratchet re-derives on every run: an exclusion's reason
 * is a number, no arm
 * reads it, and it goes stale in silence. One of them already did, between two
 * commits on this branch, with every arm green. Re-measure before relying on
 * one.
 *
 * Three of the nine are a different technology and are permanent. The rest are
 * candidates carrying what they would cost.
 */
const NOT_NAMED: Record<string, string> = {
  jest: "the wrong test runner. Its rules restate the vitest ones against an API this tree does not use, so naming it would double-report the require-to-throw-message and no-conditional-expect families the vitest plugin already enforces, and the valid-expect family at a number that moves with every two-argument assertion anybody writes. Permanent, so the total is not worth tracking.",
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

  it(
    "cannot narrow a count with an option on an entry that is off",
    () => {
      // `-D` keeps the options the config gives a rule, so an off entry written
      // with an allow list is counted with that list in force, and a new site of
      // the allowed shape is never counted. Measured: an allow list of five names
      // on `no-shadow` took its count from 35 to 14, with every arm green once
      // the 14 was written. An option belongs with the rule when it is turned on.
      const rules = readConfig().rules ?? {};
      const suppressed = suppressedIn(Object.keys(rules), effectiveLevels());

      expect(
        suppressed.filter((rule) => {
          const value = rules[rule];
          return Array.isArray(value) && value.length > 1;
        }),
        `these entries are off and carry options. An option narrows what the ` +
          `count arm counts, because a denial keeps it, so a new site of the ` +
          `shape it allows is never counted. Write the entry as plain "off".`,
      ).toEqual([]);
    },
    BUDGET,
  );

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
 * config cannot see at all.** It suppresses a rule for the line it names, and
 * a hooks directive far further: every React compiler based rule in its whole
 * enclosing component, enforced ones included, which `WAIVED` holds. It
 * carries no count, and this census re-derives nothing but the files.
 * The lint script asks for no unused directive report, so nothing reports
 * these in CI; the census the backlog counts run is a separate invocation.
 *
 * **This branch made two of them load bearing and said nothing.** Both
 * `exhaustive-deps` directives were inert while the react plugin was off.
 * Enabling it turned them live: removing all three takes the tree from 0
 * findings to 2, and both are that rule. So a plugin was adopted and two of
 * its findings were suppressed in the same change, invisibly.
 *
 * **One of them masks a refusal's site.** The directive in `lib/pdf.ts` is
 * the second site of `no-control-regex`, which is in `SITED`, so its count
 * reads through the blanked copy and states both. The directive is inert only
 * while the rule is off at top level.
 *
 * The set is pinned by equality, with a reason beside each, which is the
 * contract the suppression list already has. **It is a set of files**: a
 * directive in a file not named here reds, and a second one in a named file
 * does not. What that second one hides from a counted rule is still counted,
 * by the backlog count arm, which reads a copy with every directive blanked.
 */
const DIRECTIVES: Record<string, string> = {
  "src/pages/components/SearchBar.tsx":
    "exhaustive-deps. The debounce effect omits onSearch on purpose, because Home passes an inline callback and including it would restart the debounce on every render. LIVE since the react plugin was named. It also stands down every React compiler based rule in this component, enforced ones included: the backlog counts include what it hides, and WAIVED holds the rest.",
  "src/pages/ScanPage/components/BarcodeScanner.tsx":
    "exhaustive-deps. The teardown effect omits the deps the rule wants, which would restart the camera. LIVE since the react plugin was named. It also stands down every React compiler based rule in this component, enforced ones included: the backlog counts include what it hides, and WAIVED holds the rest.",
  "src/lib/pdf.ts":
    "no-control-regex, and it is the SECOND site of a refusal the config documents. Stripping the control characters a PDF producer pads metadata with is the point of that function. Inert while the rule is off at top level.",
};

/**
 * What the blanked copy reports outside the backlog that the checkout does
 * not, as `[code, file, message]` triples, each a finding a directive in
 * `DIRECTIVES` waives. Held by equality in the count arm.
 *
 * **Today it is each hooks directive's own rule, once per file**, which is the
 * waiver its reason argues for. A compiler based rule a hooks directive stands
 * down, or any enforced rule a second directive in a named file hides, arrives
 * here as a new triple and reds by name.
 *
 * **The message is held because it names the omitted dependencies**, which is
 * what each reason argues about. Without it the same file could swap the
 * waived effect for another, or the waived effect could read one more prop it
 * does not declare, with the code and the file unchanged and every arm green:
 * both measured, with lint at exit 0. The cost is an oxlint upgrade that
 * rewords the message, which reds with the new text printed.
 */
const WAIVED: [string, string, string][] = [
  [
    "react-hooks(exhaustive-deps)",
    "src/pages/ScanPage/components/BarcodeScanner.tsx",
    "React Hook useEffect has a missing dependency: 't'",
  ],
  [
    "react-hooks(exhaustive-deps)",
    "src/pages/components/SearchBar.tsx",
    "React Hook useEffect has a missing dependency: 'onSearch'",
  ],
];

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

/** A config's text holding these lines as its rules block. */
function configWith(...rules: string[]): string {
  return ["{", '  "rules": {', ...rules, "  }", "}"].join("\n");
}

describe("a backlog line", () => {
  it("is read with its count when the count is the whole trailing comment", () => {
    const raw = configWith(
      '    "no-await-in-loop": "off",',
      '    "no-shadow": "off", // 35',
      '    "react/refs": "off" // 6',
    );

    expect(backlogIn(raw)).toEqual([
      { rule: "no-shadow", stated: 35 },
      { rule: "react/refs", stated: 6 },
    ]);
  });

  it("is not read when anything follows the count", () => {
    expect(
      backlogIn(configWith('    "no-shadow": "off", // 35, over 4 files')),
    ).toEqual([]);
  });

  it("is not read when its count sits on the line below", () => {
    expect(
      backlogIn(configWith('    "no-shadow": "off",', "    // 35")),
    ).toEqual([]);
  });

  it("is not read outside the rules block", () => {
    const raw = ["{", '  "plugins": ["oxc"], // 3', '  "rules": {}', "}"].join(
      "\n",
    );

    expect(backlogIn(raw)).toEqual([]);
  });
});

describe("the code a config key is reported under", () => {
  it("is the plugin with the rule in parentheses", () => {
    expect(codeOf("unicorn/no-array-sort")).toBe("unicorn(no-array-sort)");
  });

  it("is spelled eslint for an unprefixed rule", () => {
    expect(codeOf("no-shadow")).toBe("eslint(no-shadow)");
  });
});

describe("a stated count", () => {
  const report = (...codes: string[]): Report => ({
    ...BASELINE,
    diagnostics: codes.map((code) => ({ code })),
  });

  it("names every rule whose count differs, either way", () => {
    const found = report(
      "eslint(no-shadow)",
      "eslint(no-shadow)",
      "react(refs)",
    );
    const backlog = [
      { rule: "no-shadow", stated: 1 },
      { rule: "react/refs", stated: 2 },
    ];

    expect(countsThatDiffer(backlog, found)).toEqual([
      ["no-shadow", 1, 2],
      ["react/refs", 2, 1],
    ]);
  });

  it("is held to zero for a rule the run did not report", () => {
    expect(
      countsThatDiffer([{ rule: "no-shadow", stated: 3 }], report()),
    ).toEqual([["no-shadow", 3, 0]]);
  });

  it("does not take the findings of another plugin's rule of the same name", () => {
    const found = report("eslint(no-shadow)", "typescript(no-shadow)");

    expect(countsThatDiffer([{ rule: "no-shadow", stated: 1 }], found)).toEqual(
      [],
    );
  });
});

describe("a census of disable directives", () => {
  const unused = {
    code: undefined as unknown as string,
    filename: "src/a.ts",
    labels: [{ span: { offset: 4, length: 30 } }],
  };

  it("is read as each directive's file and byte span", () => {
    const census = { ...BASELINE, number_of_rules: 0, diagnostics: [unused] };

    expect(directivesIn(census, "a probe")).toEqual([
      { filename: "src/a.ts", offset: 4, length: 30 },
    ]);
  });

  it("is refused when the run enabled a rule", () => {
    const census = { ...BASELINE, number_of_rules: 1, diagnostics: [unused] };

    expect(() => directivesIn(census, "a probe")).toThrow(/goes unreported/);
  });

  it("is refused when it carries a finding rather than a directive", () => {
    const census = {
      ...BASELINE,
      number_of_rules: 0,
      diagnostics: [{ ...unused, code: "eslint(no-shadow)" }],
    };

    expect(() => directivesIn(census, "a probe")).toThrow(/not a directive/);
  });
});

describe("a blanked directive", () => {
  const source = Buffer.from("const a = 1; // a note\nconst b = 2;\n");
  const at = source.indexOf("//");

  it("is spaces over its range, the rest of the file untouched", () => {
    expect(blankedRanges(source, [[at, at + 9]]).toString()).toBe(
      `const a = 1; ${" ".repeat(9)}\nconst b = 2;\n`,
    );
  });

  it("keeps the line breaks inside a block comment", () => {
    const block = Buffer.from("/* one\ntwo */\nx;\n");

    expect(blankedRanges(block, [[0, 13]]).toString()).toBe(
      `${" ".repeat(6)}\n${" ".repeat(6)}\nx;\n`,
    );
  });
});

/** Where `text` starts in `source`, as a span of its own length. */
function spanOf(source: Buffer, text: string): Directive {
  return {
    filename: "a.ts",
    offset: source.indexOf(text),
    length: text.length,
  };
}

describe("the range blanked for a reported directive", () => {
  it("is the span itself when the span opens a comment", () => {
    const source = Buffer.from("x;\n// a note\ny;\n");

    expect(commentToBlank(source, spanOf(source, "// a note"))).toEqual([
      3, 12,
    ]);
  });

  it("is the whole comment when an enable is reported by its body", () => {
    const source = Buffer.from("x;\n  /* eslint-enable */\ny;\n");
    const from = source.indexOf("/*");

    expect(commentToBlank(source, spanOf(source, " eslint-enable "))).toEqual([
      from,
      source.indexOf("*/") + 2,
    ]);
  });

  it("is the whole comment when an enable is reported by a rule it names", () => {
    const source = Buffer.from("/* eslint-enable no-shadow, no-console */\n");

    expect(commentToBlank(source, spanOf(source, "no-console"))).toEqual([
      0,
      source.indexOf("*/") + 2,
    ]);
  });

  it("is the whole comment when an enable in JSX children is reported by its body", () => {
    const source = Buffer.from("    <b />\n    {/* eslint-enable */}\n");
    const from = source.indexOf("/*");

    expect(commentToBlank(source, spanOf(source, " eslint-enable "))).toEqual([
      from,
      source.indexOf("*/") + 2,
    ]);
  });

  it("is refused when code precedes the brace that holds the comment", () => {
    const source = Buffer.from("x; {/* eslint-enable */}\n");

    expect(() =>
      commentToBlank(source, spanOf(source, " eslint-enable ")),
    ).toThrow(/neither opens a comment/);
  });

  it("is the rest of the line for an enable written as a line comment", () => {
    const source = Buffer.from("x;\n  // oxlint-enable no-shadow\ny;\n");

    expect(commentToBlank(source, spanOf(source, "no-shadow"))).toEqual([
      source.indexOf("//"),
      source.indexOf("\ny;"),
    ]);
  });

  it("is refused when the span sits in code", () => {
    const source = Buffer.from("const a = 1;\n");

    expect(() => commentToBlank(source, spanOf(source, "const"))).toThrow(
      /neither opens a comment/,
    );
  });

  it("is refused when the comment holding the span is not an enable", () => {
    const source = Buffer.from("/* a note */\n");

    expect(() => commentToBlank(source, spanOf(source, "note"))).toThrow(
      /neither opens a comment/,
    );
  });

  it("is refused when the comment holding the span does not begin its line", () => {
    const source = Buffer.from("x; /* eslint-enable */\n");

    expect(() =>
      commentToBlank(source, spanOf(source, " eslint-enable ")),
    ).toThrow(/neither opens a comment/);
  });

  it("is refused when the span runs past the comment's close", () => {
    const source = Buffer.from("/* eslint-enable */ x;\n");

    expect(() => commentToBlank(source, spanOf(source, "enable */ x"))).toThrow(
      /neither opens a comment/,
    );
  });
});

describe("a copy of the trees", () => {
  const fixture = join(REPORTS, "links");
  const source = join(fixture, "source");

  /** A tree holding a linked file and a linked directory. */
  const linkedTree = (): void => {
    rmSync(fixture, { recursive: true, force: true });
    mkdirSync(join(source, "t"), { recursive: true });
    mkdirSync(join(source, "elsewhere"));
    writeFileSync(join(source, "t", "a.ts"), "export const a = 1;\n");
    writeFileSync(join(source, "elsewhere", "b.ts"), "export const b = 2;\n");
    symlinkSync("a.ts", join(source, "t", "alias.ts"));
    symlinkSync(join("..", "elsewhere"), join(source, "t", "dir"));
  };

  it("follows every link, so nothing in it is shared with the source", () => {
    linkedTree();
    const copy = join(fixture, "copy");
    copyBeside(source, copy, ["t"]);

    expect(sharedWithItsSource(copy, source, ["t"])).toEqual([]);
    expect(readFileSync(join(copy, "t", "dir", "b.ts"), "utf8")).toBe(
      "export const b = 2;\n",
    );
  });

  it("names every link a copy that kept them carries", () => {
    linkedTree();
    const kept = join(fixture, "kept");
    cpSync(join(source, "t"), join(kept, "t"), { recursive: true });

    expect(sharedWithItsSource(kept, source, ["t"])).toEqual([
      join("t", "alias.ts"),
      join("t", "dir"),
    ]);
  });

  it("names a file that is the source file itself", () => {
    linkedTree();
    const hard = join(fixture, "hard");
    mkdirSync(join(hard, "t"), { recursive: true });
    linkSync(join(source, "t", "a.ts"), join(hard, "t", "a.ts"));

    expect(sharedWithItsSource(hard, source, ["t"])).toEqual([
      join("t", "a.ts"),
    ]);
  });
});

describe("what a directive waives", () => {
  const honoured = {
    ...BASELINE,
    diagnostics: [findingAt("eslint(no-shadow)", 9)],
  };

  it("is what the copy adds outside the backlog, as code, file and message", () => {
    const counted = {
      ...BASELINE,
      diagnostics: [
        findingAt("eslint(no-shadow)", 9),
        findingAt("react(refs)", 40),
        findingAt("react(purity)", 50, "the render reads Math.random"),
      ],
    };

    expect(waivedIn(counted, honoured, new Set(["react(refs)"]))).toEqual([
      ["react(purity)", "src/a.ts", "the render reads Math.random"],
    ]);
  });

  it("is nothing when the copy adds only backlog findings", () => {
    const counted = {
      ...BASELINE,
      diagnostics: [
        findingAt("eslint(no-shadow)", 9),
        findingAt("react(refs)", 40),
      ],
    };

    expect(waivedIn(counted, honoured, new Set(["react(refs)"]))).toEqual([]);
  });
});

/** A finding of `code` at one byte of one file. */
function findingAt(code: string, offset: number, message = "a note"): Finding {
  return {
    code,
    filename: "src/a.ts",
    message,
    labels: [{ span: { offset } }],
  };
}

describe("a blanked copy compared with the checkout", () => {
  it("lacks nothing when it reports every finding the checkout does, and more", () => {
    const honoured = {
      ...BASELINE,
      diagnostics: [findingAt("eslint(no-shadow)", 9)],
    };
    const copy = {
      ...BASELINE,
      diagnostics: [
        findingAt("eslint(no-shadow)", 9),
        findingAt("react(refs)", 40),
      ],
    };

    expect(findingsMissingFrom(copy, honoured)).toEqual([]);
  });

  it("names a finding the copy lost", () => {
    const honoured = {
      ...BASELINE,
      diagnostics: [findingAt("eslint(no-shadow)", 9)],
    };

    expect(findingsMissingFrom({ ...BASELINE }, honoured)).toEqual([
      "eslint(no-shadow) src/a.ts 9",
    ]);
  });
});
