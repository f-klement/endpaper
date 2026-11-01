/**
 * What a parsed module says, read the one way every rule over the tree reads
 * it: the node, the walk over nodes, the names a binding pattern binds, what
 * a scope binds, and where a relative path lands.
 *
 * **One reader, because the copies disagreed and each was right about its own
 * tests.** On `const { a: b }: Props = x;` the binding readers this replaced
 * answered `b`, `b` and `Props`, `a` and `b`, and all three. A type name taken
 * as a binding reads a type the module only mentions as a name it declares; a
 * key taken as one puts a name in a census that nothing declares. The path
 * resolvers disagreed on a `..` past their base, which one kept and three
 * dropped. The two scope readers disagreed on TypeScript and on a
 * declaration kind neither knew, which one recorded and one walked past.
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

/**
 * Every node that opens a scope a name can be bound in, JavaScript's and
 * TypeScript's both. A TypeScript kind never occurs in a JavaScript tree, so
 * one list serves the rules over the tree and the scan over the built engine.
 *
 * **The grammar's list rather than anybody's memory, and a kind missing
 * from it is a silent miss.** Its bindings land in the scope outside it.
 * The table rule in `houseRules.test.ts` then reads a pin and a generator as
 * reaching one declaration, so the group reads as held, and the engine scan
 * in `lib/sqlite.test.ts` reads a global compiler beside it as shadowed.
 * Both are false acceptances.
 *
 * **So nothing here is self correcting and a row per construct is what
 * makes it loud**, in both rule files. Over the table rule's rows, most
 * members turn a refusal into an acceptance when they go, the block
 * statement and the arrow the most of any; the enum body refuses something
 * legitimate instead and the program does both, because without it a
 * foreign import binds nowhere and the nothing it resolves to reads as the
 * runner; and a handful move no row. **The breakdown is deliberately not
 * written down**, because it is a property of the rows and it went stale in
 * the commit that added one: remove a member at a time and read it off,
 * which is how every figure here was taken.
 *
 * **The members that move no table row are measured rather than assumed.**
 * A shadow written in a function declaration, a static block, a class
 * declaration or a class expression is caught by the scope inside or
 * around it, driven each way; the two bodiless function kinds cannot hold
 * a generator at all.
 */
export const SCOPES: ReadonlySet<string> = new Set([
  "Program",
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
  "TSDeclareFunction",
  "TSEmptyBodyFunctionExpression",
  "BlockStatement",
  "StaticBlock",
  "TSModuleBlock",
  "ForStatement",
  "ForInStatement",
  "ForOfStatement",
  "CatchClause",
  "SwitchStatement",
  "ClassDeclaration",
  "ClassExpression",
  // An enum body is a namespace of its own, so its members bind inside it
  // and nowhere else. It is here rather than exempted at the reader below
  // because that is what it is: without it, every member of every enum is a
  // declaration the reader does not know, and one enum anywhere in the file
  // would refuse every name in it.
  "TSEnumBody",
]);

/** The three specifiers an import binds a local name through. */
const IMPORT_BINDINGS = new Set([
  "ImportSpecifier",
  "ImportDefaultSpecifier",
  "ImportNamespaceSpecifier",
]);

/**
 * The declaration kinds carrying a name that binds in the type space alone.
 *
 * **They are named because they are the exception to the refusal below**,
 * which records any other kind declaring a name the reader does not read,
 * rather than walking past it. Keyed on carrying an `id` that is an
 * identifier, which is what declaring a name looks like whatever the kind is
 * called. Censused that way over every module of `src` and `tests`, 689
 * files: these two are the only kinds that reach it, at 618 and 464
 * occurrences, so the exemption is what keeps the refusal off ordinary
 * TypeScript and nothing else is being waved through.
 */
const BINDS_IN_THE_TYPE_SPACE = new Set([
  "TSTypeAliasDeclaration",
  "TSInterfaceDeclaration",
]);

