import { useId } from "react";

import type { LocationOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import { MAX_LOCATION_LENGTH } from "../../lib/lastLocation";

interface LocationFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Shelves already in use, offered as suggestions. */
  locations: LocationOut[];
  label?: string;
  hint?: string;
}

/**
 * Where the copy physically lives, with the shelves already in use suggested.
 *
 * A free-text field with no suggestions turns into six spellings of "living
 * room" inside a week, which is why the API exposes the distinct values at
 * all. `<datalist>` rather than a select: the list is a prompt, not a closed
 * vocabulary, and a new shelf has to be typeable the first time it is used.
 *
 * The id is generated because two of these can be mounted at once, and a
 * duplicated `list=` attribute silently binds both inputs to whichever
 * datalist the browser found first.
 */
export default function LocationField({
  value,
  onChange,
  locations,
  label,
  hint,
}: LocationFieldProps) {
  const { t } = useTranslation();
  const inputId = useId();
  const listId = useId();

  return (
    <div>
      <label
        htmlFor={inputId}
        className="block text-sm font-medium text-paper-700 mb-1 dark:text-paper-200"
      >
        {label ?? t("location.label")}
      </label>
      <input
        id={inputId}
        type="text"
        list={locations.length > 0 ? listId : undefined}
        value={value}
        maxLength={MAX_LOCATION_LENGTH}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t("location.placeholder")}
        className="field"
      />
      {locations.length > 0 && (
        <datalist id={listId}>
          {locations.map((location) => (
            <option key={location.name} value={location.name} />
          ))}
        </datalist>
      )}
      {hint && (
        <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
          {hint}
        </p>
      )}
    </div>
  );
}
