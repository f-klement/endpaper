import { useRef, type ChangeEvent } from "react";
import { Link } from "react-router-dom";

import type { BookOut } from "../../../api/generated/model";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";
import { searchUrl } from "../../../lib/goodreads";

interface BookHeaderProps {
  book: BookOut;
  isRefreshing: boolean;
  refreshError: unknown;
  /** Rendered only when an admin has switched the Goodreads links on. */
  showGoodreadsLink: boolean;
  onBack: () => void;
  onUploadCover: (file: File) => void;
  onRefreshMetadata: () => void;
}

/** Cover, title, metadata chips and the refresh control. */
export default function BookHeader({
  book,
  isRefreshing,
  refreshError,
  showGoodreadsLink,
  onBack,
  onUploadCover,
  onRefreshMetadata,
}: BookHeaderProps) {
  const { t } = useTranslation();
  const coverInput = useRef<HTMLInputElement>(null);

  function handleCover(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onUploadCover(file);
    event.target.value = "";
  }

  return (
    <>
      <div className="relative">
        {book.cover_url ? (
          <img
            src={book.cover_url}
            alt={book.title}
            className="w-full h-56 object-cover object-top"
            onError={(event) => {
              event.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="w-full h-56 bg-gradient-to-br from-sky-100 to-sky-200 flex items-center justify-center text-6xl">
            📖
          </div>
        )}

        <button
          onClick={onBack}
          className="absolute top-4 left-4 bg-white/90 backdrop-blur-sm rounded-full p-2 shadow-sm text-gray-700 dark:text-gray-200"
        >
          ← {t("common.back")}
        </button>

        <button
          onClick={() => coverInput.current?.click()}
          className="absolute bottom-3 right-3 bg-white/90 backdrop-blur-sm rounded-full px-3 py-1.5 shadow-sm text-xs font-medium text-gray-700 hover:bg-white transition-colors dark:text-gray-200"
        >
          {t("book.uploadCover")}
        </button>
        <input
          ref={coverInput}
          type="file"
          accept="image/*"
          className="hidden"
          aria-label={t("book.uploadCover")}
          onChange={handleCover}
        />
      </div>

      <div>
        <div className="flex items-start gap-2">
          <h1 className="text-xl font-bold leading-tight flex-1">
            {book.title}
          </h1>
          {showGoodreadsLink && (
            <a
              href={searchUrl(book.title, book.isbn)}
              target="_blank"
              // noreferrer as well as noopener: the target is a third party and
              // has no business knowing which page linked to it.
              rel="noopener noreferrer"
              title={t("goodreads.lookup")}
              aria-label={t("goodreads.lookup")}
              className="shrink-0 mt-1 text-lg leading-none opacity-60 hover:opacity-100 transition-opacity"
            >
              🔗
            </a>
          )}
        </div>
        {book.subtitle && (
          <p className="text-gray-600 mt-0.5 dark:text-gray-300">
            {book.subtitle}
          </p>
        )}
        {book.series_name && (
          <Link
            to={`/?series=${encodeURIComponent(book.series_name)}&sort=series`}
            className="inline-block text-sm text-sky-600 hover:text-sky-700 mt-1 dark:text-sky-400"
          >
            {book.series_index != null
              ? t("series.partOf", {
                  name: book.series_name,
                  index: book.series_index,
                })
              : t("series.partOfUnnumbered", { name: book.series_name })}
          </Link>
        )}
        {book.author && (
          <p className="text-gray-500 text-sm mt-1 dark:text-gray-400">
            {t("book.by", { author: book.author })}
          </p>
        )}

        <div className="flex flex-wrap gap-2 mt-2">
          {book.publisher && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded dark:text-gray-500 dark:bg-gray-800">
              {book.publisher}
            </span>
          )}
          {book.year && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded dark:text-gray-500 dark:bg-gray-800">
              {book.year}
            </span>
          )}
          {book.page_count != null && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded dark:text-gray-500 dark:bg-gray-800">
              {t("book.pages", { count: book.page_count })}
            </span>
          )}
          {book.language && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded uppercase dark:text-gray-500 dark:bg-gray-800">
              {book.language}
            </span>
          )}
          {book.location && (
            <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded dark:text-amber-300 dark:bg-amber-950">
              {book.location}
            </span>
          )}
          {book.isbn && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded dark:text-gray-500 dark:bg-gray-800">
              {t("book.isbn", { isbn: book.isbn })}
            </span>
          )}
        </div>

        {/* Refreshing needs an ISBN to look anything up. */}
        {book.isbn && (
          <div className="mt-2">
            <button
              onClick={onRefreshMetadata}
              disabled={isRefreshing}
              className="text-xs text-sky-500 hover:text-sky-700 disabled:text-sky-300 transition-colors"
            >
              {isRefreshing ? t("book.refreshing") : t("book.refreshMetadata")}
            </button>
            {refreshError != null && (
              <p className="text-xs text-red-500 mt-1 dark:text-red-400">
                {errorText(refreshError, t("common.somethingWentWrong"))}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}
