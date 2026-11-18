import { useId, useState, type ChangeEvent, type FormEvent } from "react";

import { Button, Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import { readIsbnList, type IsbnList } from "../../../lib/isbnList";
import { ISBN_LIST_LIMIT } from "../queue";

interface IsbnListPanelProps {
  /** Queue these canonical ISBNs and start the paced lookup over them. */
  onList: (isbns: readonly string[]) => void;
  /**
   * Rows already waiting for the paced lookup, so the bound is the queue's:
   * two lists of five hundred are a thousand rows waiting, as one of a
   * thousand would be.
   */
  waiting: number;
}

/**
 * The largest file read as a list, in bytes.
 *
 * **A bound on the read, not on the list**: `ISBN_LIST_LIMIT` is the list's.
 * Five hundred ISBNs one a line is under nine kilobytes, so a megabyte takes a
 * spreadsheet's column with its neighbours still on, and refuses a file picked
 * by mistake before the browser holds all of it as text.
 */
const MAX_LIST_BYTES = 1024 * 1024;

/**
 * How many invalid tokens are named back; the rest are only counted.
 *
 * Enough for every typo a list typed by hand holds, and a bound on a file of
 * nothing but bad check digits, which would otherwise render one item each.
 */
const INVALID_SHOWN = 50;

/** What the last list handed in came to, or why it was refused. */
type Outcome =
  | { readonly kind: "read"; readonly list: IsbnList }
  | { readonly kind: "too-many"; readonly count: number }
  | { readonly kind: "no-room"; readonly count: number; readonly room: number }
  | { readonly kind: "file-too-large" }
  | { readonly kind: "file-unreadable" };

/** Why a list of `count` ISBNs is refused with `waiting` rows queued, or null. */
function refusalOf(count: number, waiting: number): Outcome | null {
  // A list with no valid ISBN queues nothing, so it is read rather than
  // refused: refused as no room, its invalid tokens would never be named.
  if (count === 0) return null;
  if (count > ISBN_LIST_LIMIT) return { kind: "too-many", count };
  // Counted with the ISBNs the queue already holds, which are not queued
  // again: refusing a list that would have fitted is the cheaper mistake.
  if (waiting + count > ISBN_LIST_LIMIT) {
    return {
      kind: "no-room",
      count,
      room: Math.max(0, ISBN_LIST_LIMIT - waiting),
    };
  }
  return null;
}

/**
 * Hand a picked file's text to `take`, or say why it was not read as a list.
 *
 * **`take` runs inside the `try`**, so a fault while taking the list shows as
 * an unreadable file rather than escaping as an unhandled rejection from the
 * `void` call that started the read.
 */
async function readListFile(
  file: File,
  take: (text: string) => void,
): Promise<Outcome | null> {
  if (file.size > MAX_LIST_BYTES) return { kind: "file-too-large" };
  try {
    take(await file.text());
    return null;
  } catch {
    return { kind: "file-unreadable" };
  }
}

/**
 * Catalogue a list of ISBNs without scanning each one, as a fifth way into the
 * queue rapid mode and the file picker fill.
 *
 * **Every ISBN goes through the one paced run** and lands in the same review,
 * so nothing is written before the member presses Add all, exactly as for a
 * shelf scanned in rapid mode. **An ISBN whose check digit fails is reported
 * here and never queued**, so no catalogue is asked about a typo.
 */
export default function IsbnListPanel({ onList, waiting }: IsbnListPanelProps) {
  const { t } = useTranslation();
  const textId = useId();
  const fileId = useId();
  const [text, setText] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  function take(written: string) {
    const list = readIsbnList(written);
    const refused = refusalOf(list.isbns.length, waiting);
    if (refused) {
      setOutcome(refused);
      return;
    }
    setOutcome({ kind: "read", list });
    if (list.isbns.length > 0) onList(list.isbns);
    setText("");
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    take(text);
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Cleared so the same file can be picked again after its rows are removed.
    event.target.value = "";
    if (file) void readFile(file);
  }

  async function readFile(file: File) {
    const refused = await readListFile(file, take);
    if (refused) setOutcome(refused);
  }

  return (
    <div className="mt-6 rounded-2xl border border-paper-200 p-4 dark:border-paper-700">
      <div className="flex items-center gap-2 mb-1">
        <Icon name="list" className="w-4 h-4 text-paper-600" />
        <h2 className="text-sm font-semibold text-paper-800 dark:text-paper-100">
          {t("isbnList.title")}
        </h2>
      </div>
      <p className="text-xs text-paper-600 mb-3 leading-relaxed dark:text-paper-400">
        {t("isbnList.explain", { limit: ISBN_LIST_LIMIT })}
      </p>
      <form onSubmit={handleSubmit}>
        <label
          htmlFor={textId}
          className="block text-xs font-medium text-paper-700 mb-1 dark:text-paper-200"
        >
          {t("isbnList.pasteLabel")}
        </label>
        <textarea
          id={textId}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={4}
          className="field w-full text-sm font-mono"
        />
        <Button type="submit" className="mt-2" disabled={text.trim() === ""}>
          {t("isbnList.submit")}
        </Button>
      </form>
      <label
        htmlFor={fileId}
        className="block text-xs font-medium text-paper-700 mb-1 mt-3 dark:text-paper-200"
      >
        {t("isbnList.fileLabel")}
      </label>
      <input
        id={fileId}
        type="file"
        accept=".txt,.csv,text/plain,text/csv"
        onChange={handleFile}
        className="field w-full text-sm"
      />
      {outcome && <OutcomeNote outcome={outcome} />}
    </div>
  );
}

const NOTE =
  "text-xs rounded-lg px-3 py-2 mt-2 leading-relaxed text-amber-700 bg-amber-50 dark:text-amber-300 dark:bg-amber-950/40";

/** What became of the last list, said once beneath the controls. */
function OutcomeNote({ outcome }: { outcome: Outcome }) {
  const { t } = useTranslation();
  if (outcome.kind === "too-many") {
    return (
      <p role="alert" className={NOTE}>
        {t("isbnList.tooMany", {
          count: outcome.count,
          limit: ISBN_LIST_LIMIT,
        })}
      </p>
    );
  }
  if (outcome.kind === "no-room") {
    return (
      <p role="alert" className={NOTE}>
        {t("isbnList.noRoom", {
          count: outcome.count,
          room: outcome.room,
          limit: ISBN_LIST_LIMIT,
        })}
      </p>
    );
  }
  if (outcome.kind === "file-too-large") {
    return (
      <p role="alert" className={NOTE}>
        {t("isbnList.fileTooLarge")}
      </p>
    );
  }
  if (outcome.kind === "file-unreadable") {
    return (
      <p role="alert" className={NOTE}>
        {t("isbnList.fileUnreadable")}
      </p>
    );
  }
  return <ListReport list={outcome.list} />;
}

/**
 * A list that was read: how many were queued and what was left out, each
 * reason its own sentence and absent at zero.
 *
 * **The invalid ones are named, not counted**, because a typo in a list of
 * three hundred is only fixable once the member can see which line it was on.
 */
function ListReport({ list }: { list: IsbnList }) {
  const { t } = useTranslation();
  return (
    <div role="status" className="text-xs mt-2 space-y-1">
      <p className="text-paper-700 dark:text-paper-200">
        {t("isbnList.queued", { count: list.isbns.length })}
      </p>
      {list.invalid.length > 0 && (
        <div className={NOTE}>
          <p>{t("isbnList.invalid", { count: list.invalid.length })}</p>
          <ul className="font-mono mt-1">
            {list.invalid.slice(0, INVALID_SHOWN).map((token) => (
              <li key={token}>{token}</li>
            ))}
          </ul>
          {list.invalid.length > INVALID_SHOWN && (
            <p className="mt-1">
              {t("isbnList.invalidMore", {
                count: list.invalid.length - INVALID_SHOWN,
              })}
            </p>
          )}
        </div>
      )}
      {list.repeated > 0 && (
        <p className="text-paper-600 dark:text-paper-400">
          {t("isbnList.repeated", { count: list.repeated })}
        </p>
      )}
      {list.ignored > 0 && (
        <p className="text-paper-600 dark:text-paper-400">
          {t("isbnList.ignored", { count: list.ignored })}
        </p>
      )}
    </div>
  );
}
