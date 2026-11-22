import { Link, useParams } from "react-router-dom";

import {
  TagCategory,
  type PublicBookOut,
  type PublicClassificationOut,
} from "../../api/generated/model";
import { EmptyState, ErrorState, Spinner } from "../../components";
import { KIND_LABEL, headingKind } from "../../lib/classificationLabels";
import {
  tagName,
  useTranslation,
  type MessageKey,
  type Translate,
} from "../../i18n";
import { Page } from "../components";
import CoverImage from "../components/CoverImage";
import { FORMAT_LABELS, TAG_PILL_CLASSES, originLabel } from "../types";
import PublicShell from "./components/PublicShell";
import { usePublicBook, type UsePublicBookResult } from "./hooks";

/**
 * The bibliographic facts a record carries, as label and value pairs in the
 * order the page lists them. A fact the record does not carry is left out
 * rather than shown empty, except the record's source, which is unknown
 * rather than absent. So is a year of zero: the schema's MIN_YEAR is 1,
 * so a 0 is not a year.
 *
 * Exported so its own test can state the rule without rendering a page.
 */
export function publicFacts(
  book: PublicBookOut,
  t: Translate,
): [string, string][] {
  const candidates: [MessageKey, string | null | undefined][] = [
    ["public.fact.isbn", book.isbn],
    ["public.fact.publisher", book.publisher],
    ["public.fact.year", book.year ? String(book.year) : null],
    ["public.fact.language", book.language],
    ["public.fact.pages", pagesFact(book.page_count)],
    ["public.fact.format", book.format ? t(FORMAT_LABELS[book.format]) : null],
    ["public.fact.series", seriesFact(book)],
    // Always present: a row older than the column reads as unknown, which is
    // a fact about the record rather than an absent one.
    ["origin.label", t(originLabel(book.record_origin))],
  ];
  const facts: [string, string][] = [];
  for (const [key, value] of candidates) {
    if (value) facts.push([t(key), value]);
  }
  return facts;
}

/** The page count as text, a zero included, or `null` when there is none. */
function pagesFact(count: number | null | undefined): string | null {
  return count === null || count === undefined ? null : String(count);
}

/** The series name, followed by its number when the record carries one. */
function seriesFact(book: PublicBookOut): string | null {
  if (!book.series_name) return null;
  return book.series_index === null || book.series_index === undefined
    ? book.series_name
    : `${book.series_name} ${book.series_index}`;
}

/**
 * One published record, read by somebody with no account.
 *
 * **Every field on screen comes off `PublicBookOut` and nothing is fetched
 * beside it.** There is no loan, no reading status, no note and no member,
 * because the payload carries none of those: the column boundary is on the
 * server, and this page could not draw them if it tried.
 *
 * A book that is not published, does not exist, or is in the trash is the same
 * "not found", which is what the server answers and what this must not
 * undo: telling the three apart is exactly what a stranger counting through ids
 * would use to learn how many private books a library holds.
 *
 * The bibliographic facts are a `<dl>` rather than rows of styled `<div>`s: a
 * screen reader then reads "ISBN, 978..." as a pair instead of two unrelated
 * strings, which is the difference between a catalogue record and a wall of
 * text.
 */
export default function PublicBookPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const bookId = Number(id);
  const { book, isLoading, error, isMissing } = usePublicBook(bookId);

  if (isLoading) {
    return (
      <PublicShell>
        <Spinner label={t("common.loading")} />
      </PublicShell>
    );
  }

  if (isMissing || !book) {
    return <MissingRecord error={error} isMissing={isMissing} />;
  }

  return (
    <PublicShell>
      <Page width="narrow">
        <Link
          to="/catalogue"
          className="inline-block mb-4 text-sm font-medium text-accent-700 dark:text-accent-300"
        >
          {t("public.backToCatalogue")}
        </Link>
        <RecordHeading book={book} />
        <FactList facts={publicFacts(book, t)} />
        <ClassificationList classifications={book.classifications} />
        <TagList tags={book.tags} />
        <Description description={book.description} />
      </Page>
    </PublicShell>
  );
}

/**
 * No record to draw: the server's "not found", or a failure that is not one.
 * The three kinds of "not found" stay one, as the page's docstring says.
 */
