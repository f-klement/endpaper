/**
 * What `COVERAGE.md` claims, against what a run counted.
 *
 * The comparison only. Reading files and failing the run are the reporter's
 * job, so everything here is a function of two strings and a map, which is what
 * lets `coverageRegister.test.ts` drive it against censuses it made up.
 *
 * **A row is a glob, not a filename.** Several rows stand for a directory, and
 * counting a row as one file is how the register came to state 81 rows over 179
 * files where a run had 82 over 180.
 */

import { parseAst } from "vite";

import { langOf } from "./withoutProse";

export const BEGIN = "<!-- measured: begin -->";
export const END = "<!-- measured: end -->";

/**
 * A row: a backticked pattern in the first cell, a count in the second.
 *
 * Both are read inside their own cell. A number allowed to reach across a `|`
 * is a claim about the next column, and the next column here is a sentence
 * about what the file covers, full of numbers that are not test counts.
 */
const ROW = /^\|[ \t]*`([^`]+)`[ \t]*\|[ \t]*(\d+)[ \t]*\|/gm;

/**
 * How many tests a file writes out, as against generates.
 *
 * **Counted from the parsed source, because a count matched against source text
 * was wrong about one file.** The rule used to be a regex,
 * `/(?:^|[^.\w])(?:it|test)\(/g`, matched against the raw text, so an `it(`
 * written inside a string counted as a test the file wrote out.
 * `coverageRegister.test.ts` writes two fixture test files into string literals,
 * so it published a written out figure that was too high and a generated figure
 * that was too low, and it was published as a file that generates cases while
 * generating none. **It is the only file that moves**, 29 to 27 at `fee91e9`:
 * `houseRules.test.ts` also writes test source into strings, and every one of
 * its matches is a real call, so its figure is the same under either instrument.
 * No count for it stands here. It moves with every house rule arm added, and the
 * sibling in `coverageRegister.globalSetup.ts` declines to write its own figure
 * for that reason: a number beside a rule is read as current long after it stops
 * being so. The property is what this sentence needs.
 *
 * **The rule is unchanged: a call whose callee is the bare name.** `it.each(...)`
 * generates its cases and its callee is a member expression, so it is counted in
 * the residual, which is the whole point of the pair. That is what the regex's
 * `[^.\w]` was for, and reading it off the callee is the same rule without the
 * text.
 *
 * **Blind spot, stated rather than closed.** Every modifier form is a member
 * expression too, `it.skip(`, `test.only(` and the rest, so such a call is
 * counted as generated when it generates nothing. This is exactly what the regex
 * did, so no figure moves; closing it means naming which modifiers generate,
 * which is a list of spellings somebody else controls, and the residual is where
 * the pair already puts what it cannot name. None is present in this tree today.
 *
 * **A hand written scanner was written here first and `withoutProse.test.ts`
 * refused it**, on the rule that the stripping has one home. It was right twice
 * over: that scanner tracked quoted strings by their quote character, and an
 * apostrophe in prose, in JSX text or inside a regular expression literal opened
 * a string it never left. Measured before the refusal, over the 198 test files:
 * 14 moved and one went from 30 calls to 1. That is the same failure the home's
 * own docstring records paying for once already.
 *
 * `parseAst` refuses a source that does not parse, which is a figure not
 * returned rather than a wrong one. Its own message carries an excerpt and no
 * path, and the reporter calls this inside a loop over every file the run
 * collected, so the path is added here or the reader gets an excerpt and no way
 * to tell which of 198 files it came from. Not reachable today: the suite's
 * `include` collects only `.test.ts` and `.test.tsx`, and all of them parse.
 */
export function countWrittenOut(source: string, path: string): number {
  let count = 0;
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (typeof value !== "object" || value === null) return;
    const node = value as Record<string, unknown>;
    if (node.type === "CallExpression") {
      const callee = node.callee as Record<string, unknown> | undefined;
      // The name is what decides. **The kind is a belt and is deliberately
      // unarmed**: no arm distinguishes it, because no callee kind carrying a
      // `.name` that is not an `Identifier` could be constructed, so an arm for
      // it would pin a case nothing can reach. Dropping it moves no figure.
      if (
        callee?.type === "Identifier" &&
        (callee.name === "it" || callee.name === "test")
      )
        count += 1;
    }
    for (const key of Object.keys(node)) walk(node[key]);
  };
  try {
    walk(parseAst(source, { lang: langOf(path) }));
  } catch (error) {
    throw new Error(
      `${path} did not parse, so this run cannot count what it writes out: ` +
        `${error instanceof Error ? error.message : String(error)}`,
    );
  }
  return count;
}

/**
 * The declaration the publish gate demands of an internal file and refuses to
 * publish, with the window it reads.
 *
 * Spelled here as well as in the backend's own census because this tree cannot
 * import that one, and because a published file may not read the gate's script
 * to learn either. Both halves are the gate's, transcribed: the anchor allows a
 * short run of non alphanumerics, so a comment or a list marker in front of the
 * sentence still counts.
 */
const DECLARES_ITSELF_INTERNAL =
  /^[^A-Za-z0-9]{0,6}[ \t]*\*\*This file is internal\.\*\*/m;
const HEADER_LINES = 30;

export function declaresItselfInternal(source: string): boolean {
  return DECLARES_ITSELF_INTERNAL.test(
    source.split("\n").slice(0, HEADER_LINES).join("\n"),
  );
}

export interface Census {
  /**
   * Every test file vitest discovered, whether or not this run executed it.
   *
   * **The second instrument, and the rules about which files the document
   * names are asked of this one.** `counts` is what ran; a narrowed run has
   * fewer of them and can say nothing about any count, but the question of
   * whether every file in the tree has a row does not depend on running any
   * of them. Before this field existed a narrowed run checked **nothing**: not
   * the counts, not the rows, not the contradiction between a stripped file
   * and a row naming it.
   */
  discovered: ReadonlySet<string>;
  /** Tests the run collected, per file, relative to the test root. */
  counts: ReadonlyMap<string, number>;
  /** What `countWrittenOut` found, per file. */
  writtenOut: ReadonlyMap<string, number>;
  /**
   * The files this published register may not name.
   *
   * Empty today: no frontend test file is on the publish gate's strip list. It
   * exists because the backend register has nine of them, and without it the
   * two gates contradict each other on the day the first one appears here,
   * this file demanding a row for a file the publish gate refuses to let it
   * name. Both critic seats reached that independently.
   */
  internal: ReadonlySet<string>;
}

/**
 * Whether this census can answer about counts as well as about rows.
 *
 * **A property of the census rather than a flag a caller passes**, so that no
 * caller can get the gate wrong and the one place it is decided is here. The
 * reporter reads it to say so in the log; `problems` reads it to decide which
 * rules may speak.
 *
 * Size and not the set, because the two failures are different: a run of the
 * right size over different names means the two instruments have stopped
 * spelling the same tree, which the reporter refuses outright rather than
 * treating as an ordinary narrowing.
 */
export function isWhole(census: Census): boolean {
  return census.counts.size === census.discovered.size;
}

export interface Row {
  pattern: string;
  stated: number;
}

export function rowsOf(register: string): Row[] {
  return [...register.matchAll(ROW)].flatMap((match) => {
    const [, pattern, stated] = match;
    // Both groups are mandatory in the pattern, so a match without them cannot
    // happen; dropping the row rather than asserting it away keeps the failure
    // a missing row, which every rule here reports, instead of a crash.
    return pattern && stated ? [{ pattern, stated: Number(stated) }] : [];
  });
}

/**
 * The text between the fences.
 *
 * Throws where they are missing rather than returning nothing to compare: a
 * guard whose input has gone would otherwise pass by comparing nothing with
 * nothing.
 */
export function blockOf(register: string): string {
  const begin = register.indexOf(BEGIN);
  const end = register.indexOf(END);
  if (begin < 0 || end < 0)
    throw new Error(
      `COVERAGE.md carries no measured block. Expected ${BEGIN} and ${END}.`,
    );
  return register.slice(begin + BEGIN.length, end);
}

/** Whether a row's pattern covers a file. `*` crosses directories. */
export function covers(pattern: string, file: string): boolean {
  const expanded = pattern
    .split("*")
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${expanded}$`).test(file);
}

function files(count: number): string {
  return count === 1 ? "1 file" : `${count} files`;
}

function rows(count: number): string {
  return count === 1 ? "1 row" : `${count} rows`;
}

function sum(values: Iterable<number>): number {
  let total = 0;
  for (const value of values) total += value;
  return total;
}

/**
 * Which rows cover each file the register is allowed to describe.
 *
 * A file it may not name is outside this map altogether, so no row's sum counts
 * it and it is never reported as undescribed. That a row covers one anyway is a
 * separate problem, reported on its own.
 *
 * **Over what vitest discovered, not over what this run executed.** Keyed on
 * `counts` it was empty of every file a narrowed run skipped, so the row rules
 * read a tree of whatever size the command line asked for and found nothing
 * wrong with it.
 */
export function matched(
  census: Census,
  patterns: string[],
): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of census.discovered)
    if (!census.internal.has(file))
      found.set(
        file,
        patterns.filter((pattern) => covers(pattern, file)),
      );
  return found;
}

