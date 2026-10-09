/**
 * One element tree arbitrary for every reader that hands a document to
 * `DOMParser`, and the renderer that turns a drawn tree into the string it
 * reads.
 *
 * **A tree, not a string.** `fc.string()` never draws a `<`, so it tests one
 * refusal per reader and calls it fuzzing. A tree drawn over a reader's own
 * element names reaches the walk behind the parse, and it shrinks by structure
 * and prints as a literal a named case can be written in, which is the rule
 * every other arbitrary in this tree keeps for a builder's spec.
 *
 * **Breakage no tree can express rides on top, as data**: a short list of raw
 * insertions at drawn positions, the string twin of a byte patch. That is
 * where a stray `<`, an undeclared entity reference and a declaration land.
 *
 * **Depth is bounded, and low, on purpose.** What a parse under this suite's
 * jsdom costs is nesting depth: `kindle.ts` records 16,000 levels spending 26
 * seconds in the parser. That is a known property of the test DOM, stated at
 * its own site and not bounded by any reader, so a generator reaching it
 * would report the environment rather than a reader.
 *
 * **What the text and comment arbitraries cannot draw, stated**: a `<` or a
 * `<!ENTITY` inside a comment or `CDATA` section. `xmlEntities.ts` refuses a
 * declaration there on purpose, so a property asserting a document is accepted
 * would report that documented over refusal as a wrongly refused book. A
 * declaration arrives only through an insertion, which a property asks for by
 * name.
 */

import fc from "fast-check";

import { ELEMENTS as DIGITAL_EDITIONS_ELEMENTS } from "../../src/lib/adobeDigitalEditions";
import { ELEMENTS as KINDLE_ELEMENTS } from "../../src/lib/kindle";
import { type Total } from "../property";

export interface XmlElement {
  readonly element: string;
  readonly attributes: readonly (readonly [string, string])[];
  readonly children: readonly XmlNode[];
}

export type XmlNode =
  | XmlElement
  | { readonly text: string }
  | { readonly comment: string }
  | { readonly cdata: string };

/** Raw text put into the rendered document at `at`, modulo its length. */
export interface Insertion {
  readonly at: number;
  readonly text: string;
}

export interface XmlDocument {
  /** The XML declaration: absent, double quoted, single quoted, or behind a BOM. */
  readonly declaration: "none" | "double" | "single" | "bom";
  readonly root: XmlElement;
  readonly insertions: readonly Insertion[];
  /**
   * The rendered length to pad to with a trailing comment, or `undefined`.
   * **Named rather than spelled**, for `zipFixtures.Zeroes`'s reason: a
   * document past a sixteen mebibyte cap prints as a number.
   */
  readonly padTo: number | undefined;
}

/** The names a reader looks for, which is where a drawn tree is aimed. */
export interface Vocabulary {
  /** Root element names, the reader's own first. */
  readonly roots: readonly string[];
  /** Element names below the root, prefixed ones among them. */
  readonly names: readonly string[];
  readonly attributes: readonly string[];
  /** Text values the reader reads meaning into: years, ISBNs, labels. */
  readonly texts: readonly string[];
  /**
   * A document the reader accepts, which a drawn one is mostly a mutation of.
   *
   * **What reaches a reader's walk rather than its first refusal.** A tree
   * drawn from names alone names a reader's whole required chain, root to
   * entry, on few of its draws, so most of what a property ran would be the
   * refusal at the root. Nodes drawn into this one at drawn places reach every
   * line behind that refusal, and its namespace declarations stand, which a
   * prefixed name needs or the parse refuses it.
   */
  readonly accepted: XmlElement;
}

/** An element, briefly: the vocabularies below are written in this. */
export function el(
  element: string,
  children: readonly (XmlNode | string)[] = [],
  attributes: readonly (readonly [string, string])[] = [],
): XmlElement {
  return {
    element,
    attributes,
    children: children.map((child) =>
      typeof child === "string" ? { text: child } : child,
    ),
  };
}

/** One node put into a tree below the element `path` walks to. */
export interface Graft {
  /** Child indices from the root, each modulo the element children there. */
  readonly path: readonly number[];
  readonly node: XmlNode;
}

/** The tree with each graft added as the last child where its path ends. */
export function graft(root: XmlElement, grafts: readonly Graft[]): XmlElement {
  let tree = root;
  for (const { path, node } of grafts) tree = graftOne(tree, path, node);
  return tree;
}

