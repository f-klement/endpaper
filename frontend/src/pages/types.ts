/**
 * View types and constants shared by several pages.
 *
 * Hoisted here by the colocation rule: anything used by one page lives in that
 * page's folder, and only what genuinely crosses pages moves up a level. Tag
 * grouping reaches Home's filter panel, ScanPage's tag picker and BookDetail's
 * tag editor through the one `TagPicker` all three draw, so it belongs at this
 * level rather than inside any of them.
 *
 * **A constant also lives here when a rule outside the page has to read it**,
 * which is the second criterion and the one `STATUS_STYLES` is here on: the
 * card is its only consumer, so the paragraph above would send it back down.
 * The paragraph at that constant says what reads it and why. Moving it back
 * is a compile error wherever those rules import it rather than a silent
 * regression, which is the property that makes this safe to state once.
 *
 * Wire types (BookOut, LoanOut, ...) are NOT redeclared here. They are
 * generated from the OpenAPI schema into `src/api/generated/model`.
 */

import {
  BookCondition,
  BookFormat,
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
  TagCategory,
} from "../api/generated/model";
import type { Locale, TagOut } from "../api/generated/model";
import { tagName, type MessageKey } from "../i18n";
import { sortByName } from "../lib/nameOrder";
import type { ThemePreference } from "../theme";

/**
 * The list back, refused at compile time when it leaves a member out.
 *
 * A `readonly Union[]` cannot see a missing member, which is the hole every
 * `*_ORDER` list in this file sits in: a value in the enum and not in the order
 * is one nobody can choose and nobody can filter by, with nothing red anywhere.
 * The argument is intersected with an object type that exists only while
 * something is missing, so an incomplete list fails to typecheck and the error
 * names the value left out as the type of `missingFromThisOrder`.
 *
 * **A list this wraps carries no type annotation, and that is load bearing.**
 * Writing `: readonly Union[]` on the constant, which is the house style of the
 * lists below, throws the members away again: what the constant level witness
 * in `tests/pages/types.test.ts` reads is `typeof` the list, so an annotation
 * would leave it checking nothing. That witness refuses an annotated list by
 * name rather than trusting this sentence, and it stands whether or not a call
 * site still has the wrapper. The `@ts-expect-error` beside it pins this helper
 * and never a call of it.
 *
 * Curried because one type argument cannot be given while the other is
 * inferred: the union is named, the list is read. It does **not** refuse a
 * duplicate, since a list naming a member twice still excludes nothing, so that
 * property stays a test.
 *
 * Every `*_ORDER` list in this file is wrapped. The three that joined last,
 * `FORMAT_ORDER`, `LENDING_ORDER` and `MODE_ORDER`, each had a set equality test
 * first, so the wrap replaced an instrument rather than closing a gap: it takes
 * exhaustiveness, and what it cannot see stays a test beside it.
 */
export const everyOneOf =
  <Union extends string>() =>
  <const Order extends readonly Union[]>(
    order: Order &
      ([Exclude<Union, Order[number]>] extends [never]
        ? unknown
        : { missingFromThisOrder: Exclude<Union, Order[number]> }),
  ): Order =>
    order;

/**
 * The order tag categories are presented in, everywhere.
 *
 * The library's own tags come last, after the curated three. Interleaving
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

/**
 * What each reading status is called.
 *
 * Here rather than in the card, because the card and the table view both print
 * it and a second copy is the one that drifts. Exhaustive by type for the same
 * reason as the tables below: a status added to the backend enum has to be a
 * compile error rather than a blank cell, which is how `want_to_read` was
 * caught rather than rendering as an empty pill.
 */
export const STATUS_LABELS: Record<ReadStatus, MessageKey> = {
  [ReadStatus.unread]: "status.unread",
  [ReadStatus.want_to_read]: "status.want_to_read",
  [ReadStatus.reading]: "status.reading",
  [ReadStatus.read]: "status.read",
  [ReadStatus.did_not_finish]: "status.did_not_finish",
};

/**
 * What each reading status looks like.
 *
 * Here for the reason `STATUS_LABELS` above is: the card drew it and nothing
 * else could see it, while its two siblings in this file were already the
 * house shape for a keyed table of classes.
 *
 * **A named export rather than inline JSX, and that is a constraint on this
 * file now.** `tests/theme/palettes.test.ts::the status pill's ink, as it
 * draws` imports this table and measures, over every palette, the two rows
 * whose pill sits on the paper ramp: `unread` and `did_not_finish`. The other
 * three are bloom, amber and accent and are not read at all: handed one, that
 * rule would refuse it, naming the role and the string, rather than measure
 * it, and no path hands it one. A class string folded into the card's markup
 * is a pairing that rule can no longer see, so it would go green on a pill
 * nobody checks. The constraint is written here because the alternative is
 * somebody simplifying the export away as unnecessary indirection: it is not
 * indirection, it is the seam the measurement reads. What holds the card to
 * actually drawing it is `tests/pages/components/BookCard.test.tsx::draws the
 * %s pill from the shared table`, which is the one thing an import cannot tell
 * you. The `%s` is the label that arm writes, not a placeholder for this
 * sentence: it is driven over every status and expands to one arm per row.
 *
 * The rule reads the classes as tokens, so on the two rows it reads the order
 * of the pair, a variant sitting between them and any further utility are
 * free. **One exception, and it is a refusal rather than a miss**: a second
 * unprefixed `bg-paper-*` or `text-paper-*` on either of those rows makes that
 * rule refuse, naming both tokens, because which of the two paints is decided
 * by stylesheet order and not by the string. A variant of the same utility is
 * not a second one.
 */
