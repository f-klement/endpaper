import { OwnershipStatus } from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";

const OPTIONS: { value: OwnershipStatus; label: MessageKey }[] = [
  { value: OwnershipStatus.owned, label: "ownership.owned" },
  { value: OwnershipStatus.not_owned, label: "ownership.not_owned" },
  { value: OwnershipStatus.unknown, label: "ownership.unknown" },
];

interface OwnershipPickerProps {
  value: OwnershipStatus;
  disabled?: boolean;
  onChange: (ownership: OwnershipStatus) => void;
}

/**
 * Whether a copy is physically here.
 *
 * Sits next to the reading status but is deliberately a separate control,
 * because they answer different questions: one is about the reader, the other
 * about the object. A book can be read and not owned (borrowed) or owned and
 * unread (a gift).
 */
export default function OwnershipPicker({
  value,
  disabled = false,
  onChange,
}: OwnershipPickerProps) {
  const { t } = useTranslation();

  return (
    <div>
      {/* h3, not h2: the section handle that folds this panel away is the
          h2 above it, so a flat h2 here would show a reader's heading list a
          page with no grouping in it at all. */}
      <h3 className="text-sm font-semibold text-paper-900 mb-2 dark:text-paper-100">
        {t("ownership.label")}
      </h3>
      <div
        className="flex gap-2"
        role="group"
        aria-label={t("ownership.label")}
      >
        {OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(option.value)}
            aria-pressed={value === option.value}
            className={`flex-1 py-2 rounded-xl text-xs font-medium border transition-colors disabled:opacity-50 ${
              value === option.value
                ? "bg-accent-50 border-accent-300 text-accent-800 "
                + "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
            }`}
          >
            {t(option.label)}
          </button>
        ))}
      </div>
      <p className="text-xs text-paper-600 mt-1.5 dark:text-paper-400">
        {t("ownership.explain")}
      </p>
    </div>
  );
}
