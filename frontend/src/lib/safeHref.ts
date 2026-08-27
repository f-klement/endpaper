/**
 * The one place this app decides a string may become an `<a href>`.
 *
 * The backend already decides it: `custom_fields.link_target` refuses anything
 * that is not `http` or `https` with a real host, and it does so on every read
 * rather than only on every write, so a value that reached the table through a
 * restore is served as text. This is the same rule again on this side of the
 * wire, and the reason to have it twice is what React does with the string.
 *
 * **React renders `href="javascript:..."` without a word.** The development
 * warning that used to be there was removed in React 19, and there has never
 * been an error: the attribute is written to the DOM and the browser runs it on
 * click. So a component that interpolates a server value straight into `href`
 * is trusting the server for something the framework will not check, and that
 * trust is invisible in the JSX.
 *
 * Refused, therefore, and each one is a string a person can type into a text
 * box: `javascript:`, `data:`, `vbscript:`, a scheme relative `//host` (which
 * carries no scheme and inherits the page's), a bare path, anything `URL`
 * cannot parse at all, and an authority carrying any of `AUTHORITY_REFUSED`.
 *
 * Returns `undefined` rather than `""` for a refusal, because that is the value
 * that leaves the attribute off the element entirely. An empty string is a link
 * back to the current page.
 *
 * On acceptance it returns the **parsed** URL rather than the input, so an
 * `<a>` is never pointed at a string this code has not resolved itself. See
 * the comment on the return.
 *
 * **A host this parser reads differently from the stored text is refused, not
 * resolved**, which is the opposite of what the return above does for
 * everything else and is deliberate. The caller renders the stored value as
 * the link text and this as the destination, so resolving
 * `calibre.example%2eevil.example` would name two registrable domains in one
 * anchor: `evil.example` where the reader sees `calibre.example`. That is a
 * sharper phishing case than an unlinked value. See AUTHORITY_REFUSED.
 */
/**
 * Characters that must not appear in the authority of a stored link.
 *
 * All four make a browser read a **different host** than the string does, so an
 * `<a>` built from one names one domain in its text and goes to another. Three
 * are the WHATWG label separators (U+3002, U+FF0E, U+FF61); the fourth is `%`,
 * which is the same divergence one step earlier, because the host is
 * percent-decoded before IDNA maps it: `calibre.example%2eevil.example`
 * resolves to `evil.example`.
 *
 * `custom_fields.link_target` rewrites the separators and refuses the percent
 * escape, so a value this app stored contains none of them and this test is
 * free. It is here for the row it did not store: `backup.restore` writes
 * through Core.
 *
 * **Refusing beats comparing.** The obvious check is `parsed.href !== href`,
 * and it is wrong: the two parsers normalise legitimately different things, so
 * a stored `https://a.example` compares unequal to the browser's
 * `https://a.example/` and a perfectly good link would stop working. This tests
 * the four characters the server would have removed, and nothing else.
 *
 * The authority only. A percent escape in a path or a query is ordinary and
 * both parsers agree about it, so `/book/12%20a` is a link.
 */
const AUTHORITY_REFUSED = /[%\u3002\uff0e\uff61]/;

/**
 * The authority of a URL, as written, before any parser has touched it.
 *
 * **Both halves of this are one step earlier than they look**, which is the
 * shape of every hole found in this rule so far. WHATWG does two things before
 * it parses anything: it strips leading and trailing C0-or-space, and it
 * removes every tab, LF and CR from the whole string. So `^` is not the start
 * of the URL, and a leading control character or a newline inside the scheme
 * moves the authority out from under a regex anchored there.
 *
 * Then, after a **special** scheme, it consumes any run of `/` or `\` before
 * the authority, and treats `\` as `/` everywhere else too. So `https:/host`,
 * `https:///host` and `https:\\host` all have an authority, and a pattern that
 * expects exactly two forward slashes returns the empty string for the first
 * two: no `%`, no separator, check passes, link resolved against whatever the
 * browser read.
 *
 * Measured 2026-08-27, every one of these resolving to `evil.example` while
 * the old pattern returned `""` or a fragment of the scheme:
 *
 *     https:/calibre.example%2eevil.example/x
 *     https:///calibre.example%2eevil.example/x
 *     https:\\calibre.example%2eevil.example/x
 *     <TAB>https://calibre.example%2eevil.example/x
 *     <U+0001>https://calibre.example%2eevil.example/x
 *     http<LF>s://calibre.example%2eevil.example/x
 *
 * **C0-or-space rather than `trim()`**, and the difference is three of those
 * six: `trim()` removes tab, LF, CR, VT, FF and space and leaves `\u0001`,
 * `\u0007` and `\u001f`, all of which a browser strips and then parses.
 * Measured against `new URL(...).host` rather than reasoned from the spec.
 */
function rawAuthority(href: string): string {
  const stripped = href
    .replace(/^[\u0000-\u0020]+|[\u0000-\u0020]+$/g, "")
    .replace(/[\t\n\r]/g, "");
  const afterScheme = stripped.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:[/\\]*/, "");
  return afterScheme.split(/[/\\?#]/, 1)[0] ?? "";
}

export function safeHref(href: string | null | undefined): string | undefined {
  if (!href) return undefined;
  let parsed: URL;
  try {
    // No base, deliberately. Passing one would resolve `/books/12` and
    // `//evil.example/x` against this origin and hand back an absolute URL,
    // which is the opposite of refusing them.
    parsed = new URL(href);
  } catch {
    return undefined;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return undefined;
  }
  // Against the **raw** string, not `parsed.host`, which has already decoded
  // and mapped and so cannot tell the two apart. See AUTHORITY_REFUSED.
  if (AUTHORITY_REFUSED.test(rawAuthority(href))) {
    return undefined;
  }
  // **`parsed.href`, not `href`.** Returning the input computes the normalised
  // URL and throws it away, which is the whole point of parsing it here: the
  // browser resolves `https://good.example。evil.example/x` against
  // `evil.example`, and `URL` says so in `parsed.href` while the raw string
  // does not. The server rebuilds the same way (`custom_fields.link_target`),
  // so on a healthy row these two strings are equal and this line costs
  // nothing; it is what keeps that true for a row the server never saw.
  return parsed.href;
}
