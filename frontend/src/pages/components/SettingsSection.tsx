import type { ReactNode } from "react";

import { SectionIcon, type IconName } from "../../components";

interface SettingsSectionProps {
  title: string;
  icon: IconName;
  children: ReactNode;
}

/**
 * A titled card that does not fold. Dumb: layout only, no state and no data.
 *
 * Shared rather than Settings' own, because `/settings/appearance` is a second
 * screen of the same settings and drawing its sections a second way would make
 * one setting look like it belongs to a different app than the one beside it.
 *
 * The settings page itself now folds, so it draws the same card through
 * `CollapsibleSection variant="card"` instead. That is the same chrome, not a
 * second one: both use the `card` class and `SectionIcon`, which is why the
 * badge lives in its own component. Appearance is arrived at deliberately, from
 * a link that says what is set, so nothing there folds and this stays.
 */
export default function SettingsSection({
  title,
  icon,
  children,
}: SettingsSectionProps) {
  return (
    <section className="card p-5 space-y-4">
      <h2 className="flex items-center gap-2.5 text-sm font-semibold text-paper-900 dark:text-paper-100">
        <SectionIcon name={icon} />
        {title}
      </h2>
      {children}
    </section>
  );
}
