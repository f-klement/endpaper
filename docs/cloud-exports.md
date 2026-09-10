# Reading a library out of a service's own export

A member can ask Google, Amazon or Goodreads for their data and get a file back. Each is a
different shape and none is documented: what a service exports changes without notice, so an
export read today is an export read on one date.

**None of this is an integration with a company.** Nothing here signs in, holds a token or
calls an API. It reads a file the member downloaded and already has.

[device-libraries.md](device-libraries.md) is the same family one step over, a catalogue on
hardware the member owns, and its rule holds here unchanged: **an unreadable source is one
skipped source and never a broken import.** Every outcome is a value in a closed union, so a
member importing from several places at once loses the one that moved and keeps the rest.

## Google Play Books, inside a Google Takeout archive

`frontend/src/lib/takeout.ts` carries the export it was read against, its date, every
measurement and every exclusion. **This page carries none of them**, because a figure with two
homes is two things to update, and the ones below are the decisions that outlive the figures.

### It reads in the browser, and that is not a preference

The obvious home was the backend's import seam, which is a reader per service and already has
three. That seam is handed decoded text, and this archive is 37 MB of the member's own EPUB
files. Uploading it to be unzipped on the server is exactly the custody `frontend/src/lib/epub.ts`
refuses to take, and the reason it refuses is not where the code runs: a transient endpoint that
reads a book and discards it is still custody.

**So the shape of the source decides which seam it belongs to.** An export that is a table of
rows about books goes to the backend reader per service; an export that contains the books goes
to the browser, beside the EPUB reader it can then reuse.

### The suffix is not evidence, and here it is a lie

Every book in that archive is named `.pdf` and every one is a zip whose first entry is a stored
`mimetype` reading `application/epub+zip`. A reader keyed on the extension reads none of them.

**What follows for anything else read out of an archive**: a name inside a member's file is
data, not a claim, and the format is decided by the bytes at the position the format itself
specifies. The cost is stated where it falls: the check is exact, and one file in that export
carries a trailing newline in that entry and is refused. It is named with its title rather
than dropped, because a member can act on "this file is not a readable EPUB" and cannot act on
a count that is one short.

**A refused file is not proof of a broken one.** Every sidecar's stylesheet carries rules for a
narrator, an audio bookmark and a document position, so Play Books evidently writes the same
sidecar for audiobooks and for documents the member uploaded themselves, and it does not say
which of the three an entry is. No such entry was in the archive read, so that much is an
inference. The file beside the sidecar is the only thing that answers it, which is why a book
is not imported from its sidecar alone even though the sidecar carries the identifier.

### The identifier is a volume id, and it is the only one

There is no ISBN anywhere in that archive: the EPUB identifiers are UUIDs and Project Gutenberg
URLs. Every sidecar carries a Google Books volume id, which is a key into an API this app
already speaks.

**Distinct is the load bearing half.** Two titles appear twice in that export, the second file
named `Title(1)`, sharing one folder and carrying different volume ids: they are different
editions and not duplicates. Anything keyed on the folder, or on the title, files them as one
book and loses an edition.

### What is deliberately not read

The passage a highlight marks is the book's text, and the note beside it is the member's own
words with nowhere yet to go, so both are counted and neither is carried out of the parse. A
note's timestamp is localised prose, including its timezone, and a wrong parse dates a member's
own note wrongly. `frontend/src/lib/kobo.ts` refuses a read status on the same ground: whether
an import writes one is a decision about the import flow rather than about reading a file.

## What this does not settle

Amazon and Goodreads. Both are a table of rows rather than an archive of books, so by the rule
above both belong in the backend's reader per service, and neither has been read against a real
export here.
