import { Link } from "react-router-dom";

import { ApiError } from "../../../api/mutator";
import { BookFormat } from "../../../api/generated/model";
import type { LocationOut, TagOut } from "../../../api/generated/model";
import { ErrorState } from "../../../components";
import { useTranslation, type MessageKey } from "../../../i18n";
import { CoverImage, LocationField, TagPicker } from "../../components";
import type { BookDraft } from "../types";

interface LookupResultProps {
  draft: BookDraft;
  tags: TagOut[];
  selectedTagIds: number[];
  coverFile: File | null;
  isPrivate: boolean;
  location: string;
  locations: LocationOut[];
  format: BookFormat | "";
  isAdding: boolean;
  error: unknown;
  onDraftChange: (draft: BookDraft) => void;
  onToggleTag: (tagId: number) => void;
  onCoverChange: (file: File | null) => void;
  onPrivateChange: (isPrivate: boolean) => void;
  onLocationChange: (location: string) => void;
  /** Invent a tag mid-scan. Cataloguing a new shelf is when one is needed. */
  onCreateTag: (name: string) => void;
  isCreatingTag?: boolean;
  onFormatChange: (format: BookFormat | "") => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * The confirm-before-adding card.
 *
 * Shows a read-only summary when a source knew the ISBN, and editable fields
 * when neither did. Presentational, used only by ScanPage.
 */
const FORMATS: { value: BookFormat; label: MessageKey }[] = [
  { value: BookFormat.hardcover, label: "copy.format.hardcover" },
  { value: BookFormat.paperback, label: "copy.format.paperback" },
  { value: BookFormat.ebook, label: "copy.format.ebook" },
  { value: BookFormat.audiobook, label: "copy.format.audiobook" },
  { value: BookFormat.other, label: "copy.format.other" },
];

export default function LookupResult({
  draft,
  tags,
  selectedTagIds,
  coverFile,
  isPrivate,
  location,
  locations,
  format,
  isAdding,
  error,
  onDraftChange,
  onToggleTag,
  onCoverChange,
  onPrivateChange,
  onLocationChange,
  onCreateTag,
  isCreatingTag = false,
  onFormatChange,
  onConfirm,
  onCancel,
}: LookupResultProps) {
  const { t } = useTranslation();
  return (
    <div className="bg-paper-0 rounded-2xl border border-paper-100 shadow-sm overflow-hidden dark:bg-paper-900 dark:border-paper-800">
      {/* The outer condition stays: a book with no cover at all shows nothing
          here, rather than a placeholder above a form. A cover that fails to
          load is a different case and does get the placeholder. */}
      {draft.cover_url && !draft.notFound && (
        <CoverImage
          src={draft.cover_url}
          alt={draft.title}
          className="w-32 h-44 mx-auto mt-5 rounded shadow-md object-cover bg-paper-100 dark:bg-paper-800"
        />
      )}

      <div className="p-5">
        {draft.notFound ? (
          <>
            <p className="text-paper-600 text-sm mb-3 dark:text-paper-400">
              {t("scan.notFoundManual", { isbn: draft.isbn })}
            </p>
            <label
              htmlFor="manual-title"
              className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
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
              className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm mb-2 dark:border-paper-700"
              placeholder={t("scan.titlePlaceholder")}
            />
            <label
              htmlFor="manual-author"
              className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
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
              className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
              placeholder={t("scan.authorPlaceholder")}
            />
          </>
        ) : (
          <>
            <h2 className="text-lg font-bold leading-tight">{draft.title}</h2>
            {draft.subtitle && (
              <p className="text-paper-600 text-sm mt-0.5 dark:text-paper-300">
                {draft.subtitle}
              </p>
            )}
            {draft.author && (
              <p className="text-paper-600 text-sm mt-1 dark:text-paper-400">
                {t("book.by", { author: draft.author })}
              </p>
            )}
            {draft.publisher && (
              <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
                {draft.publisher}
                {draft.year ? ` · ${draft.year}` : ""}
              </p>
            )}
            <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
              {t("book.isbn", { isbn: draft.isbn })}
            </p>
          </>
        )}

        {tags.length > 0 && (
          <div className="mt-4">
            <p className="text-sm font-medium text-paper-700 mb-2 dark:text-paper-200">
              {t("library.tags")}
              {selectedTagIds.length > 0 && (
                <span className="ml-1.5 text-xs text-paper-600 dark:text-paper-400">
                  {t("scan.tagsSelected", { count: selectedTagIds.length })}
                </span>
              )}
            </p>
            <TagPicker
              tags={tags}
              selectedIds={selectedTagIds}
              onToggle={onToggleTag}
              onCreate={onCreateTag}
              isCreating={isCreatingTag}
            />
          </div>
        )}

        <div className="mt-4">
          <label
            htmlFor="cover-file"
            className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
          >
            {draft.cover_url ? t("scan.replaceCover") : t("scan.addCover")}
          </label>
          <input
            id="cover-file"
            type="file"
            accept="image/*"
            onChange={(event) => onCoverChange(event.target.files?.[0] ?? null)}
            className="block w-full text-sm text-paper-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-accent-50 file:text-accent-700 hover:file:bg-accent-100 dark:text-paper-400"
          />
          {coverFile && (
            <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
              {coverFile.name}
            </p>
          )}
        </div>

        <div className="mt-4">
          <LocationField
            value={location}
            onChange={onLocationChange}
            locations={locations}
            hint={t("location.carriedOver")}
          />
        </div>

        <label className="block text-sm mt-4">
          <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
            {t("copy.format")}
          </span>
          <select
            value={format}
            onChange={(event) =>
              onFormatChange(event.target.value as BookFormat | "")
            }
            className="field"
          >
            <option value="">{t("copy.format.unset")}</option>
            {FORMATS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 mt-4 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={isPrivate}
            onChange={(event) => onPrivateChange(event.target.checked)}
            className="w-4 h-4 rounded border-paper-300 text-accent-600"
          />
          <span className="text-sm text-paper-700 dark:text-paper-200">
            {t("scan.privateBook")}
          </span>
        </label>

        {error != null && (
          <div className="mt-3 space-y-2">
            <ErrorState error={error} fallback={t("scan.couldNotAdd")} />
            {/* The second pass through a bookcase is mostly books already on
                the shelf, so this is a common outcome rather than an edge one.
                Without the link the reader is holding the book with nothing to
                press, and has to go and find it to check it is the same
                edition. */}
            {error instanceof ApiError && error.bookId != null && (
              <Link
                to={`/book/${error.bookId}`}
                className="inline-block text-sm font-medium text-accent-600 hover:text-accent-700 dark:text-accent-400 dark:hover:text-accent-300"
              >
                {t("scan.openTheOneWeHave")}
              </Link>
            )}
          </div>
        )}

        <div className="flex gap-2 mt-5">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 border border-paper-200 text-paper-600 rounded-lg text-sm font-medium hover:bg-paper-50 transition-colors dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
          >
            {t("common.cancel")}
          </button>
          <button
            onClick={onConfirm}
            disabled={isAdding || !draft.title}
            className="flex-1 py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-sm font-semibold transition-colors"
          >
            {isAdding ? t("scan.adding") : t("scan.addToLibrary")}
          </button>
        </div>
      </div>
    </div>
  );
}
