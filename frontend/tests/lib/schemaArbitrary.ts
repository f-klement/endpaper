/**
 * Responses the committed schema permits, drawn from the schema itself.
 *
 * **Derived from `openapi.json`, never from a copy of it**, so an operation,
 * a field or a bound the backend adds reaches every property here the day
 * the client is regenerated. Read the way `lib/bookBounds.test.ts` reads it.
 *
 * **The subset of JSON Schema this reads is the subset the document uses,
 * and a keyword outside it is refused by name** rather than ignored: an
 * ignored `exclusiveMinimum` or `const` would draw values the schema forbids,
 * and a red over one of them would be the deriver's fault and read as the
 * page's. `tests/lib/schemaArbitrary.test.ts` builds every response the
 * document declares, so a keyword added to it reds there first.
 *
 * **What it draws beyond the backend's habits, deliberately**: an optional
 * field absent, though FastAPI always writes one; a nullable null; a string
 * at its `maxLength` and an integer at a declared bound; a list empty; and
 * every status a response declares, the error bodies included. What the
 * schema permits is the property's question, not what the server happens to
 * send today. And now and then a plain string as a `DISTINCT` marker, which a
 * reach can find on a page without the page's own words finding it first.
 *
 * **What it leaves out, stated**: a status the document does not declare,
 * such as a 404 or a 500 a route raises, because the schema permits nothing
 * about it; a response whose only body is not JSON, which no page reads
 * through a hook; and properties a schema does not name, which JSON Schema
 * permits and nothing in the client reads. A `format` is honoured as the
 * API's contract, RFC 3339, though the standard makes it an annotation.
 * **A session token is only ever a `SESSION_TOKEN`**, never short or empty,
 * though the schema bounds it by nothing: the oracle refuses any piece of one
 * shown on a page, and a short token is spelled by the page's own words, as
 * a drawn `name` is in "Username".
 */

import fc from "fast-check";

import { spelled, type Repeated } from "../property";

/** As much of a JSON Schema node as the deriver reads. */
export type SchemaNode = Readonly<Record<string, unknown>>;

interface Operation {
  readonly operationId: string;
  /** Who may call it; absent where anybody may. */
  readonly security?: readonly Readonly<Record<string, unknown>>[];
  readonly responses: Readonly<
    Record<
      string,
      { readonly content?: Readonly<Record<string, { schema?: SchemaNode }>> }
    >
  >;
}

interface Document {
  /** A default every operation without its own would inherit. */
  readonly security?: unknown;
  readonly paths: Readonly<Record<string, Readonly<Record<string, Operation>>>>;
  readonly components: {
    readonly schemas: Readonly<Record<string, SchemaNode>>;
  };
}

