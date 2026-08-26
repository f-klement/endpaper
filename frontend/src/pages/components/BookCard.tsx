import { useState } from "react";
import { Link } from "react-router-dom";

import {
  OwnershipStatus,
  ReadStatus,
  TagCategory,
  type BookOut,
  type TagOut,
} from "../../api/generated/model";
import { useTranslation, type MessageKey, type Translate } from "../../i18n";
import { formatMinor } from "../../lib/money";
import {
  CONDITION_LABELS,
  FORMAT_LABELS,
  LENDING_LABELS,
  STATUS_LABELS,
  TAG_PILL_CLASSES,
} from "../types";
import { Icon } from "../../components";
import CoverImage from "./CoverImage";

// Exhaustive by type: adding a status to the backend enum makes this a
// compile error until it is given a presentation here, which is how the
// `want_to_read` status was caught rather than rendering as a blank pill.
const STATUS_STYLES: Record<ReadStatus, string> = {
  // **Below the floor, and pre-existing.** Measured across all seven palettes
  // as it actually draws (paper-600 on paper-200 at 70% over the paper-0 card):
  // worst 3.97:1 on solarized, then 4.02 nord and 4.27 catppuccin, against the
  // 4.5 every text pair in `tests/theme/palettes.test.ts` is held to. Not
  // changed here, because a status pill's colour is a design decision across
  // five values and this change owns one of them; recorded rather than left to
  // be rediscovered, and `docs/decisions.md` carries the numbers. The test
  // added with `did_not_finish` pins that pill only.
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
  // Measured across all seven palettes, flat: 600 on 200 bottoms out at
  // **3.55:1 (solarized)**, 700 at 4.19:1 (solarized), and 800 at **4.57:1
  // (catppuccin)**, which is the only one of the three that clears 4.5
  // everywhere. The pair is held to that floor by
  // `tests/theme/palettes.test.ts`, on every palette and both modes.
  [ReadStatus.did_not_finish]:
    "bg-paper-200 text-paper-800 dark:bg-paper-800 dark:text-paper-200",
};

/**
 * Tags shown on the face of the card. The rest are in the fold out.
 *
 * Three rather than two, and genre first rather than whatever order the API
 * returned: what a book *is* is the thing somebody scanning a shelf is
 * matching on, and an age band or a library filing tag arriving first used
 * to push the genre off the card entirely.
 */
const MAX_VISIBLE_TAGS = 3;

function facePills(tags: TagOut[]): TagOut[] {
  const genre = tags.filter((tag) => tag.category === TagCategory.genre);
  const rest = tags.filter((tag) => tag.category !== TagCategory.genre);
  return [...genre, ...rest].slice(0, MAX_VISIBLE_TAGS);
}

/** One row of the fold out, or nothing when the book has no such value. */
interface Fact {
  label: MessageKey;
  value: string;
}

function seriesText(book: BookOut, t: Translate): string | null {
  if (!book.series_name) return null;
  return book.series_index === null || book.series_index === undefined
    ? t("series.partOfUnnumbered", { name: book.series_name })
    : t("series.partOf", { name: book.series_name, index: book.series_index });
}

/**
 * The price with its currency, or nothing.
 *
 * Currency is free text on the record and is often absent, so the amount is
 * shown on its own rather than being suppressed for want of a label: what was
 * paid is the fact somebody recorded, and which currency is usually obvious to
 * the library that recorded it.
 */
function priceText(book: BookOut): string | null {
  const amount = formatMinor(book.purchase_price_minor);
  if (!amount) return null;
  return book.purchase_currency ? `${amount} ${book.purchase_currency}` : amount;
}

function factsFor(book: BookOut, hiddenTags: TagOut[], t: Translate): Fact[] {
  const candidates: [MessageKey, string | number | null | undefined][] = [
    ["series.label", seriesText(book, t)],
    ["field.year", book.year],
    ["field.publisher", book.publisher],
    ["location.label", book.location],
    ["copy.format", book.format ? t(FORMAT_LABELS[book.format]) : null],
    [
      "copy.condition",
      book.condition ? t(CONDITION_LABELS[book.condition]) : null,
    ],
    ["lending.label", book.lending ? t(LENDING_LABELS[book.lending]) : null],
    [
      "discuss.label",
      (book.discuss_with ?? []).map((member) => member.username).join(", "),
    ],
    ["field.pageCount", book.page_count],
    ["library.tags", hiddenTags.map((tag) => tag.name).join(", ")],
    ["copy.price", priceText(book)],
    ["copy.purchasedAt", book.purchased_at],
    ["copy.purchaseSource", book.purchase_source],
  ];
  return candidates
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([label, value]) => ({ label, value: String(value) }));
}

