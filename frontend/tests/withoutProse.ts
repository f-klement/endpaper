/**
 * The one comment stripper, and the one thing that decides how to parse a path.
 *
 * **One home, so that holding the rule is using it.** The tree had two
 * instruments for the same job: this one, parser backed, and a hand written
 * scanner in `zipFailureVocabulary.test.ts` that tracked strings by quote
 * character, which fails in two directions at once. A quote inside a regex
 * literal, or a backtick inside a comment, opened a string it never left, so
 * the markers after it went unread; and a template's interpolated code is
 * string interior to such a scanner, so a comment written there went unread
 * where the template itself was read correctly. Measured over the 461 modules
 * under `src/`: prose left standing in three, one of the first shape and two of
 * the second. That
 * second one was not wrong about anything it was asked today; what it was is a
 * second instrument with a blind spot of its own, where the tree had just paid
 * to fix this one's, and the next rule written against it inherits a gap
 * already paid for once.
 *
 * **Not a test file, because a test file cannot be imported.** Importing a
 * `.test.ts` runs its suites again inside the importer, so the reader that
 * needs the stripper would silently double every rule in the exporting file.
 *
 * `withoutProse.test.ts` beside this holds what it keeps, what it removes, and
 * the rule that no second one appears.
 */
import { parseAst } from "vite";

type Node = { type: string } & Record<string, unknown>;

function isNode(value: unknown): value is Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** What a path says about how to parse it. */
export function langOf(path: string): "ts" | "tsx" {
  return path.endsWith(".tsx") ? "tsx" : "ts";
}

/**
 * The node kinds where a comment cannot begin, which is all a stripper needs
 * from a parser.
 *
 * `parseAst` hands back a Program carrying `type`, `body`, `sourceType`,
 * `hashbang`, `start` and `end`, and no list of comments: measured at vite 8.
 * So there is no comment range to delete and this takes the complement. Three
 * kinds are the places where a slash pair is characters rather than prose: a
 * string literal, one chunk of a template, and the text between two JSX tags.
 * A regex literal is a `Literal` too, so it needs no arm of its own.
 *
 * The walk stops at one of them rather than descending, which is what keeps a
 * template's interpolated expressions ordinary code: a comment written inside
 * one is still removed.
 */
const NOT_PROSE = new Set(["Literal", "TemplateElement", "JSXText"]);

/** Which offsets of `source` sit inside one of those. */
function insideALiteral(source: string, lang: "ts" | "tsx"): Uint8Array {
  const inside = new Uint8Array(source.length);
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) walk(item);
      return;
    }
    if (!isNode(value)) return;
    if (NOT_PROSE.has(value.type)) {
      const { start, end } = value as { start?: unknown; end?: unknown };
      if (typeof start === "number" && typeof end === "number")
        inside.fill(1, start, end);
      return;
    }
    for (const key of Object.keys(value)) walk(value[key]);
  };
  walk(parseAst(source, { lang }));
  return inside;
}

/**
 * What ends a line comment, which is four characters and not one.
 *
 * **The set is closed**, so enumerating it is not the open set enumeration this
 * tree's guards keep paying for: ECMAScript defines exactly these four as
 * line terminators. The regex pair this replaced stopped at all four for free,
 * because JavaScript's `.` excludes them, and a scan that stopped at `\n` alone
 * deletes whatever follows a comment on a CR, LS or PS line from what every
 * reader here sees. Measured by the security seat on a copy of the
 * tree: a `fetch` written after a `//` and a U+2028 in `lib/opf.ts` left
 * `keeps every reader out of reach of the network` green at 97 of 97 passing,
 * and the same line written with `\n` failed it.
 *
 * `prettier --check` rewrites all three to `\n` and CI runs it, which is a
 * mitigation and not the guard: it fails the format job, not the rule.
 *
 * **All four are in a fixture row beside, and the fourth is why that is said
 * here.**
 * The row carried three, and dropping U+2029 from this string left the file
 * green at 98 of 98. Closed is what makes a set safe to enumerate; it is not
 * what makes a member tested. Check it by dropping each in turn.
 */
const ENDS_A_LINE = "\n\r\u2028\u2029";

/**
 * One stripped source per language, keyed on the text.
 *
 * A pure function of its two arguments, so this is a cache and not state. It
 * is here because parsing is not free where a regex was: fifteen readers in
 * `houseRules.test.ts` over
 * the 456 modules under `src/` cost 4,672ms parsed against 91ms matched, and
 * 337ms parsed once per module. Measured on the control plane, bun 1.4.2; the
 * ratio is the point rather than the absolute.
 */
const STRIPPED: Record<"ts" | "tsx", Map<string, string>> = {
  ts: new Map(),
  tsx: new Map(),
};

/**
 * The source with comments removed, so a rule cannot be satisfied by prose.
 *
 * **Stripped by parsed ranges, because a comment is not a line shape and a
 * slash pair is not a comment.** This was two regexes, and both of them edited
 * code. Measured over the 456 modules under `src/`, twice and by two routes:
 * the regex pair deleted 4,577 characters in 12 of them, of which 3,223 are not
 * whitespace. 1,532 of those sit inside a string literal, which is a truncated
 * URL; the other 1,691, on 114 lines in 10 modules, sit outside one, which is
 * an ordinary statement. Every rule reading through here read the tree with all
 * of it missing,
 * and three of the twelve modules are `lib/goodreads.ts`, `lib/opf.ts` and
 * `lib/pdf.ts`, which are subjects of the rule that keeps a file reader out of
 * reach of the network. The direction is a false negative, which is the one
 * this repository's guard rules call the dangerous one: a rule looks at less
 * than it says it does and passes.
 *
 * **The two ways it happened, neither of which a further regex closes.** A
 * `//` inside a string literal cut the line at the scheme, so a URL in an
 * attribute became `href="https:`. And an opening slash star inside a literal
 * or inside a line comment opened a block that ran to the next closing one:
 * `accept="image/*"` in `pages/ScanPage/components/LookupResult.tsx` swallowed
 * the next sixteen lines of JSX, and a line comment quoting a wildcard media
 * type in `api/mutator.ts` swallowed the `Accept` header the module sets.
 *
 * **What the swap changed, measured rather than argued.** Over `src/` the
 * parsed form removes nothing the regex form kept, zero characters, so every
 * reader sees at least as much as it did. Seventeen values derived by the
 * fifteen readers in `houseRules.test.ts` were computed under both and none moved, so no rule
 * changed verdict on this tree; what changed is what they can see on the next.
 *
 * **What it newly refuses is a source that does not parse.** A regex returns
 * something for any text at all. Every module under `src/` parses, and
 * `strips every module the rules read` is the arm that keeps that a failure
 * naming the file rather than a stack inside whichever rule reached it first.
 */
export function withoutProse(source: string, lang: "ts" | "tsx"): string {
  const cached = STRIPPED[lang].get(source);
  if (cached !== undefined) return cached;

  const inside = insideALiteral(source, lang);
  let code = "";
  let at = 0;
  while (at < source.length) {
    if (!inside[at]) {
      if (source.startsWith("//", at)) {
        let end = at + 2;
        while (end < source.length && !ENDS_A_LINE.includes(source[end]!))
          end += 1;
        at = end;
        continue;
      }
      if (source.startsWith("/*", at)) {
        const close = source.indexOf("*/", at + 2);
        at = close === -1 ? source.length : close + 2;
        continue;
      }
    }
    code += source[at];
    at += 1;
  }

  STRIPPED[lang].set(source, code);
  return code;
}
