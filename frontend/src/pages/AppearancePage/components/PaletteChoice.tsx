import { useLayoutEffect, useState } from "react";

import { useTranslation } from "../../../i18n";
import {
  PALETTES,
  isConstructed,
  readPaletteColours,
  useTheme,
  type PaletteColours,
  type PaletteId,
} from "../../../theme";
import ChoiceTile from "./ChoiceTile";

/**
 * A palette, drawn in itself.
 *
 * Page, card, ink and the two accents, which is the smallest set that tells one
 * palette from another: half of what separates Gruvbox from Everforest is how
 * far the card stands off the page, so a single colour chip would make several
 * of the ten look alike.
 *
 * Nothing here is a hex. The values come from the shipped stylesheet through
 * `readPaletteColours`, so a tile cannot disagree with the palette it applies.
 * Where the stylesheet is not loaded they are empty strings and the tile draws
 * nothing, because an empty `background` is transparent and an empty `fill` is
 * black.
 */
function Swatch({ colours }: { colours: PaletteColours | undefined }) {
  // Every one of the five, not just the page. Same rule as `applyWallpaper`:
  // no tokens, no drawing. A partial read would paint a card with no colour on
  // a page that has one, which looks like a rendering fault rather than a
  // missing stylesheet.
  if (!colours || Object.values(colours).some((colour) => colour === "")) {
    return <span className="block h-20 bg-paper-100 dark:bg-paper-800" />;
  }
  return (
    <span
      aria-hidden="true"
      className="flex h-20 items-end gap-2 px-3 pb-3"
      style={{ backgroundColor: colours.page }}
    >
      <span
        className="flex flex-1 items-center gap-1.5 rounded-lg px-2 py-1.5"
        style={{ backgroundColor: colours.card }}
      >
        <span
          className="h-1.5 flex-1 rounded-full"
          style={{ backgroundColor: colours.ink }}
        />
        <span
          className="h-3 w-3 rounded-full"
          style={{ backgroundColor: colours.accent }}
        />
        <span
          className="h-3 w-3 rounded-full"
          style={{ backgroundColor: colours.bloom }}
        />
      </span>
    </span>
  );
}

/**
 * The ten palettes.
 *
 * The colours are read once per mode rather than per render, in a layout
 * effect: `readPaletteColours` puts each palette on the document in turn to
 * read it, and a passive effect would let the browser paint one of those
 * intermediate states. A layout effect restores the real palette inside the
 * same synchronous block, so no frame is ever painted with the wrong one.
 */
export default function PaletteChoice() {
  const { t } = useTranslation();
  const { appearance, setAppearance, theme } = useTheme();
  const [colours, setColours] = useState<Record<PaletteId, PaletteColours>>();

  useLayoutEffect(() => {
    setColours(readPaletteColours(theme));
  }, [theme]);

  return (
    <div
      role="group"
      aria-label={t("appearance.palette")}
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
    >
      {PALETTES.map((palette) => (
        <ChoiceTile
          key={palette.id}
          name={palette.label}
          hint={palette.modes[theme] ?? undefined}
          notes={[
            palette.attribution
              ? t("appearance.attribution", { source: palette.attribution })
              : t("appearance.attributionOwn"),
            // Said on the tile, not only in the licences below. Nord publishes
            // no light theme, and a reader choosing it in light is choosing
            // something this project assembled.
            ...(isConstructed(palette.id, theme)
              ? [
                  t(
                    theme === "light"
                      ? "appearance.constructedLight"
                      : "appearance.constructedDark",
                    { palette: palette.label },
                  ),
                ]
              : []),
          ]}
          selected={appearance.palette === palette.id}
          onSelect={() => setAppearance({ palette: palette.id })}
        >
          <Swatch colours={colours?.[palette.id]} />
        </ChoiceTile>
      ))}
    </div>
  );
}
