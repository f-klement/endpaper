/**
 * The seven palettes, and how one is put on the page.
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

/** Every palette on offer. The order is the order the picker will show. */
export const PALETTES = [
  {
    id: "endpaper",
    label: "Endpaper",
    /** Both modes are this project's own. */
    attribution: null,
    constructed: [],
  },
  {
    id: "catppuccin",
    label: "Catppuccin",
    attribution: "Catppuccin, MIT",
    constructed: [],
  },
  {
    id: "rosepine",
    label: "Rose Pine",
    attribution: "Rose Pine, MIT",
    constructed: [],
  },
  {
    id: "gruvbox",
    label: "Gruvbox",
    attribution: "Pavel Pertsev, MIT",
    constructed: [],
  },
  {
    id: "solarized",
    label: "Solarized",
    attribution: "Ethan Schoonover, MIT",
    constructed: [],
  },
  {
    id: "everforest",
    label: "Everforest",
    attribution: "sainnhe, MIT",
    constructed: [],
  },
  {
    id: "nord",
    label: "Nord",
    attribution: "Arctic Ice Studio and Sven Greb, MIT",
    // Nord publishes no light theme. This one is built from Snow Storm and
    // Polar Night, which are published, and the picker says so rather than
    // greying out a control every other palette leaves alone. Mode is an
    // independent axis: a palette that cannot supply one does not go in
    // the list.
    constructed: ["light"],
  },
] as const satisfies readonly PaletteEntry[];

interface PaletteEntry {
  id: string;
  label: string;
  attribution: string | null;
  constructed: readonly ("light" | "dark")[];
}

export type PaletteId = (typeof PALETTES)[number]["id"];

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
