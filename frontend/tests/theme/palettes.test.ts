/**
 * The palettes, measured against the contract they were generated to hold.
 *
 * This reads the shipped stylesheets as text and resolves the cascade the way a
 * browser would. That is the point: a table of the same hexes kept in
 * TypeScript for the test's convenience would prove that the copy is right, and
 * the copy is not what anybody sees. `vite.config.ts` turns CSS handling on for
 * exactly this file, and says why.
 *
 * Contrast is WCAG 2.1 relative luminance, which is a handful of lines and is
 * spelled out below rather than imported: no dependency, and the formula sits
 * beside the numbers it produces.
 */

import { describe, expect, it } from "vitest";

import {
  PALETTES,
  isConstructed,
  paletteEntry,
  readPaletteColours,
  withPalette,
  type PaletteId,
} from "../../src/theme/palettes";

const CSS = import.meta.glob("../../src/**/*.css", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

// Import order, which is also cascade order: `index.css` pulls the palettes in
// first, so its own `:root.dark` sits after every palette block.
const PALETTES_CSS = CSS["../../src/theme/palettes.css"] ?? "";
const INDEX_CSS = CSS["../../src/index.css"] ?? "";

// ── Reading the stylesheets ──────────────────────────────────────────────────

type Tokens = Record<string, string>;

/** The stylesheet with its prose removed, which is most of these files. */
function code(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Innermost rule blocks: a selector, and a body with no braces left in it. */
function rules(css: string): { selector: string; body: string }[] {
  return [...code(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    // The selector is the last line before the brace: everything above it
    // belongs to the enclosing at-rule, which this deliberately ignores.
    selector: match[1]!.trim().split("\n").pop()!.trim(),
    body: match[2]!,
  }));
}

function declarationsOf(body: string): Tokens {
  const tokens: Tokens = {};
  for (const [, name, value] of body.matchAll(
    /(--color-[\w-]+)\s*:\s*([^;]+);/g,
  )) {
    tokens[name!] = value!.trim();
  }
  return tokens;
}

function declarations(css: string, selector: string): Tokens {
  const block = rules(css).find((rule) => rule.selector === selector);
  return block ? declarationsOf(block.body) : {};
}

/** The body of an at-rule, by brace matching from its opening one. */
function atRuleBody(css: string, prelude: string): string {
  const source = code(css);
  const open = source.indexOf("{", source.indexOf(prelude));
  let depth = 0;
  for (let at = open; at < source.length; at += 1) {
    if (source[at] === "{") depth += 1;
    if (source[at] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, at);
    }
  }
  return "";
}

