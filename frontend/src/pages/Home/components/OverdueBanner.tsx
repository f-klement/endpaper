import { Link } from "react-router-dom";

import { useTranslation } from "../../../i18n";

interface OverdueBannerProps {
  count: number;
}

/**
 * The in app overdue reminder (#86).
 *
 * **The one reminder channel that needs nothing from the household.** The other
 * three each want something obtained first: an HTTPS receiver, an SMTP account,
 * a bot token. Before this, a household with none of them was told nothing at
 * all, because an overdue loan appeared only on the loans page, which somebody
 * has to navigate to, and in a book's own loan panel, which needs the book open.
 *
 * Same shape as `UnconfirmedBanner` beside it, deliberately: a household learns
 * one banner and reads both. It disappears on its own when the books come back,
 * so there is nothing to dismiss.
 *
 * The danger pairing rather than the amber one, because "overdue" already means
 * that colour on the loans page and a second colour for one fact is a second
 * fact. Measured: danger-700 on danger-100 is 6.69:1, and danger-100 on
 * danger-700 in dark is the same pair reversed, so also 6.69:1.
 *
 * **The dark border is danger-300, not danger-700.** It was the fill's own
 * token, which is 1.00:1 against it: an edge that is not there. danger-300 on
 * danger-700 measures 4.24:1, and it is the same token the light mode border
 * already uses, so the box has one border colour rather than two. The loans
 * page's overdue banner carried the identical defect and is fixed with it.
 *
 * **A count and no titles.** What the reader does next is open the overdue
 * page, which renders them through the Shelf and knows how to page. The server
 * sends a number for the same reason.
 *
 * **The link points at the overdue page, not the loans list (#102).** The
 * banner counts through `overdue_for_viewer` and the loans list does not, so
 * this used to hand a member a screen with more rows on it than the sentence
 * they had just read. The two now agree because they ask the same endpoint's
 * rule.
 */
export default function OverdueBanner({ count }: OverdueBannerProps) {
  const { t } = useTranslation();

  if (count === 0) return null;

  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-danger-300 bg-danger-100 px-3 py-2.5 dark:border-danger-300 dark:bg-danger-700">
      <p className="text-sm text-danger-700 dark:text-danger-100">
        {t("library.overdueBanner", { count })}
      </p>
      {/* A link, not a button: the overdue page is a route, and the reader
          expects the browser's back button to work afterwards. */}
      <Link
        to="/loans/overdue"
        className="shrink-0 text-xs font-medium text-danger-700 underline hover:no-underline dark:text-danger-100"
      >
        {t("library.overdueBannerAction")}
      </Link>
    </div>
  );
}
