/**
 * @vitest-environment node
 *
 * Draws and validates; touches no DOM.
 */
/**
 * Tests for tests/lib/schemaArbitrary.ts: the deriver draws what the
 * committed schema permits, and refuses what it cannot read.
 *
 * **Held against a second reader of the same document**: ajv, a JSON Schema
 * validator that knows nothing of the deriver. A deriver that loosened a
 * bound would draw a value ajv refuses, which is a red here rather than a
 * page property failing over a response no server could send.
 */

import Ajv2020 from "ajv/dist/2020";
import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { holds, PROFILE, PROPERTY, witness } from "../property";
import {
  AtBound,
  anonymousOperations,
  answersOf,
  arbitraryOf,
  operationAt,
  operationIds,
  schemaDocument,
  SESSION_KEY,
  SESSION_TOKEN,
  spelledOut,
  undrawable,
  type Answer,
} from "./schemaArbitrary";

/** Where ajv files the document, so a `$ref` inside it resolves against it. */
const BASE = "https://endpaper.invalid/openapi.json";

/** RFC 3339's `date-time`, written here rather than taken from the deriver. */
const DATE_TIME =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

const ajv = new Ajv2020({ strict: false });
ajv.addFormat("date-time", DATE_TIME);
ajv.addFormat("date", /^\d{4}-\d{2}-\d{2}$/);
ajv.addSchema(schemaDocument() as object, BASE);

/** A JSON pointer's token for `key`. */
function token(key: string): string {
  return key.replaceAll("~", "~0").replaceAll("/", "~1");
}

/** The path and method an operation id is declared under. */
function addressOf(operationId: string): [string, string] {
  for (const [path, methods] of Object.entries(schemaDocument().paths)) {
    for (const [method, one] of Object.entries(methods)) {
      if (one.operationId === operationId) return [path, method];
    }
  }
  throw new Error(`no operation ${operationId}`);
}

/** One compiled validator per response, since a compile walks every `$ref`. */
const validators = new Map<string, ReturnType<typeof ajv.compile>>();

/** What ajv says of `answer` as a response of `operationId`, or `null`. */
function refusal(operationId: string, answer: Answer): string | null {
  const [path, method] = addressOf(operationId);
  const declared = schemaDocument().paths[path]![method]!.responses;
  const response = declared[String(answer.status)];
  if (response === undefined) return `${answer.status} is not declared`;
  if (response.content === undefined) {
    return answer.body === undefined ? null : "a body where none is declared";
  }
  const pointer = [
    "paths",
    path,
    method,
    "responses",
    String(answer.status),
    "content",
    "application/json",
    "schema",
  ]
    .map(token)
    .join("/");
  const validate =
    validators.get(pointer) ?? ajv.compile({ $ref: `${BASE}#/${pointer}` });
  validators.set(pointer, validate);
  // What the page is handed is what survives JSON, so that is what is judged.
  const body: unknown = JSON.parse(JSON.stringify(spelledOut(answer.body)));
  return validate(body) ? null : ajv.errorsText(validate.errors);
}

/** Whether `value` holds a `null` anywhere. */
function holdsNull(value: unknown): boolean {
  if (value === null) return true;
  if (typeof value !== "object") return false;
  return Object.values(value).some(holdsNull);
}

/** Whether `value` holds a string drawn at its `maxLength`, anywhere. */
function holdsAtBound(value: unknown): boolean {
  if (value instanceof AtBound) return true;
  if (typeof value !== "object" || value === null) return false;
  return Object.values(value).some(holdsAtBound);
}

/** A tag id's declared maximum, read off the document. */
function tagIdBound(): number {
  const match = schemaDocument().components.schemas["BookMatch"] as {
    properties: { suggested_tag_ids: { items: { maximum: number } } };
  };
  return match.properties.suggested_tag_ids.items.maximum;
}

/** Whether a list of enrichment candidates suggests a tag id at its bound. */
function holdsTagIdAtBound(body: unknown): boolean {
  if (!Array.isArray(body)) return false;
  return body.some((match: { suggested_tag_ids?: unknown }) =>
    (Array.isArray(match.suggested_tag_ids)
      ? match.suggested_tag_ids
      : []
    ).includes(tagIdBound()),
  );
}

/** Every string under `SESSION_KEY` in `value`, however deep. */
function sessionsIn(value: unknown): unknown[] {
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, each]) =>
    key === SESSION_KEY ? [each] : sessionsIn(each),
  );
}

const DRAWABLE = operationIds().filter((id) => !undrawable().includes(id));

/** An operation of the document, and one answer it declares. */
const ANY_ANSWER = fc
  .constantFrom(...DRAWABLE)
  .chain((operationId) =>
    answersOf(operationId).map((answer) => ({ operationId, answer })),
  );