/** What one scope binds, and the binding shapes it could not read. */
export interface ScopeBindings {
  /** Each name, by the first identifier that binds it. */
  readonly names: Map<string, Node>;
  readonly unreadable: string[];
}

/**
 * What `scope`, a node of a kind in `SCOPES`, binds for the code inside it,
 * read off the constructs that bind rather than off the statements a scope
 * is allowed to hold.
 *
 * **Three sources, and the third is the one a block walk misses.** What the
 * scope node itself binds, which is its parameters, a catch's parameter and
 * an expression's own name; what is declared in its own region, found by
 * walking until the next scope so that a nested block keeps its own; and,
 * for a function body and the module body, what a `var` or a function
 * declaration hoists out of a nested block into.
 *
 * **A block's function declaration is hoisted as sloppy code hoists it**,
 * strict code included, where it stays in its block. That is right for the
 * built engine, which carries no `"use strict"`; `lib/sqlite.test.ts` names
 * what it costs there.
 *
 * **A pattern shape or a declaration kind it cannot read is recorded**, so a
 * caller can refuse rather than read a scope as binding less than it does.
 */
export function scopeBindings(scope: Node): ScopeBindings {
  const names = new Map<string, Node>();
  const unreadable: string[] = [];
  const add = (value: unknown): void => {
    if (!isNode(value) || value.type !== "Identifier") return;
    const name = value.name;
    if (typeof name === "string" && !names.has(name)) names.set(name, value);
  };
  const take = (pattern: unknown): void => {
    const bound = boundBy(pattern);
    unreadable.push(...bound.unreadable);
    for (const one of bound.identifiers) add(one);
  };

  for (const one of nodesIn(scope.params)) take(one);
  if (scope.type === "CatchClause") take(scope.param);
  if (scope.type === "FunctionExpression" || scope.type === "ClassExpression")
    add(scope.id);

  walk(childrenOf(scope), (child) => {
    if (SCOPES.has(child.type)) {
      // A nested declaration binds its own name out here even though its
      // body is somebody else's scope. **Written as the two exceptions
      // rather than as a list of declarations**, which is what it was: a
      // function expression and a class expression bind their own name
      // inward only, and every other scope node either carries a
      // declaration's name or carries no `id` at all, where this is a no
      // op. Naming the declarations instead left `declare function` out,
      // measured, and that is a shadow nobody sees.
      if (
        child.type !== "FunctionExpression" &&
        child.type !== "ClassExpression"
      )
        add(child.id);
      return false;
    }
    if (child.type === "VariableDeclarator") take(child.id);
    else if (IMPORT_BINDINGS.has(child.type)) add(child.local);
    else if (
      child.type === "TSEnumDeclaration" ||
      child.type === "TSModuleDeclaration" ||
      child.type === "TSImportEqualsDeclaration"
    )
      add(child.id);
    // **A declaration kind this reader does not know is recorded, not
    // walked past.** `boundBy` already does that for a pattern shape, and
    // for one round this one did not do it for a declaration kind, so
    // `import T = A.rows` was a shadow that went unseen and the group read
    // as held while driving another table. The key is carrying an `id`
    // that is an identifier, which is what declaring a name looks like
    // whatever the kind is called.
    else if (
      !BINDS_IN_THE_TYPE_SPACE.has(child.type) &&
      isNode(child.id) &&
      child.id.type === "Identifier"
    )
      unreadable.push(child.type);
  });

  if (scope.type === "Program" || Array.isArray(scope.params)) {
    walk(childrenOf(scope), (child) => {
      if (
        Array.isArray(child.params) ||
        child.type === "ClassDeclaration" ||
        child.type === "ClassExpression"
      ) {
        if (child.type === "FunctionDeclaration") add(child.id);
        return false;
      }
      if (child.type === "VariableDeclaration" && child.kind === "var")
        for (const one of nodesIn(child.declarations)) take(one.id);
    });
  }
  return { names, unreadable };
}
