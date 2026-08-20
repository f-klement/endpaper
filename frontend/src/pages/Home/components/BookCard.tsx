import { Link } from "react-router-dom";

import {
  OwnershipStatus,
  ReadStatus,
  type BookOut,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { TAG_PILL_CLASSES } from "../../types";
import { Icon } from "../../../components";

// Exhaustive by type: adding a status to the backend enum makes this a
// compile error until it is given a presentation here, which is how the
// `want_to_read` status was caught rather than rendering as a blank pill.
const STATUS_STYLES: Record<ReadStatus, string> = {
  [ReadStatus.unread]:
    "bg-paper-200/70 text-paper-600 dark:bg-paper-800 dark:text-paper-300",
  [ReadStatus.want_to_read]:
    "bg-bloom-100 text-bloom-700 dark:bg-bloom-700/25 dark:text-bloom-300",
  [ReadStatus.reading]:
    "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  [ReadStatus.read]:
    "bg-accent-100 text-accent-800 dark:bg-accent-500/15 dark:text-accent-200",
};

const STATUS_LABELS: Record<ReadStatus, MessageKey> = {
  [ReadStatus.unread]: "status.unread",
  [ReadStatus.want_to_read]: "status.want_to_read",
  [ReadStatus.reading]: "status.reading",
  [ReadStatus.read]: "status.read",
};

/** Tags shown before the card gets too tall; the rest are on the detail page. */
const MAX_VISIBLE_TAGS = 2;

interface BookCardProps {
  book: BookOut;
  /** While selecting, the card ticks a box instead of navigating. */
  isSelecting?: boolean;
  isSelected?: boolean;
  onToggleSelect?: (bookId: number) => void;
}

/** One book in the grid. Presentational, used only by Home. */
export default function BookCard({
  book,
  isSelecting = false,
  isSelected = false,
  onToggleSelect,
}: BookCardProps) {
  const { t } = useTranslation();
  const status = book.my_status ?? ReadStatus.unread;
  const isUnconfirmed = book.ownership === OwnershipStatus.unknown;

  const card = (
    <div
      className={`card overflow-hidden ${
        isSelected
          ? "border-accent-500 ring-2 ring-accent-400/50"
          // Only lifts when it is a link. A card that rises under the cursor
          // while selecting suggests it will navigate, and it will not.
          : isSelecting
            ? ""
            : "card-interactive"
      }`}
    >
      <div className="aspect-[2/3] bg-paper-100 relative overflow-hidden dark:bg-paper-800">
        {book.cover_url ? (
          <img
            src={book.cover_url}
            alt={book.title}
            className="w-full h-full object-cover"
            loading="lazy"
            // Open Library cover URLs 404 often; a broken-image icon reads
            // as a bug in our app rather than a gap in their catalogue.
            onError={(event) => {
              event.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-4xl bg-gradient-to-br from-accent-100 to-accent-200"><Icon name="book" className="w-1/3 h-1/3 opacity-40" /></div>
        )}

        {isSelecting && (
          <div
            aria-hidden="true"
            className={`absolute top-1.5 left-1.5 w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-bold ${
              isSelected
                ? "bg-accent-600 border-accent-600 text-white"
                : "bg-white/90 border-paper-300 text-transparent"
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
      </div>
      <div className="p-2.5">
        <h3 className="font-semibold text-sm leading-tight line-clamp-2 mb-0.5">
          {book.title}
        </h3>
        {book.author && (
          <p className="text-xs text-paper-500 truncate dark:text-paper-400">
            {book.author}
          </p>
        )}
        <div className="flex flex-wrap gap-1 mt-1.5">
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[status]}`}
          >
            {t(STATUS_LABELS[status])}
          </span>
          {(book.tags ?? []).slice(0, MAX_VISIBLE_TAGS).map((tag) => (
            <span
              key={tag.id}
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${TAG_PILL_CLASSES[tag.category]}`}
            >
              {tag.name}
            </span>
          ))}
        </div>
      </div>
    </div>
  );

  // A button, not a link with its navigation suppressed: while selecting, the
  // card genuinely is a checkbox, and it should be announced and behave like
  // one rather than like a link that mysteriously goes nowhere.
  if (isSelecting) {
    return (
      <button
        type="button"
        role="checkbox"
        aria-checked={isSelected}
        aria-label={book.title}
        onClick={() => onToggleSelect?.(book.id)}
        className="block w-full text-left"
      >
        {card}
      </button>
    );
  }

  return (
    <Link to={`/book/${book.id}`} className="block">
      {card}
    </Link>
  );
}
