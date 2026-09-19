/**
 * @vitest-environment node
 *
 * Touches no DOM. Building one costs more than this file spends running.
 */
/**
 * Tests for src/lib/bulkWrite.ts, and for the rule it exists to make true.
 *
 * Two halves. The first is the loop's own behaviour: what it does with a
 * refusal, what it reports after a stop, and the property no caller can assert
 * for itself, that a request is never in flight beside another. The second is
 * the tree wide rule, which lives here rather than in `houseRules.test.ts`
 * because it names this module: a guard that asserts something about one module
 * belongs beside it, where somebody editing the module will read it.
 */

import { describe, expect, it, vi } from "vitest";
import { parseAst } from "vite";

import { writeOneAtATime, type BulkProgress } from "../../src/lib/bulkWrite";

function items(count: number): string[] {
  return Array.from({ length: count }, (_, index) => `Book ${index + 1}`);
}

function collector() {
  const progress: BulkProgress[] = [];
  return { progress, onProgress: (one: BulkProgress) => progress.push(one) };
}

describe("writing a shelf one book at a time", () => {
  it("never has two requests in flight at once", async () => {
    // **Sequential rather than `Promise.all`**, and this is the assertion that
    // sees it: nine hundred concurrent requests against one SQLite writer is
    // not a faster import. A `Promise.all` passes every count based check here
    // and fails this one.
    let inFlight = 0;
    let most = 0;
    const seen = collector();

    const outcome = await writeOneAtATime(items(4), {
      post: async () => {
        inFlight += 1;
        most = Math.max(most, inFlight);
        await Promise.resolve();
        inFlight -= 1;
      },
      onProgress: seen.onProgress,
      stopped: () => false,
    });

    expect(most).toBe(1);
    expect(outcome.added).toBe(4);
    expect(outcome.failures).toEqual([]);
    expect(outcome.stopped).toBe(false);
    expect(seen.progress.at(-1)).toEqual({ done: 4, total: 4 });
  });

  it("keeps a refused item, rather than counting it", async () => {
    // The item and not a row built from it: what an import card lists and what
    // the scanner writes back into its queue are different things, and a count
    // is neither.
    const outcome = await writeOneAtATime(items(3), {
      post: async (item) => {
        if (item === "Book 2") throw { status: 409 };
      },
      onProgress: () => {},
      stopped: () => false,
    });

    expect(outcome.added).toBe(2);
    expect(outcome.failures).toEqual([
      { item: "Book 2", thrown: { status: 409 } },
    ]);
  });

  it("asks between every item whether it was stopped", async () => {
    // A function rather than a value, and this is why: the answer changes
    // while the loop runs, and a boolean read once says `false` for ever.
    const post = vi.fn(async () => {});
    let done = 0;

    const outcome = await writeOneAtATime(items(5), {
      post,
      onProgress: () => {
        done += 1;
      },
      stopped: () => done > 2,
    });

    expect(post.mock.calls.length).toBeLessThan(5);
    expect(outcome.stopped).toBe(true);
  });

  it("does not call a run that wrote everything stopped", async () => {
    // **A stop pressed while the last item is in flight.** The loop reads the
    // flag before an item and there is no item left, so every item was
    // written, every row a caller prunes by was reached, and there is nothing
    // short about the count. Reported as stopped, the queue's banner says what
    // it did not reach is still there, over an empty queue.
    let done = 0;
    const outcome = await writeOneAtATime(items(3), {
      post: async () => {},
      onProgress: () => {
        done += 1;
      },
      // True only once the last item has reported, which is after the last
      // read the loop makes.
      stopped: () => done > 3,
    });

    expect(outcome.added).toBe(3);
    expect(outcome.attempted).toHaveLength(3);
    expect(outcome.stopped).toBe(false);
  });

  it("reports the items it reached, which a stop makes fewer than it was given", async () => {
    // **What a caller prunes by.** A queue that clears what it offered clears
    // rows the run never attempted, which are exactly the ones a member
    // pressing stop is keeping.
    let done = 0;
    const outcome = await writeOneAtATime(items(5), {
      post: async () => {},
      onProgress: () => {
        done += 1;
      },
      stopped: () => done > 2,
    });

    expect(outcome.attempted).toEqual(["Book 1", "Book 2"]);
  });

  it("reports every item as reached when nothing stopped it", async () => {
    // The two sets are equal for a run that finished, which is why pruning by
    // the wrong one was invisible until there was a stop.
    const given = items(3);
    const outcome = await writeOneAtATime(given, {
      post: async () => {},
      onProgress: () => {},
      stopped: () => false,
    });

    expect(outcome.attempted).toEqual(given);
  });

  it("counts an item it reached and could not write as reached", async () => {
    // A failure is not a row the run left alone: the queue keeps it with its
    // reason on it, and pruning it back to untouched would lose that.
    const outcome = await writeOneAtATime(items(2), {
      post: async () => {
        throw new Error("the network went away");
      },
      onProgress: () => {},
      stopped: () => false,
    });

    expect(outcome.attempted).toEqual(["Book 1", "Book 2"]);
    expect(outcome.failures).toHaveLength(2);
  });

  it("does nothing at all for a run with nothing in it", async () => {
    const post = vi.fn(async () => {});

    const outcome = await writeOneAtATime([], {
      post,
      onProgress: () => {},
      stopped: () => false,
    });

    expect(post).not.toHaveBeenCalled();
    expect(outcome).toEqual({
      added: 0,
      failures: [],
      attempted: [],
      stopped: false,
    });
  });
});

