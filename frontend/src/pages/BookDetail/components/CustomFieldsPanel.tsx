import { useState } from "react";

import type {
  CustomFieldOut,
  CustomFieldValueOut,
} from "../../../api/generated/model";
import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import { safeHref } from "../../../lib/safeHref";

/** Matches `CUSTOM_FIELD_VALUE_MAX` in the backend's models.py.
 *
 * Stated here so the box stops where the API refuses, rather than letting
 * somebody paste a long URL and then answering 422. The server is still the
 * authority: this is a courtesy, not a check. */
const VALUE_MAX = 500;

interface CustomFieldsPanelProps {
  /** Every field the library has defined. */
  definitions: CustomFieldOut[];
  /** Only the ones this book has something in. */
  values: CustomFieldValueOut[];
  isSaving: boolean;
  error: unknown;
  /**
   * Reports per call, so a refusal can be told from a success. See
   * `writeChanged()` below for why the panel needs to know.
   */
  onSave: (
    fieldId: number,
    value: string,
    callbacks: { onSuccess: () => void; onError: () => void },
  ) => void;
}

/**
 * What this library keeps about this book that Endpaper has no column for.
 *
 * **Nothing at all until the library defines a field.** A household that never
 * uses this feature never sees it, which is what an empty panel with an Edit
 * button would fail to do.
 *
 * **A field with no value is absent rather than blank**, which is user story 4
 * and also why editing is a mode rather than a permanently open form: reading
 * a book's page should show what is there, and a column of empty boxes is the
 * opposite of that. Pressing Edit opens every definition, filled or not, which
 * is the only place an empty one can be reached.
 *
 * **A link is rendered from `href`, never from `value`.** The server decides
 * which values are links, on every read rather than on every write, and
 * `safeHref` says why this side checks again before handing the string to an
 * `<a>`.
 */
export default function CustomFieldsPanel({
  definitions,
  values,
  isSaving,
  error,
  onSave,
}: CustomFieldsPanelProps) {
  const { t } = useTranslation();
  const [drafts, setDrafts] = useState<Record<number, string> | null>(null);
  // This panel's own writes, as opposed to `isSaving`, which is the mutation's
  // and goes false between the calls a multi-field save makes.
  const [writing, setWriting] = useState(false);

  // Nothing at all when the library has told this member of no fields,
  // **unless** a request failed: with no definitions the whole panel is
  // absent, so returning early on an error would make a failed fetch
  // invisible rather than quiet.
  //
  // **This cannot hide a value the book holds, and that is a property of the
  // server rather than of this line.** The definitions are scoped to the
  // viewer and the first of the three arms is "a book this viewer can see
  // holds a value in it", so every field on a book that resolved here is in
  // the list by construction. `backend/fields.py` carries the arms.
  if (definitions.length === 0 && error == null) return null;

  const current = new Map(values.map((row) => [row.field_id, row.value]));

  function save(open: Record<number, string>) {
    writeChanged(definitions, current, open, onSave, {
      started: () => setWriting(true),
      landed: () => {
        setWriting(false);
        setDrafts(null);
      },
      refused: () => setWriting(false),
    });
  }

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-2 dark:text-paper-200">
        {t("customFields.title")}
      </p>

      {error != null && <ErrorState error={error} />}

      {drafts === null ? (
        <FieldValues
          values={values}
          onEdit={() => setDrafts(draftsFor(definitions, current))}
        />
      ) : (
        <FieldsEditor
          definitions={definitions}
          drafts={drafts}
          onChange={setDrafts}
          onSave={() => save(drafts)}
          onCancel={() => setDrafts(null)}
          disabled={isSaving || writing}
        />
      )}
    </div>
  );
}

/** One draft per definition, holding what the book has in it or nothing. */
function draftsFor(
  definitions: CustomFieldOut[],
  current: Map<number, string>,
): Record<number, string> {
  return Object.fromEntries(
    definitions.map((field) => [field.id, current.get(field.id) ?? ""]),
  );
}

/**
 * Write what changed, and **keep the editor open if any write is refused**.
 *
 * The server goes out of its way to answer 400 on a url field that does not
 * hold a URL, rather than degrading it to text, so that the member can be
 * told. Closing the editor before the reply arrives threw away the half that
 * makes the message actionable: the error rendered above a closed panel
 * still showing the old value, and the only way forward was to reopen and
 * retype.
 */
function writeChanged(
  definitions: CustomFieldOut[],
  current: Map<number, string>,
  drafts: Record<number, string>,
  onSave: CustomFieldsPanelProps["onSave"],
  report: { started: () => void; landed: () => void; refused: () => void },
) {
  const changed = changedFields(definitions, current, drafts);
  if (changed.length === 0) {
    // Nothing to write is a save that landed, so the editor closes.
    report.landed();
    return;
  }

  report.started();
  const settle = settler(changed.length, report);
  for (const field of changed) {
    onSave(field.id, drafts[field.id] ?? "", {
      onSuccess: () => settle(true),
      onError: () => settle(false),
    });
  }
}