/** Follow `var(--color-x)` until every value is a colour. */
function resolve(tokens: Tokens): Tokens {
  const out = { ...tokens };
  for (let pass = 0; pass < 5; pass += 1) {
    let changed = false;
    for (const [name, value] of Object.entries(out)) {
      const reference = /^var\((--color-[\w-]+)\)$/.exec(value);
      if (reference && out[reference[1]!]) {
        out[name] = out[reference[1]!]!;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return out;
}

const BASE = declarations(INDEX_CSS, "@theme static");
const ENDPAPER_DARK = declarations(INDEX_CSS, ":root.dark");
/**
 * What `@media (prefers-contrast: more)` does, and in which mode.
 *
 * Read by matching the selectors rather than by naming them, so a rule that
 * loses its scope is applied here in both modes and fails the contract instead
 * of quietly measuring nothing. That was not hypothetical: the light half
 * shipped unscoped, at (0,2,0) after `:root.dark`, and took the dark card's
 * muted ink from 3.00:1 to 1.91:1.
 *
 * Matching is by mode alone, which makes this **stricter than a browser about
 * specificity**: a matched rule is applied over everything, where an unscoped
 * `:root:root` at (0,2,0) really loses to a palette's own dark block at
 * (0,3,0), so only the default palette would break and this reports all seven.
 * The error runs one way and it is the safe one: over-applying can invent a
 * failure but never hide one, because the state those six would really be in
 * is the base state, which the block above measures in full. Do not read this
 * as "what a browser does" for a selector below (0,3,0): there it would claim
 * a preference is honoured on palettes that in fact ignore it.
 */
const MORE_CONTRAST_RULES = rules(
  atRuleBody(INDEX_CSS, "@media (prefers-contrast: more)"),
).map((rule) => {
  const exceptDark = rule.selector.includes(":not(.dark)");
  const onlyDark = rule.selector.replace(":not(.dark)", "").includes(".dark");
  return {
    tokens: declarationsOf(rule.body),
    light: !onlyDark,
    dark: !exceptDark,
  };
});

function moreContrast(mode: "light" | "dark"): Tokens {
  return MORE_CONTRAST_RULES.filter((rule) => rule[mode]).reduce(
    (tokens, rule) => ({ ...tokens, ...rule.tokens }),
    {} as Tokens,
  );
}

function paletteBlock(palette: PaletteId, mode: "light" | "dark"): Tokens {
  const selector =
    mode === "light"
      ? `:root[data-theme="${palette}"]`
      : `:root[data-theme="${palette}"].dark`;
  return declarations(PALETTES_CSS, selector);
}

/**
 * Every token in force for one theme and one mode.
 *
 * The merge order is the cascade, not a convenience. `:root.dark` and
 * `:root[data-theme="x"]` are both specificity (0,2,0) and `index.css` comes
 * second, so in the dark Endpaper's overrides beat a palette's light block;
 * only the palette's own dark block, at (0,3,0), beats them back.
 */
function tokensFor(
  palette: PaletteId,
  mode: "light" | "dark",
  withContrast = false,
): Tokens {
  const light = { ...BASE, ...paletteBlock(palette, "light") };
  const merged =
    mode === "light"
      ? light
      : { ...light, ...ENDPAPER_DARK, ...paletteBlock(palette, "dark") };
  // Last, and outranking everything above it, which is what the padded
  // selectors in that block buy. Modelling it here is the whole reason the
  // regression it once carried was invisible: a rule justified entirely by a
  // specificity argument was the one rule the harness could not resolve.
  return resolve(withContrast ? { ...merged, ...moreContrast(mode) } : merged);
}

// ── Contrast ─────────────────────────────────────────────────────────────────

function channel(value: number): number {
  const srgb = value / 255;
  return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((at) =>
    channel(parseInt(value.slice(at, at + 2), 16)),
  ) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

// ── The contract ─────────────────────────────────────────────────────────────

const PAPER_STEPS = [0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const ACCENT_STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const SEMANTIC_STEPS = [100, 300, 500, 600, 700];

/** Every token a palette block has to state. See the note in `palettes.css`. */
const REQUIRED = [
  ...PAPER_STEPS.map((step) => `--color-paper-${step}`),
  ...ACCENT_STEPS.map((step) => `--color-accent-${step}`),
  "--color-accent-fill",
  "--color-accent-fill-hover",
  "--color-on-accent",
  ...SEMANTIC_STEPS.flatMap((step) => [
    `--color-bloom-${step}`,
    `--color-danger-${step}`,
  ]),
];

interface Pair {
  what: string;
  fg: string;
  bg: string;
  floor: number;
  ceiling?: number;
}

function pair(what: string, fg: string, bg: string, floor: number): Pair {
  return { what, fg: `--color-${fg}`, bg: `--color-${bg}`, floor };
}

/**
 * What the tokens promise, stated as pairs the app really paints.
 *
 * Every entry is a class pairing that exists in `src/`: `text-accent-700` on a
 * card, `text-danger-700` on `bg-danger-100`, and so on. A ramp that passes
 * here is one whose rungs hold the weights they are named for, which is a
 * stronger claim than evenly spaced rungs and a weaker one than "every pairing
 * in the app is legible".
 *
 * It is deliberately not the second, and the gap it used to leave is closed
 * elsewhere rather than here. Dark hover was the concentration of it: twelve
 * sites wrote `hover:text-accent-800` with no `dark:` variant and landed
 * between 1.36 and 2.85 on the dark card. All twelve are repaired, so the rule
 * that holds them shipped with no exemption list, in
 * `frontend/tests/houseRules.test.ts`. It is there and not here because it is
 * a rule about call sites, and this file measures tokens.
 *
 * The pairs those repairs use are already below: `accent-300` and `danger-300`
 * on the dark card. That is the arrangement to preserve. A repair that reached
 * for a step this file does not measure would be a call site passing a rule by
 * pointing at a token nobody checks.
 */
function lightPairs(): Pair[] {
  const semantic = (ramp: string) => [
    pair(`${ramp}-500 text on the card`, `${ramp}-500`, "paper-0", 4.5),
    pair(`${ramp}-500 text on the page`, `${ramp}-500`, "paper-50", 4.5),
    pair(`${ramp}-600 text on the card`, `${ramp}-600`, "paper-0", 4.5),
    pair(`${ramp}-600 text on the page`, `${ramp}-600`, "paper-50", 4.5),
    pair(`${ramp}-600 text on its tint`, `${ramp}-600`, `${ramp}-100`, 4.5),
    pair(`${ramp}-700 ink on its tint`, `${ramp}-700`, `${ramp}-100`, 4.5),
    pair(`${ramp}-700 ink on the card`, `${ramp}-700`, "paper-0", 4.5),
  ];
  return [
    // The rung contract.
    pair("paper-400", "paper-400", "paper-0", 3.0),
    pair("paper-500", "paper-500", "paper-0", 4.5),
    pair("paper-700", "paper-700", "paper-0", 6.0),
    pair("paper-900", "paper-900", "paper-0", 7.0),
    // Body and muted text, on all three surfaces they sit on.
    pair("body text on the page", "paper-900", "paper-50", 7.0),
    pair("muted text on the card", "paper-600", "paper-0", 4.5),
    pair("muted text on the page", "paper-600", "paper-50", 4.5),
    pair("muted text on the sunken tier", "paper-600", "paper-100", 4.5),
    pair("secondary text on the card", "paper-800", "paper-0", 4.5),
    // The "did not finish" pill, which is the one status pill drawn from the
    // paper ramp rather than a semantic one. Giving up on a book is neither an
    // error nor an achievement, so it must not borrow danger or bloom, and it
    // still has to be readable at pill size.
    pair("the did-not-finish pill", "paper-800", "paper-200", 4.5),
    // The accent, at the rungs that carry text.
    pair("link on the card", "accent-700", "paper-0", 4.5),
    pair("link on the page", "accent-700", "paper-50", 4.5),
    pair("accent text on the card", "accent-600", "paper-0", 4.5),
    pair("chip ink on its tint", "accent-800", "accent-100", 4.5),
    pair("chip ink on accent-50", "accent-800", "accent-50", 4.5),
    // The fill pairing, all three tokens of it.
    pair("on-accent on the fill", "on-accent", "accent-fill", 4.5),
    pair("on-accent on the hover", "on-accent", "accent-fill-hover", 4.5),
    // Focus and selection, which WCAG 1.4.11 puts at 3:1.
    pair("the focus ring on the page", "accent-500", "paper-50", 3.0),
    pair("the focus ring on the card", "accent-500", "paper-0", 3.0),
    ...semantic("bloom"),
    ...semantic("danger"),
  ];
}

function darkPairs(): Pair[] {
  const semantic = (ramp: string) => [
    pair(`${ramp}-300 text on the card`, `${ramp}-300`, "paper-900", 4.5),
    pair(`${ramp}-300 text on the page`, `${ramp}-300`, "paper-950", 4.5),
    pair(`${ramp}-500 text on the card`, `${ramp}-500`, "paper-900", 4.5),
    pair(`${ramp}-100 ink on the banner`, `${ramp}-100`, `${ramp}-700`, 4.5),
  ];
  return [
    pair("paper-600", "paper-600", "paper-900", 3.0),
    pair("paper-500", "paper-500", "paper-900", 4.5),
    pair("paper-400", "paper-400", "paper-900", 6.0),
    pair("paper-300", "paper-300", "paper-900", 7.0),
    pair("body text on the card", "paper-200", "paper-900", 7.0),
    pair("the did-not-finish pill", "paper-200", "paper-800", 4.5),
    pair("muted text on the page", "paper-400", "paper-950", 6.0),
    pair("accent text on the card", "accent-400", "paper-900", 4.5),
    pair("accent text on the page", "accent-400", "paper-950", 4.5),
    pair("accent hover text on the card", "accent-300", "paper-900", 4.5),
    pair("chip ink on the card", "accent-200", "paper-900", 4.5),
    pair("chip ink on its own tint", "accent-200", "accent-950", 4.5),
    pair("on-accent on the fill", "on-accent", "accent-fill", 4.5),
    pair("on-accent on the hover", "on-accent", "accent-fill-hover", 4.5),
    pair("the focus ring on the page", "accent-500", "paper-950", 3.0),
    pair("the focus ring on the card", "accent-500", "paper-900", 3.0),
    ...semantic("bloom"),
    ...semantic("danger"),
  ];
}

function measure(tokens: Tokens, pairs: Pair[]): string[] {
  return pairs.flatMap(({ what, fg, bg, floor }) => {
    const foreground = tokens[fg];
    const background = tokens[bg];
    if (!foreground || !background) return [`${what}: ${fg} or ${bg} is missing`];
    const ratio = contrast(foreground, background);
    return ratio >= floor
      ? []
      : [`${what}: ${ratio.toFixed(2)}:1 against ${floor} (${foreground} on ${background})`];
  });
}

const THEMES = PALETTES.map((palette) => palette.id);
const MODES = ["light", "dark"] as const;

describe("the stylesheets are actually read", () => {
  it("finds both files", () => {
    // Under `css: false` a raw import of a stylesheet is an empty string, and
    // every measurement below would then pass by measuring nothing.
    expect(INDEX_CSS.length).toBeGreaterThan(1000);
    expect(PALETTES_CSS.length).toBeGreaterThan(1000);
    expect(Object.keys(BASE).length).toBeGreaterThan(30);
  });
});

describe("the catalogue and the stylesheet agree", () => {
  it("every palette but the default has both blocks", () => {
    const missing = THEMES.filter((id) => id !== "endpaper").flatMap((id) =>
      MODES.filter((mode) => Object.keys(paletteBlock(id, mode)).length === 0).map(
        (mode) => `${id} ${mode}`,
      ),
    );
    expect(missing).toEqual([]);
  });

  it("the default palette has no block, because it is the tokens themselves", () => {
    expect(paletteBlock("endpaper", "light")).toEqual({});
    expect(paletteBlock("endpaper", "dark")).toEqual({});
  });

  it("no block belongs to a palette the catalogue does not list", () => {
    const declared = new Set(
      // The comments are stripped first: this file's header explains the
      // cascade using `[data-theme="x"]` as the example, and a scan that read
      // prose would report a palette called x.
      [...code(PALETTES_CSS).matchAll(/data-theme="([^"]+)"/g)].map(
        (match) => match[1]!,
      ),
    );
    expect([...declared].filter((id) => !THEMES.includes(id as PaletteId))).toEqual(
      [],
    );
  });

  it("every mode is offered by every palette", () => {
    // Mode is an independent axis and no palette may disable it. Nord's light
    // member is constructed rather than published, which the picker says and
    // the catalogue records, but it exists.
    for (const palette of PALETTES) {
      for (const mode of MODES) {
        expect(Object.keys(tokensFor(palette.id, mode)).length).toBeGreaterThan(30);
      }
    }
  });
});

describe("every palette block states every token", () => {
  // Not tidiness. A dark block that leaves out a token because it matches the
  // light block above it gets Endpaper's dark value instead, silently, because
  // `:root.dark` outranks a light palette block by source order.
  for (const palette of THEMES.filter((id) => id !== "endpaper")) {
    for (const mode of MODES) {
      it(`${palette} ${mode}`, () => {
        const declared = Object.keys(paletteBlock(palette, mode));
        expect(REQUIRED.filter((token) => !declared.includes(token))).toEqual([]);
      });
    }
  }
});

describe("every theme and mode clears the contract", () => {
  for (const palette of THEMES) {
    for (const mode of MODES) {
      it(`${palette} ${mode}`, () => {
        const tokens = tokensFor(palette, mode);
        const failures = measure(
          tokens,
          mode === "light" ? lightPairs() : darkPairs(),
        );
        expect(failures).toEqual([]);
      });
    }
  }
});

describe("and clears it again with more contrast asked for", () => {
  // The same fourteen, with the media block applied. A preference for more
  // contrast that moved a rung the wrong way would be the worst possible
  // regression: it is invisible to everybody who did not ask for it, and it
  // lands only on the reader who did.
  for (const palette of THEMES) {
    for (const mode of MODES) {
      it(`${palette} ${mode}`, () => {
        const tokens = tokensFor(palette, mode, true);
        const failures = measure(
          tokens,
          mode === "light" ? lightPairs() : darkPairs(),
        );
        expect(failures).toEqual([]);
      });
    }
  }

  it("moves the muted ink up, in the mode it belongs to and no other", () => {
    for (const palette of THEMES) {
      const light = tokensFor(palette, "light", true);
      const dark = tokensFor(palette, "dark", true);
      expect(light["--color-paper-600"]).toBe(
        tokensFor(palette, "light")["--color-paper-700"],
      );
      expect(dark["--color-paper-400"]).toBe(
        tokensFor(palette, "dark")["--color-paper-300"],
      );
      // The half that regressed: unscoped, the light rule outranked
      // `:root.dark` and took the dark card's muted ink from 3.00:1 to 1.91:1.
      expect(dark["--color-paper-600"]).toBe(
        tokensFor(palette, "dark")["--color-paper-600"],
      );
    }
  });
});

describe("the body ink stays inside the anti-glare band", () => {
  // Near white on near black is around 18:1, which is past legible and into
  // glare: a grid of book titles reads as a row of lightbulbs. `index.css`
  // reasons about the same band for the default palette.
  for (const palette of THEMES) {
    it(`${palette} dark`, () => {
      const tokens = tokensFor(palette, "dark");
      const ratio = contrast(tokens["--color-paper-200"]!, tokens["--color-paper-950"]!);
      expect(ratio).toBeGreaterThanOrEqual(8.5);
      expect(ratio).toBeLessThanOrEqual(16);
    });
  }
});

describe("a ramp only ever goes one way", () => {
  // A corrected rung can otherwise overtake its neighbour, and a ramp that
  // reverses in the middle no longer carries the hierarchy it exists for.
  for (const palette of THEMES) {
    for (const mode of MODES) {
      it(`${palette} ${mode}`, () => {
        const tokens = tokensFor(palette, mode);
        const reversals: string[] = [];
        const walk = (ramp: string, steps: number[]) => {
          for (let at = 1; at < steps.length; at += 1) {
            const lighter = tokens[`--color-${ramp}-${steps[at - 1]}`]!;
            const darker = tokens[`--color-${ramp}-${steps[at]}`]!;
            if (luminance(darker) >= luminance(lighter)) {
              reversals.push(`${ramp}-${steps[at - 1]} to ${ramp}-${steps[at]}`);
            }
          }
        };
        walk("paper", PAPER_STEPS);
        walk("accent", ACCENT_STEPS);
        walk("bloom", SEMANTIC_STEPS);
        walk("danger", SEMANTIC_STEPS);
        expect(reversals).toEqual([]);
      });
    }
  }
});

describe("the card and the page are distinguishable", () => {
  for (const palette of THEMES) {
    it(`${palette}`, () => {
      const light = tokensFor(palette, "light");
      const dark = tokensFor(palette, "dark");
      // Small on purpose: the default palette's own two surfaces are 1.04:1
      // apart, and a card that announces itself is a card that fights the page.
      // The floor is only that they are not the same colour.
      expect(
        contrast(light["--color-paper-0"]!, light["--color-paper-50"]!),
      ).toBeGreaterThan(1.01);
      expect(
        contrast(dark["--color-paper-900"]!, dark["--color-paper-950"]!),
      ).toBeGreaterThan(1.01);
    });
  }
});

describe("more contrast is honoured on every palette, not only the default", () => {
  it("outranks a palette block, and the light half stays in the light", () => {
    // `:root:root` is doubled so it beats `:root[data-theme="x"]`, which is
    // (0,2,0). Written once it would apply on Endpaper and be silently ignored
    // on the other six. `:not(.dark)` is the other half: without it the light
    // rule also outranks `:root.dark`, which sits before it in the same layer,
    // and rewrites the dark card's muted ink from 3.00:1 to 1.91:1.
    const media = INDEX_CSS.slice(
      INDEX_CSS.indexOf("@media (prefers-contrast: more)"),
    );
    expect(media).toContain(":root:root:not(.dark) {");
    expect(media).toContain(":root:root.dark {");
  });

  it("moves the muted ink up a rung rather than inventing one", () => {
    expect(moreContrast("light")["--color-paper-600"]).toBe(
      "var(--color-paper-700)",
    );
    expect(moreContrast("dark")["--color-paper-400"]).toBe(
      "var(--color-paper-300)",
    );
  });

  it("changes something in both modes", () => {
    // A block whose selectors stopped matching would make every measurement
    // above pass by changing nothing.
    expect(Object.keys(moreContrast("light")).length).toBe(1);
    expect(Object.keys(moreContrast("dark")).length).toBe(1);
  });
});

describe("the catalogue", () => {
  it("names the member of a palette upstream gives a name to", () => {
    // Latte, Mocha, Dawn, Moon. The docs and the stylesheet comments both used
    // these before any field held them, so the picker had nothing to print.
    expect(paletteEntry("catppuccin").modes).toEqual({
      light: "Latte",
      dark: "Mocha",
    });
    expect(paletteEntry("rosepine").modes).toEqual({
      light: "Dawn",
      dark: "Moon",
    });
  });

  it("names no member upstream leaves unnamed", () => {
    // "Gruvbox light" is not a title anybody uses, and inventing one would put
    // a name in the picker that appears nowhere upstream.
    expect(paletteEntry("gruvbox").modes).toEqual({ light: null, dark: null });
    expect(paletteEntry("endpaper").modes).toEqual({ light: null, dark: null });
  });

  it("records Nord's light member as the only constructed one", () => {
    const constructed = PALETTES.filter(
      (palette) => palette.constructed.length > 0,
    ).map((palette) => palette.id);

    expect(constructed).toEqual(["nord"]);
    expect(isConstructed("nord", "light")).toBe(true);
    expect(isConstructed("nord", "dark")).toBe(false);
  });

  it("credits every palette that is not this project's own", () => {
    // The licence notices on the picker are generated from this, so a palette
    // added without one ships uncredited.
    for (const palette of PALETTES) {
      if (palette.id === "endpaper") continue;
      expect(palette.attribution, palette.id).toMatch(/MIT$/);
    }
  });
});

describe("withPalette", () => {
  it("puts the palette back after reading", () => {
    // The picker reads seven palettes on a page that can only have one.
    // Leaving the last one on the document would repaint the whole app.
    document.documentElement.dataset.theme = "gruvbox";

    withPalette("nord", () => {
      expect(document.documentElement.dataset.theme).toBe("nord");
    });

    expect(document.documentElement.dataset.theme).toBe("gruvbox");
  });

  it("puts it back even when the read throws", () => {
    document.documentElement.dataset.theme = "gruvbox";

    expect(() =>
      withPalette("nord", () => {
        throw new Error("no");
      }),
    ).toThrow();

    expect(document.documentElement.dataset.theme).toBe("gruvbox");
  });

  it("leaves a document with no palette without one", () => {
    delete document.documentElement.dataset.theme;

    withPalette("nord", () => undefined);

    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("reads one entry per palette", () => {
    const colours = readPaletteColours("light");

    expect(Object.keys(colours).sort()).toEqual(
      PALETTES.map((palette) => palette.id).sort(),
    );
  });

  it("hands back an empty string for a token nothing declares", () => {
    // No stylesheet is loaded here, so only the six tokens `setup.ts` writes
    // resolve. That is the case the picker has to survive: an empty
    // `background` is transparent and an empty `fill` is black, so a tile with
    // a gap in it draws nothing at all rather than part of itself.
    expect(readPaletteColours("light").endpaper.card).toBe("");
  });
});