const SCHEMA = import.meta.glob("../../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

let parsed: Document | undefined;

/** The committed document, parsed once. */
export function schemaDocument(): Document {
  const raw = SCHEMA["../../openapi.json"] ?? "";
  // A glob matching nothing would leave no operation to draw for, and every
  // property over it green over an empty subject.
  if (raw.length < 1000) throw new Error("openapi.json was not read");
  parsed ??= JSON.parse(raw) as Document;
  return parsed;
}

/** Keywords that say nothing about what a value may be. */
const ANNOTATIONS = new Set([
  "title",
  "description",
  "default",
  "contentMediaType",
]);

/** Keywords the deriver honours, which is every one the document uses. */
const ASSERTIONS = new Set([
  "$ref",
  "anyOf",
  "enum",
  "type",
  "properties",
  "required",
  "additionalProperties",
  "items",
  "minimum",
  "maximum",
  "minLength",
  "maxLength",
  "minItems",
  "maxItems",
  "pattern",
  "format",
]);

/** The keywords that stand alone: nothing else may assert beside them. */
const ALONE = ["$ref", "anyOf"];

/**
 * How long a list grows where the schema sets no bound. A list at a declared
 * `maxItems` is still drawn at that length, whatever this says.
 */
const LIST_CAP = 4;

/** The widest integer a JSON number carries exactly. */
const SAFE = Number.MAX_SAFE_INTEGER;

/** The key a session token is carried under, in `Token`. */
export const SESSION_KEY = "access_token";

/**
 * Every session token drawn: a prefix no page's words spell and 32 hex
 * digits, so any ten characters of one cannot occur on a page by chance.
 */
export const SESSION_TOKEN = /^session_[0-9a-f]{32}$/u;

/**
 * A string drawn to be found again: a prefix and eight hex digits, which no
 * page's own words spell, so a page showing one showed what it was sent.
 */
export const DISTINCT = /^drawn_[0-9a-f]{8}$/u;

/** How long a `DISTINCT` marker is, for the bounds it must fit. */
const DISTINCT_LENGTH = "drawn_".length + 8;

/** The instants RFC 3339 can spell: four digit years, zero to 9999. */
const EARLIEST = new Date("0000-01-01T00:00:00.000Z");
const LATEST = new Date("9999-12-31T23:59:59.999Z");

const refs = new Map<string, fc.Arbitrary<unknown>>();
const building = new Set<string>();

function numberAt(node: SchemaNode, key: string): number | undefined {
  const value = node[key];
  if (value === undefined) return undefined;
  if (typeof value !== "number") throw new Error(`${key} is not a number`);
  return value;
}

/** A declared bound, or nothing: an edge only where the schema drew one. */
function declared(...bounds: (number | undefined)[]): number[] {
  return bounds.filter((bound): bound is number => bound !== undefined);
}

/** `arbitrary`, and now and then exactly one of `edges`. */
function withEdges<T>(arbitrary: fc.Arbitrary<T>, edges: T[]): fc.Arbitrary<T> {
  if (edges.length === 0) return arbitrary;
  return fc.oneof(
    { arbitrary, weight: 3 },
    { arbitrary: fc.constantFrom(...edges), weight: 1 },
  );
}

function integerOf(node: SchemaNode): fc.Arbitrary<number> {
  const min = numberAt(node, "minimum");
  const max = numberAt(node, "maximum");
  // Clamped to what a double holds exactly: a bound past it, such as the
  // largest signed 64 bit integer an id column declares, made fast-check
  // draw over a range it cannot represent and never return. The bound itself
  // is still drawn as an edge, as the double JSON parsing makes of it.
  return withEdges(
    fc.integer({
      min: Math.max(Math.ceil(min ?? -SAFE), -SAFE),
      max: Math.min(Math.floor(max ?? SAFE), SAFE),
    }),
    declared(min, max),
  );
}

function numberOf(node: SchemaNode): fc.Arbitrary<number> {
  const min = numberAt(node, "minimum");
  const max = numberAt(node, "maximum");
  return withEdges(
    fc.double({
      min: min ?? -Number.MAX_VALUE,
      max: max ?? Number.MAX_VALUE,
      noNaN: true,
      noDefaultInfinity: true,
    }),
    declared(min, max),
  );
}

/** How many code points `text` holds, which is what `maxLength` counts. */
function codePoints(text: string): number {
  return [...text].length;
}

function stringOf(node: SchemaNode): fc.Arbitrary<string | AtBound> {
  const minLength = numberAt(node, "minLength") ?? 0;
  const maxLength = numberAt(node, "maxLength");
  const format = node["format"];
  const pattern = node["pattern"];
  if (format !== undefined) {
    if (
      pattern !== undefined ||
      node["maxLength"] !== undefined ||
      node["minLength"] !== undefined
    ) {
      throw new Error("a format beside another string bound");
    }
    const instants = withEdges(
      fc.date({ min: EARLIEST, max: LATEST, noInvalidDate: true }),
      [EARLIEST, LATEST],
    ).map((instant) => instant.toISOString());
    if (format === "date-time") return instants;
    if (format === "date") return instants.map((text) => text.slice(0, 10));
    throw new Error(`the format ${String(format)}`);
  }
  if (pattern !== undefined) {
    if (typeof pattern !== "string") throw new Error("a pattern not a string");
    return fc
      .stringMatching(new RegExp(pattern, "u"), { maxLength })
      .filter((text) => codePoints(text) >= minLength);
  }
  // Code points by unit, so a length here is a length `maxLength` counts:
  // ASCII mostly, the whole of Unicode outside the surrogates sometimes.
  const drawn = fc.oneof(
    {
      arbitrary: fc.string({ unit: "binary-ascii", minLength, maxLength }),
      weight: 3,
    },
    {
      arbitrary: fc.string({ unit: "binary", minLength, maxLength }),
      weight: 1,
    },
  );
  // A marker only where the bounds admit its length.
  const some =
    minLength <= DISTINCT_LENGTH && (maxLength ?? Infinity) >= DISTINCT_LENGTH
      ? fc.oneof(
          { arbitrary: drawn, weight: 3 },
          { arbitrary: fc.stringMatching(DISTINCT), weight: 1 },
        )
      : drawn;
  if (maxLength === undefined || maxLength === 0) return some;
  return fc.oneof(
    { arbitrary: some, weight: 3 },
    {
      arbitrary: fc
        .string({ unit: "binary", minLength: 1, maxLength: 1 })
        .map((unit) => new AtBound(unit, maxLength)),
      weight: 1,
    },
  ) as fc.Arbitrary<string | AtBound>;
}

/** Whether `node` is a string and asserts nothing else. */
function bareString(node: SchemaNode): boolean {
  const asserted = Object.keys(node).filter((key) => !ANNOTATIONS.has(key));
  return asserted.length === 1 && node["type"] === "string";
}

/**
 * A session token, from its node. **Refused unless the node is a bare
 * string**: a bound added to `Token` later would make some `SESSION_TOKEN`
 * one the schema forbids, and this would draw it.
 */
function sessionOf(node: SchemaNode, where: string): fc.Arbitrary<string> {
  if (!bareString(node)) {
    throw new Error(`${where}: a session token that is not a bare string`);
  }
  return fc.stringMatching(SESSION_TOKEN);
}

/**
 * A string at its `maxLength`, named rather than spelled: one code point,
 * repeated. **So a counterexample prints as four short fields**, where ten
 * thousand code points would print as themselves, which `docs/testing.md`
 * refuses to land. `spelledOut` turns one into the string a server would
 * send.
 */
export class AtBound implements Repeated {
  readonly before = "";
  readonly after = "";

  constructor(
    readonly unit: string,
    readonly times: number,
  ) {}
}

/** `value` with every `AtBound` in it spelled, which is what a page is sent. */
export function spelledOut(value: unknown): unknown {
  if (value instanceof AtBound) return spelled(value);
  if (Array.isArray(value)) return value.map(spelledOut);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, each]) => [key, spelledOut(each)]),
    );
  }
  return value;
}

