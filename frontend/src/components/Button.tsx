import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

/**
 * The one button.
 *
 * It exists because there were about forty of them, each with its own copy of
 * the same dozen utility classes (padding, a background, a radius, a size, a
 * weight, a hover colour, a transition), drifting apart a little at a time.
 * Those class names are deliberately not spelled out here: Tailwind scans
 * comments too, and naming them compiled two dead utilities into the bundle.
 *
 * Three consequences, all of them visible: no two buttons agreed on height, the
 * disabled state was sometimes `opacity-40` and sometimes nothing at all, and
 * none of them had a pressed state, which is most of why the interface felt
 * unfinished rather than because of any single colour.
 *
 * Polish here is not decoration. It is that every button is the same height,
 * responds to being held down, and says the same thing when it cannot be used.
 */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Renders a spinner and blocks the click without changing the width. */
  isLoading?: boolean;
  /** A leading glyph or icon. Hidden from assistive tech: the label carries it. */
  icon?: ReactNode;
  fullWidth?: boolean;
  children?: ReactNode;
  /**
   * The underlying element, for the rare caller that has to move focus itself.
   *
   * A plain prop rather than `forwardRef`, which React 19 made unnecessary: it
   * flows through the rest spread onto the `<button>` like any other attribute.
   * The one caller today is the provider list's reorder buttons, which put
   * focus on a row's other button when the one just pressed becomes disabled at
   * an end, because a disabled element drops focus to the body and silently
   * ends a run of presses.
   */
  ref?: Ref<HTMLButtonElement>;
}

const BASE =
  // `active:scale-[0.97]` is the friendly note, and it is deliberately small.
  // Enough that a press is felt, little enough that nobody calls it bouncy.
  "inline-flex items-center justify-center gap-2 font-medium rounded-lg " +
  "transition-[background-color,border-color,color,box-shadow,transform] duration-150 " +
  "ease-[var(--ease-out-soft)] active:scale-[0.97] " +
  // Disabled reads as unavailable rather than as broken, and stops the press
  // animation, which on a dead control is a lie about what just happened.
  "disabled:opacity-50 disabled:pointer-events-none disabled:active:scale-100 " +
  "select-none";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent-fill text-on-accent shadow-[var(--shadow-soft)] " +
    "hover:bg-accent-fill-hover hover:shadow-[var(--shadow-lift)]",
  secondary:
    "bg-paper-0 text-paper-800 border border-paper-200 shadow-[var(--shadow-soft)] " +
    "hover:border-paper-300 hover:bg-paper-50 " +
    "dark:bg-paper-900 dark:text-paper-100 dark:border-paper-800 " +
    "dark:hover:bg-paper-800 dark:hover:border-paper-700",
  ghost:
    "text-paper-600 hover:text-paper-900 hover:bg-paper-100 " +
    "dark:text-paper-400 dark:hover:text-paper-50 dark:hover:bg-paper-800",
  danger:
    "text-danger-600 hover:bg-danger-100 " +
    "dark:text-danger-300 dark:hover:bg-danger-700/25",
};

// Fixed heights rather than padding alone. Padding plus a variable font size is
// how a row of buttons ends up with three different heights.
const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-sm",
};

export default function Button({
  variant = "primary",
  size = "md",
  isLoading = false,
  icon,
  fullWidth = false,
  className = "",
  disabled,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      // Defaulted rather than required: an un-typed button inside a form
      // submits it, which has caused a stray submit in this codebase before.
      type={type}
      disabled={disabled || isLoading}
      // Announced to a screen reader, which a spinner alone is not.
      aria-busy={isLoading || undefined}
      className={[
        BASE,
        VARIANTS[variant],
        SIZES[size],
        fullWidth ? "w-full" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    >
      {isLoading ? (
        <span
          aria-hidden="true"
          className="w-4 h-4 rounded-full border-2 border-current border-r-transparent animate-spin"
        />
      ) : (
        icon && (
          <span aria-hidden="true" className="shrink-0">
            {icon}
          </span>
        )
      )}
      {children}
    </button>
  );
}
