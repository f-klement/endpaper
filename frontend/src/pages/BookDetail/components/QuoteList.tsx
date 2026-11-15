import { useState, type FormEvent } from "react";

import type {
  QuoteCreate,
  QuoteOut,
  UserOut,
} from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { shortMonthDate } from "../../../lib/date";

/** Matches `QUOTE_TEXT_MAX` and `QUOTE_NOTE_MAX` in the backend's models.py.
 *
 * Stated here so the textarea stops at the same place the API refuses, rather
 * than letting somebody type a passage for a minute and then answering 422.
 * The server is still the authority: this is a courtesy, not a check. */
const TEXT_MAX = 2000;
const NOTE_MAX = 1000;
/** `MAX_PAGE_NUMBER_IN_A_BOOK`, which the API bounds `page` by. */
const PAGE_MAX = 100000;

interface QuoteListProps {
  quotes: QuoteOut[];
  currentUser: UserOut;
  isAdding: boolean;
  onAdd: (quote: QuoteCreate) => void;
  onEdit: (quoteId: number, quote: QuoteCreate) => void;
  onRemove: (quoteId: number) => void;
}

/**
 * An empty page field means "I did not note it", which the API stores as null.
 *
 * **Deliberately not clamped to the range.** An earlier version returned null
 * for anything outside 1 to PAGE_MAX, which quietly saved the quote with no
 * page at all after somebody typed a number: a silent discard is worse than a
 * refusal they can see.
 *
 * That leaves this relying on the browser refusing the submit, which is why
 * **both** forms here are real `<form>` elements with `type="submit"` on the
 * button. The edit controls were a bare `<div>` with an `onClick`, and
 * constraint validation does not run outside a form, so `min`, `max` and the
 * implicit `step` of 1 were all inert there. Two consequences, both measured
 * against the code as it was: an out-of-range page reached the API and 422d
 * *after* the save had closed the editor and thrown the edit away, and a
 * decimal like `12.5` fell through the `Number.isInteger` branch below and was
 * discarded in silence, which is the exact defect this comment says was
 * removed. Inside a form the step mismatch stops both before they start.
 */
function pageOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) ? parsed : null;
}

const FIELD_CLASS =
  "w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700";

/**
 * One quote being corrected, seeded from the quote as stored. Mounted afresh
 * for each quote opened, so a correction abandoned on one never seeds another.
 *
 * A form, not a div. `min`/`max` on the page field are only enforced by a
 * submit, and this used to be a click handler.
 */
