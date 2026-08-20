import type { ReactNode } from "react";

import { Icon, type IconName } from "../../components";

/**
 * The frame every page sits in.
 *
 * It exists because the pages did not agree on anything. Widths ran
 * `max-w-lg`, `max-w-2xl` and `max-w-6xl` with no rule behind which was which;
 * padding was `px-4 pt-5` on some and `px-4 pt-5 pb-4` on others, so half the
 * app ended flush against the bottom of the viewport; vertical rhythm was
 * `space-y-4`, `space-y-6` or nothing at all. None of that is visible as a bug
 * on any single screen, and all of it is visible as a lack of care when you
 * move between them.
 *
 * Two widths, and the choice is meaningful rather than aesthetic: `wide` is for
 * a grid that should use the display, `narrow` is for anything read in a
 * column, where a long measure hurts legibility.
 */

const WIDTHS = {
  narrow: "max-w-2xl",
  wide: "max-w-6xl",
} as const;

interface PageProps {
  width?: keyof typeof WIDTHS;
  children: ReactNode;
}

export function Page({ width = "narrow", children }: PageProps) {
  return (
    <div className={`${WIDTHS[width]} mx-auto px-4 sm:px-6 pt-6 pb-16`}>
      {children}
    </div>
  );
}

interface PageHeaderProps {
  icon: IconName;
  title: string;
  /** A count, a status, anything that qualifies the title rather than acts. */
  badge?: ReactNode;
  /** Buttons. Right-aligned, vertically centred on the title. */
  actions?: ReactNode;
}

/**
 * One page title, laid out one way.
 *
 * The icon sits in a tile rather than inline with the text. Inline, it competes
 * with the heading for the same baseline and every page ends up looking
 * slightly different depending on the glyph's height; in a fixed tile the
 * heading always starts at the same x and the same optical weight.
 */
export function PageHeader({ icon, title, badge, actions }: PageHeaderProps) {
  return (
    <header className="flex items-center gap-3 mb-6 min-h-10">
      <span className="grid place-items-center w-9 h-9 rounded-xl bg-paper-200/60 text-paper-600 dark:bg-paper-800 dark:text-paper-300">
        <Icon name={icon} className="w-[18px] h-[18px]" />
      </span>
      <h1 className="flex items-baseline gap-2.5 text-xl font-semibold text-paper-900 dark:text-paper-100">
        {title}
        {badge}
      </h1>
      {actions && (
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      )}
    </header>
  );
}

/** A count beside a page title. Its own component so every page counts alike. */
export function PageCount({ children }: { children: ReactNode }) {
  return (
    <span className="text-xs font-medium tabular-nums px-2 py-0.5 rounded-full bg-paper-200/70 text-paper-600 dark:bg-paper-800 dark:text-paper-300">
      {children}
    </span>
  );
}
