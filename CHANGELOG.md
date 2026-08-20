# Changelog

## v0.2.0

The first release that publishes both source and an image. v0.1.0 got half way:
GitHub received the source, Docker Hub received nothing.

### Added

**Metadata, four sources instead of two.** The DNB and K10plus are asked
concurrently and their answers merged, then Open Library, then Google Books.
Which is asked first is decided by the ISBN prefix, so a 978-3 goes to the DNB.
No key is required for any of the first three, and Google is optional.

**Covers are verified before they are stored.** A candidate URL is fetched and
answered three ways: present, definitely absent, or unknown. Unknown keeps the
URL, so a momentary 5xx at the image host does not throw away a cover that
exists.

**Import from anything, not just Goodreads.** Columns are guessed rather than
required, with a preview before anything is written. Measured against real
exports from Goodreads, StoryGraph, LibraryThing and Calibre, and a list
somebody typed by hand.

**Backup and restore.** The whole library plus every cover as one zip.

**Tags a household can invent for itself**, beside a curated vocabulary grown
from 32 to 105 and grouped by category in the picker.

**Trash.** Deleting a book is reversible, with a window to change your mind.

Also: saved searches, a wishlist view, overdue loans that say so, and format,
condition, price, purchase date and purchase source on a book.

### Fixed

**Proxy and LDAP deployments had no admin bootstrap.** Registration is 403 in
both modes and admin came only from a configured group, so deploying with
`AUTH_MODE=proxy` and no groups header produced a library nobody could
administer, and switching an existing local deployment to a directory demoted
the existing admin on their first page load.

**The cover cookie was a copy of the access token.** It is now scoped and
refused everywhere but the cover route, so a copy that escapes cannot be
replayed against the API. `POST /auth/logout` clears it; nothing did before, so
it outlived the session.

**A restore could hand a live session to the wrong person.** It replaces the
users table, so the id in an existing token may afterwards belong to somebody
else. Tokens now carry an epoch that a restore rerolls.

**Foreign keys were not enforced**, which made every `ON DELETE CASCADE` in the
schema decorative. Turned on, along with WAL and a busy timeout, and every
foreign key column is now indexed.

**One open loan per book is a database constraint.** Merging two records used to
leave both open, so a book could be out with two people at once.

**Uploads are refused before they reach the disk.** A 200 MB request aimed at
the 5 MB cover endpoint was spooled to a temporary file in full and only then
answered with a 413.

**A failed cover upload no longer destroys the cover that was there.**

**Rate limits** on library import and on the metadata fan-out, which reaches as
many as four public catalogues per call.

**Re-scanning a book you already own** offers to open it, rather than answering
with a sentence and no way forward.

**The account menu was unreadable on a phone**, folded into a 56px rail.

### Changed

- `POST /api/books/bulk/ownership` is removed. `POST /api/books/bulk` with
  `set_ownership` has the same body, the same permission rules and the same
  result.
- `GET /api/healthz` is the health endpoint. Container probes should point at
  it rather than `/`, which is answered from disk and stays healthy when the
  database is not.

## v0.1.0

Source published to GitHub. The image did not publish.