function arrayOf(node: SchemaNode, where: string): fc.Arbitrary<unknown[]> {
  const items = node["items"];
  if (items === undefined) throw new Error(`${where}: a list of no items`);
  const each = arbitraryOf(items as SchemaNode, `${where}/items`);
  const minLength = numberAt(node, "minItems") ?? 0;
  const maxItems = numberAt(node, "maxItems");
  const some = fc.array(each, {
    minLength,
    maxLength: Math.max(minLength, Math.min(maxItems ?? LIST_CAP, LIST_CAP)),
  });
  if (maxItems === undefined || maxItems <= LIST_CAP) return some;
  return fc.oneof(
    { arbitrary: some, weight: 3 },
    {
      arbitrary: fc.array(each, { minLength: maxItems, maxLength: maxItems }),
      weight: 1,
    },
  );
}

/** The named fields over the others, as one object. */
function merged([others, fields]: [
  Record<string, unknown>,
  Record<string, unknown>,
]): Record<string, unknown> {
  return { ...others, ...fields };
}

function objectOf(
  node: SchemaNode,
  where: string,
): fc.Arbitrary<Record<string, unknown>> {
  const properties = (node["properties"] ?? {}) as Record<string, SchemaNode>;
  const required = (node["required"] ?? []) as string[];
  for (const name of required) {
    if (!(name in properties)) throw new Error(`${where}: requires ${name}`);
  }
  const extra = node["additionalProperties"];
  const named = Object.keys(properties).length > 0;
  if (!named && extra === undefined) {
    // An object the schema says nothing about: any JSON object.
    return fc.dictionary(fc.string(), fc.jsonValue({ maxDepth: 1 }), {
      maxKeys: 3,
    });
  }
  const record = fc.record(
    Object.fromEntries(
      Object.entries(properties).map(([name, schema]) => [
        name,
        name === SESSION_KEY
          ? sessionOf(schema, `${where}/${name}`)
          : arbitraryOf(schema, `${where}/${name}`),
      ]),
    ),
    { requiredKeys: required },
  ) as fc.Arbitrary<Record<string, unknown>>;
  if (extra === undefined) return record;
  if (typeof extra !== "object" || extra === null) {
    throw new Error(`${where}: additionalProperties that is not a schema`);
  }
  const rest = fc.dictionary(
    fc.string().filter((key) => !(key in properties)),
    arbitraryOf(extra as SchemaNode, `${where}/additionalProperties`),
    { maxKeys: 3 },
  );
  return fc.tuple(rest, record).map(merged);
}

