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
import { declaresEntities } from "../../src/lib/xmlEntities";

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
    // then passed 151 of 151 against it. `MAX_OPF_BYTES` is as wide as any of
    // the five caps a caller applies before it parses, **tied with `epub.ts`'s
    // `MAX_PACKAGE_BYTES` at 4 MiB** and above 1 MiB for `ComicInfo.xml`,
    // 256 KiB for an FB2 header and 64 KiB for an EPUB container. It is the one
    // of the two that is exported, which is the whole of why it is this one. So
    // a prefix that misses a declaration here misses one no bound would have
    // stopped.
    const padded =
      "<!--" +
      "x".repeat(MAX_OPF_BYTES) +
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