function graftOne(
  at: XmlElement,
  path: readonly number[],
  node: XmlNode,
): XmlElement {
  const elements = at.children.filter(
    (child): child is XmlElement => "element" in child,
  );
  const [first, ...rest] = path;
  if (first === undefined || elements.length === 0) {
    return { ...at, children: [...at.children, node] };
  }
  const target = elements[first % elements.length]!;
  return {
    ...at,
    children: at.children.map((child) =>
      child === target ? graftOne(target, rest, node) : child,
    ),
  };
}

/** A document declaring an entity, in the internal subset. */
export const DECLARATION = '<!DOCTYPE r [<!ENTITY e "x">]>';

/**
 * Raw text that no tree can express, each a different way a parse goes wrong.
 * The declarations below ride beside them, so every door's property also asks
 * whether one reaches the parser.
 */
const DAMAGE = [
  "<",
  "&",
  "&e;",
  "&#0;",
  "&#x110000;",
  "</x>",
  "]]>",
  "<?x?>",
  "\u0000",
  "￾",
  "<!DOCTYPE x>",
];

/** Declarations, each a different place one can sit. */
export const DECLARING = [
  DECLARATION,
  '<!ENTITY % p "x">',
  '<!-- <!ENTITY e "x"> -->',
  '<![CDATA[<!ENTITY e "x">]]>',
];

