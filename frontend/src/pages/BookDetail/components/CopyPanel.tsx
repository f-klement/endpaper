import { useEffect, useState, type FormEvent } from "react";

import {
  BookCondition,
  BookFormat,
  type BookDetailsUpdate,
  type BookOut,
} from "../../../api/generated/model";
import { Button } from "../../../components";
import { useTranslation, type MessageKey } from "../../../i18n";
import { formatMinor, parseMinor } from "../../../lib/money";
import {
  CONDITION_LABELS,
  CONDITION_ORDER,
  FORMAT_LABELS,
  FORMAT_ORDER,
} from "../../types";

interface CopyPanelProps {
  book: BookOut;
  isSaving: boolean;
  onSave: (fields: BookDetailsUpdate) => void;
}

// Built from the shared tables in `pages/types.ts` rather than restated, so the
// card's fold out and the table view cannot end up calling a format something
// this editor does not.
const FORMATS: { value: BookFormat; label: MessageKey }[] = FORMAT_ORDER.map(
  (value) => ({ value, label: FORMAT_LABELS[value] }),
);

const CONDITIONS: { value: BookCondition; label: MessageKey }[] =
  CONDITION_ORDER.map((value) => ({ value, label: CONDITION_LABELS[value] }));

/**
 * Facts about the object on the shelf, rather than about the work.
 *
 * Behind a disclosure on purpose, and that disclosure is now the "Your copies"
 * section rather than a <details> of its own. Nothing here is ever filled in by
 * a lookup and most books will never have any of it, so putting six more inputs
 * in front of everybody to serve the few who care would make the ordinary page
 * worse. Goodreads is criticised in review after review for having nowhere to
 * record condition; this is that, plus what the copy cost.
 */
export default function CopyPanel({ book, isSaving, onSave }: CopyPanelProps) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<string>(book.format ?? "");
  const [condition, setCondition] = useState<string>(book.condition ?? "");
  const [price, setPrice] = useState(formatMinor(book.purchase_price_minor));
  const [currency, setCurrency] = useState(book.purchase_currency ?? "");
  const [purchasedAt, setPurchasedAt] = useState(book.purchased_at ?? "");
  const [source, setSource] = useState(book.purchase_source ?? "");
  const [priceError, setPriceError] = useState(false);

  // Re-seed when the book changes underneath, the same reason ShelfPanel does.
  useEffect(() => {
    setFormat(book.format ?? "");
    setCondition(book.condition ?? "");
    setPrice(formatMinor(book.purchase_price_minor));
    setCurrency(book.purchase_currency ?? "");
    setPurchasedAt(book.purchased_at ?? "");
    setSource(book.purchase_source ?? "");
    setPriceError(false);
  }, [
    book.format,
    book.condition,
    book.purchase_price_minor,
    book.purchase_currency,
    book.purchased_at,
    book.purchase_source,
  ]);

  const dirty =
    format !== (book.format ?? "") ||
    condition !== (book.condition ?? "") ||
    price !== formatMinor(book.purchase_price_minor) ||
    currency !== (book.purchase_currency ?? "") ||
    purchasedAt !== (book.purchased_at ?? "") ||
    source !== (book.purchase_source ?? "");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const minor = parseMinor(price);
    if (minor === undefined) {
      // Refused rather than stored as zero, which is what a silently dropped
      // typo would become.
      setPriceError(true);
      return;
    }
    setPriceError(false);
    onSave({
      // Empty means "clear". The API distinguishes absent from null and an
      // empty string would be neither.
      format: (format || null) as BookFormat | null,
      condition: (condition || null) as BookCondition | null,
      purchase_price_minor: minor,
      purchase_currency: currency.trim().toUpperCase() || null,
      purchased_at: purchasedAt || null,
      purchase_source: source.trim() || null,
    });
  }

  // No <details> of its own any more. It had one, opened on a copy with
  // something already recorded, and the collapsible section around this panel
  // now does that job: two disclosures nested inside each other put these
  // fields two clicks deep and swallowed the inner one's signal entirely.
  //
  // The label is an h3 and not the bold <p> six other panels use, because it
  // was a <summary> before that removal: focusable and announced. A <p> is
  // announced as nothing, so dropping the wrapper would have traded a
  // redundant disclosure for a lost landmark, and "Your copies" would have
  // been the one section holding no heading at all.
  return (
    <div>
      <h3 className="text-sm font-medium text-paper-700 dark:text-paper-200">
        {t("copy.title")}
      </h3>
      <p className="text-xs text-paper-600 mt-1 mb-3 dark:text-paper-400">
        {t("copy.hint")}
      </p>

      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
              {t("copy.format")}
            </span>
            <select
              value={format}
              onChange={(event) => setFormat(event.target.value)}
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

          <label className="block text-sm">
            <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
              {t("copy.condition")}
            </span>
            <select
              value={condition}
              onChange={(event) => setCondition(event.target.value)}
              className="field"
            >
              <option value="">{t("copy.condition.unset")}</option>
              {CONDITIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.label)}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
              {t("copy.price")}
            </span>
            <input
              type="text"
              inputMode="decimal"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              placeholder="12.99"
              aria-invalid={priceError}
              className="field"
            />
          </label>

          <label className="block text-sm">
            <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
              {t("copy.currency")}
            </span>
            <input
              type="text"
              value={currency}
              maxLength={3}
              onChange={(event) => setCurrency(event.target.value)}
              placeholder="EUR"
              className="field uppercase"
            />
          </label>

          <label className="block text-sm">
            <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
              {t("copy.purchasedAt")}
            </span>
            <input
              type="date"
              value={purchasedAt}
              onChange={(event) => setPurchasedAt(event.target.value)}
              className="field"
            />
          </label>

          <label className="block text-sm">
            <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
              {t("copy.purchaseSource")}
            </span>
            <input
              type="text"
              value={source}
              maxLength={120}
              onChange={(event) => setSource(event.target.value)}
              placeholder={t("copy.purchaseSourcePlaceholder")}
              className="field"
            />
          </label>
        </div>

        {priceError && (
          <p role="alert" className="text-xs text-danger-600 dark:text-danger-300">
            {t("copy.priceInvalid")}
          </p>
        )}

        {/* Named rather than a bare "Save": three panels on this page each
            have one, and "Save" alone says nothing about which. */}
        <Button
          type="submit"
          size="sm"
          disabled={!dirty}
          isLoading={isSaving}
          aria-label={t("copy.save")}
        >
          {t("common.save")}
        </Button>
      </form>
    </div>
  );
}