/**
 * The block the register carries, from one run's own figures.
 *
 * Every number the document states about itself is rendered here from one
 * census, so the arithmetic between them holds by construction. The register
 * used to state the identity and ask the reader to check it, and the readers
 * who checked were wrong six times in two days.
 */
export function render(census: Census, patterns: string[]): string {
  const total = sum(census.counts.values());
  const writtenOut = sum(census.writtenOut.values());
  const generating = [...census.counts].filter(
    ([file, count]) => count !== census.writtenOut.get(file),
  ).length;
  const shortfall = [...census.counts]
    .filter(([file]) => census.internal.has(file))
    .reduce((carried, [, count]) => carried + count, 0);
  return [
    // Two, because prettier separates the opening fence from what follows it
    // and a block this does not render byte for byte is one the formatter and
    // the guard argue about on every run.
    "",
    "",
    `**${total} tests, in ${files(census.counts.size)}**, counted by the run that reads this line.`,
    census.internal.size === 0
      ? `**${rows(patterns.length)} below, and every file this run collected has one.**`
      : `**${rows(patterns.length)} below.** The other ${shortfall} tests are in ${files(census.internal.size)} this register may not name.`,
    // **A participle, because the noun pluralises and a finite verb would have
    // to agree with it.** `that generate any` reads "the 1 file that generate
    // any" whenever exactly one file generates, and this block is rendered into
    // a published register, so the disagreement publishes. Unreachable at 29
    // files; the arm below pinned the broken wording rather than the rule.
    `**${writtenOut} are written out and ${total - writtenOut} are generated**, over the ${files(generating)} generating any.`,
    "",
  ].join("\n");
}