/**
 * Every module the rule below covers.
 *
 * **Stated as an exclusion**: every `.ts` and `.tsx` under `src/` less
 * `src/api/generated/`, which is written by a generator and reviewed by
 * nobody. Not a list of the loops that are known about, which is what goes
 * stale the day a fourth page grows one.
 */
const SOURCES = import.meta.glob("../../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function entries(): [string, string][] {
  return Object.entries(SOURCES)
    .map(
      ([path, source]) =>
        [path.replace("../../src/", ""), source] as [string, string],
    )
    .filter(([path]) => !path.startsWith("api/generated/"));
}

const langOf = (path: string) => (path.endsWith(".tsx") ? "tsx" : "ts");

const LOOPS = new Set([
  "ForStatement",
  "ForOfStatement",
  "ForInStatement",
  "WhileStatement",
  "DoWhileStatement",
]);

const FUNCTIONS = new Set([
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);

interface Node {
  type: string;
  [key: string]: unknown;
}

const isNode = (value: unknown): value is Node =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as Node).type === "string";

/** Every name one parameter binds, destructuring included. */
function boundBy(pattern: unknown, out: string[] = []): string[] {
  if (!isNode(pattern)) return out;
  if (pattern.type === "Identifier") {
    out.push(pattern.name as string);
    return out;
  }
  for (const key of Object.keys(pattern)) {
    const child = pattern[key];
    if (Array.isArray(child)) child.forEach((one) => boundBy(one, out));
    else boundBy(child, out);
  }
  return out;
}

/**
 * The identifier an expression is reached through, or null where there is
 * none.
 *
 * `hooks` for `hooks`, `hooks` for `hooks.post`, and null for anything that is
 * computed, a call among them: a value a call produced is not the name it was
 * produced through.
 */
function rootOf(value: unknown): string | null {
  if (!isNode(value)) return null;
  if (value.type === "Identifier") return value.name as string;
  if (value.type !== "MemberExpression") return null;
  let object: unknown = value.object;
  while (isNode(object) && object.type === "MemberExpression")
    object = object.object;
  return isNode(object) && object.type === "Identifier"
    ? (object.name as string)
    : null;
}

/** The identifier a call is reached through, or null where it is an expression. */
function calleeRoot(call: Node): string | null {
  return rootOf(call.callee);
}

/** Whether a call writes, which for this client is one of two method names. */
function isMutation(value: unknown): boolean {
  if (!isNode(value) || value.type !== "CallExpression") return false;
  const callee = value.callee;
  if (!isNode(callee) || callee.type !== "MemberExpression") return false;
  const property = callee.property;
  return (
    isNode(property) &&
    property.type === "Identifier" &&
    /^mutate(Async)?$/.test(property.name as string)
  );
}

