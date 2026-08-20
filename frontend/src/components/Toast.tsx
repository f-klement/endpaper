import { useEffect } from "react";

import { useTranslation } from "../i18n";
import Icon from "./Icon";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastProps {
  message: string;
  action?: ToastAction;
  onDismiss: () => void;
  /** Milliseconds before it dismisses itself. */
  timeout?: number;
}

/** Long enough to read a sentence and reach for the button, short enough not
 *  to sit over the page. */
const DEFAULT_TIMEOUT = 8000;

/**
 * A transient message with one optional action.
 *
 * `role="status"` and `aria-live="polite"`, not `alert`: this reports
 * something that already happened successfully. An assertive live region
 * interrupts a screen reader mid-sentence, which is right for an error and
 * rude for "moved to the trash".
 *
 * The timer is cleared on unmount, so dismissing by hand cannot leave a
 * pending callback that fires against a gone component.
 */
export default function Toast({
  message,
  action,
  onDismiss,
  timeout = DEFAULT_TIMEOUT,
}: ToastProps) {
  const { t } = useTranslation();

  useEffect(() => {
    const timer = setTimeout(onDismiss, timeout);
    return () => clearTimeout(timer);
  }, [onDismiss, timeout]);

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 rounded-xl border border-paper-200 bg-paper-0 px-4 py-3 shadow-lg dark:border-paper-700 dark:bg-paper-900"
    >
      <span className="min-w-0 flex-1 text-sm text-paper-800 dark:text-paper-100">
        {message}
      </span>
      {action && (
        <button
          type="button"
          onClick={() => {
            action.onClick();
            onDismiss();
          }}
          className="shrink-0 text-sm font-semibold text-accent-700 hover:text-accent-800 dark:text-accent-300 dark:hover:text-accent-200"
        >
          {action.label}
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label={t("common.close")}
        className="shrink-0 text-paper-600 hover:text-paper-800 dark:text-paper-400 dark:hover:text-paper-200"
      >
        <Icon name="close" className="w-4 h-4" />
      </button>
    </div>
  );
}
