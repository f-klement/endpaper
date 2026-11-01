/**
 * The SQLite seam, against real databases.
 *
 * Every case here builds a database with the shipped engine and hands the bytes
 * back through the public door, so what is asserted is what a member's file
 * would do rather than what a stand in was told to answer.
 */

import { parseAst } from "vite";
import { describe, expect, it } from "vitest";

import * as sqlite from "../../src/lib/sqlite";
import {
  MAX_CELL_BYTES,
  MAX_DATABASE_BYTES,
  MAX_ROWS_PER_QUERY,
  openSqlite,
  openSqliteFile,
  type SqliteFailure,
  type SqliteRow,
} from "../../src/lib/sqlite";
import { holds, PROFILE, PROPERTY, witness } from "../property";
import {
  expectNamedOutcome,
  hostile,
  overrunBreach,
  type Door,
  type Hostile,
} from "./readerContract";
import {
  boundedDatabaseSpec,
  buildDatabase,
  databaseOf,
  engine,
  type DatabaseSpec,
  type DatabaseVocabulary,
} from "./sqliteFixtures";
// One module's text from the armed corpus, which refuses a name the tree does
// not hold. The lookup this replaced cast the first value of its own glob, so
// a rename handed the comparison below `undefined`.
import { sourceText } from "../sourceModules";
import {
  isNode,
  nodesIn,
  SCOPES,
  scopeBindings,
  walk,
  type Node,
} from "../sourceReader";

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
 * Not looked for, though each would need `'unsafe-eval'`, because each takes
 * intent rather than an accident of how a build is emitted: `Function`
 * reached through some other function's `.constructor`, a destructuring off a
 * passed read included, since `readsAPropertyOnly` follows a member chain and
 * not a pattern, so `const {constructor: F} = Function.prototype` passes; a
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
 * Refused although legitimate: a compiler compared, stored or handed on as
 * a value, `x === Function` included. A local named like a global object is
 * read as that object, so `self.eval(x)` on a local `self` reds loudly.
 */