/**
 * Whether a function handed to this call is repeated by it.
 *
 * **The collection is the receiver, which is the whole of the test.**
 * `items.reduce(fn)`, `items.map(fn)` and `items.forEach(fn)` all call `fn`
 * once per item and are all a member call on the thing being walked. A bare
 * identifier callee is not: `useCallback(fn)`, `useMemo(fn)` and `useEffect(fn)`
 * hand React one function to hold, and treating those as repetition would
 * refuse every single write in this tree that is written as a callback.
 *
 * **It over-matches in one direction and that is said here rather than
 * discovered.** `promise.then(async () => await x.mutateAsync())` is a member
 * call taking a function and writes exactly once, so it would be reported. The
 * tree holds no such site: measured over the population below, every awaited
 * write is reached by `await`, not by a chained handler. If one is ever
 * written, the remedy is to await the promise, which is what every other write
 * here does.
 *
 * A method name list was the alternative and is the shape this repository's
 * notes name twice: `flatMap`, `every`, `some` and `for await` over an async
 * iterator are all repetition, and a list is what somebody has to think to add
 * to.
 */
function repeatsItsArgument(call: Node): boolean {
  return isNode(call.callee) && call.callee.type === "MemberExpression";
}

/**
 * One parse per file, because three readers walk the same tree.
 *
 * A pure function of its two arguments, so this is a cache and not state.
 */
const PARSES = new Map<string, Node>();

function parsed(source: string, lang: "ts" | "tsx"): Node {
  const key = `${lang}\u0000${source}`;
  const held = PARSES.get(key);
  if (held !== undefined) return held;
  const ast = parseAst(source, { lang }) as unknown as Node;
  PARSES.set(key, ast);
  return ast;
}

/** Whether anything inside this subtree satisfies a test. */
function somewhereInside(
  node: unknown,
  wanted: (one: Node) => boolean,
): boolean {
  if (Array.isArray(node))
    return node.some((one) => somewhereInside(one, wanted));
  if (!isNode(node)) return false;
  if (wanted(node)) return true;
  return Object.keys(node).some((key) =>
    key === "type" || key === "start" || key === "end"
      ? false
      : somewhereInside(node[key], wanted),
  );
}

/**
 * The names in one file that reach a write when they are called.
 *
 * **One hop, and it is the hop somebody actually writes.** A loop over a local
 * helper that writes is a bulk write in which no write is spelled inside the
 * loop: `const writeOne = (item) => client.scanAdd.mutateAsync(item)` and then
 * `for (const item of items) await writeOne(item)` passes a rule that reads the
 * loop body alone. Measured: it did, on this guard, before this reader existed.
 *
 * **Two hops and upwards are covered by nothing here, and neither assertion
 * below is the backstop for them.** A helper calling a helper, or one imported
 * from another module, is outside any rule that reads one file's syntax. The
 * other assertion sees a loop whose callee is the work its caller handed in,
 * directly or through one alias of it, which is a different question and not a
 * wider one: a module reaching its writes through a second local helper is
 * outside both. What stands there is a reviewer.
 *
 * It names the enclosing functions too, every hook in this tree among them,
 * which costs nothing: a rule only asks about a name it sees awaited inside a
 * repetition, and nothing awaits a hook in a loop.
 */
function writersIn(ast: Node): Set<string> {
  const names = new Set<string>();
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const one of value) walk(one);
      return;
    }
    if (!isNode(value)) return;
    if (
      value.type === "FunctionDeclaration" &&
      isNode(value.id) &&
      somewhereInside(value.body, isMutation)
    )
      names.add(value.id.name as string);
    if (
      value.type === "VariableDeclarator" &&
      isNode(value.id) &&
      value.id.type === "Identifier" &&
      isNode(value.init) &&
      FUNCTIONS.has(value.init.type) &&
      somewhereInside(value.init, isMutation)
    )
      names.add(value.id.name as string);
    for (const key of Object.keys(value)) {
      if (key === "type" || key === "start" || key === "end") continue;
      walk(value[key]);
    }
  };
  walk(ast);
  return names;
}

