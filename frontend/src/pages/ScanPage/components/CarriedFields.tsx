import type {
  BookCondition,
  CollectionOut,
  OwnershipStatus,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { TEXT_CEILINGS } from "../../../lib/bookBounds";
import {
  CONDITION_LABELS,
  CONDITION_ORDER,
  OWNERSHIP_LABELS,
} from "../../types";
import type { PendingBook } from "../types";

/** In the label table's order, which puts owned, the default, first. */
const OWNERSHIPS: { value: OwnershipStatus; label: MessageKey }[] = (
  Object.keys(OWNERSHIP_LABELS) as OwnershipStatus[]
).map((value) => ({ value, label: OWNERSHIP_LABELS[value] }));

const CONDITIONS: { value: BookCondition; label: MessageKey }[] =
  CONDITION_ORDER.map((value) => ({ value, label: CONDITION_LABELS[value] }));

interface CarriedFieldsProps {
  pending: PendingBook;
  onChange: (patch: Partial<PendingBook>) => void;
  collections: CollectionOut[];
  /** From `useScanFlow`: the book is private because the last one was. */
  privacyCarried: boolean;
}

/**
 * The fields the add form carries from the last book, each editable and each
 * clearable.
 *
 * **Shown, never applied out of sight**, which is the condition the owner
 * carried them on: a collection or a shop nobody can see on the form is a book
 * filed where nobody chose. The shelf, the format and the tags are drawn by the
 * confirm card, which drew them before they carried; these are the rest.
 *
 * **The privacy notice is a sentence and a button, not only the tick.** A
 * private book is hidden from every other member, and a carried tick is the
 * one carried value whose mistake nobody else can see to point out.
 */
export default function CarriedFields({
  pending,
  onChange,
  collections,
  privacyCarried,
}: CarriedFieldsProps) {
  const { t } = useTranslation();
  const { collectionId, condition, ownership, purchaseSource, purchasedAt } =
    pending;

  return (
    <section
      aria-label={t("carry.heading")}
      className="mb-4 bg-paper-0 rounded-2xl border border-paper-100 p-5 space-y-4 dark:bg-paper-900 dark:border-paper-800"
    >
      {privacyCarried && (
        <div
          role="status"
          className="text-sm text-amber-800 bg-amber-50 rounded-lg px-3 py-2 space-y-1 dark:text-amber-200 dark:bg-amber-950/40"
        >
          <p>{t("carry.privateNotice")}</p>
          <button
            type="button"
            onClick={() => onChange({ isPrivate: false })}
            className="font-medium underline hover:no-underline"
          >
            {t("carry.makePublic")}
          </button>
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold text-paper-800 dark:text-paper-100">
          {t("carry.heading")}
        </h2>
        <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
          {t("carry.hint")}
        </p>
      </div>

      <label className="block text-sm">
        <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
          {t("collections.label")}
        </span>
        <select
          value={collectionId ?? ""}
          onChange={(event) =>
            onChange({
              collectionId:
                event.target.value === "" ? null : Number(event.target.value),
            })
          }
          className="field"
        >
          <option value="">{t("collections.none")}</option>
          {collections.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
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
          onChange={(event) =>
            onChange({ condition: event.target.value as BookCondition | "" })
          }
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
          {t("ownership.label")}
        </span>
        {/* No blank option: the column holds one of three, and owned is what
            an add means when nobody says otherwise. Choosing it is the clear. */}
        <select
          value={ownership}
          onChange={(event) =>
            onChange({ ownership: event.target.value as OwnershipStatus })
          }
          className="field"
        >
          {OWNERSHIPS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.label)}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-sm">
        <span className="block font-medium text-paper-700 mb-1 dark:text-paper-200">
          {t("copy.purchaseSource")}
        </span>
        <input
          type="text"
          value={purchaseSource}
          maxLength={TEXT_CEILINGS.purchase_source}
          onChange={(event) => onChange({ purchaseSource: event.target.value })}
          placeholder={t("copy.purchaseSourcePlaceholder")}
          className="field"
        />
      </label>

      <div className="text-sm">
        <label
          htmlFor="carried-purchased-at"
          className="block font-medium text-paper-700 mb-1 dark:text-paper-200"
        >
          {t("copy.purchasedAt")}
        </label>
        <div className="flex gap-2">
          {/* The input's own value, `YYYY-MM-DD`, kept as that string: a
              calendar date parsed as an instant is the day before west of
              Greenwich. */}
          <input
            id="carried-purchased-at"
            type="date"
            value={purchasedAt}
            onChange={(event) => onChange({ purchasedAt: event.target.value })}
            className="field flex-1"
          />
          {/* A date input's own clear control is not offered by every
              browser, and a carried date has to be clearable everywhere. */}
          {purchasedAt !== "" && (
            <button
              type="button"
              onClick={() => onChange({ purchasedAt: "" })}
              className="text-sm font-medium text-paper-700 underline hover:no-underline dark:text-paper-200"
            >
              {t("carry.clearDate")}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