function stringEvaluationSites(
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

function stringEvaluation(script: string): string[] {
  return [...new Set(stringEvaluationSites(script).map((s) => s.compiler))];
}

/**
 * Every script build sql.js ships, by path, each read only when asked for.
 *
 * The scan looks up the build `sqlite.ts` names here rather than importing one
 * by a second spelling, so the file scanned is the file imported. The key is
 * the specifier taken as a path, which skips the package's `exports` map, so
 * the scan asserts that map sends `./dist/*` to itself. Lazy, since the builds
 * together are megabytes and one is wanted.
 */
const ENGINE_BUILDS = import.meta.glob<string>(
  "../../node_modules/sql.js/dist/*.js",
  { query: "?raw", import: "default" },
);

/** sql.js's manifest, for the `exports` entry the lookup above relies on. */
const ENGINE_MANIFEST = Object.values(
  import.meta.glob<{ exports?: Record<string, unknown> }>(
    "../../node_modules/sql.js/package.json",
    { eager: true, import: "default" },
  ),
);

async function open(bytes: Uint8Array) {
  const reading = await openSqlite(bytes, engine);
  if (!reading.ok)
    throw new Error(`expected a database, got ${reading.failure}`);
  return reading.database;
}

describe("opening a database", () => {
  it("reads a table back by column name", async () => {
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (id INTEGER, title TEXT)",
        "INSERT INTO shelf VALUES (1, 'Dune'), (2, 'Solaris')",
      ),
    );

    expect(database.query("SELECT id, title FROM shelf ORDER BY id")).toEqual([
      { id: 1, title: "Dune" },
      { id: 2, title: "Solaris" },
    ]);
    database.close();
  });

  it("binds a parameter rather than pasting it in", async () => {
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (title TEXT)",
        "INSERT INTO shelf VALUES ('Dune'), (''' OR 1=1 --')",
      ),
    );

    expect(
      database.query("SELECT title FROM shelf WHERE title = ?", [
        "' OR 1=1 --",
      ]),
    ).toEqual([{ title: "' OR 1=1 --" }]);
    database.close();
  });

  it("refuses a file that is not a database", async () => {
    const reading = await openSqlite(
      new TextEncoder().encode("this is a text file"),
      engine,
    );

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
  });

  it("refuses an empty file rather than reading it as an empty library", async () => {
    // SQLite opens a zero byte file as a valid database with nothing in it, so
    // the layer above would report "that is not a Calibre library" about a file
    // that is not a database at all.
    const reading = await openSqlite(new Uint8Array(0), engine);

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
  });

  it("refuses a database whose pages no longer agree with each other", async () => {
    // What a copy taken while calibre-web was writing looks like: a header that
    // still parses over a page that has been overwritten with something else.
    // The whole reason the reference library's own journal mode was called out
    // on the ticket is that SQLite will answer from a file like this rather
    // than refuse it, so the refusal has to be asked for.
    const bytes = await databaseOf(
      "CREATE TABLE shelf (id INTEGER, title TEXT)",
      "INSERT INTO shelf VALUES (1, 'Dune')",
    );
    const pageSize = (bytes[16]! << 8) | bytes[17]!;
    bytes.fill(0x5a, pageSize, pageSize + 64);

    const reading = await openSqlite(bytes, engine);

    expect(reading).toEqual({ ok: false, failure: "damaged" });
  });

  it("refuses a file past the byte ceiling without reading it", async () => {
    // A `File` rather than the bytes: the point of the second door is that the
    // size is refused before an `ArrayBuffer` of it exists, so a file that
    // would not fit in memory never gets there. `arrayBuffer` throws if it is
    // ever called, which is what makes this an assertion rather than a hope.
    const file = {
      size: MAX_DATABASE_BYTES + 1,
      arrayBuffer: () => {
        throw new Error("the bytes were read after all");
      },
    } as unknown as File;

    expect(await openSqliteFile(file, engine)).toEqual({
      ok: false,
      failure: "too-large",
    });
  });

  it("closes a database it is about to refuse", async () => {
    // A file that opens and then fails a pragma is still holding all of itself
    // in WebAssembly memory, and the engine module is imported once and cached,
    // so a leak here accumulates across every refused pick for the life of the
    // tab. The loader is the seam: the engine is real everywhere else, and here
    // it is one that records what was closed.
    const closed: string[] = [];
    const failing = () =>
      Promise.resolve({
        Database: class {
          exec(): never {
            throw new Error("file is not a database");
          }
          export() {
            return new Uint8Array() as Uint8Array<ArrayBuffer>;
          }
          close() {
            closed.push("closed");
          }
        },
      });

    const reading = await openSqlite(new Uint8Array([1, 2, 3]), {
      engine: failing,
    });

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
    expect(closed).toEqual(["closed"]);
  });

  it("still names the refusal when closing the handle throws too", async () => {
    // The close runs on a handle that has already misbehaved. A throw there
    // would replace the closed failure union with an exception, and the member
    // holding a damaged copy would be told something generic went wrong.
    const engineThatCannotClose = () =>
      Promise.resolve({
        Database: class {
          exec(): never {
            throw new Error("database disk image is malformed");
          }
          export() {
            return new Uint8Array() as Uint8Array<ArrayBuffer>;
          }
          close(): never {
            throw new Error("close failed too");
          }
        },
      });

    const reading = await openSqlite(new Uint8Array([1, 2, 3]), {
      engine: engineThatCannotClose,
    });

    expect(reading).toEqual({ ok: false, failure: "damaged" });
  });

  it("says the engine is missing rather than throwing", async () => {
    // What a browser that refuses to compile WebAssembly looks like from here,
    // which is the shape a content security policy without 'wasm-unsafe-eval'
    // produces. It cannot be provoked in a test environment, so the loader is
    // the seam and this is the arm it exists for.
    const reading = await openSqlite(await databaseOf("CREATE TABLE a (b)"), {
      engine: () => Promise.reject(new Error("compilation refused")),
    });

    expect(reading).toEqual({ ok: false, failure: "no-engine" });
  });
});

