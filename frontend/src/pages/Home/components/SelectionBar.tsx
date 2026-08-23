import { useState } from "react";

import {
  BulkAction,
  OwnershipStatus,
  ReadStatus,
  type BulkResult,
  type CollectionOut,
  type TagOut,
} from "../../../api/generated/model";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";
import { Icon } from "../../../components";

interface SelectionBarProps {
  selectedCount: number;
  isApplying: boolean;
  result: BulkResult | null;
  error: unknown;
  tags: TagOut[];
  collections: CollectionOut[];
  onSelectAll: () => void;
  onClear: () => void;
  onApply: (ownership: OwnershipStatus) => void;
  onRun: (action: BulkAction, value?: string | number) => void;
  onDone: () => void;
}

/**
 * The bulk-action bar, shown while selecting.
 *
 * Sticky at the bottom rather than the top: on a phone the grid is scrolled
 * with a thumb, and the action belongs where the thumb already is.
 */
export default function SelectionBar({
  selectedCount,
  isApplying,
  result,
  error,
  tags,
  collections,
  onSelectAll,
  onClear,
  onApply,
  onRun,
  onDone,
}: SelectionBarProps) {
  const { t } = useTranslation();
  // The extra verbs are behind a disclosure. Marking a shelf is the common
  // case and deserves the primary buttons; deleting forty books is not, and
  // should not sit one mis-tap away from them.
  const [showMore, setShowMore] = useState(false);

  return (
    <div className="sticky bottom-0 z-40 -mx-4 px-4 py-3 bg-paper-0/95 backdrop-blur-sm border-t border-paper-200 dark:bg-paper-900/95 dark:border-paper-700">
      <div className="max-w-6xl mx-auto space-y-2">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-paper-700 dark:text-paper-200">
            {t("common.selectedCount", { count: selectedCount })}
          </span>
          <div className="flex gap-3 text-xs">
            <button
              type="button"
              onClick={onSelectAll}
              className="text-accent-700 hover:underline dark:text-accent-400"
            >
              {t("common.selectAll")}
            </button>
            <button
              type="button"
              onClick={onClear}
              disabled={selectedCount === 0}
              className="text-paper-600 hover:underline disabled:opacity-40 dark:text-paper-400"
            >
              {t("common.clearSelection")}
            </button>
            <button
              type="button"
              onClick={onDone}
              className="text-paper-600 hover:underline dark:text-paper-400"
            >
              {t("common.done")}
            </button>
          </div>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            disabled={selectedCount === 0 || isApplying}
            onClick={() => onApply(OwnershipStatus.owned)}
            className="flex-1 py-2.5 rounded-xl bg-accent-fill text-on-accent text-sm font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
          >
            {isApplying ? t("common.saving") : t("ownership.confirmSelected")}
          </button>
          <button
            type="button"
            disabled={selectedCount === 0 || isApplying}
            onClick={() => onApply(OwnershipStatus.not_owned)}
            className="px-4 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
          >
            {t("ownership.markNotOwned")}
          </button>
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setShowMore((open) => !open)}
            aria-expanded={showMore}
            className="inline-flex items-center gap-1.5 text-xs text-paper-600 hover:text-paper-800 dark:text-paper-400 dark:hover:text-paper-100"
          >
            {t("bulk.more")}
            <Icon
              name="chevron"
              className={`w-3 h-3 opacity-70 transition-transform duration-150 ${
                showMore ? "-rotate-90" : "rotate-90"
              }`}
            />
          </button>
        </div>

        {showMore && (
          <div className="space-y-2 border-t border-paper-100 pt-2 dark:border-paper-800">
            <div className="flex flex-wrap gap-2">
              <select
                aria-label={t("bulk.setStatus")}
                defaultValue=""
                disabled={selectedCount === 0 || isApplying}
                onChange={(event) => {
                  if (event.target.value) {
                    onRun(BulkAction.set_status, event.target.value);
                    event.target.value = "";
                  }
                }}
                className="flex-1 min-w-32 px-2 py-1.5 rounded-lg border border-paper-200 text-xs bg-paper-0 disabled:opacity-40 dark:border-paper-700 dark:bg-paper-900"
              >
                <option value="">{t("bulk.setStatus")}</option>
                {Object.values(ReadStatus).map((value) => (
                  <option key={value} value={value}>
                    {t(`status.${value}`)}
                  </option>
                ))}
              </select>

              <select
                aria-label={t("bulk.addTag")}
                defaultValue=""
                disabled={selectedCount === 0 || isApplying}
                onChange={(event) => {
                  if (event.target.value) {
                    onRun(BulkAction.add_tag, Number(event.target.value));
                    event.target.value = "";
                  }
                }}
                className="flex-1 min-w-32 px-2 py-1.5 rounded-lg border border-paper-200 text-xs bg-paper-0 disabled:opacity-40 dark:border-paper-700 dark:bg-paper-900"
              >
                <option value="">{t("bulk.addTag")}</option>
                {tags.map((tag) => (
                  <option key={tag.id} value={tag.id}>
                    {tag.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Only once a household has made one. An empty picker offering
                only "take these out of every collection" is a control for a
                state that cannot exist yet. */}
            {collections.length > 0 && (
              <select
                aria-label={t("bulk.setCollection")}
                defaultValue=""
                disabled={selectedCount === 0 || isApplying}
                onChange={(event) => {
                  if (event.target.value) {
                    // The empty string is the placeholder, so clearing needs a
                    // value of its own: the API reads null as "unfile these".
                    onRun(
                      BulkAction.set_collection,
                      event.target.value === "none"
                        ? ""
                        : Number(event.target.value),
                    );
                    event.target.value = "";
                  }
                }}
                className="w-full px-2 py-1.5 rounded-lg border border-paper-200 text-xs bg-paper-0 disabled:opacity-40 dark:border-paper-700 dark:bg-paper-900"
              >
                <option value="">{t("bulk.setCollection")}</option>
                {collections.map((collection) => (
                  <option key={collection.id} value={collection.id}>
                    {collection.name}
                  </option>
                ))}
                <option value="none">{t("bulk.clearCollection")}</option>
              </select>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                disabled={selectedCount === 0 || isApplying}
                onClick={() => {
                  const place = prompt(t("bulk.locationPrompt"));
                  // null is cancel; an empty string is a deliberate clear, and
                  // the two must not be conflated.
                  if (place !== null) onRun(BulkAction.set_location, place);
                }}
                className="flex-1 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-40 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
              >
                {t("bulk.setLocation")}
              </button>
              <button
                type="button"
                disabled={selectedCount === 0 || isApplying}
                onClick={() => {
                  if (
                    confirm(t("bulk.deleteConfirm", { count: selectedCount }))
                  ) {
                    onRun(BulkAction.delete);
                  }
                }}
                className="flex-1 py-1.5 rounded-lg border border-danger-300 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 dark:border-danger-700 dark:text-danger-300"
              >
                {t("bulk.delete")}
              </button>
            </div>
          </div>
        )}

        {error != null && (
          <p role="alert" className="text-xs text-danger-600 dark:text-danger-300">
            {errorText(error, t("common.somethingWentWrong"), t)}
          </p>
        )}

        {result && (
          <p role="status" className="text-xs text-paper-600 dark:text-paper-400">
            {t("ownership.bulkResult", {
              updated: result.updated,
              unchanged: result.unchanged,
              skipped: result.skipped,
            })}
          </p>
        )}
      </div>
    </div>
  );
}
