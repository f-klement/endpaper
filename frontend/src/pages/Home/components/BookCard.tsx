import { Link } from "react-router-dom";

import {
  OwnershipStatus,
  ReadStatus,
  type BookOut,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { TAG_PILL_CLASSES } from "../../types";

// Exhaustive by type: adding a status to the backend enum makes this a
// compile error until it is given a presentation here, which is how the
// `want_to_read` status was caught rather than rendering as a blank pill.
const STATUS_STYLES: Record<ReadStatus, string> = {
  [ReadStatus.unread]: "bg-gray-100 text-gray-600",
  [ReadStatus.want_to_read]: "bg-sky-100 text-sky-700",
  [ReadStatus.reading]: "bg-yellow-100 text-yellow-700",
  [ReadStatus.read]: "bg-green-100 text-green-700",
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
      className={`bg-white rounded-xl shadow-sm border overflow-hidden transition-shadow ${
        isSelected
          ? "border-sky-400 ring-2 ring-sky-300"
          : "border-gray-100 hover:shadow-md"
      }`}
    >
      <div className="aspect-[2/3] bg-gray-100 relative overflow-hidden dark:bg-gray-800">
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
          <div className="w-full h-full flex items-center justify-center text-4xl bg-gradient-to-br from-sky-100 to-sky-200">
            📖
          </div>
        )}

        {isSelecting && (
          <div
            aria-hidden="true"
            className={`absolute top-1.5 left-1.5 w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-bold ${
              isSelected
                ? "bg-sky-500 border-sky-500 text-white"
                : "bg-white/90 border-gray-300 text-transparent"
            }`}
          >
            ✓
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
          <p className="text-xs text-gray-500 truncate dark:text-gray-400">
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
