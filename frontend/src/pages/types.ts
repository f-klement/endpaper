/**
 * View types and constants shared by several pages.
 *
 * Hoisted here by the colocation rule: anything used by one page lives in that
 * page's folder, and only what genuinely crosses pages moves up a level. Tag
 * grouping is used by Home's filter panel, ScanPage's tag picker, BookDetail's
 * tag editor and StatsPage's breakdown, so it belongs at this level rather
 * than being duplicated four times.
 *
 * Wire types (BookOut, LoanOut, ...) are NOT redeclared here. They are
 * generated from the OpenAPI schema into `src/api/generated/model`.
 */

import { TagCategory } from "../api/generated/model";
import type { TagOut } from "../api/generated/model";
import type { MessageKey } from "../i18n";

/**
 * The order tag categories are presented in, everywhere.
 *
 * The household's own tags come last, after the curated three. Interleaving
 * them alphabetically would scatter "Holiday reads" through a genre list and
 * make the curated vocabulary harder to scan, which is the thing that makes
 * it useful on the first day.
 */
export const TAG_CATEGORY_ORDER: TagCategory[] = [
  TagCategory.type,
  TagCategory.genre,
  TagCategory.age,
  TagCategory.custom,
];

/** Message keys, not text: these headings are rendered in both languages. */
export const TAG_CATEGORY_LABELS: Record<TagCategory, MessageKey> = {
  [TagCategory.type]: "tags.type",
  [TagCategory.genre]: "tags.genre",
  [TagCategory.age]: "tags.age",
  [TagCategory.custom]: "tags.custom",
};

/** Type, genre and age. One value, written once. */
const CURATED_PILL = "bg-paper-100 text-paper-700";

/**
 * Pill colours per category, used wherever a tag is rendered.
 *
 * The curated three are neutral on purpose. They used to carry a blue, a purple
 * and a green, which were the one place in this app where a colour was chosen at
 * random: there is no mnemonic that makes genre purple, so the hue had to be
 * looked up, which is slower than reading the word already printed on the pill.
 * The three cost fifteen shades per mode to theme and encoded nothing.
 *
 * Custom keeps the accent, so a tag the household invented still reads as theirs
 * rather than as a fourth colour picked at random.
 *
 * Still a four-key table holding two values, rather than a default and one
 * exception: a category added to the backend enum has to be a compile error
 * here, not an unstyled pill nobody notices.
 */
export const TAG_PILL_CLASSES: Record<TagCategory, string> = {
  [TagCategory.type]: CURATED_PILL,
  [TagCategory.genre]: CURATED_PILL,
  [TagCategory.age]: CURATED_PILL,
  [TagCategory.custom]: "bg-accent-100 text-accent-800",
};

/** The same three, at chip weight. */
const CURATED_CHIP = "border-paper-200 text-paper-600 bg-paper-0";

/** Resting style for a selectable tag chip. */
export const TAG_CHIP_CLASSES: Record<TagCategory, string> = {
  [TagCategory.type]: CURATED_CHIP,
  [TagCategory.genre]: CURATED_CHIP,
  [TagCategory.age]: CURATED_CHIP,
  [TagCategory.custom]: "border-accent-200 text-accent-700 bg-paper-0",
};

/**
 * Selected, for every category.
 *
 * One string rather than four, because selection is the same state whatever the
 * tag is about. It takes the accent fill and its paired foreground: the four
 * this replaced were `bg-*-500 text-white`, and all four failed AA, the accent
 * one at 3.22:1 and the green at 2.28:1. `accent-500` is the focus ring's step,
 * not a fill step, and the chip was using it as one.
 */
export const TAG_CHIP_SELECTED =
  "bg-accent-fill border-accent-fill text-on-accent";

/** Group a flat tag list into its categories, in display order. */
export function groupTagsByCategory(
  tags: TagOut[],
): Record<TagCategory, TagOut[]> {
  return {
    [TagCategory.type]: tags.filter((tag) => tag.category === TagCategory.type),
    [TagCategory.genre]: tags.filter(
      (tag) => tag.category === TagCategory.genre,
    ),
    [TagCategory.age]: tags.filter((tag) => tag.category === TagCategory.age),
    [TagCategory.custom]: tags.filter(
      (tag) => tag.category === TagCategory.custom,
    ),
  };
}
