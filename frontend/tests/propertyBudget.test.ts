/**
 * @vitest-environment node
 *
 * Parses and samples; touches no DOM.
 */
/**
 * What a property in this suite may spend, and the one door it spends through.
 *
 * **The frontend half of `backend/tests/test_property_budget.py`, carrying its
 * lessons rather than its anecdote.** That guard is a floor: it counts what a
 * property executed and refuses fewer than fifty, because a profile lowered to
 * one example is a suite that passes in the usual time and tests nothing. Its
 * keyword list is the part not carried: fast-check 4.10 moved its time limits
 * into plugins, so a list of option names here would be one spelling short on
 * the day it was written. So the rule is a door instead. **Only
 * `tests/property.ts` may name a fast-check runner, global or plugin**, and
 * every property calls `holds` from there, which takes no options.
 *
 * | arm | catches |
 * |---|---|
 * | the one door, by parse | a test passing its own example count, seed, replay path or plugin; a global configured in one file that reaches every later file under `isolate: false`; any loader handed the package as a string; a package subpath import; an arbitrary drawing for itself, by any spelling of the name |
 * | the one door, beyond the trees | a runner kept in a module under `frontend/` that neither tree holds |
 * | no resolver alias | the package reached through the manifest's `imports` or the type checker's `paths` |
 * | the export list, by equality | a fast-check version adding a door the rule does not name |
 * | the profiles | a profile lowered under the floor |
 * | the replay agrees with the run | a hang's last `run <i>` line regenerating something other than what ran |
 * | no committed file pins the seed | the gate turned back into one sweep repeated forever, by a name, a dotenv file or bun's configuration |
 * | every property witnessed, under the runner's options, found by binding | an arbitrary weakened so it cannot draw the shape its property is about; a property run under an alias, off the runner's namespace, through a specifier the bundler resolves to the runner, or with options of its own |
 * | the samplers, derived and pinned, and every export of the runner | a drawing export of the runner other than `holds` and `witness` used outside this guard, by any spelling of the export; a witness standing alone |
 * | the reaches, pinned per file | a reach deleted |
 * | every door, by its import closure as Vite's server transform resolves it | a module a door reaches with no property; a property crediting a module its test does not import |
 *
 * **What the runner holds for itself, every property, every run**, and so is
 * not an arm here: a run that executed fewer examples than its profile, a run
 * that was interrupted, and a reach argument naming nothing all fail inside
 * `holds`.
 */

import {
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import fc from "fast-check";
import { createServer, parseAst, type ViteDevServer } from "vite";
import { afterAll, beforeAll, describe, expect, inject, it } from "vitest";

import {
  DRAWS_FOR_ITSELF,
  fastCheckExports,
  FLOOR,
  holds,
  lastSeed,
  namesTheGenerator,
  PROFILE,
  PROFILES,
  PROPERTY,
  REPLAY,
  replay,
  runnerExports,
  witness,
  writeAll,
} from "./property";
import { sourceEntries } from "./sourceModules";
import { testEntries, testEntriesBesides, testText } from "./testModules";
import { langOf } from "./withoutProse";

/** The runner, which is the one module the door rule exempts. */
const RUNNER = "./property.ts";

/**
 * The names that run a property, configure one, or plug into a run.
 *
 * **Classified against the export list pinned below**, so a version adding a
 * name reds there and somebody decides which side of this it belongs on.
 * `default` is here because `fc.default` is the namespace again, with every
 * runner on it. `Random` because it is what an arbitrary's own `generate`
 * draws from, which is a run of a property at a seed of its own: measured,
 * three examples drawn that way passed every arm here.
 */
const DOOR = [
  "afterEach",
  "assert",
  "asyncModelRun",
  "asyncProperty",
  "beforeEach",
  "check",
  "configureGlobal",
  "default",
  "ignoreEqualValues",
  "installGlobalPlugin",
  "interruptAfterTimeLimit",
  "modelRun",
  "pre",
  "property",
  "Random",
  "readConfigureGlobal",
  "resetConfigureGlobal",
  "sample",
  "scheduledModelRun",
  "skipEqualValues",
  "statistics",
  "timeout",
];

/** Every name fast-check 4.10.2 exports, as `Object.keys` sorts them. */
const EXPORTS = (
  "Arbitrary ExecutionStatus PreconditionFailure Random Stream Value " +
  "VerbosityLevel __commitHash __type __version afterEach anything array " +
  "assert asyncDefaultReportMessage asyncModelRun asyncProperty " +
  "asyncStringify asyncToStringMethod base64String beforeEach bigInt " +
  "bigInt64Array bigUint64Array boolean chainUntil check clone cloneIfNeeded " +
  "cloneMethod commands compareBooleanFunc compareFunc configureGlobal " +
  "constant constantFrom context createDepthIdentifier date default " +
  "defaultReportMessage dictionary domain double emailAddress entityGraph " +
  "falsy float float32Array float64Array func gen getDepthContextFor " +
  "hasAsyncToStringMethod hasCloneMethod hasToStringMethod hash " +
  "ignoreEqualValues infiniteStream installGlobalPlugin int16Array " +
  "int32Array int8Array integer interruptAfterTimeLimit ipV4 ipV4Extended " +
  "ipV6 json jsonValue letrec limitShrink lorem map mapToConstant " +
  "maxSafeInteger maxSafeNat memo mixedCase modelRun nat noBias noShrink " +
  "object oneof option pre property readConfigureGlobal record " +
  "resetConfigureGlobal sample scheduledModelRun scheduler schedulerFor set " +
  "shuffledSubarray skipEqualValues sparseArray statistics stream string " +
  "stringMatching stringify subarray timeout toStringMethod tuple " +
  "uint16Array uint32Array uint8Array uint8ClampedArray ulid unbiased " +
  "uniqueArray uuid webAuthority webFragments webPath webQueryParameters " +
  "webSegment webUrl"
).split(" ");

interface Node {
  readonly type: string;
  readonly [key: string]: unknown;
}

function isNode(value: unknown): value is Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** Every node, with the chain of nodes above it, outermost first. */
function walk(
  node: unknown,
  visit: (node: Node, ancestors: readonly Node[]) => void,
  ancestors: Node[] = [],
): void {
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit, ancestors);
    return;
  }
  if (!isNode(node)) return;
  visit(node, ancestors);
  ancestors.push(node);
  for (const [key, child] of Object.entries(node)) {
    if (key !== "type") walk(child, visit, ancestors);
  }
  ancestors.pop();
}

function isFastCheck(source: unknown): boolean {
  return (
    isNode(source) &&
    source.type === "Literal" &&
    typeof source.value === "string" &&
    namesTheGenerator(source.value)
  );
}

