import { useEffect, useState, type FormEvent } from "react";

import type {
  BookDetailsUpdate,
  BookOut,
  LocationOut,
} from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface ShelfPanelProps {
  book: BookOut;
  /** Existing locations, offered as suggestions rather than as a fixed list. */
  knownLocations: LocationOut[];
  isSaving: boolean;
  onSave: (fields: BookDetailsUpdate) => void;
}

/**
 * Which series a book belongs to, and where the copy physically is.
 *
 * Both are free text and both are edited here rather than in a modal, because
 * the moment somebody wants to record a shelf is the moment they are looking
 * at the book with it in their hand.
 */
export default function ShelfPanel({
  book,
  knownLocations,
  isSaving,
  onSave,
}: ShelfPanelProps) {
  const { t } = useTranslation();
  const [seriesName, setSeriesName] = useState(book.series_name ?? "");
  const [seriesIndex, setSeriesIndex] = useState(
    book.series_index === null || book.series_index === undefined
      ? ""
      : String(book.series_index),
  );
  const [location, setLocation] = useState(book.location ?? "");

  // Re-seed when the book changes underneath, which happens after an
  // enrichment run fills the series in. Without this the form keeps showing
  // the empty values it mounted with.
  useEffect(() => {
    setSeriesName(book.series_name ?? "");
    setSeriesIndex(
      book.series_index === null || book.series_index === undefined
        ? ""
        : String(book.series_index),
    );
    setLocation(book.location ?? "");
  }, [book.series_name, book.series_index, book.location]);

  const dirty =
    seriesName !== (book.series_name ?? "") ||
    location !== (book.location ?? "") ||
    seriesIndex !==
      (book.series_index === null || book.series_index === undefined
        ? ""
        : String(book.series_index));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedIndex = seriesIndex.trim() === "" ? null : Number(seriesIndex);
    onSave({
      // Empty string means "clear", which is why these are normalised to null
      // rather than sent as "". The API distinguishes absent from null, and an
      // empty string would be neither.
      series_name: seriesName.trim() || null,
      series_index:
        parsedIndex !== null && Number.isFinite(parsedIndex)
          ? parsedIndex
          : null,
      location: location.trim() || null,
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
        {t("series.label")}
      </h2>
      <div className="flex gap-2">
        <input
          type="text"
          value={seriesName}
          onChange={(event) => setSeriesName(event.target.value)}
          placeholder={t("series.placeholder")}
          aria-label={t("series.label")}
          className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-400 dark:border-paper-700"
        />
        <input
          type="number"
          step="0.5"
          min="0"
          value={seriesIndex}
          onChange={(event) => setSeriesIndex(event.target.value)}
          placeholder={t("series.numberPlaceholder")}
          aria-label={t("series.numberPlaceholder")}
          className="w-20 px-3 py-2 rounded-xl border border-paper-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-400 dark:border-paper-700"
        />
      </div>

      <h2 className="text-sm font-semibold text-paper-900 pt-1 dark:text-paper-100">
        {t("location.label")}
      </h2>
      <input
        type="text"
        list="known-locations"
        value={location}
        onChange={(event) => setLocation(event.target.value)}
        placeholder={t("location.placeholder")}
        aria-label={t("location.label")}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-400 dark:border-paper-700"
      />
      {/* Suggestions, not a closed list. Free text with no suggestions turns
          into six spellings of "living room" inside a week, but a fixed
          vocabulary chosen before anyone has started is worse. */}
      <datalist id="known-locations">
        {knownLocations.map((known) => (
          <option key={known.name} value={known.name} />
        ))}
      </datalist>
      <p className="text-xs text-paper-500 dark:text-paper-400">
        {t("location.hint")}
      </p>

      {dirty && (
        <button
          type="submit"
          disabled={isSaving}
          className="w-full py-2 rounded-xl bg-accent-600 text-white text-sm font-medium hover:bg-accent-700 disabled:opacity-50 transition-colors"
        >
          {isSaving ? t("common.saving") : t("common.save")}
        </button>
      )}
    </form>
  );
}
