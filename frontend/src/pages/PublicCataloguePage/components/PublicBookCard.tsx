import { Link } from "react-router-dom";

import type { PublicBookOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import CoverImage from "../../components/CoverImage";

interface PublicBookCardProps {
  book: PublicBookOut;
}

/**
 * One record in the published catalogue.
 *
 * A separate component from `pages/components/BookCard` rather than a mode on
 * it, and that separation is the same argument `schemas/public.py` makes on the
 * server: `BookCard` draws an ownership pill, a reading status, a lending
 * badge and a price, and every one of those is a field the public payload does
 * not carry. A shared component would have to be told which half of itself to
 * draw, and the half it drew would be decided by a prop rather than by the
 * data being absent.
 *
 * **The whole card is one link with one accessible name.** A card whose cover,
 * title and author are three separate links is three stops on a keyboard and
 * three announcements for one record.
 */
export default function PublicBookCard({ book }: PublicBookCardProps) {
  const { t } = useTranslation();
  const credit = (book.authors ?? []).join(", ");

  return (
    <li>
      <Link
        to={`/catalogue/${book.id}`}
        className="group flex gap-3 h-full p-3 rounded-2xl bg-paper-0 border border-paper-200 hover:border-accent-400 dark:bg-paper-900 dark:border-paper-800"
      >
        <CoverImage
          src={book.cover_url}
          // Empty, because the title is beside it in the same link: a screen
          // reader reading the cover's alt text as well would say the title
          // twice for one card.
          alt=""
          loading="lazy"
          className="w-14 shrink-0 aspect-[2/3] rounded-lg bg-paper-100 dark:bg-paper-800 object-cover"
        />
        <span className="min-w-0">
          <span className="block font-medium text-paper-900 group-hover:text-accent-700 dark:text-paper-100 dark:group-hover:text-accent-300">
            {book.title}
          </span>
          {credit && (
            <span className="block text-sm text-paper-600 dark:text-paper-400">
              {t("book.by", { author: credit })}
            </span>
          )}
          {book.year !== null && book.year !== undefined && (
            <span className="block text-xs text-paper-600 dark:text-paper-400 tabular-nums">
              {book.year}
            </span>
          )}
        </span>
      </Link>
    </li>
  );
}
