import { describe, expect, it } from "vitest";

import {
  childrenNamed,
  elementChildren,
  firstNamed,
} from "../../src/lib/elementChildren";
import { langOf, withoutProse } from "../withoutProse";

function parse(xml: string): Element {
  const root = new DOMParser().parseFromString(
    xml,
    "application/xml",
  ).documentElement;
  // A parser that refused the fixture answers a `parsererror` document rather
  // than throwing, so a malformed fixture would otherwise read as a node with
  // no children and pass half the arms below.
  if (root === null || root.localName === "parsererror")
    throw new Error(`the fixture did not parse: ${xml}`);
  return root;
}

const NAMES = (elements: readonly Element[]): string[] =>
  elements.map((element) => element.localName);

describe("walking the element children of one node", () => {
  it("answers every child in document order", () => {
    const root = parse("<r><a/><b/><a/></r>");
    expect(NAMES([...elementChildren(root)])).toEqual(["a", "b", "a"]);
  });

  it("answers nothing for a node with no element children", () => {
    expect([...elementChildren(parse("<r>text only</r>"))]).toEqual([]);
  });

  it("passes over text and comments between the elements", () => {
    // The walk steps by `nextElementSibling`, so this is what it buys over a
    // `childNodes` loop: a pretty printed document is whitespace between every
    // pair, and a comment is a node the reader must never see as a field.
    const root = parse("<r>\n  <a/>\n  <!-- note -->\n  <b/>\n</r>");
    expect(NAMES([...elementChildren(root)])).toEqual(["a", "b"]);
  });

  it("stops at the match rather than reading to the end of the list", () => {
    // The property the generator is for, and the one a reader of a member's
    // file pays for: `firstNamed` on a 900 child list touches the children
    // before its match and no others. Asserted against a hand built chain
    // rather than a parsed document, because what is being counted is how many
    // links the walk followed and a DOM will not say.
    const followed: string[] = [];
    const link = (name: string, next: Element | null): Element =>
      ({
        localName: name,
        get nextElementSibling() {
          followed.push(name);
          return next;
        },
      }) as unknown as Element;
    const late = link("late", null);
    const parent = {
      firstElementChild: link("wanted", late),
    } as unknown as Element;

    expect(firstNamed(parent, "wanted")?.localName).toBe("wanted");
    expect(followed).toEqual([]);

    expect(childrenNamed(parent, "late")).toHaveLength(1);
    expect(followed).toEqual(["wanted", "late"]);
  });

  it("answers only the children whose local name matches", () => {
    const root = parse("<r><a/><b/><a/></r>");
    expect(NAMES(childrenNamed(root, "a"))).toEqual(["a", "a"]);
  });

  it("answers an empty list for a name no child carries", () => {
    expect(childrenNamed(parse("<r><a/></r>"), "b")).toEqual([]);
  });

  it("looks no deeper than the children", () => {
    // What every caller of this depends on and no caller states twice: a
    // format whose subtree repeats a name must not have the deeper one
    // answered. A comic's `<Pages>` holds a `<Page>` per page; an FB2
    // `<document-info>` holds the converter as an `<author>`.
    const root = parse("<r><wrapper><a/></wrapper></r>");
    expect(childrenNamed(root, "a")).toEqual([]);
  });

  it("matches the local name where the document declared a prefix", () => {
    // Conceded here once so no format inherits it in silence: a document that
    // declares a prefix and spells `x:a` is answered for `a`.
    const root = parse('<r xmlns:x="urn:example"><x:a/></r>');
    expect(NAMES(childrenNamed(root, "a"))).toEqual(["a"]);
  });

  it("answers the first matching child and not merely the first child", () => {
    const root = parse("<r><b/><a id='wanted'/><a/></r>");
    expect(firstNamed(root, "a")?.getAttribute("id")).toBe("wanted");
  });

  it("answers null for a name no child carries", () => {
    expect(firstNamed(parse("<r><a/></r>"), "b")).toBeNull();
  });

  it("answers null for a parent that was not found", () => {
    // The reason this door takes an absent parent at all: a reader descending a
    // member's document may find nothing at any step, and making each site test
    // first turns a chain of four lookups into four guards, one of which is the
    // one that gets forgotten.
    expect(firstNamed(null, "a")).toBeNull();
    expect(firstNamed(undefined, "a")).toBeNull();
  });
});

