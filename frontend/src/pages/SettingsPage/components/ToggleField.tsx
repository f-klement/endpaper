interface ToggleFieldProps {
  label: string;
  hint?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

/**
 * A labelled switch.
 *
 * Built on a real `<input type="checkbox">` rather than a styled `<div>`, so
 * it is reachable by keyboard and announced correctly, and so the label's
 * `htmlFor` association works without ARIA plumbing. The visible switch is the
 * peer sibling, driven entirely by CSS.
 */
export default function ToggleField({
  label,
  hint,
  checked,
  disabled = false,
  onChange,
}: ToggleFieldProps) {
  return (
    <div>
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          className="peer sr-only"
        />
        <span
          aria-hidden="true"
          className="mt-0.5 shrink-0 w-9 h-5 rounded-full bg-paper-300 dark:bg-paper-700 transition-colors relative peer-checked:bg-accent-600 peer-disabled:opacity-50 peer-focus-visible:ring-2 peer-focus-visible:ring-accent-400 peer-focus-visible:ring-offset-2 after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-4 after:h-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"
        />
        <span className="text-sm text-paper-700 peer-disabled:opacity-50 dark:text-paper-200">
          {label}
        </span>
      </label>
      {hint && (
        <p className="text-xs text-paper-500 mt-1.5 ml-12 dark:text-paper-400">
          {hint}
        </p>
      )}
    </div>
  );
}
