# What Endpaper does

A catalogue of the books a household owns, and a record of who has them.

This is the current feature set, not a roadmap. Where a feature has a limit or a
deliberate omission, it is stated here rather than discovered later.

## The catalogue

**A book** records ISBN, title, subtitle, author, publisher, year, description,
cover, page count, language, categories, series name and index, format
(hardcover, paperback, ebook, audiobook), condition, and where it is shelved.

**Adding a book** by ISBN, by barcode scan in the browser, by free text search,
or by hand. ISBN lookup chains several sources so a European or pre-ISBN book
still resolves rather than failing at one provider.

**Enrichment** fills a sparse record from an external catalogue on request. It is
always a choice: nothing is fetched in the background, and a field is only
overwritten when you say so.

**Covers are stored here**, not hotlinked. A cover survives the source going
away, and fetching is restricted to an allowlist of hosts.

**Import and export** as CSV, and a full backup and restore.

## Finding things

**Search** across title, author and ISBN, with filters for tags, collection,
series, shelf location, format, reading status and ownership. A filter set can
be saved as a view.

**Card or table.** The table carries nineteen columns and sorts on what the
server can genuinely order by. The choice is remembered.

**Series** and **author** pages group the shelf by what it already knows.
Authors can be **merged** when one person arrives spelled several ways: the merge
records a decision and never rewrites a book, so it is reversible and survives a
re-import.

**Duplicates** finds books that look like the same title, matched on normalised
title and author rather than ISBN, so different printings are caught.

## Reading and lending

**Reading status**: unread, reading, read, and did not finish. Progress is
recorded per member with a page number and a history.

**Notes** and **quotes** hang off a book. A quote is verbatim text with an
optional page and your own remark beside it, kept separate so one is not
mistaken for the other.

**Loans** record who has a book and when it is due, including people who are not
members. Overdue loans are chased on a schedule you set, and the digest is
posted to a webhook of your choosing.

**Willingness to lend** is a property of a book, so somebody can see what you
would part with before asking.

## Organising

**Tags**, with a predefined set seeded on first run.

**Collections**: named parts of a shelf, one per book. Filing changes nothing
about who may see a book.

**Multiple copies** of one title, each with its own condition, location and
lending state. The ISBN uniqueness rule applies to single copies only.

**Ownership** distinguishes what the household owns from what it wants.

## People and privacy

**One account per person.** Authentication is local, LDAP, or a reverse proxy
that has already authenticated the reader.

**A private book is visible only to the member who added it.** This is enforced
in one place and asserted by a test that walks every backend module: an
unfiltered query fails the build rather than leaking quietly. An invisible book
answers 404, never 403, because a 403 confirms the id exists.

**Trash** holds a deleted book until it is purged, so a mistake is recoverable.

## The interface

Seven palettes, light and dark, decorated papers, and a per account choice.
English and German throughout. Installable as a PWA. Keyboard reachable, and
tested for it.

The book page folds into sections whose defaults follow the book: a loan section
opens on a book that is out, copies on a book with more than one, and your own
choice to open or close one is remembered.

## Deliberately not built

**No public catalogue.** Nothing is readable without a session.

**No offline mode.** Everything on every screen comes from the API, so an
offline shell could only lie.

**No social features**, no federation, no recommendations, no reading goals.

**No library circulation.** No queue positions, no pickup notifications, no
fines, no MARC, no Z39.50 as a client. Koha exists and is better at all of it.

**No author biographies or portraits.** The shelf knows a name and nothing else
about a person, which is what keeps an author a derived fact rather than a
second thing to maintain.