/** The text a string literal or a template with no expression holds. */
function stringOf(node: Node): string | null {
  if (node.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  if (
    node.type === "TemplateLiteral" &&
    (node.expressions as unknown[]).length === 0
  ) {
    const [quasi] = node.quasis as Node[];
    const value = quasi?.value as { cooked?: string } | undefined;
    return value?.cooked ?? null;
  }
  return null;
}

/**
 * Whether `node` is where an import or a `require` names its module, which
 * the arms above read for themselves.
 */
function isSpecifierOf(node: Node, parent: Node | undefined): boolean {
  if (parent === undefined) return false;
  switch (parent.type) {
    case "ImportDeclaration":
    case "ExportNamedDeclaration":
    case "ExportAllDeclaration":
    case "ImportExpression":
      return parent.source === node;
    case "CallExpression":
      return (
        nameOf(parent.callee) === "require" &&
        (parent.arguments as unknown[])[0] === node
      );
    default:
      return false;
  }
}

function nameOf(node: unknown): string | null {
  if (!isNode(node)) return null;
  if (node.type === "Identifier") return node.name as string;
  if (node.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  return null;
}

/**
 * Where an identifier is a name rather than a reference: a property after a
 * dot, an object key, a qualified name's right side, a specifier's foreign
 * name. Everything else is a reference to a binding.
 */
function isNameOnly(node: Node, parent: Node | undefined): boolean {
  if (parent === undefined) return false;
  switch (parent.type) {
    case "MemberExpression":
      return parent.property === node && parent.computed !== true;
    case "TSQualifiedName":
      return parent.right === node;
    case "Property":
    case "PropertyDefinition":
    case "MethodDefinition":
      return (
        parent.key === node &&
        parent.computed !== true &&
        parent.shorthand !== true
      );
    case "ImportSpecifier":
      return parent.imported === node;
    case "ExportSpecifier":
      return parent.exported === node;
    default:
      return false;
  }
}

/**
 * What one module does with fast-check, as findings.
 *
 * `uses X` for a door name reached as a member or a named import, and
 * `unread: ...` for every route a parse cannot follow to a name: a re-export,
 * a dynamic import, a `require`, a package subpath import, the namespace bound
 * anywhere but before a dot, the generator's random source imported at all,
 * an arbitrary's own `generate` named anywhere, and **the package named by any
 * string that is not an import's specifier**. That last is structural rather than a list of loaders: what
 * `vi.importActual`, a `createRequire`, an `import.meta.glob` and the next
 * loader have in common is that they are handed the package's name or its
 * path as a string, measured with the first three passing an arm per call
 * shape. **Refused rather than followed**, because the failure of each is the
 * right direction: a false refusal is loud at the line that made it, and an
 * analysis deciding a route is harmless is wrong in silence.
 *
 * **What it does not read, stated**: a name computed at run time, which no
 * parse can see and which the bundler's own guard in `vite.config.ts` does not
 * reach either, since it guards the build and not the suite; a resolver alias
 * outside the manifest, a `resolve.alias` in the configuration naming the
 * package as a string being refused by the walk beyond the trees and the type
 * checker's `paths` refused below by its key; a local of
 * another scope that shadows the namespace's name is refused as though it were
 * the namespace, and the package named in a type, `typeof import(...)`, is
 * refused as a string, both loud; and a dynamic import whose specifier is not
 * a string literal is refused whatever it names, because nothing can say what
 * it names.
 */
function findings(source: string, path: string): string[] {
  const ast = parseAst(source, { lang: langOf(path) }) as unknown as Node;
  const found: string[] = [];
  const namespaces = new Set<string>();

  walk(ast, (node, ancestors) => {
    const text = stringOf(node);
    if (
      text !== null &&
      namesTheGenerator(text) &&
      !isSpecifierOf(node, ancestors.at(-1))
    ) {
      found.push("unread: the generator named outside an import");
    }
    // **The name, wherever it stands**, and not one call shape: a computed
    // member, `Reflect.apply` over the member and a destructured key each
    // drew values with every arm green while this read a dotted call only,
    // measured, and the random source need not be fast-check's at all: any
    // object with a `nextInt` draws. A string spelling it whole counts, so a
    // key written as a literal is the same name.
    if (
      (node.type === "Identifier" && node.name === DRAWS_FOR_ITSELF) ||
      text === DRAWS_FOR_ITSELF
    ) {
      once(found, "unread: an arbitrary's own generate");
    }
    if (
      text !== null &&
      text.startsWith("#") &&
      isSpecifierOf(node, ancestors.at(-1))
    ) {
      // A package subpath import resolves through the manifest's `imports`,
      // so the name it loads is in no string here: measured, `#gen` mapped to
      // the package ran three examples at a seed of its own with every arm
      // green. The manifest is refused the key below; this is the module side.
      found.push("unread: a subpath import");
    }
    if (
      node.type === "ImportDeclaration" &&
      isFastCheck(node.source) &&
      /pure-rand/.test((node.source as Node).value as string)
    ) {
      found.push("unread: the generator's random source imported");
      return;
    }
    if (node.type === "ImportDeclaration" && isFastCheck(node.source)) {
      for (const specifier of node.specifiers as Node[]) {
        const local = nameOf(specifier.local)!;
        if (specifier.type !== "ImportSpecifier") {
          namespaces.add(local);
          continue;
        }
        const imported = nameOf(specifier.imported)!;
        const typeOnly =
          node.importKind === "type" || specifier.importKind === "type";
        if (imported === "default") namespaces.add(local);
        else if (!typeOnly && DOOR.includes(imported)) {
          found.push(`uses ${imported}`);
        }
      }
    }
    if (
      (node.type === "ExportNamedDeclaration" ||
        node.type === "ExportAllDeclaration") &&
      isFastCheck(node.source)
    ) {
      found.push("unread: a re-export of fast-check");
    }
    if (node.type === "ImportExpression") {
      const literal =
        isNode(node.source) &&
        node.source.type === "Literal" &&
        typeof node.source.value === "string";
      if (!literal) found.push("unread: a dynamic import of no literal");
      else if (isFastCheck(node.source)) {
        found.push("unread: a dynamic import of fast-check");
      }
    }
    if (
      node.type === "CallExpression" &&
      nameOf(node.callee) === "require" &&
      isFastCheck((node.arguments as unknown[])[0])
    ) {
      found.push("unread: a require of fast-check");
    }
  });

  if (namespaces.size === 0) return found;
  walk(ast, (node, ancestors) => {
    if (node.type !== "Identifier" || !namespaces.has(node.name as string)) {
      return;
    }
    const parent = ancestors.at(-1);
    if (isNameOnly(node, parent)) return;
    if (
      parent?.type === "ImportDefaultSpecifier" ||
      parent?.type === "ImportNamespaceSpecifier" ||
      (parent?.type === "ImportSpecifier" && parent.local === node)
    ) {
      return;
    }
    const member =
      parent?.type === "MemberExpression" &&
      parent.object === node &&
      parent.computed !== true
        ? nameOf(parent.property)
        : parent?.type === "TSQualifiedName" && parent.left === node
          ? nameOf(parent.right)
          : null;
    if (member === null) {
      found.push(`unread: ${node.name as string} reached other than by a dot`);
    } else if (DOOR.includes(member)) {
      found.push(`uses ${member}`);
    }
  });
  return found;
}

/** Push `finding` once: a name can stand at several nodes of one shape. */
function once(found: string[], finding: string): void {
  if (!found.includes(finding)) found.push(finding);
}

/** A list in order, so findings compare whatever order they came in. */
function ordered(list: readonly string[]): string[] {
  const out = [...list];
  out.sort();
  return out;
}

/** `frontend/`, where the walk below starts. */
const FRONTEND = fileURLToPath(new URL("..", import.meta.url));

/**
 * The two trees other rules walk, and what is never a module of this
 * package. **Stated as an exclusion and not an inclusion**, because a runner
 * written under a directory nobody listed is the case: measured, a property
 * run by a helper under `frontend/scripts/` passed every arm here.
 */
const NOT_BEYOND = new Set(["src", "tests", "node_modules", "dist"]);

/** A module's extension, by which a file beyond the trees is read. */
const MODULE = /\.(?:[cm]?[jt]s|[jt]sx)$/;

/**
 * Every module under `frontend/` outside `src/` and `tests/`, by its path
 * there: what a test can import that neither the house rule nor the walk of
 * the test tree reads.
 */
function beyondTheTrees(): [string, string][] {
  const out: [string, string][] = [];
  const visit = (relative: string): void => {
    for (const entry of readdirSync(`${FRONTEND}${relative}`, {
      withFileTypes: true,
    })) {
      const path = `${relative}${entry.name}`;
      if (entry.name.startsWith(".")) continue;
      if (entry.isDirectory()) {
        if (relative === "" && NOT_BEYOND.has(entry.name)) continue;
        if (entry.name === "node_modules") continue;
        visit(`${path}/`);
      } else if (MODULE.test(entry.name)) {
        out.push([path, readFileSync(`${FRONTEND}${path}`, "utf8")]);
      }
    }
  };
  visit("");
  out.sort(([a], [b]) => a.localeCompare(b));
  return out;
}

describe("a property runs through one door", () => {
  it("is reached by no test module but the runner", () => {
    const offenders = testEntriesBesides(RUNNER)
      .map(([path, source]) => [path, findings(source, path)] as const)
      .filter(([, found]) => found.length > 0);

    expect(offenders).toEqual([]);
  });

  it("is reached by no module beyond the two trees either", () => {
    // **A test imports from anywhere it likes**, so a runner kept outside
    // `tests/` is a runner the arm above never reads.
    const offenders = beyondTheTrees()
      .map(([path, source]) => [path, findings(source, path)] as const)
      .filter(([, found]) => found.length > 0);

    expect(offenders).toEqual([]);
  });

  it("is reached through no resolver alias", () => {
    // **A name a resolver maps is in no string here**: measured, `#gen`
    // mapped to the package in the manifest's `imports` ran a property at a
    // seed of its own with every arm green. The type checker's `paths` is the
    // same question for the next resolver that reads it. Refused by key,
    // loud, whatever they would map.
    const manifest = JSON.parse(outside("package.json")) as Record<
      string,
      unknown
    >;
    expect(Object.keys(manifest)).not.toContain("imports");
    expect(outside("tsconfig.json")).not.toMatch(/"paths"\s*:/);
    // Not vacuous: the manifest read is the one whose scripts start a run.
    expect(Object.keys(manifest)).toContain("scripts");
  });

  it("reads the modules beyond the two trees, so the rule above is not vacuous", () => {
    // Containment, not equality: a new script is not a reason to edit this,
    // and a walk that stopped descending loses one of these by name.
    expect(beyondTheTrees().map(([path]) => path)).toEqual(
      expect.arrayContaining([
        "orval.config.ts",
        "public/sw-cleanup.js",
        "scripts/check-build.ts",
        "types/build-env.d.ts",
        "vite.config.ts",
      ]),
    );
  });

  it("reads the runner's own use of the door, so the rule above is not vacuous", () => {
    // **Equality, and the runner is the subject because it is the one module
    // that must use the door.** A reader that stopped reading reports nothing,
    // which the arm above would take for a clean tree.
    const found = findings(testText(RUNNER), RUNNER);
    found.sort();
    expect(found).toEqual([
      // The name the rule below refuses, held here so the guard can say it.
      "unread: an arbitrary's own generate",
      "unread: fastCheck reached other than by a dot",
      "uses asyncProperty",
      "uses check",
      "uses readConfigureGlobal",
      // Twice: `replay` and `witness` each sample.
      "uses sample",
      "uses sample",
    ]);
  });

  it("reports every shape it exists for, and not the ones it does not", () => {
    const rows: [string, string[]][] = [
      [`import fc from "fast-check"; fc.assert(p);`, ["uses assert"]],
      [`import * as f from "fast-check"; await f.check(p);`, ["uses check"]],
      [`import { sample } from "fast-check";`, ["uses sample"]],
      [`import { check as c } from "fast-check";`, ["uses check"]],
      [
        `import { default as f } from "fast-check"; f.timeout(1);`,
        ["uses timeout"],
      ],
      [`import fc from "fast-check"; fc.default.check(p);`, ["uses default"]],
      [
        `import fc from "fast-check"; fc.installGlobalPlugin(fc.timeout(1));`,
        ["uses installGlobalPlugin", "uses timeout"],
      ],
      [
        `import fc from "fast-check"; const g = fc;`,
        ["unread: fc reached other than by a dot"],
      ],
      [
        `import fc from "fast-check"; fc["check"](p);`,
        ["unread: fc reached other than by a dot"],
      ],
      [
        `export { check } from "fast-check";`,
        ["unread: a re-export of fast-check"],
      ],
      [`export * from "fast-check";`, ["unread: a re-export of fast-check"]],
      [
        `await import("fast-check");`,
        ["unread: a dynamic import of fast-check"],
      ],
      [`await import(name);`, ["unread: a dynamic import of no literal"]],
      [`require("fast-check");`, ["unread: a require of fast-check"]],
      [`import { check } from "@fast-check/vitest";`, ["uses check"]],
      // Each loader the reviews drove past the arms above, by the one thing
      // they share: the package named as a string.
      [
        `const fc = await vi.importActual("fast-check"); await fc.check(p);`,
        ["unread: the generator named outside an import"],
      ],
      [
        `const fc = createRequire(import.meta.url)("fast-check"); fc.assert(p);`,
        ["unread: the generator named outside an import"],
      ],
      [
        `import.meta.glob("/node_modules/fast-check/lib/fast-check.js", { eager: true });`,
        ["unread: the generator named outside an import"],
      ],
      [
        "await import(`fast-check`);",
        ["unread: a dynamic import of no literal"],
      ],
      [
        `import fc from "../node_modules/fast-check/lib/fast-check.js"; fc.assert(p);`,
        ["uses assert"],
      ],
      [
        `import prand from "pure-rand"; prand.xoroshiro128plus(7);`,
        ["unread: the generator's random source imported"],
      ],
      [
        `import fc from "fast-check"; fc.nat().generate(new fc.Random(g), undefined);`,
        ["unread: an arbitrary's own generate", "uses Random"],
      ],
      // The same draw with a random source of the test's own, by each
      // spelling a dotted call does not cover.
      [
        `const r = { nextInt: () => 1 }; a["generate"](r, undefined);`,
        ["unread: an arbitrary's own generate"],
      ],
      [
        `Reflect.apply(a.generate, a, [r, undefined]);`,
        ["unread: an arbitrary's own generate"],
      ],
      [`const { generate } = a;`, ["unread: an arbitrary's own generate"]],
      [`import gen from "#gen"; gen.assert(p);`, ["unread: a subpath import"]],
      [`await import("#gen");`, ["unread: a subpath import"]],
      // Loud, and stated in the docstring: a type naming the package.
      [
        `type F = typeof import("fast-check");`,
        ["unread: the generator named outside an import"],
      ],
      // The shapes it must leave alone.
      [`const s = "fast-check, the generator";`, []],
      [`const s = "generate a report"; const t = "#gen";`, []],
      ["const s = `see fast-check`;", []],
      [`import fc from "fast-check"; fc.record({ a: fc.nat() });`, []],
      [`import fc from "fast-check"; let a: fc.Arbitrary<number>;`, []],
      [`import type { Parameters } from "fast-check";`, []],
      [`import { type Parameters, record } from "fast-check";`, []],
      [`import { record } from "fast-check"; const check = 1;`, []],
      [`const fc = { check() {} }; fc.check();`, []],
    ];

    expect(
      rows.map(([source]) => [source, ordered(findings(source, "./row.ts"))]),
    ).toEqual(rows.map(([source, expected]) => [source, ordered(expected)]));
  });
});

describe("the generator's surface", () => {
  it("is exactly the names this guard was written against", () => {
    // **Reds once per version that changes it, deliberately.** A new export
    // may be a runner, a plugin or a global; the person bumping decides which
    // side of `DOOR` it is on, and that decision is the point.
    expect(fastCheckExports()).toEqual(EXPORTS);
  });

  it("names a door only among them", () => {
    expect(DOOR.filter((name) => !EXPORTS.includes(name))).toEqual([]);
  });
});

describe("what a property runs", () => {
  it("never runs fewer examples than the floor, under any profile", () => {
    // The floor is the backend's, for the backend's reason.
    expect(FLOOR).toBe(50);
    expect(
      Object.entries(PROFILES).filter(([, profile]) => profile.runs < FLOOR),
    ).toEqual([]);
    expect(PROFILE).toBe(PROFILES.suite);
  });

  it(
    "refuses a run or a witness that names nothing to reach",
    PROPERTY,
    async () => {
      // A third argument is what the reach pin below counts, so one naming
      // nothing would keep that count right while the run reached nothing.
      await expect(holds(fc.nat(), async () => {}, {})).rejects.toThrow(
        /names nothing/,
      );
      await expect(witness(fc.nat(), {})).rejects.toThrow(/names no class/);
    },
  );

  it("writes a progress line whole through a pipe that is full for a moment", () => {
    // A write refused twice for a full pipe, then taking half, then the rest:
    // the line arrives once and whole, and nothing throws.
    const written: string[] = [];
    let refused = 0;
    writeAll(2, "run 7\n", (_, bytes) => {
      if (refused < 2) {
        refused += 1;
        throw Object.assign(new Error("full"), { code: "EAGAIN" });
      }
      const taken = Math.max(1, Math.floor(bytes.length / 2));
      written.push(new TextDecoder().decode(bytes.subarray(0, taken)));
      return taken;
    });

    expect(written.join("")).toBe("run 7\n");
    expect(refused).toBe(2);
    expect(() =>
      writeAll(2, "x", () => {
        throw Object.assign(new Error("closed"), { code: "EPIPE" });
      }),
    ).toThrow("closed");
  });

  it(
    "draws a fresh seed for every property, unless one is pinned to replay",
    PROPERTY,
    async () => {
      // **The settled decision, held**: a seed the runner returned as a constant
      // would be the fixed sweep `docs/decisions.md` calls the defect, and
      // nothing else here would red on it. Two runs, two seeds, which collide by
      // chance once in four billion; a person replaying with the seed pinned
      // gets that seed twice, which is the pin working.
      const seeds: (number | null)[] = [];
      for (let run = 0; run < 2; run += 1) {
        expect(await holds(fc.nat(), async () => {})).toBe(PROFILE.runs);
        seeds.push(lastSeed());
      }

      expect(new Set(seeds).size).toBe(process.env[REPLAY] ? 1 : 2);
    },
  );

  it(
    "hands a property exactly the values a replay of its seed regenerates",
    PROPERTY,
    async () => {
      // **What makes a progress line evidence**: a run killed while spinning
      // leaves `seed <s>` and `run <i>` as its last words, and the input is
      // only recovered if `replay` at that seed and index is the value the
      // property was running. Every index, in order, because a replay that
      // agreed on the first value and drifted after it would name the wrong
      // input for every hang but the first.
      const arbitrary = fc.record({ n: fc.nat(), s: fc.string() });
      const seen: unknown[] = [];

      expect(
        await holds(arbitrary, async (value) => {
          seen.push(value);
        }),
      ).toBe(PROFILE.runs);
      const seed = lastSeed();
      expect(seed).not.toBeNull();
      expect(seen).toEqual(seen.map((_, at) => replay(arbitrary, seed!, at)));
      // And a witness asks as many values as a property runs, so a rate it
      // measures is a rate per run: a class that is the last of them is seen,
      // and one past them is not.
      let asked = 0;
      await witness(arbitrary, {
        "is the last value a property would run": () => {
          asked += 1;
          return asked === PROFILE.runs;
        },
      });
      await expect(
        witness(arbitrary, { "is never drawn": () => false }),
      ).rejects.toThrow(/none that is never drawn/);
    },
  );
});

/** This guard's own file, which names the variable to look for it. */
const GUARD = "./propertyBudget.test.ts";

/** A file of `frontend/` outside the two module trees, by its path there. */
function outside(relative: string): string {
  return readFileSync(
    fileURLToPath(new URL(`../${relative}`, import.meta.url)),
    "utf8",
  );
}

/**
 * Every committed file under `frontend/` that names what a run reads: the two
 * module trees, every module beyond them, the suite's configuration and any
 * script among them, and the manifest whose scripts start a run. The arm below
 * refuses the replay variable named in any of them.
 *
 * **Every module beyond the trees, and not the one configuration by name**:
 * vitest takes a `vitest.config.ts` ahead of `vite.config.ts`, and one naming
 * the variable outright pinned all 57 seeds with every arm here green while
 * this read `vite.config.ts` alone, measured. The walk is the door rule's.
 *
 * **What it does not read, stated, and what covers it instead.** The
 * pipeline's definition and the scripts that run the suite are not published,
 * so a published test reading them could not pass on the mirror. A pin in the
 * pipeline, in its file or in the project's own CI variables, is refused by
 * the runner, which will not take a pinned seed where `CI` is set. **The suite
 * pod's manifest is read by nothing**: it forwards only the variables it
 * names, so a pin there is a diff to the suite runner, and that diff is the
 * whole of what stands in the way.
 *
 * **Files a loader reads by convention are refused by existence, not read**,
 * in the arms after this one: bun loads a dotenv file into every worker, and
 * vitest copies Vite's prefixed variables into each, so the variable need not
 * be named in a file at all to reach a property. Where Vite looks for one, and
 * what vitest adds to the environment each worker inherits, are read off the
 * configuration vitest's main process loaded rather than its text, so a key
 * spelled by computation is a value like any other. **And the residue, as a
 * mechanism**: code that runs before the runner, a setup file or a global
 * setup, can set the variable under a computed name, which no reading of text
 * sees; so can the configuration's own code, or a `define` key, putting it
 * into the main process's environment, which every worker inherits and which
 * nothing here lists; and a project the configuration names is answered for
 * the root project only.
 */
function runInputs(): [string, string][] {
  return [
    ...testEntriesBesides(GUARD),
    ...sourceEntries(),
    ...beyondTheTrees(),
    ["package.json", outside("package.json")],
  ];
}

/**
 * Bun's configuration, parsed by the runtime the workers are. **Loud where
 * that is not bun**, because a guard that cannot parse the file would read as
 * a file with nothing in it.
 */
function bunConfig(): unknown {
  const bun = (
    globalThis as { Bun?: { TOML: { parse(text: string): unknown } } }
  ).Bun;
  if (bun === undefined) {
    throw new Error(
      "the suite is not running under bun, so bunfig.toml is unread",
    );
  }
  return bun.TOML.parse(outside("bunfig.toml"));
}

/** Every key of a parsed TOML document, as dotted paths, sorted. */
function keysOf(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return [];
  }
  const keys: string[] = [];
  for (const [key, child] of Object.entries(value)) {
    keys.push(`${prefix}${key}`, ...keysOf(child, `${prefix}${key}.`));
  }
  keys.sort();
  return keys;
}

describe("no committed file pins the seed", () => {
  it("names the replay variable in the runner that reads it, and nowhere else", () => {
    // **A mention and not an assignment**, because an assignment has more
    // spellings than a pattern holds: shell, YAML, an object key, a property
    // write, and the `name:` and `value:` pair the suite pod's manifest
    // forwards a variable with, which no `=` or `:` after the name reaches.
    // Nothing a run reads has a reason to name it at all, so naming it is
    // refused whatever the spelling, and a comment doing so is refused too.
    expect(
      runInputs()
        .filter(([, text]) => text.includes(REPLAY))
        .map(([path]) => path),
    ).toEqual(["./property.ts"]);
  });

  it("reads the files a run starts from, so the rule above is not vacuous", () => {
    // A path that resolved to the wrong file would answer nothing, which is a
    // clean result. Each of these is where a pin would most plausibly land.
    const read = new Map(runInputs());
    expect(read.get("package.json")).toContain('"test": "vitest run"');
    expect(read.get("vite.config.ts")).toContain("isolate: false");
  });

  it("leaves no dotenv file where either loader looks", () => {
    // **By existence, because what a loader reads is not a file naming the
    // variable.** Measured in the suite pod: each fork worker starts with
    // `NODE_ENV` set to `test`, and bun loads `.env.test` and
    // `.env.test.local` into it; vitest copies the `VITE_` prefixed variables
    // of mode `test` into each worker as well, from `.env.local` among others,
    // which bun does not load there. A seed pinned in `.env.test` printed one
    // seed for every property with this guard green. Both read `frontend/`
    // itself, bun from the working directory and Vite from the root, and the
    // suite's runner ships an untracked file too, so ignoring one is not the
    // backstop it reads as.
    expect(
      readdirSync(FRONTEND).filter((name) => name.startsWith(".env")),
    ).toEqual([]);
  });

  it("leaves the configuration vitest loaded pointing at no other dotenv file, and copying no pin", () => {
    // **Values, not spellings.** A text match for the two keys passed them
    // written as computed keys, and with the variable in `types/.env.test`
    // and the prefix widened, every seed was one, measured. **And the values
    // vitest's main process holds, not this worker's**: the main process
    // loads the environment, and a configuration answering differently in
    // the two pinned every seed while a resolution here was green, measured.
    // So `tests/runConfiguration.globalSetup.ts` hands over what was loaded:
    // the file, with the root as the only place Vite loads a dotenv file from,
    // which the arm above holds empty; no prefix of its own, so only `VITE_`
    // variables are copied; and what vitest adds to the environment each
    // worker inherits, which is not the whole of it (the residue above).
    const loaded = inject("runConfiguration");
    expect(loaded).toBeDefined();
    expect(`${loaded.root}/`).toBe(FRONTEND);
    expect(loaded.configFile).toBe(`${loaded.root}/vite.config.ts`);
    expect(loaded.envDir).toBe(loaded.root);
    expect(loaded.envPrefix).toBeNull();
    expect(loaded.workerEnv).toContain("MODE");
    expect(loaded.workerEnv).not.toContain(REPLAY);
  });

  it("lets bun's configuration hold only the keys it holds today", () => {
    // **A configuration that runs code**: a top level `preload` runs its
    // script in every bun process of a run, vitest's own and every worker's
    // among them. Measured: one setting the seed under a computed name pinned
    // every property and every witness, this guard's own arms green beside
    // it. So the keys are pinned by equality, and a `preload`, a `[run]` or a
    // `[test]` table reds here once, for somebody to decide on. Values are
    // left free, because the release age is the patch pipeline's to move.
    expect(keysOf(bunConfig())).toEqual([
      "install",
      "install.minimumReleaseAge",
      "install.security",
      "install.security.scanner",
    ]);
  });

  it("reads where the loaders look, so the two rules above are not vacuous", () => {
    // A directory that resolved somewhere else lists no dotenv file either.
    expect(readdirSync(FRONTEND)).toEqual(
      expect.arrayContaining(["bunfig.toml", "package.json", "vite.config.ts"]),
    );
    expect(keysOf({ a: { b: 1, c: { d: 2 } }, e: [] })).toEqual([
      "a",
      "a.b",
      "a.c",
      "a.c.d",
      "e",
    ]);
  });
});

/**
 * Whether an import specifier in the test module at `path` is the runner,
 * **resolved the way the bundler resolves it** rather than matched against
 * the spellings somebody thought of. Relative from the module, or from
 * `frontend/` where it starts with a slash, and any script extension taken
 * off: measured, `../property.js` and `/tests/property` each loaded the
 * runner while the first version matched neither, and a property run through
 * either was counted nowhere, green.
 *
 * **Ends with the runner's path rather than equals it**, so a specifier
 * climbing past `frontend/` and back down, or an absolute path, is the runner
 * too. Counting a module as the runner is the loud direction: its properties
 * are then held to every arm here.
 */
function isRunner(specifier: unknown, path: string): boolean {
  if (typeof specifier !== "string") return false;
  if (!specifier.startsWith(".") && !specifier.startsWith("/")) return false;
  const from = specifier.startsWith("/")
    ? "file:///"
    : `file:///tests/${path.slice(2)}`;
  const resolved = new URL(specifier, from).pathname.replace(
    /\.(?:[cm]?[jt]s|[jt]sx)$/,
    "",
  );
  return resolved.endsWith("/tests/property");
}

/** The names a parameter binds, through any pattern it is written as. */
function boundBy(pattern: unknown): string[] {
  if (!isNode(pattern)) return [];
  switch (pattern.type) {
    case "Identifier":
      return [pattern.name as string];
    case "AssignmentPattern":
      return boundBy(pattern.left);
    case "RestElement":
      return boundBy(pattern.argument);
    case "TSParameterProperty":
      return boundBy(pattern.parameter);
    case "ArrayPattern":
      return (pattern.elements as unknown[]).flatMap(boundBy);
    case "ObjectPattern":
      return (pattern.properties as Node[]).flatMap((one) =>
        boundBy(one.type === "Property" ? one.value : one),
      );
    default:
      return [];
  }
}

/**
 * Whether an identifier under `ancestors` names something other than a value
 * of the scope it sits in: a property after a dot, a key, anything in a type,
 * or a parameter of a function around it, which shadows a function of the
 * same name. A type node holds a value only under its `expression` or
 * `initializer`, as a cast does.
 */
function namesNoOuterValue(node: Node, ancestors: readonly Node[]): boolean {
  const name = node.name as string;
  return (
    isNameOnly(node, ancestors.at(-1)) ||
    ancestors.some((above, at) => {
      const below = ancestors[at + 1] ?? node;
      return (
        above.type.startsWith("TS") &&
        above.expression !== below &&
        above.initializer !== below
      );
    }) ||
    ancestors.some(
      (above) =>
        Array.isArray(above.params) &&
        (above.params as unknown[]).flatMap(boundBy).includes(name),
    )
  );
}

/**
 * The runner's exports that draw values, and every export whose function body
 * the parse read, **derived by parse of the runner**. A body is a function
 * declared, or bound to a top level constant, and an export is one declared
 * exported or named in an export list. A body draws when it reaches a door
 * member of the generator, or names a body that draws as a value.
 *
 * **`read` is what the arm below holds the runner's function exports
 * against**, as the runner itself lists them: an export this parse reads no
 * body for, wrapped in a call or a cast or brought from another module, reds
 * there by name rather than passing as one that draws nothing. **What it does
 * not see**: a method of an exported object, and a local of a body that
 * shadows a drawing function, which is read as that function, loud. And the
 * quiet one: the arm holds exports only, so a read export that draws through
 * a local helper whose body the parse cannot read (in a cast, a wrapped call,
 * an object method, a class, a reassigned binding) is derived as drawing
 * nothing.
 */
function samplersOf(source: string): { draws: string[]; read: string[] } {
  const ast = parseAst(source, { lang: "ts" }) as unknown as Node;
  const namespaces = new Set<string>();
  const bodies = new Map<string, Node>();
  // Exported name to local name, which an export list may make differ.
  const exported = new Map<string, string>();
  for (const statement of ast.body as Node[]) {
    if (
      statement.type === "ImportDeclaration" &&
      isFastCheck(statement.source)
    ) {
      for (const specifier of statement.specifiers as Node[]) {
        if (specifier.type !== "ImportSpecifier") {
          namespaces.add(nameOf(specifier.local)!);
        }
      }
    }
    if (
      statement.type === "ExportNamedDeclaration" &&
      !isNode(statement.declaration) &&
      !isNode(statement.source)
    ) {
      for (const specifier of statement.specifiers as Node[]) {
        exported.set(nameOf(specifier.exported)!, nameOf(specifier.local)!);
      }
    }
    const declared =
      statement.type === "ExportNamedDeclaration" &&
      isNode(statement.declaration)
        ? statement.declaration
        : statement;
    if (declared.type === "FunctionDeclaration" && isNode(declared.id)) {
      const name = nameOf(declared.id)!;
      bodies.set(name, declared);
      if (declared !== statement) exported.set(name, name);
    }
    // A helper written as a constant arrow, the tree's ordinary style, is a
    // body too: read as nothing, it let a stated export draw through it.
    if (declared.type === "VariableDeclaration") {
      for (const declarator of declared.declarations as Node[]) {
        const init = declarator.init;
        if (
          isNode(init) &&
          (init.type === "ArrowFunctionExpression" ||
            init.type === "FunctionExpression") &&
          nameOf(declarator.id) !== null
        ) {
          const name = nameOf(declarator.id)!;
          bodies.set(name, init);
          if (declared !== statement) exported.set(name, name);
        }
      }
    }
  }
  const draws = new Set<string>();
  for (let grew = true; grew;) {
    grew = false;
    for (const [name, body] of bodies) {
      if (draws.has(name)) continue;
      let reaches = false;
      walk(body, (node, ancestors) => {
        const member =
          node.type === "MemberExpression" &&
          isNode(node.object) &&
          node.object.type === "Identifier" &&
          namespaces.has(node.object.name as string) &&
          DOOR.includes(nameOf(node.property) ?? "");
        const call =
          node.type === "Identifier" &&
          node.name !== name &&
          draws.has(node.name as string) &&
          !namesNoOuterValue(node, ancestors);
        if (member || call) reaches = true;
      });
      if (reaches) {
        draws.add(name);
        grew = true;
      }
    }
  }
  const of = (keep: (local: string) => boolean) => {
    const names = [...exported]
      .filter(([, local]) => keep(local))
      .map(([name]) => name);
    names.sort();
    return names;
  };
  return {
    draws: of((local) => draws.has(local)),
    read: of((local) => bodies.has(local)),
  };
}

/** What the parse reads of the runner's own source today. */
const PARSED = samplersOf(testText(RUNNER));

/** The runner's drawing exports, as the runner's own source says today. */
const SAMPLERS = new Set(PARSED.draws);

/**
 * The runner's other exports, stated, so a new one reds once and somebody
 * decides which side of the counting it is on. A name here is a value, or a
 * function whose body the parse read and found drawing nothing.
 */
const DRAWS_NOTHING = [
  "DRAWS_FOR_ITSELF",
  "edges",
  "fastCheckExports",
  "FLOOR",
  "lastSeed",
  "namesTheGenerator",
  "PROFILE",
  "PROFILES",
  "PROPERTY",
  "REPLAY",
  "runnerExports",
  "sometimes",
  "spelled",
  "writeAll",
];

/** The nearest of `ancestors` to the node that satisfies `matches`. */
function innermost(
  ancestors: readonly Node[],
  matches: (node: Node) => boolean,
): Node | undefined {
  for (let at = ancestors.length - 1; at >= 0; at -= 1) {
    if (matches(ancestors[at]!)) return ancestors[at];
  }
  return undefined;
}

/** The runner exports this guard counts, which a module may reach only by a call. */
const CALLED = new Set(["holds", "witness"]);

/**
 * The one module that may reach a drawing export this guard does not count:
 * `replay` is a sampler, and it is here only to be checked against `holds`.
 */
const SAMPLES_UNCOUNTED = GUARD;

/**
 * Calls of the runner's `holds` and `witness` in one module, **by what they
 * bind to and not by what they are called**.
 *
 * Measured against the version that matched a callee named `holds`: an
 * aliased import and a namespace member each ran a property no arm counted,
 * and a local `PROPERTY` satisfied the options arm by name. So a property is
 * a call of whatever local the runner's `holds` is bound to, named, aliased or
 * as a member of the runner's namespace, and the options must be the runner's
 * own `PROPERTY` the same way. **Any other reach of `holds` or `witness` is
 * refused**, a local alias or a reference passed along, because a call the
 * walk cannot see through one is a property it cannot count.
 */
function propertyCalls(source: string, path: string) {
  const ast = parseAst(source, { lang: langOf(path) }) as unknown as Node;
  const bound = new Map<string, string>();
  const namespaces = new Set<string>();
  walk(ast, (node) => {
    if (
      node.type !== "ImportDeclaration" ||
      !isRunner((node.source as Node).value, path)
    ) {
      return;
    }
    for (const specifier of node.specifiers as Node[]) {
      const local = nameOf(specifier.local)!;
      if (specifier.type === "ImportSpecifier") {
        bound.set(local, nameOf(specifier.imported)!);
      } else {
        namespaces.add(local);
      }
    }
  });
  /** The runner export an expression names, or `null`. */
  const runnerName = (node: unknown): string | null => {
    if (!isNode(node)) return null;
    if (node.type === "Identifier")
      return bound.get(node.name as string) ?? null;
    if (
      node.type === "MemberExpression" &&
      node.computed !== true &&
      isNode(node.object) &&
      node.object.type === "Identifier" &&
      namespaces.has(node.object.name as string)
    ) {
      return nameOf(node.property);
    }
    return null;
  };

  let witnesses = 0;
  let properties = 0;
  let reaching = 0;
  const unwrapped: string[] = [];
  const unread: string[] = [];
  const uncounted: string[] = [];
  walk(ast, (node, ancestors) => {
    const parent = ancestors.at(-1);
    if (node.type === "Identifier" && !isNameOnly(node, parent)) {
      const name = node.name as string;
      const declaring =
        parent?.type === "ImportSpecifier" ||
        parent?.type === "ImportNamespaceSpecifier" ||
        parent?.type === "ImportDefaultSpecifier";
      const reach =
        namespaces.has(name) &&
        parent?.type === "MemberExpression" &&
        parent.object === node &&
        parent.computed !== true
          ? parent
          : node;
      const exported =
        reach === node ? bound.get(name) : nameOf((reach as Node).property);
      const holder = reach === node ? parent : ancestors.at(-2);
      if (!declaring && namespaces.has(name) && reach === node) {
        unread.push(
          `the runner's namespace ${name} reached other than by a dot`,
        );
      } else if (
        !declaring &&
        exported !== undefined &&
        exported !== null &&
        CALLED.has(exported) &&
        !(holder?.type === "CallExpression" && holder.callee === reach)
      ) {
        unread.push(`${exported} reached other than by a call`);
      } else if (
        !declaring &&
        exported !== undefined &&
        exported !== null &&
        SAMPLERS.has(exported) &&
        !CALLED.has(exported)
      ) {
        uncounted.push(`${exported}, which draws and is counted by nothing`);
      }
    }
    if (
      (node.type === "ExportNamedDeclaration" ||
        node.type === "ExportAllDeclaration") &&
      isNode(node.source) &&
      isRunner(node.source.value, path)
    ) {
      // A module re-exporting the runner hands its properties to whoever
      // imports it, under a specifier this walk does not take for the runner.
      unread.push("the runner re-exported");
    }
    if (node.type !== "CallExpression") return;
    const callee = runnerName(node.callee);
    if (
      callee === null &&
      isNode(node.callee) &&
      node.callee.type === "Identifier" &&
      CALLED.has(node.callee.name as string)
    ) {
      // **A call the linter counts as an assertion by its name**, which a
      // local function named `witness` satisfied while asserting nothing,
      // measured. This walk binds; a name it cannot bind is refused.
      unread.push(`a ${node.callee.name as string} that is not the runner's`);
    }
    if (callee === "witness") witnesses += 1;
    if (callee !== "holds") return;
    properties += 1;
    if ((node.arguments as unknown[]).length > 2) reaching += 1;
    const test = innermost(
      ancestors,
      (above) =>
        above.type === "CallExpression" &&
        ["it", "test"].includes(nameOf(above.callee) ?? ""),
    );
    const options = test ? runnerName((test.arguments as unknown[])[1]) : null;
    if (options !== "PROPERTY")
      unwrapped.push(`a holds at ${node.start as number}`);
  });
  return { properties, witnesses, reaching, unwrapped, unread, uncounted };
}

/**
 * The properties that name what their run must reach, per module, as a count.
 * **Pinned rather than derived**, because what it holds is that a reach is not
 * dropped: a reach deleted is a smaller count, which only an equality sees.
 */
const REACHING: Readonly<Record<string, number>> = {
  // The arm refusing a reach that names nothing, which is this guard's own.
  "./propertyBudget.test.ts": 1,
  "./lib/audiobook.test.ts": 2,
  "./lib/calibre.test.ts": 1,
  "./lib/cbz.test.ts": 1,
  "./lib/epub.test.ts": 1,
  "./lib/fb2.test.ts": 2,
  "./lib/mobi.test.ts": 1,
  "./lib/pdf.test.ts": 1,
  "./lib/schemaArbitrary.test.ts": 1,
  "./lib/sqlite.test.ts": 1,
  "./lib/stores.test.ts": 1,
  "./lib/takeout.test.ts": 1,
  "./lib/zip.test.ts": 1,
  "./pages/AuthorsPage/AuthorsPage.test.tsx": 1,
  "./pages/BookDetail/BookDetail.test.tsx": 1,
  "./pages/CollectionsPage/CollectionsPage.test.tsx": 1,
  "./pages/DuplicatesPage/DuplicatesPage.test.tsx": 1,
  "./pages/Home/Home.test.tsx": 1,
  "./pages/LoginPage/LoginPage.test.tsx": 1,
  "./pages/LoansPage/LoansPage.test.tsx": 1,
  "./pages/OverduePage/OverduePage.test.tsx": 1,
  "./pages/PublicCataloguePage/PublicBookPage.test.tsx": 1,
  "./pages/PublicCataloguePage/PublicCataloguePage.test.tsx": 1,
  "./pages/QuotesPage/QuotesPage.test.tsx": 1,
  "./pages/ScanPage/ScanPage.test.tsx": 1,
  "./pages/SeriesPage/SeriesPage.test.tsx": 1,
  "./pages/SettingsPage/AccountSettingsPage/AccountSettingsPage.test.tsx": 1,
  "./pages/SettingsPage/AppearanceSettingsPage/AppearanceSettingsPage.test.tsx": 1,
  "./pages/SettingsPage/CatalogueSettingsPage/CatalogueSettingsPage.test.tsx": 1,
  "./pages/SettingsPage/DataSettingsPage/DataSettingsPage.test.tsx": 1,
  "./pages/SettingsPage/LendingSettingsPage/LendingSettingsPage.test.tsx": 1,
  "./pages/SettingsPage/LibrarySettingsPage/LibrarySettingsPage.test.tsx": 1,
  "./pages/SettingsPage/PublicCatalogueSettingsPage/PublicCatalogueSettingsPage.test.tsx": 1,
  "./pages/StatsPage/StatsPage.test.tsx": 1,
  "./pages/TrashPage/TrashPage.test.tsx": 1,
};

/** A module's calls, every field empty but what a row names. */
function callsOf(
  found: Partial<ReturnType<typeof propertyCalls>>,
): ReturnType<typeof propertyCalls> {
  return {
    properties: 0,
    witnesses: 0,
    reaching: 0,
    unwrapped: [],
    unread: [],
    uncounted: [],
    ...found,
  };
}

describe("every property", () => {
  const withProperties = () =>
    testEntriesBesides(RUNNER)
      .map(([path, source]) => [path, propertyCalls(source, path)] as const)
      .filter(([, calls]) => calls.properties > 0);

  it("runs inside an it taking the runner's options", () => {
    expect(
      withProperties().flatMap(([path, calls]) =>
        calls.unwrapped.map((where) => `${path}: ${where}`),
      ),
    ).toEqual([]);
  });

  it("is reached only by a call this guard can count", () => {
    // Over every test module, not only those with a property: an alias that
    // hides the only call is a module whose properties this guard reads as
    // none.
    expect(
      testEntriesBesides(RUNNER).flatMap(([path, source]) =>
        propertyCalls(source, path).unread.map((what) => `${path}: ${what}`),
      ),
    ).toEqual([]);
  });

  it("counts by binding, every spelling it exists for", () => {
    const rows: [string, ReturnType<typeof propertyCalls>][] = [
      [
        `import { holds } from "./property"; it("x", PROPERTY, async () => { await holds(a, p); });`,
        callsOf({ properties: 1, unwrapped: ["a holds at 74"] }),
      ],
      [
        `import { holds, PROPERTY } from "./property"; it("x", PROPERTY, async () => { await holds(a, p); });`,
        callsOf({ properties: 1 }),
      ],
      [
        `import { holds as run, PROPERTY as P } from "./property"; it("x", P, async () => { await run(a, p); });`,
        callsOf({ properties: 1 }),
      ],
      [
        `import * as r from "./property"; it("x", r.PROPERTY, async () => { await r.holds(a, p); await r.witness(a, {}); });`,
        callsOf({ properties: 1, witnesses: 1 }),
      ],
      [
        `import { holds as run } from "./property"; it("x", async () => { await run(a, p); });`,
        callsOf({ properties: 1, unwrapped: ["a holds at 71"] }),
      ],
      [
        `import { holds } from "./property"; const PROPERTY = { timeout: 50 }; it("x", PROPERTY, async () => { await holds(a, p); });`,
        callsOf({ properties: 1, unwrapped: ["a holds at 108"] }),
      ],
      [
        `import { holds } from "./property"; const run = holds;`,
        callsOf({ unread: ["holds reached other than by a call"] }),
      ],
      [
        `import * as r from "./property"; const run = r.holds; const all = r;`,
        callsOf({
          unread: [
            "holds reached other than by a call",
            "the runner's namespace r reached other than by a dot",
          ],
        }),
      ],
      // The runner by each specifier the bundler resolves to it, which a
      // match on two spellings counted nowhere.
      [
        `import { holds } from "./property.js"; it("x", async () => { await holds(a, p); });`,
        callsOf({ properties: 1, unwrapped: ["a holds at 67"] }),
      ],
      [
        `import { holds } from "/tests/property"; it("x", async () => { await holds(a, p); });`,
        callsOf({ properties: 1, unwrapped: ["a holds at 69"] }),
      ],
      [
        `import { holds, PROPERTY } from "./property"; it("x", PROPERTY, async () => { await holds(a, p, { r: () => true }); });`,
        callsOf({ properties: 1, reaching: 1 }),
      ],
      // A drawing export the walk does not count, which ran three examples at
      // a seed of its own with every arm green, measured.
      [
        `import { replay } from "./property"; for (let at = 0; at < 3; at += 1) f(replay(a, 7, at));`,
        callsOf({
          uncounted: ["replay, which draws and is counted by nothing"],
        }),
      ],
      [
        `export { holds } from "./property";`,
        callsOf({ unread: ["the runner re-exported"] }),
      ],
      // A name that is not the runner's, which a guard by name counted and
      // the linter still takes for an assertion: refused, loud.
      [
        `const holds = () => 0; it("x", async () => { holds(); });`,
        callsOf({ unread: ["a holds that is not the runner's"] }),
      ],
      [
        `function witness() {} it("x", () => { witness(); });`,
        callsOf({ unread: ["a witness that is not the runner's"] }),
      ],
      [`import { holds } from "./properties"; f(holds);`, callsOf({})],
      [
        `import { holds } from "../../tests/property.mts"; f(holds);`,
        callsOf({ unread: ["holds reached other than by a call"] }),
      ],
    ];

    expect(
      rows.map(([source]) => propertyCalls(source, "./row.test.ts")),
    ).toEqual(rows.map(([, expected]) => expected));
  });

  it("draws through exactly the runner exports this guard knows", () => {
    // **Derived from the runner and asserted**, so a fourth sampler reds
    // here once rather than becoming a fixed sweep no arm counts.
    expect(
      [...SAMPLERS],
      "a new export of tests/property.ts draws: count it where holds and " +
        "witness are counted, in propertyCalls, or make it draw nothing",
    ).toEqual(["holds", "replay", "witness"]);
    const exports = runnerExports();
    const stated = [...SAMPLERS, ...DRAWS_NOTHING];
    stated.sort();
    expect(
      exports.map(([name]) => name),
      "a new export of tests/property.ts that draws nothing is named in " +
        "DRAWS_NOTHING in this file; one that draws is found by samplersOf " +
        "when every helper it draws through is a body the parse reads",
    ).toEqual(stated);
    // **The parse held against the runner's own list**: every export that is
    // a function at run time must be one whose body the parse read, so a form
    // it cannot read is refused here rather than read as drawing nothing.
    expect(
      exports
        .filter(
          ([name, kind]) => kind === "function" && !PARSED.read.includes(name),
        )
        .map(([name]) => name),
      "an export of tests/property.ts whose body samplersOf cannot read: " +
        "write it as a function declaration, or a top level constant bound " +
        "to an arrow, exported by declaration or by an export list",
    ).toEqual([]);
    expect(
      samplersOf(
        `import fc from "fast-check"; function inner() { return fc.sample(a); } export function outer() { return inner(); } export function plain() { return 1; }`,
      ),
    ).toEqual({ draws: ["outer"], read: ["outer", "plain"] });
    expect(
      samplersOf(
        `import fc from "fast-check"; const inner = () => fc.sample(a); export const outer = function () { return inner(); }; export const plain = () => 1;`,
      ),
    ).toEqual({ draws: ["outer"], read: ["outer", "plain"] });
    // An export list, renamed, and a drawing name in a member, a key, a type
    // and a parameter, none of which reaches it.
    expect(
      samplersOf(
        `import fc from "fast-check"; const inner = () => fc.sample(a); const quiet = (r: { inner: number }, inner: number) => r.inner + ({ inner: 1 }).inner + inner; export { inner as drawn, quiet }; export const cast = (() => 1) as () => number;`,
      ),
    ).toEqual({ draws: ["drawn"], read: ["drawn", "quiet"] });
  });

  it("draws uncounted only in this guard", () => {
    // `replay` is here to be checked against `holds`, and anywhere else it
    // is a sweep of the examples it is handed, at the seed it is handed.
    expect(
      testEntriesBesides(RUNNER)
        .filter(([path]) => path !== SAMPLES_UNCOUNTED)
        .flatMap(([path, source]) =>
          propertyCalls(source, path).uncounted.map(
            (what) => `${path}: ${what}`,
          ),
        ),
    ).toEqual([]);
    expect(propertyCalls(testText(GUARD), GUARD).uncounted).not.toEqual([]);
  });

  it("is beside a witness that its arbitrary draws what it is about", () => {
    // A witness per property, counted per module: a property with no witness
    // is green over a generator nobody has asked anything of. **A witness
    // asserts inside and returns nothing**, so a counted call is an
    // assertion and not a sample somebody may never filter.
    expect(
      withProperties()
        .filter(([, calls]) => calls.witnesses < calls.properties)
        .map(([path]) => path),
    ).toEqual([]);
  });

  it("is what a witness rides beside, so no witness stands alone", () => {
    // **A witness hands every value it draws to a predicate of the test's
    // own**, which may assert on each and stop when it likes: measured, three
    // values asserted that way with every arm green. Beside a property that
    // is a witness; in a module with none it is a property by another name,
    // under no count. **The residue, stated**: a module with a property can
    // still assert inside an extra witness's predicate. Closing it means a
    // witness always asking the profile's whole count, whose cost on the
    // store witness, which opens libraries, is unmeasured.
    expect(
      testEntriesBesides(RUNNER)
        .map(([path, source]) => [path, propertyCalls(source, path)] as const)
        .filter(([, calls]) => calls.witnesses > 0 && calls.properties === 0)
        .map(([path]) => path),
    ).toEqual([]);
  });

  it("names what its run must reach where it did, and loses none silently", () => {
    // **Pinned, because a reach is one argument nothing else reads**:
    // deleting one left a reader that stopped reaching its bomb green on
    // every arm here, measured. Per module, the properties passing one.
    expect(
      Object.fromEntries(
        withProperties()
          .filter(([, calls]) => calls.reaching > 0)
          .map(([path, calls]) => [path, calls.reaching]),
      ),
    ).toEqual(REACHING);
  });

  it("is in a module this guard knows about, and every one of them", () => {
    // **The population, derived and asserted.** A property added elsewhere
    // reds here once, and the person adding it reads this guard.
    const paths = withProperties().map(([path]) => path);
    paths.sort();
    expect(paths).toEqual([
      "./lib/adobeDigitalEditions.test.ts",
      "./lib/audiobook.test.ts",
      "./lib/calibre.test.ts",
      "./lib/cbz.test.ts",
      "./lib/digitalReference.test.ts",
      "./lib/epub.test.ts",
      "./lib/fb2.test.ts",
      "./lib/fileName.test.ts",
      "./lib/kindle.test.ts",
      "./lib/mobi.test.ts",
      "./lib/opf.test.ts",
      "./lib/pdf.test.ts",
      "./lib/schemaArbitrary.test.ts",
      "./lib/sqlite.test.ts",
      "./lib/stores.test.ts",
      "./lib/takeout.test.ts",
      "./lib/xmlEntities.test.ts",
      "./lib/zip.test.ts",
      "./pages/AuthorsPage/AuthorsPage.test.tsx",
      "./pages/BookDetail/BookDetail.test.tsx",
      "./pages/CollectionsPage/CollectionsPage.test.tsx",
      "./pages/DuplicatesPage/DuplicatesPage.test.tsx",
      "./pages/Home/Home.test.tsx",
      "./pages/LoansPage/LoansPage.test.tsx",
      "./pages/LoginPage/LoginPage.test.tsx",
      "./pages/OverduePage/OverduePage.test.tsx",
      "./pages/PublicCataloguePage/PublicBookPage.test.tsx",
      "./pages/PublicCataloguePage/PublicCataloguePage.test.tsx",
      "./pages/QuotesPage/QuotesPage.test.tsx",
      "./pages/ScanPage/ScanPage.test.tsx",
      "./pages/SeriesPage/SeriesPage.test.tsx",
      "./pages/SettingsPage/AccountSettingsPage/AccountSettingsPage.test.tsx",
      "./pages/SettingsPage/AppearanceSettingsPage/AppearanceSettingsPage.test.tsx",
      "./pages/SettingsPage/CatalogueSettingsPage/CatalogueSettingsPage.test.tsx",
      "./pages/SettingsPage/DataSettingsPage/DataSettingsPage.test.tsx",
      "./pages/SettingsPage/LendingSettingsPage/LendingSettingsPage.test.tsx",
      "./pages/SettingsPage/LibrarySettingsPage/LibrarySettingsPage.test.tsx",
      "./pages/SettingsPage/PublicCatalogueSettingsPage/PublicCatalogueSettingsPage.test.tsx",
      "./pages/StatsPage/StatsPage.test.tsx",
      "./pages/TrashPage/TrashPage.test.tsx",
      "./propertyBudget.test.ts",
    ]);
    expect(testEntries().length).toBeGreaterThan(withProperties().length);
  });
});

/**
 * Where a stranger's bytes or names enter the application: the reader
 * registry, the store registry, the audiobook tag reader, the Calibre intake
 * and the two string doors a picked file's name and path go through.
 *
 * **Stated, and what holds it is the equality below**: a root dropped from
 * here takes its closure with it, and a module of that closure that has a
 * property is then a property of no door, which reds.
 *
 * **The door outside it, named**: `lib/audiobookGroups.ts`, which the scan
 * page loads lazily. It groups what the audiobook reader and the file name
 * door already answered, strings each bounded by those doors, and reads no
 * byte of its own, so it is outside the rule as it stands rather than
 * covered by it. **Nothing here can see a seventh root**: the population is
 * what these six reach, by construction.
 */
const ROOTS = [
  "lib/audiobook.ts",
  "lib/calibre.ts",
  "lib/digitalReference.ts",
  "lib/fileName.ts",
  "lib/fileReaders.ts",
  "lib/stores.ts",
];

/**
 * Modules of the closure reached only through a door, named as such and
 * **not claimed as covered by a property of their own**: what holds each is
 * the property of every door that reaches it, which is weaker than a property
 * aimed at it and is said here so nobody reads it as more.
 */
const THROUGH_A_DOOR: Readonly<Record<string, string>> = {
  "lib/appleBooks.ts": "the store property, through the Apple Books opener",
  "lib/bookBounds.ts": "the string doors, whose bounds it declares",
  "lib/elementChildren.ts": "every XML door, whose parsed tree it walks",
  "lib/fileReaders.ts": "the registry: each reader it names has its own",
  "lib/isbn.ts": "every door that reads an identifier",
  "lib/isbnLabel.ts": "the doors that read an identifier, through isbn.ts",
  "lib/kobo.ts": "the store property, through the Kobo opener",
  "lib/moonReader.ts": "the store property, through the Moon+ opener",
  "lib/sqliteRow.ts": "the store and Calibre doors, whose cells it decodes",
  "lib/year.ts": "every door that reads a date",
};

/**
 * The one subtree of `src/` the walk does not follow, and why: the generated
 * client's model is enums of constants and types, regenerated from the
 * schema, and reads nothing. **An exclusion and not an inclusion**, so a
 * helper moved anywhere else under `src/` is in the closure: measured, one
 * moved to `src/app/` and called by a reader on a member's text passed every
 * arm here while the walk followed `lib/` alone.
 */
const NOT_FOLLOWED = "api/generated/";

/**
 * What the module at `url` loads for a value, as paths below `src/`, **resolved
 * by Vite rather than by this file**: its server transform of the module, read
 * for the imports it kept. So a reader loaded through `import.meta.glob`, a
 * specifier ending in `.js` and a type only import each mean here what they
 * mean to the build, where a hand resolution missed the first, threw on the
 * second and had to be taught the third. The aliases are the ones vitest's main
 * process resolved by, so a specifier only one resolves is followed, and a
 * module the suite replaces with a double is the double here. What is not a module under
 * `src/`, a package or an asset, is a leaf. **What it does not follow,
 * stated**: a module loaded as a Web Worker, by `new Worker(new URL(...))` or
 * a `?worker` import, which the page build bundles and this transform does not
 * report as the module; and a root absolute specifier in backticks,
 * `` import(`/src/lib/x.ts`) ``, which the transform drops and `unreadImports`
 * reads as a literal. The first is a gap, stated; the second takes a
 * deliberate act.
 */
async function loads(server: ViteDevServer, url: string): Promise<string[]> {
  const result = await server.environments.ssr.transformRequest(url);
  if (result === null) throw new Error(`the bundler could not load ${url}`);
  return [...(result.deps ?? []), ...(result.dynamicDeps ?? [])]
    .filter((id) => /^\/src\/[^?]*\.tsx?$/.test(id))
    .map((id) => id.slice("/src/".length));
}

/**
 * Every dynamic import in one module whose specifier is not a literal.
 *
 * **Refused by the arm below**, because what Vite makes of one is not what the
 * module loads. A bare variable, or a template such as `./${g}.ts`, it reads
 * as nothing and leaves out of what `loads` answers in silence: a reader
 * loaded by a template passed every arm here, measured. A template with a
 * directory, such as `../lib/${g}.ts`, it widens to every module the pattern
 * matches, which would demand a property of each.
 */
function unreadImports(path: string, source: string): string[] {
  const ast = parseAst(source, { lang: langOf(path) }) as unknown as Node;
  const unread: string[] = [];
  walk(ast, (node) => {
    if (
      node.type === "ImportExpression" &&
      (!isNode(node.source) || stringOf(node.source) === null)
    ) {
      unread.push(`${path}: a dynamic import of no literal`);
    }
  });
  return unread;
}

/**
 * Every module under `src/` the roots reach for a value, the roots among
 * them, and what the walk could not follow.
 */
async function closure(
  server: ViteDevServer,
): Promise<{ modules: string[]; unread: string[] }> {
  const sources = new Map(sourceEntries());
  const seen = new Set<string>();
  const unread: string[] = [];
  const visit = async (path: string): Promise<void> => {
    if (seen.has(path) || path.startsWith(NOT_FOLLOWED)) return;
    const source = sources.get(path);
    if (source === undefined) throw new Error(`${path} is not a module`);
    seen.add(path);
    unread.push(...unreadImports(path, source));
    await Promise.all((await loads(server, `/src/${path}`)).map(visit));
  };
  await Promise.all(ROOTS.map(visit));
  unread.sort();
  const modules = [...seen];
  modules.sort();
  return { modules, unread };
}

/**
 * The modules whose own test file runs a property, by that file's name, **and
 * only where that file loads the module for a value**: measured, a test file
 * gaining a property over nothing of its module's credited the module with
 * every arm green. **Still not a check of what the property drives**, which no
 * parse here makes: a test loading its module and running a property over
 * something else is credited.
 */
async function propertyModules(server: ViteDevServer): Promise<string[]> {
  const credited = await Promise.all(
    testEntriesBesides(RUNNER)
      .filter(([path]) => path.startsWith("./lib/"))
      .filter(([path, source]) => propertyCalls(source, path).properties > 0)
      .map(async ([path]) => {
        const module = path.replace(/^\.\//, "").replace(/\.test\.ts$/, ".ts");
        const loaded = await loads(server, `/tests/${path.slice(2)}`);
        return loaded.includes(module) ? module : null;
      }),
  );
  const modules = credited.filter((one): one is string => one !== null);
  modules.sort();
  return modules;
}

describe("every door a stranger's input enters through", () => {
  let server: ViteDevServer;
  let reached: { modules: string[]; unread: string[] };
  let credited: string[];

  // **Derived once**: the walk transforms every module it reaches and every
  // test of the reader family, which no single arm's five seconds holds.
  beforeAll(async () => {
    server = await createServer({
      root: FRONTEND,
      mode: "test",
      logLevel: "silent",
      appType: "custom",
      server: { middlewareMode: true, hmr: false, ws: false, watch: null },
      optimizeDeps: { noDiscovery: true, include: [] },
      // **The run's aliases, as vitest's main process resolved them**, handed
      // over by `tests/runConfiguration.globalSetup.ts`. A plain server reads
      // no `test.alias`, so a test importing its module through one loaded
      // nothing here and its property went uncredited, measured.
      resolve: { alias: inject("runConfiguration").aliases },
    });
    reached = await closure(server);
    credited = await propertyModules(server);
  }, 60_000);

  afterAll(async () => {
    await server.close();
  });

  it("has a property, or is named as reached only through one", () => {
    // **Two derivations of one population**: what the doors import, walked
    // from the source, and which modules' tests run a property, walked from
    // the test tree. A reader added to a registry and given no property is in
    // the first and not the second, and a property left behind by a door
    // that went is in the second and not the first.
    const named = [...credited, ...Object.keys(THROUGH_A_DOOR)];
    named.sort();
    expect(reached.modules).toEqual(named);
  });

  it("is loaded by a specifier the walk can read", () => {
    expect(reached.unread).toEqual([]);
  });

  it("names nothing as reached through a door that has a property of its own", () => {
    expect(
      Object.keys(THROUGH_A_DOOR).filter((path) => credited.includes(path)),
    ).toEqual([]);
  });

  it("follows the edges a registry loads its readers by", async () => {
    // **The reader registry imports every reader lazily**, so a walk that
    // followed only static imports would stop at it and report a closure with
    // no reader in it, which the equality above would then hold over less.
    expect(await loads(server, "/src/lib/fileReaders.ts")).toEqual(
      expect.arrayContaining(["lib/epub.ts", "lib/pdf.ts"]),
    );
    expect(
      unreadImports(
        "lib/x.ts",
        'await import("./e"); await import(`./f`); await import(`./${g}`); await import(h);',
      ),
    ).toEqual([
      "lib/x.ts: a dynamic import of no literal",
      "lib/x.ts: a dynamic import of no literal",
    ]);
  });

  it("applies the run's aliases, and each resolves as its replacement does", async () => {
    // **Two loads of the configuration compared**: what this worker's server
    // read as `test.alias` against what the main process resolved by, so a
    // global setup reading the wrong place, or a configuration answering
    // differently in a worker, reds here rather than walking without the
    // alias. Then each alias the walk applies must resolve as its
    // replacement does, which an alias the walk did not apply cannot: the
    // scanner's double is not the package.
    const run = inject("runConfiguration").aliases;
    const own = server.config.test?.alias ?? {};
    const declared = Array.isArray(own)
      ? own.map(({ find, replacement }) => ({ find, replacement }))
      : Object.entries(own).map(([find, replacement]) => ({
          find,
          replacement,
        }));
    expect(
      declared.filter(
        (one) =>
          !run.some(
            (applied) =>
              applied.find === one.find &&
              applied.replacement === one.replacement,
          ),
      ),
      "a test.alias entry this worker read is not among the aliases the " +
        "run resolved by: make the global setup hand it over, or make the " +
        "configuration answer the same in a worker, and spell its find as a string",
    ).toEqual([]);
    const importer = join(FRONTEND, "src/lib/fileReaders.ts");
    const resolve = async (id: string) =>
      (await server.environments.ssr.pluginContainer.resolveId(id, importer))
        ?.id;
    const resolved = await Promise.all(
      run.map(async ({ find, replacement }) => ({
        find,
        byFind: await resolve(find),
        // What Vite's alias plugin answers for a replacement that resolves
        // to nothing, a directory, is the replacement itself.
        byReplacement: (await resolve(replacement)) ?? replacement,
      })),
    );
    expect(
      resolved.filter((one) => one.byFind !== one.byReplacement),
      "an alias the walk does not resolve to its replacement: hand the " +
        "run's aliases to the walk's server in beforeAll above",
    ).toEqual([]);
  });

  it("follows a glob, a script suffix and an asset as the build does", async () => {
    // A reader behind `import.meta.glob` passed every arm while the walk read
    // specifiers itself, and a `.js` suffix or an asset made it throw. The
    // type only import is the edge the build drops.
    const directory = mkdtempSync(join(tmpdir(), "endpaper-closure-"));
    const registry = join(directory, "registry.ts");
    writeFileSync(
      registry,
      [
        'export const readers = import.meta.glob("/src/lib/epub.ts");',
        'export { supportedExtension } from "/src/lib/fileName.js";',
        'export { default as sheet } from "/src/index.css?url";',
        'import type { SourceRecord } from "/src/lib/sourceRecord";',
      ].join("\n"),
    );
    try {
      const found = await loads(server, registry);
      found.sort();
      expect(found).toEqual(["lib/epub.ts", "lib/fileName.ts"]);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