/**
 * Every place in one file where something is done more than once.
 *
 * Two shapes, because a loop is a statement in one and a callback in the
 * other, and a guard that knew only the first would be a guard against the
 * `for` keyword: `bodies.reduce(async (p, b) => { await p; await post(b) },
 * Promise.resolve())` is a sequential write of a whole shelf and holds no loop
 * statement at all.
 */
function offences(
  source: string,
  lang: "ts" | "tsx",
  found: (node: Node, repeated: boolean, params: Set<string>) => void,
): void {
  const ast = parsed(source, lang);
  const walk = (
    value: unknown,
    repeated: boolean,
    params: Set<string>,
  ): void => {
    if (Array.isArray(value)) {
      for (const one of value) walk(one, repeated, params);
      return;
    }
    if (!isNode(value)) return;

    const inside = repeated || LOOPS.has(value.type);
    const bound = FUNCTIONS.has(value.type)
      ? new Set([
          ...params,
          ...((value.params as unknown[]) ?? []).flatMap((one) => boundBy(one)),
        ])
      : params;

    // **A name taken off an injected value is that injected value.**
    // `const { post } = hooks` and `const write = hooks.post` are one line of
    // ordinary style, and without this the rule below reads "the callee is a
    // parameter binding" rather than "the work was handed in": both walked
    // past it, measured. Added to the enclosing function's own set rather than
    // to a copy, because the loop that uses the alias is the declaration's
    // sibling and not its child, and a set per function is what keeps that
    // scoped.
    //
    // **It matches a name rather than a binding**, so a later declaration
    // shadowing an injected name inside the same function is read as injected
    // too. That is the loud direction, it reports rather than admits, and it
    // fires on nothing in the tree: measured over the 261 files this rule
    // covers, adding this step moved neither result.
    if (
      value.type === "VariableDeclarator" &&
      rootOf(value.init) !== null &&
      bound.has(rootOf(value.init) as string)
    )
      for (const name of boundBy(value.id)) bound.add(name);

    found(value, inside, bound);

    for (const key of Object.keys(value)) {
      if (key === "type" || key === "start" || key === "end") continue;
      const child = value[key];
      if (value.type === "CallExpression" && key === "arguments") {
        const repeats = repeatsItsArgument(value);
        for (const argument of child as unknown[]) {
          const isFunction =
            isNode(argument) && FUNCTIONS.has(argument.type) && repeats;
          walk(argument, inside || isFunction, bound);
        }
        continue;
      }
      walk(child, inside, bound);
    }
  };
  walk(ast, false, new Set());
}

/**
 * Files where a write is awaited somewhere that runs more than once.
 *
 * The write is either spelled in the repetition or one call away from it, and
 * the second half is not optional: the first evasion tried against this guard
 * was a loop over a helper defined three lines above it.
 */
function repeatedWrites(source: string, lang: "ts" | "tsx"): number {
  const writers = writersIn(parsed(source, lang));
  let count = 0;
  offences(source, lang, (node, repeated) => {
    if (!repeated || node.type !== "AwaitExpression") return;
    if (isMutation(node.argument)) {
      count += 1;
      return;
    }
    const call = node.argument;
    if (!isNode(call) || call.type !== "CallExpression") return;
    const callee = call.callee;
    if (
      isNode(callee) &&
      callee.type === "Identifier" &&
      writers.has(callee.name as string)
    )
      count += 1;
  });
  return count;
}

/**
 * Files that walk work handed to them, which is what the shared loop is.
 *
 * The callee is the injected value itself or one alias of it. A name taken off
 * an alias of an alias is not, and neither is one imported from elsewhere; the
 * bound is stated at `writersIn` above rather than in two places.
 */
function loopsOverInjectedWork(source: string, lang: "ts" | "tsx"): number {
  let count = 0;
  offences(source, lang, (node, repeated, params) => {
    if (!repeated || node.type !== "AwaitExpression") return;
    const call = node.argument;
    if (!isNode(call) || call.type !== "CallExpression") return;
    const root = calleeRoot(call);
    if (root !== null && params.has(root)) count += 1;
  });
  return count;
}

/** Every awaited write in the tree, wherever it is. */
function awaitedWrites(source: string, lang: "ts" | "tsx"): number {
  let count = 0;
  offences(source, lang, (node) => {
    if (node.type === "AwaitExpression" && isMutation(node.argument))
      count += 1;
  });
  return count;
}

