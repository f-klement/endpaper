import type { ReactNode } from "react";

interface EmptyStateProps {
  glyph: string;
  title: string;
  hint?: ReactNode;
}

/** "Nothing here", reused wherever a list comes back empty. */
export default function EmptyState({ glyph, title, hint }: EmptyStateProps) {
  return (
    <div className="text-center py-16 text-gray-400 dark:text-gray-500">
      <p className="text-4xl mb-3">{glyph}</p>
      <p className="font-medium">{title}</p>
      {hint && <p className="text-sm mt-1">{hint}</p>}
    </div>
  );
}
