/**
 * @vitest-environment node
 *
 * Parses strings; touches no DOM.
 */
/**
 * Tests for tests/sourceReader.ts: the answers its copies disagreed on, each
 * driven over a source written here.
 */

import { describe, expect, it } from "vitest";
import { parseAst } from "vite";

import {
  boundBy,
  namesBoundBy,
  resolvePath,
  SCOPES,
  scopeBindings,
  walk,
  type Node,
} from "./sourceReader";

/** The binding target of the first declarator, or the first parameter. */
function targetOf(code: string): unknown {
  const [first] = parseAst(code, { lang: "ts" }).body as unknown as Node[];
  if (first!.type === "VariableDeclaration")
    return (first!.declarations as Node[])[0]!.id;
  return (first!.params as unknown[])[0];
}

/** The names each scope in `code` binds, outermost first, by its kind. */
function scopesOf(code: string): string[] {
  const read: string[] = [];
  walk(parseAst(code, { lang: "ts" }), (node) => {
    if (!SCOPES.has(node.type)) return;
    const names = [...scopeBindings(node).names.keys()].toSorted();
    read.push(`${node.type}: ${names.join(" ")}`);
  });
  return read;
}

describe("the source reader", () => {
  it("reads a renamed key under a type as binding the new name alone", () => {
    expect(namesBoundBy(targetOf("const { a: b }: Props = x;"))).toEqual(["b"]);
  });

  it("reads no default value as a binding", () => {
    expect(namesBoundBy(targetOf("function f({ a = D, ...r }: T) {}"))).toEqual(
      ["a", "r"],
    );
  });

  it("records a target outside the pattern grammar rather than skipping it", () => {
    const member = parseAst("for (o.p of xs);", { lang: "ts" })
      .body[0] as unknown as Node;

    expect(boundBy(member.left).unreadable).toEqual(["MemberExpression"]);
    expect(() => namesBoundBy(member.left)).toThrow("MemberExpression");
  });

  it("keeps a `..` that climbs past the start of its base", () => {
    expect(resolvePath(["tests"], "../../src/x.ts")).toEqual([
      "..",
      "src",
      "x.ts",
    ]);
    expect(resolvePath([], "./a/../../b")).toEqual(["..", "b"]);
    expect(resolvePath(["frontend", "tests"], "../src/./x.ts")).toEqual([
      "frontend",
      "src",
      "x.ts",
    ]);
  });

  it("visits every node once, outermost first, and prunes where told", () => {
    const seen: string[] = [];
    walk(parseAst("f(a, () => b);", { lang: "ts" }), (node, ancestors) => {
      seen.push(`${ancestors.length}:${node.type}`);
      if (node.type === "ArrowFunctionExpression") return false;
    });

    expect(seen).toEqual([
      "0:Program",
      "1:ExpressionStatement",
      "2:CallExpression",
      "3:Identifier",
      "3:Identifier",
      "3:ArrowFunctionExpression",
    ]);
  });

  it("descends into the values a visit hands back instead of the node's own", () => {
    const seen: string[] = [];
    walk(parseAst("a + b;", { lang: "ts" }), (node) => {
      if (node.type === "Identifier") seen.push(String(node.name));
      if (node.type === "BinaryExpression") return [node.right];
    });

    expect(seen).toEqual(["b"]);
  });

  it("keeps a block's `let` in the block and hoists its `var` and function", () => {
    expect(
      scopesOf("function f(p) { { let a; var b; function c() {} } }"),
    ).toEqual([
      "Program: f",
      "FunctionDeclaration: b c p",
      "BlockStatement: ",
      "BlockStatement: a b c",
      "FunctionDeclaration: ",
      "BlockStatement: ",
    ]);
  });

  it("binds a function expression's own name inside it and nowhere else", () => {
    expect(scopesOf("const g = function h() {};")).toEqual([
      "Program: g",
      "FunctionExpression: h",
      "BlockStatement: ",
    ]);
  });

  it("reads the TypeScript declarations and not the type space ones", () => {
    expect(
      scopesOf("enum E { A } namespace N {} import Q = N; type T = 1;"),
    ).toEqual(["Program: E N Q", "TSEnumBody: ", "TSModuleBlock: "]);
  });

  it("records a declaration kind it does not know rather than walking past it", () => {
    const named = { type: "Identifier", name: "x" };
    const program = {
      type: "Program",
      body: [{ type: "NextDeclaration", id: named }],
    };

    expect(scopeBindings(program).unreadable).toEqual(["NextDeclaration"]);
  });
});