const SHARED_LOOP = "lib/bulkWrite.ts";

describe("a shelf is written in bulk in one place", () => {
  it("has no write repeated anywhere else in the tree", () => {
    // Three page folders wrote this loop, in two vocabularies, and the two
    // comments describing the same concurrency rule pointed at each other
    // across a wall neither crossed. One of the three had no stop, and nothing
    // said so.
    const offenders = entries()
      .filter(([path, source]) => repeatedWrites(source, langOf(path)) > 0)
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("walks work handed to it from exactly one module", () => {
    // The other half of the same rule, and the half that survives a rename: a
    // second module that takes a `post` and walks it, directly or through one
    // alias of it, is a second bulk write however its own writes are spelled,
    // and it is invisible to the rule above because a loop over an injected
    // callback names no write at all.
    const walkers = entries()
      .filter(
        ([path, source]) => loopsOverInjectedWork(source, langOf(path)) > 0,
      )
      .map(([path]) => path)
      .sort();

    expect(walkers).toEqual([SHARED_LOOP]);
  });

  it("is still watching a live idiom", () => {
    // A rule that matches nothing because the thing it matches has been
    // renamed passes for ever. This counts the writes it can see rather than
    // asserting a number: the two rules above are only as good as this being
    // more than zero.
    const writes = entries().reduce(
      (total, [path, source]) => total + awaitedWrites(source, langOf(path)),
      0,
    );

    expect(writes).toBeGreaterThan(0);
  });

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make everything above pass for ever.
    expect(entries().length).toBeGreaterThan(50);
  });
});

/**
 * The detector, against each shape in turn.
 *
 * **A guard nobody has attacked is not evidence**, and the attack that matters
 * is the one that is not a `for` statement. Each row is checked on its own, so
 * a row going quiet is reported as itself rather than hidden by the row beside
 * it.
 */
