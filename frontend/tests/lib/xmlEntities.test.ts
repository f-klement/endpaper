/**
 * @vitest-environment node
 *
 * A substring test over a string. No DOM, and building one would cost more than
 * this file spends running.
 */
/**
 * Tests for src/lib/xmlEntities.ts.
 *
 * **The refusal had no test of its own for as long as it sat at the reader
 * seam**, and four readers each pinned it through their own format: what an
 * EPUB, an FB2 and a CBZ do with a declaration is asserted in those files, and
 * what the rule itself refuses was asserted nowhere. The difference matters for
 * the two ends its docstring states and neither reader can reach: a reference
 * is not a declaration, and the exclusions are deliberate rather than a
 * substring test nobody finished.
 */

import { describe, expect, it } from "vitest";

import { MAX_OPF_BYTES } from "../../src/lib/calibre";
import { MAX_CACHE_BYTES } from "../../src/lib/kindle";
import { declaresEntities } from "../../src/lib/xmlEntities";

/**
 * Every module under `src/lib/`, as source, for the derivation at the foot of
 * this file. Read with `import.meta.glob` rather than `node:fs` so this needs
 * no `@types/node`, which is `houseRules.test.ts`'s reason and the same one.
 */
const SOURCES = import.meta.glob("../../src/lib/*.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("a document that declares its own entities", () => {
  it("is refused for a declaration in the internal subset", () => {
    expect(
      declaresEntities(
        '<?xml version="1.0"?>\n' +
          '<!DOCTYPE package [<!ENTITY blow "&blow;&blow;">]>\n' +
          "<package/>",
      ),
    ).toBe(true);
  });

  it("is refused for a parameter entity declaration", () => {
    // The parameter entity spelling, which is how a nested declaration is
    // usually written: the same three characters after the bang, so no second
    // rule is needed for it.
    expect(
      declaresEntities('<!DOCTYPE p [<!ENTITY % e SYSTEM "e.dtd">]>'),
    ).toBe(true);
  });

  it("is allowed for an ordinary document with no doctype", () => {
    expect(declaresEntities('<?xml version="1.0"?><package/>')).toBe(false);
  });

  it("is allowed for a document that references a predefined entity", () => {
    // **A reference is not a declaration**, and this is the arm that says so.
    // The five predefined entities expand to one character each and cost
    // nothing to expand, so a title carrying `&amp;` is an ordinary title. A
    // rule written against `&` rather than against `<!ENTITY` would refuse
    // every EPUB whose author has an ampersand in their name.
    expect(declaresEntities("<dc:title>Marks &amp; Spencer</dc:title>")).toBe(
      false,
    );
    expect(declaresEntities("<dc:title>&#38;</dc:title>")).toBe(false);
  });

  it("is refused for a declaration inside a comment", () => {
    // The exclusion the docstring states, pinned rather than left as prose: a
    // declaration that cannot expand is refused too. Being told a file is not
    // the format it claimed is the smaller harm, and the alternative is a rule
    // that has to know where the prolog ends.
    expect(declaresEntities('<!-- <!ENTITY e "x"> --><package/>')).toBe(true);
  });

  it("is refused for a declaration inside a CDATA section", () => {
    expect(declaresEntities('<d><![CDATA[<!ENTITY e "x">]]></d>')).toBe(true);
  });

  it("is refused wherever in the document the declaration sits", () => {
    // **The whole document and not its first bytes.** A leading comment is well
    // formed XML and may be any length, so a producer can put a declaration
    // past whatever prefix a reader looked at. Measured by the security seat:
    // `xml.slice(0, 200)` passed 164 of 164 across this file and the four
    // readers, because every other fixture here puts the declaration in the
    // first hundred or so bytes.
    //
    // **The pad is the largest document that can reach this rule, and it is
    // derived rather than written down.** A literal 4,096 was the first draft
    // and defended 4,096 bytes of 4,194,304: the same seat's `slice(0, 65536)`
    // then passed 151 of 151 against it.
    //
    // **Derived from the caps a caller exports, and there are two.** The others
    // are module private and smaller: `epub.MAX_PACKAGE_BYTES` at 4 MiB,
    // 1 MiB for `ComicInfo.xml`, 256 KiB for an FB2 header, 64 KiB for an EPUB
    // container. So the larger of these two is the widest of all six, and a
    // prefix that misses a declaration here misses one no bound would have
    // stopped. **A `Math.max` rather than a choice**, because a caller landed
    // with four times what this line had named as the widest: a new caller
    // wider than both has to export its cap and join this line, and the
    // derivation at the foot of this file is what makes such a caller arrive as
    // a failure rather than silently.
    //
    // **It allocates the widest cap, and that is a real cost in the suite pod
    // rather than here.** 16 MiB of code units is 32 MB of string and it grows
    // with whichever cap is widest, and the pod's memory limit is what a run
    // dies against. Worth knowing before a caller declares a much larger one.
    const padded =
      "<!--" +
      "x".repeat(Math.max(MAX_OPF_BYTES, MAX_CACHE_BYTES)) +
      '--><!DOCTYPE p [<!ENTITY e "x">]><p/>';

    expect(declaresEntities(padded)).toBe(true);
  });

  it("is allowed for the lower case spelling, which declares nothing", () => {
    // **Not a hole.** XML markup declarations are case sensitive, so `<!entity`
    // is not a declaration in any conforming parser: a document carrying one is
    // refused by the engine before it can expand anything. Matching it would
    // refuse a document that is merely broken, which is a different sentence to
    // a member and a worse one.
    expect(declaresEntities('<!DOCTYPE p [<!entity e "x">]>')).toBe(false);
  });
});

