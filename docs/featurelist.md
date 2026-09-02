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
Spanish, Portuguese, Greek and Czech titles all resolve. The two newest are the
clearest case for chaining them: of 50 Greek ISBNs the other free sources answer
8 between them and the Greek national catalogue answers 37, and of 50 Czech ISBNs
they answer 10 and the Czech national catalogue answers 49.

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
Headings, which the record supplies as a phrase rather than a number. A book shows
the headings it carries, any of them can be filtered on, and a shelf can be ordered
by its Dewey numbers.

**A provider list.** Every catalogue this build can ask is listed in Settings, with a
switch and a position. Off means not asked, not deprioritised. The order is the order they
are asked in; which source is believed when two disagree is a separate rule that is
deliberately not exposed.

---

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
table carries twenty three columns, sorts on what the server can genuinely
order by, and draws whichever of them you pick. Both the view and the columns
are remembered in the browser, and the columns are remembered per mode.

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
on every channel switched on: **in the app**, **email** over SMTP, a **Telegram**
chat, and a **webhook** of your choosing. The three that send outward land in a
mailbox or a chat, so private books are left out of all of them and reported
only as a count. The in app notice is the one with a reader, so it carries what
that reader may already see, their own private books included; it is also the
only one that needs nothing set up, and it is on to begin with.

**Overdue loans have a page of their own**, with the reminder channels' standing
state beside them. The library page says how many and links to it; the loans
page keeps every loan in one list and marks the late ones in place. What the
channel lines can say is bounded, and the page says so: the app records what
each channel did on its last run, not which reminder reached which borrower.

**A reminder channel that has stopped working says so**, under the switch that
configures it, on the overdue page beside the loans, and, once it has been
failing for a day, on the library page. A setting the app will not use is
reported at once, because nothing was tried; a destination that could not be
reached only after it has failed repeatedly, so a network blip does not raise an
alarm.

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

Ten palettes, light and dark, decorated papers, and a per account choice.
English and German throughout, the seeded tag vocabulary included: a predefined
tag reads in the language you chose, while a tag you invented or renamed is
shown exactly as you typed it. Installable as a PWA. Keyboard reachable, and
tested for it.

The book page folds into sections whose defaults follow the book: a loan section
opens on a book that is out, copies on a book with more than one, and your own
choice to open or close one is remembered.

**Settings is an index of eight screens**, each with a sentence saying what is
behind it: appearance, your account, catalogue sources, your library, the public
catalogue, lending, data and accounts, and about. Nothing there folds. Every screen has its own address, so a
setting can be linked to rather than described as "third card down".

**An email address per member**, optional, set while an account is being created
or afterwards on the account screen. Whoever creates the account can give one:
the person registering, or the admin creating a test account. A
member with none is told so rather than shown an empty box, and a member whose
account came from a directory that supplies no address is told that the field is
theirs to fill in. **Nothing is sent to it yet**: overdue reminders go to the
household mailbox, and the address is there so that they can stop having to.

**An About screen** names the version it is running, links the source, and asks
once, in one sentence, whether you want to buy the author a coffee. Nothing else
in the app asks at all.

**MARC21 import and export** (library mode). Read a MARCXML file another
library exported; write the whole shelf back out as MARCXML. Matched on ISBN,
then author and title together. Carries the classifications, which is what a
receiving library shelves by.

**ISO 2709 is deliberately not read or written**, the binary MARC serialisation. It carries a
directory of byte offsets that has to agree with the field data after every
change, and every consumer that reads it reads MARCXML too. Authority record
import is also out: this app stores an author identifier, not an authority
record.

**A public catalogue, off by default and behind two switches.** Library mode
changes what a cataloguer sees: call number and Classification in, ownership,
lending willingness and reading status out. Which columns the table draws is
chosen from that set and remembered separately for each mode, so turning the
mode on and off does not rearrange a household's catalogue. The call number is
Dewey and Library of Congress, the two schemes that place a book on a shelf, and
it sorts by the Dewey number rather than by the text in the cell. It publishes
nothing. The publish switch is a
second, separate decision, and a library running library mode internally without
publishing is the common case rather than an edge one. Publishing is refused by
the server whenever library mode is off, so turning library mode back off cannot
leave a catalogue public.

What a reader with no account gets is **search and one item record, and nothing
else**. Ownership, lending willingness, reading status, member names, notes,
purchase details, the trash and every per member field are absent from the
payload, not merely hidden by a client. **Private books stay private in every
mode**: that rule is not the switch's to relax. The public routes are rate
limited, and a published catalogue is `noindex` until indexing is separately
allowed, because publishing a catalogue and inviting a search engine to crawl it
are different decisions.

## Deliberately not built

**No offline mode.** Everything on every screen comes from the API, so an
offline shell could only lie.

**No Apple build, and none planned.** No iOS app, no iPad app, no macOS
desktop client. The reason is hardware rather than product: building for an
Apple platform requires Apple hardware to build on. On those platforms the
progressive web app is the whole offering, and it is a real one, with its own
icon and its own window. It needs the instance reachable, like every other
screen here.

**No social features**, no federation, no recommendations, no reading goals.

**No library circulation.** No queue positions, no pickup notifications, no
fines, no MARC, no Z39.50 as a client. Koha exists and is better at all of it.

**No author biographies or portraits.** The shelf stores a name and, where a
catalogue asserted one or somebody confirmed one, that spelling's number in an
authority file. Confirming a GND number keeps the ISNI, Library of Congress
number, VIAF cluster and Wikidata item the same record carries, **and the
national library numbers for Brazil, Argentina, Spain, Portugal, Italy and
Chile**, which the GND record does not carry and the VIAF cluster it names does.
That is what lets an author be looked up outside German. Dates and a one line
description are shown while you tell two same named writers apart, and are not
kept. An author stays a derived fact rather than a second thing to maintain.

Those six are **stored and not resolved**, and the difference is honest rather
than a limitation being dressed up: Brazil's and Argentina's catalogues refuse
every request, and the rest speak a protocol this app has no client for. The
identifier arrives free with a confirmation, which is what would make an adapter
for one of them cheap on the day it becomes possible.
