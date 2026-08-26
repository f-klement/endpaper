# Changelog

## Unreleased

**Internal: one module now owns every book query.** `backend/shelf.py` is the only
place that applies the privacy rule, so a listing, a count, an index or an export
is scoped to what a member may see by how it is built rather than by remembering a
filter. Nothing about what anybody sees has changed; the rule it enforces is the
same one, enforced in one place instead of twenty four.

**Fixed: a backup did not include the author merges, so restoring one split
every merged author back into its spellings.** The books themselves were always
intact, which is why nothing looked wrong: a merge records a decision and never
rewrites a book. Backups taken from now on carry the decisions. An older archive
restores with none, which is the state it was written in.

**Fixed: some pages could leave the server holding on to memory it never freed.**
Every "not found" answer from the cover, book and author routes kept a little
state alive for the lifetime of the process. Nothing was exposed and nothing was
lost; a busy library would have seen memory climb slowly.

**Internal: the library's filters have one owner, and the two sides are now checked
against each other.** Reading them out of a link and turning them into a request were
written in different places, and nothing said they described the same set of filters.
They do, and a test proves it against the API's own schema from now on. Nothing about
what the filters do has changed.

**Fixed: importing a library export could fail completely if one of its shelf
names was not plain English.** A shelf called "Ästhetik" that already existed as
a tag made the whole import stop and write nothing, every time, with no useful
message. Nothing was lost, but nothing arrived either.

**Fixed: the import preview had no rate limit**, although the documentation said
it did. Reading a large file is the expensive half, so it is now limited
together with the import itself.

**Internal: applying an import has one owner too.** The code that reads a parsed
export and writes it into the library moved out of the request handler. Nothing
about importing behaves differently.

**Internal: author identity has one owner too.** The rules for deciding that two
spellings are one person were already in their own module and were already pure;
everything the database knew about it was in a route handler. Both halves now sit
together. Nothing about merging, undoing a merge or filtering by an author has
changed.

## v0.9.0

_2026-08-26_

**Classification review.** Metadata refresh and automatic enrichment now update scalar
facts only. Choosing a catalogue record shows its Classifications first, then adds the
selected evidence to the book.

**Endpaper is for libraries and archives too, and now says so.** It was always
usable by a small library, and every page described it as a household tool, which
told the wrong half of its audience it was not for them. The description is now "a
self-hosted catalogue for the books you share", built for a household's shelves and
for the library or archive that has outgrown a spreadsheet.

Nothing about how it behaves has changed. The features a library needs are still
being built, and the pages say only what has actually shipped.

Two interface labels read better as a result: "Household tags" is now "Your tags",
and the German text no longer assumes the people sharing a catalogue live together.

## v0.8.0

_2026-08-25_

A larger refactor of UI elements, naming conventions, documentation and
presentation style.

The `:latest` image also reports its version again. It read `unknown` between
releases, and `:latest` is what most self-hosters run, so the version was
missing on every day that was not a release day. It now names the release it
descends from. Tagged releases were never affected.

## v0.7.0

_2026-08-24_

**Library of Congress subject headings.** A title search now brings back what a
cataloguer said the book is about, in the Library of Congress's own controlled
vocabulary: `Computer programming`, `Software architecture`,
`Computer software -- Development`. They ride along on the record the search
already fetched, so nothing got slower and no new service is involved. Measured
over 900 live records: 85% carry at least one.

They are kept whole, subdivisions included, because `Computer software` and
`Computer software -- Development` are two different headings with two different
sets of books under them. Nothing displays them yet.

**The About card carries the README's badges.** Version, licence and source, at
the top of the card at the foot of Settings, where the version and a source link
used to sit as a sentence. They are drawn rather than fetched: no shields.io and
no image at all, so they take the colours of whichever palette you chose, they
render with the app installed and offline, and opening Settings tells no outside
service that your server exists.

**Classifications are stored whole.** A catalogue heading is a scheme, a number
and a caption: `GND`, `4203576-4`, `Schatz`. The number used to be stripped off
at parse time so the caption could substring match a tag by name, which threw
away the only half that means the same in two languages.

**Which is why German records now suggest tags at all.** Measured against the
DNB over ten German ISBNs: eight carried a DDC heading, and not one of the eight
captions matched any of the 105 built in tag names, because every caption was
German. Dewey `830` now suggests Fiction and `004` suggests Computing, through
a mapping of the 100 published Dewey divisions that reads the number and never
the words. Which is just as well, because the catalogues send the number
without any words at all.

