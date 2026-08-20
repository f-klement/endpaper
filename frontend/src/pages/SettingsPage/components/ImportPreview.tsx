import type { ImportPreviewOut } from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";

interface ImportPreviewProps {
  preview: ImportPreviewOut;
}

/**
 * The fields worth showing, in the order somebody checks them.
 *
 * `keys` is a list because one field can be filled from either of two
 * columns. A file carrying only an ISBN-10 column was reported as having no
 * ISBN at all, which is the opposite of reassuring.
 */
const FIELDS: { keys: string[]; label: MessageKey }[] = [
  { keys: ["title"], label: "import.fieldTitle" },
  { keys: ["author"], label: "import.fieldAuthor" },
  { keys: ["isbn13", "isbn"], label: "import.fieldIsbn" },
  { keys: ["status"], label: "import.fieldStatus" },
  { keys: ["rating"], label: "import.fieldRating" },
  { keys: ["date_read"], label: "import.fieldDateRead" },
  { keys: ["publisher"], label: "import.fieldPublisher" },
  { keys: ["year"], label: "import.fieldYear" },
  { keys: ["pages"], label: "import.fieldPages" },
  { keys: ["format"], label: "import.fieldFormat" },
  { keys: ["tags"], label: "import.fieldTags" },
];

/** The header that filled a field, from whichever of its keys matched. */
function columnFor(
  mapping: Record<string, string | null>,
  keys: string[],
): string | null {
  for (const key of keys) {
    if (mapping[key]) return mapping[key];
  }
  return null;
}

/**
 * What the file turned out to be, before anything is written.
 *
 * Two halves, because two different things go wrong. The mapping catches a
 * column read as the wrong field, which is silent and ruins the whole import.
 * The sample rows catch a file read with the wrong delimiter or encoding,
 * which is loud and obvious the moment anybody looks at one row.
 */
export default function ImportPreview({ preview }: ImportPreviewProps) {
  const { t } = useTranslation();
  const unmatched = FIELDS.filter(
    ({ keys }) => !columnFor(preview.mapping, keys),
  );
  // The schema defaults it to an empty list, but the generated type keeps it
  // optional, so the page does not have to care which.
  const rows = preview.rows ?? [];

  return (
    <div className="rounded-xl border border-paper-200 bg-paper-50 p-3 text-sm dark:border-paper-700 dark:bg-paper-900">
      <p className="font-medium text-paper-800 dark:text-paper-100">
        {t("import.previewTitle", { count: preview.total_rows })}
      </p>

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {FIELDS.map(({ keys, label }) => {
          const column = columnFor(preview.mapping, keys);
          return column ? (
            <div key={label} className="contents">
              <dt className="text-paper-600 dark:text-paper-400">{t(label)}</dt>
              <dd className="truncate font-medium text-paper-700 dark:text-paper-200">
                {column}
              </dd>
            </div>
          ) : null;
        })}
      </dl>

      {unmatched.length > 0 && (
        <p className="mt-2 text-xs text-paper-600 dark:text-paper-400">
          {t("import.notFound", {
            fields: unmatched.map(({ label }) => t(label)).join(", "),
          })}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-paper-200 pt-2 text-xs dark:border-paper-700">
          {rows.map((row, index) => (
            // The index keys these: two rows of one export can be the same
            // book on two shelves, and a title is not a key.
            <li key={index} className="truncate text-paper-600 dark:text-paper-300">
              {row.title}
              {row.author && (
                <span className="text-paper-600 dark:text-paper-400">
                  {" "}
                  {t("book.by", { author: row.author })}
                </span>
              )}
              {/* The status and the ISBN are here because they are what a
                  wrong column looks like. A title list looks correct whether
                  the status came from the shelf or from the tag column. */}
              {row.status && (
                <span className="ml-1 text-accent-700 dark:text-accent-300">
                  {row.status}
                </span>
              )}
              {row.isbn && (
                <span className="ml-1 text-paper-600 dark:text-paper-400">
                  {row.isbn}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {preview.skipped > 0 && (
        <p className="mt-2 text-xs text-paper-600 dark:text-paper-400">
          {t("import.skipped", { count: preview.skipped })}
        </p>
      )}
    </div>
  );
}
