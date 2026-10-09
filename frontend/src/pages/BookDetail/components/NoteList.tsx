import { useId, useState, type FormEvent } from "react";

import type { NoteOut, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { Icon } from "../../../components";

export function formatDate(iso: string, locale?: string): string {
  return new Date(iso).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

interface NoteListProps {
  notes: NoteOut[];
  currentUser: UserOut;
  isAdding: boolean;
  onAdd: (content: string) => void;
  onEdit: (noteId: number, content: string) => void;
  onRemove: (noteId: number) => void;
}

/**
 * Reader notes on a book. Used only by BookDetail.
 *
 * ## Two states, and the member is told about both at two different moments
 *
 * `is_private` true means visible to the note's author and to nobody else, an
 * admin included; false, which is every note written through this form, means
 * visible to whoever can see the book.
 *
 * **The two tellings land at different moments, which is what makes them two
 * and not a repetition.** The marker is read-time: it answers which of these
 * rows the rest of the library cannot see, and it is on the private rows
 * only, since false is the default and a marker on every row is a marker that
 * means nothing. The line above the form is write-time, and it is the only
 * one of the pair that arrives before the act it is about. A member who
 * believes a note they are typing is private has already published it by the
 * time any marker could correct them, and a marker cannot reach a member who
 * holds no private note to contrast against.
 *
 * **Neither is a control, and that is deliberate.** `NoteCreate` carries no
 * `is_private`, so a note written here is shared and there is no route that
 * would change one afterwards. A marker drawn as a pressable pill, or a line
 * phrased as a setting, would promise a thing this app cannot do.
 */
export default function NoteList({
  notes,
  currentUser,
  isAdding,
  onAdd,
  onEdit,
  onRemove,
}: NoteListProps) {
  const { t, locale } = useTranslation();
  // `useId`, not a literal: a literal's uniqueness rests on this component
  // being rendered once per page, which is a docstring sentence rather than a
  // rule. A second instance would point both textareas at the first hint, and
  // a duplicate id breaks `aria-describedby` silently, in the one place whose
  // whole job is telling a member something before they act.
  const hintId = useId();
  const [draft, setDraft] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    setDraft("");
  }

  function saveEdit(noteId: number) {
    const trimmed = editDraft.trim();
    if (!trimmed) return;
    onEdit(noteId, trimmed);
    setEditingId(null);
  }

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-3 dark:text-paper-200">
        {t("notes.title")}
      </p>

      {notes.length === 0 && (
        <p className="text-sm text-paper-600 italic mb-3 dark:text-paper-400">
          {t("notes.none")}
        </p>
      )}

      <div className="space-y-3 mb-3">
        {notes.map((note) => {
          const isAuthor = note.user_id === currentUser.id;
          // Admins may remove anyone's note; only the author may reword one.
          const canDelete = isAuthor || currentUser.is_admin;

          return (
            <div
              key={note.id}
              className="bg-paper-50 rounded-xl p-3 border border-paper-100 dark:bg-paper-900 dark:border-paper-800"
            >
              {editingId === note.id ? (
                <div>
                  <textarea
                    value={editDraft}
                    onChange={(event) => setEditDraft(event.target.value)}
                    rows={3}
                    aria-label={t("notes.editLabel")}
                    className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm resize-none dark:border-paper-700"
                  />
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => saveEdit(note.id)}
                      className="px-3 py-1.5 bg-accent-fill hover:bg-accent-fill-hover text-on-accent rounded-lg text-xs font-medium"
                    >
                      {t("common.save")}
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="px-3 py-1.5 border border-paper-200 text-paper-600 rounded-lg text-xs font-medium hover:bg-paper-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
                    >
                      {t("common.cancel")}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className="text-sm text-paper-700 leading-relaxed dark:text-paper-200">
                    {note.content}
                  </p>
                  <div className="flex items-center justify-between gap-2 mt-2">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-paper-600 dark:text-paper-400">
                      <span>
                        {note.author?.username} ·{" "}
                        {formatDate(note.created_at, locale)}
                      </span>
                      {/* Read off the server's answer, never inferred from
                          authorship. `note_visible_to` narrows every route
                          that returns a note, so a `true` reaching a client
                          is that client's own row and the first person
                          wording holds; deriving it here from `isAuthor`
                          instead would mark a member's shared notes private
                          and say so in the first person, which is the
                          surprise this marker exists to stop, printed. */}
                      {note.is_private && (
                        <span
                          // Ink and a lock, with no fill behind them. A tinted
                          // chip is what this started as, and it fails twice:
                          // `paper-100` on the card measures 1.05 (everforest)
                          // to 1.11 (nord) in light and `paper-800` 1.17
                          // (nord) to 1.38 (catppuccin) in dark, across all
                          // ten themes, so the boundary carrying the meaning
                          // sits far under the 3:1 of WCAG 1.4.11; and a
                          // filled pill is the one thing here that reads as
                          // pressable, which this marker must not, there
                          // being no route that would change a note's
                          // privacy.
                          //
                          // A rung darker than the metadata beside it, which
                          // is what separates it without a fill: 5.30
                          // (kanagawa) to 8.80 light and 7.00 (everforest) to
                          // 11.64 dark on the card, better in every theme
                          // than the chip it replaces.
                          className="inline-flex items-center gap-1 font-medium text-paper-700 dark:text-paper-300"
                        >
                          <Icon name="lock" className="w-3 h-3" />{" "}
                          {t("notes.privateBadge")}
                        </span>
                      )}
                    </span>
                    {canDelete && (
                      <div className="flex gap-2">
                        {isAuthor && (
                          <button
                            onClick={() => {
                              setEditingId(note.id);
                              setEditDraft(note.content);
                            }}
                            className="text-xs text-accent-600 hover:text-accent-800 dark:text-accent-400 dark:hover:text-accent-300"
                          >
                            {t("common.edit")}
                          </button>
                        )}
                        <button
                          onClick={() => onRemove(note.id)}
                          // `danger-300` is the tint tier and is not ink on a
                          // light card: a delete control nobody could read
                          // until they hovered it. The dark hover needs saying
                          // too, because the ramp runs the other way there and
                          // `danger-600` is nearly the dark card itself, so
                          // repairing only the resting state would leave the
                          // control going illegible the moment it is pointed
                          // at. Both rungs are recomputed over every palette by
                          // `tests/theme/palettes.test.ts::the rungs a delete
                          // control cannot rest on`; no band is quoted here.
                          className="text-xs text-danger-500 hover:text-danger-600 dark:text-danger-300 dark:hover:text-danger-100"
                        >
                          {t("common.delete")}
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* Above the form, not under it: it is what the member needs before
          they decide what to write, and `aria-describedby` puts it in the
          same order for a reader who never sees the layout. */}
      <p
        id={hintId}
        className="text-xs text-paper-600 mb-2 dark:text-paper-400"
      >
        {t("notes.sharedHint")}
      </p>

      <form onSubmit={submit} className="flex gap-2">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={2}
          placeholder={t("notes.placeholder")}
          aria-label={t("notes.addLabel")}
          aria-describedby={hintId}
          className="flex-1 px-3 py-2 rounded-lg border border-paper-200 text-sm resize-none dark:border-paper-700"
        />
        <button
          type="submit"
          disabled={isAdding || !draft.trim()}
          className="px-4 py-2 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-sm font-semibold self-end transition-colors"
        >
          {t("common.add")}
        </button>
      </form>
    </div>
  );
}
