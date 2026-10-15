import { Link } from "react-router-dom";

import { Button } from "../../components";
import { useTranslation } from "../../i18n";
import { plainName } from "../../lib/fileName";
import type { FolderSweep } from "../hooks";

interface FolderSweepNoticeProps {
  swept: readonly FolderSweep[] | null;
  failed: boolean;
  isMarking: boolean;
  /** Mark what one root's sweep did not find as missing. */
  onMarkMissing: (root: string) => void;
}

/**
 * What re-picking a folder found: how many saved files were found again, and
 * each one that was not, linked to its book, with one press to mark them.
 *
 * **Nothing is marked missing until that press.** A folder name is all a
 * root is, so a file not found may be another member's file in their own
 * folder of the same name, and only a person looking at the list can tell.
 *
 * **Every path is rendered through `plainName`**, the rule
 * `lib/digitalReference.ts` states for a stored path on screen.
 *
 * Says nothing for a pick whose folder had nothing saved under it, which is
 * every first pick.
 */
export default function FolderSweepNotice({
  swept,
  failed,
  isMarking,
  onMarkMissing,
}: FolderSweepNoticeProps) {
  const { t } = useTranslation();

  return (
    <>
      {failed && (
        <p
          role="status"
          className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mt-2 dark:text-amber-300 dark:bg-amber-950/40"
        >
          {t("files.sweepFailed")}
        </p>
      )}
      {swept && swept.length > 0 && (
        <div role="status" className="mt-2 space-y-2">
          {swept.map((one) => (
            <div
              key={one.root}
              className="text-xs text-paper-700 bg-paper-50 rounded-lg px-3 py-2 space-y-1 dark:text-paper-200 dark:bg-paper-900"
            >
              {one.kind === "different" ? (
                <p>
                  {t("files.sweptDifferent", {
                    root: plainName(one.root),
                    count: one.saved,
                  })}
                </p>
              ) : (
                <>
                  <p>
                    {t("files.swept", {
                      root: plainName(one.root),
                      seen: one.seen,
                      missing: one.notFound.length,
                    })}
                  </p>
                  {one.moved > 0 && (
                    <p>{t("files.sweptMoved", { count: one.moved })}</p>
                  )}
                  {one.notFound.length > 0 && (
                    <details>
                      <summary className="cursor-pointer">
                        {t("files.sweptNotFound", {
                          count: one.notFound.length,
                        })}
                      </summary>
                      <ul className="mt-1 space-y-0.5">
                        {one.notFound.map((file) => (
                          <li key={file.referenceId} className="break-all">
                            <Link
                              to={`/book/${file.bookId}`}
                              className="underline"
                            >
                              {plainName(file.path)}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {one.notFound.length > 0 &&
                    (one.marked === null ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        isLoading={isMarking}
                        onClick={() => onMarkMissing(one.root)}
                      >
                        {t("files.markMissing")}
                      </Button>
                    ) : (
                      <p>{t("files.markedMissing", { count: one.marked })}</p>
                    ))}
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
