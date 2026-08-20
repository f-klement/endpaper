import type { BookOut, DuplicateGroup } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { CoverImage } from "../../components";

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
    <div className="bg-paper-0 border border-paper-200 rounded-2xl p-4 space-y-3 dark:bg-paper-900 dark:border-paper-700">
      <ul className="space-y-2">
        {group.books.map((book) => (
          <li
            key={book.id}
            className="flex items-center gap-3 border border-paper-100 rounded-xl p-2 dark:border-paper-800"
          >
            <CoverImage
              src={book.cover_url}
              alt=""
              className="w-10 h-14 object-cover rounded shrink-0 bg-paper-100 dark:bg-paper-800"
            />

            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-paper-900 truncate dark:text-paper-100">
                {book.title}
              </p>
              <p className="text-xs text-paper-600 truncate dark:text-paper-400">
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
              className="shrink-0 px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
            >
              {isMerging ? t("duplicates.merging") : t("duplicates.keepThis")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
