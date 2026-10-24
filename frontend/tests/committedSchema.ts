/**
 * The committed `openapi.json`, read once, and the questions every test asks
 * of it.
 *
 * **One reader, because a reader written per rule reads its own subset and
 * goes blind outside it without saying so.** A rule that cast the document
 * to a partial type and skipped a `$ref` it did not follow saw an empty list
 * where a referenced one stood, and a comparison over an empty list passes.
 * So every question here either answers from the whole document or throws:
 *
 * | question | refused when |
 * |---|---|
 * | the document | the glob read nothing, which would leave every rule green over an empty subject |
 * | an operation by id | none or more than one declares it |
 * | what a `$ref` points at | it leaves the document or names nothing in it |
 * | a field's branches | a keyword below asserts what no reader here models |
 * | a schema's fields | it declares none, as a bare object, a map or an `anyOf` does |
 *
 * **The keywords modelled are the ones the document uses**, and a keyword
 * outside them is refused by name rather than ignored: an ignored
 * `exclusiveMinimum` is a bound a rule recomputing bounds never sees.
 * `tests/lib/schemaArbitrary.test.ts` builds every response the document
 * declares through `arbitraryOf`, which asks `refuseUnmodelled` of every node,
 * so a keyword added to a response reds there first.
 *
 * **`import.meta.glob` rather than `node:fs`**, so a reader running under
 * happy-dom, whose `URL` refuses a `file:` base, reads it the same way.
 * `houseRules.test.ts` refuses a second module that globs the document,
 * imports it, or names it in quotes beside a `readFileSync(` call.
 */

/** As much of a JSON Schema node as anything here reads. */
export type SchemaNode = Readonly<Record<string, unknown>>;

/** One operation, as much of it as the tests read. */
export interface Operation {
  readonly operationId: string;
  /** Who may call it; absent where anybody may. */
  readonly security?: readonly Readonly<Record<string, unknown>>[];
  readonly parameters?: readonly SchemaNode[];
  readonly requestBody?: SchemaNode;
  /** Each a response or a `$ref` to one: read it through `responseOf`. */
  readonly responses: Readonly<Record<string, SchemaNode>>;
}

/** One response, as much of it as the tests read. */
export interface DeclaredResponse {
  readonly headers?: Readonly<Record<string, unknown>>;
  readonly content?: Readonly<Record<string, { schema?: SchemaNode }>>;
}

export interface Document {
  /** A default every operation without its own would inherit. */
  readonly security?: unknown;
  readonly paths: Readonly<Record<string, Readonly<Record<string, Operation>>>>;
  readonly components: {
    readonly schemas: Readonly<Record<string, SchemaNode>>;
  };
}