describe("a database opened here is never written", () => {
  it("refuses an insert on its own connection", async () => {
    // `PRAGMA query_only` rather than a promise not to write one. The member's
    // own file is already out of reach, since a picked `File` is a snapshot;
    // this is the half that stops a bug here mutating the copy in memory and
    // reporting rows nobody's library contains.
    const bytes = await databaseOf(
      "CREATE TABLE shelf (title TEXT)",
      "INSERT INTO shelf VALUES ('Dune')",
    );
    const database = await open(bytes);

    database.query("INSERT INTO shelf VALUES ('Solaris')");

    expect(database.query("SELECT count(*) AS n FROM shelf")).toEqual([
      { n: 1 },
    ]);
    database.close();
  });
});

describe("what one statement may hand back", () => {
  it("drops a cell wider than the ceiling and keeps the row", async () => {
    // The row is the point. A hostile file putting a hundred megabytes in one
    // description must not cost the library it sits in, which is the same rule
    // `bookBounds.ts` applies one layer up.
    const wide = "a".repeat(MAX_CELL_BYTES + 1);
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (title TEXT, description TEXT)",
        `INSERT INTO shelf VALUES ('Dune', '${wide}')`,
      ),
    );

    expect(database.query("SELECT title, description FROM shelf")).toEqual([
      { title: "Dune", description: null },
    ]);
    database.close();
  });

  it("measures a cell in bytes, not in code units", async () => {
    // One over the ceiling, in bytes. Each is two UTF-16 units and four bytes,
    // so a ceiling read off `length` would admit twice what it meant to and
    // this row would come back whole.
    const emoji = "\u{1F4DA}".repeat(MAX_CELL_BYTES / 4 + 1);
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (title TEXT)",
        `INSERT INTO shelf VALUES ('${emoji}')`,
      ),
    );

    expect(database.query("SELECT title FROM shelf")).toEqual([
      { title: null },
    ]);
    database.close();
  });
});

