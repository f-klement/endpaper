/**
 * Rules that hold across the whole tree, asserted rather than trusted.
 *
 * Neither has any other enforcement, and both are the kind of thing that looks
 * fine in a diff and is only wrong when read against the rest of the tree,
 * which is exactly what a reviewer does not do.
 *
 * The sources are read with `import.meta.glob` rather than `node:fs` so this
 * needs no `@types/node`, which the project does not otherwise want: a guard
 * test is a poor reason to add a dependency and widen the global types.
 */

import { describe, expect, it } from "vitest";

const SOURCES = import.meta.glob("../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function entries(): [string, string][] {
  return Object.entries(SOURCES).map(([path, source]) => [
    path.replace("../src/", ""),
    source,
  ]);
}

describe("the generated client stays behind hooks.ts", () => {
  it("is imported by nothing else", () => {
    // The single indirection is what stops a regeneration rippling through
    // every component. Types are a different matter and are imported freely:
    // `api/generated/model` is a description of the API, not a call to it.
    const offenders = entries()
      .filter(([path]) => !path.startsWith("api/"))
      .filter(([, source]) => source.includes("api/generated/endpoints"))
      .map(([path]) => path)
      .filter((path) => !path.endsWith("hooks.ts"));

    expect(offenders).toEqual([]);
  });

  it("reads the source tree at all", () => {
    // A glob that matched nothing would make both tests above pass forever.
    expect(entries().length).toBeGreaterThan(50);
  });
});

describe("paper-400 and paper-500 are not text in light mode", () => {
  it("appears nowhere in the source", () => {
    // Measured against the card they sit on: 2.35:1 and 3.83:1, where AA wants
    // 4.5. Both pass in dark, on a dark card, which is why nobody noticed: a
    // light surface admits fewer legible grey tiers than a dark one, and the
    // app was treating the ramp as symmetric. Muted text is `paper-600` in
    // light and `paper-400` in dark.
    //
    // Retiring the two as text is also what lets three upstream palettes ship
    // verbatim later: as decoration the step has to clear 3.0, not 4.5.
    //
    // `disabled:` is the exemption, and the only one. WCAG 1.4.3 does not apply
    // to an inactive control, and a disabled field that reads as strongly as a
    // live one is worse than a faint one.
    //
    // `index.css` is not covered, and no longer because it cannot be: the glob
    // above is TypeScript, while `tests/theme/palettes.test.ts` reads the
    // stylesheets as text and could do the same here. It holds exactly one of
    // these tokens, on `.field:disabled`, which is the exemption, so a second
    // glob would buy an assertion about a line that is already allowed.
    const offenders = entries().flatMap(([path, source]) =>
      [...source.matchAll(/[\w:./[\]-]*text-paper-[45]00/g)]
        .map((match) => match[0])
        .filter((token) => !token.includes("dark:") && !token.includes("disabled:"))
        .map((token) => `${path}: ${token}`),
    );

    expect(offenders).toEqual([]);
  });
});

