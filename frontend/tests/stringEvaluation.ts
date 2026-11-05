/**
 * Every site in a script that would run a string as script under a content
 * security policy refusing `'unsafe-eval'`, read off the syntax tree.
 *
 * Two readers share it, which is why it is a module of its own: the engine
 * test in `lib/sqlite.test.ts`, which scans the sql.js build the app imports
 * before any build exists, and `scripts/check-build.ts`, which scans every
 * script the production build emits, since the policy covers all of them.
 */

import { parseAst } from "vite";

import {
  isNode,
  nodesIn,
  SCOPES,
  scopeBindings,
  walk,
  type Node,
} from "./sourceReader";

/** The names a script reaches the global object by. */
const GLOBAL_OBJECTS = new Set(["globalThis", "self", "window", "global"]);
/** What compiles the string it is called with. */
const COMPILERS = new Set(["eval", "Function"]);
/** What compiles its first argument when that is a string, not a function. */
const TIMERS = new Set(["setTimeout", "setInterval"]);
/**
 * What a member read straight off a compiler may not name. Each hands the
 * compiler on, or runs it with arguments the read cannot see:
 * `Function.call(null, s)`, and `eval.constructor`, which is `Function`.
 */
const RUNS_THE_HOLDER = new Set(["call", "apply", "bind", "constructor"]);

/** `node` with the wrapping that does not change what it reads taken off. */
function bare(node: Node): Node {
  if (
    node.type === "ChainExpression" ||
    node.type === "ParenthesizedExpression"
  )
    return isNode(node.expression) ? bare(node.expression) : node;
  if (node.type === "SequenceExpression") {
    const last = nodesIn(node.expressions).at(-1);
    return last === undefined ? node : bare(last);
  }
  return node;
}

/** The name a key reads, when it is written as a constant. */
function constantName(key: unknown, computed: unknown): string | null {
  if (!isNode(key)) return null;
  const read = bare(key);
  if (computed !== true)
    return read.type === "Identifier" && typeof read.name === "string"
      ? read.name
      : null;
  if (read.type === "Literal" && typeof read.value === "string")
    return read.value;
  if (
    read.type === "TemplateLiteral" &&
    nodesIn(read.expressions).length === 0
  ) {
    const cooked = (nodesIn(read.quasis)[0]?.value as { cooked?: unknown })
      ?.cooked;
    return typeof cooked === "string" ? cooked : null;
  }
  return null;
}

/** The name a member expression reads, when it is written as a constant. */
function memberName(member: Node): string | null {
  return constantName(member.property, member.computed);
}

/**
 * The global `value` names: a bare identifier, or a constant member of one
 * of `GLOBAL_OBJECTS`. Null for anything else, `x.Function` included.
 */
function globalName(value: unknown): string | null {
  if (!isNode(value)) return null;
  const node = bare(value);
  if (node.type === "Identifier")
    return typeof node.name === "string" ? node.name : null;
  if (node.type !== "MemberExpression") return null;
  const holder = globalName(node.object);
  return holder !== null && GLOBAL_OBJECTS.has(holder)
    ? memberName(node)
    : null;
}

function isString(value: unknown): boolean {
  if (!isNode(value)) return false;
  const node = bare(value);
  if (node.type === "Literal") return typeof node.value === "string";
  if (node.type === "TemplateLiteral") return true;
  return (
    node.type === "BinaryExpression" &&
    node.operator === "+" &&
    (isString(node.left) || isString(node.right))
  );
}

/** The timer a call, a construction or a tagged template hands a string. */
function timerRun(node: Node): string | null {
  const callee =
    node.type === "TaggedTemplateExpression" ? node.tag : node.callee;
  const name = globalName(callee);
  return name !== null &&
    TIMERS.has(name) &&
    isString(nodesIn(node.arguments)[0])
    ? name
    : null;
}

/** Each scope's names, once: the module's walk is the whole engine. */
const BOUND = new WeakMap<Node, ReadonlyMap<string, Node>>();

/**
 * The names `scope` binds for the code inside it, by `scopeBindings`, which
 * reads JavaScript and TypeScript alike. A shape it cannot read throws, so a
 * binding is never read as binding less than it does.
 */