function escapeText(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttribute(value: string): string {
  return escapeText(value).replace(/"/g, "&quot;");
}

export function renderNode(node: XmlNode): string {
  if ("text" in node) return escapeText(node.text);
  if ("comment" in node) return `<!--${node.comment}-->`;
  if ("cdata" in node) return `<![CDATA[${node.cdata}]]>`;
  const attributes = node.attributes
    .map(([name, value]) => ` ${name}="${escapeAttribute(value)}"`)
    .join("");
  const inside = node.children.map(renderNode).join("");
  return `<${node.element}${attributes}>${inside}</${node.element}>`;
}

const PROLOG = {
  none: "",
  double: '<?xml version="1.0" encoding="UTF-8"?>\n',
  single: "<?xml version='1.0' encoding='UTF-8'?>\n",
  bom: '﻿<?xml version="1.0"?>\n',
} as const;

/**
 * Padding strings by the length a document pads to, built once each and cut.
 *
 * **Keyed on the target and never on the length a document needs**: the
 * second differs with every document drawn, so a memo keyed on it kept a new
 * sixteen mebibyte string per draw and took the suite pod past its memory
 * limit, measured. A cut of a kept string shares its characters.
 */
const PADDING = new Map<number, string>();

function padding(target: number, length: number): string {
  let known = PADDING.get(target);
  if (known === undefined) {
    known = "x".repeat(target);
    PADDING.set(target, known);
  }
  return known.slice(0, length);
}

/** The string a reader is handed for this document. */
export function render(document: XmlDocument): string {
  let out = PROLOG[document.declaration] + renderNode(document.root);
  for (const { at, text } of document.insertions) {
    const index = out.length === 0 ? 0 : at % (out.length + 1);
    out = out.slice(0, index) + text + out.slice(index);
  }
  if (document.padTo !== undefined && document.padTo > out.length + 7) {
    out += `<!--${padding(document.padTo, document.padTo - out.length - 7)}-->`;
  }
  return out;
}

/** Text with neither of the two characters that would end a comment or open markup. */
function quiet(arbitrary: fc.Arbitrary<string>): fc.Arbitrary<string> {
  return arbitrary.map((value) => value.replace(/[-<\]]/g, " "));
}

/**
 * How deep a drawn tree may nest. **Chosen, not measured**: deep enough that a
 * reader's walk below its root is reached, and nowhere near the depth the
 * module docstring says is the environment's cost.
 */
export const MAX_DEPTH = 5;

/**
 * A document over a reader's vocabulary: any tree, mostly under one of its
 * roots, with or without damage, and padded past `caps` where a reader has one.
 */
export function xmlDocument(
  vocabulary: Vocabulary,
  caps: readonly number[] = [],
): fc.Arbitrary<XmlDocument> {
  const name = fc.oneof(
    { arbitrary: fc.constantFrom(...vocabulary.names), weight: 6 },
    { arbitrary: fc.constantFrom("x", "a:b", "p"), weight: 1 },
  );
  const text = fc.oneof(
    { arbitrary: fc.constantFrom(...vocabulary.texts), weight: 3 },
    { arbitrary: fc.string({ maxLength: 12 }), weight: 2 },
    { arbitrary: fc.string({ maxLength: 12, unit: "binary" }), weight: 1 },
    { arbitrary: fc.constantFrom("", " ", "\n\t", "&", "<p>x</p>"), weight: 1 },
  );
  const attribute = fc.tuple(
    fc.oneof(
      { arbitrary: fc.constantFrom(...vocabulary.attributes), weight: 4 },
      { arbitrary: fc.constantFrom("xmlns", "xmlns:x", "id"), weight: 1 },
    ),
    text,
  );
  const { node } = fc.letrec<{ node: XmlNode; element: XmlElement }>((tie) => ({
    node: fc.oneof(
      { maxDepth: MAX_DEPTH, depthSize: "small" },
      { arbitrary: fc.record({ text }), weight: 3 },
      {
        arbitrary: fc.record({ comment: quiet(fc.string({ maxLength: 8 })) }),
        weight: 1,
      },
      {
        arbitrary: fc.record({ cdata: quiet(fc.string({ maxLength: 8 })) }),
        weight: 1,
      },
      { arbitrary: tie("element"), weight: 5 },
    ),
    element: fc.record({
      element: name,
      attributes: fc.array(attribute, { maxLength: 3 }),
      children: fc.array(tie("node"), { maxLength: 4 }),
    } satisfies Total<XmlElement>),
  }));
  const drawnRoot = fc.record({
    element: fc.oneof(
      { arbitrary: fc.constantFrom(...vocabulary.roots), weight: 8 },
      { arbitrary: name, weight: 1 },
    ),
    attributes: fc.array(attribute, { maxLength: 3 }),
    children: fc.array(node, { maxLength: 5 }),
  } satisfies Total<XmlElement>);
  const grafted = fc
    .array(
      fc.record({
        path: fc.array(fc.nat(), { maxLength: MAX_DEPTH }),
        node,
      } satisfies Total<Graft>),
      { maxLength: 4 },
    )
    .map((grafts) => graft(vocabulary.accepted, grafts));
  const root = fc.oneof(
    { arbitrary: grafted, weight: 3 },
    { arbitrary: drawnRoot, weight: 1 },
  );
  return fc.record({
    declaration: fc.constantFrom("none", "double", "single", "bom"),
    root,
    insertions: fc.oneof(
      { arbitrary: fc.constant([]), weight: 4 },
      {
        arbitrary: fc.array(
          fc.record({
            at: fc.nat(),
            // **A declaration a quarter of the time**, so a run from any seed
            // draws one into some document: one damage among thirteen, it
            // landed on a few runs in a hundred.
            text: fc.oneof(
              { arbitrary: fc.constantFrom(...DAMAGE), weight: 3 },
              { arbitrary: fc.constantFrom(...DECLARING), weight: 1 },
            ),
          } satisfies Total<Insertion>),
          { minLength: 1, maxLength: 2 },
        ),
        weight: 2,
      },
    ),
    padTo:
      caps.length === 0
        ? fc.constant(undefined)
        : fc.oneof(
            { arbitrary: fc.constant(undefined), weight: 7 },
            {
              arbitrary: fc.constantFrom(...caps.map((cap) => cap + 1)),
              weight: 1,
            },
          ),
  } satisfies Total<XmlDocument>);
}

/** Whether a drawn document carries a declaration, by insertion. */
export function declares(document: XmlDocument): boolean {
  return document.insertions.some(({ text }) => text.includes("<!ENTITY"));
}

// --- the readers' own vocabularies ------------------------------------------
//
// **Input to a generator, not a copy of a reader's rules.** A name missing
// here costs reach and nothing else, and every property using one carries a
// witness that the reader accepts what it draws, which is what reds when a
// vocabulary stops matching its reader.

const DC = "http://purl.org/dc/elements/1.1/";

/** An EPUB package document, `opf.ts`'s. */
export const OPF: Vocabulary = {
  roots: ["package"],
  names: [
    "metadata",
    "dc:title",
    "dc:creator",
    "dc:identifier",
    "dc:date",
    "dc:language",
    "dc:publisher",
    "dc:subject",
    "dc:description",
    "meta",
    "manifest",
    "spine",
  ],
  attributes: [
    "id",
    "refines",
    "property",
    "scheme",
    "opf:role",
    "opf:scheme",
    "opf:file-as",
    "name",
    "content",
  ],
  texts: [
    "Dune",
    "Frank Herbert",
    "9780441013593",
    "urn:isbn:9780441013593",
    "1965-08-01",
    "en",
    "aut",
    "#t",
    "calibre:series",
    "calibre:series_index",
    "belongs-to-collection",
    "group-position",
    "title-type",
    "subtitle",
  ],
  accepted: el(
    "package",
    [
      el("metadata", [
        el("dc:title", ["Dune"], [["id", "t"]]),
        el("dc:creator", ["Frank Herbert"]),
        el("dc:identifier", ["urn:isbn:9780441013593"], [["id", "pub-id"]]),
        el("dc:date", ["1965"]),
      ]),
    ],
    [
      ["xmlns", "http://www.idpf.org/2007/opf"],
      ["xmlns:dc", DC],
      ["xmlns:opf", "http://www.idpf.org/2007/opf"],
      ["version", "3.0"],
      ["unique-identifier", "pub-id"],
    ],
  ),
};

/** A comic's `ComicInfo.xml`, `cbz.ts`'s. */
export const COMIC_INFO: Vocabulary = {
  roots: ["ComicInfo"],
  names: [
    "Series",
    "Number",
    "Title",
    "Writer",
    "Genre",
    "GTIN",
    "Publisher",
    "Year",
    "Month",
    "Day",
    "LanguageISO",
    "Summary",
    "Volume",
  ],
  attributes: ["xmlns:xsi", "xsi:nil"],
  texts: [
    "Saga",
    "The Will",
    "1",
    "1.5",
    "-1",
    "Brian K. Vaughan, Fiona Staples",
    "9781534308374",
    "2012",
    "13",
    "en",
    "Science Fiction, Fantasy",
  ],
  accepted: el("ComicInfo", [
    el("Series", ["Saga"]),
    el("Number", ["1"]),
    el("Writer", ["Brian K. Vaughan"]),
    el("Year", ["2012"]),
  ]),
};

/** A FictionBook header, `fb2.ts`'s. */
export const FICTION_BOOK: Vocabulary = {
  roots: ["FictionBook"],
  names: [
    "description",
    "title-info",
    "src-title-info",
    "publish-info",
    "document-info",
    "author",
    "first-name",
    "middle-name",
    "last-name",
    "nickname",
    "book-title",
    "genre",
    "lang",
    "annotation",
    "sequence",
    "date",
    "year",
    "publisher",
    "isbn",
    "p",
  ],
  attributes: ["name", "number", "value", "xmlns:l"],
  texts: [
    "Онегин",
    "Александр",
    "Пушкин",
    "sf",
    "ru",
    "1833",
    "978-5-17-090332-2",
    "1",
    "x",
  ],
  accepted: el(
    "FictionBook",
    [
      el("description", [
        el("title-info", [
          el("genre", ["sf"]),
          el("author", [
            el("first-name", ["Александр"]),
            el("last-name", ["Пушкин"]),
          ]),
          el("book-title", ["Онегин"]),
          el("lang", ["ru"]),
        ]),
      ]),
    ],
    [["xmlns", "http://www.gribuser.ru/xml/fictionbook/2.0"]],
  ),
};

/** A Kindle for PC catalogue, `kindle.ts`'s, its names its own. */
export const KINDLE: Vocabulary = {
  roots: ["response"],
  names: KINDLE_ELEMENTS,
  attributes: ["xmlns", "id"],
  texts: [
    "B000FC1PJI",
    "EBOK",
    "PDOC",
    "Dune",
    "Frank Herbert",
    "2005-10-01T00:00:00+0000",
    "Ace",
  ],
  accepted: el("response", [
    el("add_update_list", [
      el("meta_data", [
        el("ASIN", ["B000FC1PJI"]),
        el("title", ["Dune"]),
        el("authors", [el("author", ["Frank Herbert"])]),
        el("cde_contenttype", ["EBOK"]),
      ]),
    ]),
  ]),
};

/** An Adobe Digital Editions catalogue, its names its own. */
export const DIGITAL_EDITIONS: Vocabulary = {
  roots: ["contentRecord", "manifest"],
  names: DIGITAL_EDITIONS_ELEMENTS,
  attributes: ["xmlns", "xmlns:dc"],
  texts: ["Dune", "Frank Herbert", "9780441013593", "urn:uuid:1", "Ace"],
  accepted: el("manifest", [
    el("contentRecord", [
      el("title", ["Dune"]),
      el("creator", ["Frank Herbert"]),
      el("identifier", ["9780441013593"]),
    ]),
  ]),
};
