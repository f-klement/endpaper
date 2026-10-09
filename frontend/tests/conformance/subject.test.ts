/**
 * @vitest-environment node
 *
 * The TypeScript side of the shared subject conformance suite.
 *
 * The cases live in `conformance/cases/subject.json`, outside both language
 * trees, and `backend/tests/conformance/test_subject.py` runs the same file.
 * `conformance/subject.md` holds what the invariant is and why a case carries
 * both implementations' answers rather than one expectation.
 *
 * **This arm is half of a lock and is not a specification on its own.** It
 * holds that `boundCategories` answers what the `browser` field says. What
 * makes that field trustworthy is the Python side, which runs the server's rule
 * over the same literal and asserts it gives the server's own answer about the
 * raw input. Edit a `browser` value to green this file and that arm reddens.
 * Shipping this one alone would be a golden file wearing a conformance suite's
 * name.
 *
 * **A runner, holding no subject expectation of its own.** Every expectation
 * comes out of the case file. What is written here is the guards below, which
 * are expectations about the case file rather than about subjects.
 *
 * Three ways this could quietly stop testing anything, and what stops each:
 *
 * - **The case file is missing or emptied.** `load()` throws at module scope, so
 *   the file fails to collect and the suite fails. It never skips: a conformance
 *   suite that silently runs zero cases is the failure that makes this theatre.
 * - **The case file has drifted from the format.** Every file is validated
 *   against `conformance/schema/subject.schema.json` before a single case runs.
 * - **This runner has drifted from the schema.** The outcome classifier is
 *   compared against the schema's own list of outcome classes, so a class added
 *   to the specification and not wired here fails rather than going unexercised.
 *
 * **The loader below is copied from `isbn.test.ts` rather than shared with it**,
 * and that is deliberate. The two are independent readings of one rule in one
 * language, which is the arrangement this directory already defends between the
 * languages: a shared loader is a single point whose weakening is invisible in
 * both domains at once, where two copies fail independently. The ISBN loader is
 * also welded to guards that are ISBN's alone, and refactoring a heavily
 * attacked file to share sixty lines means re-verifying every one of them.
 *
 * Node environment rather than jsdom: this reads a file and calls pure
 * functions, and there is no DOM in it. **The pragma is in this docblock and
 * not in a `//` comment above it**, because `frontend/vite.config.ts` counts
 * the opt outs with a grep anchored on ` * @vitest-environment node`, and the
 * `//` spelling works in vitest while being invisible to that count.
 */

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";

import { boundCategories } from "../../src/lib/bookRequest";

// frontend/tests/conformance/subject.test.ts -> the repository root.
const CASES_PATH = fileURLToPath(
  new URL("../../../conformance/cases/subject.json", import.meta.url),
);
const SCHEMA_PATH = fileURLToPath(
  new URL("../../../conformance/schema/subject.schema.json", import.meta.url),
);
const CASES_DIR = fileURLToPath(
  new URL("../../../conformance/cases/", import.meta.url),
);
const FRONTEND_RUNNERS = fileURLToPath(
  new URL("../../../frontend/tests/conformance/", import.meta.url),
);
const BACKEND_RUNNERS = fileURLToPath(
  new URL("../../../backend/tests/conformance/", import.meta.url),
);

type Answer = { kind: "kept" | "dropped" | "refused"; value: string | null };
type Case = {
  id: string;
  input: string;
  browser: Answer;
  server: Answer;
  why: string;
};

/**
 * The partition, as a table from a pair of outcomes onto one class name.
 *
 * **A case's class is derived from what it says rather than declared in the
 * file**, so a case cannot be filed under a class it does not belong to, and a
 * pair nobody has thought about is classified nowhere and fails by name. That
 * is `backend/book_columns.py`'s discipline: one partition over the whole
 * population, refused when a member is classified nowhere or twice. It is what
 * this domain has instead of the ISBN runner's operation dispatch, because
 * every case here runs the same pipeline and an `op` field would carry a guard
 * that cannot fail.
 *
 * The two pairs missing here are the two the schema refuses: a browser that
 * drops what the server would have kept is a false refusal, and a server that
 * refuses what the browser sent costs the whole book.
 */
const OUTCOME_CLASSES: Record<string, string> = {
  "kept/kept": "kept-by-both",
  "kept/dropped": "dropped-by-the-server",
  "dropped/dropped": "dropped-by-the-browser",
  "dropped/refused": "refused-by-the-server",
};

function outcomeClass(one: Case): string | undefined {
  return OUTCOME_CLASSES[`${one.browser.kind}/${one.server.kind}`];
}

// A floor, not a count, and it is here for the same reason `palettes.test.ts`
// asserts it has rows it can actually see: a loader that produced one case, or
// none, would make every assertion below vacuous while the suite stayed green.
// The schema's `minItems` rejects an empty array; this rejects a gutted file.
// `conformance/subject.md` carries why the number is below the file's size and
// what actually protects the cases that carry a reason. Kept in step with the
// Python runner's MINIMUM_CASES by hand, and a mismatch costs nothing: the
// smaller of the two is the one that binds.
const MINIMUM_CASES = 14;

function read(path: string, what: string): unknown {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch (cause) {
    throw new Error(
      `conformance ${what} missing or unreadable: ${path}. This suite runs the ` +
        `shared fixtures in conformance/cases/, and refuses to pass by running ` +
        `none of them. (${String(cause)})`,
    );
  }
  return JSON.parse(text) as unknown;
}

