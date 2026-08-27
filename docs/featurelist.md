# What Endpaper does

A catalogue of the books a library holds, and a record of who has them. Built for a
household's shelves and for the library or archive that has outgrown a spreadsheet.

This is the current feature set, not a roadmap.

**The README's Features section is the summary; this is the complete list.** The
difference that matters is the last section: what this app deliberately does not
do. Somebody deciding whether to run it should learn that here rather than by
trying it. If the two ever disagree, this file is wrong, because the README is
what people read first and gets corrected first.

## The catalogue

**A book** records ISBN, title, subtitle, author, publisher, year, description,
cover, page count, language, categories, series name and index, format
(hardcover, paperback, ebook, audiobook), condition, and where it is shelved.

**Adding a book** by ISBN, by barcode scan in the browser, by free text search,
or by hand. ISBN lookup chains several sources so a European or pre-ISBN book
still resolves rather than failing at one provider, and English, German, French,
Spanish and Portuguese titles all resolve.

**Rapid mode** scans a whole shelf without stopping between books. The batch is
reviewed before anything is written, so a misread barcode is caught before it
becomes a row.

**Enrichment** fills a sparse record from an external catalogue on request. It is
always a choice: nothing is fetched in the background, and a field is only
overwritten when you say so.

**Classifications are kept whole**: the scheme, the number and the caption a
catalogue gave it (`DDC`, `004`; `GND`, `4203576-4`, `Schatz`). The number is
what a tag suggestion is matched on, so a German record and an English one
suggest the same tag. It is offered on the add form with the suggestions ticked,
so it is a proposal you confirm rather than a tag applied behind you.

Four schemes are stored: Dewey and Library of Congress shelf numbers, the
subject headings the German National Library assigns, each with the identifier
that names it in the national authority file, and Library of Congress Subject
Headings, which the record supplies as a phrase rather than a number. Nothing
displays them yet.

**Covers are stored here**, not hotlinked. Every candidate image is fetched and
checked before it is offered, so a broken link never becomes a book's cover, and
a stored cover survives the source going away. Fetching is restricted to an
allowlist of hosts.

**Import and export** as CSV, and a full backup and restore.

## Finding things

**Search** across title, author and ISBN, with filters for tags, collection,
series, shelf location, format, reading status and ownership. A filter set can
be saved as a view.

**Card, list or table.** The list is one dense row per book: a tiny cover, the
title, and the author, series, year and reading status beside it, plus a marker
where the book is out on loan or nobody has confirmed the library holds it. The
table carries twenty one columns and sorts on what the server can genuinely
order by. The choice is remembered in the browser.

**Series** and **author** pages group the shelf by what it already knows, and a
series page works out which volumes are missing rather than making you notice.

**A saved view** keeps a filter combination under a name, including a wishlist:
books you want but do not own, which is the same data as ownership rather than a
second list to maintain.
Authors can be **merged** when one person arrives spelled several ways: the merge
records a decision and never rewrites a book, so it is reversible and survives a
re-import.

**Duplicates** finds books that look like the same title, matched on normalised
title and author rather than ISBN, so different printings are caught.

## Reading and lending

**Reading status**: unread, want to read, reading, read, and did not finish, per
person rather than per book.

**Reading progress** records the page you reached, or a percentage for an
audiobook, as many times as you like. Recording progress on a book you had
abandoned returns it to reading; nothing deletes the log.

**Notes** and **quotes** hang off a book. A quote is verbatim text with an
optional page and your own remark beside it, kept separate so one is not
mistaken for the other.

**Loans** record who has a book and when it is due, including people who are not
members. Overdue loans are chased on a schedule you set, and the digest goes out
on every channel switched on: **email** over SMTP, a **Telegram** chat, and a
**webhook** of your choosing. Private books are left out of all three.

**Willingness to lend** is a property of a book, so somebody can see what you
would part with before asking.

## Organising

**Tags**, with a predefined set seeded on first run.

**Collections**: named parts of a shelf, one per book. Filing changes nothing
about who may see a book.

**Multiple copies** of one title, each with its own condition, location and
lending state. The ISBN uniqueness rule applies to single copies only.

**Ownership** distinguishes what the library holds from what it wants.

**Bulk edits** tag, re-shelve, set a status or delete a whole selection at once,
so a shelf reorganised in life does not take an evening to reorganise here.

**Custom fields**: a fact the library keeps about a book that Endpaper has no
column for, defined once and filled in per book. A field can be declared to hold
a web link, and then renders as one, which is what makes a book's page in a
calibre-web instance one tap away. Renaming a field keeps every value under it;
deleting one takes them all, and is admin only.

## People and privacy

**One account per person**, and the first account created becomes the admin,
whichever way you sign in. Authentication is local, LDAP, or a reverse proxy that
has already authenticated the reader.

**A private book is visible only to the member who added it.** This is enforced
in one place and asserted by a test that walks every backend module: an
unfiltered query fails the build rather than leaking quietly. An invisible book
answers 404, never 403, because a 403 confirms the id exists.

**Trash** holds a deleted book until it is purged, so a mistake is recoverable.

## Knowing what you have

**Statistics**: what is on the shelf, who reads what, what got finished when, and
how the year compares to the last. Every count obeys the privacy rule, so a
library wide total is not a way to learn what somebody keeps private.

## Running it

**One container**, a single SQLite file and a directory of covers. `GET
/api/healthz` answers container probes and genuinely touches storage, so a pod
whose volume vanished reports unhealthy rather than staying green.

## The interface

Seven palettes, light and dark, decorated papers, and a per account choice.
English and German throughout. Installable as a PWA. Keyboard reachable, and
tested for it.

The book page folds into sections whose defaults follow the book: a loan section
opens on a book that is out, copies on a book with more than one, and your own
choice to open or close one is remembered. Settings folds the same way against a
fixed rule instead: a card that answers "what is this set to" arrives open, a
card that starts a job arrives closed.

**An About card** names the version it is running, links the source, and asks
once, in one sentence, whether you want to buy the author a coffee. Last on the
page, and nothing else in the app asks at all.

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
