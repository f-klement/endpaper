import { useTranslation, type MessageKey, type Translate } from "../../../i18n";
import type { BookMatch } from "../../../api/generated/model";
import type { AudioFailure } from "../../../lib/audiobook";
import type { FileFailure } from "../../../lib/fileReaders";
import type {
  NamedScanReason,
  QueueFigures,
  ScanReason,
  ScannedEntry,
} from "../hooks";
import type { BulkProgress } from "../../../lib/bulkWrite";

/**
 * What a member is told about a file that yielded nothing.
 *
 * A total mapping of `FileFailure` rather than a switch, so a reason added to
 * that closed union is a compile error here instead of a file reported with
 * whatever the last arm said.
 */
const FILE_FAILURES: Record<FileFailure, MessageKey> = {
  "not-an-epub": "file.notAnEpub",
  "not-a-mobi": "file.notAMobi",
  "not-an-fb2": "file.notAnFb2",
  "not-a-comic": "file.notAComic",
  "not-a-pdf": "file.notAPdf",
  damaged: "file.damaged",
  protected: "file.protected",
  "too-large": "file.tooLarge",
  unsupported: "file.unsupported",
  "no-inflate": "file.noInflate",
};

/**
 * What a member is told about an audio file that said nothing about itself.
 *
 * Its own total mapping rather than an arm of `FILE_FAILURES`, because the two
 * unions are closed separately: an audio file that carries no tags is an
 * ordinary file rather than a broken one, and it still becomes a candidate
 * under whatever its folder is called.
 */
const AUDIO_FAILURES: Record<AudioFailure, MessageKey> = {
  "no-tags": "audio.noTags",
  unreadable: "audio.unreadable",
};

/**
 * One sentence per reason that is a name and nothing else.
 *
 * A total `Record` rather than a switch, which is `STORE_FAILURES`' rule and
 * `OFFERED_AGAIN`'s: a reason added to `NamedScanReason` with no sentence here
 * is a compile error rather than a row rendered blank. The two tables above are
 * the same thing one level down, for the two arms that carry a reader's own
 * closed union.
 *
 * **Keyed on `NamedScanReason` rather than on `ScanReason["kind"]`**, because
 * three of the union's arms are answered above this table and never reach it:
 * keyed on every kind, this would have to carry a sentence for `file`, `audio`
 * and `server-said` that nothing would ever look up. `NamedScanReason` holds
 * the rest of that reasoning.
 */
const REASONS: Record<NamedScanReason, MessageKey> = {
  "no-title": "file.noTitle",
  unreadable: "file.unreadable",
  "not-in-catalogues": "fallback.notInCatalogues",
  "lookup-failed": "fallback.lookupFailed",
  "kept-the-name": "fallback.keptTheName",
  "kept-for-now": "fallback.keptForNow",
  unreachable: "common.cannotReachServer",
};

/**
 * The sentence one reason is told in, in the locale being read now.
 *
 * **The whole point of the queue holding a name.** The row was rendered in the
 * language in force when the file failed for as long as the sentence was what
 * was stored.
 *
 * The three arms handled before the table are the three that are not a bare
 * name: two carry a reader's own closed union, and `server-said` carries the
 * server's own words, which are the one thing here no catalogue of ours can
 * translate.
 */
function reasonText(reason: ScanReason, t: Translate): string {
  if (reason.kind === "file") return t(FILE_FAILURES[reason.failure]);
  if (reason.kind === "audio") return t(AUDIO_FAILURES[reason.failure]);
  if (reason.kind === "server-said") return reason.message;
  return t(REASONS[reason.kind]);
}

/**
 * One catalogue record as one line: what is shown, and what is announced.
 *
 * **One function because the two must not drift**, and they did: the line was
 * composed inline in the JSX and the accessible name took `match.title` alone,
 * so two records differing only in author or year were one name to a screen
 * reader and two visibly different rows to everybody else.
 *
 * Empty where a record names nothing at all, which the caller reads as its
 * signal to fall back to the file's own label.
 */
function recordLine(match: BookMatch): string {
  // **Built from the parts that are there**, rather than from three fragments
  // that assume the one before them. A `BookMatch.title` is nullable, and
  // composing the separators into each fragment printed `, Frank Herbert
  // (1965)` for a record with no title, on the visible line and in the
  // accessible name with it.
  const named = [match.title, match.author].filter(Boolean).join(", ");
  return match.year ? `${named} (${match.year})`.trim() : named;
}

