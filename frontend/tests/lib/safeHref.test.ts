import { describe, expect, it } from "vitest";

import { safeHref } from "../../src/lib/safeHref";

describe("safeHref", () => {
  it.each([
    ["javascript:alert(1)"],
    ["JavaScript:alert(1)"],
    ["java\tscript:alert(1)"],
    ["data:text/html,<script>alert(1)</script>"],
    ["vbscript:msgbox(1)"],
    ["//evil.example/x"],
    ["/books/12"],
    ["calibre.example/book/12"],
    [""],
    // WHATWG percent-decodes the host before IDNA maps it, so every one of
    // these resolves to `evil.example` while reading as a host the household
    // trusts. Refused rather than resolved, because the link text is the
    // stored value and the destination is this return: resolving would put two
    // different registrable domains in one anchor.
    ["https://calibre.example%2eevil.example/x"],
    ["https://calibre.example%2Eevil.example/x"],
    ["https://calibre.example%252eevil.example/x"],
    ["https://calibre.example%ef%bc%8eevil.example/x"],
    ["https://calibre.example%00/x"],
    ["https://calibre.example%2fevil.example/x"],
    // Every authority form WHATWG accepts, not just `scheme://`. After a
    // special scheme it consumes any run of `/` or `\\`, so a pattern
    // expecting exactly two forward slashes read the empty string out of the
    // first two of these and passed them. Measured: all resolve to
    // `evil.example`.
    ["https:/calibre.example%2eevil.example/x"],
    ["https:///calibre.example%2eevil.example/x"],
    ["https:\\\\calibre.example%2eevil.example/x"],
    ["https:/calibre.example\u3002evil.example/x"],
  ])("refuses %s", (value) => {
    expect(safeHref(value)).toBeUndefined();
  });

  it.each([[null], [undefined]])("refuses %s", (value) => {
    expect(safeHref(value)).toBeUndefined();
  });

  it.each([
    ["https://calibre.example/book/12"],
    ["http://calibre.lan:8083/book/12"],
    ["https://calibre.example/book?id=12&x=1"],
  ])("allows %s unchanged", (value) => {
    // Unchanged because the server rebuilt it the same way. These are the
    // shapes where the two parsers already agree.
    expect(safeHref(value)).toBe(value);
  });

  it.each([
    ["https://calibre.example\u3002evil.example/x"],
    ["https://calibre.example\uff0eevil.example/x"],
    ["https://calibre.example\uff61evil.example/x"],
  ])("refuses the separator %s rather than resolving it", (value) => {
    // The server rewrites these, so a value this app stored never carries one.
    // This is the row the server never saw: `backup.restore` writes through
    // Core. Refused rather than resolved, because the panel renders the stored
    // `value` as the link text and this as the destination, so resolving would
    // name two different registrable domains in one anchor.
    expect(safeHref(value)).toBeUndefined();
  });

  it.each([
    ["a space", " "],
    ["a tab", "\t"],
    ["a line feed", "\n"],
    ["a start of heading", "\u0001"],
    ["a bell", "\u0007"],
    ["a unit separator", "\u001f"],
  ])("refuses a host hidden behind %s", (_name, prefix) => {
    // WHATWG strips leading C0-or-space **before** parsing, so `^` is not the
    // start of the URL and a regex anchored there reads a fragment of the
    // scheme instead of the authority. All six parse and resolve to
    // `evil.example`.
    //
    // The three control characters are why this strips C0-or-space rather
    // than calling `trim()`, which leaves `\u0001`, `\u0007` and `\u001f`
    // exactly where they were.
    expect(
      safeHref(`${prefix}https://calibre.example%2eevil.example/x`),
    ).toBeUndefined();
  });

  it("refuses a host hidden behind a newline inside the scheme", () => {
    // Tabs and newlines are removed from the **whole** string before parsing,
    // so one inside the scheme moves the authority without breaking the URL.
    expect(
      safeHref("http\ns://calibre.example%2eevil.example/x"),
    ).toBeUndefined();
  });

  it("allows a percent escape outside the authority", () => {
    // Only the host is the question: an escape in a path or a query is
    // ordinary and both parsers agree about it.
    expect(safeHref("https://calibre.example/book/12%20a")).toBe(
      "https://calibre.example/book/12%20a",
    );
    expect(safeHref("https://calibre.example/x?q=a%20b")).toBe(
      "https://calibre.example/x?q=a%20b",
    );
  });

  it("does not compare the parsed url against its input", () => {
    // The obvious check is `parsed.href !== href`, and it is wrong: the two
    // parsers normalise legitimately different things, so a URL the server
    // stores without a trailing slash would stop being a link.
    expect(safeHref("https://calibre.example")).toBeDefined();
  });

  it("leaves the attribute off rather than linking to this page", () => {
    // `""` in an href is a link back to the current URL, so a refusal that
    // returned one would be a working link to somewhere unexpected.
    expect(safeHref("javascript:alert(1)")).not.toBe("");
  });
});
