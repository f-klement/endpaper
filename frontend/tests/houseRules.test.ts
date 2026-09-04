/**
 * @vitest-environment node
 *
 * Touches no DOM, so it needs no jsdom. Building one costs more than this file
 * spends running: measured across the suite, `environment` was 168s of a 245s
 * run, paid once per file.
 */
/**
 * Rules that hold across the whole tree, asserted rather than trusted.
 *
 * None of them has any other enforcement, and every one is the kind of thing
 * that looks fine in a diff and is only wrong when read against the rest of the
 * tree, which is exactly what a reviewer does not do. (This said "neither" and
 * "both" while the file held eleven rules, which is what a count written in
 * prose does: it does not recount itself when a rule is added beside it. There
 * is deliberately no number here now.)
 *
 * The sources are read with `import.meta.glob` rather than `node:fs` so this
 * needs no `@types/node`, which the project does not otherwise want: a guard
 * test is a poor reason to add a dependency and widen the global types.
 */

import { describe, expect, it, vi } from "vitest";

// Imported through the specifier the application uses, so this is the double
// only if the alias is in force.
import * as zxingDouble from "@zxing/library";

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

describe("nothing hand-written lives under the assets directory", () => {
  // The invariant behind the backend's cache policy, which gives everything in
  // `assets/` a year with `immutable` and everything else `no-cache`. That is
  // safe only because Vite emits `assets/` and every name in it carries a
  // content hash. Vite also copies `public/` into the build verbatim, so a file
  // at `public/assets/anything` would land there unhashed and be pinned in
  // every reader's browser for a year, with no way to bust it short of a
  // rename: the exact failure the header exists to prevent, inverted.
  //
  // Asserted rather than commented, because the rule is about a directory
  // nobody has a reason to create and would therefore be created by somebody
  // who never read the comment. Backend side: `main.cache_control_for`.
  // Lazy and untyped on purpose: only the keys are wanted, and an eager raw
  // glob would inline every icon in `public/` into this test file as a string.
  const PUBLIC = import.meta.glob("../public/**/*");

  it("has no public/assets", () => {
    const offenders = Object.keys(PUBLIC).filter((path) =>
      path.startsWith("../public/assets/"),
    );
    expect(offenders).toEqual([]);
  });

  it("reads public/ at all", () => {
    // A glob that matched nothing would make the test above pass for ever.
    expect(Object.keys(PUBLIC).length).toBeGreaterThan(0);
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
        .filter(
          (token) => !token.includes("dark:") && !token.includes("disabled:"),
        )
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
      [
        ...source.matchAll(
          /[\w:./[\]-]*focus(-visible)?:(outline-none|ring-[\w./#%[\]-]+)/g,
        ),
      ]
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

/** The one module allowed to drop the whole cache. */
const INVALIDATION_OWNER = "api/invalidate.ts";

describe("a write names what it made stale", () => {
  it("does not drop the whole cache at the call site", () => {
    // `queryClient.invalidateQueries()` with no key refetches every mounted
    // query on the page, whatever it is about and whatever staleTime it was
    // given. Eleven call sites did it. Measured on 2026-08-26: ten requests on
    // a book's page for deleting a curated tag, where five are about the tag,
    // and on the scan page a refetch of `/api/books/search`, which is a billed
    // Google Books call the query's own staleTime exists to avoid re-spending.
    //
    // Two writes still earn the whole cache and both go through
    // `invalidate.everything()`, where the reason is written down: restoring a
    // backup, and merging duplicates. The rule is that the decision is made in
    // the module that knows what each group covers, not at a call site that
    // has to remember.
    //
    // Said out loud so nobody trusts it as total: this counts a spelling. A
    // call site holding a `QueryClient` under another name, or building an
    // empty filter object, is outside it.
    const offenders = entries()
      .filter(([path]) => path !== INVALIDATION_OWNER)
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .filter(([, code]) => /invalidateQueries\(\s*\)/.test(code))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it("drops the whole cache from exactly two call sites", () => {
    // `everything()` is the same keyless invalidate with a better name, and the
    // rule above permits it anywhere. Its docstring says "two callers, and both
    // earn it", which is a count, and a count with no enforcement is how the
    // group whose whole point is being rare stops being rare.
    //
    // Both are named here rather than counted, because what makes them correct
    // is what they do and not how many they are: a backup restore replaces
    // every row in the database including the signed-in member's, and merging
    // duplicates moves notes, quotes, progress and reading statuses between
    // books with no account in the response of what moved. A third caller is a
    // decision somebody has to make, in this file, rather than a line in a
    // diff.
    const callers = entries()
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .filter(([, code]) => /\.everything\s*\(/.test(code))
      .map(([path]) => path)
      .sort();

    expect(callers).toEqual([
      "pages/DuplicatesPage/hooks.ts",
      "pages/SettingsPage/DataSettingsPage/hooks.ts",
    ]);
  });

  it("still has an owner that does it", () => {
    // A rule whose subject has been renamed passes by matching nothing.
    const owner = entries().find(([path]) => path === INVALIDATION_OWNER);
    expect(owner).toBeDefined();
    expect(withoutProse(owner![1])).toMatch(/invalidateQueries\(\s*\)/);
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
    // Concatenated class strings are joined before matching. Four of these are
    // written as `"…light…" + "…dark…"` across a line break, and a rule that
    // read the halves separately would report all four as offenders and teach
    // the next person to work around it. Counted 2026-08-24, by joining each
    // concatenation chain and asking which put the plain hover and the dark one
    // in different segments: `components/Button.tsx`,
    // `app/components/NavBar.tsx`, `pages/Home/components/BookFilters.tsx`,
    // `pages/SettingsPage/AboutSettingsPage/components/AboutBadges.tsx`. This comment said "two"
    // while there were three, which is why the count is now dated and the files
    // named: a claim that there are exactly N is worth nothing without them.
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

/** A background painted with the light-only top surface, at any variant. */
const LIGHT_FILL = /(?<![-\w])(?:[a-z-]+:)*bg-paper-0(?:\/\d+)?(?![-\w])/;
const DARK_FILL = /(?<![-\w])dark:(?:[a-z-]+:)*bg-/;
const DARK_INK = /(?<![-\w])dark:(?:[a-z-]+:)*text-/;

/** The class strings in one module, with concatenation chains joined first. */
function classStrings(source: string): string[] {
  return [
    ...source.replace(/["`]\s*\+\s*["`]/g, " ").matchAll(/["`]([^"`]*)["`]/g),
  ].map((match) => match[1]!);
}

describe("a dark ink never lands on the light-only surface", () => {
  it("appears nowhere in the source", () => {
    // `paper-0` is the top surface, and it is the one paper token no palette
    // and no mode redefines: `index.css` sets it once and `:root.dark` leaves
    // it alone, which is why every dark call site in this tree spells
    // `dark:bg-paper-900` rather than relying on the token to flip. So a
    // literal that paints `bg-paper-0`, states a `dark:text-` and states no
    // dark background has moved the ink into the dark ramp and left the pill
    // in the light one.
    //
    // That is not a shade being slightly off. It is a light label on a white
    // pill: the two on the book detail cover measured 1.26:1 for
    // `text-paper-200` on `paper-0`, against the 4.5:1 WCAG 1.4.3 asks, and
    // they had read that way since they were written because nothing looks
    // wrong in the diff. Both now use the shared Button, whose `secondary`
    // variant states the fill and the foreground together: 14.25:1 light and
    // 15.79:1 dark.
    //
    // Both halves of the trigger matter. A literal with no `dark:text-` at all
    // inherits its ink from a parent that has one, and 42 of the 44 literals
    // painting this token do exactly that, correctly. The offence is stating
    // one half of the pair and not the other, which is the same defect the
    // dark hover rule above exists for, one property along.
    //
    // Variant prefixes are matched rather than assumed away: `PublicShell`'s
    // skip link is `focus:bg-paper-0` with `dark:focus:bg-paper-900`, and a
    // rule anchored on the bare spellings would report it.
    //
    // Concatenation chains are joined for the same reason the hover rule joins
    // them: the light half and the dark half are routinely written in
    // different segments across a line break.
    const offenders = entries().flatMap(([path, source]) =>
      classStrings(source)
        .filter(
          (classes) =>
            LIGHT_FILL.test(classes) &&
            DARK_INK.test(classes) &&
            !DARK_FILL.test(classes),
        )
        .map((classes) => `${path}: ${classes}`),
    );

    expect(offenders).toEqual([]);
  });

  it("is watching something", () => {
    // A rule whose subject was renamed passes by matching nothing. Counted
    // 2026-08-29: 44 literals in the tree paint this token.
    const painted = entries().flatMap(([, source]) =>
      classStrings(source).filter((classes) => LIGHT_FILL.test(classes)),
    );

    expect(painted.length).toBeGreaterThan(30);
  });

  it("reports the shapes it exists for", () => {
    const offends = (classes: string) =>
      LIGHT_FILL.test(classes) &&
      DARK_INK.test(classes) &&
      !DARK_FILL.test(classes);

    // The two it was written for, verbatim.
    expect(
      offends("bg-paper-0/90 shadow-sm text-paper-700 dark:text-paper-200"),
    ).toBe(true);
    expect(offends("bg-paper-0 text-paper-700 dark:text-paper-200")).toBe(true);
    // Stating the pair is the fix, at any variant depth.
    expect(
      offends(
        "bg-paper-0 dark:bg-paper-900 text-paper-800 dark:text-paper-100",
      ),
    ).toBe(false);
    expect(
      offends(
        "focus:bg-paper-0 dark:focus:bg-paper-900 dark:focus:text-paper-100",
      ),
    ).toBe(false);
    // Inheriting the ink is correct and is what most of the tree does.
    expect(offends("bg-paper-0 border border-paper-200")).toBe(false);
    // Neither a longer token nor a longer ramp step is this surface.
    expect(offends("bg-paper-0-something dark:text-paper-200")).toBe(false);
    expect(offends("bg-paper-900 dark:text-paper-200")).toBe(false);
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

describe("a tag reaches a reader through tagName", () => {
  /** The one module allowed to read a tag's stored name. */
  const TAG_NAME_OWNER = "i18n/tagNames.ts";

  it("is not printed from the stored name at a call site", () => {
    // `tags.name` is the **English** name, and only the English name: the
    // German one is looked up by `tags.key` in `i18n/tagNames.ts`. A component
    // that prints `tag.name` therefore prints English into a German page, with
    // nothing failing and nothing to see in a diff. Counted 2026-08-27 against
    // the tree this rule arrived in: **9** reads in 6 files, every one of them
    // a tag on screen, which is why this is a rule rather than a habit.
    //
    // Said out loud so nobody trusts it as total: this counts a spelling. It
    // matches an identifier whose name ends in `tag` or `tags`, which is what
    // every site in this tree calls one, and a site that named its variable
    // `chip` or destructured `{ name }` off a `TagOut` would walk past it. No
    // regex closes that gap: it is the distance between a concept and the
    // characters it is usually written with.
    const offenders = entries()
      .filter(([path]) => path !== TAG_NAME_OWNER)
      .map(([path, source]) => [path, withoutProse(source)] as const)
      .flatMap(([path, code]) =>
        [...code.matchAll(/\b\w*[Tt]ags?\.name\b/g)].map(
          (match) => `${path}: ${match[0]}`,
        ),
      );

    expect(offenders).toEqual([]);
  });

  it("is watching something", () => {
    // A rule whose subject has been renamed passes by matching nothing. There
    // are tag names on screen in this tree; the rule is that every one of them
    // goes through the function.
    const callers = entries().filter(
      ([path, source]) =>
        path !== TAG_NAME_OWNER && /\btagName\(/.test(withoutProse(source)),
    );

    expect(callers.length).toBeGreaterThan(4);
  });
});

describe("no fixture or string carries an address outside reserved space", () => {
  // The frontend half of
  // `backend/tests/test_house_rules.py::TestNoFixtureLooksLikeACredential`.
  // That arm walks the backend test tree only, and its own reason for existing
  // is that **both** trees are published: this repository mirrors `src/`,
  // `tests/` and `docs/` to public GitHub. `src/i18n/en.ts` ships a placeholder
  // address in published source, which the backend rule cannot see at all.
  //
  // RFC 2606 reserves `example.com`, `example.net` and `example.org`, and RFC
  // 6761 the `.test`, `.example`, `.invalid` and `.localhost` names. Anything
  // outside them is registrable, and a stranger reading the mirror cannot tell
  // a placeholder from somebody's real mailbox.
  const RESERVED = [
    "example.com",
    "example.net",
    "example.org",
    "test",
    "example",
    "invalid",
    "localhost",
  ];

  // A label boundary, not a suffix. The backend arm shipped for one round
  // comparing with `endsWith` against bare names, which accepted
  // `notexample.com`, `myexample.org` and `fakeexample.net`.
  const isReserved = (domain: string) =>
    RESERVED.some((base) => domain === base || domain.endsWith(`.${base}`));

  // Deliberately looser than any address validator: this looks for what a
  // reader would take for an address, and nobody triaging the mirror runs our
  // rules over it first.
  const ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;

  const TESTS = import.meta.glob("./**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  // This file writes the shapes down in order to forbid them, so it is filtered
  // out. **Measured: today that filter removes nothing**, because Vite excludes
  // the importing module from its own `import.meta.glob`. A probe run from a
  // sibling file saw `./houseRules.test.ts` among 131 keys; run from here it is
  // absent. The filter stays because it is one line and it is what keeps the
  // rule working if that ever changes, and the assertion below pins the fact so
  // that nobody reads the filter as evidence of something it is not doing.
  const SELF = "./houseRules.test.ts";

  function everything(): [string, string][] {
    return [
      ...entries(),
      ...Object.entries(TESTS)
        .filter(([path]) => path !== SELF)
        .map(([path, source]): [string, string] => [
          path.replace("./", "tests/"),
          source,
        ]),
    ];
  }

  it("finds none", () => {
    const offenders = everything().flatMap(([path, source]) =>
      source.split("\n").flatMap((line, index) =>
        [...line.matchAll(ADDRESS)]
          .map((match) => match[0])
          .filter(
            (address) => !isReserved(address.split("@")[1]!.toLowerCase()),
          )
          .map((address) => `${path}:${index + 1} (${address})`),
      ),
    );

    expect(offenders).toEqual([]);
  });

  it("reads both trees, not just one", () => {
    // The backend arm walks one tree while its docstring named two, which is
    // why this one exists. A glob that matched nothing would make the rule
    // above pass forever.
    const paths = everything().map(([path]) => path);

    expect(paths.some((path) => path.startsWith("tests/"))).toBe(true);
    expect(paths.some((path) => path.startsWith("i18n/"))).toBe(true);
  });

  it("is not scanning itself, and the exclusion above is not what stops it", () => {
    // Pointing `SELF` at a name that does not exist changes nothing, which is
    // how this was found: Vite already keeps the importing module out of its
    // own glob. Pinned rather than left implicit, because if that behaviour
    // changes the honest failure is this line saying so, not the rule above
    // failing on this file's own deliberately unreserved fixture.
    expect(Object.keys(TESTS)).not.toContain(SELF);
  });

  it("reports the shapes it exists for", () => {
    expect(isReserved("mail.example.org")).toBe(true);
    expect(isReserved("example.org")).toBe(true);
    expect(isReserved("anything.invalid")).toBe(true);
    // The three a bare suffix comparison lets through.
    expect(isReserved("notexample.com")).toBe(false);
    expect(isReserved("myexample.org")).toBe(false);
    expect(isReserved("fakeexample.net")).toBe(false);
    expect(isReserved("gmail.com")).toBe(false);

    const found = [
      ..."write to kim.jones@gmail.com or sam@example.org".matchAll(ADDRESS),
    ].map((match) => match[0]);
    expect(found).toEqual(["kim.jones@gmail.com", "sam@example.org"]);
  });
});

/**
 * Source with every whole line comment removed.
 *
 * **Every way this is wrong is a false positive, which is the direction a rule
 * has to be wrong in.** Measured, not reasoned about, after the first version
 * of this paragraph stated the bias backwards: three shapes are reported that
 * are not calls, and they are a call in a string literal, a call after code on
 * a line that ends in a trailing comment, and a call inside a block comment
 * whose own line carries no leading `//`, `*` or `/*`. Each fails loudly and is
 * reworded in a minute.
 *
 * The only shape this misses is a call on a line that begins with one of those
 * three, and no line beginning that way is executed. So there is no false
 * negative here to trade against, which is not what the first draft claimed.
 *
 * **What it does not attempt is a receiver.** It matches the literal `vi.`, so
 * `v.mock(` after `import { vi as v }`, a destructured `mock`, `vi["mock"]` and
 * a call through a saved reference all pass. Adding an arm for each is the
 * enumeration this file argues against elsewhere, and none of them is a
 * spelling anybody reaches for by accident: the rule is a tripwire on the
 * idiomatic form, not a type checker.
 *
 * A general comment stripper would be a second parser to get wrong, and this
 * project has none to borrow: both were checked rather than assumed.
 * `typescript` is at 7.x, which is the native compiler and exposes no
 * `createSourceFile` (it is `undefined` at runtime), and rolldown re-exports no
 * parser either.
 *
 * Line anchoring was the other candidate and is strictly weaker: it sees only a
 * call that begins its own line, so anything at all before it hides it.
 *
 * **The pattern requires the opening parenthesis, so prose naming the bare API
 * is invisible to it either way.** That is why this stripping is load bearing
 * for exactly one file in the tree, `tests/utils.tsx`, and not for the four
 * that mention the name: the other three write it bare. Attacking it is what
 * established that, and the first attempt at the check asserted the wrong
 * thing, that every file mentioning the API must be reported without the
 * stripping. Mentioning it is not spelling a call.
 */
function codeOnly(source: string): string {
  return source
    .split("\n")
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
    .join("\n");
}

/**
 * Its own separate glob, because the one in the address rule above is scoped
 * inside that describe block.
 */
const TEST_SOURCES = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/**
 * The forbidden spellings, assembled rather than written out.
 *
 * **This file would otherwise be the only offender in the suite**: the
 * fixtures below have to spell what the rule forbids, they sit in string
 * literals on ordinary code lines, and `codeOnly` keeps those by design. An
 * exception for this one path would be the obvious fix and is the worse one,
 * because it also stops the rule ever applying here. Assembling the spelling
 * keeps this file inside the rule it states.
 *
 * The pattern itself is safe unassembled: its source carries a backslash and
 * an alternation, so it does not contain the literal it matches.
 */
// **`\s*` on both sides of the dot, because prettier puts them there.** When
// the call heads an assignment chain it splits the receiver onto its own line:
// `const setItem = vi\n  .spyOn(...)`. That shape occurs three times in this
// tree, so `vi\n  .mock("./x")` is a spelling the formatter produces rather
// than one an evader would have to invent, and the tighter pattern walked past
// it. Found by attacking the rule after a first pass dismissed the same
// evasion as contrived.
const CALLS = /\bvi\s*\.\s*(mock|doMock|importMock)\s*\(/;
const MOCK = "vi." + "mock";
const DO_MOCK = "vi." + "doMock";

describe("a module is replaced by an alias, never by a module mock", () => {
  /**
   * **This is what makes `isolate: false` sound rather than merely lucky.**
   * The files in a worker share one module registry, so a module mock is a
   * claim one file makes about a module another file may already have
   * evaluated, and the loser is silent: the mock is dropped and the real
   * module is what the test gets.
   *
   * Measured before this rule existed, in both directions, with the whole
   * suite otherwise green. `App.test.tsx` ahead of `BarcodeScanner.test.tsx`
   * gave the scanner the real ZXing and failed fifteen of its tests at once.
   * `App.test.tsx` ahead of `BookDetail.test.tsx` gave it the real
   * `useNavigate` and failed the one test asserting on that spy. Both files
   * pass alone and pass in the other order, which is what makes this worth a
   * guard rather than a note.
   *
   * The replacement is `test.alias` in `vite.config.ts` pointing into
   * `tests/doubles/`: one implementation for the whole suite, so there is no
   * real module left to lose to and no ordering to get wrong.
   * `tests/doubles/README.md` is the argument in full.
   */
  it("is not called anywhere in the suite", () => {
    const offenders = Object.entries(TEST_SOURCES)
      .filter(([, source]) => CALLS.test(codeOnly(source)))
      .map(([path]) => path.replace("./", "tests/"));

    expect(offenders).toEqual([]);
  });

  it("reads the test tree at all", () => {
    // A glob that matched nothing would make the rule above pass for ever.
    expect(Object.keys(TEST_SOURCES).length).toBeGreaterThan(100);
  });

  it("tells a call apart from prose about one", () => {
    // Every live mention in this suite is prose: in `tests/utils.tsx`, in both
    // ScanPage test files, and in `tests/doubles/zxing.ts`. A rule matching the
    // spelling would report all of them and would have to be switched off, so
    // the two cases are pinned apart rather than left to a reader's judgement.
    const prose = [
      `// ${MOCK}("react-router-dom") is refused: see the rule above.`,
      ` * with a ${MOCK}("@zxing/library") the scanner gets the real decoder.`,
      `  /* ${MOCK}("./thing"); */`,
    ].join("\n");
    expect(CALLS.test(codeOnly(prose))).toBe(false);

    for (const code of [
      `${MOCK}("@zxing/library", () => ({}));`,
      `  ${DO_MOCK}("./thing");`,
      // Not anchored to the start of a line: that was the cheaper rule and it
      // is blind to anything sharing the line with the call.
      `const a = 1; ${MOCK}("./thing");`,
      // The receiver split onto its own line, which is what prettier does to a
      // call that heads an assignment chain, and which three real call sites in
      // this tree are already written as.
      `const m = vi\n  .${"mock"}("./thing");`,
    ]) {
      expect(CALLS.test(codeOnly(code))).toBe(true);
    }
  });

  /**
   * **The one mistake here with a production consequence, so it is the one
   * checked against the running config rather than against its text.**
   *
   * `test.alias` is scoped to the suite. `resolve.alias` is not: the same entry
   * one level up would put a decoder that never decodes into the shipped
   * bundle, and no test could tell, because from inside the suite the two are
   * indistinguishable by construction. That is exactly the shape a guard has to
   * cover from outside.
   *
   * Asking vite what the **build** resolves is the only assertion that cannot
   * be satisfied by a config that merely looks right. A text check would pass
   * on a `resolve.alias` added in a shape it did not anticipate.
   *
   * This test exists because a docstring in `tests/doubles/zxing.ts` said it
   * did, for a round, while nothing read the config at all.
   */
  it("keeps the doubles out of the application build", async () => {
    const { resolveConfig } = await import("vite");
    // No root passed: vite falls back to the working directory and finds the
    // config the way a build does, which is the thing under test.
    for (const command of ["build", "serve"] as const) {
      const resolved = await resolveConfig({}, command);

      // **Assert a config was found, or this passes by reading nothing.**
      // Measured from a different working directory: `configFile` comes back
      // `undefined` and `resolve.alias` is byte identical, because the project
      // contributes nothing to it, which is the correct state and is also
      // exactly what never opening the file looks like. Same shape as a script
      // that takes a ref and reads whichever repository the shell is in.
      expect(resolved.configFile).toMatch(/vite\.config\.ts$/);

      // **The directory, not the two names in use.** A `find` that is a RegExp
      // serialises to `{}`, so the discriminating half of an entry is erased
      // before this sees it, and vite's own defaults already contain two such
      // entries. Naming the words `zxing` and `doubles` would therefore pass on
      // a double keyed by a pattern, and it would be an inclusion list one test
      // after this file removed one for being an inclusion list. Measured
      // absent from the resolved default.
      expect(JSON.stringify(resolved.resolve.alias)).not.toContain("/tests/");
    }
  });

  it("still aliases them for the suite", () => {
    // The other half, and it is what stops the test above passing because
    // somebody deleted the alias rather than because it is correctly scoped.
    // Read off the running suite rather than off the config text: this
    // specifier is the one the application uses, so whatever it resolves to
    // here is what the code under test got.
    //
    // The real `BarcodeFormat` is a numeric enum and the double's is strings,
    // so the value alone says which one answered.
    //
    // **`tsc` disagrees with the runtime here, and that is the point.** It
    // resolves this import to the real library's types, because the alias is
    // vitest's and not tsconfig's. So the application keeps the real types
    // while the suite gets the double, which is the arrangement the test above
    // checks from the other side. It also means only the shape the real
    // library declares can be read through this import: reaching for one of
    // the double's spies here is a type error, and they are imported from
    // `tests/doubles/zxing` by the files that assert on them.
    expect(zxingDouble.BarcodeFormat.EAN_13).toBe("EAN_13");
  });

  it("covers every vitest api that replaces a module", () => {
    // **Derived from vitest, and stated as an exclusion.** The first version of
    // the rule named two of the three and missed `importMock`, which takes a
    // specifier and replaces the module exactly as the other two do. The second
    // version derived the set with `/^(do|import)?[Mm]ock$/`, which is an
    // inclusion list wearing a pattern's clothes: it would have gone on passing
    // against a `mockModule` or a `mockRequire`, because a name of a shape it
    // did not anticipate simply is not selected.
    //
    // So: everything vitest spells with "mock", minus the ones classified below
    // as not replacing a module. A new API containing that word then fails here
    // until somebody decides which side it is on, which is the whole point.
    const NOT_A_REPLACEMENT = new Set([
      // Reads or asserts on a mock that already exists.
      "mocked",
      "isMockFunction",
      // Replaces an object's methods, never a module specifier.
      "mockObject",
      // Undoes a replacement rather than making one. These two do take a module
      // specifier, which is why this test is named for replacing rather than
      // for the argument: the argument is not what makes one dangerous.
      "unmock",
      "doUnmock",
      // Act on every spy at once, and take no specifier.
      "clearAllMocks",
      "resetAllMocks",
      "restoreAllMocks",
      // Fake timers.
      "getMockedSystemTime",
    ]);
    const replacers = Object.keys(vi).filter(
      (name) => /mock/i.test(name) && !NOT_A_REPLACEMENT.has(name),
    );

    // Not a stated count. A floor, so an API that has been enumerated away, or
    // one this filter can no longer see, fails here rather than passing quietly
    // on an empty set.
    expect(replacers.length).toBeGreaterThanOrEqual(3);

    // Driven through the rule rather than compared against its source text: a
    // substring check would pass on a pattern that happens to mention the name
    // without matching a call.
    for (const name of replacers) {
      expect(CALLS.test(codeOnly(`vi.${name}("./x");`))).toBe(true);
    }
  });
});