describe("the schema deriver", () => {
  it("derives an answer for every operation", () => {
    for (const operationId of DRAWABLE) answersOf(operationId);
    expect(undrawable()).toEqual([]);
  });

  it(
    "draws an operation whose only success is a file at its refusals alone",
    PROPERTY,
    async () => {
      // The backup's 200 is a zip, which the deriver skips; its 401 and 403
      // are JSON, which it draws.
      expect(
        await holds(answersOf("download_backup"), async (answer) => {
          expect(answer.status).toBeGreaterThanOrEqual(400);
        }),
      ).toBe(PROFILE.runs);
    },
  );

  it("refuses a keyword it does not read, naming where it sits", () => {
    expect(() =>
      arbitraryOf({ type: "integer", exclusiveMinimum: 0 }, "Here/count"),
    ).toThrow("Here/count: the deriver does not read exclusiveMinimum");
  });

  it("refuses a format beside a length, which it would otherwise drop", () => {
    expect(() =>
      arbitraryOf({ type: "string", format: "date", minLength: 1 }, "Here"),
    ).toThrow("a format beside another string bound");
  });

  it("refuses an assertion beside a $ref, which it would otherwise drop", () => {
    expect(() =>
      arbitraryOf(
        { $ref: "#/components/schemas/TagOut", maxLength: 3 },
        "Here",
      ),
    ).toThrow("Here: $ref beside maxLength");
  });

  it(
    "draws every session token a sign in or a registration carries as a SESSION_TOKEN",
    PROPERTY,
    async () => {
      const carried = fc
        .oneof(answersOf("login"), answersOf("register"))
        .map((answer) => sessionsIn(answer.body));
      expect(
        await holds(
          carried,
          async (tokens) => {
            for (const each of tokens) expect(each).toMatch(SESSION_TOKEN);
          },
          { "carried a token": (tokens) => tokens.length > 0 },
        ),
      ).toBe(PROFILE.runs);
    },
  );

  it("refuses a session token whose node asserts more than a string", () => {
    expect(() =>
      arbitraryOf(
        {
          type: "object",
          properties: { [SESSION_KEY]: { type: "string", maxLength: 8 } },
        },
        "Here",
      ),
    ).toThrow(`Here/${SESSION_KEY}: a session token that is not a bare string`);
  });

  it("finds the operation a request is for, the literal path first", () => {
    expect(operationAt("GET", "/api/books/tags")).toBe("list_tags");
    expect(operationAt("GET", "/api/books?page=1&page_size=24")).toBe(
      "list_books",
    );
    expect(operationAt("GET", "/api/books/12")).toBe("get_book");
    expect(operationAt("DELETE", "/api/nowhere")).toBeUndefined();
  });

  it("draws an error body, a null and an empty list among its answers", async () => {
    await witness(ANY_ANSWER, {
      "is an error body": ({ answer }) => answer.status >= 400,
      "holds a null": ({ answer }) => holdsNull(answer.body),
      "is an empty list": ({ answer }) =>
        Array.isArray(answer.body) && answer.body.length === 0,
    });
  });

  it("draws a string at its maxLength", async () => {
    // Every field of an enrichment candidate declares one.
    await witness(answersOf("enrichment_candidates"), {
      "holds a string at its bound": (answer) => holdsAtBound(answer.body),
    });
  });

  it("draws an integer at a declared bound past the safe range", async () => {
    // A tag id's declared maximum is the largest signed 64 bit integer, which
    // the drawn range is clamped short of; only the edge reaches it.
    expect(tagIdBound()).toBeGreaterThan(Number.MAX_SAFE_INTEGER);
    await witness(answersOf("enrichment_candidates"), {
      "suggests a tag id at its declared maximum": (answer) =>
        holdsTagIdAtBound(answer.body),
    });
  });

  it(
    "draws only answers the document permits, as ajv reads it",
    PROPERTY,
    async () => {
      expect(
        await holds(ANY_ANSWER, async ({ operationId, answer }) => {
          expect(refusal(operationId, answer)).toBeNull();
        }),
      ).toBe(PROFILE.runs);
    },
  );
});

/** A document of one open operation and one that asks for a sign in. */
function opening(security: readonly Record<string, unknown>[]) {
  return {
    paths: {
      "/open": { get: { operationId: "open", security, responses: {} } },
      "/closed": {
        get: {
          operationId: "closed",
          security: [{ OAuth2PasswordBearer: [] }],
          responses: {},
        },
      },
    },
    components: { schemas: {} },
  };
}

describe("which operations a visitor with no account may call", () => {
  it("counts an operation open whose security is an empty list", () => {
    expect([...anonymousOperations(opening([]))]).toEqual(["open"]);
  });

  it("counts an operation open that offers an empty requirement", () => {
    expect([
      ...anonymousOperations(opening([{ OAuth2PasswordBearer: [] }, {}])),
    ]).toEqual(["open"]);
  });
});