**It stays a suggestion.** The suggested tags arrive ticked on the add form and
nothing is written until you press the button, so an unwanted one is one click
away rather than something to find and undo later. Tags are a small curated list
the household chooses from, and one nobody chose cannot later be told apart from
one they did.

**German records come back with proper subject headings.** The German National
Library is now read in the full catalogue format rather than the summary one it
was asked for before, and the difference is what the summary left out: the
subject headings a librarian assigned, each with the identifier that names it in
the national authority file. A book about a treasure hunt in Samoa arrives filed
under Schatz and Samoainseln rather than under nothing.

**And it fixed things nobody had noticed.** Records for older books had the
translator credit sitting inside the title. An edited volume had no author at
all. German umlauts arrived in a form that looks identical on screen and counts
as a different word, which was enough to file one author under two spellings.
Titles beginning with an article carried two invisible control characters, and
one carried a stray double space. Page counts now arrive on 71 of 74 records
where they used to arrive on 50.

**A well catalogued book no longer disappears from search.** A search result
carrying more subject headings than a book is allowed to keep was being thrown
away whole rather than trimmed. It now keeps the eight that matter most, and
the classification a tag suggestion reads is the one that survives.

**"Other editions of this book" now means it.** The picker used to search
every catalogue for the title and author, which is a good guess. It now asks
Open Library for the printings it has merged under the same work, with the
book's own ISBN, and puts those first: a donation in an unfamiliar printing is
matched against the actual list of printings rather than against whatever a
search returned. Editions in another language are left out, because a
translation cannot tell you what your copy's page count is.

**Open Library answers with far more than it used to.** It is read as three
records rather than one, and across 35 books that means subjects on 28 of them
rather than 16, a page count on 20 rather than none, a language on 27 rather
than none, and a Dewey or Library of Congress number on 12 rather than none. It
costs a tenth of a second.

**A DVD is no longer offered as a book.** A scanned identifier that names a
disc is refused rather than catalogued; an ebook edition of a book you are
holding is still offered, because it is the same book.

**A third way to look at the library.** Beside the covers and the table there
is now a list: one dense row per book, a tiny cover, and the title, author,
series, year and reading status beside it, with a marker when the book is out on
loan or nobody has confirmed you own it. It is for the case the other two are
bad at, which is finding a book you know you own without reading twenty one
columns or scrolling past forty covers. Your choice is remembered in your
browser, as it already was.

**Suggested tags stop reading a word inside another word.** "Software
engineering" used to suggest **War** and "thoughtcrime" used to suggest
**Crime**, and since suggestions arrive ticked, those got written unless you
noticed. Measured over 22 books, 12 of 32 suggestions were wrong that way, and
on German records every single one was. It costs one real suggestion: a book
filed under "fiction classics" no longer offers **Classic**, because the tag is
singular and the subject is not.

**Headless.** `SERVE_FRONTEND=false` runs the API without mounting the compiled
frontend, for a host that has no reader to serve a page to. One image and one
flag: the built files stay on disk, unused. With it set, a path outside the API
is a plain 404 rather than the app shell, which is correct, because a host
serving no frontend has no client routes for the shell to rescue.

**Settings folds.** Eleven cards, the same disclosure and the same per device
memory the book page uses, against a fixed rule: a card that answers "what is
this set to" arrives open, a card that starts a job (import, cover backfill,
overdue reminders, test accounts, backup) arrives closed. Your own choice wins
after that, and is remembered per card.

**An About card** at the foot of Settings: the version you are running, a link
to the source, and one sentence asking whether you would like to buy the author
a coffee. The Ko-fi button is served from your own deployment, so opening
Settings tells Ko-fi nothing.

**Funding links**, in `README.md`, on the Docker Hub page and in that one
sentence. The money is for running a shared relay. It is not a paid tier and no
feature sits behind it.

**The version on that card is now the tag you released**, derived at build time
rather than typed into a file first. Nothing is bumped before tagging: a release
shows `0.7.0`, a working build shows `0.6.0-14-gbbdf755` and cannot be mistaken
for one.

## v0.6.0

_2026-08-23_

Five features, and a bug that had been hiding under a comment saying it was
fixed.

**More than one copy of a title.** Two paperbacks of one book are two objects,
each with its own condition, location and lending state. This meant breaking the
rule that an ISBN is unique, which every other feature here assumed, so it went
first: uniqueness now applies to single copies only, through a partial index.

