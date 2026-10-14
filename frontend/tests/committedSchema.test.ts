/**
 * @vitest-environment node
 *
 * Reads JSON; touches no DOM.
 */
/**
 * Tests for tests/committedSchema.ts: each refusal a rule leans on instead of
 * a floor of its own, driven over a document written here.
 */

import { describe, expect, it } from "vitest";

import {
  boundOf,
  branchesOf,
  committedSchema,
  objectsIn,
  operationById,
  parametersOf,
  propertiesOf,
  responseOf,
  type Document,
} from "./committedSchema";

/** A document with one of each shape a rule could otherwise read past. */
const DOCUMENT = {
  paths: {
    "/books": {
      get: {
        operationId: "list_books",
        parameters: [
          { name: "q", in: "query", schema: { type: "string" } },
          { $ref: "#/components/parameters/Tag" },
        ],
        responses: { "200": { $ref: "#/components/responses/Listing" } },
      },
    },
    "/twice": {
      get: { operationId: "twice", responses: {} },
      post: { operationId: "twice", responses: {} },
    },
  },
  components: {
    parameters: {
      Tag: { name: "tag", in: "query", schema: { type: "integer" } },
    },
    responses: {
      Listing: {
        description: "the books",
        content: { "application/json": { schema: { type: "array" } } },
      },
    },
    schemas: {
      Width: { type: "string", maxLength: 9 },
      Book: {
        type: "object",
        properties: {
          width: {
            anyOf: [{ $ref: "#/components/schemas/Width" }, { type: "null" }],
          },
        },
      },
      Composed: { allOf: [{ $ref: "#/components/schemas/Book" }] },
      Empty: { type: "object" },
      Loose: { type: "integer", exclusiveMaximum: 9 },
    },
  },
} as unknown as Document;

describe("the committed schema", () => {
  it("reads the committed document", () => {
    expect(Object.keys(committedSchema().paths).length).toBeGreaterThan(0);
  });

  it("finds an operation by id only where exactly one declares it", () => {
    expect(operationById("list_books", DOCUMENT).path).toBe("/books");
    expect(() => operationById("twice", DOCUMENT)).toThrow("2 operations");
    expect(() => operationById("absent", DOCUMENT)).toThrow("0 operations");
  });

  it("follows a parameter declared by reference rather than dropping it", () => {
    const { operation } = operationById("list_books", DOCUMENT);

    expect(parametersOf(operation, DOCUMENT).map((one) => one["name"])).toEqual(
      ["q", "tag"],
    );
  });

  it("refuses a reference to nothing", () => {
    const operation = {
      operationId: "x",
      parameters: [{ $ref: "#/components/parameters/Gone" }],
      responses: {},
    };

    expect(() => parametersOf(operation, DOCUMENT)).toThrow(
      "a $ref to nothing",
    );
  });

  it("reads a bound through a nullable field's referenced branch", () => {
    const width = propertiesOf("Book", DOCUMENT)["width"]!;

    expect(branchesOf(width, "width", DOCUMENT)).toHaveLength(1);
    expect(boundOf(width, "maxLength", "width", DOCUMENT)).toBe(9);
  });

  it("refuses a keyword it does not model, naming where it sits", () => {
    expect(() =>
      branchesOf({ type: "integer", exclusiveMinimum: 0 }, "Here", DOCUMENT),
    ).toThrow("Here: no reader of the schema models exclusiveMinimum");
    // On the schema a branch points at, which the field itself does not show.
    const referenced = {
      anyOf: [{ $ref: "#/components/schemas/Loose" }, { type: "null" }],
    };
    expect(() => branchesOf(referenced, "There", DOCUMENT)).toThrow(
      "There|0: no reader of the schema models exclusiveMaximum",
    );
  });

  it("refuses a schema whose fields sit behind a composition keyword", () => {
    expect(() => propertiesOf("Composed", DOCUMENT)).toThrow("allOf");
  });

  it("refuses a schema that declares no fields", () => {
    expect(() => propertiesOf("Empty", DOCUMENT)).toThrow(
      "Empty declares no fields",
    );
  });

  it("refuses a nullable schema whose fields sit behind its anyOf", () => {
    // `anyOf` is modelled, so it is not refused by name: this check is what
    // stops a nullable wrapper reading as an object with no fields.
    const nullable = {
      anyOf: [{ $ref: "#/components/schemas/Book" }, { type: "null" }],
    };
    expect(() => propertiesOf(nullable, DOCUMENT)).toThrow(
      "a schema declares no fields",
    );
  });

  it("reaches an object held in a list inside another object", () => {
    const inner = { format: "date" };
    const objects = objectsIn({ anyOf: [{ items: inner }, "text", null] });

    expect(objects).toHaveLength(3);
    expect(objects).toContain(inner);
  });

  it("follows a response declared by reference to where it is declared", () => {
    const declared = responseOf(
      operationById("list_books", DOCUMENT),
      "200",
      DOCUMENT,
    );

    expect(declared?.response.content).toHaveProperty("application/json");
    expect(declared?.pointer).toBe("components/responses/Listing");
  });
});