const SCHEMA = import.meta.glob("../openapi.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

let parsed: Document | undefined;

/** The committed document, parsed once, refused when nothing was read. */
export function committedSchema(): Document {
  const raw = SCHEMA["../openapi.json"] ?? "";
  // Half a megabyte when present. Far below that is a glob that matched
  // nothing, and every rule over it green over an empty subject.
  if (raw.length < 1000) throw new Error("openapi.json was not read");
  parsed ??= JSON.parse(raw) as Document;
  return parsed;
}

/** One operation, with where it is declared. */
export interface Located {
  readonly path: string;
  readonly method: string;
  readonly operation: Operation;
}

/**
 * The operation `operationId` names, refused unless exactly one declares it:
 * the first of two would be a guess about which one a rule meant.
 */
export function operationById(
  operationId: string,
  document: Document = committedSchema(),
): Located {
  const found: Located[] = [];
  for (const [path, methods] of Object.entries(document.paths)) {
    for (const [method, operation] of Object.entries(methods)) {
      if (operation.operationId === operationId) {
        found.push({ path, method, operation });
      }
    }
  }
  if (found.length !== 1) {
    throw new Error(
      `openapi.json declares ${found.length} operations ${operationId}`,
    );
  }
  return found[0]!;
}

/** A JSON pointer token, unescaped. */
function unescaped(token: string): string {
  return token.replaceAll("~1", "/").replaceAll("~0", "~");
}

/** `key` as a JSON pointer token. */
export function escaped(key: string): string {
  return key.replaceAll("~", "~0").replaceAll("/", "~1");
}

/**
 * The node a local `$ref` points at, refused when it leaves the document or
 * names nothing in it.
 */
export function target(
  ref: unknown,
  document: Document = committedSchema(),
): SchemaNode {
  if (typeof ref !== "string" || !ref.startsWith("#/")) {
    throw new Error(`a $ref outside the document, ${String(ref)}`);
  }
  let node: unknown = document;
  for (const token of ref.slice(2).split("/").map(unescaped)) {
    node =
      typeof node === "object" && node !== null
        ? (node as Record<string, unknown>)[token]
        : undefined;
  }
  if (typeof node !== "object" || node === null) {
    throw new Error(`a $ref to nothing, ${ref}`);
  }
  return node as SchemaNode;
}

/**
 * `node`, found at the JSON pointer `pointer`, with any chain of `$ref`
 * followed: what it lands on, and the pointer of that.
 */
function followed(
  node: SchemaNode,
  pointer: string,
  document: Document,
): [SchemaNode, string] {
  let at = node;
  let where = pointer;
  const seen = new Set<unknown>();
  while ("$ref" in at) {
    const ref = at["$ref"];
    if (seen.has(ref)) {
      throw new Error(`a $ref that reaches itself, ${String(ref)}`);
    }
    seen.add(ref);
    at = target(ref, document);
    where = (ref as string).slice(2);
  }
  return [at, where];
}

/**
 * `node`, with any chain of `$ref` followed to what it points at.
 *
 * Annotations beside a `$ref` are dropped with it; anything asserting beside
 * one is refused by `refuseUnmodelled` before it could be.
 */
export function resolved(
  node: SchemaNode,
  document: Document = committedSchema(),
): SchemaNode {
  return followed(node, "", document)[0];
}

/**
 * The response `located` declares for `status`, a `$ref` followed, and the
 * JSON pointer it is declared at; `undefined` where it declares none.
 *
 * **The one way to read a response**: one declared by `$ref` carries no
 * `content` of its own, so a raw read takes it for a response with no body.
 */
export function responseOf(
  located: Located,
  status: string,
  document: Document = committedSchema(),
):
  | { readonly response: DeclaredResponse; readonly pointer: string }
  | undefined {
  const declared = located.operation.responses[status];
  if (declared === undefined) return undefined;
  const pointer = ["paths", located.path, located.method, "responses", status]
    .map(escaped)
    .join("/");
  const [response, at] = followed(declared, pointer, document);
  return { response: response as DeclaredResponse, pointer: at };
}

/** Keywords that say nothing about what a value may be. */
const ANNOTATIONS = new Set([
  "title",
  "description",
  "default",
  "contentMediaType",
]);

/** Keywords the readers here model, which is every one the document uses. */
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

/** The keys of `node` that assert something about a value. */
export function assertedKeys(node: SchemaNode): string[] {
  return Object.keys(node).filter((key) => !ANNOTATIONS.has(key));
}

/**
 * Refuses `node` when it asserts with a keyword nothing here models, or
 * asserts beside a `$ref` or an `anyOf`. `where` names the node in the error.
 */
export function refuseUnmodelled(node: SchemaNode, where: string): void {
  const asserted = assertedKeys(node);
  for (const key of asserted) {
    if (!ASSERTIONS.has(key)) {
      throw new Error(`${where}: no reader of the schema models ${key}`);
    }
  }
  for (const alone of ALONE) {
    if (alone in node && asserted.length > 1) {
      const others = asserted.filter((key) => key !== alone).join(", ");
      throw new Error(`${where}: ${alone} beside ${others}`);
    }
  }
}

/**
 * The branches of a field that are not its null, each resolved.
 *
 * A nullable field is `anyOf: [{the real thing}, {"type": "null"}]`, and the
 * real thing may itself be a `$ref`. Every node on the way is refused when it
 * asserts what this does not model.
 */
export function branchesOf(
  field: SchemaNode,
  where = "a field",
  document: Document = committedSchema(),
): SchemaNode[] {
  refuseUnmodelled(field, where);
  const node = resolved(field, document);
  refuseUnmodelled(node, where);
  if (!("anyOf" in node)) return node["type"] === "null" ? [] : [node];
  return (node["anyOf"] as SchemaNode[]).flatMap((branch, at) =>
    branchesOf(branch, `${where}|${at}`, document),
  );
}

/**
 * The number `keyword` states on a field, from whichever non null branch
 * states it, or `undefined` where none does.
 */
export function boundOf(
  field: SchemaNode,
  keyword: string,
  where = "a field",
  document: Document = committedSchema(),
): number | undefined {
  const stated = branchesOf(field, where, document)
    .map((branch) => branch[keyword])
    .filter((value) => value !== undefined);
  if (stated.length > 1) throw new Error(`${where}: two ${keyword} branches`);
  const [value] = stated;
  if (value !== undefined && typeof value !== "number") {
    throw new Error(`${where}: ${keyword} is not a number`);
  }
  return value;
}

/** `boundOf`, refused where no branch states the bound. */
export function statedBound(
  field: SchemaNode | undefined,
  keyword: string,
  where = "a field",
  document: Document = committedSchema(),
): number {
  if (field === undefined) throw new Error(`${where}: no such field`);
  const bound = boundOf(field, keyword, where, document);
  if (bound === undefined) throw new Error(`${where}: states no ${keyword}`);
  return bound;
}

/** The schema of a list field's entries, refused where the field is no list. */
export function itemsOf(
  field: SchemaNode,
  where = "a field",
  document: Document = committedSchema(),
): SchemaNode {
  const lists = branchesOf(field, where, document).filter(
    (branch) => branch["items"] !== undefined,
  );
  if (lists.length !== 1) throw new Error(`${where}: not one list branch`);
  return lists[0]!["items"] as SchemaNode;
}

/**
 * Every object in `value`, itself included, depth first through lists.
 *
 * What a rule over every declared field walks: a schema can sit under
 * `components`, inline in a body or a response, or inside a branch, and
 * walking the objects rather than those places reaches all of them.
 */
export function objectsIn(value: unknown): SchemaNode[] {
  const out: SchemaNode[] = [];
  const descend = (held: unknown): void => {
    if (Array.isArray(held)) {
      for (const item of held as unknown[]) descend(item);
      return;
    }
    if (typeof held !== "object" || held === null) return;
    out.push(held as SchemaNode);
    for (const child of Object.values(held)) descend(child);
  };
  descend(value);
  return out;
}

/**
 * The fields a schema declares, refused when it declares none, as a bare
 * `{"type": "object"}`, a map or an `anyOf` does: a comparison over no fields
 * passes. `allOf` and `oneOf` are refused by name before this.
 */
export function propertiesOf(
  schema: string | SchemaNode,
  document: Document = committedSchema(),
): Readonly<Record<string, SchemaNode>> {
  const where = typeof schema === "string" ? schema : "a schema";
  const named =
    typeof schema === "string"
      ? target(`#/components/schemas/${schema}`, document)
      : schema;
  refuseUnmodelled(named, where);
  const node = resolved(named, document);
  refuseUnmodelled(node, where);
  const properties = node["properties"] as
    | Readonly<Record<string, SchemaNode>>
    | undefined;
  if (properties === undefined || Object.keys(properties).length === 0) {
    throw new Error(`${where} declares no fields`);
  }
  return properties;
}

/** The fields a schema requires. */
export function requiredOf(
  schema: string,
  document: Document = committedSchema(),
): readonly string[] {
  const node = resolved(
    target(`#/components/schemas/${schema}`, document),
    document,
  );
  return (node["required"] ?? []) as string[];
}

/** One operation's parameters, each `$ref` among them followed. */
export function parametersOf(
  operation: Operation,
  document: Document = committedSchema(),
): SchemaNode[] {
  return (operation.parameters ?? []).map((one) => resolved(one, document));
}