function scopeBinds(scope: Node): ReadonlyMap<string, Node> {
  const known = BOUND.get(scope);
  if (known !== undefined) return known;
  const { names, unreadable } = scopeBindings(scope);
  if (unreadable.length > 0)
    throw new Error(`a binding this cannot read: ${unreadable.join(", ")}`);
  BOUND.set(scope, names);
  return names;
}

/** Whether an identifier is read as a name, rather than a key or a label. */
function isReference(node: Node, parent: Node | undefined): boolean {
  if (parent === undefined) return true;
  if (parent.type === "MemberExpression")
    return parent.object === node || parent.computed === true;
  if (
    parent.type === "Property" ||
    parent.type === "MethodDefinition" ||
    parent.type === "PropertyDefinition"
  )
    return parent.key !== node || parent.computed === true;
  return !(
    parent.type === "LabeledStatement" ||
    parent.type === "BreakStatement" ||
    parent.type === "ContinueStatement" ||
    parent.type === "MetaProperty" ||
    parent.type === "ExportSpecifier" ||
    parent.type === "ImportSpecifier"
  );
}

/**
 * Whether `held`, a compiler, only has properties taken off it that cannot
 * reach a compiler again, `ancestors[at]` being the first read: the first a
 * constant outside `RUNS_THE_HOLDER`, and every later one a constant other
 * than `constructor`, which on any function is `Function`. A computed name
 * that is not a constant could be either, so it refuses.
 */
function readsAPropertyOnly(
  held: Node,
  ancestors: readonly Node[],
  at: number,
): boolean {
  let first = true;
  for (let i = at; i >= 0; i--) {
    const step = ancestors[i]!;
    if (step.type === "ChainExpression" && step.expression === held) {
      held = step;
      continue;
    }
    if (step.type !== "MemberExpression" || step.object !== held) return true;
    const name = memberName(step);
    if (name === null || name === "constructor") return false;
    if (first && RUNS_THE_HOLDER.has(name)) return false;
    first = false;
    held = step;
  }
  return true;
}

/**
 * The compiler `node` reads where its value can still be run, if any.
 *
 * Refused: any read of the global `eval` or `Function`, as a bare name no
 * local binding shadows or as a constant member of a global object, except
 * as the operand of `typeof`, the right of `instanceof`, or the object of a
 * property read `readsAPropertyOnly` passes. Each of those yields a string,
 * a boolean or a property that is not the compiler, so the value cannot
 * travel on from there; anywhere else it can, which is how a call through an
 * alias, an argument or a destructuring got past a guard that read callees.
 */
function compilerRead(node: Node, ancestors: readonly Node[]): string | null {
  let name: string | null = null;
  if (node.type === "Identifier" && typeof node.name === "string") {
    const read = node.name;
    if (
      !COMPILERS.has(read) ||
      !isReference(node, ancestors.at(-1)) ||
      ancestors.some(
        (scope) => SCOPES.has(scope.type) && scopeBinds(scope).has(read),
      )
    )
      return null;
    name = read;
  } else if (node.type === "MemberExpression") {
    const read = globalName(node);
    if (read === null || !COMPILERS.has(read)) return null;
    name = read;
  } else return null;

  let at = ancestors.length - 1;
  let held: Node = node;
  while (at >= 0 && ancestors[at]!.type === "ChainExpression") {
    held = ancestors[at]!;
    at--;
  }
  const parent = ancestors[at];
  if (parent === undefined) return name;
  if (parent.type === "UnaryExpression" && parent.operator === "typeof")
    return null;
  if (
    parent.type === "BinaryExpression" &&
    parent.operator === "instanceof" &&
    parent.right === held
  )
    return null;
  if (parent.type === "MemberExpression" && parent.object === held)
    return readsAPropertyOnly(held, ancestors, at) ? null : name;
  return name;
}

/** The compiler a destructuring takes off whatever it destructures. */
function compilerTaken(node: Node, parent: Node | undefined): string | null {
  if (node.type !== "Property" || parent?.type !== "ObjectPattern") return null;
  const key = constantName(node.key, node.computed);
  return key !== null && COMPILERS.has(key) ? key : null;
}

