import type { ReactNode } from "react";

interface SettingsSectionProps {
  title: string;
  glyph: string;
  children: ReactNode;
}

/** A titled card. Dumb: layout only, no state and no data. */
export default function SettingsSection({
  title,
  glyph,
  children,
}: SettingsSectionProps) {
  return (
    <section className="bg-white border border-gray-200 rounded-2xl p-5 space-y-4 dark:bg-gray-900 dark:border-gray-700">
      <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2 dark:text-gray-100">
        <span aria-hidden="true">{glyph}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}
