/**
 * @vitest-environment jsdom
 *
 * **jsdom rather than the suite's happy-dom, and this is not a preference.**
 * `kindle.test.ts` carries the measurement for the same parser and the same
 * question, and it is not repeated here: happy-dom reads a declaration written
 * with single quotes as HTML, so an ordinary catalogue comes back with a
 * `documentElement` of `html`, and it recovers an unclosed element into a well
 * formed document where a browser and jsdom both report `parsererror`. The
 * first would hide a real reader working and the second a real one failing.
 * `a declaration written with single quotes` below is the arm that catches the
 * first coming back.
 */
/**
 * The Adobe Digital Editions reader, against catalogue shaped documents built
 * here.
 *
 * **Every document below is constructed and none came off a machine.** No
 * machine running this app is reachable from where this was written, and unlike
 * the Kindle store there is no published capture of this catalogue either: a
 * search covering a code host's index as well as the web found none.
 * `src/lib/adobeDigitalEditions.ts` names the sources the element vocabulary
 * comes from and the date they were read. That module is their one home.
 *
 * **Two things in these fixtures are invented, and both are inert.** The
 * catalogue's root element is not published, so `manifest` below names one; and
 * the `de` prefix's namespace URI is not published, so the declarations below
 * carry a placeholder. The reader names neither: it looks for a `contentRecord`
 * wherever it sits and matches every element by local name. So neither
 * invention can make a fixture pass where a real file would fail, which is the
 * property `a catalogue whose root is something else again` and
 * `elements carrying no prefix at all` are here to hold.
 *
 * A fixture presented as a real install's catalogue when it is not would be
 * worse than no fixture, so this paragraph is the fixture's provenance and is
 * meant to be read before the assertions below are trusted.
 */

import { describe, expect, it, vi } from "vitest";

import {
  MAX_CATALOGUE_BYTES,
  readDigitalEditionsCatalogueFile,
  readDigitalEditionsLibrary,
  type DigitalEditionsBook,
  type DigitalEditionsLibrary,
} from "../../src/lib/adobeDigitalEditions";

// The module's own source, for the two rules below that recompute a list rather
// than restating it. A `?raw` specifier is a different module id, so this is a
// string and not a second evaluation of the reader.
import readerSource from "../../src/lib/adobeDigitalEditions.ts?raw";

/** Adobe's own prefix, bound to a URI nothing published. See the docblock. */
const DE = 'xmlns:de="urn:example:not-published"';

/** Dublin Core, whose URI is published and is the real one. */
const DC = 'xmlns:dc="http://purl.org/dc/elements/1.1/"';

/** One `<de:contentRecord>`, with only the elements it is given. */
function record(elements: string): string {
  return `<de:contentRecord>${elements}</de:contentRecord>`;
}

/**
 * A whole library manifest, the layout the 1.x line wrote.
 *
 * **No XML declaration**, so that a doctype can be put in front of one below.
 * Whether this catalogue carries a declaration is not published, and a reader
 * that needed one would read no file that did not. `a declaration written with
 * single quotes` is where one is asserted.
 */
function manifest(...records: string[]): string {
  return `<de:manifest ${DE} ${DC}>${records.join("")}</de:manifest>`;
}

/**
 * One book's manifest, the layout the 2.0 line and later write.
 *
 * The whole file is the record, which is why the reader counts records rather
 * than expecting a list to hold them.
 */
function perBookManifest(elements: string): string {
  return `<de:contentRecord ${DE} ${DC}>${elements}</de:contentRecord>`;
}

/**
 * One record carrying every element this reader knows, and one it does not.
 *
 * `de:thumbnailID` is here and is read by nothing, which is what proves the
 * reader names its elements rather than taking whatever a record holds.
 */
const FULL = record(`
  <dc:title>A Constructed Title</dc:title>
  <dc:creator>Surname, Given</dc:creator>
  <dc:publisher>A Constructed Publisher</dc:publisher>
  <dc:identifier>urn:uuid:00000000-0000-4000-8000-000000000001</dc:identifier>
  <de:thumbnailID>Thumbnails/not-read.jpg</de:thumbnailID>
`);

/**
 * The same elements, wrapped one level down in a container.
 *
 * **The shape the module's own weakest evidence points at.** Adobe's fulfilment
 * file for the same book carries the `dc:` terms in one metadata block, so a
 * reader taking direct children only would answer nothing for a record written
 * this way, and a record with no title is skipped: the cost would be the book
 * rather than a field.
 */
const WRAPPED = record(`
  <de:metadata>
    <dc:title>A Wrapped Title</dc:title>
    <dc:creator>Wrapped, Author</dc:creator>
    <dc:publisher>A Wrapped Publisher</dc:publisher>
    <dc:identifier>urn:uuid:00000000-0000-4000-8000-000000000002</dc:identifier>
  </de:metadata>
`);

