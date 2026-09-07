import type { ChangeEvent } from "react";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";

interface FilePickPanelProps {
  /** Hand the picked files to the queue. Reading them is the hook's business. */
  onPick: (files: File[]) => void;
  /** True while any picked file is still being read. */
  isReading: boolean;
}

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
}: FilePickPanelProps) {
  const { t } = useTranslation();

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
      <input
        type="file"
        multiple
        // Both spellings, because a browser matches an extension and a media
        // type separately and a file picked off a share often carries neither.
        // It is a filter on the dialog and never a check: what decides whether
        // a file is an EPUB is opening it.
        accept=".epub,application/epub+zip"
        aria-label={t("file.pickLabel")}
        onChange={handleChange}
        className="field w-full text-sm"
      />
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