describe("the engine the content security policy admits", () => {
  it("runs no string as script, in the build the module imports", async () => {
    // `'wasm-unsafe-eval'` is granted and `'unsafe-eval'` refused on the
    // strength of this. It reads the installed package, so a version bump
    // that keeps the property passes and one that breaks it fails here.
    // The build scanned is looked up from the specifier `sqlite.ts` imports,
    // so a move to another build scans that build. A bare `sql.js`, whose
    // file depends on the resolver's conditions, has no entry and throws. A
    // specifier assembled at run time is not read.
    expect(ENGINE_MANIFEST).toHaveLength(1);
    expect(ENGINE_MANIFEST[0]?.exports?.["./dist/*"]).toBe("./dist/*");
    const engines = [
      ...sourceText("lib/sqlite.ts").matchAll(
        /["'](sql\.js(?:\/[^"'?]*)?)["']/g,
      ),
    ].map((match) => match[1]);
    expect(engines).toHaveLength(1);
    const read = ENGINE_BUILDS[`../../node_modules/${engines[0]}`];
    if (read === undefined)
      throw new Error(`${engines[0]} is not a script build sql.js ships`);

    const engineText = await read();

    // An empty read passes every absence check below, so the read is checked
    // for the engine's own name. Every build holds that name, so this does not
    // tell builds apart: the lookup key above is what picks the file.
    expect(engineText).toContain("initSqlJs");
    expect(stringEvaluation(engineText)).toEqual([]);
  });

  it("finds a string run as script in an engine that holds one", () => {
    // The expected names are written out rather than read off the patterns,
    // so dropping a pattern to quiet a hit reds here too.
    const rows: [string, string[]][] = [
      ["eval(s)", ["eval"]],
      ["(0,eval)(s)", ["eval"]],
      ['self["eval"](s)', ["eval"]],
      ["eval?.(s)", ["eval"]],
      ["globalThis.eval(s)", ["eval"]],
      ['eval.call(null, "s")', ["eval"]],
      ['Reflect.apply(eval, null, ["s"])', ["eval"]],
      ['new Function("x","return x")', ["Function"]],
      ['Function("return this")()', ["Function"]],
      ['globalThis.Function("x")', ["Function"]],
      ['self["Function"]("x")', ["Function"]],
      ["self['Function']('x')", ["Function"]],
      ['self[`Function`]("x")', ["Function"]],
      ['globalThis [ "Function" ] ("x")', ["Function"]],
      ['self?.Function("x")', ["Function"]],
      ['self?.["Function"]("x")', ["Function"]],
      ['window.self.Function("x")', ["Function"]],
      ['Function\n("x")', ["Function"]],
      ['Function?.("x")', ["Function"]],
      ['globalThis.Function?.("x")', ["Function"]],
      ['Function/**/("x")', ["Function"]],
      ['Function /* c */ ("x")', ["Function"]],
      ['new (Function)("x")', ["Function"]],
      ['(0,Function)("x")', ["Function"]],
      ['\\u0046unction("x")', ["Function"]],
      ["Function`x`", ["Function"]],
      ['Function.call(null, "src")', ["Function"]],
      ['Function.apply(null, ["src"])', ["Function"]],
      ['Function.bind(null, "src")()', ["Function"]],
      ['Reflect.construct(Function, ["src"])', ["Function"]],
      ['setTimeout("tick()", 1)', ["setTimeout"]],
      ['window.setInterval("tick" + n, 1)', ["setInterval"]],
      ["setTimeout(tick, 1)", []],
      ["k.addFunction(1)", []],
      ["myFunction(1)", []],
      ["x.removeFunction(a)", []],
      ["RegisterExtensionFunctions(1)", []],
      ["$Function(1)", []],
      ["Function$(1)", []],
      ["isFunction(1)", []],
      ["x.Function(1)", []],
      ["a instanceof Function", []],
      ["typeof Function", []],
      ["Function.prototype.call(x)", []],
      ['"[object Function]"', []],
      ["// avoid eval(x)", []],
      ['"wasm-unsafe-eval"', []],
      // A compiler handed on as a value. Emscripten's embind ships exactly
      // the first, so a guard reading callees alone passed it.
      [
        "function newFunc(c, a) { return c.apply(o, a) } newFunc(Function, a).apply(null, b)",
        ["Function"],
      ],
      ["f(Function)", ["Function"]],
      ['const F = Function; F("x")', ["Function"]],
      ["var e = eval; e(s)", ["eval"]],
      ['const { Function: F } = globalThis; F("x")', ["Function"]],
      ["const { Function } = globalThis", ["Function"]],
      ['const { ["eval"]: e } = self', ["eval"]],
      ["const F = globalThis.Function", ["Function"]],
      ['const e = globalThis["eval"]', ["eval"]],
      ['[Function][0]("x")', ["Function"]],
      // Refused although nothing runs: the value could travel on from here.
      ["x === Function", ["Function"]],
      // A property that is the compiler again, or could be.
      ['Function.constructor("x")', ["Function"]],
      ['eval.constructor("x")', ["eval"]],
      ['Function.prototype.constructor("x")', ["Function"]],
      ["(Function?.prototype).constructor", ["Function"]],
      ["Function[k]", ["Function"]],
      ["Function.prototype[k]", ["Function"]],
      // A local in a sibling scope of each kind shadows nothing out here.
      ["{ let eval = 1 } eval(s)", ["eval"]],
      ['function g(Function) {} Function("x")', ["Function"]],
      ['(function () { var Function })(); Function("x")', ["Function"]],
      ['(() => { var Function })(); Function("x")', ["Function"]],
      ["try {} catch (eval) {} eval(s)", ["eval"]],
      ["for (let eval of a) {} eval(s)", ["eval"]],
      ["for (let eval in a) {} eval(s)", ["eval"]],
      ["for (let eval = 0; ; ) {} eval(s)", ["eval"]],
      ["switch (k) { case 1: let eval } eval(s)", ["eval"]],
      ["class C { static { var eval } x = eval }", ["eval"]],
      ["class C { m(eval) {} } eval(s)", ["eval"]],
      ["(function eval() {}); eval(s)", ["eval"]],
      ['(class Function {}); Function("x")', ["Function"]],
      // A local of the same name is not the global.
      ['function g(Function) { return Function("x") }', []],
      ["function g() { var eval = h; { eval(s) } }", []],
      ['let Function = h; Function("x")', []],
      ["try {} catch (eval) { eval(s) }", []],
      ["(function eval() { eval(s) })", []],
      ['function Function() {} Function("x")', []],
      ["function g() { { function eval() {} } eval(s) }", []],
      ['import { Function } from "m"; Function("x")', []],
      ["const { a: Function } = o; Function(1)", []],
      ['class Function {} new Function("x")', []],
      // A key, a label or a harmless property is not a read of the compiler.
      ["({ Function: 1, eval() {} })", []],
      ["class C { eval() {} Function = 1 }", []],
      ["eval: for (;;) break eval;", []],
      ["Function.name", []],
      ["typeof (Function)", []],
      ["Function.prototype.toString.call(f)", []],
    ];

    expect(rows.map(([script]) => stringEvaluation(script))).toEqual(
      rows.map(([, names]) => names),
    );
  });
});