function load(): { cases: Case[]; classes: string[] } {
  const document = read(CASES_PATH, "case file") as { cases: Case[] };
  const schema = read(SCHEMA_PATH, "schema") as {
    $defs: { outcomeClass: { enum: string[] } };
  };

  // **Strict mode on, and it is the only detector of a typoed schema keyword
  // either runner has.** Measured 2026-09-06 on the ISBN schema: with
  // `minLength` spelled `minLenght`, a case carrying a one character `why`
  // validates clean under `strict: false`, and Python misses it too, because an
  // unknown keyword is legal JSON Schema and `check_schema` passes it. Strict
  // mode throws at compile. `allowUnionTypes` is what an answer's
  // `["string", "null"]` value needs.
  const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true });
  const validate = ajv.compile(schema);
  if (!validate(document)) {
    const detail = (validate.errors ?? [])
      .map(
        (error) => `  at ${error.instancePath || "<root>"}: ${error.message}`,
      )
      .join("\n");
    throw new Error(
      `${CASES_PATH} does not match subject.schema.json:\n${detail}`,
    );
  }

  const identifiers = document.cases.map((one) => one.id);
  // JSON Schema cannot express uniqueness across a property of array items, so
  // both runners assert it. A duplicated id is a case silently overwritten in
  // any implementation that keys on it.
  const duplicates = [
    ...new Set(identifiers.filter((id, at) => identifiers.indexOf(id) !== at)),
  ].sort();
  if (duplicates.length > 0) {
    throw new Error(
      `duplicate case ids in ${CASES_PATH}: ${duplicates.join(", ")}`,
    );
  }
  return { cases: document.cases, classes: schema.$defs.outcomeClass.enum };
}

const { cases, classes } = load();

describe("the case file is worth running", () => {
  it("carries enough cases to be a specification", () => {
    expect(cases.length).toBeGreaterThanOrEqual(MINIMUM_CASES);
  });

  it("names every outcome class the schema names, and no others", () => {
    // The dispatch cross check, against the classifier's own range rather than
    // against what the cases happen to exercise: those are two different
    // questions and the arm below is the other one. A class added to the
    // specification and not wired here fails on this line.
    expect([...new Set(Object.values(OUTCOME_CLASSES))].sort()).toEqual(
      [...classes].sort(),
    );
  });

  it("puts every case in exactly one outcome class", () => {
    // A lookup in one table, so "at most one" holds by construction and what
    // this fails on is "at least one": a pair the table does not know. The
    // schema admits four pairs and the table knows four, and a fifth arriving
    // in either place without the other is what this catches.
    const unclassified = cases
      .filter((one) => outcomeClass(one) === undefined)
      .map((one) => `${one.id} (${one.browser.kind}/${one.server.kind})`);
    expect(unclassified).toEqual([]);
  });

  it("exercises every outcome class with at least one case", () => {
    const missing = classes.filter(
      (name) => !cases.some((one) => outcomeClass(one) === name),
    );
    expect(missing).toEqual([]);
  });

  it("carries cases where the browser changes what it was given", () => {
    // **Not the same anti vacuity as the floor.** A file of cases the browser
    // returns unchanged clears the floor, exercises every outcome class and
    // runs every arm here, while pinning only that `boundCategories` is the
    // identity on the shapes it was handed. It is also what would make the
    // Python side's equality arm a second copy of its absolute arm, since
    // `server(browser(x))` is then `server(x)` by substitution rather than by
    // measurement. The count that sees this is of what the browser **changes**,
    // never of what it keeps.
    const transformed = cases.filter(
      (one) => one.browser.kind === "kept" && one.browser.value !== one.input,
    );
    expect(transformed.length).toBeGreaterThan(0);
  });

  it("has a runner on both sides for every domain in the case directory", () => {
    // **The failure a second domain makes possible for the first time**: a
    // domain added on one side only, which reads as a passing suite on the side
    // that has no runner for it. Membership is derived from what the repository
    // versions rather than from a list, so a third domain is covered by the
    // commit that creates its case file.
    //
    // **What this checks is that a runner file exists, not that it runs those
    // cases.** A file named for a domain and reading another domain's cases
    // passes here. Closing that would need this arm to parse two languages, and
    // the loader in each runner already fails loudly on a missing or drifted
    // case file, which is the half that costs a silent pass.
    const domains = readdirSync(CASES_DIR)
      .filter((name) => name.endsWith(".json"))
      .map((name) => name.slice(0, -".json".length))
      .sort();
    expect(domains.length).toBeGreaterThan(0);
    const here = new Set(readdirSync(FRONTEND_RUNNERS));
    const there = new Set(readdirSync(BACKEND_RUNNERS));
    const missing = domains.flatMap((domain) => [
      ...(here.has(`${domain}.test.ts`)
        ? []
        : [`frontend/tests/conformance/${domain}.test.ts`]),
      ...(there.has(`test_${domain}.py`)
        ? []
        : [`backend/tests/conformance/test_${domain}.py`]),
    ]);
    expect(missing).toEqual([]);
  });
});

describe("shared subject conformance cases", () => {
  // The `why` goes into the failure message because it is the only place the
  // reason for a case lives, and a failure here is a divergence between two
  // implementations rather than an ordinary broken test.
  it.each(cases)("$id", (one: Case) => {
    const kept = boundCategories([one.input]);
    const actual: Answer =
      kept.length === 0
        ? { kind: "dropped", value: null }
        : { kind: "kept", value: kept[0]! };
    expect(
      actual,
      `${one.id}: boundCategories([${JSON.stringify(one.input)}]) gave ` +
        `${JSON.stringify(actual)}, the shared cases say ` +
        `${JSON.stringify(one.browser)}.\n${one.why}`,
    ).toEqual(one.browser);
  });
});