function refOf(ref: unknown, where: string): fc.Arbitrary<unknown> {
  const prefix = "#/components/schemas/";
  if (typeof ref !== "string" || !ref.startsWith(prefix)) {
    throw new Error(`${where}: a $ref outside the schemas, ${String(ref)}`);
  }
  const name = ref.slice(prefix.length);
  const known = refs.get(name);
  if (known !== undefined) return known;
  // A schema reaching itself would build forever. None does today; this says
  // so loudly the day one does, where `fc.letrec` would then be the fix.
  if (building.has(name)) throw new Error(`${where}: ${name} reaches itself`);
  const schema = schemaDocument().components.schemas[name];
  if (schema === undefined) throw new Error(`${where}: no schema ${name}`);
  building.add(name);
  try {
    const built = arbitraryOf(schema, name);
    refs.set(name, built);
    return built;
  } finally {
    building.delete(name);
  }
}

/**
 * Every value `node` permits, as an arbitrary. `where` names the node in a
 * refusal, so a keyword the deriver does not read is reported where it sits.
 */
export function arbitraryOf(
  node: SchemaNode,
  where: string,
): fc.Arbitrary<unknown> {
  const asserted = Object.keys(node).filter((key) => !ANNOTATIONS.has(key));
  for (const key of asserted) {
    if (!ASSERTIONS.has(key)) {
      throw new Error(`${where}: the deriver does not read ${key}`);
    }
  }
  for (const alone of ALONE) {
    if (alone in node && asserted.length > 1) {
      const others = asserted.filter((key) => key !== alone).join(", ");
      throw new Error(`${where}: ${alone} beside ${others}`);
    }
  }
  if ("$ref" in node) return refOf(node["$ref"], where);
  if ("anyOf" in node) {
    const branches = node["anyOf"] as SchemaNode[];
    return fc.oneof(
      ...branches.map((branch, at) => arbitraryOf(branch, `${where}|${at}`)),
    );
  }
  if ("enum" in node) {
    return fc.constantFrom(...(node["enum"] as unknown[]));
  }
  switch (node["type"]) {
    case undefined:
      // No type: any JSON value. FastAPI's `ValidationError.input` is one.
      return fc.jsonValue({ maxDepth: 2 });
    case "null":
      return fc.constant(null);
    case "boolean":
      return fc.boolean();
    case "integer":
      return integerOf(node);
    case "number":
      return numberOf(node);
    case "string":
      return stringOf(node);
    case "array":
      return arrayOf(node, where);
    case "object":
      return objectOf(node, where);
    default:
      throw new Error(`${where}: the type ${String(node["type"])}`);
  }
}

/** What a stubbed request answers: a status and, unless it has none, a body. */
export interface Answer {
  readonly status: number;
  readonly body?: unknown;
}

/** The operation an id names, refused when the document has none. */
function operation(operationId: string): Operation {
  for (const methods of Object.values(schemaDocument().paths)) {
    for (const found of Object.values(methods)) {
      if (found.operationId === operationId) return found;
    }
  }
  throw new Error(`openapi.json declares no operation ${operationId}`);
}

/**
 * The answers one operation's responses declare, without the ones this
 * cannot draw: a status that is not a number, and a body that is not JSON.
 */
function declaredAnswers(
  operationId: string,
): [number, fc.Arbitrary<Answer>][] {
  const answers: [number, fc.Arbitrary<Answer>][] = [];
  for (const [code, response] of Object.entries(
    operation(operationId).responses,
  )) {
    const status = Number(code);
    if (!Number.isInteger(status)) {
      throw new Error(`${operationId}: a response for ${code}`);
    }
    const content = response.content;
    if (content === undefined) {
      answers.push([status, fc.constant({ status })]);
      continue;
    }
    const json = content["application/json"];
    if (json === undefined) continue;
    answers.push([
      status,
      arbitraryOf(json.schema ?? {}, `${operationId} ${code}`).map((body) => ({
        status,
        body,
      })),
    ]);
  }
  return answers;
}

