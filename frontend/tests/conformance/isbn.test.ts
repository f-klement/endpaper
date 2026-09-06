/**
 * @vitest-environment node
 *
 * The TypeScript side of the shared ISBN conformance suite.
 *
 * The cases live in `conformance/cases/isbn.json`, outside both language trees,
 * and `backend/tests/conformance/test_isbn.py` runs the same file against the
 * same expectations. `src/lib/isbn.ts` mirrors `backend/isbn.py` deliberately,
 * because the barcode scanner has to decide within a video frame whether what it
 * just read is a book and cannot ask the server. This file is what makes the
 * mirror claim checkable instead of aspirational: it was not true, and for
 * months nothing on either side would have said so.
 *
 * **A runner, holding no ISBN expectation of its own.** Every expectation about
 * an ISBN comes out of the case file; the only ISBN knowledge written here is
 * the mapping from a language neutral operation name onto this implementation's
 * spelling. What else is written here is the guards below, which are
 * expectations about the case file rather than about ISBNs. Adding a
 * case is editing JSON. Changing an expectation is changing the protocol, and
 * belongs in a commit that says so and that lands on both sides together.
 *
 * Three ways this could quietly stop testing anything, and what stops each:
 *
 * - **The case file is missing or emptied.** `load()` throws at module scope, so
 *   the file fails to collect and the suite fails. It never skips: a conformance
 *   suite that silently runs zero cases is the failure that makes this theatre.
 * - **The case file has drifted from the format.** Every file is validated
 *   against `conformance/schema/isbn.schema.json` before a single case runs.
 * - **This runner has drifted from the schema.** The dispatch table is compared
 *   against the schema's own list of operations, so an operation added to the
 *   specification and not wired here fails rather than going unexercised.
 *
 * Node environment rather than jsdom: this reads a file and calls pure
 * functions, and there is no DOM in it. **The pragma is in this docblock and
 * not in a `//` comment above it**, because `frontend/vite.config.ts` counts
 * the opt outs with a grep anchored on ` * @vitest-environment node`, and the
 * `//` spelling works in vitest while being invisible to that count.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";

import * as mirrored from "../../src/lib/isbn";
import {
  isValidIsbn,
  isValidIsbn10,
  isValidIsbn13,
  isbn10ToIsbn13,
  normalise,
  parseIsbn,
} from "../../src/lib/isbn";

// frontend/tests/conformance/isbn.test.ts -> the repository root.
const CASES_PATH = fileURLToPath(
  new URL("../../../conformance/cases/isbn.json", import.meta.url),
);
const SCHEMA_PATH = fileURLToPath(
  new URL("../../../conformance/schema/isbn.schema.json", import.meta.url),
);

type Case = {
  id: string;
  op: string;
  input: string | null;
  expect: string | boolean | null;
  why: string;
};

/**
 * A second, independent check that the schema's per operation input rule holds.
 *
 * Four of the six operations are not null safe on either side. The schema says
 * so with an `if`/`then` arm, and if that arm were deleted this would still
 * throw here rather than calling `normalise(null)` and reporting whatever came
 * back. Two guards on one rule, because the schema is data and this is code.
 */
function requireString(value: string | null, op: string): string {
  if (value === null) {
    throw new Error(`${op} takes a string, and this case gives a null input`);
  }
  return value;
}

// The operations, in the specification's spelling, mapped onto this
// implementation's. Written out rather than derived from the names: the point of
// the indirection is that neither language's naming owns the format.
const OPERATIONS: Record<
  string,
  (input: string | null) => string | boolean | null
> = {
  normalise: (input) => normalise(requireString(input, "normalise")),
  "is-valid-isbn10": (input) =>
    isValidIsbn10(requireString(input, "is-valid-isbn10")),
  "is-valid-isbn13": (input) =>
    isValidIsbn13(requireString(input, "is-valid-isbn13")),
  "isbn10-to-isbn13": (input) =>
    isbn10ToIsbn13(requireString(input, "isbn10-to-isbn13")),
  parse: (input) => parseIsbn(input),
  "is-valid": (input) => isValidIsbn(input),
};