/** A record carrying a title and nothing else. */
function titled(title: string): string {
  return record(`<dc:title>${title}</dc:title>`);
}

/**
 * The `FIELDS` array as the reader declares it, in the order it declares it.
 *
 * Read out of the source rather than restated, so the two rules below that turn
 * on it cannot agree with a declaration that has moved.
 */
function declaredFields(): string[] {
  const array =
    /const FIELDS: readonly DigitalEditionsField\[\] = \[([^\]]+)\]/.exec(
      readerSource,
    );
  expect(array, "the FIELDS declaration moved").not.toBeNull();
  return [...array![1]!.matchAll(/"([^"]+)"/g)].map((match) => match[1]!);
}

/**
 * The source with comments removed, so a rule cannot be satisfied by prose.
 *
 * `houseRules.test.ts` and `xmlEntities.test.ts` each keep their own copy and
 * state why: a test importing another test file evaluates that file's
 * `describe`s. This is the third, with the same known defect, that it cuts
 * inside a string literal containing `//`. No module under `src/lib/` is shaped
 * that way.
 */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
}

/**
 * The index just past the delimiter that closes the one opening at `open`.
 *
 * **Balanced and not "the next one"**, which is the whole of why it exists: a
 * parameter list can hold braces, in a destructured parameter or in a type, and
 * a body can hold them anywhere.
 */
function past(code: string, open: number): number | null {
  const openers = "([{";
  const closers = ")]}";
  let depth = 0;
  for (let at = open; at < code.length; at += 1) {
    if (openers.includes(code[at]!)) depth += 1;
    else if (closers.includes(code[at]!)) {
      depth -= 1;
      if (depth === 0) return at + 1;
    }
  }
  return null;
}

/**
 * Whether nothing but whitespace follows `at` on its line.
 */
function endsLine(code: string, at: number): boolean {
  const lineEnd = code.indexOf("\n", at);
  const rest =
    lineEnd === -1 ? code.slice(at + 1) : code.slice(at + 1, lineEnd);
  return rest.trim() === "";
}

/**
 * The body of the function whose parameter list opens at `open`.
 *
 * **Two braces have to be told apart and neither is "the first one".** The
 * parameter list's, which is inside the parentheses and is skipped by balancing
 * them; and a return type's, which sits between the parameters and the body.
 * Both arrived as mutations that shipped with every arm green: a third parameter
 * typed `{ deep?: boolean }`, and a parameter typed `{ node: Element }`.
 *
 * **A body's braces both end their lines, and a return type's do not.** That is
 * the rule, and it is two ended because one end was not enough. Taking the first
 * brace that ends its line was the third draft and it reads a return type
 * prettier wrapped across lines, which is what prettier does to any object type
 * past the print width; the design seat shipped one of three fields with
 * `format:check`, `typecheck` and all 52 arms green. A body's closing brace is
 * alone on its line, where a wrapped return type's is followed by ` {` and a
 * union's first group by ` |`.
 *
 * **What it rests on, and the residual, stated rather than implied.** It rests
 * on prettier, which `format:check` runs over this tree and which is in the
 * gate. Its residual is any shape where prettier puts a brace that is not a
 * body's alone at the end of a line: neither seat could construct one and
 * neither claims there is none. **This is the fourth rule of its kind in three
 * rounds and each was defeated by the next shape of the same family**, which is
 * what an enumeration looks like; what would end the family is a parser, and
 * this tree has none. Said here because the next person to touch it should know
 * it is a better enumeration rather than an escape from one.
 *
 * **It fails closed, and it did not until the scan was bounded.** Walking on
 * after a brace pair that fails the rule reaches end of file, so it returned the
 * next qualifying pair whoever's it was: for a named function expression in an
 * argument position, whose `}` is followed by `});`, it returned a `for` block
 * further down and found no self call in it. 52 of 52 green, measured by the
 * security seat. **Fail closed is the property that makes an enumeration
 * survivable**, so it was the one sentence here that mattered and the one that
 * was not true. The scan now stops at the end of the declaration it was asked
 * about, and the caller's `has no body` assertion turns that into a red arm
 * naming the function.
 *
 * **The order of the two branches below is the fix's own bug, kept as a
 * comment.** Refusing a closer before skipping a group reddens the shipped
 * reader, because `Element[]` in a return type closes a bracket; the group skip
 * has to come first. Found by a run rather than by reading, on the seat's own
 * first draft.
 */
function bodyOf(code: string, open: number): string | null {
  const from = past(code, open);
  if (from === null) return null;
  for (let at = from; at < code.length; at += 1) {
    const here = code[at]!;
    if (here === ";") return null;
    if (here === "(" || here === "[") {
      const skip = past(code, at);
      if (skip === null) return null;
      at = skip - 1;
      continue;
    }
    if (here === ")" || here === "]" || here === "}") return null;
    if (here !== "{") continue;
    const end = past(code, at);
    if (end === null) return null;
    if (!endsLine(code, at) || !endsLine(code, end - 1)) {
      // Stepped over as a group rather than a character at a time, so a return
      // type is passed rather than re-entered.
      at = end - 1;
      continue;
    }
    return code.slice(at + 1, end - 1);
  }
  return null;
}

