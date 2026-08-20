import { useState, type FormEvent } from "react";

import type { NoteOut, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

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

/** Reader notes on a book. Used only by BookDetail. */
export default function NoteList({
  notes,
  currentUser,
  isAdding,
  onAdd,
  onEdit,
  onRemove,
}: NoteListProps) {
  const { t, locale } = useTranslation();
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
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-paper-600 dark:text-paper-400">
                      {note.author?.username} ·{" "}
                      {formatDate(note.created_at, locale)}
                    </span>
                    {canDelete && (
                      <div className="flex gap-2">
                        {isAuthor && (
                          <button
                            onClick={() => {
                              setEditingId(note.id);
                              setEditDraft(note.content);
                            }}
                            className="text-xs text-accent-600 hover:text-accent-800"
                          >
                            {t("common.edit")}
                          </button>
                        )}
                        <button
                          onClick={() => onRemove(note.id)}
                          // `danger-300` is the tint tier and measures 1.89:1
                          // on the card in light mode: a delete control nobody
                          // could read until they hovered it. The dark hover
                          // needs saying too, because the ramp runs the other
                          // way there: `danger-600` on the dark card is 1.67
                          // to 2.85 across the seven palettes, so repairing
                          // only the resting state would leave the control
                          // going illegible the moment it is pointed at.
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

      <form onSubmit={submit} className="flex gap-2">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={2}
          placeholder={t("notes.placeholder")}
          aria-label={t("notes.addLabel")}
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