describe("no control draws its own focus ring", () => {
  it("appears nowhere in the source", () => {
    // There is one ring, in `index.css`, and a control that brings its own is a
    // control that gets missed the next time that one moves. Twenty-one of them
    // did: `focus:ring-accent-400` measures 2.24:1 against the page where WCAG
    // 1.4.11 wants 3:1, and sixteen killed the browser default with
    // `focus:outline-none` first, so the text fields had the weakest focus
    // indicator in the app and nothing underneath it.
    //
    // `focus-visible:` as well as `focus:`, and arbitrary values, because the
    // shared rule *is* `:focus-visible`: the next person repairing a control
    // reaches for that spelling first, and for `ring-[3px]` second. Two shapes
    // are deliberately out of scope, both of which stop looking like a focus
    // ring at all: `focus:[box-shadow:...]`, which is a raw property rather than
    // a ring utility, and a bare `outline-none`, which removes the outline in
    // every state rather than on focus and belongs to a rule about outlines.
    //
    // `peer-focus-visible:` is exempt and is the settings toggle: its input is
    // `sr-only`, so the shared ring lands on something with no size and the
    // visible track has to draw its own.
    const offenders = entries().flatMap(([path, source]) =>
      [...source.matchAll(
        /[\w:./[\]-]*focus(-visible)?:(outline-none|ring-[\w./#%[\]-]+)/g,
      )]
        .map((match) => match[0])
        .filter((token) => !token.includes("peer-focus-visible:"))
        .map((token) => `${path}: ${token}`),
    );

    expect(offenders).toEqual([]);
  });
});

/** The source with comments removed, so a rule cannot be satisfied by prose. */
function withoutProse(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");
}

function sessionWrites(code: string): number {
  return [...code.matchAll(/\b(set|clear)Session\s*\(/g)].length;
}

function cacheClears(code: string): number {
  return [...code.matchAll(/queryClient\.clear\(\)/g)].length;
}

/** The one module that owns the session, and the one that defines it. */
const SESSION_OWNER = "pages/hooks.ts";
const SESSION_DEFINITION = "api/mutator.ts";

describe("an identity change drops the cache with it", () => {
  it("is decided in one module, not at each call site", () => {
    // The instance of this that mattered was the whole shelf. React Query's
    // client is built once per page load and outlives a sign-out, "Switch
    // account" is a router link rather than a navigation, switching into a
    // test account is a button in Settings, and under proxy auth the identity
    // can change with nothing happening in this app at all. `visible_to()` is
    // "public or mine", so the next member in was handed the previous one's
    // private books back under identical keys, with nothing refetching for
    // another thirty seconds.
    //
    // `useSession` now clears on a change of account id, so every path gets
    // it, including the proxy one, which has no call site here to add a clear
    // to. What this rule protects is that arrangement: a component that writes
    // the session itself would change the identity without going past the
    // hook watching it, and no effect can cover that.
    //
    // This replaced a count of `queryClient.clear()` against a count of
    // session writes per file. That was the right question while three call
    // sites each had to remember; against one effect keyed on the identity it
    // asks for a redundant call per writer, which is a rule that teaches the
    // wrong lesson to whoever adds the fourth path.
    //
    // Said out loud so nobody trusts it as total: this counts spellings, not
    // calls. A module that writes `localStorage` itself, or through an alias,
    // is outside it. No regex closes that gap: it is the distance between a
    // concept and the characters it is usually written with.
    const offenders = entries()
      .filter(([path]) => path !== SESSION_DEFINITION && path !== SESSION_OWNER)
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .filter(([, code]) => sessionWrites(code) > 0)
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("still clears the cache somewhere in that module", () => {
    // A tripwire, not the proof: what the clearing actually does is asserted
    // in tests/pages/hooks.test.ts, per mode and per path. This is here so
    // that deleting the mechanism outright cannot be a silent diff.
    const owner = entries().find(([path]) => path === SESSION_OWNER);
    expect(owner).toBeDefined();
    expect(cacheClears(withoutProse(owner![1]))).toBeGreaterThan(0);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing.
    const writers = entries().filter(
      ([, source]) => sessionWrites(withoutProse(source)) > 0,
    );
    expect(writers.length).toBeGreaterThan(1);
  });
});

describe("a dark hover state is stated, never inherited", () => {
  it("appears nowhere in the source", () => {
    // Every ramp runs the other way in the dark, so a hover written once is
    // legible at rest and illegible while pointed at. Twelve sites were:
    // `text-accent-700 hover:text-accent-800` measures 4.5:1 or better on a
    // light card and **1.36 to 2.85** on a dark one across the seven palettes,
    // because `accent-800` in a dark ramp is nearly the card itself.
    //
    // This rule ships with no exemption list, which is a claim rather than an
    // omission: all twelve were repaired in the same change, so there is
    // nothing to exempt. The alternative shape was considered and rejected for
    // that reason. A frozen allowlist is what this repository does when a rule
    // arrives before its repair (`api/mutator.ts` in the session rule,
    // `.field:disabled` in the paper rule), and a list of twelve would have
    // been a list of twelve things nobody was going to come back to.
    //
    // Only `hover:text-`, and not `hover:bg-` or `hover:border-`. A background
    // or a border that is a shade off in the dark is a flat surface that looks
    // slightly wrong; text that is a shade off is text nobody can read, and
    // WCAG 1.4.3 has a number for the second and not the first.
    //
    // Concatenated class strings are joined before matching. Two of these are
    // written as `"…light…" + "…dark…"` across a line break, and a rule that
    // read the halves separately would report both as offenders and teach the
    // next person to work around it.
    //
    // Said out loud so nobody trusts it as total: the unit is the string
    // literal, not the utility. A literal carrying two unqualified hover
    // states and one `dark:hover:text-` satisfies this rule while leaving one
    // of them unrepaired. No such site exists, and every site in the tree pairs
    // one hover with one dark hover, so pinning that shape would assert today's
    // spelling rather than the rule.
    const offenders = entries().flatMap(([path, source]) =>
      [
        ...source
          .replace(/["`]\s*\+\s*["`]/g, " ")
          .matchAll(/["`]([^"`]*hover:text-[^"`]*)["`]/g),
      ]
        .filter(([, classes]) => !/dark:hover:text-/.test(classes!))
        .flatMap(([, classes]) => [
          ...classes!.matchAll(
            /(?<![-\w:])hover:text-(?:paper|accent|bloom|danger)-\d+/g,
          ),
        ])
        .map((match) => `${path}: ${match[0]}`),
    );

    expect(offenders).toEqual([]);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing. There
    // are dark hover states in this tree; the rule is that they are all stated.
    const stated = entries().filter(([, source]) =>
      /dark:hover:text-/.test(source),
    );
    expect(stated.length).toBeGreaterThan(10);
  });
});

describe("no dash is used as punctuation", () => {
  it("appears nowhere in the source", () => {
    // House style. The message catalogues have their own test; this covers
    // comments, docstrings and anything else with words in it. A dash is easy
    // to paste in and invisible when skimming.
    const offenders = entries()
      .filter(([, source]) => /[–—]/.test(source))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