export const STATUS_STYLES: Record<ReadStatus, string> = {
  // **Below the floor, and pre-existing.** As it actually draws, the ink on
  // this tint composited over the paper-0 card, it falls under the 4.5 every
  // text pair in `tests/theme/palettes.test.ts` is held to, on palettes where
  // the same ink on the card clears it. That is recomputed there by `the
  // status pill's ink, as it draws`, over every palette and with the tint
  // composited; `docs/decisions.md` carries the figures, and its table is held
  // against the stylesheets by the same file. Not changed here, because a
  // status pill's colour is a design decision across five values and this
  // change owns one of them. The test added with `did_not_finish` pins that
  // pill only.
  [ReadStatus.unread]:
    "bg-paper-200/70 text-paper-600 dark:bg-paper-800 dark:text-paper-300",
  // Bloom, not danger. Wanting to read something is the pleased note, and the
  // two were one rose until they were split: see --color-danger-* in index.css.
  [ReadStatus.want_to_read]:
    "bg-bloom-100 text-bloom-700 dark:bg-bloom-700/25 dark:text-bloom-300",
  [ReadStatus.reading]:
    "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  [ReadStatus.read]:
    "bg-accent-100 text-accent-800 dark:bg-accent-500/15 dark:text-accent-200",
  // The paper ramp, not a semantic one. Giving up on a book is neither an
  // error nor an achievement, and a rose or an amber pill would make the shelf
  // look like it was reporting a problem.
  //
  // `paper-800` on `paper-200`, not the `paper-600` the `unread` pill uses.
  // Flat, because this pill is `bg-paper-200` at full opacity, and it is the
  // only rung from the `unread` pill's ink up to this one that clears 4.5 on
  // every palette: recomputed by `tests/theme/palettes.test.ts::the status
  // pill's ink, as it draws`, which reads both ends off the two class strings
  // here rather than restating them. The pair itself is in that file's
  // contract, in both modes.
  [ReadStatus.did_not_finish]:
    "bg-paper-200 text-paper-800 dark:bg-paper-800 dark:text-paper-200",
};

/**
 * The order the statuses are offered in, everywhere they are offered.
 *
 * A reading lifecycle rather than an alphabet: not started, means to, in
 * progress, finished, gave up. The library filter strip and a book's own status
 * picker both render it, and each used to write it out again.
 *
 * A literal rather than `Object.values(ReadStatus)`, which cannot be incomplete
 * and is still the wrong source: the generated enum happens to declare these
 * five in this sequence today, so a regen after somebody reorders the backend
 * enum would reorder the strip and the picker with nothing red anywhere.
 */
export const STATUS_ORDER = everyOneOf<ReadStatus>()([
  ReadStatus.unread,
  ReadStatus.want_to_read,
  ReadStatus.reading,
  ReadStatus.read,
  ReadStatus.did_not_finish,
]);

/**
 * What each ownership is called. Same reason, same shape.
 */
export const OWNERSHIP_LABELS: Record<OwnershipStatus, MessageKey> = {
  [OwnershipStatus.owned]: "ownership.owned",
  [OwnershipStatus.not_owned]: "ownership.not_owned",
  [OwnershipStatus.unknown]: "ownership.unknown",
};

/**
 * What each format and condition is called.
 *
 * Here rather than in the copy editor because a page's worth of things name
 * them, and a list of which ones is the thing that goes stale: the version of
 * this sentence that named four was already short by two. Copies of this table
 * drift, and the copy that drifts is the one nobody is looking at, so every one
 * of them is built from this pair rather than written out again.
 *
 * `Record<...>` and not a lookup with a default, for the same reason
 * `TAG_PILL_CLASSES` is: a value added to the backend enum has to be a compile
 * error here rather than a blank cell nobody notices.
 */
export const FORMAT_LABELS: Record<BookFormat, MessageKey> = {
  [BookFormat.hardcover]: "copy.format.hardcover",
  [BookFormat.paperback]: "copy.format.paperback",
  [BookFormat.ebook]: "copy.format.ebook",
  [BookFormat.audiobook]: "copy.format.audiobook",
  [BookFormat.comic]: "copy.format.comic",
  [BookFormat.other]: "copy.format.other",
};

/**
 * The order they are offered in, coarsest first.
 *
 * Every dropdown and filter in the app is built from it, so a format left out
 * is one a member can never choose and never filter by. The compiler refuses
 * that now, where a set equality test used to catch it. The test could not see
 * a duplicate and had no opinion on where the catch-all sits, so
 * `tests/pages/types.test.ts` still names both of those separately.
 */