/**
 * Every `const`, `let` or `var` that binds a function, as name and initialiser.
 *
 * **The signature is never matched, and that is the point.** A return type, a
 * generic parameter list or a destructured parameter can all sit between the `=`
 * and the `=>`, so a pattern over the arrow's spelling loses to one of them: a
 * draft matching `const walk = (at) =>` went green on
 * `const walk = (at: Element): void =>`. What tells a bound function from an
 * arrow passed as an argument is depth rather than spelling, so this asks
 * whether an `=>` occurs at depth zero of the initialiser. The design seat's
 * answer, taken whole.
 *
 * **Angle brackets are not depth here**, so a `=>` inside a type argument to a
 * call reads as a bound function: `const memo = useMemo<() => void>(fn, []);`
 * is taken as one. A type annotation is not, because it sits before the
 * assignment and the scan starts after it. That direction is a red arm rather
 * than a silent miss, which is the way round to be wrong. Both measured by the
 * design seat, which also found the annotation named here first was the wrong
 * example for a claim that is true.
 */
function functionBindings(code: string): { name: string; body: string }[] {
  const found: { name: string; body: string }[] = [];
  for (const binding of code.matchAll(/\b(?:const|let|var)\s+(\w+)\b/g)) {
    let at = binding.index + binding[0].length;
    let depth = 0;
    let start: number | null = null;
    for (; at < code.length; at += 1) {
      const here = code[at]!;
      if ("([{".includes(here)) depth += 1;
      else if (")]}".includes(here)) depth -= 1;
      else if (here === ";" && depth === 0) break;
      else if (
        here === "=" &&
        depth === 0 &&
        code[at + 1] !== "=" &&
        code[at + 1] !== ">" &&
        !"=!<>".includes(code[at - 1]!)
      ) {
        start = at + 1;
        at += 1;
        break;
      }
    }
    if (start === null) continue;

    depth = 0;
    let arrow = false;
    let end = code.length;
    for (; at < code.length; at += 1) {
      const here = code[at]!;
      if ("([{".includes(here)) depth += 1;
      else if (")]}".includes(here)) depth -= 1;
      else if (here === ";" && depth === 0) {
        end = at;
        break;
      } else if (here === "=" && code[at + 1] === ">" && depth === 0) {
        arrow = true;
      }
    }
    if (arrow) found.push({ name: binding[1]!, body: code.slice(start, end) });
  }
  return found;
}

/** The library, or a failure raised where the assertion can see it. */
function libraryOn(...records: string[]): DigitalEditionsLibrary {
  const read = readDigitalEditionsLibrary(manifest(...records));
  if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
  return read.library;
}

function booksOn(...records: string[]): readonly DigitalEditionsBook[] {
  return libraryOn(...records).books;
}

