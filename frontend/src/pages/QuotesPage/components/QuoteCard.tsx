import { Link } from "react-router-dom";

import type { QuoteWithBookOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { CoverImage } from "../../components";

interface QuoteCardProps {
  quote: QuoteWithBookOut;
}

/**
 * One saved passage, with the book it came out of.
 *
 * The passage is the heading here, not the book: this page exists to be read
 * down, and a list whose loudest element is a repeated title reads as a book
 * list with quotes attached rather than the other way round. The book is the
 * footer, and it is the link, because "what was this from" is the question a
 * quote raises and following it is the answer.
 */
export default function QuoteCard({ quote }: QuoteCardProps) {
  const { t } = useTranslation();

  return (
    <article className="bg-paper-0 rounded-xl p-4 border border-paper-200 dark:bg-paper-900 dark:border-paper-800">
      {/* `whitespace-pre-line` because a passage of verse is line breaks. */}
      <blockquote className="border-l-2 border-accent-300 pl-3 text-sm text-paper-800 leading-relaxed whitespace-pre-line dark:border-accent-500 dark:text-paper-100">
        {quote.text}
      </blockquote>

      {quote.note != null && (
        <p className="text-sm text-paper-600 mt-2 dark:text-paper-400">
          {quote.note}
        </p>
      )}

      <Link
        to={`/book/${quote.book_id}`}
        className="flex items-center gap-3 mt-3 pt-3 border-t border-paper-100 group dark:border-paper-800"
      >
        <CoverImage
          src={quote.book_cover_url}
          alt=""
          className="w-8 h-11 shrink-0 rounded bg-paper-100 dark:bg-paper-800"
          loading="lazy"
        />
        <span className="min-w-0">
          <span className="block text-sm font-medium text-paper-800 truncate group-hover:text-accent-700 dark:text-paper-100 dark:group-hover:text-accent-300">
            {quote.book_title}
          </span>
          <span className="block text-xs text-paper-600 truncate dark:text-paper-400">
            {[
              quote.book_author,
              quote.page != null ? t("quotes.onPage", { page: quote.page }) : null,
              quote.author?.username,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
      </Link>
    </article>
  );
}