export const FORMAT_ORDER = everyOneOf<BookFormat>()([
  BookFormat.hardcover,
  BookFormat.paperback,
  BookFormat.ebook,
  BookFormat.audiobook,
  BookFormat.comic,
  BookFormat.other,
]);

export const CONDITION_LABELS: Record<BookCondition, MessageKey> = {
  [BookCondition.new]: "copy.condition.new",
  [BookCondition.good]: "copy.condition.good",
  [BookCondition.fair]: "copy.condition.fair",
  [BookCondition.poor]: "copy.condition.poor",
  [BookCondition.ex_library]: "copy.condition.ex_library",
};

/**
 * Best to worst, with the provenance category last: it is not a point on the
 * scale, so sorting it into the middle would imply it is one.
 *
 * Wrapped alongside `STATUS_ORDER` rather than left as it was, because it was
 * the one list here with no guard of any kind: the copy editor's condition
 * select is built from it and nothing else reads it, so a condition added to
 * the backend enum was unreachable in the editor with no compile error and no
 * red test. That is the same defect the two status tables had, one enum over.
 */
export const CONDITION_ORDER = everyOneOf<BookCondition>()([
  BookCondition.new,
  BookCondition.good,
  BookCondition.fair,
  BookCondition.poor,
  BookCondition.ex_library,
]);

/**
 * What each answer to "would you lend this" is called.
 *
 * Here for the same reason the two tables above are: four places name these
 * now (the lend panel's select, the card's fold out, the table column and the
 * library filter), and the copy that drifts is the one nobody is looking at.
 *
 * The strings are deliberately about the owner rather than about the book.
 * "Not available" would describe a state; "I am using it myself" describes a
 * person, and that is what the field records.
 */
export const LENDING_LABELS: Record<LendingWillingness, MessageKey> = {
  [LendingWillingness.in_use]: "lending.in_use",
  [LendingWillingness.never]: "lending.never",
  [LendingWillingness.happy]: "lending.happy",
};

/**
 * Yes, later, no. Offered in the order somebody would say them.
 *
 * The sorted array comparison this replaced did three jobs in one expression,
 * and the wrap takes one of them. A duplicate is still a test's to catch: a
 * list naming an answer twice excludes nothing, so the type has no opinion.
 */
export const LENDING_ORDER = everyOneOf<LendingWillingness>()([
  LendingWillingness.happy,
  LendingWillingness.in_use,
  LendingWillingness.never,
]);

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
 * Custom keeps the accent, so a tag the library invented still reads as theirs
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

/**
 * Group a flat tag list into its categories, in display order.
 *
 * Ordered here rather than trusted from the endpoint, which sorts on
 * `Tag.category, Tag.name` and so files an accented tag after `z` inside its
 * category. Grouping and ordering are one call on purpose: this is the only
 * road to a rendered tag list, so a caller cannot get the grouping without the
 * ordering. The categories themselves keep `TAG_CATEGORY_ORDER`, which is a
 * curated sequence and not alphabetical. See `lib/nameOrder.ts`.
 *
 * Ordered by the **printed** name, which for a seeded tag is not the stored
 * one: a German picker sorted on `name` would file Belletristik under F, in an
 * order justified by words the reader is not being shown.
 */
export function groupTagsByCategory(
  tags: TagOut[],
  locale: Locale,
): Record<TagCategory, TagOut[]> {
  const ordered = sortByName(tags, locale, (tag) => tagName(tag, locale));
  return {
    [TagCategory.type]: ordered.filter(
      (tag) => tag.category === TagCategory.type,
    ),
    [TagCategory.genre]: ordered.filter(
      (tag) => tag.category === TagCategory.genre,
    ),
    [TagCategory.age]: ordered.filter(
      (tag) => tag.category === TagCategory.age,
    ),
    [TagCategory.custom]: ordered.filter(
      (tag) => tag.category === TagCategory.custom,
    ),
  };
}

/**
 * What each light and dark mode is called.
 *
 * Here rather than in the picker because two screens name them: the picker
 * draws the buttons, and the settings list prints the one in force in its
 * summary. Written twice they drift, and the copy that was indexed with a
 * `Record<string, MessageKey>` needed a non-null assertion to compile, which
 * is what a fourth mode would have silently walked past.
 */
export const MODE_LABELS: Record<ThemePreference, MessageKey> = {
  light: "theme.light",
  dark: "theme.dark",
  system: "theme.system",
};

/**
 * The order they are offered in.
 *
 * `system` last rather than first: it is the default, and a default reads
 * better as the thing you return to than the thing you start at.
 *
 * `ThemePreference` is a bare string union with no runtime object to
 * enumerate, so what guarded this before the wrap was a **pair**: `MODE_LABELS`
 * is a total `Record` over the union, and the retired test compared this order
 * against its keys. Drop a mode from the table and `tsc` refuses it, TS2741,
 * measured 2026-09-25. The pair held, so the wrap closes no hole: what it buys
 * is one instrument at the declaration, which does not depend on that table
 * staying total.
 */
export const MODE_ORDER = everyOneOf<ThemePreference>()([
  "light",
  "dark",
  "system",
]);
