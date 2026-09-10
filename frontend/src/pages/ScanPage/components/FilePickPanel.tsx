import { useId, type ChangeEvent } from "react";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import { SUPPORTED_EXTENSIONS } from "../../../lib/fileName";

interface FilePickPanelProps {
  /** Hand the picked files to the queue. Reading them is the hook's business. */
  onPick: (files: File[]) => void;
  /** True while any picked file is still being read. */
  isReading: boolean;
  /**
   * How many picked files the walk passed over.
   *
   * **Said here rather than beside the queue**, because a folder of formats
   * Endpaper does not read produces no queue at all: a message that only
   * appears next to entries would be absent in exactly the case it is for.
   */
  skipped: number;
}

/**
 * What the dialog offers to pick, which is a filter and never a check.
 *
 * Built from the one list rather than spelled again, so a format joining the
 * walk cannot be one the dialog greys out. A folder pick ignores it entirely,
 * which is why `hooks.ts` filters by extension as well.
 */
const ACCEPTED = SUPPORTED_EXTENSIONS.join(",");

/**
 * How a browser is asked for a folder.
 *
 * Spread rather than written as a prop because `webkitdirectory` is not in
 * React's DOM typings, and it is the only attribute any browser offers for
 * this. React passes a lowercase attribute through unchanged.
 */
const FOLDER: Record<string, string> = { webkitdirectory: "" };

const LABEL =
  "block text-xs font-medium text-paper-700 mb-1 dark:text-paper-200";

/**
 * Choosing a book by pointing at its file.
 *
 * The fourth way of answering *which* book, beside the camera, the ISBN box and
 * the title search, and it fills the same queue as the scanner rather than a
 * second bulk path of its own.
 *
 * **The file is read here and the application never takes custody of it.** Its
 * metadata joins the queue and the bytes are dropped. The rule is about custody
 * rather than about destination, which is why this is not simply "we do not
 * upload": a transient endpoint that discards the file, and a browser that PUTs
 * it to somebody else's host, are both the thing being refused. `lib/epub.ts`
 * carries the full statement.
 *
 * **Custody of the file is not the whole of what a member is deciding.** A
 * folder pick sends where the file was: the picked folder's name and the path
 * beneath it, on a book every account that can see the book can read.
 * `lib/digitalReference.ts` is what the browser may honestly claim, and
 * `file.explain` says it here, because this is the press that starts it.
 *
 * **Nothing opens by itself, and that is deliberate rather than incidental.**
 * The page next to this one says why for the camera: opening a camera is not
 * something a page should do because somebody looked at it. A file dialog is
 * the same class of thing, and an `<input type="file">` cannot open one without
 * a press, so keeping the intake on a real input is what holds that line.
 *
 * Dumb: it reports what was picked. Reading, bounding and queueing are the
 * page's hooks.
 */
export default function FilePickPanel({
  onPick,
  isReading,
  skipped,
}: FilePickPanelProps) {
  const { t } = useTranslation();
  // Generated rather than written, because two of these on one page would give
  // a label two inputs to point at and neither of them the right one.
  const filesId = useId();
  const folderId = useId();

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    // Cleared so picking the same file again fires a change. Without it, a file
    // removed from the queue by hand could not be picked back.
    event.target.value = "";
    if (files.length > 0) onPick(files);
  }

  return (
    <div className="mt-6 rounded-2xl border border-paper-200 p-4 dark:border-paper-700">
      <div className="flex items-center gap-2 mb-1">
        <Icon name="inbox" className="w-4 h-4 text-paper-600" />
        <h2 className="text-sm font-semibold text-paper-800 dark:text-paper-100">
          {t("file.title")}
        </h2>
      </div>
      <p className="text-xs text-paper-600 mb-3 leading-relaxed dark:text-paper-400">
        {t("file.explain")}
      </p>
      {/* **Both labels are visible, and that is not a style choice.** No
          browser promises a different button on a `webkitdirectory` input:
          Chrome and Safari both draw "Choose Files". Two controls a sighted
          member cannot tell apart, distinguished only for a screen reader, is
          the folder half of this feature hidden behind a guess. */}
      <label htmlFor={filesId} className={LABEL}>
        {t("file.pickLabel")}
      </label>
      <input
        id={filesId}
        type="file"
        multiple
        // A filter on the dialog and never a check: what decides whether a file
        // can be read is opening it, and what decides whether it is walked at
        // all is `supportedExtension`.
        accept={ACCEPTED}
        onChange={handleChange}
        className="field w-full text-sm"
      />
      {/* The folder is the other half of the fallback and not a convenience: a
          file under a directory named for its author is telling you something
          the file itself often does not, and only a folder pick carries that
          path. */}
      <label htmlFor={folderId} className={`${LABEL} mt-3`}>
        {t("fallback.pickFolderLabel")}
      </label>
      <input
        id={folderId}
        type="file"
        multiple
        {...FOLDER}
        onChange={handleChange}
        className="field w-full text-sm"
      />
      {skipped > 0 && (
        <p
          role="status"
          className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mt-2 dark:text-amber-300 dark:bg-amber-950/40"
        >
          {t("fallback.skipped", { count: skipped })}
        </p>
      )}
      {isReading && (
        <p
          role="status"
          className="text-xs text-paper-600 mt-2 dark:text-paper-400"
        >
          {t("file.readingFiles")}
        </p>
      )}
    </div>
  );
}