/**
 * The source with comments removed, so a rule cannot be satisfied by prose.
 *
 * Without it a comment naming `declaresEntities(` puts a module into the
 * calling set, which is the direction that hides a reader parsing without the
 * rule. Measured.
 *
 * `houseRules.test.ts` has the same two lines and they are not shared: a test
 * importing another test file evaluates that file's `describe`s.
 *
 * **It cuts inside a string literal containing `//`, which is the defect the
 * shared copy already carries**, so a module whose only mention of either name
 * sat after such a literal on one line would be misread. No module under
 * `src/lib/` is shaped that way, and this copy is no better than the one it
 * mirrors, which is the whole of what duplicating it costs.
 */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
}

/**
 * Which readers apply this rule, derived rather than listed.
 *
 * **The set is derived here because a count in prose does not recount itself.**
 * Two of them in one docstring were stale, and neither was visible in a diff
 * nor red in a run.
 *
 * The rule this asserts: a module under `src/lib/` that builds a `DOMParser`
 * refuses a declaration first, because expansion happens inside the parser and
 * no caller can bound it afterwards. Three do not, and each is named below with
 * the reason it is outside the rule rather than lax about it.
 *
 * **Matched on the constructor and deliberately not on the media type.** The
 * media type reads as though it told XML from HTML, when what it tells apart is
 * one spelling of XML from every other. A module parsing `"text/xml"`, which
 * `DOMParser` treats identically, left this file green; probed across 13
 * spellings of the same call, 11 evaded, including
 * `application/xhtml+xml`, a media type held in a constant, and **the line
 * break prettier inserts when the call exceeds the print width**, which is the
 * one nobody chooses. `new DOMParser(` is one spelling, it is short enough that
 * no formatter breaks it, and every caller has to write it.
 *
 * **What still evades, stated rather than left to be found**, and the list is
 * as complete as two seats got it: a parser constructed in one module and used
 * in another; a construction reached through an alias, `new window.DOMParser(`
 * and `new globalThis.DOMParser(` among them; and a string literal containing
 * `//` sitting before the constructor on one physical line, which `withoutProse`
 * cuts away with the rest of that line. The last was reached end to end and
 * needed a line of 80 characters or fewer to survive `format:check`, and no
 * plausible reader was found that would write one. The bound on all of them is
 * the directory, `houseRules.test.ts`'s reason for the same scope: a module
 * outside `src/lib/` is outside this rule until it moves there.
 *
 * **Both directions, which is the half a list of names cannot do.** A reader
 * added and not calling the rule fails, and so does an exemption for a module
 * that no longer builds a parser.
 */
