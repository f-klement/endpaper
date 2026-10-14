/**
 * What a parsed module says, read the one way every rule over the tree reads
 * it: the node, the walk over nodes, the names a binding pattern binds, and
 * where a relative path lands.
 *
 * **One reader, because the copies disagreed and each was right about its own
 * tests.** On `const { a: b }: Props = x;` the binding readers this replaced
 * answered `b`, `b` and `Props`, `a` and `b`, and all three. A type name taken
 * as a binding reads a type the module only mentions as a name it declares; a
 * key taken as one puts a name in a census that nothing declares. The path
 * resolvers disagreed on a `..` past their base, which one kept and three
 * dropped.
 *
 * **Not a test file, because a test file cannot be imported**: importing one
 * runs its suites again inside the importer. `sourceReader.test.ts` holds each
 * answer.
 */

/** A node of the tree `parseAst` returns: anything with a string `type`. */
export type Node = { type: string } & Record<string, unknown>;

export function isNode(value: unknown): value is Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** The nodes `value` holds, whether it is one node or a list of them. */
export function nodesIn(value: unknown): Node[] {
  if (Array.isArray(value))
    return (value as unknown[]).filter((one): one is Node => isNode(one));
  return isNode(value) ? [value] : [];
}

/** Every node `node` holds directly, by its own keys, in source order. */
export function childrenOf(node: Node): Node[] {
  return Object.keys(node).flatMap((key) => nodesIn(node[key]));
}

/**
 * What a visit tells the walk: nothing to descend as usual, `false` to leave
 * this node's children unvisited, or the values to descend into instead.
 */
export type Descent = void | false | readonly unknown[];

/**
 * Every node under `value`, depth first in source order, each visited before
 * what it holds and handed the chain of nodes above it, outermost first.
 *
 * **The chain is live**: it is the walk's own stack, so a visit that keeps it
 * copies it. A list is descended into and a value with no string `type` is
 * not, which is what keeps a `TemplateElement`'s `{ raw, cooked }` and a
 * literal's value out of the walk.
 */
export function walk(
  value: unknown,
  visit: (node: Node, ancestors: readonly Node[]) => Descent,
): void {
  const ancestors: Node[] = [];
  const descend = (held: unknown): void => {
    if (Array.isArray(held)) {
      for (const item of held as unknown[]) descend(item);
      return;
    }
    if (!isNode(held)) return;
    const next = visit(held, ancestors);
    if (next === false) return;
    ancestors.push(held);
    for (const child of next ?? Object.keys(held).map((key) => held[key]))
      descend(child);
    ancestors.pop();
  };
  descend(value);
}

/** Every node under `root`, each with the node holding it. */
export function parentsOf(root: Node): Map<Node, Node | null> {
  const parents = new Map<Node, Node | null>();
  walk(root, (node, ancestors) => {
    parents.set(node, ancestors.at(-1) ?? null);
  });
  return parents;
}

/** The identifiers a binding pattern binds, and the shapes it could not read. */
export interface Bound {
  readonly identifiers: Node[];
  readonly unreadable: string[];
}

/**
 * Every identifier a binding position binds, by the pattern grammar.
 *
 * **A key, a default value and a type annotation bind nothing.** In
 * `{ a: b = c }: T` the name bound is `b`: `a` is the property read, `c` an
 * expression and `T` a type. So this follows the grammar's binding positions
 * rather than collecting identifiers and subtracting the rest.
 *
 * **Do not descend into a computed key.** `{ [useTheHook]: renamed }` reads
 * `useTheHook`; collecting it as a binding took that hook out of a census
 * keyed by name, measured.
 *
 * **Closed, and a shape outside it is recorded rather than skipped.**
 * Skipping one is how a shadowing binding goes unseen.
 */
export function boundBy(pattern: unknown): Bound {
  const identifiers: Node[] = [];
  const unreadable: string[] = [];
  const read = (node: unknown): void => {
    if (!isNode(node)) return;
    if (node.type === "Identifier") identifiers.push(node);
    else if (node.type === "ObjectPattern")
      for (const one of nodesIn(node.properties)) read(one);
    else if (node.type === "ArrayPattern")
      for (const one of nodesIn(node.elements)) read(one);
    else if (node.type === "Property") read(node.value);
    else if (node.type === "AssignmentPattern") read(node.left);
    else if (node.type === "RestElement") read(node.argument);
    else if (node.type === "TSParameterProperty") read(node.parameter);
    else unreadable.push(node.type);
  };
  read(pattern);
  return { identifiers, unreadable };
}

/**
 * The names a binding position binds, throwing on a shape `boundBy` cannot
 * read, so a caller that has nowhere to report one fails rather than reading
 * a pattern as binding less than it does.
 */
export function namesBoundBy(pattern: unknown): string[] {
  const { identifiers, unreadable } = boundBy(pattern);
  if (unreadable.length > 0)
    throw new Error(`a binding this cannot read: ${unreadable.join(", ")}`);
  return identifiers.map((one) => String(one.name));
}

/**
 * `path`'s `.` and `..` segments resolved against `base`, given as segments.
 *
 * **A `..` past the start of `base` is kept**, so a path that leaves the space
 * it was resolved in says so. Dropping it, which three of the copies did, lands
 * `../../src/x.ts` from a directory one level down on `src/x.ts`: a path out
 * of the tree read as a path in it. A leading `/` means nothing here; a caller
 * whose paths have a root says where it is.
 */
export function resolvePath(base: readonly string[], path: string): string[] {
  const out = [...base];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === ".." && out.length > 0 && out.at(-1) !== "..") out.pop();
    else out.push(part);
  }
  return out;
}