function QuoteEditForm({
  quote,
  onSave,
  onCancel,
}: {
  quote: QuoteOut;
  onSave: (quote: QuoteCreate) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [editText, setEditText] = useState(quote.text);
  const [editPage, setEditPage] = useState(
    quote.page == null ? "" : String(quote.page),
  );
  const [editNote, setEditNote] = useState(quote.note ?? "");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = editText.trim();
    if (!trimmed) return;
    onSave({
      text: trimmed,
      page: pageOrNull(editPage),
      note: editNote.trim() || null,
    });
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <textarea
        value={editText}
        onChange={(event) => setEditText(event.target.value)}
        rows={3}
        maxLength={TEXT_MAX}
        aria-label={t("quotes.editLabel")}
        className={`${FIELD_CLASS} resize-none`}
      />
      <input
        type="number"
        inputMode="numeric"
        min={1}
        max={PAGE_MAX}
        value={editPage}
        onChange={(event) => setEditPage(event.target.value)}
        placeholder={t("quotes.pagePlaceholder")}
        aria-label={t("quotes.editPageLabel")}
        className={FIELD_CLASS}
      />
      <textarea
        value={editNote}
        onChange={(event) => setEditNote(event.target.value)}
        rows={2}
        maxLength={NOTE_MAX}
        placeholder={t("quotes.notePlaceholder")}
        aria-label={t("quotes.editNoteLabel")}
        className={`${FIELD_CLASS} resize-none`}
      />
      <div className="flex gap-2">
        <button
          type="submit"
          className="px-3 py-1.5 bg-accent-fill hover:bg-accent-fill-hover text-on-accent rounded-lg text-xs font-medium"
        >
          {t("common.save")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 border border-paper-200 text-paper-600 rounded-lg text-xs font-medium hover:bg-paper-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
        >
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

/** One quote as read, with the controls its reader may use on it. */
function QuoteView({
  quote,
  isAuthor,
  canDelete,
  onStartEdit,
  onRemove,
}: {
  quote: QuoteOut;
  isAuthor: boolean;
  canDelete: boolean;
  onStartEdit: () => void;
  onRemove: () => void;
}) {
  const { t, locale } = useTranslation();
  return (
    <>
      {/* A blockquote, because it is one: this is the book's text and not the
          member's. The rule down the left is what says so at a glance, and
          `whitespace-pre-line` keeps the line breaks of a passage of verse. */}
      <blockquote className="border-l-2 border-accent-300 pl-3 text-sm text-paper-700 leading-relaxed whitespace-pre-line dark:border-accent-500 dark:text-paper-200">
        {quote.text}
      </blockquote>
      {quote.note != null && (
        <p className="text-sm text-paper-600 mt-2 dark:text-paper-400">
          {quote.note}
        </p>
      )}
      <div className="flex items-center justify-between mt-2">
        <span className="text-xs text-paper-600 dark:text-paper-400">
          {quote.page != null && (
            <>{t("quotes.onPage", { page: quote.page })} · </>
          )}
          {quote.author?.username} · {shortMonthDate(quote.created_at, locale)}
        </span>
        {canDelete && (
          <div className="flex gap-2">
            {isAuthor && (
              <button
                onClick={onStartEdit}
                className="text-xs text-accent-600 hover:text-accent-800 dark:text-accent-400 dark:hover:text-accent-300"
              >
                {t("common.edit")}
              </button>
            )}
            <button
              onClick={onRemove}
              // The same four tiers and the same reason as NoteList's delete:
              // `danger-300` is not ink on a light card and `danger-600` is
              // nearly the dark card itself, so neither the resting state nor
              // the dark hover can be inherited. Both rungs are recomputed over
              // every palette by `tests/theme/palettes.test.ts::the rungs a
              // delete control cannot rest on`; no band is quoted here.
              className="text-xs text-danger-500 hover:text-danger-600 dark:text-danger-300 dark:hover:text-danger-100"
            >
              {t("common.delete")}
            </button>
          </div>
        )}
      </div>
    </>
  );
}

/** Passages copied out of this book. Used only by BookDetail. */
export default function QuoteList({
  quotes,
  currentUser,
  isAdding,
  onAdd,
  onEdit,
  onRemove,
}: QuoteListProps) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [page, setPage] = useState("");
  const [note, setNote] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    onAdd({ text: trimmed, page: pageOrNull(page), note: note.trim() || null });
    setText("");
    setPage("");
    setNote("");
  }

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-3 dark:text-paper-200">
        {t("quotes.title")}
      </p>

      {quotes.length === 0 && (
        <p className="text-sm text-paper-600 italic mb-3 dark:text-paper-400">
          {t("quotes.none")}
        </p>
      )}

      <div className="space-y-3 mb-3">
        {quotes.map((quote) => {
          const isAuthor = quote.user_id === currentUser.id;
          // Admins may remove anyone's quote; only the author may correct one.
          const canDelete = isAuthor || currentUser.is_admin;

          return (
            <div
              key={quote.id}
              className="bg-paper-50 rounded-xl p-3 border border-paper-100 dark:bg-paper-900 dark:border-paper-800"
            >
              {editingId === quote.id ? (
                <QuoteEditForm
                  quote={quote}
                  onSave={(fields) => {
                    onEdit(quote.id, fields);
                    setEditingId(null);
                  }}
                  onCancel={() => setEditingId(null)}
                />
              ) : (
                <QuoteView
                  quote={quote}
                  isAuthor={isAuthor}
                  canDelete={canDelete}
                  onStartEdit={() => setEditingId(quote.id)}
                  onRemove={() => onRemove(quote.id)}
                />
              )}
            </div>
          );
        })}
      </div>

      <form onSubmit={submit} className="space-y-2">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={TEXT_MAX}
          placeholder={t("quotes.placeholder")}
          aria-label={t("quotes.addLabel")}
          className={`${FIELD_CLASS} resize-none`}
        />
        <div className="flex gap-2">
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={PAGE_MAX}
            value={page}
            onChange={(event) => setPage(event.target.value)}
            placeholder={t("quotes.pagePlaceholder")}
            aria-label={t("quotes.pageLabel")}
            className={`${FIELD_CLASS} w-28`}
          />
          {/* A textarea, matching the edit form. `<input type="text">` cannot
              hold a newline at all, so a remark typed here could only gain its
              line breaks afterwards, in a different control, on a field that
              renders as a paragraph. */}
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={1}
            maxLength={NOTE_MAX}
            placeholder={t("quotes.notePlaceholder")}
            aria-label={t("quotes.noteLabel")}
            className={`${FIELD_CLASS} flex-1 resize-none`}
          />
          <button
            type="submit"
            disabled={isAdding || !text.trim()}
            // Named rather than left as the bare "Add" the button reads,
            // because the notes form above it has an Add button too. The label
            // still contains the visible word, which is what keeps voice
            // control working (WCAG 2.5.3, label in name).
            aria-label={t("quotes.addButton")}
            className="px-4 py-2 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-sm font-semibold shrink-0 transition-colors"
          >
            {t("common.add")}
          </button>
        </div>
      </form>
    </div>
  );
}
