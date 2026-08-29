import { Link } from "react-router-dom";

import type {
  AuthorOut,
  AuthorWikipediaOut,
} from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { languageName } from "../../../lib/languageName";
import { safeHref } from "../../../lib/safeHref";

/**
 * The pill both of this card's actions wear.
 *
 * **Spelled out here rather than taken from `Button`, and that is a known
 * duplication rather than an oversight.** `Button` renders a `<button>`, and
 * both of these are navigations: one into the library, one out to Wikipedia. An
 * anchor is the correct element for each, and a `<button>` that calls
 * `navigate()` breaks middle click, open in a new tab, and copy link address.
 * Teaching `Button` an `href` mode is the right fix and is a change to a shared
 * component this trio does not own; when it lands, this constant goes.
 *
 * **`Button`'s `secondary` at size `sm`, declaration for declaration**, and the
 * first version of this said so while differing in five: no
 * `active:scale-[0.97]`, no `shadow-[var(--shadow-soft)]`, no
 * `ease-[var(--ease-out-soft)]`, `gap-1.5` where `Button` has `gap-2`, and a
 * transition naming three properties where `Button` names five. The press
 * feedback is the one that shows: `Button`'s own docstring calls its absence
 * most of why the interface felt unfinished. A comment claiming a match is
 * worse than no comment, because it stops the next reader checking.
 *
 * **The four `disabled:` declarations are deliberately absent**, and that is the
 * whole of the remaining difference: an anchor has no disabled state, so
 * `:disabled` never matches and the classes would be dead weight. A link that
 * should not be followed is not rendered, which is what `href &&` does.
 */
const ACTION =
  "inline-flex h-8 items-center justify-center gap-2 rounded-lg px-3 text-xs " +
  "font-medium select-none active:scale-[0.97] " +
  "transition-[background-color,border-color,color,box-shadow,transform] " +
  "duration-150 ease-[var(--ease-out-soft)] " +
  "bg-paper-0 text-paper-800 border border-paper-200 shadow-[var(--shadow-soft)] " +
  "hover:border-paper-300 hover:bg-paper-50 " +
  "dark:bg-paper-900 dark:text-paper-100 dark:border-paper-800 " +
  "dark:hover:bg-paper-800 dark:hover:border-paper-700";

interface AuthorCardProps {
  author: AuthorOut;
  isBusy: boolean;
  isSelected: boolean;
  onToggleSelect: (author: AuthorOut) => void;
  onUndo: (aliasId: number) => void;
  /**
   * Where to read about this person, or undefined for no second button.
   *
   * **Undefined is the ordinary case and is a fact about the shelf, not about
   * the network.** The server returns a row only for an author carrying a
   * confirmed authority identifier, so the button appears exactly where this
   * library has said which person this name means. A Wikidata outage does not
   * remove it: the server answers with the Wikidata item's own page instead,
   * and `language` is then null.
   */
  wikipedia?: AuthorWikipediaOut;
}

/**
 * One person, and what the shelf knows about them. Dumb.
 *
 * The link carries the **name**. The API accepts either that or the key, and
 * resolves a spelling a merge folded away, so neither is more durable than the
 * other: a merge moves the key exactly as it moves the name, and what keeps an
 * old link working is the redirect rather than the shape of what it carries.
 * Given that, the name is the one to send, because it is what the library's
 * filter chip then shows, and a chip reading "Author: j r r tolkien" from this
 * card and "Author: J. R. R. Tolkien" from a book page is the same filter
 * describing itself two ways.
 *
 * The other spellings are shown rather than hidden. They are the reason a
 * merge is ever wanted, and a card that quietly showed one spelling would make
 * the other look like a missing book.
 */
