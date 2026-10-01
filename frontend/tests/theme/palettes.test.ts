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

import { ReadStatus } from "../../src/api/generated/model";
import { STATUS_STYLES } from "../../src/pages/types";

import {
  PALETTES,
  isConstructed,
  paletteEntry,
  readPaletteColours,
  withPalette,
  type PaletteId,
} from "../../src/theme/palettes";
import { stylesheetText } from "../sourceModules";

// Import order, which is also cascade order: `index.css` pulls the palettes in
// first, so its own `:root.dark` sits after every palette block.
//
// **Asked for by name from the one enumeration of `src/`**, which holds the
// stylesheets as the half of the tree that is not a module and refuses the
// pair when it is not what the tree carries. A lookup defaulting to the empty
// string used to stand here, and an empty stylesheet satisfies most of the
// rules below.
const PALETTES_CSS = stylesheetText("theme/palettes.css");
const INDEX_CSS = stylesheetText("index.css");

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
 * (0,3,0), so only the default palette would break and this reports all ten.
 * The error runs one way and it is the safe one: over-applying can invent a
 * failure but never hide one, because the state those nine would really be in
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

/**
 * CIE L*, because a contrast ratio says nothing useful about two adjacent
 * surfaces. `paper-100` on `paper-200` is 1.035:1 on Rose Pine light and
 * 1.272:1 on solarized: both round to "the same", while their lightness
 * separation differs by a factor of six and only one of them reads as two
 * surfaces. Yn is 1, so the argument is the relative luminance above.
 */
function lightness(hex: string): number {
  const y = luminance(hex);
  return y > 0.008856 ? 116 * Math.cbrt(y) - 16 : 903.3 * y;
}

function separation(a: string, b: string): number {
  return Math.abs(lightness(a) - lightness(b));
}

/**
 * One colour painted over another at `alpha`, which is what a `/70` utility
 * does and what a pair of tokens cannot express.
 *
 * Blended in sRGB, the space a compositor works in, and quantised to eight bits
 * because that is what reaches the screen. Measured against the same blend left
 * in floating point, the ten palettes move by 0.0011 (everforest) to 0.0112
 * (ayu) and their order does not change. So the quantising can decide the
 * second decimal and never the first, which is why no arm below reads a figure
 * and why a figure taken off this instrument is worth one decimal. It is here
 * because the only pairing in this app drawn at less than full opacity is the
 * one pairing that sits below the floor, so an instrument that cannot composite
 * measures the pill it is least entitled to assume about.
 */