interface BookCardProps {
  book: BookOut;
  /** While selecting, the card ticks a box instead of navigating. */
  isSelecting?: boolean;
  isSelected?: boolean;
  onToggleSelect?: (bookId: number) => void;
}

/**
 * One book in the grid. Presentational: it takes a book and renders it.
 *
 * Shared rather than Home's own, because the appearance picker previews a
 * palette on the reader's own first two books and a card drawn only for the
 * preview would be the invented sample content the picker exists to avoid.
 *
 * **The fold out toggle is a sibling of the link, never a child of it.** A
 * button inside an anchor is invalid HTML, and browsers resolve the ambiguity
 * differently: some navigate, some fire the button, and a screen reader reads
 * one control where there are two. So the card is a plain container holding a
 * link and a button, rather than a link wrapping everything.
 */
export default function BookCard({
  book,
  isSelecting = false,
  isSelected = false,
  onToggleSelect,
}: BookCardProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  const status = book.my_status ?? ReadStatus.unread;
  const isUnconfirmed = book.ownership === OwnershipStatus.unknown;
  const wantsDiscussion = (book.discuss_with ?? []).length > 0;
  const tags = book.tags ?? [];
  const shown = facePills(tags);
  const hidden = tags.filter((tag) => !shown.includes(tag));
  const facts = factsFor(book, hidden, t);

  const face = (
    <>
      <div className="aspect-[2/3] bg-paper-100 relative overflow-hidden dark:bg-paper-800">
        {/* A cover fails more often than it looks, and a broken-image icon
            reads as a bug in our app rather than a gap in a catalogue. */}
        <CoverImage
          src={book.cover_url}
          alt={book.title}
          loading="lazy"
          className="w-full h-full object-cover bg-gradient-to-br from-accent-100 to-accent-200"
        />

        {isSelecting && (
          <div
            aria-hidden="true"
            className={`absolute top-1.5 left-1.5 w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-bold ${
              isSelected
                ? "bg-accent-fill border-accent-fill text-on-accent"
                : "bg-paper-0/90 border-paper-300 text-transparent"
            }`}
          >
            <Icon name="check" className="w-3.5 h-3.5" strokeWidth={2.5} />
          </div>
        )}

        {/* Ownership is shown only when it is in doubt. A badge on every owned
            book would be noise on the overwhelming majority of the grid. */}
        {isUnconfirmed && (
          <div className="absolute bottom-1.5 left-1.5 bg-amber-500/90 text-white text-xs font-medium px-1.5 py-0.5 rounded-full">
            {t("ownership.unknown")}
          </div>
        )}

        {book.active_loan && (
          <div className="absolute top-1.5 right-1.5 bg-orange-500 text-white text-xs font-medium px-1.5 py-0.5 rounded-full">
            {t("library.loaned")}
          </div>
        )}

        {/* On the face of the card, not in the fold out. The offer exists to
            be noticed by somebody browsing, and a marker that needs a click to
            find is a marker only the person who set it ever sees. Bottom
            right, which is the one corner nothing else uses: ownership takes
            bottom left and a loan takes top right. */}
        {wantsDiscussion && (
          <div className="absolute bottom-1.5 right-1.5 bg-accent-fill text-on-accent text-xs font-medium px-1.5 py-0.5 rounded-full">
            {t("discuss.badge")}
          </div>
        )}
      </div>
      <div className="p-2.5">
        <h3 className="font-semibold text-sm leading-tight line-clamp-2 mb-0.5">
          {book.title}
        </h3>
        {book.author && (
          <p className="text-xs text-paper-600 truncate dark:text-paper-400">
            {book.author}
          </p>
        )}
        <div className="flex flex-wrap gap-1 mt-1.5">
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[status]}`}
          >
            {t(STATUS_LABELS[status])}
          </span>
          {/* Only when there is more than one, and on the face rather than in
              the fold out. Two copies are two rows and the grid draws both, so
              without this the shelf looks like a catalogue that has
              double-added something, which is the one reading this feature
              must not produce. The paper ramp, not a semantic colour: owning a
              spare paperback is neither a warning nor an achievement.
              `paper-800` on `paper-200`, the pair the `did_not_finish` pill
              already uses and the only one of that ramp measured over 4.5:1 on
              every palette. */}
          {(book.copy_count ?? 1) > 1 && (
            <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-paper-200 text-paper-800 dark:bg-paper-800 dark:text-paper-200">
              {t("copies.badge", { count: book.copy_count ?? 1 })}
            </span>
          )}
          {shown.map((tag) => (
            <span
              key={tag.id}
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${TAG_PILL_CLASSES[tag.category]}`}
            >
              {tag.name}
            </span>
          ))}
        </div>
      </div>
    </>
  );

  // A button, not a link with its navigation suppressed: while selecting, the
  // card genuinely is a checkbox, and it should be announced and behave like
  // one rather than like a link that mysteriously goes nowhere.
  //
  // No fold out in this mode, and that is not an omission. A button inside a
  // button is invalid for the same reason a button inside a link is, and
  // somebody ticking twenty boxes is not reading page counts.
  if (isSelecting) {
    return (
      <button
        type="button"
        role="checkbox"
        aria-checked={isSelected}
        aria-label={book.title}
        onClick={() => onToggleSelect?.(book.id)}
        className={`card overflow-hidden block w-full text-left ${
          isSelected
            ? // The ring is what says "selected" on a card whose contents are
              // unchanged, so it has to clear the 3:1 that WCAG 1.4.11 asks of
              // a non-text indicator. `accent-400/50` composited to 1.52:1 over
              // the card. This is the focus ring's own step at full opacity:
              // 3.09:1 on the light page and 5.98:1 on the dark one, and every
              // palette holds that rung to the same floor.
              "border-accent-500 ring-2 ring-accent-500"
            : ""
        }`}
      >
        {face}
      </button>
    );
  }

  return (
    <div className="card overflow-hidden card-interactive">
      <Link to={`/book/${book.id}`} className="block">
        {face}
      </Link>

      {facts.length > 0 && (
        <>
          <button
            type="button"
            aria-expanded={isOpen}
            // No `aria-controls`, deliberately. The panel is rendered only when
            // open, which is right (25 hidden definition lists per page is real
            // DOM nobody asked for), and ARIA requires the reference to resolve
            // to an element that is in the document. A dangling id is worse
            // than none: `aria-expanded` plus DOM adjacency already says what
            // this button does, and every screen reader announces it.
            // Named after the book, not just "Details": a grid of 25 identical
            // buttons is unusable from a screen reader's control list.
            aria-label={t("card.detailsFor", { title: book.title })}
            onClick={() => setIsOpen((open) => !open)}
            className="flex w-full items-center justify-between gap-1 border-t border-paper-200 px-2.5 py-1.5 text-xs font-medium text-paper-600 transition-colors hover:bg-paper-100 hover:text-paper-800 dark:border-paper-800 dark:text-paper-400 dark:hover:bg-paper-800 dark:hover:text-paper-100"
          >
            <span aria-hidden="true">{t("card.details")}</span>
            <Icon
              name="chevron"
              className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-90" : ""}`}
            />
          </button>

          {/* Rendered only when open rather than hidden with CSS: a closed card
              is the common case, and 25 hidden definition lists per page is
              real DOM for something nobody has asked to see. */}
          {isOpen && (
            <dl className="space-y-1 border-t border-paper-100 px-2.5 py-2 text-xs dark:border-paper-800">
              {facts.map((fact) => (
                <div key={fact.label} className="flex gap-2">
                  <dt className="shrink-0 text-paper-600 dark:text-paper-400">
                    {t(fact.label)}
                  </dt>
                  <dd className="ml-auto text-right text-paper-800 dark:text-paper-200">
                    {fact.value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </>
      )}
    </div>
  );
}
