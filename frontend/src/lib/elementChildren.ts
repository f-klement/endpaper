/**
 * Walking the element children of one node, and the only place that walk is
 * spelled.
 *
 * **A sibling walk and never a spread of `parent.children`**, which is the whole
 * reason this module exists rather than a convenience. `children` is a live
 * `HTMLCollection` and indexing one is not required to be constant time, so
 * spreading it costs whatever the host charges per index over a length that a
 * file the member supplied decides. Measured 2026-09-07 under jsdom by
 * `opf.ts`, which carried the first copy: 4 times the elements took 14.8 times
 * the wall clock, which is the quadratic signature, and the walk below took it
 * to linear. A browser may charge less; the point is that a reader of a
 * member's file does not get to depend on which.
 *
 * **Five readers had written that loop, six times between them, and four had
 * written this reason for it.** Two of the four reached for the measurement
 * above without having taken it, one of them by copying its figures, which is
 * the duplication this module ends: a number quoted in a second file stops
 * being re-derived and starts being copied. The fifth reader argues the walk
 * against a subtree search instead, which is a correctness reason and stays at
 * its own site. `tests/lib/elementChildren.test.ts` holds the rule that there
 * is one copy, as an exact set over the tree rather than as a count.
 *
 * **It names no format, no element and no book**, which is what lets it sit
 * here where every page can reach it. `bulkWrite.ts` states that rule for the
 * loop it owns and it is the same rule.
 *
 * **The name is matched on `localName` and therefore without a namespace.** A
 * caller for whom the namespace decides something says so at its own site: this
 * module concedes it once, here, so that a reader of a format that is stricter
 * than its documents are does not inherit the concession in silence.
 *
 * **What a caller keeps rather than passes.** The names a document may be asked
 * for are the caller's, and a caller that constrains them to a closed set keeps
 * that constraint by binding these doors to its own type at its own site rather
 * than by widening the parameter here. `kindle.ts` does exactly that and says
 * why at its binding. A type parameter here would not hold it: inference binds
 * such a parameter to whatever the call site passed, so every call site
 * satisfies it and it constrains nothing.
 */

/**
 * The element children of `parent`, in document order, one at a time.
 *
 * A generator rather than an array, so `firstNamed` below stops at its match
 * instead of building the whole list to read one member of it. Callers wanting
 * every child spread it.
 */
export function* elementChildren(parent: Element): Generator<Element> {
  for (
    let child = parent.firstElementChild;
    child !== null;
    child = child.nextElementSibling
  ) {
    yield child;
  }
}

/** Children of `parent` whose local name matches, in document order. */
export function childrenNamed(parent: Element, name: string): Element[] {
  const found: Element[] = [];
  for (const child of elementChildren(parent)) {
    if (child.localName === name) found.push(child);
  }
  return found;
}

/**
 * The first child of `parent` whose local name matches, or `null`.
 *
 * **Takes an absent parent**, because the readers that want this are descending
 * a document a member supplied and each step may find nothing. Making every
 * call site test first is how a chain of four lookups becomes four guards, and
 * one of them is the one that gets forgotten.
 */
export function firstNamed(
  parent: Element | null | undefined,
  name: string,
): Element | null {
  if (parent === null || parent === undefined) return null;
  for (const child of elementChildren(parent)) {
    if (child.localName === name) return child;
  }
  return null;
}
