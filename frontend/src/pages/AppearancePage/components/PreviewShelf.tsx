import type { BookOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import BookCard from "../../components/BookCard";

interface PreviewShelfProps {
  /** The reader's own, from the cache. Never fetched, and never invented. */
  books: BookOut[];
}

/**
 * Two of the reader's own book cards, on the page they will be on.
 *
 * The picker's honest preview is the page itself: the wallpaper is painted on
 * the body, so it is already behind this and everything else on the screen.
 * What a swatch cannot show is the palette on real content, which is what these
 * two cards are for, and they are the reader's own books rather than invented
 * ones because sample content is not the page.
 *
 * Where the cache holds nothing, this says so instead of drawing a placeholder
 * book. A fake book in a preview is exactly what it exists to avoid. That case
 * is not rare: the cache is evicted after five idle minutes, so a reload on
 * this route reaches it with a full library.
 */
export default function PreviewShelf({ books }: PreviewShelfProps) {
  const { t } = useTranslation();

  if (books.length === 0) {
    return (
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("appearance.previewEmpty")}
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 max-w-xs">
      {books.map((book) => (
        <BookCard key={book.id} book={book} />
      ))}
    </div>
  );
}
