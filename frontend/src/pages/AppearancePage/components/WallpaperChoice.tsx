import { useLayoutEffect, useState } from "react";

import { BAR_STICKY } from "../../../app/components/NavBar";
import { useTranslation, type MessageKey } from "../../../i18n";
import {
  WALLPAPER_OFF,
  currentPattern,
  useTheme,
  withPalette,
  type PaletteId,
  type ResolvedTheme,
} from "../../../theme";
import {
  PATTERNS,
  patternDataUri,
  wallpaperColours,
  type Pattern,
  type PatternFamily,
} from "../../../theme/patterns";
import ChoiceTile from "./ChoiceTile";

/** The order the two headings appear in, and their titles. */
const FAMILIES: { family: PatternFamily; label: MessageKey }[] = [
  { family: "morris", label: "appearance.family.morris" },
  { family: "papers", label: "appearance.family.papers" },
];

/**
 * A tile, at the opacity it is actually painted at.
 *
 * Not brightened for the picker. A swatch drawn at three times the page's
 * opacity is a lie about what is being chosen, and somebody picks khatam and
 * finds nothing there. The honest answer to a faint swatch is a larger one,
 * which is what the grid is: four columns inside `max-w-6xl`, less the page's
 * own padding and the section's, is a 257px cell, and every tile repeats
 * between 240px and 300px except Asanoha, so `contain` draws them at 86% to
 * 107% of the size they have on the page. Asanoha, at 420px, is the one that
 * shrinks, to 61%.
 *
 * Stated as a range with its one exception named rather than as "n of the m
 * tiles", which is a count that does not recount itself: it read "nine of the
 * ten" for a while after the set reached sixteen.
 *
 * `contain` rather than a 1:1 crop for the same reason: the swatch's job is
 * identification, and a 96px crop of a 260px repeat looks like nothing at all.
 */
function Tile({ image }: { image: string | null }) {
  return (
    <span
      aria-hidden="true"
      className="block aspect-square bg-paper-50 dark:bg-paper-950"
      style={
        image === null
          ? undefined
          : { backgroundImage: image, backgroundSize: "contain" }
      }
    />
  );
}

/**
 * The tile for a pattern, as a data URI, or null where there is no palette.
 *
 * The colours are read off the document, so a tile follows the palette the
 * reader has just picked without this component knowing any of them. The read
 * can come back empty, which is what `applyWallpaper` refuses to paint on, and
 * this refuses for the same reason: an SVG shape with an empty fill is black.
 */
function useTiles(
  theme: ResolvedTheme,
  palette: PaletteId,
): Map<string, string> {
  const [tiles, setTiles] = useState<Map<string, string>>(new Map());

  // `withPalette` rather than reading the document as it stands, because a
  // child's effect runs before its parent's: `ThemeProvider` has not applied
  // the palette that was just chosen, so the grid would be one choice behind.
  //
  // A layout effect so the re-render it causes lands before the paint. The mode
  // is a commit later either way, because `theme` only changes once the
  // provider has put the class on the document, which is what keeps the ink and
  // the page here from ever disagreeing.
  useLayoutEffect(() => {
    const colours = withPalette(palette, () => wallpaperColours(theme));
    if (!colours.ink || !colours.bloom || !colours.page) {
      setTiles(new Map());
      return;
    }
    setTiles(
      new Map(
        PATTERNS.map((pattern) => [
          pattern.id,
          patternDataUri(pattern, theme, colours),
        ]),
      ),
    );
  }, [theme, palette]);

  return tiles;
}

export default function WallpaperChoice() {
  const { t } = useTranslation();
  const { appearance, setAppearance, theme } = useTheme();
  const tiles = useTiles(theme, appearance.palette);

  // What Surprise me is showing today. `currentPattern` is fixed for the page
  // load, so the tile shows the wallpaper actually on the body rather than a
  // different one from the one being described.
  const surprise = currentPattern();

  const tile = (pattern: Pattern) => tiles.get(pattern.id) ?? null;

  return (
    <div role="group" aria-label={t("appearance.wallpaper")}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <ChoiceTile
          name={t("appearance.wallpaperNone")}
          hint={t("appearance.wallpaperNoneHint")}
          selected={appearance.wallpaper === WALLPAPER_OFF}
          onSelect={() => setAppearance({ wallpaper: WALLPAPER_OFF })}
        >
          <Tile image={null} />
        </ChoiceTile>
        <ChoiceTile
          name={t("appearance.wallpaperSurprise")}
          hint={t("appearance.wallpaperSurpriseHint")}
          selected={appearance.wallpaper === null}
          onSelect={() => setAppearance({ wallpaper: null })}
        >
          <Tile image={tile(surprise)} />
        </ChoiceTile>
      </div>

      {FAMILIES.map(({ family, label }) => (
        <div key={family}>
          {/* Sticky, because the grid is a 257px cell per pattern plus two, and
              the heading is the only thing saying which half of the set you are
              looking at.
              `top-14` is the fixed bar's own height: see NavBar.BAR_STICKY.

              The card tokens, not the page's, because this sits inside a
              `.card`: over `paper-0`/`paper-900` the page colour composites to
              1.03:1 to 1.23:1 and the heading floats over the tiles scrolling
              under it. NavBar does the same job with the same two. */}
          <h3
            className={`sticky ${BAR_STICKY} z-10 -mx-1 mt-6 mb-3 px-1 py-2 text-sm font-semibold text-paper-900 bg-paper-0/85 backdrop-blur-sm dark:text-paper-100 dark:bg-paper-900/85`}
          >
            {t(label)}
          </h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {PATTERNS.filter((pattern) => pattern.family === family).map(
              (pattern) => (
                <ChoiceTile
                  key={pattern.id}
                  name={pattern.name}
                  selected={appearance.wallpaper === pattern.id}
                  onSelect={() => setAppearance({ wallpaper: pattern.id })}
                >
                  <Tile image={tile(pattern)} />
                </ChoiceTile>
              ),
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