describe("a reader that parses a whole document refuses a declaration first", () => {
  /**
   * The three modules that build a parser and do not call the rule.
   *
   * `pdf.ts` cuts an XMP packet down to its root element, so what reaches the
   * parser has no prolog for a declaration to sit in, and says so at its own
   * site. `calibre.ts::plainText` and `takeout.ts::readSidecar` parse
   * `text/html`, whose parser has no internal subset to expand, so both are
   * outside the rule rather than exempt from it.
   *
   * Named as modules rather than as expressions because what puts each outside
   * is the shape of what it parses rather than a call it makes.
   */
  const EXEMPT = ["lib/calibre.ts", "lib/pdf.ts", "lib/takeout.ts"];

  /**
   * The one exemption no scan over source can check.
   *
   * What puts `pdf.ts` outside the rule is the value it hands the parser, a
   * packet already cut to its root element, and that is a fact about a runtime
   * value. Named here rather than left out of `EXEMPT`, so the arm below is
   * that list less this one name rather than a second copy of it: a fourth
   * exemption added to `EXEMPT` alone reached no check at all, measured.
   *
   * **What that leaves open, said rather than implied.** This module is outside
   * the equality's requirement to call the rule and outside both arms below, so
   * it is the softest of the eight: a second XML parse added there, refusing
   * nothing, is seen by nothing here. What holds it is its own docstring and a
   * reader of its diff.
   */
  const UNCHECKABLE = "lib/pdf.ts";

  /** This module's own definition, which is not a call site. */
  const RULE = "lib/xmlEntities.ts";

  function modules(): [string, string][] {
    return Object.entries(SOURCES).map(([path, source]) => [
      path.replace("../../src/", ""),
      withoutProse(source),
    ]);
  }

  function matching(pattern: RegExp): string[] {
    return modules()
      .filter(([path]) => path !== RULE)
      .filter(([, code]) => pattern.test(code))
      .map(([path]) => path)
      .sort();
  }

  const parses = () => matching(/new DOMParser\(/);
  const refuses = () => matching(/\bdeclaresEntities\(/);

  it("is every module that builds one, and only those", () => {
    expect(parses()).toEqual([...refuses(), ...EXEMPT].sort());
  });

  /**
   * The index of the closing quote of the string literal starting at `at`, or
   * `at` where no literal starts there.
   *
   * **The two scanners below know what a string is**, because otherwise a
   * bracket or a comma inside one is counted as code:
   * `parseFromString(html.replace("(", ""), "text/xml")` left the counter a
   * level deep at the call's real closing paren and it read on into the module
   * until it reached somebody else's `"text/html"`, and `html.replace("&nbsp;",
   * " ")` is an ordinary thing for an html reader to do. Measured, both.
   */
  function endOfString(code: string, at: number): number {
    const quote = code[at];
    if (quote !== '"' && quote !== "'" && quote !== "`") return at;
    for (let end = at + 1; end < code.length; end += 1) {
      if (code[end] === "\\") end += 1;
      else if (code[end] === quote) return end;
    }
    return code.length;
  }

  /**
   * The media type each `parseFromString(` call in `code` names, or `null`
   * where the scan ran to the end of the source without closing.
   *
   * **A scanner rather than a pattern over syntax**, because three shapes
   * defeat a pattern here: a nested call's own paren, the line break prettier
   * inserts when a call exceeds the print width, and a quote span that runs
   * across the code sitting between two literals rather than matching either.
   *
   * **The media type is a position and not a presence**, so the list is split
   * at its own top level comma and the last element is the answer:
   * `parseFromString(html + "text/html", "text/xml")` names html and parses
   * XML.
   *
   * **It fails loud and never open**, which is the one property to take from
   * it: a shape it cannot read answers a slice of the wrong text or `null`,
   * neither being the literal, and where the damage takes the call itself the
   * module leaves the parsing set and the equality reddens instead.
   *
   * That was the last claim here about behaviour no test asserted, so the
   * shapes are now inputs in `answers no media type for a shape it cannot
   * read` rather than sentences. **There is also a reason and not only a
   * search**: `last` re-scans from its own index zero, so the answer can only
   * be the literal if the slice ends at a top level one, which needs depth back
   * at zero immediately after it, and there the scan sits inside a mis-paired
   * string where a closing paren is invisible. **The exclusion is the one gap this does not hold at
   * all**: a third argument would make the last element the third, and what
   * refuses it is the compiler, `parseFromString` taking two parameters, with
   * `typecheck` in the gate.
   */
  function mediaTypes(code: string): (string | null)[] {
    const found: (string | null)[] = [];
    const needle = "parseFromString(";
    for (
      let at = code.indexOf(needle);
      at !== -1;
      at = code.indexOf(needle, at + 1)
    ) {
      const opened = at + needle.length - 1;
      let depth = 0;
      let end = opened;
      for (; end < code.length; end += 1) {
        end = endOfString(code, end);
        if (code[end] === "(") depth += 1;
        else if (code[end] === ")" && --depth === 0) break;
      }
      found.push(
        end === code.length ? null : last(code.slice(opened + 1, end)),
      );
    }
    return found;
  }

  /**
   * The last element of an argument list, split at its own top level comma.
   *
   * **A trailing comma is not an empty last argument.** Prettier writes one
   * whenever it breaks a call across lines, and splitting naively answered the
   * empty string for a perfectly good html parse.
   */
  function last(args: string): string {
    const parts: string[] = [];
    let depth = 0;
    let from = 0;
    for (let at = 0; at < args.length; at += 1) {
      at = endOfString(args, at);
      const character = args[at]!;
      if ("([{".includes(character)) depth += 1;
      else if (")]}".includes(character)) depth -= 1;
      else if (character === "," && depth === 0) {
        parts.push(args.slice(from, at));
        from = at + 1;
      }
    }
    parts.push(args.slice(from));
    return (
      parts.map((part) => part.trim()).findLast((part) => part !== "") ?? ""
    );
  }

  it("answers no media type for a shape it cannot read", () => {
    // **The claim above, as inputs rather than as prose**, which is what turns
    // the one remaining behavioural sentence in that docstring from stated into
    // asserted.
    //
    // **A sample and not every shape either seat tried.** What is here is the
    // set that separates a readable call from an unreadable one, rather than
    // the set that was attempted, and the shapes that were tried and are not
    // here all came back correct.
    const unreadable: [string, string][] = [
      [
        "a quote inside a regex literal",
        'new DOMParser().parseFromString(html.replace(/"/g, ""), "text/html");\nconst after = "x";',
      ],
      [
        "a comment opener inside a string",
        withoutProse(
          'new DOMParser().parseFromString(html.replace("/*", ""), "text/html");\n/* a later block */',
        ),
      ],
      [
        "the literal concatenated into another argument",
        'new DOMParser().parseFromString(html + "text/html", "text/xml");',
      ],
      [
        "the literal inside a nested call",
        'new DOMParser().parseFromString(wrap(html, "text/html"), "text/xml");',
      ],
      [
        "an unbalanced paren inside a string",
        'new DOMParser().parseFromString(html.replace("(", ""), "text/xml");\nconst real = "text/html";',
      ],
      [
        "a second call that is the bad one",
        'new DOMParser().parseFromString(html, "text/html");\nnew DOMParser().parseFromString(html, "text/xml");',
      ],
    ];

    // **Built from the answer, and inverted**: it says at least one element is
    // not the literal, and an empty answer fails it because `[]` equals
    // `[].map(...)`, which is what catches a `mediaTypes` answering nothing.
    //
    // **`a second call that is the bad one` is the only fixture here carrying
    // two calls**, so it is what pins how many the scanner reads and is not a
    // duplicate of the five above it. Measured: a `mediaTypes` returning only
    // the first call leaves the other five green.
    for (const [what, code] of unreadable) {
      expect(mediaTypes(code), what).not.toEqual(
        mediaTypes(code).map(() => '"text/html"'),
      );
    }
  });

  it("reads the media type of every shape it can", () => {
    // The other half, and it is the half that stops the arm above being
    // satisfied by a function that answers nothing for everything. The last two
    // are ordinary lines an html reader writes, and each was a red suite once.
    const readable = [
      'new DOMParser().parseFromString(html, "text/html");',
      'new DOMParser().parseFromString(\n  aVeryLongVariableNameIndeed,\n  "text/html",\n);',
      'new DOMParser().parseFromString(html.replace("&nbsp;", " "), "text/html");',
      'const note = "see https://example.invalid/x";\nnew DOMParser().parseFromString(html, "text/html");',
    ];

    for (const code of readable) {
      expect(mediaTypes(code), code).toEqual(['"text/html"']);
    }

    // **One input carrying two calls, so the array's length is asserted
    // against something other than itself.** Without it, a `mediaTypes` reading
    // only the first call was green on all thirteen arms and then admitted a
    // second, XML parse. Measured, and found by the seat that did not write
    // these two.
    expect(
      mediaTypes(
        'new DOMParser().parseFromString(head, "text/html");\nnew DOMParser().parseFromString(body, "text/html");',
      ),
    ).toEqual(['"text/html"', '"text/html"']);
  });

  it("lets a checkable exemption make no parse that is not an html one", () => {
    // **Asserted at the position the parser reads.** A media type held in a
    // constant, built from a template, or sitting in an argument list this
    // cannot read fails rather than passing, which is a real constraint on two
    // modules and a loud one.
    for (const path of EXEMPT.filter((one) => one !== UNCHECKABLE)) {
      const code = modules().find(([one]) => one === path)?.[1] ?? "";
      // **The expectation is built from the source and not from the answer.**
      // It used to be `types.map(() => the literal)`, which cannot notice a
      // missing element, so a `mediaTypes` reading only the first call passed
      // every arm here and then let a second, XML parse through. Measured.
      const calls = (code.match(/parseFromString\(/g) ?? []).length;
      expect(
        calls,
        `${path} parses nothing and needs no exemption`,
      ).toBeGreaterThan(0);
      expect(
        mediaTypes(code),
        `${path} makes a parse this cannot read as an html one`,
      ).toEqual(Array.from({ length: calls }, () => '"text/html"'));
    }
  });

  it("is reading a source tree at all", () => {
    // A glob that resolved nothing would satisfy the equality above with three
    // names on one side and three on the other, which is the evasion this
    // closes. It is also the only arm that notices every caller dropping the
    // rule at once while the exempt three keep parsing.
    expect(refuses().length).toBeGreaterThan(1);
  });
});