**Collections.** Named parts of a shelf, one per book: physical from ebook, kept
from sold, yours from mine. Filing a book changes nothing about who may see it,
which is deliberate. A collection is shelving, not permission.

**Author pages, and merging.** Everybody your shelf credits, with their books
behind one click. When one person arrives spelled three ways you can fold them
together, and the merge writes nothing to any book: it records the decision, so
it is reversible, it survives a re-import that would otherwise split the name
again, and it can express a spelling no book carries.

**Quotes.** A passage worth keeping, with the page it is on and your own line
about it beside it. Kept separate from notes because one is meant to be verbatim
and the other is not.

**The book page folds.** Seventeen panels in one column became six collapsible
groups plus a heading that never folds. What arrives open depends on the book: a
loan section opens on a book that is out, copies on a book with more than one.
Your own choice to open or close a section wins over that, permanently, on that
device.

**The endless spinner is fixed, and it was two faults.** The client did not tell
the server it wanted JSON, so a portal answered an expired session with a
redirect rather than a 401; the service worker then served the cached shell to
the reload, so the reload never reached the portal. Round and round. Both are
closed, and a guard now makes a second reload in one page load impossible: a
loop degrades to a page that says what happened.

**Deep links survived nothing before this.** `/book/12` and every other client
route answered 404 on refresh, with a valid session, and had since v0.2.0. Five
documents said otherwise, one of them published. The shell is now served for an
unmatched path that is not an API route, that accepts HTML, and that is not an
asset, so a bookmark works, a refresh works, and a shared link works. `/login`
was 404ing too, which behind a portal is invisible and in the default local mode
is the sign-in form.

**Cache headers.** The shell revalidates, hashed assets do not. A reader holding
yesterday's page no longer asks for a script that a deploy deleted.

**Five migrations run on start**, in this order: `d1a7f36b9c58` adds lending
willingness, `b1e7c94a2d05` makes a second copy legal, `c2f95a80d417` creates
`collections`, `a9c4e7b21d03` creates `author_aliases`, and `d3f6b81c9a27`
creates `quotes`. All additive, all with a working downgrade, and none touches an
existing row's data. The copies one is the only one that changes a constraint:
it replaces the unique index on `books.isbn` with a partial one, so a downgrade
fails rather than silently dropping the second copy of anything.

**Dropped, so nobody goes looking.** Linking a physical book to an ebook: the
useful half of it already exists, since a copy can be marked as an ebook format
and two copies of one title are now two rows. MARC import and export, and
printable reports.

## v0.5.0

_2026-08-22_

Also in this release, after the section below was written:

**Covers are stored here rather than hotlinked.** A candidate is verified, then fetched
and written beside the book, so a cover no longer depends on a third party being
reachable from every reader's browser. `POST /api/books/covers/backfill` repairs a
library that predates this, a hundred books at a time, and reports what it could not
find. Fetching is restricted to an allowlist of hosts, which closed a server-side
request forgery that predates this release: a member-supplied `cover_url` was fetched
with redirects followed and no host check.

**The service worker no longer pins a broken cover for a month.** It cached
cross-origin covers `CacheFirst` with no restriction on what may be stored, and an
opaque response cannot be told from an error, so one failed fetch blanked a cover for
thirty days. Now `StaleWhileRevalidate`, only 200s are stored, and the cache is renamed
so already-poisoned entries are dropped rather than inherited.

**A fourth reading status, did not finish.** Started, not finished, not going back.
Recording progress on such a book returns it to reading; nothing deletes the log.

**The library can be read as a table**, nineteen columns, sortable on what the API can
actually order by, with the choice remembered. Cards gained a fold out.

**The health probe can fail.** It ran `SELECT 1`, which on an already-open SQLite handle
is served from cache and issues no RPC, so this app stayed ready for 39 hours through a
total storage outage. It now performs a filesystem operation with its own timeout, and
answers 503 when storage cannot be reached. Set `timeoutSeconds` above 2 on any probe
that calls it: the Kubernetes default of 1 makes the check inert.


Where you are in a book, and something that chases the books that are out.

**Two migrations run on start**, in this order: `f7c2a1e50b93` creates the
`reading_progress` table, and `a3e94c0d15f8` adds `loans.notified_at`. Both are
additive, both have a working downgrade, and neither touches an existing row's
data. The second drops and recreates the partial unique index on open loans
around its batch step, because batch mode rebuilds a SQLite table by reflecting
it and that index coming back as a plain unique one would forbid ever lending a
book twice.