/**
 * The walk is spelled in one module, asserted over the tree.
 *
 * **An exact set and never a count.** A count is an inequality, and a stated
 * bound in this tree has already stopped guarding without ever failing because
 * a smaller number is a weaker claim. An exact set fails in both directions: a
 * seventh reader that writes its own walk fails it, and so does removing a
 * module from the list below without converting it, so an entry here cannot
 * outlive its reason.
 *
 * **Read through the comment stripper**, because four of the copies this rule
 * exists for described the walk in a docstring and the module that owns it has
 * to be able to say what it does.
 *
 * **Four anchors and not two, because the DOM's element traversal is closed at
 * four.** A walk written `lastElementChild` and `previousElementSibling` is
 * this same loop, taken the other way, for this same reason: a reader wanting
 * the last `<dc:date>` writes it without a thought. Enumerating here is safe
 * for the reason `ENDS_A_LINE` in `tests/withoutProse.ts` gives for its own
 * four, and it is the same reason: the set is closed by a specification rather
 * than open to whatever the tree grows next, so there is no fifth to go stale
 * against. That file also says what closure does not buy, and the arm below
 * takes it: closed is what makes a set safe to enumerate, not what makes a
 * member tested, so each of the four is dropped in turn.
 *
 * **What this does not see, stated rather than bounded.** It detects the walk
 * by an anchor. A reader that re-derives the same traversal by spreading
 * `parent.children`, by filtering `childNodes` on node type, or by narrowing a
 * subtree search afterwards writes no anchor and is invisible here. Those are
 * the shapes this walk exists to avoid rather than further copies of it, which
 * is why the rule is written on the walk; how else a traversal could be spelled
 * is open and is not claimed.
 *
 * **And two routes past the last arm are open by decision rather than by
 * oversight.** That arm holds one module to one import statement and one
 * binding; a door re-exported through any `lib/` module, its own included, or taken by a
 * dynamic `import()`, reaches it without writing either. Closing them needs a
 * rule over every module that names the home, which is a larger instrument
 * than an arm, and neither is what a reader of that module plausibly writes.
 * Named here so the next reader meets them as a decision.
 */