/**
 * Every site in a script that would run a string as script under a policy
 * refusing `'unsafe-eval'`, by the compiler it reaches, read off the syntax
 * tree `parseAst` builds, so comments and strings are not code here.
 *
 * Matched: every read of the global `eval` or `Function` that `compilerRead`
 * refuses, a call or an alias or an argument alike, and a destructuring that
 * takes either by name; and `setTimeout` or `setInterval`, bare or a
 * constant member of a global object, handed a string first argument, which
 * the policy refuses just as it refuses `eval`.
 *
 * Not looked for, though each would need `'unsafe-eval'`. Over a whole
 * bundle every compile site is deliberate on its author's part, so what
 * accepts each gap is that a dependency would have to be written in that
 * shape. The build check refuses only what is matched above. A site in a
 * gap fails in the browser, which throws in the feature that reached it,
 * and nobody running the server learns of it, since the policy names no
 * `report-uri`. The gaps: `Function` reached through some other function's
 * `.constructor`, the AsyncFunction family included (`GeneratorFunction` and
 * `AsyncGeneratorFunction` too), which a template or REPL style library takes
 * as `Object.getPrototypeOf(async function () {}).constructor`, and a
 * destructuring off a passed read, since `readsAPropertyOnly` follows a member
 * chain and not a pattern, so `const {constructor: F} = Function.prototype`
 * passes; a timer reached through `call` or `apply`, as in
 * `setTimeout.call(window, "tick()")`, since timers have no counterpart of
 * `RUNS_THE_HOLDER` and `timerRun` matches only a callee naming the timer; a
 * parameter default reading a compiler its own function's body declares a
 * local of, which `scopeBindings` counts as shadowed although a default cannot
 * see the body's `var` or function names; in strict code, a compiler read
 * beside a block declaring a function of its name, since `scopeBindings`
 * hoists that function as sloppy code does, which is right for the engine,
 * whose builds carry no `"use strict"`; a member of a global object under a
 * computed name that is not a constant; a global object reached through
 * `this`, `top`, `parent`, `frames` or a local holding one; and a timer handed
 * a variable that holds a string, or a call such as `String(c)` that returns
 * one.
 *
 * Nor the policy's other refusals, because no grant of `'unsafe-eval'` would
 * admit them: inline script and `javascript:` URLs, which `script-src`
 * refuses by not listing `'unsafe-inline'`, and a script, an `import()` or a
 * worker from a `blob:` or `data:` URL, which it refuses by listing `'self'`
 * and no scheme (a worker falls back to it, as there is no `worker-src`).
 *
 * Refused although legitimate, because the walk reads presence and not reach:
 * a compiler compared, stored or handed on as a value, `x === Function`
 * included; a feature probe under `try` that falls back when the policy
 * refuses it, as zod 4's `allowsEval` does; and a branch the browser never
 * takes, such as `typeof window === "undefined" ? eval("require") : ...`. A
 * local named like a global object is read as that object, so `self.eval(x)`
 * on a local `self` reds loudly. When a dependency nobody can drop ships one
 * of these, raise it rather than loosening a rule here: every rule is shared
 * by the engine test and by every script the build emits, and an exception
 * scoped to one file and one site is a design decision not yet made.
 */
export function stringEvaluationSites(
  script: string,
): { compiler: string; at: number }[] {
  const sites: { compiler: string; at: number }[] = [];
  walk(parseAst(script), (node, ancestors) => {
    const compiler =
      compilerRead(node, ancestors) ??
      compilerTaken(node, ancestors.at(-1)) ??
      (node.type === "CallExpression" ||
      node.type === "NewExpression" ||
      node.type === "TaggedTemplateExpression"
        ? timerRun(node)
        : null);
    if (compiler !== null)
      sites.push({
        compiler,
        at: typeof node.start === "number" ? node.start : -1,
      });
  });
  return sites;
}

/** The compilers `script` reaches, each named once. */
export function stringEvaluation(script: string): string[] {
  return [...new Set(stringEvaluationSites(script).map((s) => s.compiler))];
}