export default function AuthorCard({
  author,
  isBusy,
  isSelected,
  onToggleSelect,
  onUndo,
  wikipedia,
}: AuthorCardProps) {
  const { t, locale } = useTranslation();
  const merged = author.merged ?? [];
  const mergedSpellings = new Set(merged.map((entry) => entry.spelling));
  const others = (author.spellings ?? []).filter(
    (spelling) => spelling !== author.name && !mergedSpellings.has(spelling),
  );

  // **Checked here as well as on the server, and the coupling is the point.**
  // `authority._WIKIPEDIA_ARTICLE` already refuses anything that is not an
  // article URL, so on a healthy response these two agree and this line costs
  // nothing. What it buys is that the agreement is not the only thing standing
  // between a response and an `href`: `safeHref`'s own docstring records that
  // React 19 renders a `javascript:` href silently, and this was the only one
  // of the five `href={` sites in this app taking a URL from a response without
  // it. `undefined` removes the button rather than rendering a dead one.
  const href = wikipedia ? safeHref(wikipedia.url) : undefined;

  // Three labels rather than one, because they say three different things and a
  // reader deserves to know which. `language` null means the link is the
  // Wikidata item, and naming the language when it is not the page's is the
  // owner's rule on #89: a page you cannot read beats an absent button, and a
  // surprise is what makes that feel broken rather than generous.
  const wikipediaLabel = !wikipedia
    ? ""
    : wikipedia.language == null
      ? t("authors.wikidataItem", { name: author.name })
      : wikipedia.language === locale
        ? t("authors.wikipediaOn", { name: author.name })
        : t("authors.wikipediaInOther", {
            name: author.name,
            // The name, not the subdomain: "in fr" reads as a fault. Codes
            // with no name fall back to themselves, and four real Wikipedia
            // codes make `Intl` throw rather than fall back. See
            // `lib/languageName`.
            language: languageName(wikipedia.language, locale),
          });

  return (
    <div className="bg-paper-0 border border-paper-200 rounded-2xl p-4 dark:bg-paper-900 dark:border-paper-700">
      {/* A checkbox rather than a card that selects on click: the card's
          primary action is following the name into the library, and a surface
          that sometimes navigates and sometimes selects is the one interaction
          nobody guesses right. Same reasoning as the library's own grid. */}
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggleSelect(author)}
          aria-label={t("authors.select", { name: author.name })}
          className="mt-1 shrink-0"
        />
        <h2 className="font-semibold text-paper-900 flex-1 min-w-0 dark:text-paper-100">
          {author.name}
        </h2>
      </div>
      <p className="text-xs text-paper-600 mt-0.5 dark:text-paper-400">
        {t("authors.bookCount", { count: author.book_count })}
      </p>

      {others.length > 0 && (
        <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
          {t("authors.alsoSpelled", { spellings: others.join(", ") })}
        </p>
      )}

      {merged.map((entry) => (
        <p
          key={entry.alias_id}
          className="text-xs text-paper-600 mt-1 flex items-center gap-1.5 dark:text-paper-400"
        >
          {t("authors.mergedFrom", { spelling: entry.spelling })}
          {/* Undo is offered per row rather than per author: a person who
              folded three spellings in and got one wrong should not have to
              unpick the other two. */}
          <button
            type="button"
            disabled={isBusy}
            onClick={() => onUndo(entry.alias_id)}
            aria-label={t("authors.undo")}
            title={t("authors.undo")}
            className="opacity-60 hover:opacity-100 disabled:opacity-30 leading-none"
          >
            ×
          </button>
        </p>
      ))}

      {/* Two actions side by side: their titles, and who they were. The second
          is absent for an author nobody has identified, which is the whole of
          why it is safe to offer at all. */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Link
          to={`/?author=${encodeURIComponent(author.name)}`}
          className={ACTION}
        >
          {t("authors.browse")}
        </Link>

        {wikipedia && href && (
          <a
            href={href}
            target="_blank"
            // noreferrer as well as noopener: the target is a third party and
            // has no business knowing which page linked to it. The same rule
            // `BookHeader` applies to its Goodreads link.
            rel="noopener noreferrer"
            // `hreflang` where we know it, because the article may not be in
            // the page's language and a screen reader should switch voice.
            hrefLang={wikipedia.language ?? undefined}
            title={wikipediaLabel}
            aria-label={wikipediaLabel}
            className={ACTION}
          >
            {/* The stylised W of the Wikipedia wordmark, which is a serif
                capital rather than the puzzle globe: the globe is a trademarked
                logo and would be an asset, a licence question and a CSP change.
                Hidden from assistive tech, which reads the label above. */}
            <span
              aria-hidden="true"
              className="font-serif text-sm leading-none"
            >
              W
            </span>
          </a>
        )}
      </div>
    </div>
  );
}
