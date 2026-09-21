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
 * An `it()` or `test()` call written out rather than generated.
 *
 * The register quotes this pattern beside the figure it produces, because the
 * split between written and generated moves with the instrument while the total
 * does not. `[^.\w]` is what keeps `it.each` out: that call generates its cases
 * and is counted in the residual, which is the whole point of the pair.
 */
export const WRITTEN_OUT = /(?:^|[^.\w])(?:it|test)\(/g;

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
  /** Tests the run collected, per file, relative to the test root. */
  counts: ReadonlyMap<string, number>;
  /** Calls matching `WRITTEN_OUT`, per file. */
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
 */
export function matched(
  census: Census,
  patterns: string[],
): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of census.counts.keys())
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
    `**${writtenOut} are written out and ${total - writtenOut} are generated**, over the ${files(generating)} that generate any.`,
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

  for (const { pattern, stated } of declared) {
    const covered = [...hits].filter(([, patternsHit]) =>
      patternsHit.includes(pattern),
    );
    if (covered.length === 0) {
      found.push(`\`${pattern}\` matches no file this run collected`);
      continue;
    }
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

  const fresh = render(census, patterns);
  if (blockOf(register) !== fresh)
    found.push(
      "the measured block is not what this run counted. It is generated: " +
        "replace the text between the fences with what follows, and read what " +
        `moved rather than adjusting a figure by the delta.\n${fresh}`,
    );

  return found;
}
