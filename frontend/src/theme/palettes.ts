/**
 * The ten palettes, and how one is put on the page.
 *
 * The values are not here: they are `--color-*` blocks in `palettes.css`,
 * selected by `data-theme` on the document element. This module holds only what
 * cannot be said in CSS, which is the list itself, where each palette comes
 * from, and which of its two modes was constructed rather than published.
 *
 * Endpaper has no block. Its light values are the `@theme` in `index.css`,
 * where Tailwind reads them to generate the utilities, and its dark ones sit in
 * the `:root.dark` block beside them. So the default palette is what the page
 * already is, and applying it means removing an attribute rather than adding
 * thirty six properties.
 */

/** Every palette on offer. The order is the order the picker shows. */
export const PALETTES = [
  {
    id: "endpaper",
    label: "Endpaper",
    /** Both modes are this project's own. */
    attribution: null,
    modes: { light: null, dark: null },
    constructed: [],
  },
  {
    id: "catppuccin",
    label: "Catppuccin",
    attribution: "Catppuccin, MIT",
    modes: { light: "Latte", dark: "Mocha" },
    constructed: [],
  },
  {
    id: "rosepine",
    label: "Rose Pine",
    attribution: "Rose Pine, MIT",
    modes: { light: "Dawn", dark: "Moon" },
    constructed: [],
  },
  {
    id: "gruvbox",
    label: "Gruvbox",
    attribution: "Pavel Pertsev, MIT",
    modes: { light: null, dark: null },
    constructed: [],
  },
  {
    id: "solarized",
    label: "Solarized",
    attribution: "Ethan Schoonover, MIT",
    modes: { light: null, dark: null },
    constructed: [],
  },
  {
    id: "everforest",
    label: "Everforest",
    attribution: "sainnhe, MIT",
    modes: { light: "Medium light", dark: "Medium dark" },
    constructed: [],
  },
  {
    id: "nord",
    label: "Nord",
    attribution: "Arctic Ice Studio and Sven Greb, MIT",
    // Nord names its colour groups, not its themes: Polar Night and Snow Storm
    // are the two neutral sets this palette is built out of, and neither is the
    // name of a light or a dark theme. So there is nothing to print here.
    modes: { light: null, dark: null },
    // Nord publishes no light theme. This one is built from Snow Storm and
    // Polar Night, which are published, and the picker says so rather than
    // greying out a control every other palette leaves alone. Mode is an
    // independent axis: a palette that cannot supply one does not go in
    // the list.
    constructed: ["light"],
  },
  {
    id: "kanagawa",
    label: "Kanagawa",
    attribution: "Tommaso Laurenzi, MIT",
    // Kanagawa names its themes rather than its colour groups, which is the
    // other way round from Nord: Wave is the dark one, Lotus the light one, and
    // a third, Dragon, is not ported.
    modes: { light: "Lotus", dark: "Wave" },
    constructed: [],
  },
  {
    id: "tokyonight",
    label: "Tokyo Night",
    attribution: "Enkia, MIT",
    // Upstream ships three themes and names them Tokyo Night, Tokyo Night Storm
    // and Tokyo Night Light. The two ported here are the first and the third, so
    // what upstream calls each member is the palette's own name plus the word
    // for the mode, which is not a title and is not printed. Storm is a name,
    // and Storm is not what is here.
    modes: { light: null, dark: null },
    constructed: [],
  },
  {
    id: "ayu",
    label: "Ayu",
    attribution: "Konstantin Pschera, MIT",
    // Light, Mirage and Dark upstream. Two of the three are ported and neither
    // carries a name of its own, the same case as Gruvbox.
    modes: { light: null, dark: null },
    constructed: [],
  },
] as const satisfies readonly PaletteEntry[];

interface PaletteEntry {
  id: string;
  label: string;
  attribution: string | null;
  /**
   * What upstream calls each member, where it calls it anything.
   *
   * Catppuccin's light is Latte and Rose Pine's is Dawn, and a reader who knows
   * the palette knows the member's name better than the mode's. Null where
   * upstream publishes no name of its own, which is most of them: the picker
   * then says nothing rather than inventing one, and "Gruvbox light" is not a
   * title anybody uses.
   */
  modes: { light: string | null; dark: string | null };
  constructed: readonly ("light" | "dark")[];
}

/** The two members of a palette. Also the two values `constructed` holds. */
export type PaletteMode = "light" | "dark";

export type PaletteId = (typeof PALETTES)[number]["id"];

/** One entry, by id. Every id is in the list, so this always answers. */
export function paletteEntry(id: PaletteId): PaletteEntry {
  return PALETTES.find((palette) => palette.id === id)!;
}

/**
 * Whether this palette's member for `mode` was built here rather than published.
 *
 * Through `paletteEntry` rather than reading `PALETTES` directly, because
 * `as const` narrows an empty `constructed` to `readonly []` and asking whether
 * that contains a mode is a type error at every call site. Widening it once
 * here is the alternative to widening it at each of them.
 */
export function isConstructed(id: PaletteId, mode: PaletteMode): boolean {
  return paletteEntry(id).constructed.includes(mode);
}

/** The palette a page with no stored preference shows. */
export const DEFAULT_PALETTE: PaletteId = "endpaper";