### Added

**Reading progress.** Record the page you reached, or a percentage for an
audiobook or anything with no page count, as often as you like. It is an
append-only log rather than one editable number, which is what lets it answer
"how much did I read in March" as well as "where am I". Each entry can carry how
long the sitting was. The first entry on an unstarted book moves it to reading
and stamps the date, because saying where you are is the same claim the status
button makes; nothing ever moves a book to read on a page number, since page
counts come from catalogues and are off by one often enough that the last page
proves nothing.

A member's log is theirs. Two people reading the same copy see their own
positions and never each other's, on a shared shelf as much as a private book.

**Pages read, by month**, on the stats page. Computed from the differences
between consecutive positions, and covering page-tracked books only: an
audiobook records a percentage, and turning that into a page count would produce
a figure that adds up with the others while meaning something else.

**Overdue reminders, by webhook.** Endpaper can POST a digest of every overdue
loan to an address you choose, hourly, signed with HMAC-SHA256 so the receiver
can check it really came from here. How many days pass before the same loan is
chased again is yours to set. A generic webhook rather than email or one chat
service, because a self-hosted app should not carry an integration with
something only one household runs.

**Private books are never in it.** A webhook has no account behind it and lands
in a channel everyone reads, so a private title there would be readable by all
of them. The digest says how many it left out without naming one, and the owner
is still chased in the app, where the overdue view is per member. The settings
screen says this in words rather than leaving it to the documentation.

There is a **Send now** button beside the settings, which runs the digest
immediately and says what happened: sent, and to how many loans; or which of the
four reasons it sent nothing, because a switched-off toggle, a missing address, a
quiet week and a webhook that refused the request are four different problems and
only one of them is not a problem. That is what makes the feature checkable by a
person, and it is the endpoint to point an external cron at:
`ENABLE_OVERDUE_TICKER=false` turns the in-process timer off.

### Fixed

**A backup taken before this release still restores.** Adding a table to the
archive would have made every older backup fail with "the backup is missing:
reading_progress", because the restore required every table it knew about to be
present. A table added after format version 1 is now optional and restores as
empty, while a truncated archive missing `books` is refused as before.

**A restore now reports the reading statuses it put back.** `user_books` was
absent from the report, so a restore that dropped every member's entire reading
history read as a clean one. It is counted now, along with the progress log.

**Covers are downloaded and served from here, not linked to somebody else's
server.** A hotlinked cover needed five things to keep working: the image
service being up, the URL not rotting, this app being able to reach it, your
browser being able to reach it, and the content policy permitting it. Four of
those five are outside this application, so a shelf could go blank for a reason
nothing here could see or fix. Measured on the running deployment, the covers
directory held **zero** files, so that described every cover in the library. It
also stops your browser telling `covers.openlibrary.org` which books the
household owns, once per book, every time the grid draws.

Every way a book gets added now resolves a cover, including **the CSV import,
which never did**: a library that arrived that way showed the placeholder on
every single book and nothing in any log said why. The import itself does not
fetch, because a fetch per row over thousands of rows would hold the request
open until a proxy gave up on it. **Settings has a Covers section** that fetches
the ones that are missing, a hundred at a time, six at a time within that, and
tells you how many it stored, how many had a cover that could not be downloaded
from here, how many no service has one for, and how many are left. Each press
carries on from where the last one stopped, so a book that cannot be fixed does
not block the ones behind it, and reaching the end starts over. It is safe to
press twice. If a download fails the remote link is kept, so
the worst case is what the app did before.

**A cover URL nobody could parse used to break the repair button for everybody.** A URL
with an impossible port, like `:99999`, was accepted onto a book and then crashed every
attempt to fetch it, for every member, permanently, because one bad row is enough. It is
refused up front now, and a cover failure of any kind can no longer fail the request that
provoked it: adding a book always saves the book.

**Covers must come from one of the four image services this app knows about.**
`cover_url` can be typed by anybody with an account, and adding a book makes the
server fetch it, so without a host check that was an account holder choosing
which address this server connects to. Redirects are followed by hand, two hops
at most, and every hop is checked. The blind version of that predates covers
being stored at all.

**A fourth reading status: Did not finish.** Started, not going to be finished.
The date you started is kept, because that happened; the finish date is cleared,
so a book you gave up on is never counted in "books finished this year", and the
record of how far you got is left exactly where it is. Recording a new position
puts the book back to reading, because that is what picking it up again is.
Goodreads and StoryGraph shelves called `abandoned`, `dnf` or `did-not-finish`
all import onto it.