describe("the sibling walk has one home", () => {
  const SOURCES = import.meta.glob("../../src/**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  const HOME = "../../src/lib/elementChildren.ts";

  /**
   * The modules outside the home that spell an anchor, and what each is.
   *
   * **Named for what the list holds and not for why each member is on it**,
   * because the two are not the same and the honest name is the weaker one.
   * Two of the readers this rule was written for still carry their own walk:
   * `adobeDigitalEditions.ts` wants the generator spread and `cbz.ts` wants
   * `firstNamed` with its own trim around it, and neither was converted here
   * because this change did not own their test files, where a source moved
   * without its tests is the half of a change that looks done.
   *
   * **A module that merely reads one adjacency lands here too, and is exempted
   * rather than converted.** Reading one child, or stepping to one sibling,
   * once is not a walk, and two of the four anchors are child reads rather
   * than sibling steps. There is no door in the home module to route such a
   * read through, and this rule fires on the identifier and cannot tell the
   * two apart, so an entry here says only that the module spells the word. An
   * entry that is such a read says so in a comment beside it, and is not a
   * debt.
   */
  const SPELLS_AN_ANCHOR = [
    // Both still carry their own walk.
    "../../src/lib/adobeDigitalEditions.ts",
    "../../src/lib/cbz.ts",
  ];

  const ANCHORS =
    /\b(?:first|last)ElementChild\b|\b(?:next|previous)ElementSibling\b/;

  const spellsAnAnchor = (): string[] =>
    Object.entries(SOURCES)
      .filter(([path, source]) =>
        ANCHORS.test(withoutProse(source, langOf(path))),
      )
      .map(([path]) => path)
      .sort();

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make every rule below pass for ever.
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect(Object.keys(SOURCES)).toContain(HOME);
  });

  it("sees the walk in its own home, so the rule below is not vacuous", () => {
    // Also what a rename of the home module fails on: the path leaves the glob
    // and this arm reports it by name rather than the set equality reporting a
    // difference in two directions at once.
    expect(spellsAnAnchor()).toContain(HOME);
  });

  it("spells an anchor nowhere but its home and the modules named above", () => {
    expect(spellsAnAnchor()).toEqual([HOME, ...SPELLS_AN_ANCHOR].sort());
  });

  it("does not take a walk described in prose for a walk", () => {
    // The stripper is load bearing and not a tidiness. No module names an
    // anchor in prose today, which is a fact about this tree and not a
    // property of it: the readers that carried the loop described it, and the
    // module that owns it now has every reason to write one of these words
    // down. A rule reading raw source would then report a walk in whichever
    // file explained one.
    const described = [
      "// a sibling walk uses nextElementSibling",
      "/** Steps by firstElementChild. */",
      'const label = "firstElementChild";',
    ].join("\n");
    expect(ANCHORS.test(withoutProse(described, "ts"))).toBe(true);
    expect(
      ANCHORS.test(
        withoutProse(described.split("\n").slice(0, 2).join("\n"), "ts"),
      ),
    ).toBe(false);
  });

  it("observes each of the four anchors on its own", () => {
    // Closure makes the set above safe to enumerate and does nothing to show
    // that a member of it is watched. `ENDS_A_LINE` in `tests/withoutProse.ts`
    // learned that by dropping one of its four and staying green. So each is
    // spelled alone here: three of the four appear nowhere under `src/` today,
    // and without this arm three quarters of the pattern would be untested.
    const missed = ["first", "last"]
      .map((end) => `${end}ElementChild`)
      .concat(["next", "previous"].map((way) => `${way}ElementSibling`))
      .filter((anchor) => !ANCHORS.test(`const x = parent.${anchor};`));

    expect(missed).toEqual([]);
  });

  it("keeps the Kindle reader's lookups behind its own typed binding", () => {
    // **The one thing the shared module cannot hold for a caller.** The door
    // it exports takes a `string`; `kindle.ts` narrows it to `KindleElement`
    // in a one line binding and every lookup there goes through that, which is
    // what keeps its `ELEMENTS` argument true: nothing outside a closed list
    // reaches the document. What used to enforce that was the type of the only
    // function in scope. Importing the shared door put a `string` taking
    // function in scope, so a new lookup calling it directly now typechecks,
    // and that objection was answered in prose with nothing failing.
    //
    // **Two assertions, and what each holds, stated rather than generalised.**
    // The count holds the binding's own name to two spellings, the import and
    // the binding's body, so a third use of that name is a lookup that went
    // around the binding. The second holds every import of the home module, as
    // the whole list of them against one exact line.
    //
    // **The whole list against an exact line, and each half of that was bought
    // separately.** A count of statements is satisfied by adding a specifier
    // to the one already there, and `{ childrenNamed as namedChildren,
    // firstNamed }` is one line, one statement, typechecks, and is what this
    // module writes the day it wants `firstNamed`. Taking only the first match
    // is then satisfied by a second statement below it. Matching on the
    // statement rather than on a brace group is the third half of it: a
    // namespace import has no braces and binds the whole module. It is brittle
    // to reformatting on purpose, and the format check in the gate is what
    // holds the spelling still.
    //
    // **What the pair does not hold.** Two routes are known open and are left
    // so deliberately: a re-export of the door through any `lib/` module, its own included,
    // and a dynamic `import()` inside a reader. Closing either needs a rule
    // over every module that names the home, which is a larger instrument than
    // this arm is, and both are contrived where the specifier above is not.
    // **So this arm holds one import statement and one binding, and claims
    // nothing about a door reached some other way.** Three rounds on this file
    // have had the comment claim a family the assertion did not hold; the
    // remedy is to stop claiming rather than to claim better.
    const source = withoutProse(SOURCES["../../src/lib/kindle.ts"]!, "ts");
    expect(source.match(/\bnamedChildren\b/g) ?? []).toHaveLength(2);
    expect(
      source.match(/import[^;]*from "\.\/elementChildren"/g) ?? [],
    ).toEqual([
      'import { childrenNamed as namedChildren } from "./elementChildren"',
    ]);
  });
});
