import {
  AccessStatus,
  type AccessRequestOut,
  type BookOut,
} from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface AccessPanelProps {
  book: BookOut;
  currentUserId: number;
  /** What `useBookAccess` returns: the requests the viewer holds or made,
   * oldest first. */
  requests: AccessRequestOut[];
  isBusy: boolean;
  onRequest: () => void;
  onDecide: (requestId: number, granted: boolean) => void;
}

/**
 * Asking for a digital copy, or answering those who ask. Used only by BookDetail.
 *
 * Takes the place of the lend controls on a digital copy, which is
 * not lent: nothing comes back and nothing expires. The holder is the member
 * who added the book when the request was made, and a grant shares no file,
 * so the panel says the copy changes hands outside the app.
 */
export default function AccessPanel({
  book,
  currentUserId,
  requests,
  isBusy,
  onRequest,
  onDecide,
}: AccessPanelProps) {
  const { t } = useTranslation();
  const holder = book.added_by ?? null;

  // Each request names its own holder, fixed when it was made, so a merged
  // entry's adder is not shown requests addressed to somebody else.
  const held = requests.filter((entry) => entry.holder.id === currentUserId);
  const mine = requests.filter(
    (entry) => entry.requested_by.id === currentUserId,
  );
  const isAdder = holder?.id === currentUserId;

  const answering =
    isAdder || held.length > 0 ? (
      held.length === 0 ? (
        <p className="text-sm text-paper-600 dark:text-paper-400">
          {t("access.none")}
        </p>
      ) : (
        <ul className="space-y-2">
          {held.map((entry) => (
            <li
              key={entry.id}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <span className="text-paper-700 dark:text-paper-200">
                {t(
                  entry.status === AccessStatus.granted
                    ? "access.grantedTo"
                    : entry.status === AccessStatus.declined
                      ? "access.declinedFor"
                      : "access.waiting",
                  { name: entry.requested_by.username },
                )}
              </span>
              {entry.status === AccessStatus.pending && (
                <span className="flex gap-2">
                  <button
                    onClick={() => onDecide(entry.id, true)}
                    disabled={isBusy}
                    className="px-3 py-1.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-xs font-semibold"
                  >
                    {t("access.grant")}
                  </button>
                  <button
                    onClick={() => onDecide(entry.id, false)}
                    disabled={isBusy}
                    className="px-3 py-1.5 border border-paper-200 rounded-lg text-xs font-semibold text-paper-700 dark:border-paper-700 dark:text-paper-200"
                  >
                    {t("access.decline")}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )
    ) : null;

  // Oldest first, so the last is the one that stands: a declined request may
  // be followed by a new one.
  const latest = mine.at(-1);
  const status = latest?.status;
  const askedOf = latest?.holder.username ?? holder?.username ?? "";
  const asking =
    holder === null && latest === undefined ? (
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("access.noHolder")}
      </p>
    ) : isAdder && latest === undefined ? null : (
      <>
        {status === AccessStatus.pending && (
          <p className="text-sm text-paper-700 dark:text-paper-200">
            {t("access.pending", { holder: askedOf })}
          </p>
        )}
        {status === AccessStatus.granted && (
          <p className="text-sm text-paper-700 dark:text-paper-200">
            {t("access.granted", { holder: askedOf })}
          </p>
        )}
        {status === AccessStatus.declined && (
          <p className="mb-2 text-sm text-paper-700 dark:text-paper-200">
            {t("access.declined", { holder: askedOf })}
          </p>
        )}
        {/* The server refuses a request to oneself, so the adder is never
            offered one. */}
        {!isAdder &&
          holder !== null &&
          (status === undefined || status === AccessStatus.declined) && (
            <button
              onClick={onRequest}
              disabled={isBusy}
              className="w-full py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-sm font-semibold transition-colors"
            >
              {t("access.request")}
            </button>
          )}
      </>
    );

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-1 dark:text-paper-200">
        {t("access.title")}
      </p>
      <p className="text-xs text-paper-600 mb-3 dark:text-paper-400">
        {t("access.explain")}
      </p>
      {answering}
      {asking}
    </div>
  );
}
