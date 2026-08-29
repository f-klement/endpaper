import { Link, useParams } from "react-router-dom";

import { TagCategory } from "../../api/generated/model";
import { EmptyState, ErrorState, Spinner } from "../../components";
import { tagName, useTranslation } from "../../i18n";
import { Page } from "../components";
import CoverImage from "../components/CoverImage";
import { FORMAT_LABELS, TAG_PILL_CLASSES } from "../types";
import PublicShell from "./components/PublicShell";
import { usePublicBook } from "./hooks";

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
  const { t, locale } = useTranslation();
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

  // `?? []` on every collection, because the generated types make a field
  // with a server side default optional. Same guard `BookCard` applies to
  // `book.tags`.
  const credit = (book.authors ?? []).join(", ");
  const classifications = book.classifications ?? [];
  const tags = book.tags ?? [];
  const facts: [string, string][] = [];
  if (book.isbn) facts.push([t("public.fact.isbn"), book.isbn]);
  if (book.publisher) facts.push([t("public.fact.publisher"), book.publisher]);
  if (book.year !== null && book.year !== undefined) {
    facts.push([t("public.fact.year"), String(book.year)]);
  }
  if (book.language) facts.push([t("public.fact.language"), book.language]);
  if (book.page_count !== null && book.page_count !== undefined) {
    facts.push([t("public.fact.pages"), String(book.page_count)]);
  }
  if (book.format) {
    facts.push([t("public.fact.format"), t(FORMAT_LABELS[book.format])]);
  }
  if (book.series_name) {
    facts.push([
      t("public.fact.series"),
      book.series_index === null || book.series_index === undefined
        ? book.series_name
        : `${book.series_name} ${book.series_index}`,
    ]);
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
              <p className="text-paper-700 dark:text-paper-300">
                {book.subtitle}
              </p>
            )}
            {credit && (
              <p className="mt-1 text-sm text-paper-600 dark:text-paper-400">
                {t("book.by", { author: credit })}
              </p>
            )}
          </div>
        </div>

        {facts.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm mb-6">
            {facts.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-paper-600 dark:text-paper-400">{label}</dt>
                <dd className="text-paper-900 dark:text-paper-100">{value}</dd>
              </div>
            ))}
          </dl>
        )}

        {/* The call number and the Classification, which are what library mode
            is for and the one addition the public record makes over a plain
            bibliographic one. */}
        {classifications.length > 0 && (
          <section className="mb-6">
            <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100 mb-2">
              {t("public.classifications")}
            </h2>
            {/* `role="list"` beside `list-none`: Safari and VoiceOver drop
                list semantics from a `ul` whose `list-style` is none. */}
            <ul role="list" className="space-y-1 text-sm list-none p-0">
              {classifications.map((entry) => (
                <li
                  key={`${entry.scheme}-${entry.number}`}
                  className="text-paper-700 dark:text-paper-300"
                >
                  <span className="font-medium uppercase text-xs text-paper-600 dark:text-paper-400 mr-2">
                    {entry.scheme}
                  </span>
                  <span className="tabular-nums">{entry.number}</span>
                  {entry.label && <span className="ml-2">{entry.label}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {tags.length > 0 && (
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
        )}

        {book.description && (
          <section>
            <h2 className="text-sm font-semibold text-paper-900 dark:text-paper-100 mb-2">
              {t("book.description")}
            </h2>
            <p className="text-sm text-paper-700 whitespace-pre-line dark:text-paper-300">
              {book.description}
            </p>
          </section>
        )}
      </Page>
    </PublicShell>
  );
}