describe("reading a catalogue", () => {
  it("gives back a book with every element the record carries", () => {
    const [book] = booksOn(FULL);

    expect(book).toEqual({
      record: 1,
      title: "A Constructed Title",
      authors: ["Surname, Given"],
      publisher: "A Constructed Publisher",
      identifier: "urn:uuid:00000000-0000-4000-8000-000000000001",
    } satisfies DigitalEditionsBook);
  });

  it("reads a record whose metadata sits in a container", () => {
    const [book] = booksOn(WRAPPED);

    expect(book).toEqual({
      record: 1,
      title: "A Wrapped Title",
      authors: ["Wrapped, Author"],
      publisher: "A Wrapped Publisher",
      identifier: "urn:uuid:00000000-0000-4000-8000-000000000002",
    } satisfies DigitalEditionsBook);
  });

  it("prefers the record's own element to one in a container beside it", () => {
    // **The regression the last fix round introduced, in both orders.** Reading
    // descendants alone takes the first match in document order, so a container
    // that is not a record and sits first wins: that gave a record a cover
    // caption for its title and a photographer for an author, and reordering the
    // same three elements gave the right answers. A read that goes no deeper
    // loses a field, which `missing` reports; a read that prefers whatever came
    // first puts a wrong book on a shelf, which nothing reports.
    const own = `
      <dc:title>The Real Title</dc:title>
      <dc:creator>Author, Real</dc:creator>`;
    const foreign = `
      <de:cover>
        <dc:title>cover caption</dc:title>
        <dc:creator>Photographer, A</dc:creator>
      </de:cover>`;

    for (const elements of [foreign + own, own + foreign]) {
      const [book] = booksOn(record(elements));

      expect(book).toMatchObject({
        title: "The Real Title",
        authors: ["Author, Real"],
      });
    }
  });

  it("reads an element's own text and not one nested inside it twice", () => {
    // The other half of the walk's stated pair: a match is not descended into,
    // so an element nested inside a match is that match's text rather than a
    // second answer.
    //
    // **The container is what makes this arm observe the walk**, and it is not
    // the only route to a match inside a match: a nested creator under a direct
    // child creator reaches the same answer through `within`'s own branch,
    // without the walk running at all. Simplify this fixture to a direct child
    // and it goes green observing nothing.
    const [book] = booksOn(
      record(`
        <de:metadata>
          <dc:title>A Wrapped Title</dc:title>
          <dc:creator>Outer, Name<dc:creator>Inner, Name</dc:creator></dc:creator>
        </de:metadata>
      `),
    );

    expect(book!.authors).toEqual(["Outer, NameInner, Name"]);
  });

  it("does not take a nested record's title for the record around it", () => {
    // The second rule the walk has, and the one a field read needs: a record
    // below this one is somebody else's book, so its elements are not this
    // one's to answer with.
    const [book] = booksOn(
      `<de:contentRecord>${titled("Inner")}</de:contentRecord>`,
    );

    expect(book).toBeUndefined();
  });

  it("reads a manifest holding one record per book", () => {
    // The 2.0 layout: the whole file is the record. A reader expecting a list
    // above it reads nothing on every install since that version.
    const read = readDigitalEditionsLibrary(
      perBookManifest("<dc:title>A Constructed Title</dc:title>"),
    );

    expect(read.ok && read.library.books).toEqual([
      {
        record: 1,
        title: "A Constructed Title",
        authors: [],
        publisher: null,
        identifier: null,
      },
    ]);
  });

  it("reads a manifest holding the whole library", () => {
    // The 1.x layout, and the one reader answers both.
    expect(
      booksOn(titled("First"), titled("Second")).map((one) => one.title),
    ).toEqual(["First", "Second"]);
  });

  it("keeps every creator a record names, in the document's order", () => {
    const [book] = booksOn(
      record(`
        <dc:title>A Constructed Title</dc:title>
        <dc:creator>Second, Written</dc:creator>
        <dc:creator>First, Written</dc:creator>
      `),
    );

    expect(book!.authors).toEqual(["Second, Written", "First, Written"]);
  });

  it("leaves a surname first name exactly as the file writes it", () => {
    // Nothing here reorders or splits one. `pdf.ts` carries why: the separator
    // that would split a list is also how a single name is written surname
    // first, so a reader guessing at it files one person as two.
    const [book] = booksOn(
      record(`
        <dc:title>A Constructed Title</dc:title>
        <dc:creator>Surname, Given and Other, Another</dc:creator>
      `),
    );

    expect(book!.authors).toEqual(["Surname, Given and Other, Another"]);
  });

  it("numbers records from one and counts the ones it skipped", () => {
    // The number is the record's place in the catalogue and not its place in
    // `books`, which is what makes it usable as a key: a caller reading the
    // array index would give two different books the same one across two
    // catalogues that differ only in what they skipped.
    const books = booksOn(record(""), titled("Second"), titled("Third"));

    expect(books.map((one) => one.record)).toEqual([2, 3]);
  });

  it("reads elements carrying no prefix at all", () => {
    // Matched by local name, so a prefix is neither required nor read. The
    // reason is in the reader: the `de` prefix's namespace URI is not
    // published, so requiring one would mean inventing it.
    const read = readDigitalEditionsLibrary(
      "<library><contentRecord><title>Unprefixed</title></contentRecord></library>",
    );

    expect(read.ok && read.library.books.map((one) => one.title)).toEqual([
      "Unprefixed",
    ]);
  });

  it("has no publisher where the element is there and empty", () => {
    const [book] = booksOn(
      record(
        `<dc:title>A Constructed Title</dc:title><dc:publisher></dc:publisher>`,
      ),
    );

    expect(book!.publisher).toBeNull();
  });

  it("takes the first identifier where a record carries two", () => {
    // A record with two is a record this reader has no way to choose between,
    // so it takes the one the document put first rather than joining them into
    // a value that is neither.
    const [book] = booksOn(
      record(`
        <dc:title>A Constructed Title</dc:title>
        <dc:identifier>first</dc:identifier>
        <dc:identifier>second</dc:identifier>
      `),
    );

    expect(book!.identifier).toBe("first");
  });

  it("gives back an identifier that looks like an ISBN exactly as written", () => {
    // **The identifier is opaque and is never parsed.** No source says what
    // scheme this format writes, so a value shaped like an ISBN is still a
    // value of unknown scheme, and putting it through `parseIsbn` would file a
    // right looking number in a field every lookup treats as an ISBN. There is
    // no `isbn` on this record at all, which is what makes that unavailable
    // rather than merely undone.
    const [book] = booksOn(
      record(`
        <dc:title>A Constructed Title</dc:title>
        <dc:identifier>urn:isbn:9780306406157</dc:identifier>
      `),
    );

    expect(book!.identifier).toBe("urn:isbn:9780306406157");
    expect(book).not.toHaveProperty("isbn");
  });

  it("reads a record however deep in the document it sits", () => {
    // The element holding the records is not published, so the reader may not
    // name one, and a record two containers down is as ordinary as one at the
    // top.
    const read = readDigitalEditionsLibrary(
      `<de:manifest ${DE} ${DC}><de:shelves><de:shelf>${titled(
        "Buried",
      )}</de:shelf></de:shelves></de:manifest>`,
    );

    expect(read.ok && read.library.books.map((one) => one.title)).toEqual([
      "Buried",
    ]);
  });

  it("answers rather than throwing on a document nested deeply", () => {
    // **The reason the walk uses an explicit stack.** Nesting depth on a file
    // somebody else wrote is theirs to choose, and a recursive walk deep enough
    // throws a `RangeError` where this contract promises a value.
    //
    // **This arm does not observe the explicit stack.** A recursive walk
    // returns cleanly at this depth and at 10,000, and the depth where it throws
    // costs 281,633 ms to build a tree for, measured on builder. `has no
    // function in this reader that calls itself` is the arm that holds the rule;
    // what this one holds is that the walk works at a depth no other fixture
    // reaches.
    const depth = 2000;
    const deep =
      `<de:manifest ${DE} ${DC}>` +
      "<n>".repeat(depth) +
      titled("Deep") +
      "</n>".repeat(depth) +
      "</de:manifest>";

    const read = readDigitalEditionsLibrary(deep);

    expect(read.ok && read.library.books.map((one) => one.title)).toEqual([
      "Deep",
    ]);
  });
});

