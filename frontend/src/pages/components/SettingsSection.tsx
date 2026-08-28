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
 * Shared rather than any one page's, because settings is eight screens now (an
 * index, six detail routes and the palette picker) and drawing a section a
 * second way on one of them would make one setting look like it belongs to a
 * different app than the one beside it.
 *
 * **This is the only titled settings card, since 2026-08-27.** The list used to
 * fold, through `CollapsibleSection`'s `card` variant, and folding was retired
 * when each group became a route: navigation is the state now, and keeping both
 * would give a household two ways to hide the same thing. Two places still
 * write `.card` by hand and neither wants a heading: the settings index, whose
 * entries are links rather than sections, and the About screen, where a card
 * titled "About Endpaper" under a page titled "About Endpaper" would be the
 * same sentence twice.
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
