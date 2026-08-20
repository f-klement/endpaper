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
        {/* The one control that draws its own ring, because the shared
            `:focus-visible` lands on the `sr-only` input and would be invisible.
            It restates the shared rule in full rather than borrowing from it:
            the ring sits on this `<span>` while the element actually matching
            `:focus-visible` is the input, so `index.css` cannot reach it, and
            `--tw-ring-offset-color` is registered with `inherits: false` and an
            initial value of white. Leave the offset colour out and a dark page
            gets a 2px white halo between the track and the ring. */}
        <span
          aria-hidden="true"
          className="mt-0.5 shrink-0 w-9 h-5 rounded-full bg-paper-300 dark:bg-paper-700 transition-colors relative peer-checked:bg-accent-fill peer-disabled:opacity-50 peer-focus-visible:ring-2 peer-focus-visible:ring-accent-500 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-paper-50 dark:peer-focus-visible:ring-offset-paper-950 after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-4 after:h-4 after:rounded-full after:bg-paper-0 after:transition-transform peer-checked:after:translate-x-4"
        />
        <span className="text-sm text-paper-700 peer-disabled:opacity-50 dark:text-paper-200">
          {label}
        </span>
      </label>
      {hint && (
        <p className="text-xs text-paper-600 mt-1.5 ml-12 dark:text-paper-400">
          {hint}
        </p>
      )}
    </div>
  );
}
