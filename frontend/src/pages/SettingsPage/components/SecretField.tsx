import { useState, type ReactNode } from "react";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";

interface SecretFieldProps {
  id: string;
  label: string;
  /** Beside the label, such as a help button. */
  labelAside?: ReactNode;
  placeholder: string;
  /** Names the secret, as in "Show the bot token". See the docstring. */
  showLabel: string;
  hideLabel: string;
  /** What is stored, by its preview, or why the field is fixed. */
  status: string;
  /** The idle label; a save in flight reads "Saving..." whatever this is. */
  saveLabel: string;
  clearLabel: string;
  hasStored: boolean;
  /** Fixed by the deployment: nothing to type, unmask, save or remove. */
  pinned?: boolean;
  /** Shown where the buttons would be, when pinned. */
  pinnedNotice?: ReactNode;
  isSaving: boolean;
  /** Called with the trimmed draft, never with an empty one. */
  onSave: (value: string) => void;
  onClear: () => void;
  /** Below everything else, such as a hint. */
  children?: ReactNode;
}

/**
 * A write only credential field: an API key, a signing secret, a password, a
 * bot token.
 *
 * **It takes no stored value, so it cannot render one.** The server never sends
 * a stored secret back; `status` describes it by its preview instead. The box
 * holds only what was typed here, the reveal shows only that, and the draft is
 * emptied once it is handed to `onSave` so the secret is not left on screen.
 *
 * **An empty box means "leave it alone"**, so Save is withheld while the trimmed
 * draft is empty: sending it would read as "clear", which is the Remove
 * button's job. Remove is the caller's `onClear`, which must send an empty
 * string: `undefined` means "leave it alone".
 *
 * The reveal button's label is the caller's, because it is the part that goes
 * wrong: each needs a label naming **which** secret it reveals, or a screen
 * reader user hears "Show" once per field with nothing to tell them apart.
 */
export default function SecretField({
  id,
  label,
  labelAside,
  placeholder,
  showLabel,
  hideLabel,
  status,
  saveLabel,
  clearLabel,
  hasStored,
  pinned = false,
  pinnedNotice,
  isSaving,
  onSave,
  onClear,
  children,
}: SecretFieldProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [shown, setShown] = useState(false);

  const labelElement = (
    <label
      htmlFor={id}
      className="block text-xs font-medium text-paper-600 dark:text-paper-300"
    >
      {label}
    </label>
  );

  return (
    <div className="space-y-1.5">
      {labelAside ? (
        <div className="flex items-center gap-2">
          {labelElement}
          {labelAside}
        </div>
      ) : (
        labelElement
      )}
      <div className="relative">
        <input
          id={id}
          // `pinned` as well as `shown`: a field can become pinned after its
          // reveal was pressed, by a refetch once the deployment sets it, and
          // the hide button goes with the pin. Without it the typed draft stays
          // in clear with nothing left to hide it.
          type={shown && !pinned ? "text" : "password"}
          autoComplete="off"
          disabled={pinned}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder}
          className="w-full px-3 py-2 pr-10 rounded-xl border border-paper-200 text-sm disabled:bg-paper-50 disabled:text-paper-400 disabled:cursor-not-allowed dark:border-paper-700 dark:disabled:bg-paper-800"
        />
        {/* Not offered when pinned: the box is disabled and empty, so there
            is nothing to unmask. */}
        {!pinned && (
          <button
            type="button"
            onClick={() => setShown((was) => !was)}
            aria-label={shown ? hideLabel : showLabel}
            aria-pressed={shown}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-paper-600 hover:text-paper-800 text-sm leading-none dark:text-paper-400 dark:hover:text-paper-300"
          >
            <span aria-hidden="true">
              <Icon name={shown ? "eyeOff" : "eye"} className="w-4 h-4" />
            </span>
          </button>
        )}
      </div>
      <p className="text-xs text-paper-600 dark:text-paper-400">{status}</p>
      {pinned ? (
        pinnedNotice
      ) : (
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            disabled={isSaving || value.trim() === ""}
            onClick={() => {
              onSave(value.trim());
              setValue("");
            }}
            className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
          >
            {isSaving ? t("common.saving") : saveLabel}
          </button>
          {hasStored && (
            <button
              type="button"
              disabled={isSaving}
              onClick={onClear}
              className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-danger-300"
            >
              {clearLabel}
            </button>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