describe("how many rows one statement may hand back", () => {
  it("stops at the ceiling rather than building every row", async () => {
    const over = MAX_ROWS_PER_QUERY + 1;
    const database = await open(
      await databaseOf(
        "CREATE TABLE wide (n INTEGER)",
        `INSERT INTO wide
           WITH RECURSIVE counter(n) AS (
             SELECT 1 UNION ALL SELECT n + 1 FROM counter WHERE n < ${over}
           )
           SELECT n FROM counter`,
      ),
    );

    expect(database.query("SELECT count(*) AS n FROM wide")).toEqual([
      { n: over },
    ]);
    expect(database.query("SELECT n FROM wide")).toHaveLength(
      MAX_ROWS_PER_QUERY,
    );
    database.close();
  });
});

describe("a question the file cannot answer", () => {
  it("is an empty result and never a throw", async () => {
    const database = await open(await databaseOf("CREATE TABLE shelf (title)"));

    expect(database.query("SELECT * FROM nothing_like_this")).toEqual([]);
    expect(database.query("SELECT title FROM shelf")).toEqual([]);
    database.close();
  });

  it("throws only for a query after close, which is a caller's bug", async () => {
    const database = await open(await databaseOf("CREATE TABLE shelf (title)"));
    database.close();

    expect(() => database.query("SELECT 1")).toThrow(
      "query on a closed database",
    );
  });
});

/** Names and values for a database nobody in particular wrote. */
const VOCABULARY: DatabaseVocabulary = {
  tables: ["shelf", "books", "sqlite_stat1"],
  columns: ["id", "title", "n", "rowid"],
  values: ["Dune", "", 1, 0, -1, 1.5, "\u{1F4DA}", new Uint8Array([0, 1])],
};

/** How many bytes a cell costs, in the unit `MAX_CELL_BYTES` is in. */
function cellBytes(cell: SqliteRow[string]): number {
  if (typeof cell === "string") return new TextEncoder().encode(cell).length;
  if (cell instanceof Uint8Array) return cell.byteLength;
  return 0;
}

/**
 * The seam as a door: open the picked file, read every table it was built
 * with and one it was not, and hold each answer to the bounds.
 *
 * **`sqlite.ts` catches everything**, so the contract's clause about a throw
 * cannot fail here: its open path answers every engine error as a failure, and
 * its query path answers `[]` for any throw. **Its bounds are this door's only
 * teeth**, and a green is not coverage of throwing: no answer longer than
 * `MAX_ROWS_PER_QUERY` and no cell wider than `MAX_CELL_BYTES`, which the
 * property draws past and its reaches ask it read; and the file's size refused
 * before a byte of it is read, which the meter's read ceiling holds and which
 * the named case and the positive control below reach, since the property
 * draws no file that large (`boundedDatabaseSpec` says why).
 */
const door: Door<DatabaseSpec, SqliteFailure | readonly number[]> = {
  module: sqlite,
  ceilings: () => ({ read: MAX_DATABASE_BYTES, reads: 1 }),
  build: buildDatabase,
  open: async (file, meter, spec) => {
    const reading = await openSqliteFile(file, engine);
    if (!reading.ok) return reading.failure;
    try {
      const names = [...spec.tables.map((table) => table.name), "absent"];
      return names.map((name) => {
        const rows = reading.database.query(
          `SELECT * FROM "${name.replace(/"/g, '""')}"`,
        );
        meter.require(
          rows.length <= MAX_ROWS_PER_QUERY,
          `a query handed back ${rows.length} rows against a ceiling of ${MAX_ROWS_PER_QUERY}`,
        );
        for (const row of rows) {
          for (const cell of Object.values(row)) {
            meter.require(
              cellBytes(cell) <= MAX_CELL_BYTES,
              `a cell of ${cellBytes(cell)} bytes was handed back against a ceiling of ${MAX_CELL_BYTES}`,
            );
          }
        }
        return rows.length;
      });
    } finally {
      reading.database.close();
    }
  },
};

