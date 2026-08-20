import type { ReactNode } from "react";

import { Icon, type IconName } from "../../../components";

interface SettingsSectionProps {
  title: string;
  icon: IconName;
  children: ReactNode;
}

/** A titled card. Dumb: layout only, no state and no data. */
export default function SettingsSection({
  title,
  icon,
  children,
}: SettingsSectionProps) {
  return (
    <section className="card p-5 space-y-4">
      <h2 className="flex items-center gap-2.5 text-sm font-semibold text-paper-900 dark:text-paper-100">
        <span className="grid place-items-center w-7 h-7 rounded-lg bg-paper-100 text-paper-600 dark:bg-paper-800 dark:text-paper-400">
          <Icon name={icon} className="w-4 h-4" />
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}
