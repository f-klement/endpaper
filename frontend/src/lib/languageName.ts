/**
 * A Wikipedia language code, as something a reader recognises.
 *
 * `fr` becomes "French" for an English reader and "Französisch" for a German
 * one. The alternative is showing the code, which reads as a fault rather than
 * as information: "Read about Frank Herbert on Wikipedia, in fr" tells somebody
 * nothing they can act on.
 *
 * **Wikipedia's subdomains are not all valid language tags, and
 * `Intl.DisplayNames` throws rather than falling back on the ones that are
 * not.** Measured in this project's own runtime: `of("bat-smg")`,
 * `of("zh-yue")`, `of("roa-rup")` and `of("cbk-zam")` all raise a
 * `RangeError`, while `of("simple")` and `of("xx")` return the code unchanged
 * because `fallback: "code"` covers a well formed tag nobody has a name for.
 * Those four are legacy Wikipedia codes, and they are not a tail case here:
 * the article link's last tier picks `min()` of the codes available, so
 * `bat-smg` and `cbk-zam` sort **ahead of** `de`, `en`, `fr` and `zh`. For an
 * author whose editions include one of them, the malformed tag is the one that
 * gets picked. An unguarded throw there is not a rare crash, it is the ordinary
 * outcome for that author, and it takes the whole card down behind an error
 * boundary.
 *
 * So the throw is caught and the code is shown. That is the same answer
 * `fallback: "code"` gives, applied to the inputs it refuses to consider.
 */
export function languageName(code: string, locale: string): string {
  try {
    return (
      new Intl.DisplayNames([locale], {
        type: "language",
        fallback: "code",
      }).of(code) ?? code
    );
  } catch {
    // Not a language tag `Intl` will consider. See above: `bat-smg` and three
    // others are real Wikipedia editions and raise rather than fall back.
    return code;
  }
}