describe("what the catalogue does not say about who owns these books", () => {
  /**
   * The finding the whole ticket turns on.
   *
   * Adobe Digital Editions is a fulfilment client for library loans as much as
   * for purchases, and a catalogue record does not say which a book is: the
   * loan is a token that travels with the book file, inside the protection this
   * project does not open. The reader's own docstring carries the sources.
   *
   * So the claim this reader makes about ownership is none, and these two arms
   * are what stop a later edit making one quietly.
   */
  it("says ownership was never stated, on every catalogue it reads", () => {
    expect(libraryOn(FULL).ownershipStated).toBe(false);
    expect(libraryOn(titled("Bare")).ownershipStated).toBe(false);
  });

  it("carries no per book claim about ownership either", () => {
    // A borrowed title and a bought one are the same record here, so a field
    // saying which would be a guess on every row rather than on some of them.
    const [book] = booksOn(FULL);

    expect(Object.keys(book!).sort()).toEqual([
      "authors",
      "identifier",
      "publisher",
      "record",
      "title",
    ]);
  });
});

describe("a document this reader did not get everything out of", () => {
  it("names the fields no record could fill", () => {
    expect(libraryOn(titled("Bare")).missing).toEqual([
      "authors",
      "identifier",
      "publisher",
    ]);
  });

  it("counts a field one record filled as filled for the document", () => {
    // Occupancy over the document rather than over a record: a catalogue where
    // one book names its publisher is a catalogue this reader got publishers
    // out of.
    const library = libraryOn(
      titled("Bare"),
      record(`
        <dc:title>A Constructed Title</dc:title>
        <dc:publisher>An Imprint</dc:publisher>
      `),
    );

    expect(library.missing).toEqual(["authors", "identifier"]);
  });

  it("reads a field off a record it skipped", () => {
    // The record has no title and is skipped, and it still says the document
    // carried publishers. `missing` is what this reader could take out of the
    // document, which is not the same question as which books it kept.
    const library = libraryOn(
      record("<dc:publisher>An Imprint</dc:publisher>"),
    );

    expect(library).toMatchObject({
      books: [],
      skipped: 1,
      missing: ["authors", "identifier"],
    });
  });

  it("names them in one order however the reader listed them", () => {
    // **The arm the sort has, and what it rests on is asserted rather than
    // relied on.** Its whole power is that `FIELDS` is declared in the union's
    // order rather than the alphabet's: alphabetise that array and the sort
    // becomes unobservable here, silently and with every arm still green.
    const declared = declaredFields().filter((field) => field !== "authors");
    const sorted = [...declared].sort();
    expect(
      declared,
      "FIELDS is now in alphabetical order, so this arm no longer observes " +
        "the sort in readDigitalEditionsLibrary: put the declaration back " +
        "into the order DigitalEditionsField names, or pin the sort another way",
    ).not.toEqual(sorted);

    const library = libraryOn(
      record(`
        <dc:title>A Constructed Title</dc:title>
        <dc:creator>Surname, Given</dc:creator>
      `),
    );

    expect(library.missing).toEqual(sorted);
  });

  it("has nothing missing on a document carrying every element", () => {
    expect(libraryOn(FULL).missing).toEqual([]);
  });

  it("says this catalogue states no version of itself", () => {
    // It states none anywhere published, so the field is `null` rather than
    // absent: the shape is what every store reader answers in.
    expect(libraryOn(FULL).schemaVersion).toBeNull();
  });

  /**
   * The two spellings of the field list, held against each other.
   *
   * **Recomputed from the module's own source rather than restated here**, in
   * both directions: a member added to the type and not to the array would
   * never be reported missing, and one added to the array and not to the type
   * would not compile. Restating either list in this file would give the pair a
   * third home and this test would agree with whichever it was written from.
   */
  it("can report every field its own type names", () => {
    const union = /export type DigitalEditionsField =([^;]+);/.exec(
      readerSource,
    );
    expect(union).not.toBeNull();
    const named = [...union![1]!.matchAll(/"([^"]+)"/g)]
      .map((match) => match[1])
      .sort();

    expect([...declaredFields()].sort()).toEqual(named);
    // A pattern that matched nothing would satisfy the equality with two empty
    // lists, which is the evasion this second assertion closes.
    expect(named.length).toBeGreaterThan(0);
  });
});

