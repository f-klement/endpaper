import type { BookOut } from "../../../api/generated/model";
import { Skeleton } from "../../../components";
import { useTranslation } from "../../../i18n";
import BookCard from "./BookCard";

/** Placeholder cards rendered while the first page loads. */
const SKELETON_COUNT = 8;

/** Reflows by available width alone, with no breakpoints. */
const GRID_CLASSES =
  "grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3";

interface BookGridProps {
  books: BookOut[];
  isLoading: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;

  isSelecting?: boolean;
  isSelected?: (bookId: number) => boolean;
  onToggleSelect?: (bookId: number) => void;
}

/** The grid itself, plus its loading and "load more" affordances. */
export default function BookGrid({
  books,
  isLoading,
  hasMore,
  isLoadingMore,
  onLoadMore,
  isSelecting = false,
  isSelected,
  onToggleSelect,
}: BookGridProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div className={GRID_CLASSES} data-testid="book-skeletons">
        {Array.from({ length: SKELETON_COUNT }).map((_, index) => (
          <div
            key={index}
            className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden animate-pulse dark:bg-gray-900 dark:border-gray-800"
          >
            <Skeleton className="aspect-[2/3] rounded-none" />
            <div className="p-2.5 space-y-1.5">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      <div className={GRID_CLASSES}>
        {books.map((book) => (
          <BookCard
            key={book.id}
            book={book}
            isSelecting={isSelecting}
            isSelected={isSelected?.(book.id) ?? false}
            onToggleSelect={onToggleSelect}
          />
        ))}
      </div>

      {hasMore && (
        <div className="flex justify-center mt-6">
          <button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-700 hover:border-sky-300 disabled:opacity-50 transition-colors dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
          >
            {isLoadingMore ? t("common.loading") : t("library.loadMore")}
          </button>
        </div>
      )}
    </>
  );
}
