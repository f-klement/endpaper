import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { IconName } from "../../../components";
import { useTranslation } from "../../../i18n";
import { Page, PageHeader } from "../../components";

interface SettingsSubPageProps {
  icon: IconName;
  title: string;
  children: ReactNode;
}

/**
 * The frame the six settings detail routes share.
 *
 * One place decides the width, the header and the way back, so six screens
 * cannot drift into six slightly different settings pages. That was the
 * failure the split risked: a page becomes a namespace once each section is
 * free to draw its own chrome.
 *
 * The way back is a link rather than browser history, for the reason
 * `AppearancePage` already uses one: a reader who arrived here from a
 * bookmark, or from the burger menu, has no settings index behind them to go
 * back to.
 */
export default function SettingsSubPage({
  icon,
  title,
  children,
}: SettingsSubPageProps) {
  const { t } = useTranslation();

  return (
    <Page width="narrow">
      <PageHeader
        icon={icon}
        title={title}
        actions={
          <Link
            to="/settings"
            className="text-sm font-medium text-accent-700 dark:text-accent-300"
          >
            {t("nav.settings")}
          </Link>
        }
      />
      {/* The cards carry no margin of their own, so the rhythm is stated here.
          `AppearancePage` does the same, and the screens are meant to look like
          one app. */}
      <div className="space-y-5">{children}</div>
    </Page>
  );
}
