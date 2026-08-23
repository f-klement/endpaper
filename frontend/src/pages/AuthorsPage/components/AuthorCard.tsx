import { Link } from "react-router-dom";

import type { AuthorOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface AuthorCardProps {
  author: AuthorOut;
  isBusy: boolean;
  isSelected: boolean;
  onToggleSelect: (author: AuthorOut) => void;
  onUndo: (aliasId: number) => void;
}

/**
 * One person, and what the shelf knows about them. Dumb.
 *
 * The link carries the **name**. The API accepts either that or the key, and
 * resolves a spelling a merge folded away, so neither is more durable than the
 * other: a merge moves the key exactly as it moves the name, and what keeps an
 * old link working is the redirect rather than the shape of what it carries.
 * Given that, the name is the one to send, because it is what the library's
 * filter chip then shows, and a chip reading "Author: j r r tolkien" from this
 * card and "Author: J. R. R. Tolkien" from a book page is the same filter
 * describing itself two ways.
 *
 * The other spellings are shown rather than hidden. They are the reason a
 * merge is ever wanted, and a card that quietly showed one spelling would make
 * the other look like a missing book.
 */
export default function AuthorCard({
  author,
  isBusy,
  isSelected,
  onToggleSelect,
  onUndo,
}: AuthorCardProps) {
  const { t } = useTranslation();
  const merged = author.merged ?? [];
  const mergedSpellings = new Set(merged.map((entry) => entry.spelling));
  const others = (author.spellings ?? []).filter(
    (spelling) => spelling !== author.name && !mergedSpellings.has(spelling),
  );

  return (
    <div className="bg-paper-0 border border-paper-200 rounded-2xl p-4 dark:bg-paper-900 dark:border-paper-700">
      {/* A checkbox rather than a card that selects on click: the card's
          primary action is following the name into the library, and a surface
          that sometimes navigates and sometimes selects is the one interaction
          nobody guesses right. Same reasoning as the library's own grid. */}
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggleSelect(author)}
          aria-label={t("authors.select", { name: author.name })}
          className="mt-1 shrink-0"
        />
        <h2 className="font-semibold text-paper-900 flex-1 min-w-0 dark:text-paper-100">
          {author.name}
        </h2>
      </div>
      <p className="text-xs text-paper-600 mt-0.5 dark:text-paper-400">
        {t("authors.bookCount", { count: author.book_count })}
      </p>

      {others.length > 0 && (
        <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
          {t("authors.alsoSpelled", { spellings: others.join(", ") })}
        </p>
      )}

      {merged.map((entry) => (
        <p
          key={entry.alias_id}
          className="text-xs text-paper-600 mt-1 flex items-center gap-1.5 dark:text-paper-400"
        >
          {t("authors.mergedFrom", { spelling: entry.spelling })}
          {/* Undo is offered per row rather than per author: a person who
              folded three spellings in and got one wrong should not have to
              unpick the other two. */}
          <button
            type="button"
            disabled={isBusy}
            onClick={() => onUndo(entry.alias_id)}
            aria-label={t("authors.undo")}
            title={t("authors.undo")}
            className="opacity-60 hover:opacity-100 disabled:opacity-30 leading-none"
          >
            ×
          </button>
        </p>
      ))}

      <div className="mt-3 text-xs">
        <Link
          to={`/?author=${encodeURIComponent(author.name)}`}
          className="text-accent-700 hover:underline dark:text-accent-400"
        >
          {t("authors.browse")}
        </Link>
      </div>
    </div>
  );
}
