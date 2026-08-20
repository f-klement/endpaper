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

/** Pill colours per category, used wherever a tag is rendered. */
export const TAG_PILL_CLASSES: Record<TagCategory, string> = {
  [TagCategory.type]: "bg-blue-100 text-blue-700",
  [TagCategory.genre]: "bg-purple-100 text-purple-700",
  [TagCategory.age]: "bg-green-100 text-green-700",
  // The accent, so a tag the household invented reads as theirs rather than as
  // a fourth colour picked at random.
  [TagCategory.custom]: "bg-accent-100 text-accent-800",
};

/** Selectable tag chips: resting and selected. */
export const TAG_CHIP_CLASSES: Record<
  TagCategory,
  { base: string; active: string }
> = {
  [TagCategory.type]: {
    base: "border-blue-200 text-blue-700 bg-white",
    active: "bg-blue-500 border-blue-500 text-white",
  },
  [TagCategory.genre]: {
    base: "border-purple-200 text-purple-700 bg-white",
    active: "bg-purple-500 border-purple-500 text-white",
  },
  [TagCategory.age]: {
    base: "border-green-200 text-green-700 bg-white",
    active: "bg-green-500 border-green-500 text-white",
  },
  [TagCategory.custom]: {
    base: "border-accent-200 text-accent-700 bg-white",
    active: "bg-accent-500 border-accent-500 text-white",
  },
};

/** Bar colours in the statistics breakdown. */
export const TAG_BAR_CLASSES: Record<TagCategory, string> = {
  [TagCategory.type]: "bg-blue-400",
  [TagCategory.genre]: "bg-purple-400",
  [TagCategory.age]: "bg-green-400",
  [TagCategory.custom]: "bg-accent-400",
};

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
