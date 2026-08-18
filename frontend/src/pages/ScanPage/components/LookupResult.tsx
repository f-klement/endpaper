import type { TagOut } from "../../../api/generated/model";
import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import { TagPicker } from "../../components";
import type { BookDraft } from "../types";

interface LookupResultProps {
  draft: BookDraft;
  tags: TagOut[];
  selectedTagIds: number[];
  coverFile: File | null;
  isPrivate: boolean;
  isAdding: boolean;
  error: unknown;
  onDraftChange: (draft: BookDraft) => void;
  onToggleTag: (tagId: number) => void;
  onCoverChange: (file: File | null) => void;
  onPrivateChange: (isPrivate: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * The confirm-before-adding card.
 *
 * Shows a read-only summary when a source knew the ISBN, and editable fields
 * when neither did. Presentational, used only by ScanPage.
 */
export default function LookupResult({
  draft,
  tags,
  selectedTagIds,
  coverFile,
  isPrivate,
  isAdding,
  error,
  onDraftChange,
  onToggleTag,
  onCoverChange,
  onPrivateChange,
  onConfirm,
  onCancel,
}: LookupResultProps) {
  const { t } = useTranslation();
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden dark:bg-gray-900 dark:border-gray-800">
      {draft.cover_url && !draft.notFound && (
        <img
          src={draft.cover_url}
          alt={draft.title}
          className="w-32 mx-auto mt-5 rounded shadow-md"
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
      )}

      <div className="p-5">
        {draft.notFound ? (
          <>
            <p className="text-gray-500 text-sm mb-3 dark:text-gray-400">
              {t("scan.notFoundManual", { isbn: draft.isbn })}
            </p>
            <label
              htmlFor="manual-title"
              className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-200"
            >
              {t("scan.titleRequired")}
            </label>
            <input
              id="manual-title"
              type="text"
              value={draft.title}
              onChange={(event) =>
                onDraftChange({ ...draft, title: event.target.value })
              }
              className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 mb-2 dark:border-gray-700"
              placeholder={t("scan.titlePlaceholder")}
            />
            <label
              htmlFor="manual-author"
              className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-200"
            >
              {t("scan.authorField")}
            </label>
            <input
              id="manual-author"
              type="text"
              value={draft.author ?? ""}
              onChange={(event) =>
                onDraftChange({ ...draft, author: event.target.value })
              }
              className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 dark:border-gray-700"
              placeholder={t("scan.authorPlaceholder")}
            />
          </>
        ) : (
          <>
            <h2 className="text-lg font-bold leading-tight">{draft.title}</h2>
            {draft.subtitle && (
              <p className="text-gray-600 text-sm mt-0.5 dark:text-gray-300">
                {draft.subtitle}
              </p>
            )}
            {draft.author && (
              <p className="text-gray-500 text-sm mt-1 dark:text-gray-400">
                {t("book.by", { author: draft.author })}
              </p>
            )}
            {draft.publisher && (
              <p className="text-xs text-gray-400 mt-1 dark:text-gray-500">
                {draft.publisher}
                {draft.year ? ` · ${draft.year}` : ""}
              </p>
            )}
            <p className="text-xs text-gray-400 mt-1 dark:text-gray-500">
              {t("book.isbn", { isbn: draft.isbn })}
            </p>
          </>
        )}

        {tags.length > 0 && (
          <div className="mt-4">
            <p className="text-sm font-medium text-gray-700 mb-2 dark:text-gray-200">
              {t("library.tags")}
              {selectedTagIds.length > 0 && (
                <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">
                  {t("scan.tagsSelected", { count: selectedTagIds.length })}
                </span>
              )}
            </p>
            <TagPicker
              tags={tags}
              selectedIds={selectedTagIds}
              onToggle={onToggleTag}
            />
          </div>
        )}

        <div className="mt-4">
          <label
            htmlFor="cover-file"
            className="block text-sm font-medium text-gray-700 mb-1 dark:text-gray-200"
          >
            {draft.cover_url ? t("scan.replaceCover") : t("scan.addCover")}
          </label>
          <input
            id="cover-file"
            type="file"
            accept="image/*"
            onChange={(event) => onCoverChange(event.target.files?.[0] ?? null)}
            className="block w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-sky-50 file:text-sky-600 hover:file:bg-sky-100 dark:text-gray-400"
          />
          {coverFile && (
            <p className="text-xs text-gray-400 mt-1 dark:text-gray-500">
              {coverFile.name}
            </p>
          )}
        </div>

        <label className="flex items-center gap-2 mt-4 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={isPrivate}
            onChange={(event) => onPrivateChange(event.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-sky-500 focus:ring-sky-400"
          />
          <span className="text-sm text-gray-700 dark:text-gray-200">
            {t("scan.privateBook")}
          </span>
        </label>

        {error != null && (
          <div className="mt-3">
            <ErrorState error={error} fallback={t("scan.couldNotAdd")} />
          </div>
        )}

        <div className="flex gap-2 mt-5">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            {t("common.cancel")}
          </button>
          <button
            onClick={onConfirm}
            disabled={isAdding || !draft.title}
            className="flex-1 py-2.5 bg-sky-500 hover:bg-sky-600 disabled:bg-sky-300 text-white rounded-lg text-sm font-semibold transition-colors"
          >
            {isAdding ? t("scan.adding") : t("scan.addToLibrary")}
          </button>
        </div>
      </div>
    </div>
  );
}
