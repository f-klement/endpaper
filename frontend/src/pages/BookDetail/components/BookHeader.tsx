import { useRef, type ChangeEvent } from "react";
import { Link } from "react-router-dom";

import type { BookOut } from "../../../api/generated/model";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";
import { searchUrl } from "../../../lib/goodreads";
import { CoverImage } from "../../components";
import { Button, Icon } from "../../../components";

interface BookHeaderProps {
  book: BookOut;
  isRefreshing: boolean;
  refreshError: unknown;
  /** Rendered only when an admin has switched the Goodreads links on. */
  showGoodreadsLink: boolean;
  onBack: () => void;
  onUploadCover: (file: File) => void;
  onRefreshMetadata: () => void;
}

/** Cover, title, metadata chips and the refresh control. */
export default function BookHeader({
  book,
  isRefreshing,
  refreshError,
  showGoodreadsLink,
  onBack,
  onUploadCover,
  onRefreshMetadata,
}: BookHeaderProps) {
  const { t } = useTranslation();

  // "by {author}" with each name a link, without breaking the phrase into
  // fragments a translator would have to reassemble. German does not keep
  // English word order, so the catalogue holds the whole sentence and the
  // placeholder is located by rendering it with a sentinel and splitting
  // there: whatever sits on either side of the name stays where the
  // translation put it. A catalogue that lost the placeholder degrades to the
  // phrase followed by the names rather than to an exception.
  const [byPrefix, bySuffix = ""] = t("book.by", { author: "\u0000" }).split(
    "\u0000",
  );
  const coverInput = useRef<HTMLInputElement>(null);

  function handleCover(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onUploadCover(file);
    event.target.value = "";
  }

  return (
    <>
      <div className="relative">
        {/* Never absent, whatever happens to the image. The back button below
            is positioned against this box, and when a failed cover removed
            itself from the flow the box collapsed to nothing and the button
            landed on the title. */}
        <CoverImage
          src={book.cover_url}
          alt={book.title}
          className="w-full h-56 object-cover object-top bg-gradient-to-br from-accent-100 to-accent-200"
        />

        {/* Both of these are the shared Button rather than their own classes,
            and the reason is not tidiness. They used to say `bg-paper-0/90`
            with `dark:text-paper-200`, and `paper-0` is the top surface in
            every palette in **both** modes: it is the one paper token that is
            never redefined under `.dark`, which is why every dark call site in
            this app spells `dark:bg-paper-900` instead. So the dark variant
            moved the ink and left the pill white, and the label measured
            1.26:1 against the 4.5:1 WCAG 1.4.3 asks. `secondary` carries the
            matching pair (14.25:1 light, 15.79:1 dark) because the fill and
            the foreground are stated together, which is the same rule the
            accent fill tokens exist for.

            Only position is passed through `className`. Anything that
            re-spells a utility the variant already sets (the radius, the
            shadow, the height) would be two classes for one property, and
            which of them wins is decided by Tailwind's output order rather
            than by the order they are written in here. */}
        <Button
          variant="secondary"
          size="sm"
          onClick={onBack}
          icon={<Icon name="chevron" className="h-3.5 w-3.5 rotate-180" />}
          className="absolute top-3 left-3"
        >
          {t("common.back")}
        </Button>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => coverInput.current?.click()}
          icon={<Icon name="camera" className="h-3.5 w-3.5" />}
          className="absolute bottom-3 right-3"
        >
          {t("book.uploadCover")}
        </Button>
        <input
          ref={coverInput}
          type="file"
          accept="image/*"
          className="hidden"
          aria-label={t("book.uploadCover")}
          onChange={handleCover}
        />
      </div>

      <div>
        <h1 className="text-xl font-bold leading-tight">{book.title}</h1>
        {book.subtitle && (
          <p className="text-paper-600 mt-0.5 dark:text-paper-300">
            {book.subtitle}
          </p>
        )}
        {book.series_name && (
          <Link
            to={`/?series=${encodeURIComponent(book.series_name)}&sort=series`}
            className="inline-block text-sm text-accent-700 hover:text-accent-800 mt-1 dark:text-accent-400 dark:hover:text-accent-300"
          >
            {book.series_index != null
              ? t("series.partOf", {
                  name: book.series_name,
                  index: book.series_index,
                })
              : t("series.partOfUnnumbered", { name: book.series_name })}
          </Link>
        )}
        {book.author && (
          <p className="text-paper-600 text-sm mt-1 dark:text-paper-400">
            {/* The credit line as printed, with each name inside it a link.
                The split comes from the payload (`authors`) rather than from a
                comma in here: the separator rule belongs to the server, which
                is also where `categories` proves how easy it is to get wrong.
                A book whose credit line is one name still renders the line, so
                the text on screen is what the cover says either way. */}
            {byPrefix}
            {(book.authors ?? [book.author]).map((name, index) => (
              <span key={name}>
                {index > 0 && ", "}
                <Link
                  to={`/?author=${encodeURIComponent(name)}`}
                  className="hover:text-accent-700 hover:underline dark:hover:text-accent-400"
                >
                  {name}
                </Link>
              </span>
            ))}
            {bySuffix}
          </p>
        )}

        <div className="flex flex-wrap gap-2 mt-2">
          {book.publisher && (
            <span className="text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded dark:text-paper-400 dark:bg-paper-800">
              {book.publisher}
            </span>
          )}
          {book.year && (
            <span className="text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded dark:text-paper-400 dark:bg-paper-800">
              {book.year}
            </span>
          )}
          {book.page_count != null && (
            <span className="text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded dark:text-paper-400 dark:bg-paper-800">
              {t("book.pages", { count: book.page_count })}
            </span>
          )}
          {book.language && (
            <span className="text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded uppercase dark:text-paper-400 dark:bg-paper-800">
              {book.language}
            </span>
          )}
          {book.location && (
            <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded dark:text-amber-300 dark:bg-amber-950">
              {book.location}
            </span>
          )}
          {book.isbn && (
            <span className="text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded dark:text-paper-400 dark:bg-paper-800">
              {t("book.isbn", { isbn: book.isbn })}
            </span>
          )}
        </div>

        {/* The page's actions, together and labelled.
            The Goodreads link used to be a 14 pixel chain-link glyph at 60%
            opacity wedged beside the title, with no text, and it could not be
            found: the flag that gates it defaults to on, so the styling was the
            whole of the problem. It is still visually secondary, because it
            leaves this app for a third party, but secondary is not invisible.
            `paper-600` is the muted step the palette contract already holds to
            4.5:1 on the page, and it carries its own words. */}
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          {/* Refreshing needs an ISBN to look anything up. Searching Goodreads
              does not, so the two are gated separately. */}
          {book.isbn && (
            <button
              onClick={onRefreshMetadata}
              disabled={isRefreshing}
              className="text-xs text-accent-600 hover:text-accent-800 disabled:text-accent-300 transition-colors dark:text-accent-400 dark:hover:text-accent-300 dark:disabled:text-accent-600"
            >
              {isRefreshing ? t("book.refreshing") : t("book.refreshMetadata")}
            </button>
          )}

          {showGoodreadsLink && (
            <a
              href={searchUrl(book.title, book.isbn)}
              target="_blank"
              // noreferrer as well as noopener: the target is a third party and
              // has no business knowing which page linked to it.
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-paper-600 underline-offset-2 transition-colors hover:text-paper-900 hover:underline dark:text-paper-400 dark:hover:text-paper-100"
            >
              <Icon name="link" aria-hidden="true" className="h-3.5 w-3.5" />
              {t("goodreads.lookup")}
            </a>
          )}
        </div>

        {refreshError != null && (
          <p className="text-xs text-danger-500 mt-1 dark:text-danger-300">
            {errorText(refreshError, t("common.somethingWentWrong"), t)}
          </p>
        )}
      </div>
    </>
  );
}
