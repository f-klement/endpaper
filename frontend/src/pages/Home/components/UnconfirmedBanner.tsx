import { useTranslation } from "../../../i18n";

interface UnconfirmedBannerProps {
  count: number;
  onReview: () => void;
}

/**
 * A nudge that some books have never been confirmed as being on the shelf.
 *
 * Shown rather than left for someone to notice, because the books it is about
 * arrive from an import in bulk and otherwise sit unverified forever. It
 * disappears on its own once the count reaches zero, so there is nothing to
 * dismiss.
 */
export default function UnconfirmedBanner({
  count,
  onReview,
}: UnconfirmedBannerProps) {
  const { t } = useTranslation();

  if (count === 0) return null;

  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 dark:border-amber-900 dark:bg-amber-950">
      <p className="text-sm text-amber-800 dark:text-amber-200">
        {t("ownership.unconfirmedBanner", { count })}
      </p>
      <button
        type="button"
        onClick={onReview}
        className="shrink-0 text-xs font-medium text-amber-900 underline hover:no-underline"
      >
        {t("ownership.reviewThem")}
      </button>
    </div>
  );
}
