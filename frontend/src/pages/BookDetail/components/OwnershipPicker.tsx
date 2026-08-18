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
      <h2 className="text-sm font-semibold text-gray-900 mb-2 dark:text-gray-100">
        {t("ownership.label")}
      </h2>
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
                ? "bg-sky-50 border-sky-300 text-sky-700"
                : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {t(option.label)}
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-500 mt-1.5 dark:text-gray-400">
        {t("ownership.explain")}
      </p>
    </div>
  );
}