function MissingRecord({
  error,
  isMissing,
}: Pick<UsePublicBookResult, "error" | "isMissing">) {
  const { t } = useTranslation();
  return (
    <PublicShell>
      <Page width="narrow">
        {error && !isMissing ? (
          <ErrorState error={error} />
        ) : (
          <EmptyState
            icon="book"
            title={t("book.notFound")}
            hint={
              <Link
                to="/catalogue"
                className="text-accent-700 dark:text-accent-300"
              >
                {t("public.backToCatalogue")}
              </Link>
            }
          />
        )}
      </Page>
    </PublicShell>
  );
}

/** The cover, the title, the subtitle and the credit line. */
function RecordHeading({ book }: { book: PublicBookOut }) {
  const { t } = useTranslation();
  // `?? []` here, as `BookCard` does for `book.tags`, and `?.length` on the
  // other collections, because the generated types make a field with a server
  // side default optional.
  const credit = (book.authors ?? []).join(", ");
  return (
    <div className="flex gap-4 mb-6">
      <CoverImage
        src={book.cover_url}
        alt=""
        className="w-28 shrink-0 aspect-[2/3] rounded-xl bg-paper-100 dark:bg-paper-800 object-cover"
      />
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-paper-900 dark:text-paper-100">
          {book.title}
        </h1>
        {book.subtitle && (
          <p className="text-paper-700 dark:text-paper-300">{book.subtitle}</p>
        )}
        {credit && (
          <p className="mt-1 text-sm text-paper-600 dark:text-paper-400">
            {t("book.by", { author: credit })}
          </p>
        )}
      </div>
    </div>
  );
}

function FactList({ facts }: { facts: [string, string][] }) {
  if (facts.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm mb-6">
      {facts.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-paper-600 dark:text-paper-400">{label}</dt>
          <dd className="text-paper-900 dark:text-paper-100">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The call number and the Classification, which are what library mode is for
 * and the one addition the public record makes over a plain bibliographic one.
 */
function ClassificationList({
  classifications,
}: {
  classifications: PublicBookOut["classifications"];
}) {
  const { t } = useTranslation();
  if (!classifications?.length) return null;
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100 mb-2">
        {t("public.classifications")}
      </h2>
      {/* `role="list"` beside `list-none`: Safari and VoiceOver drop
          list semantics from a `ul` whose `list-style` is none. */}
      <ul role="list" className="space-y-1 text-sm list-none p-0">
        {classifications.map((entry) => (
          <ClassificationEntry
            key={`${entry.scheme}-${entry.number}`}
            entry={entry}
          />
        ))}
      </ul>
    </section>
  );
}

function ClassificationEntry({ entry }: { entry: PublicClassificationOut }) {
  const { t } = useTranslation();
  // A carrier and a content type arrive in the same MARC field as a subject
  // and are not one. Unmarked, a public record says this book is about CD-ROM.
  const kind = KIND_LABEL[headingKind(entry.kind)];
  return (
    <li className="text-paper-700 dark:text-paper-300">
      <span className="font-medium uppercase text-xs text-paper-600 dark:text-paper-400 mr-2">
        {entry.scheme}
      </span>
      <span className="tabular-nums">{entry.number}</span>
      {entry.label && <span className="ml-2">{entry.label}</span>}
      {kind && (
        <span className="ml-2 text-xs text-paper-600 dark:text-paper-400">
          {t(kind)}
        </span>
      )}
    </li>
  );
}

function TagList({ tags }: { tags: PublicBookOut["tags"] }) {
  const { t, locale } = useTranslation();
  if (!tags?.length) return null;
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100 mb-2">
        {t("library.tags")}
      </h2>
      <ul role="list" className="flex flex-wrap gap-1.5 list-none p-0">
        {tags.map((tag) => (
          <li
            key={tag.id}
            className={`text-xs px-2 py-0.5 rounded-full ${TAG_PILL_CLASSES[tag.category ?? TagCategory.custom]}`}
          >
            {tagName(tag, locale)}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Description({
  description,
}: {
  description: PublicBookOut["description"];
}) {
  const { t } = useTranslation();
  if (!description) return null;
  return (
    <section>
      <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100 mb-2">
        {t("book.description")}
      </h2>
      <p className="text-sm text-paper-700 whitespace-pre-line dark:text-paper-300">
        {description}
      </p>
    </section>
  );
}
