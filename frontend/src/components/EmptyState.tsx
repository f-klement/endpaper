import type { ReactNode } from "react";

import Icon, { type IconName } from "./Icon";

interface EmptyStateProps {
  /** Which icon to show. Was an emoji string; see Icon.tsx for why it is not. */
  icon: IconName;
  title: string;
  hint?: ReactNode;
}

/** "Nothing here", reused wherever a list comes back empty. */
export default function EmptyState({ icon, title, hint }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center text-center py-16 px-6">
      {/* Sized and dimmed so the sentence is what the eye lands on. A full
          colour emoji here outweighed the text it was illustrating. */}
      <span className="mb-4 grid place-items-center w-11 h-11 rounded-full bg-paper-200/60 text-paper-600 dark:bg-paper-800 dark:text-paper-400">
        <Icon name={icon} className="w-5 h-5" />
      </span>
      <p className="font-medium text-paper-800 dark:text-paper-100">{title}</p>
      {hint && (
        <p className="text-sm mt-1.5 max-w-xs text-paper-600 dark:text-paper-400">
          {hint}
        </p>
      )}
    </div>
  );
}