describe("what counts as a write done more than once", () => {
  const REPEATED: Record<string, string> = {
    "a for statement": `
      async function run(items: string[], client: Client) {
        for (const item of items) await client.scanAdd.mutateAsync(item);
      }`,
    "a plain for": `
      async function run(items: string[], client: Client) {
        for (let i = 0; i < items.length; i += 1)
          await client.scanAdd.mutateAsync(items[i]);
      }`,
    "a while": `
      async function run(items: string[], client: Client) {
        while (items.length > 0) await client.scanAdd.mutateAsync(items.pop());
      }`,
    "a do while": `
      async function run(items: string[], client: Client) {
        do { await client.scanAdd.mutateAsync(items.pop()); }
        while (items.length > 0);
      }`,
    "a for await": `
      async function run(items: AsyncIterable<string>, client: Client) {
        for await (const item of items) await client.scanAdd.mutateAsync(item);
      }`,
    "a reduce over resolved promises": `
      async function run(items: string[], client: Client) {
        await items.reduce(async (previous, item) => {
          await previous;
          await client.scanAdd.mutateAsync(item);
        }, Promise.resolve());
      }`,
    "a forEach": `
      function run(items: string[], client: Client) {
        items.forEach(async (item) => {
          await client.scanAdd.mutateAsync(item);
        });
      }`,
    "a map inside Promise.all": `
      async function run(items: string[], client: Client) {
        await Promise.all(
          items.map(async (item) => await client.scanAdd.mutateAsync(item)),
        );
      }`,
  };

  for (const [shape, source] of Object.entries(REPEATED)) {
    it(`reports ${shape}`, () => {
      expect(repeatedWrites(source, "ts")).toBeGreaterThan(0);
    });
  }

  it("reports a loop over a helper in the same file that writes", () => {
    // The evasion that walked past the first draft of this guard: no write is
    // spelled inside the loop, and the loop writes a book per item.
    const source = `
      async function run(items: string[], client: Client) {
        const writeOne = (item: string) => client.scanAdd.mutateAsync(item);
        for (const item of items) await writeOne(item);
      }`;
    expect(repeatedWrites(source, "ts")).toBeGreaterThan(0);
  });

  it("reports a declared helper that writes, called from a loop", () => {
    // The same hop with the helper spelled as a declaration rather than as a
    // binding, which is how this tree writes most of its functions.
    const source = `
      async function run(items: string[], client: Client) {
        async function writeOne(item: string) {
          await client.scanAdd.mutateAsync(item);
        }
        for (const item of items) await writeOne(item);
      }`;
    expect(repeatedWrites(source, "ts")).toBeGreaterThan(0);
  });

  it("says nothing about a loop over a helper that writes nothing", () => {
    // Every bulk read in this tree is this shape. A rule that could not tell
    // them apart would report a third of the file readers here.
    const source = `
      async function run(items: string[]) {
        const readOne = (item: string) => parse(item);
        for (const item of items) await readOne(item);
      }`;
    expect(repeatedWrites(source, "ts")).toBe(0);
  });

  it("says nothing about one write that happens once", () => {
    const source = `
      async function confirm(item: string, client: Client) {
        await client.scanAdd.mutateAsync(item);
      }`;
    expect(repeatedWrites(source, "ts")).toBe(0);
  });

  it("says nothing about a write inside a callback React holds", () => {
    // `useCallback` and its neighbours take one function and call it when
    // something happens, which is not repetition. Counting them would refuse
    // every write in this tree that is written as a callback, which is most of
    // them.
    const source = `
      function useThing(client: Client) {
        return useCallback(async (item: string) => {
          await client.scanAdd.mutateAsync(item);
        }, [client]);
      }`;
    expect(repeatedWrites(source, "ts")).toBe(0);
  });

  it("says nothing about the work a caller hands to the shared loop", () => {
    // The whole seam: one item, written by the caller's own `post`, repeated
    // by the module this file is about and by nothing else. Refusing this
    // would refuse the arrangement the rule exists to hold.
    const source = `
      async function addAll(items: string[], client: Client) {
        await writeOneAtATime(items, {
          post: async (item: string) => {
            await client.scanAdd.mutateAsync(item);
          },
          onProgress: () => {},
          stopped: () => false,
        });
      }`;
    expect(repeatedWrites(source, "ts")).toBe(0);
  });

  it("reports a loop over work its caller handed in", () => {
    const source = `
      async function walk(items: string[], hooks: Hooks) {
        for (const item of items) await hooks.post(item);
      }`;
    expect(loopsOverInjectedWork(source, "ts")).toBe(1);
  });

  it("reports a reduce over work its caller handed in", () => {
    // The evasion named in this ticket's brief, which holds no loop statement.
    const source = `
      async function walk(items: string[], post: (item: string) => Promise<void>) {
        await items.reduce(async (previous, item) => {
          await previous;
          await post(item);
        }, Promise.resolve());
      }`;
    expect(loopsOverInjectedWork(source, "ts")).toBe(1);
  });

  it("reports a loop over a name destructured off the work handed in", () => {
    // One line of ordinary style, and it walked past the first draft of this
    // rule: the callee is a local binding and the work is still the caller's.
    const source = `
      async function walk(items: string[], hooks: Hooks) {
        const { post, stopped } = hooks;
        for (const item of items) {
          if (stopped()) break;
          await post(item);
        }
      }`;
    expect(loopsOverInjectedWork(source, "ts")).toBe(1);
  });

  it("reports a loop over a name aliased off the work handed in", () => {
    const source = `
      async function walk(items: string[], hooks: Hooks) {
        const write = hooks.post;
        for (const item of items) await write(item);
      }`;
    expect(loopsOverInjectedWork(source, "ts")).toBe(1);
  });

  it("says nothing about a name aliased off something the module owns", () => {
    // The other side of the same rule: an alias is only injected work where
    // what it was taken from was.
    const source = `
      async function walk(items: string[]) {
        const write = readers.one;
        for (const item of items) await write(item);
      }`;
    expect(loopsOverInjectedWork(source, "ts")).toBe(0);
  });

  it("says nothing about a loop over work the module owns itself", () => {
    // Every bulk read in this tree is this shape, and none of them is a second
    // bulk write. A rule that counted them could not be a singleton.
    const source = `
      async function walk(items: string[]) {
        for (const item of items) await readOne(item);
      }`;
    expect(loopsOverInjectedWork(source, "ts")).toBe(0);
  });
});
