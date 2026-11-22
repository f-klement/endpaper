/**
 * The TypeScript side of the shared accession number conformance suite.
 *
 * The cases live in `conformance/cases/accession.json`, and
 * `backend/tests/conformance/test_accession.py` runs the same file. A runner
 * holding no accession expectation of its own, guarded as `isbn.test.ts` is,
 * whose docblock says what each guard stops.
 *
 * **And it holds the camera's half of ticket 26's symbology guard**:
 * `ACCESSION_FORMATS` against the file's `symbologies`, while the Python runner
 * holds what the server prints to the same list. `conformance/accession.md`
 * says why a mismatch has to fail at build time.
 *
 * Not in the node environment, unlike `isbn.test.ts`: the formats live in a
 * component module, which this file imports. So the paths are joined onto
 * `import.meta.dirname`, since under happy-dom `import.meta.url` is no `file:`
 * URL and `fileURLToPath` throws.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { BarcodeFormat } from "@zxing/library";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";

import * as mirrored from "../../src/lib/accession";
import { classify, isAccession, mint } from "../../src/lib/accession";
import { ACCESSION_FORMATS } from "../../src/pages/ScanPage/components/BarcodeScanner";

const CASES_PATH = join(
  import.meta.dirname,
  "../../../conformance/cases/accession.json",
);
const SCHEMA_PATH = join(
  import.meta.dirname,
  "../../../conformance/schema/accession.schema.json",
);

type Case = {
  id: string;
  op: string;
  input: string | number;
  expect: string | boolean;
  why: string;
};

/** The schema's per operation input rule, checked a second time in code. */
function requireString(value: string | number, op: string): string {
  if (typeof value !== "string") {
    throw new Error(`${op} takes a string, and this case gives ${value}`);
  }
  return value;
}

function requireNumber(value: string | number, op: string): number {
  if (typeof value !== "number") {
    throw new Error(`${op} takes a row id, and this case gives a string`);
  }
  return value;
}

const OPERATIONS: Record<string, (input: string | number) => string | boolean> =
  {
    mint: (input) => mint(requireNumber(input, "mint")),
    "is-accession": (input) =>
      isAccession(requireString(input, "is-accession")),
    classify: (input) => classify(requireString(input, "classify")),
  };

/**
 * The case file's spelling of a symbology, onto the camera library's.
 *
 * **Typed against the real library**: `tsc` resolves `@zxing/library` to its
 * own declarations, since the suite's alias is vitest's alone, so a value that
 * names no ZXing format is a type error. At run time the import is the double
 * in `tests/doubles/zxing.ts`, which carries the same keys.
 */
const ZXING_NAME: Record<string, keyof typeof BarcodeFormat> = {
  code128: "CODE_128",
  code39: "CODE_39",
};

/** A floor, not a count: `isbn.test.ts` says why. Kept with the Python runner's. */
const MINIMUM_CASES = 15;

function read(path: string, what: string): unknown {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as unknown;
  } catch (cause) {
    throw new Error(
      `conformance ${what} missing or unreadable: ${path}. This suite refuses ` +
        `to pass by running none of the shared cases. (${String(cause)})`,
      { cause },
    );
  }
}

function load(): {
  cases: Case[];
  symbologies: string[];
  operations: string[];
} {
  const document = read(CASES_PATH, "case file") as {
    cases: Case[];
    symbologies: string[];
  };
  const schema = read(SCHEMA_PATH, "schema") as {
    $defs: { operation: { enum: string[] } };
  };
  // Strict mode on: `isbn.test.ts` measured it as the only detector of a
  // typoed schema keyword either runner has.
  const validate = new Ajv2020({
    allErrors: true,
    allowUnionTypes: true,
  }).compile(schema);
  if (!validate(document)) {
    const detail = (validate.errors ?? [])
      .map(
        (error) => `  at ${error.instancePath || "<root>"}: ${error.message}`,
      )
      .join("\n");
    throw new Error(
      `${CASES_PATH} does not match accession.schema.json:\n${detail}`,
    );
  }
  const identifiers = document.cases.map((one) => one.id);
  const duplicates = identifiers.filter(
    (id, at) => identifiers.indexOf(id) !== at,
  );
  if (duplicates.length > 0) {
    throw new Error(
      `duplicate case ids in ${CASES_PATH}: ${duplicates.join(", ")}`,
    );
  }
  return {
    cases: document.cases,
    symbologies: document.symbologies,
    operations: schema.$defs.operation.enum,
  };
}

const { cases, symbologies, operations } = load();

describe("the accession case file is worth running", () => {
  it("carries enough cases to be a specification", () => {
    expect(cases.length).toBeGreaterThanOrEqual(MINIMUM_CASES);
  });

  it("names every operation this runner wires, and no others", () => {
    expect([...operations].toSorted()).toEqual(
      Object.keys(OPERATIONS).toSorted(),
    );
  });

  it("exercises every operation with at least one case", () => {
    expect([...new Set(cases.map((one) => one.op))].toSorted()).toEqual(
      Object.keys(OPERATIONS).toSorted(),
    );
  });

  it("wires every function the mirrored module exports", () => {
    // `isbn.test.ts` says why this closes the loop the two checks above leave
    // open: a function in both implementations with no case.
    const wired = new Set<unknown>([mint, isAccession, classify]);
    const exported = Object.entries(mirrored).filter(
      ([, value]) => typeof value === "function",
    );
    expect(exported.length).toBeGreaterThan(0);
    expect(
      exported.filter(([, value]) => !wired.has(value)).map(([name]) => name),
    ).toEqual([]);
  });
});

describe("what the camera reads is what the server prints", () => {
  it("reads every symbology the case file says a label may carry, and no other", () => {
    // A symbology missing from ZXING_NAME is undefined here, so it fails too
    // rather than being dropped from the comparison.
    const expected = symbologies.map((name) => {
      const zxing = ZXING_NAME[name];
      return zxing === undefined ? `unmapped ${name}` : BarcodeFormat[zxing];
    });
    expect(expected.length).toBeGreaterThan(0);
    expect([...ACCESSION_FORMATS].map(String).toSorted()).toEqual(
      expected.map(String).toSorted(),
    );
  });
});

describe("shared accession conformance cases", () => {
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
