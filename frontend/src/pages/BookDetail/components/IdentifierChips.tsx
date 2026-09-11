import { BookIdentifierScheme } from "../../../api/generated/model";
import type { BookIdentifierOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import type { MessageKey } from "../../../i18n/en";
import type { Translate } from "../../../i18n";

/**
 * What each store's own scheme is called on screen.
 *
 * **Total over the enum, so a scheme added to the API is a compile error
 * here**, and the reason is not that a partial map would render nothing:
 * `identifier.other` already covers an unnamed scheme, and dropping a member
 * from this table fails `names Google Books for a volume id`. What
 * totality buys is that a new store cannot ship under its own raw token. The
 * enum's spellings are database values, so a member would read `kobo` where
 * every neighbour reads a store's name, and nobody would be asked to choose
 * one. The cost is exactly that: whoever adds a scheme names it in two
 * catalogues, and until they do this file does not compile.
 */
const SCHEME_LABEL: Record<BookIdentifierScheme, MessageKey> = {
  [BookIdentifierScheme.asin]: "identifier.asin",
  [BookIdentifierScheme.google_books]: "identifier.google_books",
};

/**
 * The same table, read by a string rather than by a member of the enum.
 *
 * **This changes nothing the compiler or the browser does, and it is here for
 * the reader.** `api/generated/model` is regenerated from a committed schema,
 * so a scheme the server stores can reach a build that has never heard of it,
 * and the generated type is the older of the two sides saying that cannot
 * happen. Indexed by the enum, `key` is typed as always found and the fallback
 * below reads as dead code somebody should delete. Widening the read types it
 * as what actually arrives.
 *
 * **The fallback itself is guarded and this line is not**: deleting this const
 * keeps every test green, while removing the `identifier.other` branch fails
 * `a scheme this build has no name for`. So do not read it as a guard.
 */
const LABEL_BY_NAME: Partial<Record<string, MessageKey>> = SCHEME_LABEL;

/** One chip's whole sentence, naming the store where this build knows it. */
function chipText(t: Translate, identifier: BookIdentifierOut): string {
  const key = LABEL_BY_NAME[identifier.scheme];
  return key === undefined
    ? t("identifier.other", {
        scheme: identifier.scheme,
        value: identifier.value,
      })
    : t(key, { value: identifier.value });
}

interface IdentifierChipsProps {
  identifiers: BookIdentifierOut[];
  /**
   * Take this identifier off the book. The whole row rather than its id,
   * because the caller asks before removing one and the question names the
   * value: `TagEditor.onDelete` passes a whole tag for the same reason.
   */
  onRemove: (identifier: BookIdentifierOut) => void;
}

/**
 * What a store calls this book, beside the ISBN that names the edition.
 *
 * **Text, not a link, and recording that decision is most of why this is its
 * own file.** An ASIN resolves to a product page and a volume id to a
 * catalogue page, so each of these could have been an anchor. Three things say
 * it should not be:
 *
 * * **The marketplace is not stored and cannot be recovered.** An ASIN names
 *   an edition on the store that issued it, and the same string is a different
 *   book, or no book, on another. `models.BookIdentifier` states that which
 *   store said so is deliberately not kept, and the Kindle reader takes the
 *   number out of a local catalogue that never names one. A host in a URL here
 *   would be a guess, and a wrong guess sends somebody to the wrong edition
 *   rather than to none, which is the worse of the two failures.
 * * **The value is an opaque token whose shape nothing checks.**
 *   `BookIdentifierIn.an_opaque_token` bounds the length and refuses
 *   whitespace, control and formatting characters. It does not ask whether an
 *   ASIN is an ASIN, and `backup.restore` writes through Core past that model
 *   entirely, leaving one CHECK constraint on the column. So the string is
 *   arbitrary visible text, and a URL built from it is a link this app cannot
 *   stand behind.
 * * **Sending a member to a storefront is a deployment's call.** The one
 *   outbound vendor link this app has, the Goodreads lookup, is gated by an
 *   admin setting with its own words in Settings, because leaving the house is
 *   something an admin says yes to. A second one with no gate would be less
 *   consent than the first, granted by a ticket about rendering a field, and
 *   `PublicBookOut` withholds these rows precisely so a shelf does not
 *   announce which stores the house buys from.
 *
 * What text costs is a copy and a paste. What it buys is that no request
 * reaches a vendor because somebody opened their own book page, against a
 * value that until now was reachable only through the API.
 *
 * **In the chip row rather than in a panel of its own**, because the row is
 * where the ISBN is and this is the same kind of fact: a number naming this
 * edition somewhere. A book carrying none renders nothing, which is what every
 * other chip in that row does, so no empty state is needed or wanted. Why it
 * follows the ISBN rather than leading is stated where the ordering is, at the
 * call site in `BookHeader`.
 *
 * **Each chip carries the one control that removes it**, which is the whole of
 * the correction there is: `models.BookIdentifier` refuses to retype a row,
 * because an identifier is a claim about a record in somebody else's file
 * rather than a preference, and that refusal is only sound while the row can
 * be deleted instead. So no chip is editable and every chip is removable.
 *
 * **On the chip rather than in a mode the row enters**, because a row of two
 * is not a list worth a mode: `TagEditor` puts an `×` on each pill for the
 * same reason, and the label names the identifier rather than saying "remove",
 * so the control is distinguishable from its neighbour by screen reader. What
 * is **not** borrowed from that pill is its `inline-flex`, and the comment at
 * the chip says why a tag can afford one and a value of up to 60 unbroken
 * characters cannot.
 *
 * **The asking is the caller's**, in `hooks.ts` beside every other mutation on
 * this page. What is asked is not obvious and is the reason the question
 * exists: unlike a tag, which goes back on from the picker beside it, nothing
 * on this page adds an identifier. Whether anything anywhere can is a longer
 * answer with a condition in it, and `models.BookIdentifier` is where it
 * lives; three files restated it and all three got it wrong.
 */
export default function IdentifierChips({
  identifiers,
  onRemove,
}: IdentifierChipsProps) {
  const { t } = useTranslation();

  return (
    <>
      {identifiers.map((identifier) => (
        // The row id, which is what the delete route is addressed by and is
        // therefore the one thing on screen that is certainly this row. The
        // pair below it, scheme and value, is unique for one book too, by
        // `uq_book_identifiers_book_scheme_value`: two ASINs on one book is
        // what a merge of two Kindle entries produces, so the scheme alone
        // would not have been a key either.
        <span
          key={identifier.id}
          // **`min-w-0` and the wrap together, because the wrap alone does
          // nothing here.** The value is up to 60 characters with no space in
          // it, and a flex item's automatic minimum size is its min-content
          // size, which `overflow-wrap: break-word` is defined not to lower.
          // So `break-words` by itself leaves the token setting the item's
          // floor and widening the row past the viewport. `min-w-0` removes
          // the floor and the wrap then breaks the token. `min-w-0` is what
          // this tree already reaches for: 23 uses in 20 files outside this
          // one, counted in code rather than in prose. Not pixel measured,
          // because there is no browser on this node; what is measured is the
          // rule, and both values a reader here produces today are 10 and 12
          // characters long.
          //
          // **And this box is deliberately not a flex container, which is the
          // half that a tidy-up removes.** Giving it `inline-flex` to space
          // the button puts the label in an anonymous flex item of its own,
          // and that item takes `min-width: auto` and the same content floor
          // the paragraph above is about. `min-w-0` here cannot reach it, so
          // the token sets the width again through a child nobody can select.
          // The button is an ordinary inline box with a margin instead: it
          // wraps onto its own line on a narrow screen, which is the cost, and
          // the token still breaks. `leaves the chip a plain box, so the value
          // still breaks` is what fails if this is tidied into a gap.
          className="min-w-0 text-xs text-paper-600 bg-paper-100 px-2 py-0.5 rounded break-words dark:text-paper-400 dark:bg-paper-800"
        >
          {chipText(t, identifier)}
          <button
            type="button"
            onClick={() => onRemove(identifier)}
            // The whole sentence, so the accessible name tells two chips
            // apart: "Remove" alone repeats on every one of them, and a book
            // that carries two ASINs is the ordinary output of a merge.
            aria-label={t("identifier.remove", {
              identifier: chipText(t, identifier),
            })}
            className="ml-1 opacity-60 hover:opacity-100 leading-none"
          >
            ×
          </button>
        </span>
      ))}
    </>
  );
}