**Library cards fold out.** Title, author and up to three tags with the genre
first; press Details for the series, year, publisher, shelf, format, condition,
page count, the remaining tags and what the copy cost, without leaving the grid.

**A table view for the library**, toggled beside the sort control and remembered
in your browser. Nineteen columns of metadata, sortable on the ones the server
can order by, scrolling inside its own box so the page never slides sideways.

### Fixed, in the app

**Covers that had gone are back, and the cause was in your browser.** This is the fault
that was reported, and nothing on the server was wrong: the library had a cover URL on
every book, three of the four answered with a real image when fetched from the server, the
content policy allowed the host and DNS resolved it. The offline cache was storing cover
images with `CacheFirst` and no check on the response. A cross-origin image request cannot
tell a 404 from a picture, so a failed cover was cached as though it were one, and
`CacheFirst` then served it for **thirty days** without ever asking again. Covers are now
revalidated in the background, an error is never stored, and the cache has been renamed and
the poisoned one deleted, so the fix reaches browsers that already have the bad entries. It
also now covers all four image services rather than Open Library alone.

**The Goodreads lookup can be found.** It was a 14 pixel chain-link icon at 60%
opacity beside the title, with no label. It has moved down to the actions, with
its own words, at a contrast the rest of the app holds to.

**The health probe now detects the failure it was written to detect.** During a
total storage outage on 2026-08-22, `/api/healthz` answered 200 continuously and
the pod stayed ready for **39 hours**. `SELECT 1` on an already-open SQLite
handle is served from memory and never reaches the disk, so it could not fail in
the mode that mattered. It now also stats the data directory, which has to cross
the wire, under a timeout of its own so a hung mount is a failed check rather
than a handler that never answers.


## v0.4.0

Seven palettes, ten wallpapers, and a screen to choose them on.

**v0.3.0 was never released.** Its section below is a true record of what landed,
but no tag and no image were ever published for it, so there is nothing to
upgrade from. This release contains both, and upgrading from v0.2.1 goes
straight here.

**Two migrations run on start**, in this order: `c4d8e91a2f60` adds the three
appearance columns to `users`, and `e6f1a94b2d73` adds the flag that marks an
admin-created test account. Both are additive, both have a working downgrade,
and neither touches an existing row's data.

### Added

**Appearance is something you pick, at `/settings/appearance`.** A palette, light
or dark, and a wallpaper, applied the moment you choose and saved to your
account, so the look follows you from your laptop to your phone. Its own screen
rather than a row in the settings list, because the only honest preview of a
wallpaper is the page: the pattern is painted behind everything, so the picker is
the app with the controls laid over it. The preview on top of it is your own
first two books, not invented sample content.

**Seven palettes.** Endpaper, Catppuccin, Rose Pine, Gruvbox, Solarized,
Everforest and Nord, each in light and dark. The colours belong to their
projects; the lightness of each rung belongs to this app, so every palette clears
the same contrast floors rather than shipping whatever the upstream editor theme
happened to publish. Every correction, with the contrast that forced it, is
tabulated in `docs/theming.md`. Nord publishes no light theme, so its light
member is built here from Snow Storm and Polar Night, and the picker says so on
the tile rather than greying out a control every other palette leaves alone.

**Ten wallpapers, in two families.** Five after William Morris (Willow Bough,
Acanthus, Pimpernel, Strawberry Thief, Golden Lily) and five decorated papers
(Nonpareil, Seigaiha, Asanoha, Plait, Khatam). They are drawn rather than
shipped: every tile is generated in the browser from the palette's own ink, so a
pattern costs no download and follows whatever colours you chose. **None** and
**Surprise me** are tiles beside them, and a new account starts on Surprise me.

**Licences on the screen that offers them.** Six MIT notices and the note that
this project is not affiliated with Morris & Co.

**Test accounts an admin can switch into.** Sign in as any member from the
settings page to see the library as they see it, and come back the same way. The
query cache is dropped on every change of account, so nobody's private books
survive the switch.

**A top bar instead of a left rail**, and **lending to somebody who has no
account**: both landed before this release was tagged, and are described under
v0.3.0 below.

### Fixed

**The wallpaper no longer arrives a frame late.** The palette, the mode and the
pattern are applied together before React mounts, rather than the first two
synchronously and the third from an effect. Nobody noticed while the pattern was
faint and never changed; a picker makes it the first thing you watch for.