describe("an unreadable store is one skipped source, never a broken import", () => {
  /**
   * The rule the whole surface turns on, asserted as a property rather than as
   * a list of cases.
   *
   * A member picks several sources at once and one of them is a file that is
   * not what they thought it was, or one the app has since changed. That has to
   * cost the one source and nothing else, so every outcome of this reader is a
   * value in a closed union and none of them is a throw. The documents below
   * are built to break it.
   *
   * **Each case carries the reading it should produce.** Asserting only that
   * the answer is one of the two shapes is a tautology: a case flipping from a
   * library to a failure would pass it silently.
   */
  const HOSTILE = [
    {
      what: "a file that is not XML at all",
      xml: "not xml, just words",
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "an empty file",
      xml: "",
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "XML that is somebody else's",
      xml: "<notes><note>remember the milk</note></notes>",
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "a manifest that is somebody else's",
      // The word is not the signature. Plenty of formats keep a manifest, and
      // what is this catalogue's own is a record inside one.
      xml: "<manifest><entry>something</entry></manifest>",
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "a document that declares its own entities",
      xml: `<!DOCTYPE de:manifest [<!ENTITY a "aa">]>${manifest(FULL)}`,
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "a document with an unclosed element",
      xml: `<de:manifest ${DE} ${DC}><de:contentRecord></de:manifest>`,
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "a document whose tags do not match",
      xml: "<manifest></other>",
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "a record spelled with a capital letter",
      // XML is case sensitive and this reader is too. Reading `ContentRecord`
      // as the same element would be reading HTML's rule into a format that
      // does not have it.
      xml: `<de:manifest ${DE} ${DC}><de:ContentRecord><dc:title>A Constructed Title</dc:title></de:ContentRecord></de:manifest>`,
      expected: { failure: "not-a-digital-editions-catalogue" },
    },
    {
      what: "a record holding nothing at all",
      xml: manifest(record("")),
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "a record whose elements are all empty",
      xml: manifest(
        record(
          "<dc:title></dc:title><dc:creator></dc:creator>" +
            "<dc:publisher></dc:publisher><dc:identifier></dc:identifier>",
        ),
      ),
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "a record whose title is only whitespace",
      xml: manifest(record("<dc:title>   </dc:title>")),
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "a record nested inside another record",
      // Counted once. A document wide search for the name would find both and
      // report two books, which would make the count the document's to choose
      // rather than the catalogue's to state.
      xml: manifest(
        `<de:contentRecord><dc:title>Outer</dc:title>${titled(
          "Inner",
        )}</de:contentRecord>`,
      ),
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a catalogue whose root is something else again",
      // The root element is not published, so the reader names none. A fixture
      // that only ever used one root would be asserting the invention rather
      // than the rule.
      xml: `<somethingElse ${DE} ${DC}>${FULL}</somethingElse>`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a declaration written with single quotes",
      // Legal XML, and the arm the environment docblock above names: under
      // happy-dom this document parses as HTML and reads as no catalogue.
      xml: `<?xml version='1.0' encoding='utf-8'?><de:manifest ${DE} ${DC}>${FULL}</de:manifest>`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a byte order mark before the root",
      xml: `﻿${manifest(FULL)}`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "a doctype that declares no entities",
      // The refusal is on a declaration, not on a doctype: a document naming
      // one and declaring nothing has nothing to expand.
      xml: `<!DOCTYPE de:manifest>${manifest(FULL)}`,
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "an element named like a path expression",
      xml: manifest(
        record(
          "<dc:title>A Constructed Title</dc:title>" +
            "<this-is-not-read>../../*[1]</this-is-not-read>",
        ),
      ),
      expected: { books: 1, skipped: 0 },
    },
  ];

  it.each(HOSTILE)(
    "answers rather than throwing for $what",
    ({ xml, expected }) => {
      const read = readDigitalEditionsLibrary(xml);

      expect(
        read.ok
          ? { books: read.library.books.length, skipped: read.library.skipped }
          : { failure: read.failure },
      ).toEqual(expected);
    },
  );

  it("refuses a declaration without building a parser", () => {
    // **The property is the ordering, which no return value can show.**
    // Expansion happens inside the parser, before a line of this reader runs, so
    // a refusal that came after the parse would answer exactly the same and
    // guard nothing. Measured by both critic seats independently: moving the
    // call below the parse left all 44 arms green.
    const parse = vi.spyOn(DOMParser.prototype, "parseFromString");

    expect(
      readDigitalEditionsLibrary(
        `<!DOCTYPE de:manifest [<!ENTITY a "aa">]>${manifest(FULL)}`,
      ),
    ).toEqual({ ok: false, failure: "not-a-digital-editions-catalogue" });
    expect(parse).not.toHaveBeenCalled();
    parse.mockRestore();
  });

  it("refuses a document past the bound without building a parser", () => {
    // The same property for the other refusal: parsing 16 MiB and then
    // declining it has already spent what the bound protects.
    const parse = vi.spyOn(DOMParser.prototype, "parseFromString");

    expect(
      readDigitalEditionsLibrary("x".repeat(MAX_CATALOGUE_BYTES + 1)),
    ).toEqual({ ok: false, failure: "too-large" });
    expect(parse).not.toHaveBeenCalled();
    parse.mockRestore();
  });

  it("has no function in this reader that calls itself", () => {
    // **The walk promises a value at any nesting depth, and recursion is the
    // only thing in it that would break that promise.** No document this suite
    // can afford separates the two: a recursive walk returns cleanly at depth
    // 10,000, and the depth where it throws costs 281,633 ms to build a tree
    // for, both measured on builder. So the rule is read off the source.
    //
    // **Three attempts, and each was walked past by the seat that did not write
    // it.** Reading the walk's own body missed a sibling that recursed. Reading
    // every declaration anchored at column zero missed a nested one, which is
    // the most natural way recursion comes back: 52 of 52 arms green with a
    // recursive inner helper. So the anchor is gone and the count below is what
    // makes a form this pattern cannot see go red rather than go quiet.
    //
    // **The matcher is the bare name and not the name with an open paren.** A
    // draft using the paren went green on a recursive `recordsIn`, because
    // `flatMap(recordsIn)` passes the function rather than calling it. Measured
    // on the mutation rather than by reading.
    //
    // **Two shapes are outside this.** Mutual recursion, which needs a call
    // graph, not available here: `typescript` is at 7.0.2, its package main
    // resolves to `lib/version.cjs`, and `typescript/unstable/ast` exposes a
    // scanner and node predicates with no parse entry point. And a shorthand
    // method in an object literal, `const helpers = { walk(n) { helpers.walk(n);
    // } }`, which carries no `function` keyword for the count and no `=>` for
    // `functionBindings`; measured by the design seat at zero bindings and a
    // keyword count of zero. This module holds no object of helpers, and that is
    // the condition under which this arm is complete.
    //
    // **A function bound to a name by `=` is inside it**, and the way in is
    // depth rather than spelling. A pattern matching `const walk = (at) =>` was
    // written first and went green on `const walk = (at: Element): void =>`,
    // because a return type sits between the parameters and the arrow; a generic
    // list or a destructured parameter sit there too. `functionBindings` never
    // looks at the signature.
    //
    // **Five signature shapes were run against this arm before it shipped**, on
    // a nested declaration and on a bound arrow: a destructured parameter, a
    // parameter typed with an object literal, a return type carrying a brace,
    // and the last two again as arrows. Each reddens this arm alone, by name.
    const code = withoutProse(readerSource);
    // **The scans below read brackets as depth, so a bracket sitting where they
    // cannot see it is code moves a body's end.** This counts each kind instead
    // of describing where one may hide, which is what decides every lexical
    // context at once.
    //
    // **A character class was the first three drafts and it is the wrong
    // shape.** It named braces, then braces and parentheses, then all three
    // kinds, and each round found a context the last had not reached: a string
    // holding `]>`, which ends a DTD internal subset and is a plausible future
    // edit here; then a regular expression literal and a template across lines,
    // which need a quote delimiter and a single line and so no class can reach.
    // Enumerating lexical contexts is the shape this repository's rule says to
    // replace rather than extend. The security seat's fix, taken whole.
    //
    // **Its own residual**: a literal holding a balanced pair in the wrong
    // order, `"}{"`, passes the count and could still move a scan. One shape
    // rather than two whole contexts.
    for (const [opener, closer] of [
      ["(", ")"],
      ["[", "]"],
      ["{", "}"],
    ]) {
      expect(
        [...code].filter((one) => one === opener).length,
        `the reader's ${opener} and ${closer} do not balance, so a bracket ` +
          `sits somewhere the scans below cannot read as code`,
      ).toBe([...code].filter((one) => one === closer).length);
    }

    const declarations = [
      ...code.matchAll(/(?:export )?(?:async )?function (\w+)\(/g),
    ];
    const named = declarations.map((one) => one[1]!);
    expect(named).toContain("recordsIn");
    expect(named).toContain("descendantsNamed");
    expect(named).toContain("within");

    // **Completeness, which is what the three assertions above cannot give.**
    // They pass whatever forms the pattern is blind to. Every `function` keyword
    // has to be one of the declarations found, so an expression form or a
    // spelling this pattern misses fails here rather than going quiet.
    expect(named.length, "a function this pattern cannot see").toBe(
      [...code.matchAll(/\bfunction\b/g)].length,
    );

    const named2 = declarations.map((one) => ({
      name: one[1]!,
      body: bodyOf(code, one.index + one[0].length - 1),
    }));
    for (const one of named2) {
      expect(one.body, `${one.name} has no body`).not.toBeNull();
    }

    // A function bound to a name by `=` carries no `function` keyword, so the
    // count above cannot see it. `functionBindings` reaches it by depth rather
    // than by the arrow's spelling.
    const bodies = [
      ...named2.map((one) => ({ name: one.name, body: one.body! })),
      ...functionBindings(code),
    ];
    for (const one of bodies) {
      expect(
        new RegExp(String.raw`\b` + one.name + String.raw`\b`).test(one.body),
        `${one.name} calls itself`,
      ).toBe(false);
    }
  });

  it("says a catalogue with no records in it is one it cannot identify", () => {
    // **There is no `empty` here and the absence is a fact about the format.**
    // `kobo.ts` and `kindle.ts` each have a signature that survives the library
    // being empty; this catalogue's root element is not published, so a
    // document with no record in it is a document with nothing to recognise.
    expect(readDigitalEditionsLibrary(manifest())).toEqual({
      ok: false,
      failure: "not-a-digital-editions-catalogue",
    });
  });

  it("counts a record nested inside another once, as the outer one", () => {
    // The count and the value both: a document wide search would report two
    // books, and a field read reaching into the inner record would give the
    // outer one the wrong title.
    const [book] = booksOn(
      `<de:contentRecord><dc:title>Outer</dc:title>${titled(
        "Inner",
      )}</de:contentRecord>`,
    );

    expect(book!.title).toBe("Outer");
  });

  it("keeps the count when a catalogue holds only records it refuses", () => {
    // Not the same sentence as a file this reader could not identify, and the
    // member is owed the difference: this one is their catalogue, and what is
    // in it has nothing to file a book under.
    expect(libraryOn(record(""), record(""))).toMatchObject({
      books: [],
      skipped: 2,
    });
  });

  it("reads a document whose record order is not the order it reports", () => {
    // Nothing here sorts, so the document's order is the answer's order and a
    // caller can rely on it.
    expect(
      booksOn(titled("Third"), titled("First"), titled("Second")).map(
        (one) => one.title,
      ),
    ).toEqual(["Third", "First", "Second"]);
  });
});

describe("the document this reader will parse is bounded", () => {
  it("refuses a document past the bound rather than parsing it", () => {
    // The string is one code unit past the count, which is the comparison the
    // reader makes. A document this size is not built here: what is asserted is
    // the refusal, and building 16 MiB of well formed XML to assert it would
    // cost the suite the memory the bound exists to protect.
    expect(
      readDigitalEditionsLibrary("x".repeat(MAX_CATALOGUE_BYTES + 1)),
    ).toEqual({ ok: false, failure: "too-large" });
  });

  it("reads a file a member picked, whatever it is called", async () => {
    // **The name is not read**, which on this store is the line rather than a
    // detail: the manifest is named for the protected book beside it, and this
    // reader has no use for a path to one. Two names, one answer.
    const named = async (name: string) =>
      readDigitalEditionsCatalogueFile(new File([manifest(FULL)], name));

    for (const name of ["manifest.xml", "Some Borrowed Book.epub.xml"]) {
      const read = await named(name);
      expect(read.ok && read.library.books.map((one) => one.title)).toEqual([
        "A Constructed Title",
      ]);
    }
  });

  it("refuses a file past the bound before reading a byte of it", async () => {
    // **The property is that `text` is never called**, which is the whole
    // reason the file entry point exists: decoding two gigabytes into a string
    // to then decline it has already spent the memory the bound protects. A
    // test asserting only the failure passes on a reader that reads the file
    // first.
    const file = new File([manifest(FULL)], "manifest.xml");
    Object.defineProperty(file, "size", { value: MAX_CATALOGUE_BYTES + 1 });
    const text = vi.spyOn(file, "text");

    expect(await readDigitalEditionsCatalogueFile(file)).toEqual({
      ok: false,
      failure: "too-large",
    });
    expect(text).not.toHaveBeenCalled();
  });
});