/**
 * The fields whose draft differs from what the book holds, an absent value
 * reading as empty on both sides.
 *
 * Only what changed. Writing every field would send up to MAX_CUSTOM_FIELDS
 * requests to store what is already stored, and each one would invalidate the
 * list again.
 */
function changedFields(
  definitions: CustomFieldOut[],
  current: Map<number, string>,
  drafts: Record<number, string>,
): CustomFieldOut[] {
  return definitions.filter(
    (field) => (drafts[field.id] ?? "") !== (current.get(field.id) ?? ""),
  );
}

/**
 * The callback each of `count` writes settles through: once the last one has,
 * `landed` if every write succeeded and `refused` if any did not.
 *
 * `left` and `ok` are plain closure variables rather than state: every
 * callback belongs to one save, and a `setState` counter would be read stale
 * by the ones that settle in the same tick.
 */
function settler(
  count: number,
  report: { landed: () => void; refused: () => void },
): (succeeded: boolean) => void {
  let left = count;
  let ok = true;
  return (succeeded) => {
    ok = ok && succeeded;
    left -= 1;
    if (left > 0) return;
    if (ok) report.landed();
    else report.refused();
  };
}

/** The book's values as read, with the button that opens the editor. */
function FieldValues({
  values,
  onEdit,
}: {
  values: CustomFieldValueOut[];
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      {values.length === 0 ? (
        <p className="text-sm text-paper-600 italic mb-2 dark:text-paper-400">
          {t("customFields.bookNone")}
        </p>
      ) : (
        <dl className="space-y-1.5 mb-2">
          {values.map((row) => (
            <FieldValue key={row.field_id} row={row} />
          ))}
        </dl>
      )}

      <button
        onClick={onEdit}
        className="text-xs text-accent-600 hover:text-accent-800 dark:text-accent-400 dark:hover:text-accent-300"
      >
        {t("customFields.editButton")}
      </button>
    </>
  );
}

function FieldValue({ row }: { row: CustomFieldValueOut }) {
  const { t } = useTranslation();
  // **The text and the destination have to be one string.** `value` is what
  // a reader sees and `href` is where the tap goes, so a row where they differ
  // is a row that reads as one domain and resolves as another. The server
  // serves `href` only when it equals `value` (`custom_fields.values_on`), and
  // this repeats the test rather than trusting it: the whole reason this
  // module exists is the row the server never wrote.
  //
  // `safeHref` is then run over the value as well as the href, which after
  // the equality test is the same string. Written as two calls anyway, so
  // decoupling them later cannot silently leave one side unchecked.
  const target =
    row.href === row.value && safeHref(row.value) !== undefined
      ? safeHref(row.href)
      : undefined;
  return (
    <div className="flex gap-2 text-sm">
      <dt className="text-paper-600 shrink-0 dark:text-paper-400">
        {row.name}
      </dt>
      <dd className="text-paper-700 break-all dark:text-paper-200">
        {target ? (
          <a
            href={target}
            target="_blank"
            // `noopener` is what stops the opened page reaching back through
            // `window.opener`, and this link goes to a system this app knows
            // nothing about.
            rel="noopener noreferrer"
            title={t("customFields.opensElsewhere")}
            className="text-accent-600 hover:text-accent-800 underline dark:text-accent-400 dark:hover:text-accent-300"
          >
            {row.value}
          </a>
        ) : (
          row.value
        )}
      </dd>
    </div>
  );
}

/** Every definition as a box, filled or not. */
function FieldsEditor({
  definitions,
  drafts,
  onChange,
  onSave,
  onCancel,
  disabled,
}: {
  definitions: CustomFieldOut[];
  drafts: Record<number, string>;
  onChange: (drafts: Record<number, string>) => void;
  onSave: () => void;
  onCancel: () => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      {definitions.map((field) => (
        <label key={field.id} className="block">
          <span className="text-xs text-paper-600 dark:text-paper-400">
            {field.name}
          </span>
          <input
            type="text"
            value={drafts[field.id] ?? ""}
            onChange={(event) =>
              onChange({ ...drafts, [field.id]: event.target.value })
            }
            maxLength={VALUE_MAX}
            placeholder={t("customFields.valuePlaceholder")}
            className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
          />
        </label>
      ))}

      <div className="flex gap-2">
        <button
          onClick={onSave}
          disabled={disabled}
          className="px-3 py-1.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-xs font-medium"
        >
          {t("common.save")}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1.5 border border-paper-200 text-paper-600 rounded-lg text-xs font-medium hover:bg-paper-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
        >
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}
