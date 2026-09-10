/**
 * Whether a document declares its own entities, which a reader refuses to parse.
 *
 * **The one attack a reader cannot bound after the fact.** Expansion happens
 * inside the engine's parser, before any code here sees a node, so a document
 * declaring nested entities is measured in what it expands to rather than in
 * what it weighs, and a caller's byte cap on the entry does not reach it.
 * Engines cap expansion themselves, but by how much is theirs to change and is
 * not something a reader can assert.
 *
 * Refusing costs nothing, and **each caller measured its own format rather than
 * inheriting a figure from here**: 0 of the 79 EPUBs `opf.ts` describes carry
 * `<!ENTITY` in either their container or their package document, and 0 of
 * `fb2.ts`'s 18 corpus files carry one. `cbz.ts` refuses on the specification
 * alone, having no corpus, and says so at its own site. None of these formats
 * has a use for a DTD internal subset.
 *
 * A plain substring rather than a regular expression over the prolog, which
 * would need to know where the prolog ends and would then be wrong about a
 * comment containing a tag. The exclusions, stated: an unescaped `<!ENTITY`
 * inside a `CDATA` section or inside a comment is refused as well. 0 of those
 * 79 files carry a `CDATA` section at all, and being told a file is not the
 * format it claimed is a smaller harm than an unbounded parse.
 *
 * **Its own module rather than the reader seam, which is what
 * `fileReaders.ts` refuses to be.** That file says what a reader is and what it
 * answers with, and four readers apply this rule while nothing in the contract
 * consults it: a `FileReading` is the same shape whether or not the bytes went
 * through a parser at all. Here it is also a rule with no dependency, so the
 * seam's runtime edge into a reader's dependency goes with it and every module
 * that names a reader's vocabulary takes it from the seam as a type.
 *
 * **It is one module for one rule and not a bag of XML helpers.** What would
 * join it is another refusal a caller cannot make after the parse; anything
 * that reads a document belongs to the format that spells it.
 *
 * A reader that hands a whole document to `DOMParser` as `application/xml`
 * calls this first, and four do.
 *
 * **Two parses do not, and both are deliberate.** `pdf.ts` cuts the packet
 * down to its root element, so what it parses has no prolog for a declaration
 * to sit in, and says so at its own site. `calibre.ts::plainText` parses
 * `text/html`, which has no internal subset to expand.
 */
export function declaresEntities(xml: string): boolean {
  return xml.includes("<!ENTITY");
}