// A floor, not a count, and it is here for the same reason `palettes.test.ts`
// asserts it has rows it can actually see: a loader that produced one case, or
// none, would make every assertion below vacuous while the suite stayed green.
// The schema's `minItems` rejects an empty array; this rejects a gutted file.
// Kept in step with the Python runner's MINIMUM_CASES by hand, and a mismatch
// costs nothing: the smaller of the two is the one that binds.
const MINIMUM_CASES = 20;

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

function load(): { cases: Case[]; operations: string[] } {
  const document = read(CASES_PATH, "case file") as { cases: Case[] };
  const schema = read(SCHEMA_PATH, "schema") as {
    $defs: { operation: { enum: string[] } };
  };

  // **Strict mode on, and it is the only detector of a typoed schema keyword
  // either runner has.** Measured 2026-09-06: with `minLength` spelled
  // `minLenght`, a case carrying a one character `why` validates clean under
  // `strict: false`, and Python misses it too, because an unknown keyword is
  // legal JSON Schema and `Draft202012Validator.check_schema` passes it. Strict
  // mode throws at compile. Both runners read this one schema, so one detector
  // failing the pipeline is enough. `allowUnionTypes` is what the `expect`
  // field's `["string", "boolean", "null"]` needs.
  const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true });
  const validate = ajv.compile(schema);
  if (!validate(document)) {
    const detail = (validate.errors ?? [])
      .map(
        (error) => `  at ${error.instancePath || "<root>"}: ${error.message}`,
      )
      .join("\n");
    throw new Error(
      `${CASES_PATH} does not match isbn.schema.json:\n${detail}`,
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
  return { cases: document.cases, operations: schema.$defs.operation.enum };
}

const { cases, operations } = load();

describe("the case file is worth running", () => {
  it("carries enough cases to be a specification", () => {
    expect(cases.length).toBeGreaterThanOrEqual(MINIMUM_CASES);
  });

  it("names every operation this runner wires, and no others", () => {
    expect([...operations].sort()).toEqual(Object.keys(OPERATIONS).sort());
  });

  it("wires every function the mirrored module exports", () => {
    // **The schema-to-dispatch-table check above is a closed loop.** Both sides
    // of it are edited in the same commit, so it says nothing about either
    // implementation: what it refuses is an operation nobody wired, and what it
    // lets through is a function exported by BOTH implementations with no
    // operation and no case, which is precisely the drift this directory exists
    // to stop.
    //
    // This closes it on the side where it closes exactly. `src/lib/isbn.ts`
    // exports the shared surface and nothing else, so a seventh export is a
    // rule that has grown a second implementation without a case.
    //
    // **Deliberately not mirrored on the Python side.** `backend/isbn.py` has
    // four functions with no TypeScript counterpart on purpose, so the same
    // check there needs a written list of what was chosen not to share, and
    // that list is the enumeration that goes stale. A function existing only in
    // Python cannot drift; one existing in TypeScript exists in Python too.
    const wired = new Set<unknown>([
      normalise,
      isValidIsbn10,
      isValidIsbn13,
      isbn10ToIsbn13,
      parseIsbn,
      isValidIsbn,
    ]);
    const exported = Object.entries(mirrored).filter(
      ([, value]) => typeof value === "function",
    );

    // Anti vacuity: a namespace import that resolved to nothing would make the
    // rule below pass for ever.
    expect(exported.length).toBeGreaterThan(0);
    expect(
      exported
        .filter(([, value]) => !wired.has(value))
        .map(([name]) => name)
        .sort(),
    ).toEqual([]);
  });

  it("exercises every operation with at least one case", () => {
    expect([...new Set(cases.map((one) => one.op))].sort()).toEqual(
      Object.keys(OPERATIONS).sort(),
    );
  });
});

describe("shared ISBN conformance cases", () => {
  // The `why` goes into the failure message because it is the only place the
  // reason for a case lives, and a failure here is a divergence between two
  // implementations rather than an ordinary broken test.
  it.each(cases)("$id", (one: Case) => {
    const actual = OPERATIONS[one.op]!(one.input);
    expect(
      actual,
      `${one.id}: ${one.op}(${JSON.stringify(one.input)}) gave ` +
        `${JSON.stringify(actual)}, the shared cases say ` +
        `${JSON.stringify(one.expect)}.\n${one.why}`,
    ).toEqual(one.expect);
  });
});