const answers = new Map<string, fc.Arbitrary<Answer>>();

/**
 * Every answer `operationId` declares, each success weighted three to an
 * error's one.
 *
 * **Memoised by id, which `fc.gen` needs**: it replays a draw by the builder
 * and its arguments, so the same id must hand back the same arbitrary.
 */
export function answersOf(operationId: string): fc.Arbitrary<Answer> {
  const known = answers.get(operationId);
  if (known !== undefined) return known;
  const declaredOnes = declaredAnswers(operationId);
  if (declaredOnes.length === 0) {
    throw new Error(`${operationId} declares no answer this can draw`);
  }
  const built = fc.oneof(
    ...declaredOnes.map(([status, arbitrary]) => ({
      arbitrary,
      weight: status < 400 ? 3 : 1,
    })),
  );
  answers.set(operationId, built);
  return built;
}

/** Every operation id the document declares. */
export function operationIds(): string[] {
  const ids = Object.values(schemaDocument().paths).flatMap((methods) =>
    Object.values(methods).map((one) => one.operationId),
  );
  ids.sort();
  return ids;
}

/**
 * The ids a visitor with no account may call: those whose `security` asks
 * for nothing, by being absent, empty, or offering an empty requirement.
 *
 * **Refused when the document sets a default `security`**, which an
 * operation with none of its own inherits: read here as absent, it would
 * hand every such operation to a stranger.
 *
 * Takes the document so each arm can be pinned over one written by hand: the
 * committed one has every open operation with the key absent, so the other
 * two arms are exercised nowhere else.
 */
export function anonymousOperations(
  document: Document = schemaDocument(),
): Set<string> {
  if (document.security !== undefined) {
    throw new Error("openapi.json sets a default security, which this ignores");
  }
  const anonymous = new Set<string>();
  for (const methods of Object.values(document.paths)) {
    for (const found of Object.values(methods)) {
      const security = found.security;
      if (
        security === undefined ||
        security.length === 0 ||
        security.some((requirement) => Object.keys(requirement).length === 0)
      ) {
        anonymous.add(found.operationId);
      }
    }
  }
  return anonymous;
}

/** The ids whose responses declare nothing `answersOf` can draw. */
export function undrawable(): string[] {
  return operationIds().filter((id) => declaredAnswers(id).length === 0);
}

interface Route {
  readonly method: string;
  /** The path's segments, a template one such as `{book_id}` as `null`. */
  readonly segments: readonly (string | null)[];
  readonly operationId: string;
}

let routes: Route[] | undefined;

/** How many segments of a route are spelled out rather than templated. */
function literal(route: Route): number {
  return route.segments.filter((segment) => segment !== null).length;
}

/**
 * The document's routes, the most literal first, so `/api/books/tags` is
 * matched before `/api/books/{book_id}` would take it.
 */
function routeTable(): Route[] {
  if (routes !== undefined) return routes;
  const table: Route[] = [];
  for (const [path, methods] of Object.entries(schemaDocument().paths)) {
    const segments = path
      .split("/")
      .map((segment) =>
        segment.startsWith("{") && segment.endsWith("}") ? null : segment,
      );
    for (const [method, found] of Object.entries(methods)) {
      table.push({
        method: method.toUpperCase(),
        segments,
        operationId: found.operationId,
      });
    }
  }
  table.sort((a, b) => literal(b) - literal(a));
  routes = table;
  return table;
}

/** Whether `path`, split, is one `route` declares. */
function matches(route: Route, path: readonly string[]): boolean {
  return (
    route.segments.length === path.length &&
    route.segments.every((segment, at) =>
      segment === null ? path[at] !== "" : segment === path[at],
    )
  );
}

/** The operation a request is for, by method and path, or `undefined`. */
export function operationAt(method: string, url: string): string | undefined {
  const path = new URL(url, "http://localhost").pathname.split("/");
  return routeTable().find(
    (route) => route.method === method.toUpperCase() && matches(route, path),
  )?.operationId;
}