export function isPaletteId(value: unknown): value is PaletteId {
  return PALETTES.some((palette) => palette.id === value);
}

/**
 * Resolve whatever was stored into a palette that exists.
 *
 * A value this build does not know is not an error: it is a palette added by a
 * newer version, or removed by this one, and the reader gets the default rather
 * than a crash or an unstyled page. They keep it only until they change
 * something: appearance is written as a whole record, so the resolved default
 * goes back with the next change.
 */
export function resolvePalette(value: unknown): PaletteId {
  return isPaletteId(value) ? value : DEFAULT_PALETTE;
}

/**
 * Put the palette on the document.
 *
 * Exported because `main.tsx` calls it before React mounts, for the same reason
 * `applyTheme` is: resolved in an effect it lands a frame after the first
 * paint, and a palette arriving late is the whole flash this avoids.
 *
 * The attribute is set even for Endpaper, which matches no block. The document
 * then always says which palette is in force, whether or not it is the one with
 * no overrides.
 */
export function applyPalette(palette: PaletteId): void {
  document.documentElement.dataset.theme = palette;
}

/**
 * The five colours a palette tile shows.
 *
 * Five rather than four because a card on a page is two surfaces, and half of
 * what tells Gruvbox from Everforest is how far the card stands off the page.
 */
export interface PaletteColours {
  page: string;
  card: string;
  ink: string;
  accent: string;
  bloom: string;
}

/**
 * The token holding the colour of the page itself, per mode.
 *
 * Exported because `patterns.ts` needs the same one: every wallpaper layer's
 * alpha is solved as a distance from the page it is pasted onto, so both
 * modules are asking the same question. It was the one row two token tables had
 * in common, cross-referenced in prose, which is a fact stored twice.
 *
 * Two entries rather than one token, because a ramp runs the other way in the
 * dark: the page is `paper-50` in one mode and `paper-950` in the other.
 */
export const PAGE_TOKEN: Record<PaletteMode, string> = {
  light: "--color-paper-50",
  dark: "--color-paper-950",
};

/**
 * Which token each of the five reads, per mode.
 *
 * The same pairs `index.css` uses for `body` and `.card`.
 */
const COLOUR_TOKENS: Record<PaletteMode, PaletteColours> = {
  light: {
    page: PAGE_TOKEN.light,
    card: "--color-paper-0",
    ink: "--color-paper-900",
    accent: "--color-accent-500",
    bloom: "--color-bloom-500",
  },
  dark: {
    page: PAGE_TOKEN.dark,
    card: "--color-paper-900",
    ink: "--color-paper-200",
    accent: "--color-accent-500",
    bloom: "--color-bloom-500",
  },
};

/**
 * Every palette's colours, read off the shipped stylesheets.
 *
 * Not a table of hexes in this file. Thirty five values restated here would be
 * the same eleven ramps written twice, which is the thing `palettes.css` opens
 * by refusing, and a tile that disagrees with the palette it applies is worse
 * than no tile: it is a preview that lies. `wallpaperColours` in `patterns.ts`
 * resolves its inks the same way and for the same reason.
 *
 * The read costs one forced style recalculation per palette, so ten, and it
 * happens once per mode change rather than per render. Call it from a layout
 * effect: the attribute is restored inside the same synchronous block, so no
 * frame is ever painted with the wrong palette on the document, but a caller
 * that ran this in a passive effect would paint one.
 *
 * A palette whose block is missing yields empty strings, which is what jsdom
 * does with no stylesheet loaded. The picker renders the name and no colour in
 * that case rather than a black tile, which is what an empty `background`
 * would give.
 */
export function readPaletteColours(
  mode: PaletteMode,
): Record<PaletteId, PaletteColours> {
  const style = getComputedStyle(document.documentElement);
  const tokens = COLOUR_TOKENS[mode];

  const colours = {} as Record<PaletteId, PaletteColours>;
  for (const palette of PALETTES) {
    colours[palette.id] = withPalette(palette.id, () => ({
      page: style.getPropertyValue(tokens.page).trim(),
      card: style.getPropertyValue(tokens.card).trim(),
      ink: style.getPropertyValue(tokens.ink).trim(),
      accent: style.getPropertyValue(tokens.accent).trim(),
      bloom: style.getPropertyValue(tokens.bloom).trim(),
    }));
  }
  return colours;
}

/**
 * Read something off the document as if `palette` were the one in force.
 *
 * The picker needs it because it draws ten palettes on a page that can only
 * have one, and because it must not wait for the provider to apply a choice:
 * a child's effect runs before its parent's, so a component that read the
 * tokens after asking for a palette change would read the previous palette
 * every time and show a grid one choice behind.
 *
 * Synchronous, and the attribute is restored before it returns. Anything
 * asynchronous inside `read` would leave the wrong palette on the document for
 * a frame, which is the flash the whole module exists to avoid: the restore is
 * why this takes a callback rather than handing out a way to set the attribute.
 */
export function withPalette<T>(palette: PaletteId, read: () => T): T {
  const root = document.documentElement;
  const restore = root.dataset.theme;
  root.dataset.theme = palette;
  try {
    return read();
  } finally {
    if (restore === undefined) delete root.dataset.theme;
    else root.dataset.theme = restore;
  }
}