/**
 * Everything this run says the register has wrong, one line each.
 *
 * A list rather than the first failure, because what a person needs when a wave
 * lands is every row that moved, not the alphabetically first one.
 */
export function problems(register: string, census: Census): string[] {
  const declared = rowsOf(register);
  const patterns = declared.map((row) => row.pattern);
  const hits = matched(census, patterns);
  const found: string[] = [];
  // **Which rules a narrowed run may still ask**, which is the half the
  // backend half of this register already had and this one did not. Every rule
  // here used to sit downstream of the reporter's early return, so a narrowed
  // run checked nothing at all. The three guarded below are the only ones that
  // read a count; the rest read the document against the tree and hold on any
  // run.
  const whole = isWhole(census);

  // **Reported first, and refused rather than clamped, because the block below
  // states a property this is the only thing making true.** `render` calls a file
  // generating when its collected count differs from its written out figure, and
  // that is also true when written out is the LARGER of the two, where the file
  // generates nothing at all. Such a file is published as one of the files
  // generating any, and the generated half is understated by the difference.
  // **At `fee91e9` `coverageRegister.test.ts` was in exactly that state**, 29
  // written out against 27 collected, because the instrument counted two `it(`
  // calls written inside string literals. Fixing the instrument removed the one
  // live instance and left the state reachable: a call in a helper nothing
  // invokes is written out and collected nowhere. Clamping would make the
  // sentence true and the figures quietly wrong, so this refuses instead, and the
  // block's claim then holds by construction rather than by luck.
  // Empty rather than wrapped in an `if`, so the block below keeps one
  // indentation and the guard is the same expression the other two use.
  const comparable: ReadonlyMap<string, number> = whole
    ? census.counts
    : new Map();
  for (const [file, count] of comparable) {
    // `?? 0` is an unarmed belt and stays one: the reporter fills both maps in a
    // single loop over the same modules, so a file present in one and absent from
    // the other has no reachable case, and an arm for it would pin nothing.
    const writtenOut = census.writtenOut.get(file) ?? 0;
    if (writtenOut > count)
      found.push(
        `${file}: ${writtenOut} written out against ${count} collected. ` +
          "Nothing writes out more than it collects, so the instrument counting " +
          "written out has seen something the run did not, and both the " +
          "generated figure and the count of files generating any are wrong.",
      );
  }

  for (const { pattern, stated } of declared) {
    const covered = [...hits].filter(([, patternsHit]) =>
      patternsHit.includes(pattern),
    );
    if (covered.length === 0) {
      found.push(`\`${pattern}\` matches no file in this test tree`);
      continue;
    }
    if (!whole) continue;
    const counted = sum(covered.map(([file]) => census.counts.get(file) ?? 0));
    if (counted !== stated)
      found.push(
        `\`${pattern}\`: the register says ${stated}, the run counted ${counted} over ${files(covered.length)}`,
      );
  }

  for (const [file, patternsHit] of hits)
    if (patternsHit.length > 1)
      found.push(
        `${file} is matched by ${patternsHit.length} rows (${patternsHit.join(", ")}), so its tests are counted that many times`,
      );

  for (const file of census.internal)
    if (patterns.some((pattern) => covers(pattern, file)))
      found.push(
        `${file} declares itself internal, so the publish gate strips it and a ` +
          "row naming it fails that gate, but a row covers it",
      );

  // **Named, never absorbed into a count.** A figure for the files nothing
  // describes is satisfied by any file, so a new one lands by editing a digit;
  // this way the only two answers are a row or a deliberate deletion.
  const unnamed = [...hits]
    .filter(([, patternsHit]) => patternsHit.length === 0)
    .map(([file]) => file);
  if (unnamed.length > 0)
    found.push(
      `these files have no row: ${unnamed.join(", ")}. A row says what the file ` +
        `covers, which is the half of this register a run cannot write.`,
    );

  if (!whole) return found;

  const fresh = render(census, patterns);
  if (blockOf(register) !== fresh)
    found.push(
      "the measured block is not what this run counted. It is generated: " +
        "replace the text between the fences with what follows, and read what " +
        `moved rather than adjusting a figure by the delta.\n${fresh}`,
    );

  return found;
}