interface RapidQueueProps {
  entries: ScannedEntry[];
  isAdding: boolean;
  /** How far the run that is going has got, and `null` when none is. */
  progress: BulkProgress | null;
  result: {
    added: number;
    failed: number;
    unreferenced: number;
    stopped: boolean;
  } | null;
  onRemove: (key: string) => void;
  onAddAll: () => void;
  onDiscard: () => void;
  /** Halt the batch after the book in flight, leaving the rest in the queue. */
  onStopAdding: () => void;
  /**
   * What the queue adds up to, which this component renders and never counts.
   *
   * **Taken whole from the hook**, because the batch excludes exactly the rows
   * one of these figures counts and a predicate written twice is a screen able
   * to report something the page did not do. `QueueFigures` says what each one
   * is; saying it a second time here is how the two come to disagree.
   */
  figures: QueueFigures;
  isLookingUp: boolean;
  onLookUp: () => void;
  onStopLookUp: () => void;
  onChoose: (key: string, match: BookMatch) => void;
  onKeepName: (key: string) => void;
  /**
   * Keep the file name on every row still being decided, for now.
   *
   * **The one control on this screen whose effect is undone by pressing another
   * one**: the rows it clears become rows the lookup offers again, so the queue
   * grows a "Look up N by name" button back the moment it is pressed. That is
   * what the member is being told by `fallback.keepAllNote`, and it is the
   * reason this is not the refused "Keep every name".
   */
  onKeepAllForNow: () => void;
  /** Ask the catalogues again about every name kept in bulk. */
  onLookUpKept: () => void;
  /**
   * File one audiobook candidate's parts as a book each.
   *
   * **The one control that can undo the grouping rule**, and the reason every
   * grouped row says how many files it is: a member who is shown "40 files, as
   * one audiobook" and disagrees has somewhere to press. Without it the only way
   * out is to remove the row and pick the files one at a time.
   */
  onSplit: (key: string) => void;
}

/**
 * What the scanner has caught and the file picker has read so far.
 *
 * Deliberately shows the failures alongside the hits. A book whose ISBN
 * matched nothing is still a book on the shelf, an EPUB that would not open is
 * still a book on somebody's disk, and silently dropping either is how a
 * catalogue ends up quietly incomplete.
 *
 * **Entries are identified by `key`, never by ISBN**, because a picked file
 * usually has none: see `ScannedEntry.key`.
 */
