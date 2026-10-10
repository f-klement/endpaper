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
 * The form's fields as the stored book fills them, an absent value being an
 * empty field. One place, because the panel reads it three times: to seed the
 * form, to reseed it when the book changes underneath, and to tell whether
 * anything was edited.
 */
function shelfDraft(book: BookOut) {
  return {
    seriesName: book.series_name ?? "",
    seriesIndex:
      book.series_index === null || book.series_index === undefined
        ? ""
        : String(book.series_index),
    location: book.location ?? "",
  };
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
  const saved = shelfDraft(book);
  const [seriesName, setSeriesName] = useState(saved.seriesName);
  const [seriesIndex, setSeriesIndex] = useState(saved.seriesIndex);
  const [location, setLocation] = useState(saved.location);

  // Re-seed when the book changes underneath, which happens after an
  // enrichment run fills the series in. Without this the form keeps showing
  // the empty values it mounted with. Keyed on the draft's own values, the
  // ones the seed and the dirty check read, so a column flipping between null
  // and undefined, which is the same empty field, does not reseed. Keep the
  // keys primitive: keyed on `saved` itself, a fresh object every render, the
  // effect would wipe an edit on every keystroke.
  useEffect(() => {
    setSeriesName(saved.seriesName);
    setSeriesIndex(saved.seriesIndex);
    setLocation(saved.location);
  }, [saved.seriesName, saved.seriesIndex, saved.location]);

  const dirty =
    seriesName !== saved.seriesName ||
    location !== saved.location ||
    seriesIndex !== saved.seriesIndex;

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
      {/* h3, not h2: the section handle that folds this panel away is the
          h2 above it, so a flat h2 here would show a reader's heading list a
          page with no grouping in it at all. */}
      <h3 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
        {t("series.label")}
      </h3>
      <div className="flex gap-2">
        <input
          type="text"
          value={seriesName}
          onChange={(event) => setSeriesName(event.target.value)}
          placeholder={t("series.placeholder")}
          aria-label={t("series.label")}
          className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
        />
        <input
          type="number"
          step="0.5"
          min="0"
          value={seriesIndex}
          onChange={(event) => setSeriesIndex(event.target.value)}
          placeholder={t("series.numberPlaceholder")}
          aria-label={t("series.numberPlaceholder")}
          className="w-20 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
        />
      </div>

      <h3 className="text-sm font-semibold text-paper-900 pt-1 dark:text-paper-100">
        {t("location.label")}
      </h3>
      <input
        type="text"
        list="known-locations"
        value={location}
        onChange={(event) => setLocation(event.target.value)}
        placeholder={t("location.placeholder")}
        aria-label={t("location.label")}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
      />
      {/* Suggestions, not a closed list. Free text with no suggestions turns
          into six spellings of "living room" inside a week, but a fixed
          vocabulary chosen before anyone has started is worse. */}
      <datalist id="known-locations">
        {knownLocations.map((known) => (
          <option key={known.name} value={known.name} />
        ))}
      </datalist>
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("location.hint")}
      </p>

      {dirty && (
        <button
          type="submit"
          disabled={isSaving}
          className="w-full py-2 rounded-xl bg-accent-fill text-on-accent text-sm font-medium hover:bg-accent-fill-hover disabled:opacity-50 transition-colors"
        >
          {isSaving ? t("common.saving") : t("common.save")}
        </button>
      )}
    </form>
  );
}
