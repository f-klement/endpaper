import type { BookOut, DuplicateGroup } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface DuplicateCardProps {
  group: DuplicateGroup;
  isMerging: boolean;
  onMerge: (bookIds: number[], keepId: number) => void;
}

/** A short line describing what distinguishes one entry from its twin. */
function describe(book: BookOut): string {
  return [book.publisher, book.year, book.isbn].filter(Boolean).join(" · ");
}

/**
 * One suspected duplicate group, with a "keep this one" per entry.
 *
 * The choice is per entry rather than a single merge button, because which
 * copy survives matters: the survivor keeps its own values and only absorbs
 * what it is missing.
 */
export default function DuplicateCard({
  group,
  isMerging,
  onMerge,
}: DuplicateCardProps) {
  const { t } = useTranslation();
  const bookIds = group.books.map((book) => book.id);

  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-4 space-y-3 dark:bg-gray-900 dark:border-gray-700">
      <ul className="space-y-2">
        {group.books.map((book) => (
          <li
            key={book.id}
            className="flex items-center gap-3 border border-gray-100 rounded-xl p-2 dark:border-gray-800"
          >
            {book.cover_url ? (
              <img
                src={book.cover_url}
                alt=""
                className="w-10 h-14 object-cover rounded shrink-0 bg-gray-100 dark:bg-gray-800"
                onError={(event) => {
                  event.currentTarget.style.visibility = "hidden";
                }}
              />
            ) : (
              <div className="w-10 h-14 rounded shrink-0 bg-gray-100 flex items-center justify-center dark:bg-gray-800">
                📖
              </div>
            )}

            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 truncate dark:text-gray-100">
                {book.title}
              </p>
              <p className="text-xs text-gray-500 truncate dark:text-gray-400">
                {describe(book)}
              </p>
            </div>

            <button
              type="button"
              disabled={isMerging}
              onClick={() => {
                if (
                  confirm(
                    t("duplicates.confirm", {
                      count: group.books.length - 1,
                      title: book.title,
                    }),
                  )
                ) {
                  onMerge(bookIds, book.id);
                }
              }}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-sky-500 text-white text-xs font-medium hover:bg-sky-600 disabled:opacity-40 transition-colors"
            >
              {isMerging ? t("duplicates.merging") : t("duplicates.keepThis")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
