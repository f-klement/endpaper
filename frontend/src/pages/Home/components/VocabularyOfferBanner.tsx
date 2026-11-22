import { Link } from "react-router-dom";

import { useTranslation } from "../../../i18n";
import type { VocabularyOfferState } from "../hooks";

interface VocabularyOfferBannerProps {
  /** What to say to an admin about a copy, from `useVocabularyOffer`. */
  offer: VocabularyOfferState;
  /** Puts the offer away for the installation, not just this browser. */
  onDismiss: () => void;
  isDismissing: boolean;
}

/**
 * Points an admin at the subject vocabularies' download until a copy is loaded
 * or the offer is dismissed.
 *
 * The app has no first run flow, so this is where the offer is made (owner,
 * 2026-11-20). It sends the reader to the section rather than starting a
 * download here, because a load runs for minutes and its progress is drawn
 * there. The dismissal is stored for the installation (`useVocabularyOffer`),
 * so the button is disabled while it is written rather than hiding the notice
 * before the server has kept the answer. While a load runs it says so and
 * sends the reader to the same section for the progress, rather than offering
 * a download that has already been started.
 *
 * The amber pairing of `ChannelAlertBanner`, measured there: something to see
 * to, not something that has gone wrong.
 */
export default function VocabularyOfferBanner({
  offer,
  onDismiss,
  isDismissing,
}: VocabularyOfferBannerProps) {
  const { t } = useTranslation();

  if (offer == null) return null;
  const loading = offer === "loading";

  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 dark:border-amber-900 dark:bg-amber-950">
      <p className="text-sm text-amber-800 dark:text-amber-200">
        {t(loading ? "library.vocabularyLoading" : "library.vocabularyOffer")}
      </p>
      <div className="flex shrink-0 items-center gap-3">
        <Link
          to="/settings/library"
          className="text-xs font-medium text-amber-900 underline hover:no-underline dark:text-amber-200"
        >
          {t(
            loading
              ? "library.vocabularyLoadingAction"
              : "library.vocabularyOfferAction",
          )}
        </Link>
        <button
          type="button"
          onClick={onDismiss}
          disabled={isDismissing}
          className="text-xs font-medium text-amber-900 hover:underline disabled:opacity-50 dark:text-amber-200"
        >
          {t("library.vocabularyOfferDismiss")}
        </button>
      </div>
    </div>
  );
}
