/**
 * What a value has to be typed as to carry a member's book.
 *
 * `File` extends `Blob`, and both array views are what a reader hands back, so
 * naming only the first is the weaker of two spellings of one rule. Two guards
 * shipped one commit apart naming different sets, `File` in one and `File|Blob`
 * in the other, and the narrower one admitted a parameter taking a member's
 * book with no cast.
 *
 * **One home, so that holding this rule is using it.** The alternative was a
 * copy per guard and a sibling asserting the text appears in each, which is a
 * presence check: it passes while a guard narrows the copy it actually applies.
 * That was measured, with a `Blob` parameter admitted and every arm green.
 *
 * `tests/lib/fileName.test.ts` writes the pattern out rather than importing it,
 * and `tests/pages/ScanPage/types.test.ts` asserts that this exact text is
 * there. That one is a different rule over a different module and shares only
 * the literal.
 */
export const CARRIES_A_BOOK = /\b(?:File|Blob|ArrayBuffer|Uint8Array)\b/;
