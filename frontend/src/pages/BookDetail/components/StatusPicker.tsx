import { ReadStatus } from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";

const STATUS_OPTIONS: {
  value: ReadStatus;
  label: MessageKey;
  emoji: string;
}[] = [
  { value: ReadStatus.unread, label: "status.unread", emoji: "📋" },
  { value: ReadStatus.want_to_read, label: "status.want_to_read", emoji: "🔖" },
  { value: ReadStatus.reading, label: "status.reading", emoji: "📖" },
  { value: ReadStatus.read, label: "status.read", emoji: "✅" },
];

interface StatusPickerProps {
  current: ReadStatus;
  onChange: (status: ReadStatus) => void;
}

/**
 * The reader's own progress.
 *
 * Personal to whoever is signed in: a shared shelf does not mean shared
 * reading progress.
 */
export default function StatusPicker({ current, onChange }: StatusPickerProps) {
  const { t } = useTranslation();
  return (
    <div>
      <p className="text-sm font-semibold text-gray-700 mb-2 dark:text-gray-200">
        {t("status.mine")}
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {STATUS_OPTIONS.map((option) => (
          <button
            key={option.value}
            onClick={() => onChange(option.value)}
            aria-pressed={current === option.value}
            className={`py-2 rounded-lg text-sm font-medium border transition-colors ${
              current === option.value
                ? "bg-sky-500 border-sky-500 text-white"
                : "border-gray-200 text-gray-600 hover:border-sky-300 bg-white"
            }`}
          >
            {option.emoji} {t(option.label)}
          </button>
        ))}
      </div>
    </div>
  );
}
