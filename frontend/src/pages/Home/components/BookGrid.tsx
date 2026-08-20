import type { BookOut } from "../../../api/generated/model";
import { Skeleton } from "../../../components";
import { useTranslation } from "../../../i18n";
import BookCard from "../../components/BookCard";

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
            className="bg-paper-0 rounded-xl shadow-sm border border-paper-100 overflow-hidden animate-pulse dark:bg-paper-900 dark:border-paper-800"
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
            className="px-4 py-2 text-sm font-medium rounded-lg border border-paper-200 bg-paper-0 text-paper-700 hover:border-accent-300 disabled:opacity-50 transition-colors dark:border-paper-700 dark:bg-paper-900 dark:text-paper-200"
          >
            {isLoadingMore ? t("common.loading") : t("library.loadMore")}
          </button>
        </div>
      )}
    </>
  );
}