export default function RapidQueue({
  entries,
  isAdding,
  result,
  progress,
  onRemove,
  onAddAll,
  onDiscard,
  onStopAdding,
  figures,
  isLookingUp,
  onLookUp,
  onStopLookUp,
  onChoose,
  onKeepName,
  onKeepAllForNow,
  onLookUpKept,
  onSplit,
}: RapidQueueProps) {
  const { t } = useTranslation();
  // Read out here so every figure below is spelled the way the hook spells it.
  const { waiting, deciding, keptForNow, paceMinutes, keptPaceMinutes } =
    figures;

  // **Said once, and only for the rows it is true of.** Explaining before the
  // fact would be a page apologising for something that may not happen, and
  // explaining per row would say it thirty times. A member who was offered
  // records and preferred the name is not a member the catalogues had nothing
  // for, so `answered` carries the two apart.
  const anyEmptyAnswer = entries.some((entry) => entry.answered === "nothing");
  const busy = isAdding || isLookingUp;
  // Rows standing under their names with somewhere to go back to, and no run in
  // the way. Read three times below, so it is named once.
  const showKept = keptForNow > 0 && !isLookingUp;

  // The banner sits beside whatever is left rather than replacing it. Anything
  // still in the queue after a run is a book that did not go in.
  //
  // **It is rendered below the controls, and that is a safety rule rather than
  // a layout preference.** See the block that mounts it at the foot of this
  // component.
  //
  // **Never while a run is going**, which the stop made the ordinary case: the
  // rows a member keeps are kept in order to be added, so pressing Add all
  // again is the way back, and the previous run's verdict would otherwise sit
  // amber above a live progress figure saying those same rows are still in the
  // queue while they are being written. The hook clears the verdict when a run
  // starts; this refuses the pair whoever renders it.
  const banner =
    result && !isAdding ? (
      <p
        role="status"
        className={`text-sm rounded-xl px-3 py-2 mt-4 border ${
          // A stopped run reads amber for the reason a run with failures does:
          // the queue is not empty and the number is not the number that was
          // asked for. Green there would call a halt a completed batch.
          result.failed > 0 || result.stopped
            ? "text-amber-800 bg-amber-50 border-amber-100 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900"
            : "text-green-700 bg-green-50 border-green-100 dark:text-green-300 dark:bg-green-950 dark:border-green-900"
        }`}
      >
        {result.stopped
          ? t("rapid.addedStopped", {
              count: result.added,
              failed: result.failed,
            })
          : t("rapid.added", { count: result.added, failed: result.failed })}
        {/* **A second sentence rather than a third number in the first.** A book
          whose location was not recorded is in the catalogue and is not a
          failure, so saying it inside "N added, M below" would read as one.
          Absent at zero, which is every batch of barcodes. */}
        {result.unreferenced > 0 && (
          <span className="block mt-1">
            {t("rapid.unreferenced", { count: result.unreferenced })}
          </span>
        )}
      </p>
    ) : null;

  if (entries.length === 0) {
    if (banner) return banner;
    return (
      <p className="text-sm text-paper-600 text-center mt-4 dark:text-paper-400">
        {t("rapid.nothingScanned")}
      </p>
    );
  }

  return (
    <div className="mt-4 space-y-3">
      <p className="text-sm font-medium text-paper-700 dark:text-paper-200">
        {t("rapid.queued", { count: entries.length })}
      </p>

      {/* Offered, never automatic. A folder of several hundred files is
          several hundred catalogue fan outs, which is not something a page may
          spend because somebody pointed at a directory. */}
      {waiting > 0 && !isLookingUp && (
        <div>
          <button
            type="button"
            onClick={onLookUp}
            disabled={isAdding}
            className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
          >
            {t("fallback.lookUp", { count: waiting })}
          </button>
          <p className="text-xs text-paper-600 mt-1.5 leading-relaxed dark:text-paper-400">
            {t("fallback.pace", { minutes: paceMinutes })}
          </p>
        </div>
      )}

      {isLookingUp && (
        <button
          type="button"
          onClick={onStopLookUp}
          className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
        >
          {t("fallback.stop")}
        </button>
      )}

      {anyEmptyAnswer && (
        <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
          {t("fallback.aboutEbooks")}
        </p>
      )}

      <ul className="space-y-1.5 max-h-64 overflow-y-auto">
        {entries.map((entry) => (
          <li
            key={entry.key}
            className="text-sm border border-paper-100 rounded-lg px-2.5 py-1.5 dark:border-paper-800"
          >
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate">
                {entry.state === "looking-up" && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {t("rapid.lookingUp")}
                  </span>
                )}
                {entry.state === "reading" && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {t("rapid.reading", { name: entry.label })}
                  </span>
                )}
                {entry.state === "found" && (
                  <span className="text-paper-800 dark:text-paper-100">
                    {entry.draft?.title}
                  </span>
                )}
                {entry.state === "not-found" && (
                  <span className="text-amber-700 dark:text-amber-300">
                    {t("rapid.notFound", { isbn: entry.isbn })}
                  </span>
                )}
                {entry.state === "searching" && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {t("fallback.searching")}
                  </span>
                )}
                {/* A book, not a failure: it carries what its name said and the
                  batch adds it like any other. The note beside it says where
                  the title came from and what the file itself could not say. */}
                {(entry.state === "derived" || entry.state === "choosing") && (
                  <span className="text-paper-800 dark:text-paper-100">
                    {entry.draft?.title}
                    <span className="text-paper-600 dark:text-paper-400">
                      {" "}
                      {t("fallback.fromTheName")}
                      {entry.reason ? ` ${reasonText(entry.reason, t)}` : ""}
                    </span>
                  </span>
                )}
                {/* Named, not counted. After a shelf of thirty, "six could not
                  be added" is unrecoverable: this says which six and why, and
                  they stay in the queue so they can be retried or dropped. */}
                {entry.state === "failed" && (
                  <span className="text-danger-600 dark:text-danger-300">
                    {entry.draft?.title || entry.label}
                    {entry.reason && (
                      <span className="text-paper-600 dark:text-paper-400">
                        {" "}
                        {reasonText(entry.reason, t)}
                      </span>
                    )}
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => onRemove(entry.key)}
                aria-label={t("rapid.removeFromQueue", { label: entry.label })}
                className="shrink-0 text-paper-600 hover:text-danger-500 dark:text-paper-400 dark:hover:text-danger-300"
              >
                ×
              </button>
            </div>

            {/* **What a candidate is made of, and the way out of it.** For
                every other format one file is one book, so a row that stands
                for forty files has to say so before the batch runs:
                nothing here is written until "Add all", and this is the moment
                a member can see the grouping was wrong and undo it. */}
            {entry.group && entry.group.files.length > 1 && (
              <div className="mt-1.5 text-xs">
                <details>
                  <summary className="cursor-pointer text-paper-600 dark:text-paper-400">
                    {t("audio.grouped", { count: entry.group.files.length })}
                  </summary>
                  <ul className="mt-1 ml-3 space-y-0.5 max-h-32 overflow-y-auto text-paper-600 dark:text-paper-400">
                    {entry.group.files.map((file) => (
                      <li key={file.key} className="truncate">
                        {file.name}
                      </li>
                    ))}
                  </ul>
                </details>
                <button
                  type="button"
                  onClick={() => onSplit(entry.key)}
                  disabled={busy}
                  // The visible words are the same on every grouped row and the
                  // accessible name is not, for the reason the match rows give.
                  aria-label={t("audio.splitFor", { label: entry.label })}
                  className="mt-1 text-paper-600 underline hover:text-paper-800 disabled:opacity-50 dark:text-paper-400 dark:hover:text-paper-200"
                >
                  {t("audio.split")}
                </button>
              </div>
            )}

            {/* Accept or reject, per file. The ranking already put the likeliest
                record first, and the rest are here to be disagreed with. */}
            {entry.state === "choosing" && entry.matches && (
              <div className="mt-2 space-y-1">
                <p className="text-xs text-paper-600 dark:text-paper-400">
                  {t("fallback.matches", { count: entry.matches.length })}
                </p>
                <ul className="space-y-1">
                  {entry.matches.map((match, index) => (
                    <li
                      key={`${match.google_books_id ?? match.isbn13 ?? ""}:${index}`}
                      className="flex items-center gap-2 text-xs"
                    >
                      <span className="min-w-0 flex-1 truncate text-paper-700 dark:text-paper-200">
                        {recordLine(match)}
                      </span>
                      <button
                        type="button"
                        // The visible word is the same on every row and the
                        // accessible name is not: a screen reader in a queue of
                        // thirty files would otherwise meet a hundred and fifty
                        // buttons called "Use".
                        //
                        // **Both halves, because either alone collides.** The
                        // record alone is shared by two rows a catalogue
                        // answered alike, which a folder holding one book in
                        // two formats produces; the row alone is shared by
                        // every record offered inside it.
                        //
                        // **The whole line and not the title**, which is the
                        // half a fan out collides on: two sources answering one
                        // ISBN both say "Dune", and the author and the year are
                        // what a member is choosing between. Rendered from the
                        // same function that draws the line beside it, so the
                        // name a member hears is the row they can see.
                        aria-label={t("fallback.useFor", {
                          record: recordLine(match) || entry.label,
                          label: entry.label,
                        })}
                        onClick={() => onChoose(entry.key, match)}
                        className="shrink-0 px-2 py-1 rounded-lg border border-paper-200 font-medium text-paper-700 hover:bg-paper-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
                      >
                        {t("fallback.use")}
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  // Named by the row, for the reason the button above is named
                  // by the record: thirty rows still deciding render thirty of
                  // these, and the visible word is the same on every one.
                  aria-label={t("fallback.keepFor", { label: entry.label })}
                  onClick={() => onKeepName(entry.key)}
                  className="text-xs text-paper-600 underline hover:text-paper-800 dark:text-paper-400 dark:hover:text-paper-200"
                >
                  {t("fallback.keep")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>

      {/* **The count, then the way out of it, then what that costs.** The same
          three parts in the same order as the lookup control above, which is
          the pattern a member has already read once on this screen: a figure,
          a button, and the sentence saying what pressing it spends. */}
      {deciding > 0 && (
        <div>
          <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
            {t("fallback.stillToDecide", { count: deciding })}
          </p>
          {/* Bordered rather than filled, and nowhere near the discard: this
              writes nothing and throws nothing away, and a control that reads
              as either would be pressed by fewer people than should press it.
              The accent fill on this screen belongs to the one control that
              writes. */}
          <button
            type="button"
            onClick={onKeepAllForNow}
            disabled={busy}
            className="w-full mt-1.5 py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
          >
            {t("fallback.keepAllForNow", { count: deciding })}
          </button>
          <p className="text-xs text-paper-600 mt-1.5 leading-relaxed dark:text-paper-400">
            {t("fallback.keepAllNote")}
          </p>
        </div>
      )}

      {/* **What the press left, in the place the press was.** The control that
          was here unmounts when the last row is decided, and a control that
          disappears acknowledges nothing: this says how many rows are standing
          under their names, and offers the way back beside it. Announced,
          because the row it describes may be six scroll heights away.

          **Mounted before there is anything to announce, and it is the text
          that is gated rather than the region.** A live region inserted into the
          page with its content already in it is the one a screen reader does not
          speak, so gating the element would be an acknowledgement nobody hears.
          Empty while a run is going, for the reason the button beside it is
          hidden then and for a second one: the run settles one row at a time, so
          a region left saying a count would say it once per row.

          **`sr-only` on the wrapper while there is nothing to say, which is
          what keeps it out of the flow.** The container's `space-y-3` puts a
          margin between every pair of children, so a permanently present block
          would open a gap for nothing; `sr-only` is absolutely positioned, so
          the visible rows keep the spacing they had, and everything inside it
          stays in the accessibility tree. The toggle is on the wrapper rather
          than on the paragraph so that this block keeps the rhythm the lookup
          control above it has: `space-y-1.5` between the sentence and its own
          button, rather than the container's larger gap, which reads as a
          separate instruction instead of as the sentence's button.

          **`aria-live` rather than `role="status"`**, which is the same live
          region: the banner above already answers to that role, and a second
          element answering to it makes "the status" of this queue ambiguous to
          anything asking by role, tests included. */}
      <div className={showKept ? "space-y-1.5" : "sr-only"}>
        <p
          aria-live="polite"
          aria-atomic="true"
          className="text-xs text-paper-600 leading-relaxed dark:text-paper-400"
        >
          {showKept ? t("fallback.keptForNowCount", { count: keptForNow }) : ""}
        </p>
        {showKept && (
          <>
            <button
              type="button"
              onClick={onLookUpKept}
              disabled={isAdding}
              className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
            >
              {t("fallback.lookUpAgain", { count: keptForNow })}
            </button>
            {/* The same disclosure the first pass carries, because it is the
                same call: names leave the browser either way. Its own sentence,
                which usually renders with the first one nowhere on screen. */}
            <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
              {t("fallback.paceAgain", { minutes: keptPaceMinutes })}
            </p>
          </>
        )}
      </div>

      {/* **A figure beside the way out of the run.** Stopping with nothing on
          screen saying how far it had got is a button pressed blind, and this
          is the same `{done} of {total}` the import cards on the settings page
          have shown since they had a stop. It is the loop's own count rather
          than a second one kept here.

          **Not a live region, and not for the reason the block below is not
          one.** That one is kept out of `role="status"` so the banner is the
          only thing answering to the role. This one is a number that moves once
          per book, so announcing it would read a three hundred book run out
          loud a line at a time. */}
      {isAdding && progress && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("rapid.progress", {
            done: progress.done,
            total: progress.total,
          })}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDiscard}
          disabled={busy}
          className="px-4 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
        >
          {t("rapid.discard")}
        </button>
        <button
          type="button"
          onClick={onAddAll}
          disabled={busy}
          className="flex-1 py-2.5 rounded-xl bg-accent-fill text-on-accent text-sm font-semibold hover:bg-accent-fill-hover disabled:opacity-50"
        >
          {isAdding ? t("rapid.adding") : t("rapid.addAll")}
        </button>
      </div>

      {/* **The verdict and the stop are the last two children, and that is one
          rule rather than two placements.**

          A run ends in one commit: the stop unmounts, the progress figure
          unmounts, the rows that were written are pruned, and the verdict
          mounts. The member's finger is on the stop, which is the only control
          a run leaves live, and the discard beside `Add all` clears a queue of
          barcodes scanned one at a time with no confirmation and no undo.

          **So the rule is that the commit which moves the discard may not make
          it live, and the one that makes it live may not move it toward the
          finger.** Both halves hold by document order rather than by
          arithmetic, which is what makes them checkable without a layout
          engine:

          - Everything that commit removes sits **above** the row, so the
            region above it only shrinks and the row can only move away from
            the finger, never toward it. The progress figure alone guarantees
            that: it is present for every run and goes at the end of every one.
          - Everything that commit mounts sits **below** the row, and it is
            text. The verdict takes the space the stop had, so what arrives
            under a finger still tapping is a paragraph.

          Drawing the verdict at the top of this container broke the second
          half: the banner pushed the row down toward the finger by more than
          the progress figure's removal lifted it, and `disabled={busy}` went
          false in the same commit.

          **The residue is outside this component and is a neighbour's
          property**, so it is stated here rather than discovered: on the file
          pick path `rapid.isActive` is false, `showQueue` and `showEntry` are
          both true, and `ScanPage` opens that block with a full bleed
          `aspect-[4/3]` panel, the camera or its dashed placeholder. Whatever
          this container's foot does, the first control under it is the camera
          button below that panel. Reordering that block is what would make
          this false.

          The `Stop` word and the full width are the paced lookup's stop, which
          is the one this page has already taught. */}
      {banner}
      {isAdding && (
        <button
          type="button"
          onClick={onStopAdding}
          className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
        >
          {t("rapid.stopAdding")}
        </button>
      )}
    </div>
  );
}