**Muted text on a light card was below AA.** `paper-400` and `paper-500` measure
2.35:1 and 3.83:1 against the card where WCAG wants 4.5, and were text in
fourteen places. A test now fails the build if either is used as light-mode text
again.

**One rose did both "want to read" and "delete".** They are separate colours now,
because a colour that means both a pleasure and a danger means neither.

**The green success message failed AA on every palette.** `text-green-600`
measured 2.79 to 3.22 against 4.5; it is `text-green-800` now, measured 6.19 to
7.13.

**Twenty-one controls drew their own focus ring**, at 2.24:1 against a page where
WCAG 1.4.11 wants 3:1, and sixteen of them killed the browser's own first. There
is one ring now, and a test that keeps it that way.

**More contrast was honoured on the default palette only.** The
`prefers-contrast: more` block was outranked by every palette block, so six of
the seven silently ignored it. It also turns the wallpaper off, and the picker
says why rather than showing an off state nobody chose.

### Changed

**Tag pills are no longer colour coded by category.** The category is written on
the pill, and the three hues cost fifteen tokens per mode to say the same thing
twice. A tag the household invented keeps the accent, which is the one
distinction with a reason.

## v0.3.0

Four bug reports, and what fixing them turned up underneath.

### Fixed

**No cover appeared on a German shelf.** Every stored cover was blocked by the
browser, with a 200 on the record and nothing in any log. `covers.py` resolves a
978-3 ISBN through the DNB's cover service, and that host was never added to the
Content-Security-Policy, which was a hand-written list beside it. The policy is
now derived from the one list of hosts, and a test walks the AST of every backend
module to keep cover URLs from being written anywhere else: `metadata.py` held six
of them, which is the door the same bug would have come back through.

**Google Books thumbnails could not render either.** Google serves them over plain
http, which is mixed content on an https page and blocked whatever the policy
says. They are upgraded on the way in, on every path that stores a cover, and a
one-shot migration upgrades the rows already stored.

**A cover that failed to load took the layout with it.** The old handler removed
the image from the flow, which collapsed the book page's header to nothing and
dropped the back button on top of the title. Every cover in the app now falls back
to the same placeholder, at the same size.

**The back button did nothing on a deep link.** It was `navigate(-1)`, and a
shared link, a reload or a PWA cold start has no prior entry to go back to. It now
goes back where there is somewhere to go, and to the library where there is not.

**Registration refused the attempt and charged you for it.** Under `ldap` and
`proxy` auth the rate limiter ran before the refusal, so an anonymous caller could
exhaust a real budget on a route that can never succeed. The refusal also told
proxy deployments their accounts were "managed by the directory", where there need
not be one.

**A backup restored covers the browser blocks.** A restore inserts through Core,
so the column validator never fired. It calls the upgrade itself now.

### Added

**Lend to somebody who has no account.** A neighbour, a colleague, a book club.
The borrower is either a member or a typed name, exactly one of the two, enforced
by a CHECK constraint rather than by the schema alone, because a restore and an
import do not go through the schema.

**A top bar instead of a left rail.** Library, scan and loans stay on the bar as
icons; everything else moved into a menu behind the account trigger, which still
names the person signed in. The rail spent 56px of a phone's width on every screen
and had nowhere to open a menu into. Under proxy auth the menu no longer offers
sign out or switch account: the upstream owns the session and both were inert.

**A network failure says so.** A rejected request used to print the browser's own
"Failed to fetch", untranslated, to whoever was standing in a tunnel.

### Security

A cover URL is now required to be `https://` or one of our own uploads. Nothing
was exploitable through the values this rejects, and all of them become
exploitable the day `img-src` gains a wildcard or a cover is rendered outside an
image tag.

### Tested

The login and registration flow through the HTTP routes and the UI in all three
auth modes, which had thorough unit tests for the backends and nothing for the
routes.

## v0.2.1

Documentation only. No code change, and the image is a rebuild of the same
source.

The README's feature list had fallen behind what v0.2.0 actually shipped. It
omitted **per-book privacy**, **series gap detection** and **duplicate merge**,
which are three of the things this project does that most alternatives do not,
and said nothing about rapid scanning, ratings and notes, due dates and overdue
loans, bulk edits, saved views, statistics or the health endpoint. It also still
said the first account to *register* becomes admin, which stopped being the
whole story once proxy and LDAP deployments got an admin bootstrap.

Rewritten and grouped, and it now links the changelog.

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