function blend(over: string, under: string, alpha: number): string {
  const parts = (hex: string): number[] =>
    [0, 2, 4].map((at) => parseInt(hex.replace("#", "").slice(at, at + 2), 16));
  const [top, bottom] = [parts(over), parts(under)];
  return `#${top
    .map((value, at) =>
      Math.round(value * alpha + bottom[at]! * (1 - alpha))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
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
 * sites wrote `hover:text-accent-800` with no `dark:` variant, which is a rung
 * that clears the text floor on a light card and fails it on every dark one.
 * All twelve are repaired, so the rule that holds them shipped with no
 * exemption list, in `frontend/tests/houseRules.test.ts`. It is there and not
 * here because it is a rule about call sites, and this file measures tokens.
 * `the hover a dark ramp makes illegible` below is where that rung is
 * recomputed; no band is quoted for it anywhere.
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
    // The About card's badge row, which is drawn rather than fetched: no
    // shields.io, because `img-src` comes from the cover hosts and a badge is
    // decoration. The label cell reuses the pill's pairing above; the value
    // cell sits one rung lighter so the split reads without a border, and a
    // link's value cell carries the accent and an underline.
    pair("a badge label", "paper-800", "paper-200", 4.5),
    pair("a badge value", "paper-800", "paper-100", 4.5),
    pair("a badge link", "accent-800", "paper-100", 4.5),
    pair("a badge link, pointed at", "accent-900", "paper-100", 4.5),
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
    // The badge row again. `paper-700` is the lightest surface in a dark ramp
    // and so the hardest of the two cells, which is why the value cell and the
    // link ink are both measured against it rather than against the label's.
    pair("a badge label", "paper-200", "paper-800", 4.5),
    pair("a badge value", "paper-200", "paper-700", 4.5),
    pair("a badge link", "accent-200", "paper-700", 4.5),
    pair("a badge link, pointed at", "accent-100", "paper-700", 4.5),
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
    if (!foreground || !background)
      return [`${what}: ${fg} or ${bg} is missing`];
    const ratio = contrast(foreground, background);
    return ratio >= floor
      ? []
      : [
          `${what}: ${ratio.toFixed(2)}:1 against ${floor} (${foreground} on ${background})`,
        ];
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
      MODES.filter(
        (mode) => Object.keys(paletteBlock(id, mode)).length === 0,
      ).map((mode) => `${id} ${mode}`),
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
    expect(
      [...declared].filter((id) => !THEMES.includes(id as PaletteId)),
    ).toEqual([]);
  });

  it("every mode is offered by every palette", () => {
    // Mode is an independent axis and no palette may disable it. Nord's light
    // member is constructed rather than published, which the picker says and
    // the catalogue records, but it exists.
    for (const palette of PALETTES) {
      for (const mode of MODES) {
        expect(Object.keys(tokensFor(palette.id, mode)).length).toBeGreaterThan(
          30,
        );
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
        expect(REQUIRED.filter((token) => !declared.includes(token))).toEqual(
          [],
        );
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
  // The same twenty, with the media block applied. A preference for more
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
      const ratio = contrast(
        tokens["--color-paper-200"]!,
        tokens["--color-paper-950"]!,
      );
      expect(ratio).toBeGreaterThanOrEqual(8.5);
      expect(ratio).toBeLessThanOrEqual(16);
    });
  }
});

describe("the About card's badge cells read apart", () => {
  // The defect this was written for: the row's two cells are `paper-200` and
  // `paper-100` in light, which are 1.32 CIE L* apart on Rose Pine, 2.54 on
  // Kanagawa and 3.14 to 8.89 on the other eight, so on those two a badge drew
  // as a single flat chip. The same round had rejected an accent cell at 1.13:1 in the dark for
  // exactly that, which is what makes this mechanical rather than a matter of
  // taste. The fix is a hairline, and what has to hold is that the hairline is
  // visible against both cells it sits between.
  //
  // 4.0 is the floor, and it is anchored to a hairline this app already ships
  // rather than chosen. `CollapsibleSection`'s own 1px divider,
  // `border-paper-100 dark:border-paper-800`, measures 4.11 L* at worst light
  // (endpaper) and 4.25 at worst dark (nord); the card border is 5.64 and 4.25.
  // A floor below that would admit a separator fainter than the faintest line
  // the app treats as visible, which is exactly what an eleventh palette would
  // present. Measured worst with the tokens as they ship: 4.85 in light
  // (kanagawa, the separator against the label cell) and 12.07 in dark
  // (kanagawa, against the value cell), so this moves no shipped value.
  const FLOOR = 4.0;

  for (const palette of THEMES) {
    it(`${palette} light`, () => {
      const tokens = tokensFor(palette, "light");
      const rule = tokens["--color-paper-300"]!;
      const cells = ["--color-paper-200", "--color-paper-100"];
      for (const cell of cells) {
        expect(separation(rule, tokens[cell]!)).toBeGreaterThanOrEqual(FLOOR);
      }
    });

    it(`${palette} dark`, () => {
      const tokens = tokensFor(palette, "dark");
      const rule = tokens["--color-paper-600"]!;
      const cells = ["--color-paper-800", "--color-paper-700"];
      for (const cell of cells) {
        expect(separation(rule, tokens[cell]!)).toBeGreaterThanOrEqual(FLOOR);
      }
    });
  }
});

describe("the hairline the badge floor is anchored to stays visible", () => {
  // `border-paper-100 dark:border-paper-800`, the app's own 1px divider, at
  // five call sites including `CollapsibleSection`. The badge floor above is
  // 4.0 CIE L* *because* this is the faintest line the app treats as visible,
  // so a palette that drew this fainter than 4.0 would not fail anything and
  // would quietly retire the argument the floor rests on.
  //
  // That is not hypothetical. Ayu Dark publishes three surfaces inside 4.61
  // CIE L* in total, and a ladder built from all three put this at 3.02. The
  // palette takes two of them and generates the rest, and this is what says so.
  // Worst as it ships: 4.11 in light on endpaper, 4.25 in dark on nord.
  const FLOOR = 4.0;

  for (const palette of THEMES) {
    // Named for the divider rather than for the palette, because three other
    // blocks in this file name their cases after the palette alone and a
    // failure that reads "ayu" says nothing about which rule noticed.
    it(`${palette}, the 1px divider in both modes`, () => {
      expect(
        separation(
          tokensFor(palette, "light")["--color-paper-100"]!,
          tokensFor(palette, "light")["--color-paper-0"]!,
        ),
      ).toBeGreaterThanOrEqual(FLOOR);
      expect(
        separation(
          tokensFor(palette, "dark")["--color-paper-800"]!,
          tokensFor(palette, "dark")["--color-paper-900"]!,
        ),
      ).toBeGreaterThanOrEqual(FLOOR);
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
              reversals.push(
                `${ramp}-${steps[at - 1]} to ${ramp}-${steps[at]}`,
              );
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

/**
 * The hover a dark ramp makes illegible.
 *
 * **The reason `houseRules.test.ts::a dark hover state is stated, never
 * inherited` exists, computed rather than quoted.** That rule refuses
 * `hover:text-` written without a `dark:hover:` beside it. What makes it worth
 * a guard is that the accent ramp runs the other way in the dark: `accent-800`
 * is the darkest usable ink on a light card and is nearly the card itself on a
 * dark one, so one hover spelled once is legible at rest and gone while
 * pointed at.
 *
 * **A band was written into that comment and had drifted in both halves**, the
 * palette count beside it and the number itself, which is what a figure in
 * prose does: it is copied forward and never re-derived. This states the
 * property instead and computes it here, over `PALETTES`, so a palette added
 * tomorrow is measured rather than assumed. Nothing quotes a range.
 *
 * **Both directions, because either alone passes on a ramp that has stopped
 * being a ramp.** A dark `accent-800` bleached to the same value as the light
 * one would clear the floor in dark and fail nothing if only the dark arm were
 * here; an accent-800 dropped to the card's own colour in light would fail
 * nothing if only the light arm were.
 */
describe("the hover a dark ramp makes illegible", () => {
  // The floor every text pair in the contract above is held to.
  const FLOOR = 4.5;

  it("clears the text floor on every light card", () => {
    const cleared = THEMES.filter((palette) => {
      const light = tokensFor(palette, "light");
      return (
        contrast(light["--color-accent-800"]!, light["--color-paper-0"]!) >=
        FLOOR
      );
    });

    expect(cleared).toEqual(THEMES);
  });

  it("fails it on every dark card, which is why the dark hover is stated", () => {
    const legible = THEMES.filter((palette) => {
      const dark = tokensFor(palette, "dark");
      return (
        contrast(dark["--color-accent-800"]!, dark["--color-paper-900"]!) >=
        FLOOR
      );
    });

    // Named rather than counted: a palette that put this pair over the floor
    // would weaken the house rule's reason, and the fix is to argue it there
    // rather than to relax this.
    expect(legible).toEqual([]);
  });

  it("is reading a token that exists, in both modes", () => {
    // **The dark arm passes on a value that is not a colour**, and that is the
    // one direction neither arm above can see. A token left as
    // `var(--color-accent-800)` by a chain `resolve` gave up on parses to NaN,
    // every comparison against NaN is false, so the palette is filtered out of
    // `legible` and the arm goes green having measured nothing. The light arm
    // fails loudly on the same input, which is why only one of the two needs
    // saying and both are covered by asserting the value here.
    for (const palette of THEMES)
      for (const mode of MODES)
        expect(tokensFor(palette, mode)["--color-accent-800"]).toMatch(
          /^#[0-9a-f]{6}$/i,
        );
  });
});

/**
 * The two rungs a delete control cannot rest on.
 *
 * **The reason `NoteList` and `QuoteList` state four tiers between them for one
 * button**, computed rather than quoted. Those two spell
 * `text-danger-500 hover:text-danger-600 dark:text-danger-300
 * dark:hover:text-danger-100`, which reads as belt and braces until the two
 * rungs missing from it are measured: `danger-300` is the tint tier and is not
 * ink on a light card, and `danger-600` is ink on a light card and is nearly
 * the dark card itself.
 *
 * So the resting tier cannot be inherited from the tint and the dark hover
 * cannot be inherited from the light one, and neither of those is visible in a
 * diff. The four tiers the two components do use are all in the contract above.
 *
 * A band was written into both comments and had drifted in both halves, the
 * palette count and the number, which is what a figure in prose does. This
 * states the property and computes it over `PALETTES`, so a palette added
 * tomorrow is measured rather than assumed. Nothing quotes a range.
 */
describe("the rungs a delete control cannot rest on", () => {
  // The floor every text pair in the contract above is held to.
  const FLOOR = 4.5;

  it("fails the text floor at danger-300 on every light card", () => {
    const legible = THEMES.filter((palette) => {
      const light = tokensFor(palette, "light");
      return (
        contrast(light["--color-danger-300"]!, light["--color-paper-0"]!) >=
        FLOOR
      );
    });

    expect(legible).toEqual([]);
  });

  it("fails it at danger-600 on every dark card, which is why the dark hover is stated", () => {
    const legible = THEMES.filter((palette) => {
      const dark = tokensFor(palette, "dark");
      return (
        contrast(dark["--color-danger-600"]!, dark["--color-paper-900"]!) >=
        FLOOR
      );
    });

    expect(legible).toEqual([]);
  });

  it("is reading tokens that exist, in both modes", () => {
    // A token left unresolved parses to NaN, every comparison against NaN is
    // false, and both arms above then go green having measured nothing. This is
    // the half that notices, and it is the same trap the accent arms carry.
    //
    // **All four tokens, not the two the arms are named for.** This listed the
    // two `danger` rungs and left the cards they are measured against out, so
    // the failure it claims to cover was open on half its own inputs.
    for (const palette of THEMES)
      for (const mode of MODES)
        for (const token of [
          "danger-300",
          "danger-600",
          "paper-0",
          "paper-900",
        ])
          expect(tokensFor(palette, mode)[`--color-${token}`]).toMatch(
            /^#[0-9a-f]{6}$/i,
          );
  });
});

/**
 * The status pill's ink, as it actually draws.
 *
 * **The one pairing in this app that is below the floor on purpose.** The
 * `unread` pill is `bg-paper-200/70` with `text-paper-600`, so the ink sits on
 * a tint composited over the card rather than on either token, and the pairs
 * above cannot see it. `Home/components/BookList.tsx` takes plain muted text
 * instead of the pill for the same reason, and `pages/types.ts` records the
 * pill as pre-existing and unchanged.
 *
 * Computed rather than quoted, for the reason the rest of this file is: the
 * figures were written into three comments and copied forward past the palette
 * count they were taken over. `docs/decisions.md` carries the numbers, and the
 * table it carries them in is held against this file by
 * `the contrast table in docs/decisions.md` above.
 *
 * **The pill's shape is imported, not read out of a module's text.**
 * `STATUS_STYLES` is exported from `src/pages/types.ts`, and the two rungs, the
 * tint and the opacity are read off the value, so a pill respelled in any way
 * that paints the same thing is still measured rather than leaving this
 * describe's name true of nothing. It was a copy of a class string until both
 * critic seats found it independently: at `/40` instead of `/70` every arm
 * below stayed green. Replacing that copy with a pair of patterns over the
 * module's text was the same reading one level down, and every spelling those
 * patterns refused was an artefact of reading text rather than a value.
 *
 * **What an import cannot see is whether the table is still what draws.** A
 * card computing its pill per prop would leave every arm here measuring
 * something nobody paints. `tests/pages/components/BookCard.test.tsx::draws the
 * %s pill from the shared table` is what closes that, and it is the only
 * reason this rule can be an import at all.
 *
 * ## What this rule sees, and what goes past it
 *
 * Written down because it was argued to here over several rounds and the
 * arguments are worth more than the conclusion. **A narrowing is a decision;
 * a hole is a thing nobody has closed.** They are separated on purpose: the
 * first list is not work waiting to be done and the second is.
 *
 * **Seen.** The two rows of the table whose pill is on the paper ramp, read
 * by import from `src/pages/types.ts` and not out of any module's text, so
 * the order of the pair, a variant between them and any further utility are
 * all free. Exactly one background utility and exactly one ramped ink, or a
 * refusal naming both. The tint's opacity, absent meaning 1, which is the
 * direction that cannot read the contrast higher than it draws.
 *
 * **Narrowed on purpose.**
 *
 * - **Light mode only.** Every ratio here reads `tokensFor(palette, "light")`,
 *   so the `dark:` half of each pill is measured by nothing. Pre-existing,
 *   and named here rather than left for a reader to infer from the code.
 * - **Two rows of five.** The other three are bloom, amber and accent. They
 *   are not read, and handed to the reader one is refused by name rather
 *   than measured as if it were paper.
 * - **The floor arm is an existence claim.** A repaint that lightens the tint
 *   and still fails on some palette leaves it green; the crossing is between
 *   `/40` and `/10`. Pinning it tighter puts the class string in a second
 *   place, which is what moving the table removed.
 * - **A `bg-` utility that paints nothing counts as a background.** The
 *   gradient is the live member of that family here and it is not the only
 *   member: the same prefix carries layout utilities that set a size, a
 *   position or a repeat rather than a colour, and any of them beside a
 *   colour would be refused as a second background. None is written on a
 *   pill today. Taken anyway on the direction rather than the count, and
 *   that is the argument that carries it: a refused legitimate pair is loud,
 *   an uncounted second background is silent, and three gradient sites would
 *   not justify the narrowing on their own.
 *
 * **Open, and these are holes rather than decisions.**
 *
 * - **A rungless ink is counted as nothing.** `text-` is sizing and alignment
 *   as well as colour, so no rule over the prefix separates them, and
 *   `text-white` or `text-on-accent` beside the paper ink is not seen. The
 *   background side has no such problem and was widened; this side could not
 *   be. It is armed as what happens, not as what should.
 * - **Only the class list is read, by both this rule and the card's arm.**
 *   The strongest shape that hides in there is an **inline style** on the
 *   pill, which beats every class unconditionally rather than by stylesheet
 *   order, so it is worse than the second background this round was spent
 *   on and neither guard would see it. A colour reaching the pill from a
 *   parent, or from CSS that is not one of these utilities, is the same hole
 *   one step weaker.
 * - **The card's arm compares variant prefixed tokens** where this rule
 *   discards them, so a `hover:` or `focus:` colour added to the card and
 *   not to the table would redden there although this rule would ignore it.
 *   Stricter than the rule it serves, in the refusing direction, and zero
 *   cost today because no pill carries one. The `%s` is in the label that arm
 * writes, which is driven over every status.
 *
 * **That pointer was wrong for one round, and it is the same shape as the copy
 * two paragraphs up.** The arm was renamed when it grew from one status to all
 * of them, and the two sentences citing it by name, here and at the table in
 * `src/pages/types.ts`, did not move: a name in a second place goes stale the
 * round somebody changes the first. Spelled with the `%s` it is greppable
 * against the source rather than against one expansion of it, which is the
 * cheapest form of not having a second home.
 *
 * **There is deliberately no arm for "the pill reads worse than the ink on the
 * card".** The tint is a lighter rung of the same ramp, so the blend lands
 * between the card and the tint and the comparison is settled before it is
 * measured. `a ramp only ever goes one way` is what holds the ramp descending;
 * the step from there to a blended luminance is per channel and no rule states
 * it, which is why this is a note about an arm worth nothing rather than a
 * claim that another arm already covers it.
 */
describe("the status pill's ink, as it draws", () => {
  const FLOOR = 4.5;

  /**
   * A Tailwind variant, which is a token carrying a `:` outside brackets.
   *
   * **The property, not a list of variant names.** `dark:`, `hover:` and
   * `focus:` are three members of an open set, and a rule naming them goes
   * quiet on the fourth. What closes the set is the grammar: a variant is a
   * prefix ended by a colon, and the only colon that is not one sits inside an
   * arbitrary value.
   *
   * **The bracket exclusion is a fence here and not a live case**, which is
   * the part worth writing down. Arbitrary values are live in this tree,
   * `aspect-[2/3]` on the card and `shadow-[var(--shadow-soft)]` on the
   * button, and neither carries a colon: no token under `src/` does. So
   * dropping the exclusion would regress nothing today. What it buys is that
   * the first `bg-[color:var(--x)]` anybody writes reads as a base token
   * rather than being silently discarded as a variant.
   */
  const isVariant = (token: string): boolean => {
    let depth = 0;
    for (const character of token) {
      if (character === "[") depth += 1;
      else if (character === "]") depth -= 1;
      else if (character === ":" && depth === 0) return true;
    }
    return false;
  };

  /**
   * What counts as painting the pill's background, and what as inking it.
   *
   * **The refusal is about the utility, the read is about the ramp**, and the
   * two are separate questions: these decide how many things paint, `TINT`
   * and `INK` below decide whether the one that does is on the ramp this rule
   * can measure. Keyed on the ramp, the count saw a second background as
   * nothing and went on measuring the paper half while the stylesheet decided
   * what actually painted.
   *
   * **The two sides are not symmetrical and that is the honest shape of it.**
   *
   * `bg-` is unambiguous: every utility spelled that way paints the
   * background, so the count takes the prefix and a rung is not required.
   * Requiring one was the second version of this hole: `bg-accent-fill` is
   * this app's own primary fill, counted at 55 occurrences under `src/` with
   * 40 more of its hover, and beside a paper background it was invisible.
   *
   * `text-` cannot be widened the same way, because it is overloaded with
   * sizing and alignment: `text-xs` and `text-sm` alone are 666 occurrences,
   * counted the same way, and no rule over the prefix separates a colour from
   * a size. So the ink count requires a rung, and **a rungless ink goes
   * past it**: `text-white` and `text-on-accent` are counted as nothing, and
   * one beside the paper ink is not seen. That is an unclosed hole rather
   * than a narrowing, and the arm below states it rather than the docstring
   * implying both halves are held.
   *
   * **A gradient is counted as a background, deliberately and at a price.**
   * `bg-gradient-to-br` sets a background image rather than a colour, so a
   * gradient laid over a colour is a legitimate pair that this would refuse.
   * Measured: the three gradient sites in `src/` carry no background colour
   * beside them, so nothing here is refused today; and the failure direction
   * matters more than the count, because a refusal is loud and an uncounted
   * second background is silent, which is the whole of this finding.
   */
  const FILL = /^bg-/;
  const TEXT = /^text-[a-z]+-\d+(?:\/\d+)?$/;

  /** The paper ramp, which is the only pair the contrast arms can measure. */
  const TINT = /^bg-paper-(\d+)(?:\/(\d+))?$/;
  const INK = /^text-paper-(\d+)$/;

  interface Pill {
    surface: string;
    ink: string;
    surfaceStep: number;
    inkStep: number;
    opacity: number;
  }

  /**
   * The light mode paper pair a pill paints, read as a set of tokens.
   *
   * **Tokens rather than adjacency**, which is the half of this rule that
   * survives however the string reaches it. Two patterns used to want the tint
   * and the ink adjacent, in that order, double quoted and with the key beside
   * them, so the same pill written the other way round, or with a `dark:`
   * variant between the two, matched nothing while every arm below stayed
   * green on a stale read. Nothing imposes an order on a class string here:
   * there is no Tailwind ordering plugin in this project's dependencies.
   *
   * **Exactly one background and exactly one ink, or refuse, naming the count
   * and what was found.** Taking the first is what the patterns this replaced
   * did, and it asserts something the string cannot say: two unprefixed
   * background utilities are resolved by stylesheet order rather than by the
   * order somebody typed them in, so either choice is a guess dressed as a
   * reading.
   *
   * **Read lazily, and that is not a detail.** This used to run while the
   * describe was collected, which made a refusal a collection error: measured,
   * repainting the unread row onto another ramp gave one failure and **every
   * arm in this file gone**, including the floors for links, buttons, badges
   * and delete controls that have nothing to do with a pill. One repaint
   * silenced the whole theme rule. Behind a memoised call it reddens the arms
   * that read it, by name, and the rest still run.
   *
   * **An absent opacity is 1, recorded rather than assumed.** The
   * `did_not_finish` pill has none. Which way that default errs is what
   * matters and it is measured by `defaults an absent opacity low, never high`
   * below: in light mode the card is the lightest rung, so compositing
   * lightens the surface and raises the ratio, and reading a missing opacity
   * as 1 reports the lowest of that family. A false pass is the one thing this
   * default cannot produce.
   */
  const pillOf = (classes: string): Pill => {
    const base = classes
      .split(/\s+/)
      .filter((token) => token !== "" && !isVariant(token));
    const only = (pattern: RegExp, role: string): string => {
      const found = base.filter((token) => pattern.test(token));
      if (found.length !== 1)
        throw new Error(
          `expected exactly one ${role} token, found ${found.length}: ` +
            `[${found.join(", ")}] in "${classes}"`,
        );
      return found[0]!;
    };
    // Two questions, deliberately answered apart: how many utilities of this
    // family paint, and whether the one that does is on the ramp this rule
    // reads. A pill moved onto another ramp is a design change and is refused
    // here rather than measured as if it were paper.
    const onRamp = (
      token: string,
      ramp: RegExp,
      role: string,
    ): RegExpExecArray => {
      const read = ramp.exec(token);
      if (read === null)
        throw new Error(
          `the ${role} is "${token}", which is not on the paper ramp ` +
            `this rule measures, in "${classes}"`,
        );
      return read;
    };
    const tint = onRamp(only(FILL, "background"), TINT, "background");
    const ink = onRamp(only(TEXT, "ink"), INK, "ink");
    return {
      surface: `--color-paper-${tint[1]}`,
      ink: `--color-paper-${ink[1]}`,
      surfaceStep: Number(tint[1]),
      inkStep: Number(ink[1]),
      opacity: tint[2] === undefined ? 1 : Number(tint[2]) / 100,
    };
  };

  const READ_ONCE = new Map<ReadStatus, Pill>();

  /** The pill a status paints, read on first ask and kept. */
  const pill = (status: ReadStatus): Pill => {
    const had = READ_ONCE.get(status);
    if (had !== undefined) return had;
    const made = pillOf(STATUS_STYLES[status]);
    READ_ONCE.set(status, made);
    return made;
  };

  const UNREAD = () => pill(ReadStatus.unread);
  const FINISHED = () => pill(ReadStatus.did_not_finish);

  /**
   * A whole pill, written out in a string literal in this very module.
   *
   * Under the reader this replaced, a copy of the shape sitting earlier in the
   * text than the real declaration became the subject of every arm below with
   * nothing red anywhere. Under import it is a string and nothing else. It is
   * kept and asserted for that reason: an instrument that goes back to reading
   * text reddens here by name instead of quietly measuring this.
   */
  const A_COPY_OF_A_PILL =
    '[ReadStatus.unread]: "bg-paper-900/10 text-paper-100"';

  /** A paper token the palettes declare, or the name of the one that is not. */
  const paperToken = (tokens: Tokens, name: string): string => {
    const value = tokens[name];
    if (value === undefined)
      throw new Error(`the pill paints ${name}, which no palette declares`);
    return value;
  };

  const pillRatio = (palette: PaletteId): number => {
    const light = tokensFor(palette, "light");
    return contrast(
      paperToken(light, UNREAD().ink),
      blend(
        paperToken(light, UNREAD().surface),
        light["--color-paper-0"]!,
        UNREAD().opacity,
      ),
    );
  };

  const mutedRatio = (palette: PaletteId): number => {
    const light = tokensFor(palette, "light");
    return contrast(paperToken(light, UNREAD().ink), light["--color-paper-0"]!);
  };

  it("is reading the table the card draws", () => {
    // The pairing below is the pill's only if both rungs are rungs. A step no
    // palette declares used to surface as a `TypeError` inside `luminance`; it
    // surfaces in `paperToken` by name instead.
    expect(PAPER_STEPS).toContain(UNREAD().surfaceStep);
    expect(PAPER_STEPS).toContain(UNREAD().inkStep);
    expect(PAPER_STEPS).toContain(FINISHED().surfaceStep);
    expect(PAPER_STEPS).toContain(FINISHED().inkStep);
    // Not `< 1`, which the ordered pair required of the unread pill. A pill
    // painted flat is a repaint these arms measure correctly, and refusing it
    // would be this rule holding a design decision nobody gave it. Zero is the
    // one value that makes the blend return the card and the arms vacuous.
    expect(UNREAD().opacity).toBeGreaterThan(0);
    expect(UNREAD().opacity).toBeLessThanOrEqual(1);
    expect(FINISHED().opacity).toBeGreaterThan(0);
    expect(FINISHED().opacity).toBeLessThanOrEqual(1);
  });

  it("reads the pill as tokens, in any order and past any variant", () => {
    const drawn = {
      surface: "--color-paper-200",
      ink: "--color-paper-600",
      surfaceStep: 200,
      inkStep: 600,
      opacity: 0.7,
    };

    expect(pillOf("bg-paper-200/70 text-paper-600")).toEqual(drawn);
    // The ink first, which paints the same pill and matched nothing before.
    expect(pillOf("text-paper-600 bg-paper-200/70")).toEqual(drawn);
    // A variant between the two, then variants the rule has never been told
    // about, which is what makes the exclusion a property rather than a list.
    expect(pillOf("bg-paper-200/70 dark:bg-paper-800 text-paper-600")).toEqual(
      drawn,
    );
    expect(
      pillOf(
        "hover:bg-paper-300 bg-paper-200/70 focus:text-paper-900 text-paper-600",
      ),
    ).toEqual(drawn);
    // Utilities that are neither, which is most of what a pill carries.
    expect(
      pillOf("text-xs rounded-full bg-paper-200/70 font-medium text-paper-600"),
    ).toEqual(drawn);
  });

  it("tells a colon inside an arbitrary value from a variant prefix", () => {
    // The property the reading is derived from, armed directly, because no
    // token in this tree exercises it: stating it as a fence and arming it as
    // one is the honest pair. `[&:hover]:` is a variant whose own brackets
    // carry a colon, and the colon that makes it one is after the bracket.
    expect(isVariant("dark:bg-paper-800")).toBe(true);
    expect(isVariant("[&:hover]:bg-paper-300")).toBe(true);
    expect(isVariant("bg-[color:var(--x)]")).toBe(false);
    expect(isVariant("aspect-[2/3]")).toBe(false);
    expect(isVariant("shadow-[var(--shadow-soft)]")).toBe(false);
  });

  it("refuses two of either, rather than picking one of them", () => {
    expect(() => pillOf("bg-paper-100 bg-paper-200/70 text-paper-600")).toThrow(
      "found 2: [bg-paper-100, bg-paper-200/70]",
    );
    expect(() =>
      pillOf("bg-paper-200/70 text-paper-600 text-paper-800"),
    ).toThrow("found 2: [text-paper-600, text-paper-800]");
    // **The one the ramp keyed count could not see.** A background from
    // another ramp beside the paper one paints the pill, and which of the two
    // wins is stylesheet order, which is the reason the refusal exists. Keyed
    // on `bg-paper-*` this survived with every arm green while the rule went
    // on measuring the paper half.
    expect(() => pillOf("bg-bloom-100 bg-paper-200/70 text-paper-600")).toThrow(
      "found 2: [bg-bloom-100, bg-paper-200/70]",
    );
    expect(() =>
      pillOf("bg-paper-200/70 text-bloom-700 text-paper-600"),
    ).toThrow("found 2: [text-bloom-700, text-paper-600]");
    // Absence, which the type checker reaches for the table but not for what
    // any one of its strings says.
    expect(() => pillOf("text-paper-600")).toThrow("background token, found 0");
    expect(() => pillOf("bg-paper-200/70")).toThrow("ink token, found 0");
    // **A background carrying no rung is still a background.** This app's own
    // primary fill is one, and beside the paper background it used to be
    // counted as nothing while the rule measured the paper half. Refused now,
    // for being a second background.
    expect(() =>
      pillOf("bg-accent-fill bg-paper-200/70 text-paper-600"),
    ).toThrow("found 2: [bg-accent-fill, bg-paper-200/70]");
    expect(() => pillOf("bg-black/50 bg-paper-200/70 text-paper-600")).toThrow(
      "found 2: [bg-black/50, bg-paper-200/70]",
    );
    // **And the ink cannot be widened to match, which is the asymmetry.**
    // `text-` is sizing and alignment as well as colour, so a rungless ink is
    // counted as nothing and a second one is not seen. Asserted as what
    // happens rather than as what should: this is an unclosed hole, written
    // into the rule's residue, not a refusal being claimed.
    expect(() =>
      pillOf("bg-paper-200/70 text-white text-paper-600"),
    ).not.toThrow();
    expect(pillOf("bg-paper-200/70 text-white text-paper-600").inkStep).toBe(
      600,
    );
    // One of the family, on a ramp this rule cannot measure. Refused for what
    // it is rather than counted as absent, because the two want different
    // fixes: this one is a design change, and the one above is a typo.
    expect(() => pillOf("bg-bloom-100 text-paper-600")).toThrow(
      'the background is "bg-bloom-100", which is not on the paper ramp',
    );
    expect(() => pillOf("bg-paper-200/70 text-bloom-700")).toThrow(
      'the ink is "text-bloom-700", which is not on the paper ramp',
    );
    // A variant of the same utility is not a second one.
    expect(() =>
      pillOf("dark:bg-paper-800 bg-paper-200/70 text-paper-600"),
    ).not.toThrow();
    // And a utility that is not a colour is not one either, which is what
    // keeps every other class on a real pill free.
    expect(() =>
      pillOf("text-xs rounded-full bg-paper-200/70 font-medium text-paper-600"),
    ).not.toThrow();
  });

  it("defaults an absent opacity low, never high", () => {
    expect(FINISHED().opacity).toBe(1);
    expect(pillOf("bg-paper-200/100 text-paper-800").opacity).toBe(1);
    // The direction, measured over every palette rather than reasoned off the
    // ramp. A palette whose card stopped being the lighter of the two reddens
    // here, which is the condition the default rests on and the only one.
    const at = (palette: PaletteId, alpha: number): number => {
      const light = tokensFor(palette, "light");
      return contrast(
        paperToken(light, FINISHED().ink),
        blend(
          paperToken(light, FINISHED().surface),
          light["--color-paper-0"]!,
          alpha,
        ),
      );
    };
    const readsHigher = THEMES.flatMap((palette) =>
      [0.25, 0.5, 0.75]
        .filter((alpha) => at(palette, 1) > at(palette, alpha))
        .map((alpha) => `${palette} at ${alpha}`),
    );

    expect(readsHigher).toEqual([]);
  });

  it("is not read from a copy of the pill sitting in this module", () => {
    // Free under import, asserted anyway. The rungs in the copy are ones no
    // pill paints, so this can only pass by having read the table.
    expect(A_COPY_OF_A_PILL).toContain("bg-paper-900/10");
    expect(UNREAD().surfaceStep).not.toBe(900);
    expect(UNREAD().inkStep).not.toBe(100);
    expect(UNREAD().opacity).not.toBe(0.1);
  });

  it("falls below the text floor where plain muted text does not", () => {
    // The comparison, not a count and not a list of which palettes: a palette
    // added tomorrow joins the measurement instead of aging the sentence. The
    // muted arm is an equality because that pairing is in the contract above
    // and must never stop clearing the floor; the pill arm is the existence of
    // one failure, because the number of them is not what either component
    // reasons from.
    // **The extent, because the sentence above reads wider than this half.**
    // The pill half is an existence claim, so a repaint that lightens the tint
    // and still fails somewhere leaves it green. Measured 2026-09-28 at the
    // ink this pill draws: a `/40` repaint still fails on a palette and leaves
    // this green, and the crossing where every palette clears and this reddens
    // is between `/40` and `/10`. **How many fail today is deliberately not
    // written here**, for the reason the paragraph directly above gives: it
    // would age against the palettes and nothing recomputes a number in prose.
    // Not pinned tighter either, because every arm that would redden on `/40`
    // restates the class string here, and holding it in one place is what
    // moving the table to `src/pages/types.ts` bought.
    const mutedClears = THEMES.filter(
      (palette) => mutedRatio(palette) >= FLOOR,
    );
    const pillFails = THEMES.filter((palette) => pillRatio(palette) < FLOOR);

    expect(mutedClears).toEqual(THEMES);
    expect(pillFails.length).toBeGreaterThan(0);
  });

  it("clears the floor only at the rung the finished pill takes", () => {
    // Over the rungs from the one the `unread` pill inks with to the one
    // `did_not_finish` was moved to. Both ends come out of the table, so this
    // says "the rung it picked is the only one of them that works" rather than
    // restating three numbers. Composited at that pill's own opacity, which is
    // 1 today and so paints the flat tint: written as a blend rather than as a
    // token lookup because the flatness is the pill's choice and not this
    // arm's, and `blend` at 1 returns its first argument.
    const rungs = PAPER_STEPS.filter(
      (step) => step >= UNREAD().inkStep && step <= FINISHED().inkStep,
    );
    const clearsEverywhere = (step: number): boolean =>
      THEMES.every((palette) => {
        const light = tokensFor(palette, "light");
        const tint = blend(
          paperToken(light, FINISHED().surface),
          light["--color-paper-0"]!,
          FINISHED().opacity,
        );
        return contrast(light[`--color-paper-${step}`]!, tint) >= FLOOR;
      });

    expect(rungs.length).toBeGreaterThan(1);
    expect(rungs.filter(clearsEverywhere)).toEqual([FINISHED().inkStep]);
  });

  it("is compositing, rather than reading one of its two arguments", () => {
    // A blend that returned either token unchanged would make the arms above
    // measure a pairing nobody paints, and the first of them would still pass.
    const light = tokensFor("endpaper", "light");
    const tint = light["--color-paper-200"]!;
    const card = light["--color-paper-0"]!;
    // Half, chosen by this arm rather than taken from the pill. What is under
    // test is the instrument, and an alpha borrowed from the pill would redden
    // this arm on the day somebody repaints the pill flat, which is a change
    // the arms above are built to measure rather than to refuse.
    const mixed = blend(tint, card, 0.5);

    expect(mixed).toMatch(/^#[0-9a-f]{6}$/i);
    expect(mixed).not.toBe(tint);
    expect(mixed).not.toBe(card);
    expect(blend(tint, card, 1)).toBe(tint);
    expect(blend(tint, card, 0)).toBe(card);
  });
});

describe("more contrast is honoured on every palette, not only the default", () => {
  it("outranks a palette block, and the light half stays in the light", () => {
    // `:root:root` is doubled so it beats `:root[data-theme="x"]`, which is
    // (0,2,0). Written once it would apply on Endpaper and be silently ignored
    // on the other nine. `:not(.dark)` is the other half: without it the light
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
    // Latte, Mocha, Dawn, Moon, Lotus, Wave. The docs and the stylesheet
    // comments both used these before any field held them, so the picker had
    // nothing to print.
    expect(paletteEntry("catppuccin").modes).toEqual({
      light: "Latte",
      dark: "Mocha",
    });
    expect(paletteEntry("rosepine").modes).toEqual({
      light: "Dawn",
      dark: "Moon",
    });
    expect(paletteEntry("kanagawa").modes).toEqual({
      light: "Lotus",
      dark: "Wave",
    });
  });

  it("names no member upstream leaves unnamed", () => {
    // "Gruvbox light" is not a title anybody uses, and inventing one would put
    // a name in the picker that appears nowhere upstream. Tokyo Night and Ayu
    // are the same rule read from the other side: each publishes a third theme
    // that does carry a name, Storm and Mirage, and neither of those is what is
    // ported here, so printing one would name a member this app does not ship.
    expect(paletteEntry("gruvbox").modes).toEqual({ light: null, dark: null });
    expect(paletteEntry("endpaper").modes).toEqual({ light: null, dark: null });
    expect(paletteEntry("tokyonight").modes).toEqual({
      light: null,
      dark: null,
    });
    expect(paletteEntry("ayu").modes).toEqual({ light: null, dark: null });
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
    // The picker reads ten palettes on a page that can only have one.
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

// ── The documented figures ───────────────────────────────────────────────────

describe("the contrast table in docs/decisions.md", () => {
  /**
   * Every figure in that table must match what this file computes.
   *
   * Two rows of it were wrong in one session and both were caught by a person
   * re-measuring by hand: 4.19:1 was attributed to `paper-600` when it is the
   * `paper-700` figure, and the dark row's 5.57:1 was attributed to nord when
   * it belongs to everforest. Neither changed a conclusion, and that is the
   * problem: a number in a table like that one is a thing the next person
   * re-measures, and one that corresponds to nothing costs them the time to
   * find out why.
   *
   * The numbers were already computed here. Nothing asserted the prose against
   * them, so the prose drifted. This is that assertion.
   */
  // Read the same way this file reads the stylesheets, rather than through
  // `node:fs`. The frontend is a browser project with no `@types/node`, and
  // pulling that in so one test can read one file would widen the type
  // environment of the whole package to save an import.
  const DOCS = import.meta.glob("../../../docs/*.md", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const DOC = DOCS["../../../docs/decisions.md"] ?? "";

  const ROW =
    /\|\s*`paper-(\d+)`\s+on\s+`paper-(\d+)`(,\s*dark)?\s*\|\s*\*{0,2}([\d.]+):1\*{0,2}\s*\|\s*([a-z]+)/g;

  const rows = [...DOC.matchAll(ROW)].map((m) => ({
    fg: m[1],
    bg: m[2],
    mode: (m[3] ? "dark" : "light") as "light" | "dark",
    stated: Number(m[4]),
    palette: m[5],
  }));

  it("has rows this test can actually see", () => {
    // A regex that silently matches nothing would make every assertion below
    // vacuous, which is the failure mode of a test that reads prose.
    expect(rows.length).toBeGreaterThanOrEqual(4);
  });

  it.each(rows)(
    "paper-$fg on paper-$bg ($mode) is $stated:1 at $palette",
    ({ fg, bg, mode, stated, palette }) => {
      const measured = PALETTES.map((entry) => {
        const tokens = tokensFor(entry.id, mode);
        return {
          id: entry.id as string,
          ratio: contrast(
            tokens[`--color-paper-${fg}`]!,
            tokens[`--color-paper-${bg}`]!,
          ),
        };
      }).sort((a, b) => a.ratio - b.ratio);

      const worst = measured[0]!;
      // Two decimals, because that is the precision the table is written to.
      expect(Number(worst.ratio.toFixed(2))).toBe(stated);
      expect(worst.id).toBe(palette);
    },
  );
});

// ── The correction tables ────────────────────────────────────────────────────

describe("the correction tables in docs/theming.md", () => {
  /**
   * Every row recomputed from the two hexes it states.
   *
   * The upstream value is the row's second column and the shipped value its
   * third, so a row carries everything needed to check itself: the "Was" figure
   * is the upstream hex against the surface the last column names, and the
   * shipped hex is a token this file already reads out of the stylesheet.
   * Nothing here is copied from the document.
   *
   * Written because eight rows named the wrong surface for a year and nothing
   * could tell. A semantic ink in light is corrected against the page, which is
   * the darker of the two surfaces and therefore the harder one, and those rows
   * quoted the card and its figure. The reason that survived is the reason this
   * repository keeps finding: a number in prose recomputes itself never.
   *
   * The section heading is resolved through the catalogue rather than a table
   * of its own, so "Kanagawa, Lotus" is a heading only while `modes.light` says
   * Lotus. A heading naming a member no palette has fails at the parse.
   *
   * **Three blind spots, each found by attacking this rather than by reading
   * it, and all three named because a guard silent about its edges reads as one
   * with none.**
   *
   * The "Needed" column is checked as a bound rather than as a value. It is
   * held above the pairing's own contract floor and below the ratio the
   * correction achieved, and inside that interval a row may name a threshold
   * nothing paints to. The interval is narrow: `needed` equals the floor on 62
   * of the 63 rows, and the exception is Kanagawa Lotus `paper-800` at 5.39,
   * which this file asserts by another route. So this is close to a value check
   * without being one, and the gap is the part it cannot see. Held only from
   * below it could have been lowered to anything at all, which is what it was
   * until 2026-08-29.
   *
   * The upstream column is checked for arithmetic, not for provenance. Changing
   * `#8a8980` to `#8a8981` moves the recomputed ratio by less than the two
   * decimals the document states, so it survives. Nothing here can close it,
   * because the upstream palettes are not vendored; what checks it is a person
   * against the repository `docs/theming.md` names beside each palette.
   *
   * And a row deleted **together with** the count above it survives, for the
   * same reason: every reference left in the document agrees, and the value it
   * used to state is gone from the tree along with the row. What this catches
   * is every way a row that is present can contradict itself, the stylesheet,
   * or the sentence over its table. A row that is absent and unaccounted for
   * fails; a row that is absent and accounted for cannot be seen from here.
   */
  const DOCS = import.meta.glob("../../../docs/*.md", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const THEMING = DOCS["../../../docs/theming.md"] ?? "";

  /** Which token a "Where it is read" cell means, per mode. */
  const SURFACES: Record<string, Record<"light" | "dark", string>> = {
    card: { light: "--color-paper-0", dark: "--color-paper-900" },
    page: { light: "--color-paper-50", dark: "--color-paper-950" },
    "sunken tier": { light: "--color-paper-100", dark: "--color-paper-800" },
  };

  function palette(label: string): PaletteId | undefined {
    return PALETTES.find((entry) => entry.label === label)?.id;
  }

  function mode(id: PaletteId, member: string): "light" | "dark" | undefined {
    const word = member.trim().toLowerCase();
    if (word === "light" || word === "dark") return word;
    // Otherwise it is what upstream calls the member, and the catalogue is the
    // only place that knows: Lotus, Wave, Latte, Mocha, Dawn, Moon.
    const modes = paletteEntry(id).modes;
    if (modes.light?.toLowerCase() === word) return "light";
    if (modes.dark?.toLowerCase() === word) return "dark";
    return undefined;
  }

  const ROW =
    /\|\s*`([a-z]+-\d+)`\s*\|\s*`(#[0-9a-f]{6})`\s*\|\s*`(#[0-9a-f]{6})`\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([^|]+?)\s*\|/g;

  // Only the one chapter, bounded at its own end. The document has later `###`
  // headings with tables under them, the measured result and the ink budget
  // among them, and a slice that ran to the end of the file counted their rows
  // as correction rows this parse had lost: the guard then failed on the
  // untouched document, which is a guard that reports on everything and so on
  // nothing. It went unnoticed for one round because every mutation run had
  // something else failing beside it.
  const CHAPTER = THEMING.slice(THEMING.indexOf("## Every correction"));
  // `indexOf` answers -1 when this chapter is the last `##` in the file, and
  // `slice(0, -1)` then means "everything but the final character" rather than
  // "everything". Measured on that shape, with the chapter last and ending on a
  // table row: 58 rows parsed where there are 59. The chapter is not last today
  // and the row it would drop is one the count check above would then report,
  // so this is a correctness fix rather than a live hole; it is written down
  // because the safety is the document's running order and nothing else.
  const CHAPTER_END = CHAPTER.indexOf("\n## ", 1);

  const sections = CHAPTER.slice(
    0,
    CHAPTER_END === -1 ? undefined : CHAPTER_END,
  )
    .split("\n### ")
    .slice(1)
    .map((section) => {
      const heading = section.slice(0, section.indexOf("\n")).trim();
      const id = palette(heading.slice(0, heading.lastIndexOf(",")));
      // Each section opens by saying how many corrections it holds, in prose,
      // and "No corrections." is the zero. Read here so the prose can be
      // checked against the table under it.
      const stated = /^(?:(\d+) corrections?|No corrections)\b/m.exec(section);
      return {
        heading,
        body: section,
        id,
        mode: id && mode(id, heading.slice(heading.lastIndexOf(",") + 1)),
        stated: stated ? Number(stated[1] ?? 0) : undefined,
      };
    });

  const rows = sections.flatMap(({ id, mode: which, heading, body }) =>
    !id || !which
      ? []
      : [...body.matchAll(ROW)].map((m) => ({
          id,
          mode: which,
          heading,
          rung: m[1]!,
          upstream: m[2]!,
          shipped: m[3]!,
          was: Number(m[4]),
          needed: Number(m[5]),
          where: m[6]!,
        })),
  );

  it("has a section for every palette and mode", () => {
    // Derived from the catalogue rather than stated. A count written here would
    // be a smaller number than the truth the day a palette is added, and a
    // smaller count is a weaker assertion that still passes.
    const covered = new Set(
      sections
        .filter((section) => section.id && section.mode)
        .map((section) => `${section.id} ${section.mode}`),
    );
    expect(covered.size).toBe(PALETTES.length * MODES.length);
  });

  it("counts the corrections each section says it holds", () => {
    // The prose and the table are two independent statements of the same fact,
    // and this is what stops a row leaving the document quietly. Deleting a row
    // moves the table and every count derived from it, this test's included, so
    // a check that compares the table with itself agrees that nothing is
    // missing. The sentence above the table does not move, and that is the
    // whole of its value here.
    //
    // It also pins the sentence: "7 corrections" over a table of six fails from
    // the other side.
    const disagree = sections
      .map((section) => ({
        heading: section.heading,
        saysItHolds: section.stated,
        rowsInTable: rows.filter((row) => row.heading === section.heading)
          .length,
      }))
      .filter((section) => section.saysItHolds !== section.rowsInTable);
    expect(disagree).toEqual([]);
  });

  it("reads every row of every table, not merely one", () => {
    // The vacuity guard, and it counts rather than sampling. "At least one row
    // per section" was the first version and a mutation walked through it: a
    // single row stripped of its backticks left its section still contributing,
    // so the row simply left the suite. The test count went down by one and
    // nothing failed, which is the same shape as a mutation deleted from a
    // harness and read as a pass.
    //
    // Body lines are counted structurally, so the comparison is against the
    // document rather than against a number written here: a section is allowed
    // to say "No corrections." and two of them do.
    const uncounted = sections
      .map((section) => ({
        heading: section.heading,
        // Every table line that is not the header or the rule. Deliberately
        // blind to backticks and to hexes: counting the same shape the parse
        // matches makes the comparison agree with itself, which is how the
        // first version of this passed a row it had lost.
        inDocument: section.body
          .split("\n")
          .filter(
            (line) =>
              line.startsWith("|") &&
              !line.startsWith("| Rung ") &&
              !line.startsWith("|---"),
          ).length,
        parsed: rows.filter((row) => row.heading === section.heading).length,
      }))
      .filter((section) => section.inDocument !== section.parsed);
    expect(uncounted).toEqual([]);
  });

  it("names a surface each row can be measured against", () => {
    const unknown = rows.filter(
      (row) => !Object.keys(SURFACES).some((name) => row.where.includes(name)),
    );
    expect(unknown.map((row) => `${row.heading}: ${row.where}`)).toEqual([]);
  });

  it.each(rows)(
    "$heading $rung was $was on the $where",
    ({ id, mode: which, rung, upstream, shipped, was, needed, where }) => {
      const tokens = tokensFor(id, which);
      const surface = Object.entries(SURFACES).find(([name]) =>
        where.includes(name),
      )![1][which];

      // The shipped hex is the token, not a copy of it that can drift.
      expect(tokens[`--color-${rung}`]).toBe(shipped);
      // The stated figure is the upstream value against the stated surface.
      expect(Number(contrast(upstream, tokens[surface]!).toFixed(2))).toBe(was);
      // And the correction reached what it was made for.
      expect(contrast(shipped, tokens[surface]!)).toBeGreaterThanOrEqual(
        needed,
      );
      // `needed` is bounded from both sides or it is not bounded at all. Held
      // only from below it is a floor that can be lowered to anything, because
      // a smaller floor is a weaker inequality that still passes: this
      // repository's own lesson about a stated bound, arriving inside the guard
      // written to enforce measurement. A row exists because the upstream value
      // was under the floor, so that is the other side. Tightest margin across
      // the document as it ships is 0.0357, on Catppuccin light's `danger-500`.
      expect(contrast(upstream, tokens[surface]!)).toBeLessThan(needed);
      // **An interval is not a value, and this interval admitted other real
      // floors.** The two lines above pin `needed` to
      // `(contrast(upstream), contrast(shipped)]`, and on 18 of the 63 rows
      // that range contains another floor the rung contract actually uses:
      // dropping Catppuccin light `paper-500` from 4.5 to 3.0 left all 222
      // tests passing, and 3.0 is a real floor this contract states elsewhere.
      // So the document could name a plausible threshold that is not the one
      // this pair is held to. The contract already states the answer, which is
      // why this is a lookup rather than a fourth stated number.
      // `filter`, not `find`, and that is not defensive: the contract really
      // does state one key twice per mode. `paper-800` on `paper-200` and
      // `paper-200` on `paper-800` are both declared, in light and in dark,
      // for the did-not-finish pill and for a badge label. Their floors agree
      // today, so `find` gave the right answer, and it gave it by taking the
      // first of two without saying so. The dark spelling is reachable from
      // this table, because "on the sunken tier" in dark resolves to
      // `paper-800`. Holding above the strictest is the answer that stays
      // correct if the two ever diverge.
      const contracted = (
        which === "light" ? lightPairs() : darkPairs()
      ).filter(
        (candidate) =>
          candidate.fg === `--color-${rung}` && candidate.bg === surface,
      );
      expect(contracted).not.toHaveLength(0);
      expect(needed).toBeGreaterThanOrEqual(
        Math.max(...contracted.map((candidate) => candidate.floor)),
      );
    },
  );
});
