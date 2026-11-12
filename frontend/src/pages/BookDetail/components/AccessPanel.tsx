import {
  AccessStatus,
  type AccessRequestOut,
  type BookOut,
  type UserOut,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";

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

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-1 dark:text-paper-200">
        {t("access.title")}
      </p>
      <p className="text-xs text-paper-600 mb-3 dark:text-paper-400">
        {t("access.explain")}
      </p>
      <Answering
        held={held}
        isAdder={isAdder}
        isBusy={isBusy}
        onDecide={onDecide}
      />
      <Asking
        holder={holder}
        // Oldest first, so the last is the one that stands: a declined
        // request may be followed by a new one.
        latest={mine.at(-1)}
        isAdder={isAdder}
        isBusy={isBusy}
        onRequest={onRequest}
      />
    </div>
  );
}

/** What the holder reads beside each request addressed to them. */
const ANSWER_LINE: Record<AccessStatus, MessageKey> = {
  [AccessStatus.pending]: "access.waiting",
  [AccessStatus.granted]: "access.grantedTo",
  [AccessStatus.declined]: "access.declinedFor",
};

/** What the requester reads about their latest request. Declined leaves room
 * under it for the button that asks again. */
const ASK_LINE: Record<AccessStatus, { key: MessageKey; className: string }> = {
  [AccessStatus.pending]: {
    key: "access.pending",
    className: "text-sm text-paper-700 dark:text-paper-200",
  },
  [AccessStatus.granted]: {
    key: "access.granted",
    className: "text-sm text-paper-700 dark:text-paper-200",
  },
  [AccessStatus.declined]: {
    key: "access.declined",
    className: "mb-2 text-sm text-paper-700 dark:text-paper-200",
  },
};

/** The holder's side: the requests addressed to them, each answerable while
 * it waits. Shown to the adder even when nobody has asked yet. */
function Answering({
  held,
  isAdder,
  isBusy,
  onDecide,
}: {
  held: AccessRequestOut[];
  isAdder: boolean;
  isBusy: boolean;
  onDecide: AccessPanelProps["onDecide"];
}) {
  const { t } = useTranslation();
  if (!isAdder && held.length === 0) return null;
  if (held.length === 0)
    return (
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("access.none")}
      </p>
    );
  return (
    <ul className="space-y-2">
      {held.map((entry) => (
        <li
          key={entry.id}
          className="flex items-center justify-between gap-2 text-sm"
        >
          <span className="text-paper-700 dark:text-paper-200">
            {t(ANSWER_LINE[entry.status], {
              name: entry.requested_by.username,
            })}
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
  );
}

/** The requester's side: where their latest request stands, and the button
 * that asks, while asking is open to them. */
function Asking({
  holder,
  latest,
  isAdder,
  isBusy,
  onRequest,
}: {
  holder: UserOut | null;
  latest: AccessRequestOut | undefined;
  isAdder: boolean;
  isBusy: boolean;
  onRequest: () => void;
}) {
  const { t } = useTranslation();
  if (holder === null && latest === undefined)
    return (
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("access.noHolder")}
      </p>
    );
  if (isAdder && latest === undefined) return null;
  const line = latest && {
    ...ASK_LINE[latest.status],
    holder: latest.holder.username,
  };
  return (
    <>
      {line && (
        <p className={line.className}>{t(line.key, { holder: line.holder })}</p>
      )}
      {mayAsk(isAdder, holder, latest) && (
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
}

/** Whether the request button shows: nothing asked yet, or the last ask was
 * refused. The server refuses a request to oneself, so the adder is never
 * offered one, and nor is anybody when no holder is known. */
function mayAsk(
  isAdder: boolean,
  holder: UserOut | null,
  latest: AccessRequestOut | undefined,
): boolean {
  return (
    !isAdder &&
    holder !== null &&
    (latest === undefined || latest.status === AccessStatus.declined)
  );
}
