/**
 * @vitest-environment node
 *
 * Parses strings; touches no DOM.
 */
/**
 * Tests for tests/stringEvaluation.ts: each rule of the walk, driven over a
 * script written here. The scan of the installed sql.js stays in
 * `lib/sqlite.test.ts`, beside the engine it reads.
 */

import { expect, it } from "vitest";

import { stringEvaluation } from "./stringEvaluation";

it("names the compiler each script reaches, and none for a look alike", () => {
  // The expected names are written out rather than read off the patterns,
  // so dropping a pattern to quiet a hit reds here too.
  const rows: [string, string[]][] = [
    ["eval(s)", ["eval"]],
    ["(0,eval)(s)", ["eval"]],
    ['self["eval"](s)', ["eval"]],
    ["eval?.(s)", ["eval"]],
    ["globalThis.eval(s)", ["eval"]],
    ['eval.call(null, "s")', ["eval"]],
    ['Reflect.apply(eval, null, ["s"])', ["eval"]],
    ['new Function("x","return x")', ["Function"]],
    ['Function("return this")()', ["Function"]],
    ['globalThis.Function("x")', ["Function"]],
    ['self["Function"]("x")', ["Function"]],
    ["self['Function']('x')", ["Function"]],
    ['self[`Function`]("x")', ["Function"]],
    ['globalThis [ "Function" ] ("x")', ["Function"]],
    ['self?.Function("x")', ["Function"]],
    ['self?.["Function"]("x")', ["Function"]],
    ['window.self.Function("x")', ["Function"]],
    ['Function\n("x")', ["Function"]],
    ['Function?.("x")', ["Function"]],
    ['globalThis.Function?.("x")', ["Function"]],
    ['Function/**/("x")', ["Function"]],
    ['Function /* c */ ("x")', ["Function"]],
    ['new (Function)("x")', ["Function"]],
    ['(0,Function)("x")', ["Function"]],
    ['\\u0046unction("x")', ["Function"]],
    ["Function`x`", ["Function"]],
    ['Function.call(null, "src")', ["Function"]],
    ['Function.apply(null, ["src"])', ["Function"]],
    ['Function.bind(null, "src")()', ["Function"]],
    ['Reflect.construct(Function, ["src"])', ["Function"]],
    ['setTimeout("tick()", 1)', ["setTimeout"]],
    ['window.setInterval("tick" + n, 1)', ["setInterval"]],
    ["setTimeout(tick, 1)", []],
    ["k.addFunction(1)", []],
    ["myFunction(1)", []],
    ["x.removeFunction(a)", []],
    ["RegisterExtensionFunctions(1)", []],
    ["$Function(1)", []],
    ["Function$(1)", []],
    ["isFunction(1)", []],
    ["x.Function(1)", []],
    ["a instanceof Function", []],
    ["typeof Function", []],
    ["Function.prototype.call(x)", []],
    ['"[object Function]"', []],
    ["// avoid eval(x)", []],
    ['"wasm-unsafe-eval"', []],
    // A compiler handed on as a value. Emscripten's embind ships exactly
    // the first, so a guard reading callees alone passed it.
    [
      "function newFunc(c, a) { return c.apply(o, a) } newFunc(Function, a).apply(null, b)",
      ["Function"],
    ],
    ["f(Function)", ["Function"]],
    ['const F = Function; F("x")', ["Function"]],
    ["var e = eval; e(s)", ["eval"]],
    ['const { Function: F } = globalThis; F("x")', ["Function"]],
    ["const { Function } = globalThis", ["Function"]],
    ['const { ["eval"]: e } = self', ["eval"]],
    ["const F = globalThis.Function", ["Function"]],
    ['const e = globalThis["eval"]', ["eval"]],
    ['[Function][0]("x")', ["Function"]],
    // Refused although nothing runs: the value could travel on from here.
    ["x === Function", ["Function"]],
    // A property that is the compiler again, or could be.
    ['Function.constructor("x")', ["Function"]],
    ['eval.constructor("x")', ["eval"]],
    ['Function.prototype.constructor("x")', ["Function"]],
    ["(Function?.prototype).constructor", ["Function"]],
    ["Function[k]", ["Function"]],
    ["Function.prototype[k]", ["Function"]],
    // A local in a sibling scope of each kind shadows nothing out here.
    ["{ let eval = 1 } eval(s)", ["eval"]],
    ['function g(Function) {} Function("x")', ["Function"]],
    ['(function () { var Function })(); Function("x")', ["Function"]],
    ['(() => { var Function })(); Function("x")', ["Function"]],
    ["try {} catch (eval) {} eval(s)", ["eval"]],
    ["for (let eval of a) {} eval(s)", ["eval"]],
    ["for (let eval in a) {} eval(s)", ["eval"]],
    ["for (let eval = 0; ; ) {} eval(s)", ["eval"]],
    ["switch (k) { case 1: let eval } eval(s)", ["eval"]],
    ["class C { static { var eval } x = eval }", ["eval"]],
    ["class C { m(eval) {} } eval(s)", ["eval"]],
    ["(function eval() {}); eval(s)", ["eval"]],
    ['(class Function {}); Function("x")', ["Function"]],
    // A local of the same name is not the global.
    ['function g(Function) { return Function("x") }', []],
    ["function g() { var eval = h; { eval(s) } }", []],
    ['let Function = h; Function("x")', []],
    ["try {} catch (eval) { eval(s) }", []],
    ["(function eval() { eval(s) })", []],
    ['function Function() {} Function("x")', []],
    ["function g() { { function eval() {} } eval(s) }", []],
    ['import { Function } from "m"; Function("x")', []],
    ["const { a: Function } = o; Function(1)", []],
    ['class Function {} new Function("x")', []],
    // A key, a label or a harmless property is not a read of the compiler.
    ["({ Function: 1, eval() {} })", []],
    ["class C { eval() {} Function = 1 }", []],
    ["eval: for (;;) break eval;", []],
    ["Function.name", []],
    ["typeof (Function)", []],
    ["Function.prototype.toString.call(f)", []],
    // Not looked for, as the docstring says, so a change that starts finding
    // one reds here and is the prompt to move it out of that paragraph.
    ["new (Object.getPrototypeOf(async function () {}).constructor)(s)", []],
    ['window.setTimeout.call(window, "tick()")', []],
    // Refused although the browser never fails on it: the walk reads
    // presence, not reach.
    ['try { const F = Function; new F("") } catch {}', ["Function"]],
    ['typeof window === "undefined" ? eval("require") : 0', ["eval"]],
  ];

  expect(rows.map(([script]) => stringEvaluation(script))).toEqual(
    rows.map(([, names]) => names),
  );
});