/** Whether a drawn database carries no patch. */
const whole = ({ patches }: Hostile<DatabaseSpec>) => patches.length === 0;

/** Whether a drawn database holds a cell past the cell ceiling, as `as`. */
const cells = (spec: DatabaseSpec, as?: string) =>
  spec.tables.some((table) =>
    table.rows.some((row) =>
      row.some(
        (cell) =>
          typeof cell === "object" &&
          cell !== null &&
          "wide" in cell &&
          (as === undefined || cell.as === as) &&
          cell.wide > MAX_CELL_BYTES,
      ),
    ),
  );

describe("any database a member picks", () => {
  it(
    "is opened or refused by name, never read past its size and never answering past a bound",
    PROPERTY,
    async () => {
      // **Two reaches, asked of what the door answered**: a run must open a
      // database and query the long table to the row ceiling, and open one
      // holding a cell past the cell ceiling. A table or a cell the engine
      // refused first is drawn and reaches neither bound.
      expect(
        await holds(
          hostile(boundedDatabaseSpec(VOCABULARY)),
          async (input) => expectNamedOutcome(door, input),
          {
            "read a table to the row ceiling": (_, { outcome }) =>
              "answered" in outcome &&
              Array.isArray(outcome.answered) &&
              outcome.answered.includes(MAX_ROWS_PER_QUERY),
            "opened a database holding a cell past its ceiling": (
              { spec },
              { outcome },
            ) =>
              "answered" in outcome &&
              Array.isArray(outcome.answered) &&
              cells(spec),
          },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("is metered, so the read ceiling above is not held over nothing", async () => {
    const { outcome, counted } = await expectNamedOutcome(door, {
      spec: {
        tables: [
          {
            name: "shelf",
            columns: ["title"],
            rows: [["Dune"]],
            counted: undefined,
          },
        ],
        padTo: undefined,
      },
      patches: [],
    });

    expect(outcome).toEqual({ answered: [1, 0] });
    expect(counted.reads).toBe(1);
    expect(counted.read).toBeGreaterThan(0);
  });

  it("declares the read ceilings it is held to, so one deleted or loosened reds", async () => {
    // **The positive control**: a stub charging the meter as the file would,
    // through this door's own ceilings. The size is refused before any read in
    // the reader, so no property draw reaches the read ceiling, and nothing
    // but this would red were it deleted. A read is charged rather than made,
    // so the sixty four mebibyte bound costs no buffer of that size.
    expect(
      await overrunBreach(door, { ceiling: "read", bound: MAX_DATABASE_BYTES }),
    ).toContain(`bytes against a ceiling of ${MAX_DATABASE_BYTES}`);
    expect(await overrunBreach(door, { ceiling: "reads", bound: 1 })).toContain(
      "made read 2 against a ceiling of 1",
    );
  });

  it("draws every bound past itself, and a database holding rows", async () => {
    await witness(hostile(boundedDatabaseSpec(VOCABULARY)), {
      ...Object.fromEntries(
        ["text", "astral", "blob"].map((as) => [
          `holds a ${as} cell past its bound`,
          (input: Hostile<DatabaseSpec>) =>
            whole(input) && cells(input.spec, as),
        ]),
      ),
      "counts rows past the query's bound": (input) =>
        whole(input) &&
        input.spec.tables.some(
          (table) => (table.counted ?? 0) > MAX_ROWS_PER_QUERY,
        ),
      "holds rows": (input) =>
        whole(input) &&
        input.spec.padTo === undefined &&
        input.spec.tables.some((table) => table.rows.length > 0),
    });
  });
});
