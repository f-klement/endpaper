import { ReadStatus } from "../../../api/generated/model";
import { Icon, type IconName } from "../../../components";
import { useTranslation, type MessageKey } from "../../../i18n";

const STATUS_OPTIONS: {
  value: ReadStatus;
  label: MessageKey;
  icon: IconName;
}[] = [
  { value: ReadStatus.unread, label: "status.unread", icon: "list" },
  { value: ReadStatus.want_to_read, label: "status.want_to_read", icon: "bookmark" },
  { value: ReadStatus.reading, label: "status.reading", icon: "book" },
  { value: ReadStatus.read, label: "status.read", icon: "check" },
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
      <p className="text-sm font-semibold text-paper-700 mb-2 dark:text-paper-200">
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
                ? "bg-accent-fill border-accent-fill text-on-accent"
                : "border-paper-200 text-paper-600 hover:border-accent-300 bg-paper-0 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 "
                + "dark:hover:border-accent-700"
            }`}
          >
            <Icon name={option.icon} className="w-4 h-4" /> {t(option.label)}
          </button>
        ))}
      </div>
    </div>
  );
}
