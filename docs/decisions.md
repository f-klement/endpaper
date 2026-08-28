# Decisions

Things that look wrong, redundant or old-fashioned until you know why. Read the relevant
entry before "fixing" one.

## Backend

### `bcrypt` directly, not `passlib`

`passlib` is unmaintained and its last release predates modern `bcrypt`, which is why the
dependency list used to pin `bcrypt==4.0.1`. That pin blocked every security update to the
library doing the actual hashing.

`auth.py` now calls `bcrypt` directly. The hash format is unchanged (passlib was only ever
delegating), so **existing passwords keep working**, proved by a regression test holding a
hard-coded pre-migration hash.

One wrinkle this exposed: bcrypt hashes at most the first 72 bytes. The C implementation
truncates silently, the Python binding raises. `auth.py` truncates explicitly, reproducing
the old behaviour rather than turning long passwords into 500s.

### Settings are functions, not module constants

`config.py` exposes `secret_key()`, `registration_enabled()` and friends rather than
constants. `ALLOW_REGISTRATION` used to be read once at import, which made it untestable
without reimporting and meant closing signups needed a restart. Reading per call costs
nothing at this scale.

`DATA_DIR` is the deliberate exception: resolved once at import, because the directory must
exist before the app starts serving from it.

### `DATA_DIR` exists at all

Paths were hard-coded to the in-container `/app/data` in three modules, which made the
backend impossible to run or test outside a container.

### `visible_to()` is a function

It must be applied by every query that returns or counts books, and a predicate retyped at
six call sites is one that will eventually be forgotten at one of them. Note the
`.is_(False)` rather than `not Book.is_private`: the latter evaluates the Column's Python
truthiness and collapses to a constant, quietly matching every row. It looks more idiomatic
and is completely wrong.

### The Shelf owns the privacy rule, and the AST guard is gone

`backend/shelf.py` is now the only module that imports `visible_to` or `in_trash_for` and
the only one that builds a query over `Book`. A caller asks `Shelf.seen_by(db, member_id)`
and narrows what comes back, so **visibility is a property of how the query was built**
rather than a step each endpoint has to remember.

**A deleted guard with no record reads as a regression, so this is the record.** What was
deleted is `test_models.py::TestEveryBookQueryIsFiltered`, 681 lines that walked the AST of
every backend module, tracked scopes and bindings through `symtable` to accept a predicate
bound to a local, carried five `# visible_to exempt:` comments, and had a second test
parsing its own docstring to count them. It was good at its job. It was also scar tissue
over a missing seam: `dependencies.py` had owned the rule for **one** book since the round
that found fourteen endpoints with no check at all, and nothing owned it for **many**,
which is exactly where the leaks were. `list_tags` counted books unfiltered and disclosed
which tags existed only on somebody's private books.

What replaced it is `test_shelf.py::TestTheShelfIsTheOnlyWayIn`: four flat `ast` passes
asking who imports the predicate, who builds a query naming `Book`, and who reaches `books`
through a join. It resolves which local names mean `Book` first, so an alias or a rebinding
is caught, and it carries five short allowlists rather than five opt-out comments. What it
does not need is the scope and binding machinery the old guard was built from, and the
reason is structural rather than clever: outside `shelf.py` the correct answer is zero, so
there is no "was a predicate applied here" question left to answer.

**It is wider than what it replaced, and the first version of it was not.** That is worth
recording in full, because it is the round's most useful finding and both critics reached
it independently.

The rule shipped for review as two regexes over the source. It claimed to close the old
guard's documented blind spot: a statement reaching the table through `.join(Book, ...)`
while naming no `Book` inside `query()`, of which the old docstring recorded **10** in the
tree. The claim was false, and four shapes were measured passing it clean, each of them a
location index publishing a name and a count over every Member's Private Books:

| Shape | Old regexes |
|---|---|
| `db.query(Loan.id, Book.title).join(Book, ...)` | passes |
| `db.query(models.Book.location)` | passes |
| `db.query(B.location)` after `from models import Book as B` | passes |
| `db.execute(sa.select(Book.location))` | passes |

**A guard whose limits are undocumented gets read as a guarantee it never made, and this
one documented the opposite of its limit**, which is worse than the hole.

It is now a small `ast` pass instead: resolve which local names are bound to `Book`, then
report `query(...)` or `select(...)` mentioning one, and `.join(Book, ...)` separately.
All four shapes are caught, and `test_the_rule_catches_every_evasion_that_defeated_its_first_version`
keeps them caught. It is still nothing like the guard it replaced: that one tracked scopes
and bindings through `symtable` because a predicate could be applied anywhere and it had to
decide whether it had been. Here the answer outside `shelf.py` is always zero, so there is
nothing to decide.

Teaching the **old** guard the join shape was costed at 30 inspected statements to 40, for
four fresh exemptions on correct code, and refused on that arithmetic. The same widening
here costs **one allowlist entry**, `notifications.py`, because it is the only module in the
tree taking that shape. That is the difference the seam makes: the same rule is cheap once
the correct answer is zero. (The quotes entry below states that old measurement as 30 to 39
for three exemptions. The two disagreed in the tree before this refactor and the guard that
could settle it is gone, so both are recorded rather than one being picked.)

**There is a third way past a viewer, and it is not in this module.** `backup.py` reads
every row of every table through `db.query(model)` on a loop variable, so no rule that reads
the arguments to `query()` can see it, including the one above. That is deliberate: a backup
omitting everyone else's Private Books would restore to a Library missing rows. It is
unfiltered on purpose and admin only for that reason, and it is asserted by name in
`test_shelf.py` rather than left to pass silently, because "the only place that reads past a
viewer" was written in three documents before anybody counted.

**It is narrower in two ways**, stated for the same reason. It cannot tell a module
importing `Book` for a `db.get(Book, id)` or a type annotation from one importing it to
build a listing, which is why it tests query shapes rather than the import of `Book`. And
it cannot see a query built from a variable rather than a literal, which is the `backup.py`
case above.

**`Shelf.select()` anchors the FROM at `books` and that fixes the join direction only.** It
was documented as preventing the cartesian product that a query naming two tables and
joining neither produces. Measured: `db.query(Tag.name).filter(visible_to(1))` compiles to
`FROM tags, books` and `Shelf.seen_by(db, 1).select(Tag.name)` compiles to `FROM books,
tags`. Two FROMs either way. The limit is now pinned by a test rather than claimed away,
and `where()` carries the same warning, because it is the more used method and had none.

**The five exemptions became two named functions, because they were two rules.** Four were
about uniqueness (`whole_table_for_uniqueness`): the ISBN and copy-group constraints span
the whole table, so a clash with a book the caller cannot see is still a clash, and
filtering would miss the row that collides and turn a 409 into a 500. One was a re-read
(`rereading_filtered_rows`): the ids came out of a filtered query and it repopulates a
relationship on objects already in hand, so it takes ids rather than criteria and cannot
quietly become a way to read the table. Designing those as one escape hatch was the
obvious mistake and is the reason they are two.

**`notifications.py` is deliberately outside all of it**, and is named in the rule rather
than left to pass quietly. The overdue digest runs on a schedule for the library, so it has
no viewer to be scoped to, and its two halves **partition** on privacy rather than
filtering by it: `is_(False)` for the reminders it sends and `is_(True)` for the count of
what privacy held back. A Shelf would have to mean both at once, which is what
`in_trash_for` being a separate function from `visible_to` exists to avoid.

**`select()` refuses a shelf narrowed by read status**, which is worth knowing before
somebody removes the check. Every narrowing is a clause except that one, which is an outer
join to `user_books`; `select()` rebuilds a query over other columns from the accumulated
clauses, so on a joined shelf it would silently drop the join and return every book instead
of the unread ones. A wrong answer, not an error, hence the explicit refusal.

**Why now rather than with the peer sync work.** That work introduces `shareable_to_peer()`,
a second predicate over the same queries. One adapter is a hypothetical seam; two is a real
one. Doing this first makes that one change behind one interface instead of the same
migration twice, the second time across a wider surface.

### Book access lives in dependencies, not in handlers

See [security.md](security.md). Endpoints ask for a book through `book_for_read` /
`book_for_write` / `book_for_owner` rather than fetching one and writing their own checks,
because when they wrote their own checks, fourteen of them wrote none at all.

### Login has its own schema

`LoginRequest`, not `UserCreate`. Registration's 8-character floor must not apply to
sign-in, or every account created before the policy is locked out. A 422 "too short" also
leaks that the stored password is short.

### `covers.py` is the only module that knows an image host

`COVER_HOSTS` in `covers.py` is a tuple of hosts, and `middleware.py` builds the CSP's
`img-src` by joining it. That looks like indirection for its own sake until you know the bug
it comes from: the two used to be written separately, `covers.py` learned to resolve German
ISBNs through `portal.dnb.de`, the policy never did, and **every cover on a German shelf was
blocked by the browser** while the stored record looked perfectly correct. Nothing appeared
in any log.

Deriving one from the other is only half of it. `metadata.py` also held six hard-coded cover
URLs, five of them `open_library_url()` copied verbatim, so a new source could have
reintroduced the same bug through a door the CSP change did not close. Every builder now
lives in `covers.py`, and `tests/test_covers.py` walks the AST of every backend module and
fails on a `cover_url` assigned from a URL literal anywhere else.

### A stored cover must be https, or one of ours

`covers.https_url` upgrades `http://` on the way in, because Google Books serves its
thumbnails over plain http and an http image on an https page is mixed content: the browser
blocks it whatever the CSP says, so the book gets a cover that is correct in the database
and invisible in the app.

`covers.is_renderable` then refuses anything that is neither `https://` nor `/covers/`.
Nothing in the app can be exploited through the values that rejects (`javascript:` is inert
in an image tag, an SVG rendered through one cannot run script, and `//host` is refused
because `img-src` lists no bare-host wildcard). It is refused anyway, because all three
become live the day `img-src` gains a wildcard or a cover is rendered anywhere but an
`<img src>`, and neither of those changes would remind anybody of this one.

Both rules together are `covers.storable`, and that function exists because they were three
copies of the same two steps. Two of the three repaired the upgrade half of a bug and left
the acceptance half open, which is a gap that looks closed from either end: the two reviewers
of this change found exactly that, independently, and neither found it by reading the code
that had it. One function, three callers, three different reactions to the same answer:
`BookCreate` refuses with a 422, the `Book.cover_url` ORM validator drops and logs (the
backstop for the five writers with no schema in front of them), and `backup.restore` calls it
directly because a Core insert does not fire `@validates` at all.

Migration `b8e2f04c17aa` applies the same match to the rows already stored, for the reason
the migration exists at all: nothing rewrites an old row, so nothing else would ever refuse
one. `data:` is still listed in `img-src`, so a legacy row carrying one does not merely fail
to load.

### The fourth reading status is "Did not finish", not "Abandoned"

Started, not finished, and not going to be. The two self-hosted apps that ship this shelf
were both checked rather than taken on trust: **Openreads** describes its fourth list as
"books you didn't finish", and **BookLogr** ships a predefined list called "Did not finish".
**Neither calls it "Abandoned"**, so that name was rejected: a third spelling of the same
shelf costs a reader a moment every time they meet it, and matching the two apps costs
nothing.

The enum member is `DID_NOT_FINISH = "did_not_finish"`, which also keeps the existing
convention (`want_to_read` is already a three-word value in that column). The German label is
**"Abgebrochen"**, not a literal rendering of the English: it is what a German reader says
about a book they gave up on, and it fits a pill.

The importers accept `did not finish`, `dnf`, `abandoned`, `gave up`, `unfinished`,
`stopped reading`, `abgebrochen` and `nicht beendet`, because Goodreads users file this as a
custom shelf and StoryGraph as a status and both spellings turn up in the same export folder.
"finished" stays READ and "unfinished" is DID_NOT_FINISH: the match is exact after
normalising separators, so no prefix rule has to get that pair right.

**Recording progress promotes it to READING.** `add_progress` promotes from UNREAD and
WANT_TO_READ and deliberately does not promote from READ, which is a re-read. Did not finish
is the third case and it promotes, because it is a claim about the past and a new position
contradicts it: leaving it alone would have the shelf say "gave up on this" while the log
says "reached page 240 this morning". Picking an abandoned book back up is the case the
status exists for. The earlier progress rows are untouched, and `finished_at` is already null
and stays null, because READING is not READ.

**It needed no new rule in `_stamp_reading_dates`**, and that was checked rather than
assumed. It is a claim that reading started, so it joins READING and READ in stamping
`started_at`; it is not a finish, so the existing `else` already clears `finished_at`. What
it must never do is fall into the UNREAD/WANT_TO_READ branch, which clears `started_at`:
that would erase the fact the book was ever picked up. It deletes no `reading_progress` row
either, because how far somebody got before giving up is the interesting part.

**No migration.** `user_books.status` is a plain `String(20)`, so a new enum member is a new
value in a text column and every existing row is untouched. Confirmed against `models.py`,
not assumed from "it is a StrEnum".

The status pill is drawn from the **paper ramp**, not from `bloom` or `danger`. Giving up on
a book is neither an error nor an achievement, and a rose pill would make the shelf look like
it was reporting a problem.

`paper-800` on `paper-200` rather than the `paper-600` the `unread` pill uses. Measured across
all seven light palettes with the same formula `tests/theme/palettes.test.ts` uses:

| Pair | Worst | Where | Best |
|---|---|---|---|
| `paper-600` on `paper-200` | **3.55:1** | solarized (then 3.56 nord, 3.87 catppuccin) | 4.71 default |
| `paper-700` on `paper-200` | 4.19:1 | solarized | 7.32 default |
| `paper-800` on `paper-200` | **4.57:1** | catppuccin | 11.35 default |
| `paper-200` on `paper-800`, dark | 5.57:1 | everforest (then 6.31 catppuccin, 6.43 gruvbox, 7.09 nord) | 11.35 default |

Only the 800 pairing clears 4.5 on every palette, so that is the one, and
`tests/theme/palettes.test.ts` holds it there in both modes.

**Two figures in earlier drafts of this table were wrong, and the corrections are worth
keeping.** The first claimed 4.19:1 for `paper-600` on `paper-200`, which is in fact the
`paper-700` figure; the 600 pairing is 3.55:1. The second attributed the dark row's 5.57:1 to
nord, where it belongs to everforest (`#d3c6aa` on `#3d484d`); nord is 7.09:1, three rungs up
the sorted list. Neither changed a conclusion, and that is the point: a number in a table like
this one is a thing the next person re-measures, and one that corresponds to nothing costs
them the time to find out why. A row is not finished when the figure is right, only when the
figure and the palette it came from are both right.

**The `unread` pill is under the floor and this change did not put it there.** As it actually
draws, `paper-600` on `paper-200` at 70% over the `paper-0` card, it measures **3.97:1 on
solarized**, 4.02 on nord and 4.27 on catppuccin. It is left alone deliberately: a status
pill's colour is one decision across five values, and a change that owns one of them should
not quietly restyle the other four. Recorded here so it is a known debt rather than something
to be rediscovered, and the test added with `did_not_finish` pins that pill only.

### The built files state a cache lifetime, and only hashed names get a long one

Starlette's `StaticFiles` sends an ETag and a Last-Modified and no `Cache-Control` at all
(measured: every path, shell and asset alike). That leaves each file to the browser's
*heuristic* freshness, which is a guess, and it is the wrong thing to leave the app shell
to.

`main.CachePolicyStaticFiles` sets one header per file, on one rule: **a name that changes
with its content may be cached, and a name that does not must be revalidated.** Only
Vite's `assets/` is content addressed, so it gets `public, max-age=31536000, immutable`
and everything else gets `no-cache`: index.html, manifest.json, sw.js, registerSW.js and
the icons all keep their names across builds while their bytes change.

The reason for the shell is a deploy, not a session. A heuristically fresh index.html
names its scripts by content hash, and a deploy deletes the hashes it no longer builds, so
a reader holding yesterday's shell requests `assets/index-<hash>.js` and gets a 404: a
blank page after a release with nothing wrong on the server. It is **not** a second
instance of the endless-spinner bug, and claiming it would be would not survive scrutiny:
both recovery paths there already reach the network, since signing out navigates to
`/login`, a URL no cache entry answers, and a reload navigation is fetched with cache mode
`"reload"`, which skips the freshness check by specification. The service worker fault was
worse precisely because the precache answered the reload as well.

`no-cache`, not `no-store`. `no-cache` means "ask before reusing", not "do not keep": the
copy stays and the ETag turns the next request into a 304 with no body. `no-store` would
throw a working conditional request away for nothing.

Three details worth keeping. The policy is set on whatever `file_response` returns, so the
304 carries it too; Starlette copies only a fixed set of headers onto a 304, and one that
dropped the policy would leave the next request reading a cache entry with nothing on it.
It is a `StaticFiles` subclass rather than middleware, because middleware on this app would
see every response including the API's and would have to re-derive which came off the disk.
And the mount goes through `mount_spa()` so the suite drives the wiring production uses:
swapping the class back for a plain `StaticFiles` has to fail a test, and it only does if
there is one mount.

### The mount serves the shell for a client route, because `html=True` does not

`html=True` answers `/` and a directory with `index.html`, and answers everything else 404.
It was taken for `main.py`'s comment, `docs/architecture.md` and this file all to say the
mount was a catch-all, and it never was. Measured in the running container with a valid
session: `/` and `/index.html` 200, `/book/12`, `/settings` and `/quotes` **404**. A
bookmark, a refresh anywhere but home, and a shared link to a book were all broken, and the
published documentation promised they worked.

`CachePolicyStaticFiles.get_response` answers an unmatched path with the shell under three
conditions, each of which is a way this could have gone wrong:

| Condition | What it prevents |
|---|---|
| Not `/api/*` or `/auth/*` (`wants_html` refuses them) | An API typo answering 200 with HTML, which is what `_fallback` was written for |
| The request accepts `text/html` | Code asking for a missing path being handed a page instead of a 404 |
| Not under `assets/` | A stale shell's missing chunk arriving as HTML inside a script tag, which is a parse error rather than a clean failure |

The shell goes out through `file_response`, so a deep link carries the same `no-cache` that
`/` does; without that it would be cached under its own URL.

Not keyed on the path having a file extension, which is the usual shortcut for this:
`/authors/J.R.R. Tolkien` is a real client route.

**The fallback cannot serve a requested path, by construction**, and that is a better
guarantee than the obvious one. It looks up `SHELL`, a module constant; the requested
`path` reaches the method only to be tested for the `assets/` prefix, and is never looked
up, joined or opened. So even a total failure of `lookup_path`'s containment check could
not turn this branch into a file read. The containment argument is true as well, verified
on the real mount with twelve escape shapes and three symlinks pointing out of the tree,
all fifteen answering the shell and none the planted sentinel, and the symlinks are the
sharper half of it because `realpath` plus `commonpath` reject a file that genuinely
exists. But it depends on Starlette continuing to behave that way, and the structural
argument depends on nothing outside the six lines.

Three consequences worth writing down.

A `POST` to an unmatched path is **405**, not 404: Starlette's answer for any method the
mount does not serve, which predates this and which the `except` re-raises, so a write
never reaches the shell branch. Behind the real error handlers that 405 *is* an HTML page,
this app's error template. What matters is that it is not the shell.

A path that tries to escape the root (`/%2e%2e%2fmain.py`) now answers 200 with the shell
where it used to answer 404. It is an unmatched path like any other, and the standard SPA
trade.

**Every probe now answers 200 where it used to answer 404**, so the status differential a
scanner reads is gone for this host, and so is the 404 burst a rate-based detector keys on:
CrowdSec will stop seeing them from this app. That is detection, not containment, and it is
inherent to serving an SPA fallback rather than anything specific to this one. Recorded so
that nobody reads the silence as quiet.

Two smallest-fixes were held rather than taken, because they treated the symptom of this
one. `endSession()` sends the browser to `/login`, which was a 404 in `local` and `ldap`
mode, the default and what the published image runs (behind a forward-auth portal the
portal answers `/login` first, which is why it never showed up in the deployment this was
diagnosed against); `LOGIN_PATH = "/"` would have worked, since the signed-out shell
renders the login page for `path="*"`. And `reauthenticateAtEdge`'s `reload()` would have
had to become `assign("/")` for the same reason. Both are unnecessary now, and `reload()`
is better than `assign("/")` because the reader lands back where they were.

### `SERVE_FRONTEND=false` is a flag on one image, not a second image

Half of headless already existed by accident: the mount happens only when
`backend/static/` is a directory, which is how the dev server runs while Vite serves the
frontend. The shipped image always contains that directory, so absence never happened in
production and there was no way to ask for it.

A host with no reader is the case that wants it. It has no members, no library and nobody
to show a page to, so the shell, the asset routes, the SPA fallback and the cache policy
that goes with them are attack surface with no user.

**With the frontend off the SPA fallback never engages, and an unmatched path is a plain
404 again. That is correct rather than a regression**, and it is asserted
(`TestTheFrontendCanBeSwitchedOff`) so nobody repairs it back: the fallback exists so a
*client route* survives a refresh, and a host serving no frontend has no client routes.

Not a second image, not a build target, not a stripped dependency set. The compiled files
sit on disk unused, which costs nothing that is not already paid for by shipping one image.
If image size ever becomes the reason to do it properly, that is a separate argument with
a separate cost.

The two ways to end up API-only are logged apart, because in a running container a relay
that was meant to serve the frontend and a build that failed to copy look identical
otherwise.

### The health probe touches the database, and that was not enough

The original reasoning stands and is left here because it is right as far as it goes. The
Kubernetes probes used to request `/`, which the SPA mount answers from disk, so a pod whose
data volume never mounted stayed Ready and kept taking traffic while index.html was still
readable. Touching the database is the whole point, so `healthz` runs `SELECT 1`.

**It does not detect the failure it was written to detect.** Measured on the running
deployment during a total NFS outage on 2026-08-22: `/api/healthz` answered 200 continuously
and the pod stayed 1/1 Ready for **39 hours** while the data volume was unresponsive to every
new namespace operation. Verified at 12:35:11 +02:00, mid-outage.

The shallow reason is that `SELECT 1` on an already-open SQLite handle is served from the
page cache and issues no RPC, so the query crosses no wire.

The reason worth keeping is larger: **the probe could not fail in the mode that matters.** A
hung NFS call blocks in uninterruptible sleep and never returns an error, so storage death can
only ever reach a probe as a *timeout*. A handler that never reaches the mount never times
out. Readiness built on a long-lived handle measures the process, not its storage. An
unmounted volume was catchable; a hung one was not, by construction.

Both halves of the fix are needed:

1. **A `stat` of the data directory**, which is a namespace operation and therefore has to
   cross the wire. The query stays: it catches a corrupt or missing database, which the stat
   does not.
2. **Its own timeout**, `STORAGE_TIMEOUT_SECONDS`, at 2 seconds, which must stay comfortably
   under the deployment probe's `timeoutSeconds`. Without it the endpoint simply stops
   answering, and some probe configurations treat that as a hang rather than a failure, which
   makes the diagnosis harder rather than easier.

**The chart is not in this repository, and it currently defeats this.** The deployment sets no
`timeoutSeconds`, so both probes use the Kubernetes default of **1 second**, which is shorter
than the handler's own 2. The kubelet gives up while the handler is still waiting, which is
precisely the hang-instead-of-failure this exists to prevent. `docs/api.md` states the numbers
a deployer has to set (`timeoutSeconds: 5`) rather than only the direction of the inequality,
because that is the document they will be reading.

**It is the liveness probe as well as readiness, and that is intended.** A hung mount now
restarts the pod, and the restarted pod blocks in `init_db()` on the same mount, so it stays
down and visible. That is the right outcome: a container in `CrashLoopBackOff` reaches every
alert a library has, where a pod that is 1/1 Ready and serving nothing reaches none of them,
which is the 39 hours this entry is about. It recovers by itself when the mount does.

The stat runs in a **dedicated single-thread executor that is never joined**, and that is not
tidiness. The thread that made a hung call is gone for the life of the process, and running
the stat inline would leak a thread from FastAPI's own pool on every probe until the app
answered nothing at all: a worse failure than the one being detected. A stat that has not
come back is also not re-queued behind itself, because a backlog of calls that will never run
is not a second opinion.

Recording the incomplete version beside the correction is the point of the entry. The record
of why a plausible fix turned out to be insufficient is worth more than a tidy one.

### The covers that "stopped appearing" were a service worker cache, not the server

This is the answer to the question the earlier entries recorded as unmeasured, and it is
worth stating plainly: **nothing server side was wrong.** Measured on the live deployment
once storage came back:

| Checked | Result |
|---|---|
| Books in the library | 4, **all four with a `cover_url` stored** |
| Those URLs fetched from inside the pod | 3 of 4 answer `200 image/jpeg` (8 KB, 21 KB, 30 KB); the fourth is a genuine 404 |
| The live CSP | `img-src` permits `covers.openlibrary.org`, `portal.dnb.de`, `books.google.com`, `*.googleusercontent.com` |
| DNS | Both resolvers answer for `covers.openlibrary.org` identically to a public one |

So the record was right, the network was right, the policy was right, and the images existed.
The failure was in the browser, in five lines of `frontend/vite.config.ts`.

Three faults, and the first is what made it stick:

1. **`CacheFirst` never revalidates.** Whatever landed in the `book-covers` runtime cache was
   served for **thirty days** with the network never consulted. That is why this reads as
   "they have all gone" rather than as something intermittent, and why it did not recover.
2. **No `cacheableResponse`.** A cross-origin `<img>` is not a CORS request, so the response
   is **opaque**: a 404 and a real image cannot be told apart by status. `CacheFirst` then
   pinned the 404 for a month.
3. **`cleanupOutdatedCaches: true` does not help**, and it is easy to think it does. It
   cleans *precaches* from earlier Workbox builds. A runtime cache survives every deploy
   under its own name, so shipping a fix would have helped nobody who already had the bad
   entries, which is precisely the person who reported this.

All three are fixed: `StaleWhileRevalidate` so a bad entry heals itself on the next view,
`cacheableResponse: { statuses: [200] }` so an opaque or error response is never stored, and
the cache renamed to `book-covers-v2` so what is already poisoned is orphaned rather than
inherited. Orphaned is not deleted, so `public/sw-cleanup.js` drops `book-covers` on activate;
`importScripts` is how a `generateSW` build reaches into the worker.

The rule now matches **all four** hosts in `COVER_HOSTS` rather than Open Library alone. There
was never a reason for the other three to be uncached; the pattern simply predated them.

That makes the service worker's pattern a **third** copy of the host list, after `COVER_HOSTS`
and the CSP that is derived from it, and unlike the CSP nothing ties it to the tuple. That is
a considered trade rather than an oversight: the two that are tied together are tied because
drifting apart **breaks covers**, silently and with nothing in any log, which is the incident
recorded further up. A host missing from this third list costs a cache miss. The cover still
loads, from the network, every time. A test to hold a build-time config file against a Python
constant would cost more than the failure it prevents.

**Two things this says about storing covers locally.** A `/covers/<id>.<ext>` is same origin,
so it is not matched by this rule at all and its responses carry a real status: fault 2
cannot happen to it. That is a reason to store covers beyond the ones already recorded, and
it is the reason the entry above no longer has an unanswered question at the end of it.

### A cover is stored here, not hotlinked

Every cover in the library used to be a URL on somebody else's server, and five separate
things had to keep working for a reader to see one: the image service being up, the URL not
rotting, the pod being able to reach it, the reader's own browser being able to reach it, and
the CSP permitting it. Four of the five are outside this application, so the grid can go
blank for a reason nothing here can see, log or fix. That is not hypothetical: it is the
reported failure this change answers.

**Measured on the running deployment before the storage outage: `/app/data/covers` held zero
files** (link count 2, unchanged since 18 August), so every cover the library rendered
depended on a third party being reachable from every reader's browser. There was no
half-migrated state to reconcile, which is why nothing here tries to.

So `covers.resolve_and_store` fetches the bytes once, and `cover_url` becomes
`/covers/<id>.<ext>`, served by the authenticated route that already applies `visible_to()`.

Four consequences worth writing down.

* **The remote URL stays as the fallback.** A failed fetch degrades to what the app did
  before, not to no cover. A URL the pod cannot reach may still load from a reader's browser.
* **The extension comes from the magic bytes**, never from the URL and never from the
  response's `Content-Type`. A cover from a third party is untrusted input, neither of those
  is evidence about the bytes, and `portal.dnb.de/opac/mvb/cover?isbn=` has no extension in
  it at all. Same rule and the same function as an upload.
* **The download is capped at `MAX_UPLOAD_BYTES`** and read in chunks, so a service answering
  with a stream that never ends is refused at the cap rather than filling the container.
* **`COVER_HOSTS` and the CSP are unchanged.** The fallback still renders remote URLs, so
  removing a host from the policy would break exactly the case this fallback exists for.

### The cover bytes are files on the volume, not a column

**Decided by the owner on 2026-08-22, after both sides were put to them twice.** Covers are
files under `COVERS_DIR`, named `<book id>.<ext>`. A `books.cover_blob` column was built and
withdrawn, so the alternative is not hypothetical: it was measured on this schema.

What decided it:

* **A BLOB on `books` is loaded by every `query(Book)` unless it is deferred.** That is a
  permanent hazard managed by a test (listing, export, stats, duplicates, series, backup)
  rather than one that does not exist.
* **The database sits on the NFS mount that deadlocked earlier today.** Measured, 40 KB
  covers at the default `page_size` of 4096: 100 books is 4.1 MB, 1,000 books is 39.8 MB and
  3,000 books is 119.2 MB, against 176 KB today. A 176 KB file is trivially copyable and
  recoverable; a 120 MB one mid checkpoint is the worst thing to own when that mount wedges.
* **A backfill writes the payload roughly twice**, through the WAL, all of it over NFS.
* **`FileResponse` can hand off to sendfile.** Reading a column pulls every image through the
  Python heap of a pod limited to 512Mi.

What it costs, which is real and is handled rather than waved at:

* **Orphan files.** A row delete does not delete a file. `_purge` calls `covers.forget`, so
  purging a book and emptying the trash both take the cover with them, and a merge moves the
  loser's file to the keeper when the keeper absorbed its `cover_url` and deletes it
  otherwise. `_trash` deliberately does not: a trashed book can be restored, and restoring
  one to a placeholder is a delete that half happened. All four paths have a test in
  `tests/routers/test_books_covers.py::TestTheDirectoryDoesNotDriftFromTheDatabase`.
  Getting this wrong is not only clutter: SQLite reuses an id once the highest row goes, so a
  leftover file becomes the next book's cover.
* **The column and the directory can drift.** So nothing trusts `cover_url` to decide whether
  a cover exists. `_store_cover` and the backfill ask the filesystem, via `covers.stored_ids`
  (one directory read for the whole library, not a `stat` per book), and a `/covers/<id>.<ext>`
  with no file behind it is treated as missing and re-fetched. That is also what makes the
  backfill safe to press twice.

`FORMAT_VERSION` stays at **1**: the backup envelope did not change, covers are the same
files under `covers/` in the same zip, and bumping it would refuse every archive a library
already holds for no reason.

### The cover backfill is every member's own, not the admin's

`POST /api/books/covers/backfill` is what repairs a library that already exists. Storing
covers on the way in only ever helps books added afterwards, and the books that need it most
are the ones that arrived through a CSV import, which never resolved a cover at all.

It is **not** admin-only, and that is deliberate rather than an oversight of the request that
asked for an admin action. `visible_to()` has no admin bypass, so an admin running a
privacy-scoped backfill could never repair another member's private books, and those books
would then have no way to be repaired at all. Bending the privacy rule to make an operator
action work is the worse of the two, so each member repairs the shelf they can see, and the
run is rate limited (`COVER_BACKFILL_LIMIT`, six a minute) rather than gated on a role.

The run is **bounded at 100 books** because it holds an HTTP request open while it fetches,
and it is a **cursor**, which is the part that makes "press again" mean anything. The batch is
the first hundred candidates by book id, and a book that could not be fixed is still a
candidate on the next run, so without carrying `next_after_id` back it would sit at the front
of every run for ever. Measured across ten ISBNs, only eight resolved to an image, so roughly
a fifth of any batch is permanently unfixable and accumulates; a pod with no egress produces
the same shape on the first run, where every book is unfixable and the counter never moves at
all. `next_after_id` comes back as 0 at the end of the library, so the next press starts over
and re-tries the failures, which a service that was down may since have made fixable.

The reply counts **`unreachable` separately** from `still_missing` for the same reason. A
cover that resolved to a URL this server could not download is neither stored nor absent from
the world, and folding it into either produced "looked at 100 books and stored 0. No image
service has one for 0", which reads as a clean no-op in exactly the situation the feature
exists for. It is concurrent
(`covers.MAX_CONCURRENT_FETCHES`, six at a time) because serial would be one round trip per
book. Only the fetch runs in the pool: the SQLAlchemy Session is not thread safe, so the
assignment happens on one thread. The results are matched to their books **positionally**,
which is correct because `ThreadPoolExecutor.map` yields in the order it was given its
inputs rather than in completion order. That is the property the `zip(..., strict=True)`
depends on, and it is worth naming, because a switch to `as_completed` would silently give
every book somebody else's cover.

**Threading the backfill made a correct helper elsewhere wrong**, which is the kind of
consequence worth recording where the decision was taken rather than only where it landed.
`uploads.replace_image` named its temporary file after the pid, and its comment said the pid
was what stopped two writes of the same book colliding. That held while the only concurrency
here was separate processes. It stopped holding the moment this pool existed: two overlapping
requests for the same book id in one process built the same path, one `os.replace` won and
the other failed ENOENT. The name now carries the thread id as well. Two members repairing a
shared book reach it, and so does one member inside their own rate limit.

The upper bound on `after_id` belongs to the same family. A Python int has no ceiling and
SQLite's does, so an unbounded `int` query parameter is a 500 out of the unhandled-exception
handler, which classes a bad request as a bug in our own code. Every other numeric query
parameter in this tree was already bounded at both ends; this one was new and was not.

It targets books whose `cover_url` is NULL or points at a third party, which is exactly the
set that rots. A locally stored cover is bytes on this volume. Running it twice is therefore
cheap and idempotent: the second run examines nothing it fixed on the first.

### The CSV import does not fetch covers inline

Every other add path stores a cover on the way in. The import does not, because it runs over
thousands of rows inside a single request and a fetch per row would be thousands of round
trips holding that request open until a proxy gives up on it. The books arrive without covers
and the backfill fills them in afterwards, concurrently and in bounded batches, which is the
same work with nothing waiting on it.

### The server checks which host it may fetch a cover from

`covers.is_fetchable`, derived from `COVER_HOSTS`, is applied in both `covers.download` and
`covers._check`, and both clients run with `follow_redirects=False` and walk redirects by
hand with `is_fetchable` re-run per hop.

The reason is that `cover_url` is member input on `BookCreate` and adding a book makes the
server fetch it: without the test, any account could point the pod at an address of its
choosing, be redirected into private space and down to plain http, and read an image-shaped
answer back out. `COVER_HOSTS` already existed as the source of the CSP's `img-src` and was
**never applied at fetch time**, which is the same drift the tuple exists to prevent, one
door along.

It is deliberately not `storable`. `storable` governs what a **browser** may be pointed at
and has to keep admitting any https URL, because a hotlinked cover is the fallback when a
download fails. This governs what **this server** may connect to. Two questions, two answers.

**The blind version predates covers being stored.** `resolve` has put a supplied URL at the
front of its candidate list and called `_check` on it since the check existed; storing the
bytes turned a blind request into a read primitive. Both call sites are fixed, because
fixing only the newer one would have left the older hole open and looked closed. Full detail
in `docs/security.md`.

### Five cover outcomes are counted, because they used to be indistinguishable

The only trace this area left was one WARNING in `Book._store_covers_over_https` for a URL it
refused. "Covers stopped appearing" could be the image service being down, the pod having no
egress, the browser blocking the request, the stored URL having rotted, or nothing being
resolved in the first place, and the log said the same thing about all five.
`covers.CoverOutcome` names them (verified, unverified, no candidate, downloaded, download
failed), each is logged at INFO with the ISBN or URL, and `covers.outcome_counts()` is
reported in the backfill's log line.

This was written while the deployment's storage was unresponsive, when the cause could not be
measured and nothing here would guess at one. It has since been measured: see *The covers
that "stopped appearing" were a service worker cache, not the server*. The counters stay,
because they are what will answer the next one without a browser in the loop.

### A test account is a column, not "auth_source is local"

An admin can create a local account with a password to see the library the way an
ordinary member sees it, and can exchange that password for a session on it. Two things
decide whether an account is one of those, and both hang off `users.is_test_account`
rather than off `auth_source`.

**What may be switched into.** `models.is_switch_target` is the rule, in one function,
applied where a switch is granted and again where a token is allowed to override a proxy
header. A directory-backed account is never a target in any mode: an admin who could mint
a session for an LDAP or proxy member could read that member's private books, and per-book
privacy is the single promise the data model makes.

A local account from before a deployment moved to a directory is also `auth_source =
local`, belongs to a real person, and must not be reachable this way. Under `ldap` and
`proxy` a local password is not an authentication path at all (`/auth/login` refuses), and
a switch that accepted any local row would quietly revive it. Hence the column: it says
"an admin made this for testing", which is the thing being asked about.

**What a directory identity may adopt.** `upsert_directory_user` matches on **username**,
so a directory identity named like a test account would inherit its row: `auth_source`
flips, and the test account's books, loans and notes become that member's. That is the
collision this feature would have introduced, and never adopting is the rule.

What to do instead is the part with no free answer. Reserving a prefix for test accounts
was considered and is not one: a naming convention has nothing enforcing it, and it does
not close the collision either, since nothing stops a directory identity being named with
the prefix. Whatever the names look like, the backstop is still needed.

Refusing the directory sign-in reads as the stricter choice and is the one that hurts: the real member is locked out of their
own library (under proxy, every request 401s), and this app has no endpoint that renames
or deletes an account, so the remedy is a hand-edited database row. So the test account is
renamed aside, `alice` becoming `alice-2`, at WARNING and naming both. It keeps its id,
its data and its flag, so a session already switched into it keeps working and it is still
a switch target under the new name. The disposable half of the collision is the half that
moves.

A test account is never an admin, and nothing in this app grants that flag afterwards.

### The rate limiter is hand-rolled

Not slowapi. The useful key is the *username being attempted*, and a middleware-style
limiter cannot see it: its key function runs before the body is parsed. Full reasoning in
[security.md](security.md).

### Lending *to* an external is a loan; lending *from* one is not

A loan can name somebody with no account (`loans.loaned_to_name`), because the people most
likely to keep a book are exactly the ones who will never have a login here.

The other direction, a book the library has borrowed **from** somebody, is deliberately
not modelled as a loan, and the reason is that it is not the same relation. `loans` answers
"our book is with X, chase it": the row is created by a member, the book is one this
library already holds, and the whole point is the overdue calculation running against
somebody we can nag. A borrowed-in book inverts every one of those. It is not our copy, the
deadline is one imposed on us, and the useful reminder is "give this back", which is a
different sentence, a different notification and a different half of the loans page.

Most of what that direction actually needs already exists on a different axis:
`ownership = not_owned` says the copy is not ours, `location` says where it came from, and a
note carries the rest. That is the answer for now, and it costs nothing to have made it.

Building it properly means a second relation with its own verb, not a nullable lender column
bolted onto this one: a `loaned_to_name` that sometimes means the lender would make every
query about loans ambiguous, and the CHECK constraint that currently says "exactly one
borrower" could no longer say anything useful.

### Loans are ordered by `(loaned_at DESC, id DESC)`

The `id` tiebreak is not decorative. SQLite's `CURRENT_TIMESTAMP` has second resolution, so
two loans recorded in the same second tie and come back in whatever order the planner
chooses. Found by a test that lent two books in a row.

### `/export` is declared before `/{book_id}`

FastAPI matches in declaration order. Reversed, `/api/books/export` is a request for the
book with id `"export"`. Moving route definitions around in `routers/books.py` is not the
free reordering it appears to be.

### A unique *index*, not a unique constraint, on `user_books`

SQLite cannot add a constraint to an existing table without rebuilding it, but it can
create an index, which is applicable to a live database. It deduplicates existing rows
first, or the creation would fail.

### `generate_unique_id_function`

FastAPI's default operationId mangles the path in, so `list_books` becomes
`list_books_api_books_get` and the generated client turns that into
`useListBooksApiBooksGet()`. Using the handler name instead requires those names to be
unique, which `assert_unique_operation_ids()` enforces at startup.

That guard's first version iterated `app.routes` filtering on `APIRoute` and found
**nothing**: `include_router()` does not splice child routes in, it appends a wrapper. The
check passed while inspecting zero routes. It now descends into the wrappers and fails
loudly if it ever finds none again.

### Alembic, adopted rather than more hand-written ALTERs

Schema changes used to be hand-written steps in `migrate_schema()`. That is exactly the
failure mode migration tools exist to prevent, so Alembic runs at startup instead. The
adoption path for an existing database (stamp the baseline, then upgrade) is in
[architecture.md](architecture.md). `render_as_batch=True` is mandatory for SQLite.

### Ownership is a separate axis from read status

`books.ownership` answers "is a copy physically here"; `user_books.status` answers "has this
person read it". They are independent claims about different things: a library borrowing is
read and not owned. Collapsing them is what makes an imported reading history look like a
catalogue of possessions. `unknown` exists because a Goodreads export cannot answer the
ownership question at all, and guessing either way would assert something nobody checked.

### Lending willingness is a third axis, and it is on the book

`books.lending` answers "would we lend this copy", and it is neither `ownership` nor a
loan. A loan is a fact about right now; this is a standing intention that outlives it. A
book can be marked happy to lend while it is at somebody's house, and one marked never lent
can still be out with a sibling. Putting the answer on the loan would mean it existed only
while the book was somewhere else, which is precisely when nobody needs to read it.

Three values rather than a boolean, and `in_use` is the reason. "I need it myself at the
moment" is a real answer and is not a refusal: it means come back later, which yes-or-no
cannot express. It arrived that way from the library that asked for the feature, in three
sentences rather than a tick box.

Nullable rather than defaulted, like `format` and `condition`: an unanswered question is
not an answer, and a guess written into every imported book at once is worse than a blank,
because nobody re-checks a field that looks filled in.

### A book marked never lent is refused once, not forbidden

`POST /api/loans` answers a **409** carrying `code: not_lendable` for a book whose
`lending` is `never`, and creates the loan when the same request comes back with
`acknowledge_not_lendable: true`.

Neither extreme is right. Allowing it silently makes the field decorative: a library that
took the trouble to mark a copy would find the app had quietly ignored them. Forbidding it
outright is worse, because the same library lends that book to a sibling anyway, and an
app that will not let them record what actually happened gets a loan kept in somebody's
head instead. That is the one thing this table exists to replace.

So the refusal costs one deliberate extra step and nothing more. `in_use` and `happy` are
not checked at all: the first means "come back later", which is a conversation between two
people rather than a rule, and the second is a yes.

The acknowledgement is **not stored**. It says something about one request, not about the
book, and a library that lent a never-lent book once has not changed its mind about
lending it to anybody else. Pinned by a test: lending it, returning it and lending it again
asks again.

The code sits beside the message rather than replacing it because the client has to
**branch** on this one, and matching on prose would break the moment it was reworded or
translated. The two 409s this endpoint raises mean entirely different things to the reader,
and only one of them has a way past it.

### "Ask me about this book" is on the member, and everybody can see it

`user_books.wants_to_discuss` is per member, for the same reason the rating is: two people
can hold the same copy and feel entirely differently about it.

It is also the **one** field on that table meant to be read by other people. The status,
the rating and both dates are private and reach the API only as the caller's own `my_*`
fields; this one is served to everybody as `discuss_with`, a list of the members who set
it. That is not a leak of a private field, it is the feature: a marker only its owner can
see is not a way to be asked about anything. It discloses usernames and nothing else, and
in particular says nothing about whether those members have read the book.

It costs one statement per page, which is why `discuss_with` is filled by a single grouped
query rather than a lazy relationship read inside the serialisation loop. `books_to_out`
went from 5 statements to 6 and `GET /api/books` from 10 to 11, both measured and both flat
in the size of the page.

`?discuss=true` matches **anybody's** offer rather than the caller's, so the filter selects
exactly the books that carry the marker the grid draws. Scoped to the caller it would hide
half of what it claims to select.

### `categories` is joined with a semicolon, not a comma

Google's own category names contain commas ("Fiction, general"), so a comma-joined list
cannot be split back apart. `google_books.join_categories` / `split_categories` are the only
two places that know the delimiter, and the API serves the field as a **list** so no client
has to know it at all.

### A classification is stored whole, and its number is what gets matched

`metadata.py` used to strip the number off a DDC heading (`"004 Informatik"` became
`"Informatik"`) so the caption could substring match a tag by name. That threw away the only
half of the heading that means the same in two languages.

Measured against the DNB on 2026-08-23 over ten German ISBNs: eight came back with a DDC
heading, and every one of the eight captions was German (`830 Deutsche Literatur`,
`150 Psychologie`). None of the eight matched any of the 105 seeded tag names, so the
caption based suggestion scored **zero** on exactly the catalogue that supplies the heading.

So a heading is stored as scheme, number and caption in its own table, and
`ddc.DIVISION_TAGS` projects the **number** onto the library's tags. `004` and `005.133`
both resolve to Computing whatever language the record was catalogued in.

**Its own table, not three columns on `books`.** A book carries several at once: K10plus
returned `005.133` and `004` for one ISBN, and the Library of Congress returns a DDC and an
LCC side by side. Columns would hold the first and drop the rest.

**One normaliser, `ddc.notation`, and all three source paths call it.** They started with
three notions of what a number is: the DNB split on a regex, the K10plus path admitted
anything whose first three characters were digits and then stored the whole subfield, and
the Library of Congress path stored the element text untouched. A column that exists to
hold a language independent notation cannot have three answers to "what is one".

**The MARC segmentation prime is stripped, not rejected.** 082 `$a` marks where a library
may cut a number short for its own shelves (`005.13/3`); it is a printing instruction, and
the DNB stores the same heading as `005.133`. Measured against K10plus on 2026-08-23 over
463 live `$a` values, 53 carry one (11.4%). Rejecting them would throw away an eighth of
what that catalogue supplies; keeping them raw leaves two spellings of one heading that
`uq_classifications_book_scheme_number` cannot collapse.

### The DDC projection is a suggestion, and "suggestion" means pre-selected

The mapping produces tag ids in `suggested_tag_ids`, and **no server path writes a tag from
them**: no endpoint, no enrichment, no merge. Tags are a small curated vocabulary the
library chooses from; a machine derived one applied on its own turns a chosen list into a
generated one nobody can later tell apart. That is the same argument `books.categories`
exists for, and it is why the DDC caption is not written into `categories` either.

**The web client pre-selects them, so on an ordinary scan they land unless the member
unchecks them.** `ScanPage/hooks.ts` calls `update({ tagIds: next.suggested_tag_ids ?? [] })` on
both the lookup and the chosen-match path, and `confirm()` posts each selected id to
`POST /{id}/tags/{tag_id}`. The member sees the ticked boxes on the confirm form and can
untick any of them before pressing the button, and nothing is written until they do press
it.

**That is the intended reading of "suggestion" here**: the act is a person confirming a
form, not a person seeking out a checkbox. It is also pre-existing, not something this
round introduced. What the round changed is how often it fires: the caption route matched
nothing on a German record and the number route resolves eight of ten, so a default that
was mostly dormant is now the normal one.

**Worth revisiting.** If the intent is that a machine derived tag should require a positive
act, the fix is one line in `hooks.ts` (start with the boxes unticked) and it changes what
every scan does. This is recorded rather than decided, because four documents used to claim
the tag was never applied at all, and a reader who believes that is not in a position to
have the argument.

### Division level, not the full Dewey schedule

The mapping is the 100 published divisions (`000`, `010`, ... `990`). The full schedule is
not free to redistribute, and the ten classes are too coarse: every novel and every work of
literary criticism would land under one tag. A division is also the granularity the DNB
emits, since its Sachgruppen are division aligned, so `830 Deutsche Literatur` arrives
already at the level this maps.

An unmapped division is a real answer rather than a gap. Five are absent and `ddc.py` names
each one: 040 is unassigned in the schedule, 060 is associations and museums, 080 is
quotations, 090 is manuscripts and rare books, and 310 is general statistics. Inventing a
curated tag for any of them would be the failure this whole design avoids.

### The Library of Congress is fetched over plaintext HTTP, knowingly

`_LOC_URL` is `http://lx2.loc.gov:210/lcdb`, with `follow_redirects=True`. It is the one
catalogue of the six not fetched over TLS, because that is the endpoint the Library of
Congress publishes for its Z39.50-over-HTTP SRU gateway; the other five are https.

**What that costs, stated rather than implied.** An on-path attacker can substitute the
response. A Classification reaches an existing Book only after a Member has seen and selected
the candidate record. The routes that handle them are worth naming exactly:

* `POST /api/books` receives the scan draft a Member submits.
* `POST /{id}/enrich/apply` writes the selected candidate record, including its
  Classifications.
* `POST /{id}/enrich` may choose a first match to fill scalar fields, but discards its
  Classifications.
* `PUT /{id}/refresh` changes scalar lookup fields only. It does **not** reach this source:
  `metadata.lookup` uses `_SOURCES`, which holds four sources and excludes the Library of
  Congress.

The detail picker displays every candidate Classification, or an explicit empty state, before
selection. A row confirms its whole record. There is no individual Classification action.

**Its share of this table grew on 2026-08-24 and the accepting has to be re-stated for it.**
LCSH comes from this response and nothing else does: measured over 900 live records, 85.4%
carry at least one and they supply 1,559 headings, where the same records supply at most two
classifications each. So the plaintext source went from a minority supplier of a number to
the sole supplier of a whole subject vocabulary. Nothing about the exposure changed in kind;
what changed is how many rows are on the wrong side of it.

**The fence now includes confirmation.** Every candidate value goes through
`ClassificationIn` (a closed scheme enum, a 120 character number, a 200 character caption).
`_headings` and the search loop drop a record that fails rather than failing the request, and
the selected writer, `_write_classifications`, caps the per book total. A substituted record
can show a wrong heading, but cannot write one until a Member selects it. It cannot write an
unbounded value, take an endpoint down, or reach a column outside this table.

**What would change it**: an https endpoint for the same service, which would be a
one-constant change. Nobody has found one. Until then this paragraph is the point: an
undocumented plaintext source is read as a guarantee it never made.

### Catalogue XML refuses a doctype, and the response size cap that was deferred

Two risks were recorded here as one in round 1. **The first is closed.** All six catalogue
parses go through `metadata._parsed`, which refuses a body carrying `<!DOCTYPE` and raises
`ParseError`, which every one of those callers already caught. `xml.etree` expands nested
internal entities (measured on this project's own Python 3.14.7: three levels of nesting
expanded to 1,000 characters, so six is a million), and that was the only term in this
module's memory use not bounded by the response size. It costs nothing measurable: 225 live
DNB and K10plus responses cached 2026-08-24 carry no doctype, nor does a live BnF or Library
of Congress answer.

**The second is now closed too, and the reason for deferring it was wrong.** It was deferred
because a wire byte cap "turns six `client.get` calls into streamed reads with their own
fixtures", which would be a transport change shipped inside a feature round. That cost was
never paid: respx intercepts `client.stream` exactly as it intercepts `client.get`, and the
190 existing tests in `test_metadata.py` and `test_google_books.py` passed against streamed
reads with **zero fixtures changed**. The deferral rested on a cost nobody had measured.

The risk it left open was real: a hostile or substituted response is a memory exhaustion in a
pod limited to 512Mi, where a 1.8 GB peak has already caused an OOMKill once (see the backup
upload cap, which exists for the same reason from the other direction). Parsing retains a
measured 15.28x the wire bytes.

**And "1 MB is the right order" was wrong in two ways**, both found only when somebody built
it. The cap is 2 MiB, because the largest honest body moved from 587,810 to 687,481 bytes in
three days as the query sample widened: the tail of a third party catalogue's record sizes is
being sampled, not bounded, so the margin is deliberately 3.05x rather than tight.

More important, **a cap counted after decoding is not a cap**. `aiter_bytes()` hands the
decoder a whole raw chunk before yielding, so the decompressed allocation happens before the
running total is compared to the limit: 65,250 wire bytes counted 67,108,864 and allocated
148.3 MB, or 463.8 MB across the six sources `metadata.search` asks at once. The first
implementation of this cap had exactly that shape and would have shipped looking like a
security improvement. The rule is now "never expand it": `accept-encoding: identity`,
`aiter_raw()`, and a `content-encoding` we did not ask for refused on the header. Same
payload, 0.1 MB.

**Moving the DNB to MARC21 made it worth sooner.** An honest page of search results went
from 51 KB to between 438 and 588 KB, measured over four `WOE=` queries at the 50 record
ceiling on 2026-08-24; the largest was `geschichte deutschland` at 587,810 bytes. That is
not itself a risk (0.60s against 0.37s, parsed and dropped), and it does mean any cap chosen
later has to be set against a page of MARC rather than a page of Dublin Core, on the wire
bytes rather than the parsed size: measured retention is 15.28x the body, and the honest
lookup body grew 45x rather than 9x because `maximumRecords` went from 1 to 5 alongside the
schema. 1 MB is the right order for a 50 record page.

### Classifications are in the backup and not in the CSV

The full backup carries the table, because a backup is the whole library and losing a
heading would make a restore lossy. The CSV does not, and the CSV import cannot set one.

That is the same line `docs/api.md` already draws for notes, quotes and loans: the CSV is a
row per book for reading in a spreadsheet and for importing from another service, and none
of those services emits a classification. A Member restores a heading by fetching candidates,
then selecting a Catalogue record.

### Only DDC is projected, though LCC, GND and LCSH are stored

LCC has no published list short enough to ship as a mapping, and the library vocabulary it
would project onto is the same one Dewey already covers. So an LCC number is stored whole,
because a catalogue heading is worth keeping whole, and read by nothing yet.

GND is a different reason for the same answer. `4203576-4` is an authority record number
rather than a place in a schedule, so no arithmetic takes it to a division the way `005.133`
goes to `000`. What a GND heading does bring is its caption, and the caption reaches
`subjects`, where the existing name match against tag names already reads it.

LCSH is the third reason and the plainest: there is no number at all. `Computer software --
Development` is a phrase, so there is nothing to project. Its text reaches `subjects`
through the existing `<subject><topic>` reader, which is where the tag name match sees it.

### LCSH is a parser extension, and the Library of Congress stays off the lookup path

The record `_loc_subject_headings` reads is the one `_loc_record` already has in hand:
`<subject authority="lcsh">` sits beside the `<classification>` elements the same function
has parsed since round 1. So LCSH costs no outbound request, no key and no new host, and
`id.loc.gov` is not touched.

**What was measured first, because the sizing rested on it.** 45 live `dc.title=` searches
against `lx2.loc.gov`, 20 records each, 2026-08-24, 900 MODS records:

| | |
|---|---|
| Records carrying at least one LCSH heading | 769 of 900, 85.4% |
| Headings in total | 1,559 |
| Mean per record that carries any | 2.03 |
| Most on one record | 14 |
| Headings carrying a ` -- ` subdivision | 1,056, 67.7% |
| `valueURI` on any `<subject>` element | 0 of 2,280 |

**The Library of Congress does not join `_SOURCES`, and that is the decision rather than the
next step.** It is the one catalogue here reached over plaintext HTTP, which this file
already records as accepted precisely because it is not on the scan path, and putting it
there would add an outbound call to every scan. It would also buy nothing for this
library's main case: of eight ISBNs measured, the Library of Congress held a record for
five and all five were English, the misses being both German ISBNs and one English title it
does not hold. So LCSH appears on a search row and reaches a book the way any other picked
row does, through `POST /{id}/enrich/apply`.

### `classifications.number` is 120 characters, and LCSH is why

The column was 40, which is comfortably above the longest Dewey number, LCC call number or
GND authority number this app has seen. An LCSH heading is not a notation: its subdivisions
are part of it, and `Computer software` alone is a different heading with a different set of
books under it. Measured over the 1,559 live headings above, a bound of 40 refuses **399 of
them, 25.6%**, and refuses exactly the subdivided ones. 80 still refuses 5; 100 and 120
refuse none. Longest measured: 91 characters, `University of Nebraska (Lincoln campus).
University Galleries -- Exhibitions -- Periodicals`.

Widening the shared column rather than giving LCSH its own is the smaller change and costs
the row nothing that matters: `CLASSIFICATION_LABEL_MAX` is 200 on the same table, so a
heading row was already allowed 240 bytes of text and is now allowed 320, against a per book
ceiling of eight rows that did not move. Migration `b7d41f0a2c95`.

### A subject heading never reaches the Dewey parser, on this source either

`ddc.parse_heading` accepts any three digit token, so an LCSH heading opening with one
(`004 Jahre Bauhaus`) would be stored as a Dewey number and would suggest a curated tag
from it. Round 2 closed this for the DNB by making 082 the only field handed to `ddc`; the
same shape holds here. `<classification>` is the only element `_loc_classifications` reads
and the only one `ddc` ever sees, and `_loc_subject_headings` builds LCSH rows without
importing it. Structural rather than defensive, and pinned by a test using that heading.

### LCSH sorts last at the ceiling, and the tie against GND is decided on the column

`_SCHEME_ORDER` is DDC, LCC, GND, LCSH. The two shelf classifications lead both subject
vocabularies for the reason already recorded: a record supplies several subject headings and
one classification, and DDC is the only scheme a tag suggestion is projected from.

GND and LCSH are the same kind of assertion at nearly the same rate (2.20 per DNB record,
2.03 per Library of Congress record carrying any), so the rate cannot break the tie. The
column does. A GND row's `number` is an authority identifier that outlives its own caption;
an LCSH row's `number` **is** the caption, and it is what moves when the Library of Congress
revises a heading, as it did turning `Afro-Americans` into `African Americans`. The store
exists to hold the half that does not move, so the scheme that has one is kept first.

**Half of that ordering fires today and half does not**, which is worth stating rather than
leaving to be discovered. DDC and LCC ahead of LCSH is live: a Library of Congress record can
carry 14 subject headings against two classifications. That ordering decides what survives
on a **merged book**, not what a search row shows: `Record.match_headings` slices before
`_headings` sorts, which is what the comment on that slice and its test exist to say. GND
against LCSH is not reachable through any flow the app itself drives, because the
DNB supplies one and the Library of Congress the other. `POST /merge` **does** bring both
onto one book, and the conclusion survives for a different reason than "no path concatenates
them": `_repoint_relations` orders keeper first then losers by id and never consults
`_SCHEME_ORDER` at all. It is decided now so that it is not decided later by list position.

### An empty list is absent, and `[]` used to beat a populated list

`_merge_matches` filled a field only where the leading row's value `is None`. Every scalar a
catalogue omits arrives as None, so that was the whole rule until `classifications` became
the one **list valued** key a search row carried. That row builder always wrote a list, so a
source that found no heading wrote `[]`, and `[]` is not None, so an empty list beat a
populated one and a Library of Congress row folded into another lost every heading.

**The rule now lives in `catalogue.Record.filled_from`, and it is no longer one condition
holding two kinds of field apart.** A `Record` has scalars and it has two collections, they
are separate fields, and they are tested separately: `is None` for a scalar and emptiness for
a collection. The reasoning below is why the condition was written, and it is kept because it
is why the shape is what it is; what it describes is a dictionary that no longer exists.

**The first draft of this entry recorded that as a merge design question and declined to
fix it.** That was wrong, and the measurement is what showed it. Over 30 live title searches
on 2026-08-24: 13 merged rows carried `loc` beside another source, 10 of those came from an
LoC row with LCSH, and **6 lost the headings. In 6 of 6 the leading row's list was empty**,
all of them `bnf+loc`, the BnF emitting no classification at all. There was never a union to
perform.

**Open Library never lost a heading, and the reason is worth knowing**, because the obvious
example was the wrong one. Its *search* row builder omitted `classifications` entirely where
the shared row builder wrote `[]`: 290 of 1,629 measured rows carried no such key. So
`existing.get()`
returned None there and the fill always happened. Only a source that writes an empty list
could trigger this, which is why every measured loss paired the BnF with the Library of
Congress. Unioning two populated lists would indeed be a change to how every field merges;
preferring a populated list to an empty one is not, and is one condition.

The rate depends on what it is measured against and both are worth stating: 8 of 118 over
all rows carrying a heading is **6.8%**, but conditional on a merge actually happening it
was 6 of 10.

What still limits what LCSH delivers is the ranking slice, not the merge: six live searches
returned 60 rows to the member of which 12 carried an LCSH heading, **20%**, because the
Library of Congress answered 87 rows carrying one and a page holds ten. That figure is query
set bound; a different eight searches gave 39 of 80, **48.8%**.

### The DNB is read as MARC21, and Dublin Core cost a caption to leave

`metadata.py` asked for `oai_dc` because it was already the shape this app wanted, where
MARC meant writing a subfield parser for the same five values. What that missed is that the
crosswalk into Dublin Core drops every identifier the record holds. Measured against ISBN
9783446249974 on 2026-08-23:

| schema | bytes | GND identifiers |
|---|---|---|
| `oai_dc` | 1,713 | none at all |
| `MARC21-xml` | 15,502 | 100, 600, 650, 651, 655, 689, 710 |

**The switch cost one field: the DDC caption.** `dc:subject` reads `830 Deutsche Literatur`,
MARC 082 carries `830` alone, and no other MARC field supplies the words: grepped over 85
live records, the German captions appear in the Dublin Core responses and in none of the
MARC ones. Filling it in from `ddc.DIVISION_TAGS` was refused, because that column records
what the scheme said and this would put our word in it. Nothing is lost from the tag
suggestion, which reads the number.

What it bought, over those 85 records: 187 GND identified subject headings where Dublin Core
carried none, a title and subtitle already split, and an extent on 85 of 85 records where
`dc:format` was present on 51 of 74.

**Four defects that only a live comparison could find**, all invisible in a fixture written
from the new parser, and all fixed:

* MARC21 from the DNB is **NFD** where Dublin Core is NFC, so `Müller` arrives as `u` plus a
  combining diaeresis: renders identically, compares unequal, and is enough to store one
  author under two spellings. 83 of 85 live records are affected.
* MARC brackets a leading article in the **non-sorting delimiters** U+0098 and U+009C, which
  28 of the 85 records carry and no terminal shows.
* An older record **never subfielded itself**: `$p` reads
  `Der Zinker : Kriminalroman / [aus d. Engl. übertr. von Gregor Müller]`, so where MARC
  supplies no `$b` the title goes through the Dublin Core splitter that already existed.
* An **edited volume names no author** in MARC: no 100, editors in 700 with `$4=edt`. The
  Dublin Core parser fell back to every credited person and `_marc_authors` did not, which
  lost an author on 8 of 53 records.

**The physical book filter became a preference on the lookup path and stayed a refusal on
search.** `_is_physical_book` never actually ran against the DNB, because `dc:format` is
absent on an online record; MARC `300 $a` reads "Online-Ressource" and it fires. Refusing
outright would have turned 21 of 74 live lookups into misses, for records that name the
scanned ISBN in their own 020 and describe the right book, so `_dnb` ranks a physical record
above an online one and takes what it has. A search has no ISBN to tell an edition of this
book from a digitisation of another one, so it refuses, which is what `_k10plus_search`
already did.

That section says `100 $0` is stored nowhere, names the two candidate homes and
defers to the VIAF question. It is now answered and should be rewritten rather
than left, because it currently states something the code no longer does.

The answer is a **third** home, and neither of the two it names. Not a column on
`author_aliases`, because an alias row is a decision somebody made about two
names and most spellings have none: an author nobody has merged would have
nowhere to put an identifier. Not authors becoming rows, which is the expensive
change §30g says to decide before writing a migration and which storing an
identifier does not require. `author_identifiers` is keyed on a spelling the shelf
carries, as `author_aliases` is, and answers a different question about that key.

**That keying had to be corrected before the claim was true.** A row a Member
confirms was filed under the author's *display name*, which is an alias row's
`canonical_name` once a merge has run, and `merge` accepts a `keep_name` no Book
carries. So a member's row landed on a key nothing evidenced, and a second merge
to a different name orphaned it: invisible in the listing and undeletable. It is
filed under the most used spelling on the shelf instead.

**The same unevidenced key was a privacy hole read from the other end**, and
that is the sharper half. The set of keys an author reaches included the key
derived from that typed name, so a member could merge their own author under a
guessed spelling and reach rows derived from somebody else's Private Book.
Measured through the module seam: a listing that was empty returned the
stranger's identifier, the authority lookup's own door returned it, and
`forget_identifier` **deleted it**. The reachable set is now built from
evidenced keys only.

Three properties carry the design and each is enforced rather than documented:

* **The name is editable and the identifier is not.** A `canonical_name` is how
  a household wants a name to read and a national library may be overruled about
  it. An identifier is a claim about which record in an external file this is, so
  there is no operation that changes one in place: correcting a wrong one is a
  delete, and a re-import may write it again.
  `uq_author_identifiers_key_scheme` makes a second row impossible below the
  application.
* **Provenance is explicit on both sides.** `catalogue` or `member`, never
  inferred from a null `created_by_user_id`, because the question the column
  exists to answer is whether a curated list has quietly become a generated one.
* **An identifier is per spelling, not per person.** Two merged spellings may
  carry different numbers, and that disagreement is evidence rather than a bug.

### Open Library's subjects are not classifications, and its two classification fields are

Open Library carries both kinds of value and they go to different places.

**Subjects go to `subjects`, with the publisher's uncontrolled list.** §30i's rule for the
`classifications` table is an assertion from a **published scheme**. A live Open Library
work carries `open_syllabus_project`, `fiction classics` and
`Fiction, Romance, Historical, Regency`: a folksonomy, not a vocabulary, with no scheme to
name and no identifier to cite. Putting those in a table whose whole point is controlled
values would make the column meaningless for the thing it exists for, which is a heading
another institution can act on.

**`dewey_decimal_class` and `lc_classifications` go to `classifications`.** They are DDC
and LCC, the two schemes round 1 already built, and they arrive with the number alone as
every MARC 082 does. Measured over 45 live edition records on 2026-08-24: 11 carry a Dewey
number, always exactly one, and 17 carry an LC call number, 11 of them one, five two and
one three.

**Only the first LC value is stored.** The repeats are one call number written several
ways (`QB45.Z43 1998`, `QB45 .Z43 1998`, `QB45`), and `uq_classifications_book_scheme_number`
cannot collapse them because they differ by a character. Storing all three would spend three
of a book's eight rows saying one thing.

**One live counterexample, recorded rather than acted on.** `9780262033848` carries the
subject `54.10 theoretical informatics`, which genuinely *is* a Basisklassifikation
notation sitting in the folksonomy. It confirms the rule rather than breaking it: nothing
in the payload says which scheme it belongs to, and a notation whose scheme has to be
guessed is not an assertion another institution can act on. It is the shape that would
justify revisiting this if BK is ever wanted, and round 1 already refused BK for a separate
reason (nothing here can read the notation).

### Open Library subjects are bounded at twelve, and the bound is what makes them usable

`subjects` is not stored, but it feeds two things that are: `suggested_tag_ids`, which the
web client pre-selects, and `catalogue.Record.as_match`, which joins the list into the
`categories` column.

Open Library's work subjects are long. Measured over nine live works on 2026-08-24 the
lists ran 0, 0, 3, 36, 65, 82, 101, 122 and 137 entries. Unioned with the edition's own and
left uncapped they pre-select up to **16** of the 105 seeded tags on one book: 1984 resolves
to Fiction, Play, Essays, Classic, Contemporary Fiction, Crime, Dystopian, Fantasy, Satire,
Science Fiction, Short Stories, War, Art, History, Language and Science. At twelve the worst
case over the same nine is **4**, and they are the ones a person would have picked: Pride
and Prejudice resolves to Fiction and Romance (and to Classic as well, until the entry
below stopped the matcher reading a tag name inside a longer word).

The edition's own subjects are taken first, so the printing's cataloguer beats the work's
crowd where both spoke.

**Both figures above are what a substring matcher produced**, and the entry below changed
that in the same round: four of the sixteen (Art out of "Outer Party", Crime out of
"thoughtcrime", and two more) no longer match at all. The two fixes are independent. The
matcher stops reading a tag name inside a word; this cap stops one book carrying 137
chances to do it.

**A pre-existing defect this measurement surfaced, now fixed.** See the next entry: it was
deferred first, then measured properly, and the measurement said to do it.

### Tag names are matched on word boundaries, not as bare substrings

`match_subjects_to_tags` read a tag name anywhere inside a subject string, so
`Software engineering` proposed **War**, `Outer Party` proposed **Art**, `thoughtcrime`
proposed **Crime** and `Trous noirs` proposed **Noir**. This entry first recorded the
defect and deferred the fix as "a behaviour change across every source". That was the
wrong call and the reason is that the deferral cited two examples and no rate.

**Measured live on 2026-08-24, this function against the 105 seeded tag names:**

| Population | Substring | On word boundaries |
|---|---|---|
| 12 English books, Open Library subjects | 27 suggestions, 7 wrong | 20, **2 wrong** |
| 10 German ISBNs, DNB subject headings | 5 suggestions, **5 wrong** | 0, none |
| both | 32, **12 wrong (37.5%)** | 20, **2 wrong (10%)** |

It removes ten wrong suggestions and loses two correct ones, and **the two sides are not
symmetrical**: the web client pre-selects every suggestion, so a wrong one is written
unless somebody unticks it, while a missing one costs a click. Five wrong removed per
correct lost, on that asymmetry, is not a close call.

The German row is the sharper one. On those records the substring route produced nothing
but false positives, out of `Gegenwartsliteratur` and `Softwareentwicklung`, which is the
failure the DDC number projection exists to work around: it was not merely scoring zero
there, it was scoring negative.

**What it costs, and the variant that was measured and refused.** `fiction classics` no
longer proposes **Classic**, on 2 of the 12 English books. Allowing an optional trailing
`s` recovers both, and also recovers **Noir** and **Travel**: two correct for two wrong,
which fails the same asymmetry. Both losses are pinned by tests so the trade is visible
rather than rediscovered.

**Two false positives survive and are not fixable here.** `Medicine in Literature`
proposes **Medicine** and `computer science` proposes **Science**. Both match on a word
boundary, and both are wrong because the subject is *about* the tag rather than an
instance of it. That is a semantics problem and no matching rule solves it.

The boundary is a lookaround (`(?<!\w)` / `(?!\w)`) rather than `\b`, because a library
tag may end in punctuation: after the `+` of `C++`, `\b` asserts that a word character
follows, which is the opposite of what is wanted.

### An Open Library key is validated before it goes into a URL

`/isbn/{isbn}.json` answers with `authors: [{"key": "/authors/OL23919A"}]` and
`works: [{"key": "/works/OL4781294W"}]`, and both are concatenated onto our own host to
fetch the next record. A key of `@example.com/` makes that
`https://openlibrary.org@example.com/.json`, which moves the **host** rather than the path:
a request to somebody else's server, made by ours, from our network position, with our
timeout.

Two regexes match the documented shape and a key that does not match is not fetched. This
was already reachable before this round through the author key; it is closed now because
this round adds a second concatenation.
`tests/test_metadata.py::TestTheOpenLibraryLookup::test_a_key_that_is_not_open_librarys_is_never_fetched`
pins it.

### The edition cluster drops a declared translation, and ranks a declared match first

Open Library's work cluster is every printing of a work, and a work spans translations.
The cluster behind `9783442002009` (Der Zinker) holds 11 entries, of which 9 declare
English and are printings of *The Squeaker*, measured live on 2026-08-24.

Every one of those is the same work. None of them can fill in a German printing's
publisher, page count or cover, which is what `POST /{id}/enrich/apply` does with the row
somebody clicks. Left in, they took four of the five rows the picker shows and pushed the
German editions out of it entirely. So where the caller knows the language, an entry
declaring a different one is not a candidate.

**An entry declaring no language is kept, and that is a compromise rather than a
guarantee.** This entry used to say that keeping them "is what makes this safe rather than
destructive", from a sample where 19 of 129 entries (14.7%) were unlabelled. That sentence
was false and the sample was unrepresentative. Measured again on 2026-08-24: **56 of 250
entries across 14 live clusters, 22.4%**, and a second sample of 14 clusters at 52 of 160,
**32.5%**.

At that rate a filter alone leaves the picker showing four foreign printings that merely
declined to say so. `9783453435773` (King's *Es*) is the live case: Turkish, Spanish,
English and French rows, all unlabelled, while the one printing declaring `ger` ranked
fifth and was never shown. **So the language match is the first term of the sort**, ahead
of completeness, and that book now leads with its German printing. Verified live after the
fix.

**What that still cannot fix, recorded as a limit rather than claimed away.** Where *no*
entry declares the wanted language, nothing in the payload distinguishes the wanted
printing. `9783596905683` is the live case: four Catalan and Spanish rows lead and the
German Fischer printing ranks eighth, because it is itself unlabelled. The search half of
`candidates` is the only thing that answers that book, which is the reason the cluster is
capped one row short of the page rather than filling it.

**And `prefer_language` is `book.language`**, so on a book with an empty language column no
filter and no ranking run at all. That is not rare: Open Library supplied a language on
**0 of 35** records before this round, so every book enriched from it before 2026-08-24 is
in exactly that state. Nothing here fixes those rows; a refresh now fills the column, and
the cluster works from then on.

### The candidates page deduplicates on the ISBN and on nothing else

`_match_key` is a title and a first author, which is the right key for a search page where
two catalogues describe the same book. It is the wrong key here: every row on this page is
a printing of one book, so it collapsed a five row answer to one. Measured live before it
was fixed.

An ISBN identifies a printing, which is what this page lists. A row with no ISBN is always
kept, because "no ISBN" is not an identity two rows can share.

### The DNB's 653 keywords are not read

653 is the publisher's own keyword list, and the DNB passes it through. Measured over 85
live records on 2026-08-24: 1,403 values, of which 512 (36%) are ONIX and VLB product codes
(`(Produktform)Electronic book text`, `(BISAC Subject Heading)FIC000000`) and the rest run
from real subjects to shelf marketing (`gelb`, `reclam hefte`, `lektüre`).

Ten per record of that would swamp the controlled headings in `categories`, and worse:
`subjects` feeds `match_subjects_to_tags`, which is a **substring** match against tag names,
so every extra keyword is another chance to suggest a tag nobody meant. The controlled
fields (650, 651, 655, 689, 600) are read instead, and 653 is left where it is.

### The Goodreads integration is a CSV import and a link

Goodreads shut its public API to new developers in December 2020 and has issued no keys
since. There is no supported way to authenticate an account or read a shelf live, so
"connect your Goodreads account" is not an option that could be built. It is one that could
be built and never work.

### Reading progress is a log, not a `current_page` column

A column on `user_books` answers "where am I" and nothing else, because every save
destroys the previous answer. The questions this feature exists for, "how much did I read
in March" and "how long did that one take", are questions about the history.

BookLogr keeps a current page and is the reference for the position itself; it cannot
answer either question. Jelu keeps a log, and its events are per status transition, which
is a different fact from a position in a book. `reading_progress` takes the log shape from
one and the position from the other. MyBibliotheca's daily log stores `pages_read`, a
delta, which was rejected here: a delta cannot be reconciled against the book, so a
mistyped one is uncorrectable, and the deltas this app reports are computed from positions
instead.

### Two units on `reading_progress`, exactly one per row

`(page IS NULL) <> (percent IS NULL)`, as a CHECK constraint.

An audiobook has no pages, and neither has a book whose `page_count` no metadata provider
supplied, which is most of a freshly scanned shelf. So a percentage has to be recordable.
Carrying both units on one row would need a rule for which one wins when they disagree,
and a rule like that is one somebody eventually gets backwards. Carrying exactly one needs
no such rule.

In the database rather than only in `ProgressCreate`, for the same reason
`ck_loans_one_borrower` is: a restore inserts through Core and never sees a Pydantic
model.

### The displayed percentage is derived, never stored

`page / books.page_count` when the page count is known, else the recorded `percent`, else
nothing. `serialisation.derived_percent` is the single definition, and the frontend does
not repeat it: `ProgressOut` deliberately omits a percentage per row.

Storing it alongside the page would be the same fact twice, and the two would part company
the first time a metadata refresh corrected a page count. Clamped at 100 because a
provider's page count is off by one often enough that the last page computes to 101.

### Recording progress promotes to `reading` and never to `read`

Saying where you are in a book is the same claim the READING button makes, arrived at from
the other direction, so a first entry on an unstarted book promotes it and stamps
`started_at`. The transition goes through `_stamp_reading_dates`, which owns those rules;
duplicating them in the progress endpoint is how the two would drift.

It never sets `read`, however high the page number. `page_count` is a provider's figure and
is wrong often enough that "reached the last page" is not a reliable finish signal, and
finishing already has an explicit control.

### A status change never deletes progress rows

Deliberately unlike `started_at` and `finished_at`, which are cleared on the way back to
unread. Those two are *derived* from the current status and would otherwise claim something
false about now. A progress row claims nothing about now: it records that somebody was on
page 64 on a Tuesday, which stays true. A re-read is a real thing, and its earlier passes
are worth keeping.

The asymmetry is stated in the endpoint's docstring so it does not read as an oversight.

### The progress endpoints sit beside `/{book_id}/status`, not before `/{book_id}`

The route-order rule in this repository is about a **literal** first segment losing to
`/{book_id}`, which is why `/export`, `/search` and `/bulk` are declared above it.
`/{book_id}/progress` has a path parameter in that position and cannot lose to
`/{book_id}` at all: they differ in segment count. So they are declared where they belong
conceptually, next to the status endpoint they cooperate with, alongside `/{book_id}/notes`
and `/{book_id}/tags`, which are placed the same way for the same reason.

`POST /api/loans/overdue/notify` **is** declared before `/{loan_id}/return`, because that
one is the shape the rule is about.

### `pages_by_month` is computed in Python, and covers page-tracked books only

The figure is a difference between *consecutive* rows per book. SQL that expresses that is
a window function feeding a conditional sum feeding a group, and nobody would be able to
check it against its description a year later. What bounds the Python version is the input:
one row per recorded sitting per member, so it is the size of one person's reading, not of
the library.

Percent-unit entries are excluded rather than converted. A book with no page count has no
page figure to convert to, and inventing one would produce a number that adds up with the
others while meaning something else. The scope is stated where each audience meets it: in
`docs/api.md` for a caller, and inside the `stats.pagesByMonth` heading string itself for a
reader, who otherwise has no way to find out why the total is lower than they expect.

Two rules inside it drop something on purpose. The first entry on a book counts in full,
because crediting nothing would mean a single sitting per book never appears. A backwards
step counts nothing, which covers both a re-read and a corrected typo: those are
indistinguishable from here, and crediting the lower page in full would let a typo of 400
followed by its correction to 40 report 440 pages read. Missing a re-read's first sitting
is the better of the two errors, because the other one invents reading that never happened.

### Overdue reminders go out on three channels: a webhook, email, and Telegram

**This reverses an earlier decision, and the earlier reasoning is kept because it is what
the reversal answers.** It read: a self-hosted app that other libraries run should not carry
an integration with a service nobody else runs, and email means SMTP credentials,
deliverability and a second failure mode; a webhook is the shape every receiver already
speaks, a chat bridge, a home automation flow, or a five-line script.

What that missed is who does the building. A webhook makes the **household** write the
receiver, and most have none and no intention of writing one, so the feature was off for
them in practice rather than in theory. The two additions are chosen against exactly that
objection: **SMTP is universal**, carried by every household with a mailbox, and **Telegram
is one fixed host**, so "an integration with something nobody else runs" costs one constant
rather than a service. The webhook is unchanged and nothing that already sends to one is
broken. Issue #8.

The costs the old argument named are real and are paid here rather than dismissed.
Credentials: both join `settings_store.SECRET_KEYS`, both may instead be pinned by the
deployment, and `MailConfig.password` is `repr=False` so a frozen dataclass cannot print it
into a log. Deliverability: the message carries `Date` and `Message-ID`, and a mail server
that accepts everything cannot be detected, so what is refused is the **configuration**, a
password with no encryption, both TLS flags at once, an address carrying a newline. A
second failure mode: reported per channel in `senders` rather than folded into one answer.

**Telegram's host is a constant, not a setting**, and that absence is the control: the
webhook posts wherever an admin typed, this posts where the app chose. Making it
configurable would give that property away and buy nothing, since a different host would not
be Telegram. The message is sent with **no `parse_mode`**, because with one set a book
called `Kiss & Tell` or `a_b` makes Telegram reject the send, which is member-supplied
catalogue content silently stopping every reminder. The same input is why the message is
truncated in **UTF-16 code units** rather than characters: a code point outside the BMP is
two units, so counting characters under-counts exactly where a title carries an emoji, and
2,100 grinning faces are 2,100 characters and 4,200 units against a limit of 4,096.

**`MAIL_DEBUG` is the one of the eight standard `MAIL_*` names not honoured.** Python's
smtplib writes the AUTH exchange to stderr under it, so supporting it would be a supported
way to print the household's mail password into the container log.

Handy Library's named differentiator in this space is **configurable reminder timing**, and
that is the part worth copying: a week is nagging in one house and silence in another, so
`overdue_reminder_days` is the library's to set.

Koha's `overdue_notices.pl` was read for the scheduling shape and **not** adopted. Its
`--triggered` mode fires only when a loan is overdue by exactly the configured number of
days, so a run that is missed sends nothing at all, ever, for those loans. State on the
loan (`notified_at`) plus an interval is robust to a skipped tick, which matters here
because the ticker lives in the web process and dies with a restart.

### The overdue digest excludes private books, on every channel

None of the three has a member identity behind it, and each lands where everyone here
reads, so shipping a private book's title through one defeats the single promise the data
model makes. The exclusion is in the query, not a filter afterwards, so a counting mistake
downstream cannot put one in the payload.

The owner is still chased: the in-app overdue view is per member and already scoped. The
digest reports `skipped_private` as a count so a library that expects five entries and
receives four can see why, and the settings screen says so in words rather than leaving it
to the docs.

**The count is reported per channel as well as once at the top.** All three withhold the
same rows today and so all three report the same number, which is exactly why the shape
matters: a reader has no way to tell a shared number from a coincidence, and a single
figure would become a lie on two channels of three the moment one audience differs.

**A per borrower mail is the one audience that could carry a private book, and it is not
built.** Being reminded of a book *you* borrowed is not a disclosure, and withholding it
means nobody ever chases the one book least likely to be chased by anyone else. The reason
it is absent is a missing fact rather than a judgement: **no member here has an email
address.** `models.User` carries none and the LDAP backend requests only the username
attribute and `memberOf`. Reaching it needs a `users.email` column, somewhere to set it
including for accounts that never type a password here, and a decision about who may read
another member's address, since `UserOut` is served inside book payloads. Until then mail
goes to the household's own mailbox, which is a channel like the other two and excludes
private books like the other two. Recorded so the absence reads as a blocked item rather
than an oversight.

### `notified_at` is a timestamp on the loan, stamped when at least one channel delivered

Without any state the digest has two behaviours and both are wrong: send once and forget a
book that is still out, or repeat the same list into the channel every hour.

Stamped after a send that succeeded rather than before it, so a run where nothing was
delivered leaves the loans to be retried on the next tick. That is why it is a timestamp
rather than a "sent" flag: the interval question ("has this been chased recently") and the
retry question ("did the last attempt land") are the same question, and one column answers
both.

**With three channels, "at least one" rather than "all of them", and the choice has a
cost.** A broken webhook beside a working Telegram chat means that batch never reaches the
webhook. The alternative repeats the identical list hourly on the channels that work, which
is the behaviour people switch off, and the only way to have neither is per loan per sender
state, which is a table this feature does not warrant. The column records that the loan
**was chased**, and it was; a channel that is down is an operator problem, reported in
`senders` rather than compensated for.

**What compensates for it is reporting, and the reporting has a gap worth knowing.** The
hourly ticker discards the result, so once a tick has stamped `notified_at` on any one
success, a manual "Send now" inside the reminder window answers `nothing_due` with an empty
`senders`. The per channel failure is visible on the run that failed and in the log
afterwards, not on a later button press. Named here rather than left to be discovered.

### The digest result carries a `reason`, and it is null exactly when it sent

`sent: false` on its own made five different outcomes one answer on the screen: switched
off, no address stored, nothing overdue, a receiver that refused the request, and a channel
whose settings cannot be used. A person
pressing "Send now" to check their configuration was told "nothing was sent" by a broken
setup and by a quiet week alike, which is the whole thing the button exists to tell apart.

`detail` was already there and is not enough. It is a sentence, and a client cannot branch
on a sentence or translate one. `reason` is the closed set beside it, so the frontend keys a
`Record` off the generated union and adding a sixth reason on the server is a compile error
in the catalogue rather than a silent fall through.

**Nullable rather than total.** A `sent` member would make `reason` and `sent: bool` two
spellings of one fact, which is the duplication this repository treats as a defect. So the
invariant is stated instead: null exactly when `sent` is true, and `_outcome()` in
`notifications.py` is the only thing that builds a not-sent result, so a new exit cannot
forget it. The frontend still carries a fallback for the pair the type allows and the server
never produces, because a screen that renders nothing is worse than one that is vague.

### `count_private_overdue` takes no reminder interval

It answers "how many overdue loans did privacy hold back", and that does not depend on when
anything was last sent.

It used to restate `due_for_reminder`'s predicate clause for clause, including the
`notified_at` one, and had already diverged in the only case where the two differ: a private
book is never sent, so nothing in this feature ever stamps its `notified_at`, and the only
way one carries a value at all is a book that was public when it was chased and was made
private afterwards. Filtering on it hid exactly those from the count for the length of the
interval, so the number under-reported the thing it exists to report.

`_overdue_clauses()` now holds what the two share and each query adds only what it owns. The
parameter is gone rather than ignored: one nothing reads is one the next caller passes
wrongly.

### A measured number lives in one place, and the other places point at it

`books_to_out`'s statement count was stated in its own docstring, in `docs/data-model.md`
and in `docs/architecture.md`. All three were wrong, twice, and the second time was a diff
that rewrote both sentences without re-measuring: a number is easy to edit and hard to
check, so an edit that looks like a correction is the likeliest way one goes wrong.

The docstring holds the measurement now, with what it was measured against, and both
documents reference it. The measurement itself is worth keeping in mind: five statements
constant in the page size, **plus one per distinct `added_by` author**, and that last one
belongs to the caller rather than to this function, because `BookOut` reads a relationship
that lazy loads unless the caller fetched it. Every listing in `routers/books.py` passes
`joinedload(Book.added_by)` and so pays none of it.

### `SECRET_KEYS` is enforced by a test that walks it, not by being read

Nothing in the application reads that set. Masking is written by hand per field in
`_read_settings`, so the set was a list beside the code rather than a rule over it: a third
secret added to it would have been masked by nothing, returned in full to every admin page
load, and no test would have failed.

The fix is a test rather than machinery. Making `_read_settings` iterate the set would mean
generating a field name per key and lose the per-field decisions that are the point: the
Google Books key reports whether the environment supplied it, and the webhook URL beside the
secret is deliberately **not** masked. So the set stays a list, and a test stores a known
value for every key in it and asserts none of them appears in the response body.

### The webhook URL is returned in full; the signing secret is masked

The two are not the same kind of secret. A destination an admin cannot read back is a
destination nobody can proofread, and spotting a wrong one is the entire reason to show
it; an admin who can read it is an admin who can change it. The signing secret has no use
in a browser at all, so it follows the Google Books key exactly: masked on the way out,
absent means "leave alone", an empty string clears.

The URL's scheme is checked twice, in `SettingsUpdate` and again in `notifications.py`
before every send. The first gives the caller a 422 naming the field; the second still runs
for a row a restore wrote.

### The ticker is one asyncio task, and assumes one process

The Dockerfile's CMD is a single uvicorn with no `--workers`, so there is exactly one
ticker and no double-send. That is the assumption that breaks first: `--workers 4` would
give four tickers racing on the same rows, and the fix then is `ENABLE_OVERDUE_TICKER=false`
plus an external cron calling `POST /api/loans/overdue/notify`, not a lock inside the app.

It is off under test. A background task waking on a timer inside a suite that drops and
recreates every table between tests produces failures that depend on how long the run took.

### Reading dates are derived, not entered

Nobody fills in a date field. Everybody moves a book to "reading" when they start it, so
the transition is the signal. The rules and the reasons are in
[data-model.md](data-model.md); the one worth repeating is that only unset dates are
stamped, because a UI with pressable buttons makes re-selecting the current status easy.

### Series is two columns, not a table

A series has no attributes here beyond a name, and both questions asked of it are answered
by grouping on that name. A table would add a join and an orphan-cleanup problem to buy
nothing. `series_index` is a float because omnibus editions really are numbered 2.5.

### Location is free text

Nobody knows their own shelf taxonomy before they start, and a vocabulary imposed up front
is worse than a slightly untidy one that grows. `GET /api/books/locations` returns what is
actually in use, which the UI offers as suggestions, because free text with *no*
suggestions becomes six spellings of "living room" inside a week.

### Every row id a caller supplies is bounded at both ends

A Python int has no ceiling and SQLite's does. An id past 2**63-1 passes
validation, reaches the driver and raises `OverflowError` from inside the query,
which lands in the unhandled-exception handler and answers **500**: the app
calling its own code buggy over a value the caller chose. 422 is the honest
answer.

This has now been found four times, in four different places, because each fix
closed one door and the reviewer had to find the next one by hand:

| Door | Where the bound lives |
|---|---|
| Query parameter (`?after_id=`, `?collection_id=`) | `Query(ge=..., le=MAX_ROW_ID)` at the parameter |
| Path parameter (twelve of them) | `dependencies.RowId`, one alias |
| Request body field (`book_ids`, `keep_id`, `book_id`, `year`) | `schemas.common.RowIdField` |
| A loosely typed body value (`BulkRequest.value`) | the handler, per verb |

**Two lints, not one, and they are not redundant.**
`TestEveryIntParameterFromTheOutsideIsBounded` covers route handlers and
dependency functions, which is where path and query parameters are declared;
`TestEveryRequestBodyRowIdIsBounded` covers pydantic fields on the models a
route accepts as a body, which the first cannot see at all. The older
`TestEveryNumericQueryParamIsBoundedBothWays` is kept beside them because it
still catches a floor-without-ceiling on a non-int parameter.

**Both lints resolve their tables to a fixed point**, and that is the same hole
one hop further out rather than a flourish. `Loose2 = Loose` carries no `int` of
its own, so a collector that registers only what mentions one literally never
learns the second name and skips every parameter annotated with it;
`CollectionUpdate(CollectionCreate)` names no `BaseModel`, so a literal test for
that base leaves a real request body out of the rule entirely. Neither was live
when it was found, which is the point: the rule exists so the fifth instance of
this class is caught by a test rather than by a reviewer.

**The alias has to bring a parameter into scope, not just satisfy the check.**
The first version of the parameter lint tested for the literal name `int`, so
`book_id: RowId` was skipped before boundedness was ever asked about: the alias
branch was unreachable, and loosening `RowId` itself to `ge=1` left the lint
green across twelve routes. The scope test now admits a parameter that mentions
`int` **or** names an int alias, and the guard test that discriminates is the
one that loosens an alias rather than the one that bares a parameter.

**`BulkRequest.value` is the one deliberate exemption.** It is `str | int | None`
because which field it fills depends on the verb, so it cannot be typed as a row
id; the handlers that read it as one range-check it themselves before it reaches
the database. That is why `_checked_collection` carries an explicit range check
that looks redundant beside its schema bounds, and it is not.

### A book belongs to one collection, not many

A library separates physical from ebook, kept from sold, and one person's shelf from
another's. All three are **partitions**: a book is in exactly one side of each. So the
collection is a column on `books` and not a join table.

A join table would answer "which collection is this in" with a list, and every filter,
sort, export cell and payload field downstream would then need a rule for a book that is in
three of them at once. It would also be a second tag system with a worse picker, because
tags are already the many-to-many axis here and they are where an overlapping label
belongs. If a library wants "Ebooks" and "Holiday reads" on the same book, the second one
is a tag.

The cost of the column, stated plainly, and it is two costs rather than one.

**Two objects: use two rows.** A library that wants the paperback in Physical and the
epub in Ebooks has two objects, and says so the way the data model already says it. That is
the copies feature, and it is the right answer.

**One object on two axes: use a tag.** This is the one the feature's own pitch creates and
it is not answered by copies. Collections are sold on three splits (physical from ebook,
kept from sold, one person's from another's), each of which is a separate axis, and one
column holds one axis. An epub that is both "Ebooks" and "Sold" is a **single object**, so
there is no second row to put it in: the library picks one axis for the collection and
puts the other on a tag, which is what tags are and why this column is not a join table.
Somebody who instead makes four collections will discover the swap by using the picker,
which is the worst possible place to learn it, so it is said in the empty state as well as
here.

### Every book that existed before collections is unfiled, and no default was invented

`books.collection_id` is nullable and the migration backfills nothing. The alternative was a
default collection created by the migration and every existing row moved into it, which
sounds tidier and is worse in three ways. It needs a name chosen here, in one language,
for a library that has not asked for the feature. It puts a concept in front of everybody
who never wanted it. And renaming a seeded string later means a migration, which this
repository has already had to write once (`95b6a61d6668`).

So "in no collection" is a permanent, ordinary state, in the same family as a null
`format`, `condition` or `lending`: an unanswered question is not an answer. The API says
so out loud rather than leaving it implicit: `GET /api/books?unfiled=true` is its own
parameter, and the library filter offers it as its own option, because "what have I not
filed yet" is the question the feature creates.

### A collection is per library, and is never a privacy boundary

Any member may make one, rename it, and file any book they can write to into it. Filing a
book changes **nothing** about who can see it.

This is the decision with the sharpest failure mode in the batch, which is why it is
recorded rather than left obvious. `visible_to()` is already a scoping predicate, and a
second scoping axis that looks like it but is not enforced everywhere is how a privacy rule
gets weakened by accident: the moment a collection sometimes hides rows, somebody will read
it as permission, and the first "private collection" feature request would arrive with half
an implementation already in the tree.

So the separation is kept mechanical rather than intended. `visible_to()` is not given a
collection to consult. `Collection.created_by_user_id` is recorded for provenance and no
query reads it, which is what keeps the previous sentence true rather than merely meant.
Every count served with a collection applies `visible_to` (`routers/collections._counts`,
the `by_collection` statistic), because the count is the one thing a library wide label
could disclose: a member who files a private book onto a shared shelf must not thereby
announce it to everybody as a number.

A member who wants a shelf nobody else sees already has one: mark the books private. That
is one rule, enforced in one predicate, tested by an AST walk over every module.

Two asymmetries follow the tag rules exactly, for the reasons recorded there. Creating and
renaming are open to any member: both are additive or reversible. **Deleting is admin
only**, because it strips a label off every book in the house at once with no undo.

### Deleting a collection unfiles its books, and the database is what says so

`ON DELETE SET NULL`, not a cascade, and not a handler loop. A shelf label is not the books
on it, so destroying the label must never destroy them.

It is a database rule rather than application code because a restore and a hand-edited row
both reach the table without passing any handler, and a row left pointing at a destroyed
collection is a dangling foreign key. That also makes `PRAGMA foreign_keys=ON` load bearing
here in a way it was not before: without it the clause is decorative.
`tests/test_models.py` exercises it through Core, so the ORM's own nulling of loaded
children cannot be what passes the test.

### A copy carries its own collection, and the group spans them

Two copies of one title are two objects, and which part of the shelf each lives on is
exactly the kind of fact that differs between them: the paperback in the living room and the
epub on a reader are the library's physical and ebook collections respectively. So
`collection_id` is per row, like `location`, and `POST /api/books/{id}/copies` does **not**
inherit it: the new copy starts unfiled unless the payload says otherwise.

That is deliberately unlike `is_private`, which a copy does inherit, and the difference is
the test for any future per-copy field. Privacy is inherited because getting it wrong
discloses a book. A collection is not, because getting it wrong files a book on the wrong
shelf, which is visible and one press to correct, and because the library that holds both
formats wants them apart.

Two consequences worth having written down.

`copy_count` still counts the whole group, across collections. It answers "how many do we
own", not "how many are on this screen", so a library filtered to Ebooks can show a book
whose card reads 2. The alternative, scoping the count to the current filter, would make the
same book report different numbers on different screens and would require `BookOut` to know
what was being asked, which it deliberately does not.

A **merge** does absorb it, unlike `copy_group`. `collection_id` is in `_MERGEABLE_FIELDS`
for the same reason `location` is: merging two entries for one book, one of them filed,
should leave the survivor on that shelf. It fills a gap and never overrides, so a keeper
already in a collection stays where its owner put it. That is safe in a way absorbing
`copy_group` is not, because a collection makes no claim about other rows.

`/duplicates` ignores collections entirely. Two ungrouped rows naming the same book are
still offered for merge even when they sit in different collections, because a collection is
not a statement that a second row was deliberate: the `copy_group` token is, and it is the
only thing that is. The unique ISBN index is table-wide for the same reason, and is
**not** scoped per collection: making it per collection would let "add this book to Ebooks
too" quietly create a second ungrouped row with the same ISBN, which is precisely the state
the constraint exists to refuse.

### A collection is not an import option, and not a grant scope

Two places it deliberately does not appear.

**The CSV importer does not take one.** Filing an import into "Ebooks" is a real wish, and
it is already served: the import lands, the result links into the library, and the bulk verb
`set_collection` files the selection in one press. A second path to the same state would be
a second thing to keep in step with the first.

**Peer sync does not carry it.** A collection is shelf taxonomy, which the peer sync design
already refuses to send for `location`, and a collection named after a member would leak
a member's name besides. It is also not a *scope* for a grant: scopes come from
the stored grant and there are exactly two, and a third keyed on a library wide label that
any member can rename or delete would silently widen or narrow what a peer sees through an
edit made for shelving reasons. The amendment recording this is A5 in that document.

### A copy is a row, not a count column

`books.isbn` was `unique=True`, so a library that owned two paperbacks of one title could
not say so. Three models were on the table.

**A `copies` count column.** One integer, no query multiplied, the constraint untouched.
This is what Libib does, and Librarika's "2000 items including copies" implies something
similar. **Refused**, and for a specific sentence rather than on principle: a count cannot
say *one is lent out and one is on the shelf*. Nor which one is in the loft, nor that the
battered one cost 2 euro at a jumble sale. Every one of those facts is already a column on
`books`, written per object, and a count would have been a second, weaker way of describing
the same objects. The loan rule is the sharper half: `uq_loans_one_open_per_book` would have
had to become "at most `books.copies` open loans", which is a cross-row aggregate SQLite
cannot express as a CHECK. It would have moved a rule the database enforces into application
code, in an app where that rule is an index precisely because three code paths had to agree
on it and one of them did not.

**A separate `copies` table.** The textbook normalisation: `books` becomes the work,
`copies` the objects. **Refused** on cost and on fit. `location`, `condition`, `format`,
`lending`, `ownership` and the four purchase columns would all have had to move, which is
every filter, sort, export, statistic, bulk action and CSV column in the app, plus the whole
frontend, to express something the existing shape already expresses. The model comments in
`models.py` have said "this copy" about those columns since they were written: a `Book` row
already **is** a copy.

**A copy is a second row, joined by a shared `copy_group` token.** Adopted. Every existing
query keeps working because a copy is a book; the loan rule needed no change at all because
one open loan per row already means one per copy; and the four call sites the feature
investigation warned about (the scan flow, the duplicate detector, the merge logic, the CSV
importer) are exactly the four that changed, which is what "high blast radius" meant.

What it cost, stated so nobody has to rediscover it: the unique ISBN became **partial**,
over the rows whose `copy_group` is null. Those are the rows nobody has declared a copy, so
a re-scan still collides and still answers 409, which is the mistake that constraint has
always been catching. Dropping it outright would have turned the commonest mistake in this
app into a silent second row.

### Deliberate copies and accidental duplicates are told apart by a token

They are otherwise indistinguishable, and getting it wrong in either direction is bad: a
duplicate finder that offers two copies for merge invites somebody to destroy a book they
own, and a scan flow that quietly adds a copy on a mis-scan is the bug the unique ISBN was
put there to prevent.

The token is written by exactly one endpoint, `POST /api/books/{id}/copies`, reached by
pressing something that says "add another copy". Nothing infers it. In particular the CSV
importer never mints one: an export listing a book twice is an artefact of the export, and a
copy is a thing a person says they own, one press at a time.

Three places read it. `uq_books_isbn_single_copy` skips grouped rows. `/duplicates` collapses
each group to one row before matching, so a group can never be reported against itself.
`_MERGEABLE_FIELDS` deliberately omits it: absorbing a loser's group would make the survivor
a copy of the loser's siblings, which the survivor's owner never agreed to.

### The copy group is a shared label, not a self-referencing foreign key

"Is a copy of" is symmetric. Two paperbacks of one title are peers and neither is the
original, so a `copy_of_id` would have invented a distinguished row. Every distinguished row
needs a rule for what happens when it is destroyed, which here is a promote-a-sibling step
that `_purge`, `_create_book`, emptying the trash, merging and any future delete path
would each have to remember, and it has to run in the right order against the unique index
or the promotion is what raises. A shared label has no such row and therefore no such rule.

It is deliberately not a foreign key either, so purging any member of a group leaves the
rest exactly as they were rather than dangling.

The one piece of housekeeping it does need is `_normalise_copy_group`: a group that shrinks
to a single row has its token cleared, because the token is what suspends the unique index
for that ISBN and a group of one should be exclusive again. It runs on a **purge**, never on
a trash, and that is not a detail. A trashed copy can be restored, and clearing the token
underneath it would leave two formerly grouped rows with the same ISBN and no token, which
is precisely what the index refuses. The restore would fail on a button that has nothing to
do with copies.

### The copy's cover file is copied, not shared

Covers are files named by book id, and `covers.forget` deletes by id. Two rows pointing at
one file would mean purging either copy blanks the other's cover while leaving a `cover_url`
pointing at nothing. `covers.duplicate` is `adopt` without the delete, used only for a cover
this app already holds; a remote URL is inherited by assignment, and a book with neither is
resolved from its ISBN like any other new row.

### `_create_book` frees every holder of the ISBN, not the first one

That query returned one arbitrary row, which was correct while `books.isbn` was unique and
stopped being correct the moment several rows could hold one ISBN. Both failures were
measured through the API rather than reasoned about, and they differ by group size, which is
why the smaller-looking fix was refused:

| Set-up | Then scanning the ISBN | Why |
|---|---|---|
| Two copies, **both trashed** | **500**, `IntegrityError: UNIQUE constraint failed: books.isbn` | One row purged, the group shrank to one, `_normalise_copy_group` cleared the survivor's token, and that trashed survivor re-entered the partial index just as the insert reclaimed the ISBN |
| Three copies, **all trashed** | **201**, and a stray fourth row | One row purged, the group still had two members so nothing was normalised, and the insert simply succeeded against rows that still held the ISBN |

Guarding `_normalise_copy_group` against a trashed survivor fixes the first row of that table
and does nothing at all for the second, so the fix is at the cause: fetch **all** holders in
the same live-first order, refuse on the first one that cannot be freed, and free the rest
only if none refused.

Live-first is what decides which row a 409 names: the one on the shelf, not one in the
trash. Deciding in full before destroying anything is the other half, and it is not
tidiness. `_purge` is not undone by the request failing, so a 409 raised part way through a
group used to leave a member holding a book whose cover file had been unlinked.

### A cover file is unlinked after the commit, never before it

`_purge` used to call `covers.forget` first thing. A rollback after that point undoes the
DELETE and not the unlink, so the member still has the book and its `cover_url` now names a
file that does not exist. Nothing logged it.

It predates copies and copies made it reachable, through the ordinary scan flow, for the
reason above. `_purge` therefore returns the id and the caller unlinks after its commit:
`purge_book`, `empty_trash` and `_create_book` all do. Reordering inside `_purge` would have
bought nothing, because `db.delete` only marks the row in the session, and flushing per book
to get closer would put back the 3801 statements the "does not commit" note exists to avoid.

In `_create_book` the unlink sits **after the commit and before `_store_cover`**. SQLite
reuses the id of a deleted row, so the new book may well have taken one of the purged ids:
unlinking later would delete its own cover, and not unlinking at all would hand it somebody
else's.

That window is three lines wide and pinned by
`test_a_reused_id_keeps_the_new_book_s_own_cover`, because a comment saying so is what this
codebase had the first time a cover unlink was ordered wrong. Moving the loop below
`_store_cover` passes all thirty-six other tests in that file: the refusal path never runs
it, so only a test that forces the id reuse and stores a real cover can tell the two orders
apart.

**No instance is left, including the one that looked forced.** A merge lets the keeper
absorb the loser's `cover_url`, so it needs the new URL before it commits, and the first
version of this entry claimed that meant the file had to move before the commit too. It does
not: the URL is `local_url(keeper.id, extension)` and the extension is readable off the
source file without touching a byte. `covers.adoption_url` answers it, `covers.adopt` still
performs the move, and the merge does one on each side of the commit.

Which failure that chooses is the point. Moving first, a raise between the loop and the
commit, which `_normalise_copy_group`'s flush makes reachable and which is the exact shape of
the bug above, left the keeper's row naming a file that had already moved somewhere else.
Deferred, the same raise leaves every file where it was.

**Deferring moved the failure rather than removing it, and the first version of this got the
new one wrong.** With the move after the commit, `covers.adopt` can fail on its own with the
row already saved. That code discarded its answer and swept the loser's id anyway, which
destroyed the bytes and committed a `cover_url` naming a file nobody wrote: strictly worse
than the pre-commit ordering it replaced, which at least stored an honest "no cover". So
`adopt`'s return is **load bearing**. It answers None only when `replace_image` re-raised,
and that function is atomic and removes nothing but its own temporary file, so None means the
source is still the only copy and must not be swept. The row is corrected to "no cover" in
the same breath.

The backfill is **not** the escape hatch here, and leaning on it was the mistake underneath
the mistake: a hand-uploaded cover has no remote source, so `resolve_and_store` has nothing
to re-fetch. It repairs a cover that came from a metadata provider and cannot repair the
files a library cared enough about to upload.

The invariant is therefore worth stating on its own, in the half where it holds: **no cover
file is moved or unlinked before the transaction has committed.** Creation is deliberately
the other way round, in all five paths that write one (`upload_cover`, `_create_book`, both
in `add_copy`, and the backfill), and two things hold that up rather than one.

The asymmetry: a committed `cover_url` with no file behind it is a broken image every reader
sees, while an orphan file is bytes no row references. **An orphan is not harmless, though,
and an earlier draft of this entry said it was.** Nothing sweeps them: `backfill_covers` reads
`stored_ids()` only to skip books that already have a file, and deletes nothing anywhere. So a
file sitting under an id makes that id a permanent non-candidate, and a book landing on it
would show a placeholder the backfill can never repair.

What actually makes creating early safe is narrower and is the sentence to keep: **no path
writes a cover for a row that has not committed.** `_store_cover` and `covers.duplicate` both
run after the insert's own commit and refresh, and `upload_cover` writes for a row that
already exists. An orphan under an id with no row is therefore unreachable, which is why the
window between the write and the commit costs nothing here.
`upload_cover` makes the same trade one level down, writing before it deletes the book's
other formats, because the old order left a book with no cover at all when the write failed.
Do not "fix" either of them to match the moving half.

Two places unlink outside all of this, and neither falsifies the rule. `uploads.replace_image`
removes the base's **other** formats once the atomic replace has landed, before the upload
route commits: a genuine exception, and a narrow one, since what it can lose is a stale
duplicate format of the same book rather than its cover. `backup.restore` clears the covers
directory, but only after its own commit, and by then there is no transaction left to roll
back: it is destroying the previous library on purpose, which is what a restore is.

### Duplicate detection matches on title and author, not ISBN

An accidental exact repeat is already refused by `uq_books_isbn_single_copy`. The case left
to catch is a hardback and a paperback, which are the same book and two legitimately
different ISBNs. Deliberate copies are collapsed out first: see *Deliberate copies and
accidental duplicates* above.
Matching is deliberately lossy because it is a suggestion a person confirms, not an
automatic merge.

### An author is a name on a book, not a row

`books.author` stays what it has always been: one free text `String(500)`, comma separated
when a book credits more than one person. There is no `authors` table and no join table,
and an author page is a `GROUP BY` over that column, exactly as a series page is a
`GROUP BY` over `series_name`.

The reference implementation was read rather than guessed at. **Jelu** (MIT, the closest
architectural sibling) does the opposite: `AuthorTable` is a UUID row with a name,
biography, dates, image and six link fields, and `book_authors`, `book_translators` and
`book_narrators` join books to it. Its merge repoints every book from the losing author to
the surviving one and deletes the loser's row. That is the right design **for Jelu**,
because it has somewhere to put a biography and a portrait, and this repository does not:
the shelf knows a name and nothing else about a person, and Wikipedia enrichment is
deliberately out of scope. A table whose only column is the name it is keyed by buys a
join, an orphan-cleanup rule and a write path on every importer, and answers no question
that grouping does not.

What normalising **would** have bought is identity, and this design does not buy it back.
An author is addressed by `authors.author_key(name)`, a normalised form of the name itself,
so it is not durable: merging "Le Guin" and "Ursula K." into "Ursula K. Le Guin" leaves an
index keyed `ursula k le guin` and neither old key names an entry. An old link keeps working
because the alias row **redirects** it, which is the same treatment a display name gets, so
the key is no more stable than the name it came from and the API takes either.

Stated plainly because it is the cost of the design rather than a detail of it: if a
biography, a portrait or a birth date is ever wanted, the only thing to hang them on is a
key that moves under an ordinary tidy-up, and that is the point at which a real `authors`
table earns its join. What this design buys instead is the thing that argument does not
touch: a merge that writes **zero rows to `books`**, is undone by deleting one row, and
keeps folding the same split every time an import re-creates it.

### Two spellings are one person because somebody said so, not because the strings changed

The rejected alternative is the one the derived design appears to force: make the merge
**rewrite `books.author`** everywhere the folded spelling appears. It was refused for four
reasons, in order of how badly each one bites.

**It is not reversible.** Rewriting is a destructive edit to the field that records what the
cover says, and nothing is left to say what it said before. Undo would need a second table
holding the old strings, which is the alias table with worse ergonomics.

**It does not stay repaired.** `flip_catalogue_name` cannot save a name a source hands over
in catalogue order without marking it (see below), so the same CSV imported twice re-creates
the same split. An alias row folds it again the moment it reappears; a rewrite has to be
done again by hand, and nothing tells anybody it is needed.

**It cannot express a name no book carries.** "Le Guin, Ursula K." splits into two people,
neither of them spelled correctly. The repair is a name typed by a person, which a rewrite
would have to write into every affected book, editing the credit line on books whose
printed credit is not wrong.

**It multiplies across peer sync.** Every rewritten row takes a new `updated_at`, so one
tidy-up re-pushes every affected book to every peer, and two instances that tidy the same
names independently produce two rewrites of the same strings with no way to tell they were
the same decision.

So `author_aliases` stores the decision, `books` is never touched, and undoing a merge is
deleting one row. That is also what licenses the deduplication suggestions to guess: a
wrong suggestion accepted costs one row and one click to undo, which is why
`authors.suggest_merges` is allowed to be lossy in the way `_duplicate_key` already is.

### Three keys, and only the conservative one folds without asking

| Key | Folds | Decides |
|---|---|---|
| `author_key` | case, accents, punctuation (which becomes a space) | automatically, nobody asked |
| `squashed_key` | the above plus every space | a suggestion, somebody confirms |
| an alias row | anything at all | a person, reversibly |

The line between the first two is a counter-example rather than a principle:
`author_key` folds `J.R.R. Tolkien` into `J. R. R. Tolkien`, and the rule that would also
reach `JRR Tolkien` folds `Ann Aker` into `Anna Ker`. An automatic fold has no row to
delete to undo it, so it has to be a difference nobody would call a decision.

### The credit line is split on commas, and the importers' flip rule is not reused

`books.author` is comma separated. Every writer of it says so: `metadata._marc_authors`,
`_bnf_authors` and `google_books` all join with `", "`, and every import path runs a single
name through `flip_catalogue_name` first, so a catalogue-order name is flipped **before**
it reaches the column.

This is a different decision from the one `categories` made, and the two must not be swapped.
Categories are semicolon joined *because* Google's category names contain commas
("Fiction, general"). Author names contain commas too, and the field is comma separated
anyway, because a comma in it means "and" far more often than it means a name in catalogue
order.

`flip_catalogue_name` therefore cannot be reused on a stored credit line. It flips on
exactly one comma, which is also what "Terry Pratchett, Neil Gaiman" has, so applying it
here would mangle every two-author book on the shelf. What is left is a residue: a name
that reached the column in catalogue order anyway splits into two people. That residue is
exactly what merging exists to repair, and the `fragment` suggestion rule is aimed at it.

### The author page is the library, filtered

There is no `/authors/{key}` page. The index at `/authors` lists everybody with their book
count, spellings and merges, and following one goes to `/?author=<key>`, which is the
library grid with a removable chip: the same route `/series` already takes.

The alternative was a page of its own rendering the books itself, which means a second book
grid in a second page folder, kept in step with the first through every later change to a
book card. "Everything by this person" is a filtered library, and the library is already the
thing that renders a filtered library well: it sorts, pages, filters further and shows the
same cards as everywhere else.

### Deduplication has two entry points, and the suggestions are the smaller one

The suggestion rules catch a spelling, an abbreviated given name and a fragment. A
**misspelling** is none of those. `Tolkein` against `Tolkien` shares no word, no surname and
no squashed key. `Fyodor Dostoyevsky` against `Fyodor Dostoevsky` does share a word, and
still produces nothing: the fragment rule wants one name's words to sit *inside* the other's
and neither is a subset, while the initials rule buckets on the last word, which is the word
that is misspelled. Both were run against `suggest_merges` and both return `[]`. They are
exactly what an alias row is for, and the first thing `models.AuthorAlias` names as its
purpose.

So the authors page also folds names by hand: select any two, keep one of their names or type
a third. One name selected on its own is a **rename**, which is the same write and was
unreachable for the same reason. Shipping only the suggested path would have made
deduplication reachable exactly where a heuristic had already guessed for you, which is the
opposite of what the feature is for.

The rules are not therefore redundant. They are what turns "I know these two are the same" into
"here are the six pairs worth looking at", which is the part a person cannot do by scrolling.

### Merging is any member's, and so is undoing it

The same rule as creating and renaming a collection, and for the same reason: it is
reversible, and a shelf only an admin may tidy is a shelf nobody tidies. Deleting a
collection is admin only because it strips a label off every book at once with no undo;
nothing here has that shape.

### `importing.py` owns applying an export, `csv_import.py` stays pure underneath

The third module in the same series and found the same way, by measuring after the second
shipped. `csv_import.py` was already right: 12 public names, no session, decode and sniff and
map and parse. Everything the database knew about **applying** the result was in a route
handler: the catalogue index, the matching, the gap filling, the tag invention, the reading
record and the review, with a **143 line** `import_csv` around them.

`routers/imports.py` went from **511 lines to 182**. `Import.for_member(db, member_id)`
mirrors `Shelf.seen_by` and `Authorship.seen_by`.

**The index does not make the per row cost zero and must not claim to.** `find` still issues
one `db.get` for a matched row, because that is the lookup that has to return a live object
rather than an id. What moved from per row to per import is the ISBN query, the title query
and the status query. The old 25,001 figure counted every statement including writes, so no
new total is derived from it; what is pinned is the **slope in SELECTs**, and it is one.

**The rule this module exists to protect is not about speed.** A row whose ISBN belongs to a
Book the Member cannot see is counted as unmatched and its title is never reported. Creating
it raises on the unique index, which aborts the whole transaction so a 5000 row import
silently writes nothing, and the 500 against 200 difference is a clean oracle for "does a
Book with this ISBN exist in this house". `skipped` merges it with the rows that had no
title, because separating them out would be the oracle by another route.

### SQLite folds case in ASCII and Python does not

`func.lower(Tag.name) == key`, with `key` folded in Python, looks like one comparison and is
two different functions. Measured: `lower('Ästhetik')` is `'Ästhetik'` in SQLite and
`'ästhetik'` in Python.

So a Tag carrying a non-ASCII capital never matched, the import decided the name was new, and
the insert hit the binary `unique=True` on `tags.name` with a name already there. That raised
`IntegrityError` **and took the whole file with it**: a member with one German shelf name
imported nothing, every time, with a 500. Any member could plant such a tag through
`POST /api/tags` or one earlier import.

The fix is to fold on one side only: `importing.Import._tags_by_folded_name` reads the Tag
table once and keys it with Python's `.lower()`, so a cache miss means genuinely new. It also
turns one query per unseen name into one per import.

**The general rule: never compare a database fold against a Python fold.** If a lookup folds
case, do it in one language, and prefer Python where the set is small enough to hold.

The third instance was `routers/collections.py`, issue #77, and it was a different severity
rather than the same bug waiting. There the check folded in SQLite and the index it backed,
`uq_collections_name_nocase`, was `lower(name)` in SQLite too, so the two **agreed** and
nothing raised. The cost was that `Ästhetik` and `ästhetik` coexisted as two Collections
while `Fiction` and `fiction` did not. Fixing the check alone would have split the pair and
turned a quiet duplicate into an `IntegrityError`, so the index had to change, which needed
a migration: see *A collection's name folds in Python, and the migration that did it merges*
below.

**Where two lookups fold the same set, they must break a tie the same way, and stability is
not enough.** A dict comprehension and a `next(...)` over one `order_by(Tag.id)` are both
perfectly stable and land on opposite ends: the first keeps the last key written, the second
takes the first row. Measured on Tags at ids 106 and 107, the import resolved the pair to 107
and `create_tag` to 106, while both docstrings cited the ordering as what made them agree.
Both now take the first, matching `_first_wins` in the same module. Such a pair is reachable
on any database that met the bug above, because the old `create_tag` created exactly it.

### A collection's name folds in Python, and the migration that did it merges

Issue #77. `uq_collections_name_nocase` was a functional index on `lower(name)`, chosen over
a stored lowercase column "so there is one name and not a copy of it that can fall out of
step". The index it chose does not keep the promise the class docstring makes: SQLite's
`lower()` folds the twenty six ASCII letters and leaves every other letter alone, so
`Ästhetik` and `ästhetik` were two shelves while `Fiction` and `fiction` were one.

`COLLATE NOCASE` is the same twenty six letters in different words and fixes nothing:
measured, `'Ästhetik' = 'ästhetik' COLLATE NOCASE` is 0 while
`'Fiction' = 'fiction' COLLATE NOCASE` is 1. A Unicode aware `lower()` in SQLite needs the
ICU extension, which this image does not build, and a Python UDF registered per connection
would leave the index unmaintainable by any connection that had not registered it: the
`sqlite3` CLI, a restore, an ad hoc script. **Between a rule enforced on a derived column
and a rule not enforced at all, the derived column wins**, so `collections.name_folded` is
stored and `uq_collections_name_folded` is a plain unique index on it.

**What keeps the copy in step is that one function derives it.** `fold_collection_name`
in `models.py` is the whole derivation, and three sites call it, because three sites need
it and only one of them can use a validator: `Collection._fold_the_name`, a
`@validates("name")` hook covering both ORM writes; `routers/collections._named`, which
folds an incoming name to compare against the stored column; and `backup._parse_row`,
whose Core insert fires no validator. An earlier version of this entry and the comment in
`models.py` both claimed one *place* derived it, which was false in the same three sites,
and the `.lower()` versus `.casefold()` note below is exactly the change that would have
split them.

Three things follow at the restore, none of which grep showed the first time. An archive
taken before the column existed would otherwise raise `IntegrityError`, which is not
`RestoreError`, so the route would answer 500 rather than 400. A hand edited archive could
store a fold disagreeing with its name, which a unique index can never catch because it
only catches duplicates. And a name that is not a string is **refused** rather than skipped:
SQLite's TEXT affinity converts `1` and `true` to the string `'1'`, so skipping the
recompute for a non-string let two collections a reader cannot tell apart through the
index with folds describing no name.

**A pre-revision archive holding a colliding pair is refused, not merged**, which is the
opposite of what the migration does with the same pair, and the difference is the caller.
The migration is an upgrade nobody asked for and cannot consult, so it merges and logs. A
restore is something an admin chose to do to a file they hold, so `_refuse_a_colliding_pair`
names both spellings and asks them to merge in the source library. That is
`rename_collection`'s rule, not the upgrade's.

**`.lower()`, not `.casefold()`.** Casefold makes `Straße` and `STRASSE` one shelf, which
may even be the better answer, but `create_tag` and `importing.Import` both fold tag names
with `.lower()`, and a library where tags and collections fold differently is a worse defect
than either rule alone. Changing it is a decision that changes tags too.

**The migration merges, and that is not `rename_collection`'s rule being bent.**

A database already holding the pair cannot keep both under the new index, and the owner
settled it: merge, into the lower id. Lower id because that is how `_first_wins` in
`importing.py` and `create_tag` break the same tie, and two folding rules disagreeing about
the winner is the defect recorded above. Refusing to migrate was the alternative and was
rejected: in a household with no operator that is an app that stopped overnight, and the
person who can fix it may be the person who cannot read the log.

`rename_collection` still answers 409, and its docstring now says why both are true: it
refuses because a person typing a name has asked for that name and not for two shelves to
become one, while an upgrade has no caller to ask and no other resolution.

**The trap the merge had to be built around.**

**`PRAGMA foreign_keys` is 0 in a migration connection.** The `ON` listener is bound to
`database.engine`; Alembic builds its own in `migrations/env.py`. So `books.collection_id`'s
`ON DELETE SET NULL` does not fire during a migration, and a book missed by the repoint does
not get unfiled, it keeps a **dangling** id. Because the survivor is the lower id, the row
deleted is the higher, which is the rowid SQLite hands to the next insert: measured, the
book then reads as being in an unrelated collection created later.
`migrations/versions/d4a91f3c72e8_user_defined_tags.py:48` already recorded the identical
trap for tags. Hence: repoint every `books.collection_id` first, delete the losers second,
and check that nothing dangles, because nothing else in the stack complains.

**A failed revision may not roll back on SQLite, and where the checks sit is what works
around that.** Alembic's `SQLiteImpl` sets `transactional_ddl = False` (verified on alembic
1.19.1), so `context.begin_transaction()` in `migrations/env.py` returns a null context and
nothing wraps the revision. What is left is pysqlite's own rule, and it is conditional
rather than a flat split: **pysqlite opens a transaction for DML only. DDL executed while
no transaction is open is durable immediately; DDL executed after any DML statement joins
that transaction and rolls back with it.** Measured on the installed stack, sqlite 3.50.4:

| Sequence | After the failure |
|---|---|
| `ALTER TABLE`, raise | the column is there |
| `UPDATE`, `ALTER TABLE`, raise | the column is gone, the update is gone |

Both halves matter here, and this revision contains both, on different databases.
`op.add_column` is the first statement **only where there is no pair to merge**, and there
it is durable on its own: that is the case originally measured, where the column had
landed, the backfill had not, and `alembic_version` still named the previous revision, a
state no rerun can apply twice. Where a merge ran, the repoint and the delete opened the
transaction first, so `add_column` joins them and rolls back. The later `op.drop_index`,
batch rebuild and `op.create_index` follow the backfill `UPDATE` on every database, so
those always roll back.

The conclusion is unchanged and the reason for it is narrower than "DDL is never
transactional": because *some* DDL is durable, a check placed after any of it can leave a
half-applied database. So both dangling checks run **before the first DDL statement**, and
a database arriving with a dangling id is refused with the file untouched. This applies to
every future migration here, not only this one.

An earlier version of this entry stated the split unconditionally and was wrong in both
directions. It was caught by a critic re-measuring the claim rather than reading it.

**A dangling id is a hard failure, not a repair.** Nulling the column would unfile books the
revision exists to keep filed; carrying on would file them under whatever collection later
takes the freed rowid, which is worse because nobody can see it. The app cannot write one:
`delete_collection`, the ORM and `ON DELETE SET NULL` under `PRAGMA foreign_keys=ON` each
prevent it, so arriving with one means the rows were edited by hand.

**Index ordering around the SQLite table rebuild.**

The column is made NOT NULL with `batch_alter_table`, which rebuilds `collections` by
reflecting it. Reflection loses an index on an expression: measured, reflecting the table
warns "Skipped unsupported reflection of expression-based index uq_collections_name_nocase"
and returns without it. So the old functional index is dropped **before** the rebuild rather
than carried through it, and the new unique index is created **after**, where nothing can
drop it and where a merge that somehow left a duplicate fails rather than ships. The foreign
key from `books` and `ix_collections_id` both survive the rebuild, which is asserted rather
than assumed, because `collections` is the parent side of that key.

**The downgrade cannot un-merge.** It restores the schema, the losing rows and their names
being gone, and says so rather than pretending.

**Ordering by name was deliberately not part of this.** No fold moves `Ä`, which is above
every ASCII letter, so `order_by(func.lower(Collection.name))` stays and is a different
problem with a different answer: see *Name lists are ordered in the browser, not by the
database*.

### A route docstring is API documentation, not an internal comment

FastAPI serves a handler's docstring as the operation description at `/docs`, `/redoc` and
`/openapi.json`, and `orval` ships it as a doc comment in `frontend/src/api/generated/`. So
a route docstring has an audience that cannot open the repository.

Recorded because moving logic out of two handlers took their documentation with it.
Measured on `openapi.json`: `POST /api/books/authors/merge` went from **1277 characters to
395** and `DELETE /api/books/authors/aliases/{id}` from **853 to 198**, and what replaced
them was a pointer to `authorship.Authorship.merge`. Gone from the served description: that
nothing in `books` is written, that an author nobody can see is 404 and not 403, that a
`keep_name` no book carries is allowed, and what an orphan alias is. Both critic seats found
it independently, and the same session's other refactor had moved two descriptions the
**other** way, which is what made it a regression rather than a style.

**"Make the handlers thin" is about code.** The split is: caller-facing rules stay in the
handler, implementation reasoning goes on the module, and the handler ends with one line
naming where that reasoning lives.

The corollary is a house rule that already existed and was broken twice in one session:
**regenerate the client after any change a docstring or a schema makes to the OpenAPI
document**, not only after a field change. Nothing in CI catches a stale client, and
`bun run api:generate` cannot run on the test host, whose frontend image has no `uv`: dump
the schema locally with `uv --directory backend run python scripts/dump_openapi.py` and run
`orval` on its own.

### `authorship.py` owns author identity, and `authors.py` stays pure underneath

`authors.py` was always the right module: `author_key`, `squashed_key`,
`resolve_alias_map`, `build_index`, `suggest_merges`, no session, no writes, easy to test.
Its purity was never the problem. The problem was that **everything the database knew about
"these two spellings are one person" lived in a route handler**: the index query, the merge
write, the repointing pass, the alias delete, and the resolution behind `?author=`. The pure
functions had been extracted so they could be tested, and the failures that mattered were in
the calling code left behind. A locality problem, not a testing one.

`authorship.py` owns both halves and takes the session at its seam. `authors.py` is
unchanged and is now the implementation underneath, still imported directly by the three
modules that need `AUTHOR_NAME_MAX`, `author_key` and `split_authors`: `models.py`,
`schemas/author.py` and `schemas/book.py`. The four routes are one to six lines each.

Two things worth recording:

**The index is read fresh, and there is no cache.** An earlier version cached it per
instance and invalidated it from the two writes. It saved nothing: no path reads the index
twice without a write between the two reads, `merge` loads, writes and loads again for two
loads either way, and every route builds an instance for a single call. It was removed on
this module's own argument against a session watcher, machinery guarding a caller that does
not exist. What is pinned is the behaviour that still has to hold: one read costs two
statements, and a read after a write is not stale.

**It raises `AuthorNotFound`, not `HTTPException`.** The module does not know what HTTP is.
The router maps the exception to 404 rather than 403, for the reason an invisible Book is a
404: a 403 confirms that somebody owns a book by that name. Splitting the two made the rule
testable as a rule about names rather than as a status code.

### Book duplicates are not author identity

`GET /duplicates` and `POST /merge` were listed inside the author cluster's line range and
are deliberately **not** in `authorship.py`. They share a normalisation, `_duplicate_key`
folds a title and an author with the same `author_key`, and nothing else: they ask "is this
the same **Book**", and the alias table answers "is this the same **person**". Neither reads
nor writes `author_aliases`.

Folding them in would have moved code without anything becoming deeper, which is the exact
test the router split failed. If the duplicate scan ever earns its own module, the thing it
would own is `_duplicate_key`, `_one_per_copy_group`, `_absorb_fields` and
`_repoint_relations`, and that is a different module from this one.

### The alias mapping is library wide; the shelf is what `visible_to` filters

The same shape as a collection, shipped the day before: **the name is everybody's, the count
is yours.** Every alias applies to every member, so one book is filed under the same person
for all of them, `?author=` resolves identically for all of them, and a `canonical_name` is
not withheld from anybody.

**The privacy rule is one line and it is not on the mapping.** An author entry exists only
because `counts` was populated, and `counts` is populated only from rows a query filtered
with `visible_to`. So an author whose every book is private appears for nobody else: no book
the other member can see is credited to a spelling that resolves to that person, so no entry
is built. The mapping says who a name means; it never says a book exists. A row proves even
less than it looks like it does, because it outlives the book it was created for: an alias
whose spelling nothing carries any more is an orphan that maps a name nothing is credited
with.

**Filtering the mapping per caller was built, reviewed and withdrawn**, and the reasons are
worth keeping because the idea is an attractive one:

* It made **identity** per member. One book resolved to a different key *and* a different
  display name depending on who asked, which is not a narrower view of one catalogue, it is
  two catalogues.
* It **broke an old link**. A spelling in the middle of a chain is on no book at all, so a
  per-caller gate dropped it for everybody and `?author=` answered "nothing by her" for a
  name that had just been merged.
* The merge endpoint gates on a different set (`reachable`, which is keyed on canonical
  names), so **the two gates disagreed**, and `list_authors` handed a member a string that
  the merge endpoint would then answer questions about. The narrow gate leaked what the wide
  one withheld, with no guessing required.

What is still filtered is what a member has evidence for. `AuthorOut.merged` lists a folded
spelling only where it appears on a book the caller can see, and `DELETE
/authors/aliases/{id}` refuses one that does not: **undo what you can see the effect of.**
That is authority rather than secrecy, and its cost is the orphan above, which is unreachable
and therefore undeletable. Accepted: it changes no view, and it starts working again by
itself if an import re-creates the spelling, which is the property the whole design is for.

`POST /api/books/authors/merge` still answers 404 for an author that exists only on somebody
else's private book, exactly as an invisible book is 404 rather than 403: that question is
about the shelf, and any other answer confirms a book is on it.

### Author aliases never cross to a peer

The peer payload carries `author` as the string on the book, and
that does not change: a peer receives the credit line as printed and applies its own
library's decisions to it, if it has any. An alias is shelf taxonomy in the same class as
`location` and a collection name, and it is one library's reading of its own shelf.

This is the property the rewrite alternative could not have had. Since merging writes nothing
to `books`, a merge changes no `updated_at` and produces no sync traffic at all.

### Merging repoints through the ORM, not a bulk UPDATE

A bulk `UPDATE ... synchronize_session=False` leaves the session's loaded collections
stale, and the `db.delete()` that follows cascades straight through them, deleting exactly
the notes, quotes, loans and statuses just moved to the survivor. The rows are reassigned
object by object and the losers are expired before deletion.

Relatedly, the losers release their ISBN in **its own flush** before the keeper absorbs it.
Doing both in one flush puts them in a single `executemany` where the set lands before the
clear and trips the unique index.

### A quote is its own table, not a page number on a note

BookLogr, the Apache-2.0 reference for this feature, has no quotes table: it adds a
nullable `quote_page` to its notes table, and a saved quote is a note that happens to
carry one. That was the cheaper option here too and it was refused, for a reason that
shows up the first time anybody asks a question of the data: nothing in that shape can
tell a quote from a note whose author remembered the page.

The sharper reason is what the two fields are for. `quotes.text` is meant to be a
**faithful transcription** of somebody else's sentence; `notes.content` is the member's
own words about the book. One column holding both is the column where the verbatim
promise quietly stops being true, and it is also the column somebody will later want to
render as a blockquote and be unable to.

So `quotes` carries `text`, an optional `page`, and an optional `note` for the remark. The
excerpt and the remark are separate columns for the same reason the table is separate.
**BookWyrm** does the same, and it is the best worked example of quotes from books
anywhere; it is also **ACSL v1.4**, which is compatible with neither GPL nor MIT, so it
was read and not borrowed from. Nothing here is derived from its code.

### What was left off a quote, and why

Four fields that a reference implementation has and this one does not. Recorded so nobody
adds one back thinking it was an oversight.

| Field | Where it exists | Why not here |
|---|---|---|
| `endposition` | BookWyrm | It stores a **range**, needed because it also renders percentages and ebook locations in a federated post. There is no reader here and no range to draw. |
| `position_mode` (page or percent) | BookWyrm | Same reason. `reading_progress` carries a percent because an audiobook has no pages; a quote is copied out of something with a page or out of nothing at all. |
| per-quote `visibility` | BookLogr | It has a **public profile**, so a row-level visibility is what decides whether the world sees a quote. Nothing here is public, and privacy in this schema is a property of the book. |
| a favourite flag | BookWyrm has social `favorites` | That is other people liking a post. There is no social layer here, and "my favourite of my own quotes" is a second ranking beside the shelf's tags. |

### The page is an integer, so a preface has no page

`quotes.page` is an `Integer` bounded 1 to 100,000, where BookWyrm's equivalent is free
text. Free text would take "xiv", "loc. 3312" and "about a third in", all of which somebody
will want; what it would not do is sort, and a book's quotes coming back in reading order
is the only ordering that makes the list worth reading down.

The cost is real and is accepted rather than worked around: a passage from a roman-numbered
preface is saved unpaged, and unpaged quotes sort to the end. If free-text positions are
ever wanted, they are a second nullable column, not a widening of this one, because
widening it silently unsorts every list that exists by then.

`ck_quotes_page_bounds` states the same rule in the database, because a restore inserts
through Core and never sees `QuoteCreate`. The number lives once, in
`models.MAX_PAGE_NUMBER_IN_A_BOOK`, and `schemas/progress.py`, `schemas/book.py` (twice)
and `csv_import._int` now read it from there: it was written out **four** times before
this change, and a CHECK that disagreed with a schema bound would answer 500 for exactly
the values between them. `csv_import` was the one that stayed behind on the first pass,
found on review, and it is the one that matters most: an importer admitting a page count
the API refuses is a second answer to the same question.

The **length** ceilings are enforced the same way and were nearly not.
`quotes.text` is `String(2000)`, and SQLite ignores VARCHAR width entirely: a Core insert
of 50,000 characters stored 50,000, measured. So the model and the migration both carry
`ck_quotes_text_bounds`, covering `text` and `note`, and the docstrings that said the
ceiling was "in the database and not only in the schema" are now true rather than
aspirational. Nothing member-facing could reach it (only `backup.restore` bypasses
`QuoteCreate`, and it is admin-only), so this closed a false claim rather than a live
hole, which is exactly the kind of thing that becomes a live hole two features later.

### A quote is visible to whoever can see the book

Two precedents in this codebase point opposite ways. `get_notes` returns **every member's**
notes on a book anyone may read; `list_progress` returns **only the caller's own** rows,
because a reading log is a diary about a person rather than a fact about the book.

Quotes follow the notes. A passage is a fact about the book, and copying one out is the
library saying "this is worth reading", which is the whole pleasure of the feature. The
alternative would be a per-row privacy flag, and that is the expensive part: privacy in
this schema is a property of the **book**, expressed once in `visible_to()`, and a second
rule that every query has to remember is the one that eventually gets forgotten.

The copyright argument cuts the way it first appears not to. A quote is a verbatim excerpt
of somebody else's work, but showing it to the four people who share the shelf the book
sits on is not publication: this app has no public profile, no feed and no federation, and
a quote leaves the instance only in the member's own backup. That is what makes "follows
the book" safe here and would not make it safe in BookWyrm, which is federated and
therefore has per-status privacy. What the argument does buy is the length ceiling:
`QUOTE_TEXT_MAX` is 2,000 against `MAX_NOTE_LENGTH`'s 10,000, so the table cannot hold a
chapter.

The consequence to state plainly: a quote from a private book is invisible to everybody
but its owner, because the book is, and an invisible book is 404 rather than 403.

### A quote belongs to a copy, not to a work

Multiple copies shipped first, so a book row can be one of several joined by a
`copy_group`, and a quote from "the paperback" is arguably a quote from the work. It hangs
off the **book row** anyway, for one concrete reason: the page number is a fact about an
edition. Page 214 of the paperback is not page 214 of the hardback, and a quote promoted to
the work would carry a page number that is wrong for most of the rows it then appears
under.

Everything else per copy already lives this way (notes, loans, reading progress), so this
is the existing shape rather than a new one, and `_repoint_relations` moves quotes to the
survivor on a merge exactly as it moves notes. Merging two rows that were two printings
does leave their page numbers describing a printing that is no longer named; the
alternative is refusing the merge, which is worse.

`POST /{id}/copies` deliberately copies **no** quotes, for the same reason it copies no
notes or reading state: they belong to a person and an object, and the copy is an object
nobody has read yet.

**The cost this pays on `/quotes`**, which the first version of this entry left out: two
copies of one title render identically there. `QuoteCard` shows the title, the author, the
cover, the page and who saved it, and every one of those is the same for the paperback and
the hardback; only the link target differs. Accepted rather than fixed, because the fix is
`format` and `location` in the card footer and that is metadata about the object on a card
whose subject is a passage. It is the right thing to add the first time somebody actually
cannot tell two rows apart, and the schema is ready for it: `QuoteWithBookOut` already
takes its book fields as flat scalars, so it is two more columns in the same `SELECT`.

### There is a cross-book quotes page, and it is a book listing

`GET /api/books/quotes` and `/quotes` in the app exist because a quote saved and never
re-read is a write-only field. It is the feature's main pleasure in BookWyrm and it is
cheap here: one endpoint, one page folder.

It is also **a second book listing wearing a different hat**. Every row carries a title, an
author and a cover, so `visible_to()` filters the rows *and* the count, and a quote on
somebody's private book is neither listed nor counted.

**The count is spelled `count(Book.id)`, not `count(Quote.id)`, and it used to be a
decision.** The two are identical over an inner join on a primary key that is never null.
The difference was that `TestEveryBookQueryIsFiltered` identified a book query by the
arguments to `query()`, so the `Quote.id` spelling put the count outside the guard
entirely: removing its filter was measured to produce **no** offender, while removing the
row half's filter correctly reported the file. Both critics found this independently,
which is the strongest signal that review process produces.

That guard is gone (see "The Shelf owns the privacy rule"), and both halves are now rooted
at the shelf and joined outward to `quotes`, so nothing depends on which column is counted.
The spelling is left alone because a count of visible books is what it is, and changing it
would be a diff with no reader. Kept here because the reasoning is what a future reader
needs in order to know the constraint has been lifted rather than forgotten.

Editing is deliberately **not** offered there. A quote is corrected on the book it came
from, where the page number and the passage can be checked against the book in somebody's
hand, and a second editor would be a second place for the same rules to be got wrong.

**It pages with numbered Previous/Next, which is a third idiom in this app**, and the
reason is the row height. Home uses `useListBooksInfinite` with a "Load more" button; the
loans and trash lists ask for one large `page_size` and offer no controls at all. Neither
suits this one. A quote is up to 2,000 characters, so a page of fifty is a column of
unpredictable height that an infinite list makes unnavigable: with "Load more" there is no
way back to something seen two screens ago except scrolling past everything added since.
One large page is worse again, because the ceiling here is a library's entire history of
saved passages rather than its shelf. Numbered pages give a stable position to return to.
That is three idioms in one app, which is one more than anybody wants; the honest reading
is that Home's infinite list is the odd one out and the others should converge on this,
not that this should have copied one of them.

### One bulk endpoint, not six

Every verb shares the same three steps: resolve the ids the caller may actually touch,
apply, report. Six handlers would be six copies of the permission walk, and the fifth one
added would be the one that forgot it.

### `unrated` names its correlation explicitly

`.correlate(Book)` is not decoration. When the status filter has added its own `UserBook`
join, SQLAlchemy otherwise auto-correlates `UserBook` out of the subquery too, leaving it
with no FROM clause and raising rather than filtering. Found by a test that combined the
two filters.

### Python 3.14 is a hard requirement, and PEP 649 is why

`schemas/book.py` and `schemas/loan.py` reference each other under `TYPE_CHECKING`, with
unquoted annotations naming types that do not exist at runtime. That works only because
3.14 defers annotation evaluation. On 3.13 it raises `NameError` at import.

### The test suites were slow for reasons nobody had measured

Both suites were profiled rather than guessed at, and every intuition about
where the time went was wrong.

**The backend was not CPU bound.** Two xdist workers used **0.68 cores between
them**: the suite was waiting on fsync, not computing. Every test drops and
recreates nine tables and seeds 105 tags, so a run performs tens of thousands
of DDL statements and inserts against a database deleted microseconds later.
`PRAGMA synchronous=OFF` in tests and the database on `/dev/shm` took it from
**710s to 133s**. `SQLITE_SYNCHRONOUS` defaults to `FULL` and is whitelisted,
because it reaches a statement that cannot be parameterised; production keeps
FULL, which is what makes a commit survive a power cut on somebody's only copy
of a hand built catalogue.

Before that, `pytest-xdist` at `-n 2` had already halved it from 1370s. `-n 2`
and not `-n auto`: the CI pod is capped at two cores, and `auto` spawns one
worker per core only to be throttled back, which is the same work done slower
and makes the pod look like it needs a bigger limit.

**The frontend was not slow because of its tests.** `environment` was **168s of
a 245s run**, building a jsdom once per test file, and 11 of 78 files touch no
DOM at all. Those carry `@vitest-environment node`. The larger win was swapping
jsdom for **happy-dom**, which took the run to 178s.

**happy-dom does not inherit CSS custom properties down the tree.** A
`--color-*` token set on `documentElement` reads back on that element and
resolves to `""` on every descendant, measured with a two line probe. The
wallpaper resolves its ink, bloom and page from a child, so `isColour()` sees
empty strings and nothing is painted. Three files are pinned back to jsdom with
`@vitest-environment jsdom` for that reason alone; if happy-dom ever fixes it,
the pin comes off.

**Then the tests themselves.** 29 of 40 `user.type` calls became a single
`fireEvent.change`. Typing thirteen characters costs thirteen async round trips,
and a field with no per keystroke behaviour tests the same thing either way.
That took 178s to **140s**. Two calls keep `user-event` deliberately, because
`"{Enter}"` and `"{Escape}"` are keyboard semantics rather than text.

**What was refused: `deps.optimizer`.** It would pre-bundle dependencies with
esbuild and take a bite out of the 51s `import` bucket. It also produces a third
module graph, neither the dev server's nor Rollup's production build, and
`vi.mock` cannot intercept an import already inlined into a bundled chunk. Two
of the four mock sites here target `react-router-dom`. The failure mode is a
silent false pass, which is the one this repository is least willing to buy
speed with.

Net: a full local gate went from about 27 minutes to about 4.

### The per-test reset deletes rows, and two faster designs were refused

Measured in the CI pod, database on tmpfs, `synchronous=OFF`, warm:

| Reset strategy | Per test |
|---|---|
| drop, create and seed (what this replaced) | 58.8ms |
| **delete every table, reseed the tags in bulk** | **3.1ms** |
| keep the seeded tags, delete the rest | 1.0ms |
| open a transaction and roll it back | 0.8ms |

The suite went from 134s to **92s** on the second row. The two faster rows were
both refused, and the reasons matter more than the milliseconds.

**Rolling back a transaction per test** was built, reviewed by three seats and
abandoned. Binding every session to one connection means savepoints form **one
stack, not one per session**: a session that opened its savepoint first and rolls
back destroys the committed work of every session that committed after it.
Measured against the running application, that makes a privacy test vacuous, and
silently: a test asserting "another member gets 404" gets its 404 just as readily
when the book was never written at all. Sixty five privacy tests assert an
absence with nothing proving the row survived to the assertion, so a broken
`visible_to()` under a wiped fixture is a **green** run.

It had a second fault of its own. It held a write lock for a whole test rather
than a statement, and one unguarded `connection.close()` in its teardown could
leave a connection checked out holding that lock for the life of an xdist
worker. Observed once in thirty runs as 423 failures and 121 errors; twenty one
later runs could not reproduce it, and no seat could name what made the rollback
raise in the first place. The guard is worth having; the design is not, when a
row delete is three milliseconds slower and cannot fail that way at all.

**Keeping the seeded tags** is wrong for a duller reason: `backup.restore`
deletes and reinserts the tags table and `_repair_seeded_tags` rewrites
`is_predefined`, so a test can legitimately mutate a predefined tag and the next
test would inherit it.

The reset calls no `seed_tags()`. That helper opens its own session, which is a
second connection, and the point of this shape is that a reset never needs one.
Ids still restart at 1, which `covers_dir` depends on, because nothing here uses
`AUTOINCREMENT` and SQLite reuses the highest free rowid.

**One number in this file was wrong for a whole day and is worth naming.** The
rebuild cost was derived as 40.6s over 3236 rebuilds, giving 12ms. 40.6s was a
two worker wall clock, so the division halved a figure that direct measurement
puts at 58.8ms. A derived number that nobody measured is the kind this
repository is meant to catch.

### The remote test runner was reporting on a tree nobody had

It ships the working tree by piping `tar` into `tar -xf` on a **persistent
hostPath**. Extraction adds and overwrites and never deletes, so a file removed
locally lived on in the runner's copy indefinitely. A reviewer's scratch test,
deleted an hour earlier, still failed `ruff check .` and contributed two pytest
failures against a tree that no longer contained it.

`rm -rf` before extracting fixed that and created a worse fault: two runs share
the hostPath, so the second deleted the first's working directory mid run. The
symptom named neither cause, being `Module not found .../vitest/dist/workers/
forks.js` followed by a rolldown panic reading "Failed to get current dir". Two
runs were spent blaming a vitest config.

Each run now extracts into `/work/repo-$POD` and removes it in the exit trap.
The dependency caches stay shared at `/work/cache`, which is the reason the
hostPath exists. This matters more than it did: the runner serving this project
is at `concurrent: 2`, so two real CI jobs can now land together.

### A seeded tag is identified by a key, not by its name

Predefined tag names are shown in the member's language, and the row a
translation belongs to is found by `tags.key`, never by matching the name.

Matching on name at display time repeats the bug the seeding migration
`95b6a61d6668` exists to fix: it breaks the moment a household renames a tag,
and it makes the English name load bearing in two places. A boolean
`is_predefined` records that a row was seeded without saying which seeded tag
it is, so it cannot pick a translation. The key survives a rename in either
direction, and a renamed row simply has no key: it is an ordinary invented tag
from then on, shown as typed.

English is not in the translation table. The name in the database is the
English name, so `TAG_NAMES` covers every locale except English by type
(`Exclude<Locale, "en">`), and a language added later has to supply a full
table or the build fails. That is the same property `de.ts` has, obtained the
same way.

Only display changed. `ddc.tag_names` still projects a classification number
onto an English seed name and `match_subjects_to_tags` still reads the caption,
because the suggestion travels as a tag **id**.

**A rename drops the key, and that is enforced rather than asked for.**
`Tag._drop_the_key_on_a_rename` is a `@validates` hook on `name`, so a rename
through the ORM clears the key in the same write. Three paths skip it and are
named where it is defined: Core inserts, `Query.update()` and
`bulk_update_mappings`. Unlike `Collection._fold_the_name` there is no unique
index behind this one, because `uq_tags_key` enforces one row per key and
cannot enforce that the key still matches the name: that is a fact about
`PREDEFINED_TAGS`, which only the app has.

**An unknown key is forgotten, not refused.** `KnownTagKey` is a
`BeforeValidator` on `TagOut.key` and `TagStat.key`, so a row carrying a key a
later version dropped loads as an ordinary tag instead of 500ing the whole tag
list. A guard in `tests/test_schemas.py` requires that annotation on any third
model growing a `key`, and it checks the validator **is** `known_key` rather
than that some before validator exists: written the loose way it passed clean
against a model with its own validator, which is the shape it will actually
meet.

### The Catalogue record is a type, and the two dialects are gone

Six source adapters used to hand their answer across the seam as
`dict[str, Any]`, in **two** shapes. A lookup record carried `isbn` and a list
of `subjects`; a search match carried `isbn13`, a `source`, a `google_books_id`
and `categories`, the same subjects joined into one string. Two functions
existed only to cross between them, and one of them lived in a route handler.

`catalogue.Record` replaces both. What moved behind it, and each of these was
previously a rule somebody had to remember:

* Folding a heading a record repeats. One live K10plus record's 082 `$a` values
  read `100`, `610`, `610`. Three sites deduplicated: `metadata._dnb_subjects`,
  `_as_match` and `_merge`. Now one, at construction.
* Filling a caption from whichever source has one, never overwriting.
* That an **empty collection is an absence where an empty string is a value**.
  This was a live defect: `classifications` was the one list valued key a match
  carried, a source finding no heading wrote `[]`, and `[]` is not `None`, so it
  beat a populated list from the next source. Measured over 30 live title
  searches, 6 of 10 merged rows whose Library of Congress half carried LCSH lost
  every heading. The scalars and the collections are now separate fields with
  separate rules, so the two conditions cannot be confused again.
* Which fields score `completeness`.
* That several catalogues answering for one book are one row naming all of them.

**Two folding rules, named separately rather than one function with a flag.**
`merged_with` is the lookup path and unions the collections, because every
record it folds was found by the same verified ISBN and so describes the same
printing. `filled_from` is the search path and does not, because two rows meet
there on a title and a year, which is a guess, and because a search row is
bounded at `MAX_CLASSIFICATIONS_PER_BOOK` before it becomes a `BookMatch`:
unioning two full rows would cost the row rather than the heading.

**ADR 0006 is now held by the type.** `as_lookup()` and `as_match()` return the
scalar facts and no Classifications. Automatic enrichment and Refresh Metadata
write from those dictionaries, so an unattended writer has nothing to write even
by mistake, where before it was two route handlers remembering not to.

**A record folds its collections once, and the flag that says so is load
bearing.** `Record._folded` is checked first in `__post_init__`, and
`merged_with` is the only `replace` that resets it, because it is the only one
that concatenates. Without it the fold re-ran on every `replace`, and
`_merge_matches` folds every row sharing a title, an author and a year onto one
slot, so the cost became the **product** of the row count and the surviving
record's width. Measured on a four core worker, one process: 8,176 rows against
a record carrying 22,784 subjects and 11,392 headings, which is the worst shape
fitting inside `fetch.MAX_RESPONSE_BYTES`, took 125.970s without the flag and
0.227s with it. `_merge_matches` is synchronous inside `async def search`, so
that is the event loop stopped for every member at once, and
`SEARCH_DEADLINE_SECONDS` does not bound it: that bounds `_within_deadline`,
which has already returned.

**Two rules keep it, in `tests/test_house_rules.py`, because a comment does
not.** Nothing outside `catalogue.py` names `_folded`, and a module that could
hold a `Record` does not call `dataclasses.replace`: `Record.with_cover()`
exists so that the one caller which needed to has a method instead. Both critic
seats reached this independently and neither found a live offender, which is the
point. The second rule is scoped to modules importing `catalogue` rather than to
every backend module, because seven others define frozen dataclasses that have
nothing to do with this; the gap that leaves is listed in the guard's docstring.

**The severity was recorded wrong twice, in opposite directions, and how is
worth keeping.** The comment first claimed over 120 seconds against a shape of
8,001 rows and 1,913,056 wire bytes. A reviewer re-derived it from those inputs,
got 0.854s, and refused to sign off: the shape was wrong. It was then corrected
to say the figure did not reproduce, and **that correction was wrong too**, as
the next round showed by measuring the actual worst case at 125.970s. The
original timing was real and taken at a shape nobody wrote down. Both errors
have the same cause and the rule that a stated number says what it was measured
against catches both, including when the statement is a retraction.


### The Austrian National Library is a third MARCXML source, and the probe is why it works

Added 2026-08-27. Austrian imprints were reaching members as hand typed records,
because the four catalogues this app asked cover Austrian publishing thinly. The
ÖNB publishes its catalogue over Alma SRU: CQL in, MARCXML out, no key, CC0.

**Third MARCXML source, fifth SRU one**, and the counts differ because the
schemas do: the DNB answers `MARC21-xml`, K10plus and the ÖNB answer `marcxml`,
the BnF answers `dublincore` and the Library of Congress answers `mods`. Calling
it "a fifth MARCXML source", as an earlier draft of this section did, conflates
the two.

**The whole item was blocked on one fact that no documentation states, and
guessing it fails in the worst available way.** The published examples establish
the MMS ID, AC number, barcode and title indexes and say nothing about the ISBN
index. The index is `alma.isbn`, confirmed by reading an ISBN off a live record
and putting it back through the index rather than by reading anything.

What makes it worth a paragraph is the failure mode. A wrong index name is not
an error and does not return nothing. Measured live against one ISBN:
`alma.isbn=` returns 1 record, and both `alma.isbn13=` and `zzz.qqq=` return
**7,793,152**, the entire catalogue, under HTTP 200 with no diagnostic. So a
typo would have answered a member's scan with a well formed MARC record for an
arbitrary unrelated book. The only thing between that and a shelf is the check
that a returned record's own 020 carries the ISBN asked for, which already
existed for the DNB and K10plus for a different reason. It is now load bearing
for a third source in a way it was not before, and that is written at the
constant rather than left in a commit message.

**Every error this endpoint reports arrives as HTTP 200.** An invalid query and
an unsupported one both come back as a well formed envelope carrying an SRU
`diag:diagnostic` and no records. There is deliberately no branch for it: the
body parses, no record is found, and the source reports nothing, which is the
correct degradation. It is pinned with a recorded diagnostic so that staying
correct is checked rather than assumed.

**A bare multi-word term is one of those invalid queries**, so ANDing the terms
is a correctness requirement here where the same shape in `_k10plus_search` is a
precision preference.

#### Where it sits, and the measurement that put it there

It is asked after the DNB and K10plus and before Open Library. 50 ISBNs, five
each from ten Austrian presses, taken off live ÖNB records printed after 2005:

| catalogue | held | mean latency |
|---|---|---|
| ÖNB | 50 / 50 | 0.240s |
| DNB | 47 / 50 | 0.210s |
| K10plus | 39 / 50 | 0.390s |
| neither of the German pair | **3 / 50** | |

Six percent is a floor rather than an estimate, and the shape is why: every ISBN
came off an ÖNB record that carried one, from ten well known presses, which is
the half of Austrian publishing the German catalogues are likeliest to hold too.
That is enough for a fallback and not enough to widen the fast pair everybody
pays for.

#### Two defects the mapping would have shipped, neither visible by reading

**The non-sorting delimiters are spelled differently.** MARC brackets a leading
article so a catalogue can file it, and the DNB writes U+0098 and U+009C, which
is what MARC21 specifies. The ÖNB writes `<<` and `>>` and writes U+0098 nowhere.
21 of 150 live 245 `$a` values carry a bracketed run. It is also used for
nobiliary particles inside personal names, `Einem, Gottfried <<von>>`, so 28 of
the 111 runs in 21,760 subfields are not at the start and it reaches `100 $a` as
well as `245 $a`. Both spellings are now stripped for every source rather than
for the ÖNB alone, which is safe by measurement rather than by hope: `<<` and
`>>` appear in 0 of 32,038 live DNB subfields and 0 of 45,710 K10plus subfields.

**Over half of what a title search returns is journal articles.** Measured over
8 live title searches, 155 of 280 records are MARC bibliographic level `a`, a
monographic component part: an article or chapter with a 773 host item entry and
usually no 300 extent at all. `_is_physical_book` catches none of them, because
it tests the extent for an online form and the title for a volume slot and an
absent extent passes both. The MARC leader is now read for this source.

The leader decides rather than the 773, and that was measured against the same
280 records rather than reasoned about: the leader catches 155 of 155 and loses
**0** of the 122 monographs, where refusing anything carrying a 773 catches the
same 155 and loses 3 monographs that carry a host entry legitimately.

#### A `ValueError` from the parser, found while adding the seventh source

`_pages_from_extent` matched `(\d+)` and called `int()` on it. CPython refuses
an int/str conversion of more than `sys.get_int_max_str_digits()` digits, 4,300
by default, and raises **`ValueError`**, which is neither `httpx.HTTPError` nor
`ElementTree.ParseError`, so **none of the eight SRU handlers caught it**. One
MARC record carrying 4,301 digits in its `300 $a` turned `GET /api/books/search`
and `GET /api/books/lookup` into a 500 for **every MARC source at once**.

**The response cap could not reach it**, and that is what makes it worth a
section rather than a line. The poisoned envelope measures **4,870 bytes**,
0.23% of `MAX_RESPONSE_BYTES`. The percentage is the weaker way to say it: the
poison is **larger than the smallest honest response that source sends**, whose
floor is **4,585 bytes** over 50 live lookups, so no cap that still admits a
real lookup could ever have refused it. A transport bound and a parser bound
are not substitutes, and this measures it rather than asserting it.

`_LOC_URL` is plaintext HTTP, so it needed no compromised catalogue: it is the
same on-path attacker `fetch.RedirectedOffHost` already exists for. It was
pre-existing for six sources and this item added a seventh, and user story 6
asks for exactly "a hostile or oversized catalogue response refused rather than
parsed", so it was in scope rather than beside it.

The digit run is now bounded and range checked against
`MAX_PAGE_NUMBER_IN_A_BOOK`, which `_open_library_pages` has always applied to
the same field from the other source: this was the only `int()` on catalogue
text in the module without a bound, and every other one reads `\d{4}`.

**The lookbehind is the part worth keeping.** A bare `\d{1,6}` would match the
*last* six digits of a 4,301 digit run and report a page count invented out of
the tail of an attack. Requiring that no digit precede the run makes an
over-long number no number at all.

**It changed one behaviour deliberately**, and a test had to move because of it:
an out of range page count used to fail `BookMatch`'s bound and cost the whole
row, and now costs only the page count. Keeping the record is the better answer,
since only one subfield was unusable, but it meant
`TestOneBadRecordCostsOneResult` no longer had a reachable bound at that site
and now poisons the year instead, which its own docstring already named as the
reachable one.

#### What was not done, and why the omission is deliberate

**The ÖNB is not read for author authority identifiers**, though it carries
them: 158 of 209 live `100 $a` fields carry a `$0`, 75.6%, and every `$0` on a
100 field is `(DE-588)` with no other authority file appearing. That is a better
rate than the DNB's. It is withheld because reusing the DNB's parser would
otherwise have admitted a second source to that path as a side effect of a
mapping, and the rule this follows is the one already stated for K10plus: a
catalogue is not read for a person's identifier until somebody has compared it
live, and comparing the numbers is not the same as comparing the people they
name. It is one argument to turn on and the measurement is recorded so that
doing so costs a comparison rather than a fresh probe.

**MARC 084 is not read.** ÖNB records carry it heavily, 188 `bkl`, 101 `rvk` and
88 `sdnb` values over 150 records, and none of those three schemes is in
`ClassificationScheme`. Adding a scheme is a decision rather than a mapping.

**No cover host was added.**

**The response cap slice was half built, not built**, and reporting it as
"already delivered" was wrong in a way worth recording. `fetch.py` does cap
every catalogue response on raw wire bytes, at every call site, and the ÖNB
inherited that by using the same door: that half needed no work. But the ticket
also asks for **one boundary fixture per XML SRU caller**, and the tree had two
of eight. Measured by raising each caller's own `limit` to 200,000,000 and
running the file: only the DNB and ÖNB lookups noticed. Worse, the test that
looked like the K10plus fixture was **vacuous**, its body being `<x>yyy</x>`,
which yields no records whether the cap holds or not, so `rows == []` passed
with the cap defeated.

Fixed here rather than left, because the ticket asks for it: eight fixtures, one
per caller, each carrying a body that **would parse to a record** if the cap let
it through, plus a test asserting that precondition so a typo in a fixture
cannot quietly restore the vacuous shape. Re-measured the same way, 8 of 8 now
fail when their own site's cap is defeated.

#### What adding a catalogue cost, which is the seam's own report card

**Two** parameters and about forty lines of adapter. The ÖNB's record profile is
the DNB's, so it goes through `_dnb_record` rather than getting a parser of its
own, and what had to change there was that the source is now an argument and
that reading `100 $0` is now a choice rather than a given. `Record` is frozen and nothing outside `catalogue.py` may replace a
field on one, so the source has to be known where the record is built rather
than corrected afterwards, which is the guard doing exactly what it was added
for. Adding a catalogue was a mapping, as intended.

VIAF's read API is half closed and easy to probe wrongly in two opposite
directions. **The variable is the `Accept` request header**, not the
`User-Agent`, which two separate probes of this concluded before a matrix was
run. Measured 2026-08-27 on
`GET viaf.org/viaf/search?query=...&httpAccept=application/json`:

| `Accept: application/json` | `User-Agent` | result |
|---|---|---|
| sent | anything, curl's default included | **200 `application/json`**, ten `VIAFCluster` records |
| absent | a custom agent, or a browser string | **307** to `/en/viaf/search?...` |
| absent | curl's default | **403**, 5,481 bytes of `text/html` |

`httpAccept=` in the query string is VIAF's **old** convention and the current
site ignores it, so following the 307 answers **200 `text/html`**, 93,813 bytes
of Next.js page: a probe that follows redirects and reads only the status code
concludes the API works, and one that sends no `Accept` header concludes it is
gone. `AutoSuggest` also answers 200 JSON with the header; the record endpoints
are gone whatever is sent.

It is still the wrong supplier, for a reason unrelated to availability. VIAF **aggregates** national authority
files and mints nothing, and the identifier this app already receives is a GND,
so going through an aggregator is the indirect route to a file that can be read
directly. lobid carries the VIAF cluster id in `sameAs` anyway.

Two suppliers rather than one, deliberately: lobid for the GND, Wikidata as the
cross check. The join is verifiable in both directions, which is the property
that makes the second request worth making. Where they disagree the disagreement
is surfaced and never resolved by precedence, because neither file is the
authority on the other.

Wikidata is read for identity and disambiguation only, which is
`docs/featurelist.md`'s refusal of author biographies and portraits held as a
structural rule rather than a remembered one: three fields in responses this app
already parses would cross it, and a test names all three.

**Not a decision about the feature. A decision about how this repository writes
guards**, and it earned a section because the same mistake was made four times
in four days by three different seats.

`author_identifiers.identifier` may not be retyped, and
`test_there_is_no_operation_that_retypes_an_identifier` is what enforces it.
That guard has been rewritten **four times and been substantially wrong every
time**, including the rewrite that was itself billed as the simplification:

1. a substring search, `".identifier =" not in source`. Four ordinary spellings
   walked past it: no space, augmented assignment, tuple target, `setattr`.
2. a hand walk over `Assign`, `AugAssign` and `AnnAssign`. Three more walked
   past: a bulk `update({...})`, an aliased `setattr`, `row.__dict__[...] = v`.
3. store context, which **is** structurally complete for assignment. But it kept
   a fourth arm matching the **text** of SQL strings, and that arm both
   false-positived on the module's own docstring ("updated" uppercases to
   contain "UPDATE") and missed every f-string, because an f-string is a
   `JoinedStr` and no single `Constant` in it carries both the verb and the
   column.
4. the payload matcher deleted, the call names widened. Two seats independently
   found the same arm.

**The transferable lesson: an arm that matches a payload is a defect, an arm
that matches structure is not.** Rounds 1 and 2 taught this guard to stop
matching payloads, and round 3 reintroduced it in the one arm nobody
re-derived. A raw SQL write's invariant is the **call**, not the string.

**The closed form, for whoever needs a fifth arm: do not add one.** The arms
enumerate an open set, so arm five is already implied by arm four. Every shape
either reviewing seat found names `AuthorIdentifier` or `author_identifiers`, so
**an allowlist of the functions permitted to name that model closes all of them
at once**, exactly as `TestTheShelfIsTheOnlyWayIn` does for `Book`. That turns
the guard from "no spelling I thought of" into "these functions are the whole
write surface", which is a claim a reader can check.

It was **not** done in this round on purpose: it is a fifth rewrite of a guard
that had just been rewritten, on a change already through three review rounds,
and the arms as they stand catch every shape either seat has found. The next
person to reach for arm six should build the allowlist instead.

The acknowledged survivor is a **subscript key assembled at runtime**, which
needs a line whose only purpose is to hide a write from a reader. It is stated
in the guard's own docstring rather than left to be discovered, because the
previous version claimed to catch "all the cheap spellings" and that was false
when written.

### The privacy rule covers the tables that belong only to a Book, and does not try to be clever about it

`TestTheShelfIsTheOnlyWayIn` asked three questions and all three named `Book`, so
a query over `classifications`, `custom_field_values` or `book_tags` was invisible
to every one of them. The shape to worry about is an **index**: "every DDC number
in the library, with a count" names no `Book` anywhere and publishes numbers from
books the viewer may not see. That is the `list_tags` disclosure again by a
different door.

**The fourth pass reports every read of those tables and decides nothing.** Which
statements are safe is a hand written allowlist of ten, each a source fragment and
a reason, with a test asserting the fragment appears in the statement at the line
it is matched to. Two of the ten are correct queries reported anyway, and a test
keeps them reported so the cost is not quietly removed.

**Deciding correctness was tried first and abandoned on evidence.** Five versions
of a rule that judged whether a join was safe, four of them shown to leak by the
next review round:

| Version | Rule | The shape that broke it |
|---|---|---|
| 1 | a join must be present | a shelf select with no join at all |
| 2 | the join must reach `Book` | an onclause naming `Book` and joining another table |
| 3 | the onclause must name the entity too | the wrong column, `Classification.id == Book.id` |
| 4 | it must name the entity's key column | `!=`, `>`, and an `or_` that is always true |
| 5 | it must equate the key outside a disjunction | not built |

Through all five, the hand written list of readers never changed. So the rule
that decided things is deleted: `_shelf_rooted`, the chain, join and onclause
analysis, and the write gate are gone, and `_book_owned_offences` judges nothing.
**Over reporting is the behaviour, not a defect.** A correct query on these tables
is reported and goes on the list with its reason.

**Two derivations, both pinned.** Which tables are children of `books` comes from
the foreign keys, and which of those carry a member of their own is asserted, so a
ninth child fails a test rather than defaulting to unguarded. The reading methods
come from `dir(Query) | dir(Select)` rather than a list, which caught a leak an
enumeration would have missed, since `select` is itself a method on `Select`. A
floor of 38 names is asserted against that set: a derivation that can grow
silently can shrink silently, and 21 real reading paths were droppable with the
suite green.

**What it cost, recorded because it is the argument for the shape.** Five leak
families over six review rounds, **none found by mutation testing**, whose score
was high throughout: three came from running the query against a database, two
from a reader asking what the rule required rather than what it said. Three of
the four fixes a reviewer proposed were themselves a step short of the family
they were for. `CLAUDE.md` carries the general lessons.

## Frontend

### Page-centric colocation

One page goes in that page's folder, several pages in `pages/components/`, general and
domain-free in `src/components/`. See [frontend.md](frontend.md).

### `useLibrary` has one door for filters, not a setter per field

Eleven one-line setters wrote one field each of a single `BookFilters`, so adding a filter
cost the interface, the hook and every caller a line, and no caller stopped knowing
anything: the test the deep modules rule sets, that a module is judged by what a
caller stops having to know rather than by its size.
`update(patch: Partial<BookFilters>)` replaces them, and `UseLibraryResult` went from 32
members to 21.

`toggleTag` and `clearTags` stay, because neither is a field write: a caller passing a
patch would have to compute the next tag list itself, at every call site.

**`setFilters` is gone rather than kept.** Its only caller applies a saved search, and a
saved search holds a complete `BookFilters`, so a patch naming every key is already a
replacement. The one case where the two differ is a search stored before a field existed,
and merging is the better answer there: the missing field keeps its current value instead
of becoming undefined.

Reading filters out of a URL moved out with them, into `lib/bookFilters.ts`, which is pure
and has no React in it, and so did turning a filter set into query parameters.

**Reading a URL, not the round trip.** Writing one is seven hand-written literals in six
files (`NavBar`, `AuthorCard`, `BookHeader` twice, `SeriesCard`, `CollectionCard`,
`SettingsPage`), none of them going through this module and none covered by the guard
below. Renaming a parameter in `readFilters` today breaks all seven silently and the suite
stays green. That half is unowned, deliberately not fixed here, and on the tracker.

**`readFilters` covers ten of the twelve fields.** `query` and `tagIds` are not reachable
from a link, which is a decision rather than an omission: a link naming a search box's
contents, or a set of tag ids that mean something different in every library, is not
something this app produces. Both halves are now asserted, `toParams` by a totality check
and `readFilters` by two tables that between them have to account for every field.

**A link and a request do not use the same vocabulary, and writing that guard is what
surfaced it.** `?collection=3` is this app's own route parameter; `collection_id=3` is the
listing endpoint's. `readFilters` reads the first and `toParams` writes the second. The first
version of the guard fed one into the other, assumed they agreed, and failed on `collection`
alone. The tables in `tests/lib/bookFilters.test.ts` now name the link parameter per field,
so the two vocabularies are written down instead of being discovered by a test that
happened to be wrong in the right place.

`BookFilters` and `DEFAULT_FILTERS` live here rather than in `pages/Home/types.ts`.
Keeping the shape on the page was tried and does not survive its own guard: the wire test
asserts that **every one of the twelve fields becomes a query parameter**, and its
client-only allowlist is empty. Nothing in the shape is view state, so it is not a view
model, and `lib/libraryView.ts` already holds `LibraryView` by the same logic. The page
re-exports both, so no consumer changed.

### The filter set is checked against the API's own schema

`BookFilters` exists on both sides of the wire, `backend/shelf.py` has its own, and
nothing checked that the two describe the same filters. Both failures are silent: a
filter the UI sends and the API ignores is a 200 and the whole library, and a filter the
API accepts and the UI cannot send is a feature nobody can reach.

`tests/lib/bookFilters.test.ts` reads the committed `openapi.json`, takes the query
parameters of `list_books`, and compares them against what `toParams` can produce, in
both directions. It is the frontend half of
`test_shelf.py::test_every_filter_field_narrows_something`, which asserts the same thing
about `matching()`.

Three parameters are allowed through with a reason each: `page` and `page_size`, which
belong to whoever is reading rather than to a filter set, and `unrated`, which the API
accepts and no control in this app offers. Verified by mutation rather than trusted:
renaming `q` to `search` and deleting `location` from `toParams` fails all three
assertions, naming `search`, then `q` and `location`, then `location`.

**The scan flow has the same guard, on two endpoints.**
`tests/pages/ScanPage/types.test.ts` checks `toScanRequest` against `BookCreate` and
`toCopyRequest` against `CopyCreate`, resolving each `$ref` out of the same committed
document rather than assuming it.

It found its own `unrated`: **`BookCreate` accepts `collection_id` and the scan flow never
sends it**, on either endpoint. There is no collection control on the confirm step, which is
a design decision rather than a plumbing gap, and it is recorded in the exemption table so
adding one is a decision somebody makes rather than a difference nobody sees.

**Two endpoints because there were two writers.** `addCopy` built its body from a literal,
so a new per-copy field reached the scan endpoint through `toScanRequest` and reached the
copy endpoint only if somebody remembered the literal. `CopyCreate` and `BookCreate` do not
accept the same fields (`condition`, the four purchase columns and `lending` are copy only),
so one function per endpoint is the only shape under which both can be checked at all.

**The document itself is now re-derived in CI.** It is committed and read as the authority
by both guards, so nothing stopped somebody editing that one file and making every
assertion pass while agreeing with nothing. `test:backend` regenerates it and diffs, in that
job because regenerating needs `uv`.

### Types are generated, not hand-written

`src/types.ts` used to mirror `backend/schemas.py` by hand, with nothing enforcing the
mirror. Orval now generates the DTOs from the OpenAPI schema, so a backend field rename is
a compile error rather than a runtime surprise. The generated output is committed so a
fresh clone needs no Python toolchain.

### No top-level `query` block in `orval.config.ts`

**The most dangerous configuration line in this project, by omission.** Setting one applies
to every operation including DELETE, which orval then generates as `useQuery`. A query runs
on mount and on retry, so `useDeleteBook(id)` would delete the book as soon as a component
rendered. Scope query options per operation.

### `includeHttpResponseReturnType: false`

Orval's built-in fetch client returns `{ data, status, headers }`; our mutator returns the
parsed body and throws on non-2xx. Leaving the envelope on would make every generated type
describe a shape the code never produces.

### `api/mutator.ts` throws on 401, except on the credential endpoints

It previously returned `undefined` after redirecting, so callers rendered with missing data.
Treating a 401 from `/auth/login` as an expired session also cleared the stored session and
replaced "Incorrect username or password" with "Your session has expired": wrong, and
nonsense for someone who was never signed in.

`/auth/switch` is on that list too, and is the sharpest of the three because its caller is
already signed in: an admin who mistypes a test account's password would be signed out of
their own session and sent to the login screen, having changed nothing. Measured on the
first run of the settings test, not predicted.

### The multipart path does not set `Content-Type`

The browser must set it itself to include the multipart boundary. Adding it by hand
produces a request the server cannot parse.

### Every request declares `Accept`, and a download declares something else

A browser `fetch` with no `Accept` sends a wildcard, and a forward-auth portal reads
exactly that header to decide whether an unauthenticated request gets an answer it can
handle or a redirect to a login page. Measured against the live deployment, same URL and
same expired cookie:

| Request `Accept` | Portal answer |
|---|---|
| `application/json` | 401 |
| `*/*` | 302 |
| absent | 401 |

The third row is the portal being consistent rather than a third case to design
for: a browser `fetch` never sends no `Accept`, it sends `*/*`, which is row two.
It is written down because the first measurement of it was taken with curl, which
sends `*/*` unless told otherwise, so the wildcard was measured twice and one of
the two was recorded as "absent". Re-measured with the header genuinely removed:
401.

`customFetch` therefore sends `application/json`, which is also simply true: every
operation in the schema declares a JSON response.

`downloadFile` sends `application/octet-stream, application/zip, text/csv,
application/json` instead. Its two callers fetch a CSV or JSON export and a ZIP backup, so
`application/json` would be a lie, and a wildcard would put the request back on the
redirecting side of the same negotiation.

### The endless spinner was two faults, and neither was wrong on its own

Reported by the owner, reproduced against the deployment: a page that reloaded for ever
behind a spinner. The mechanism needed both halves.

1. The request had no `Accept`, so an expired portal session arrived as a **302**, not a
   401. Under `redirect: "manual"` that is an opaque redirect, which `mutator.ts` handles
   by clearing the session and reloading, because only a top-level navigation is followed
   across origins.
2. The reload could not reach the portal. `workbox.globPatterns` included `html`, so
   `index.html` was in the precache, and `precacheAndRoute` applies a `directoryIndex`
   that defaults to `"index.html"`: a request for `/` was rewritten, matched, and answered
   from the cache with no network involved. The app booted looking signed in, made a
   request, was redirected, and reloaded again.

Both are fixed. The second is fixed by dropping `html` from the glob rather than by
setting `directoryIndex: null`, which removes the class instead of the instance: with no
HTML precached there is no cached shell for any route, rewritten or exact, to serve. The
cost is that there is no offline app, and there never usefully was one, because every
screen's content comes from an API behind the same portal.

**A client that already has the bug cannot be fixed by deploying this**, and the way out
follows from the mechanism above. Such a browser is served `/` from its old precache, so
it never makes a navigation the portal can answer, and `registration.update()` fetches
`/sw.js` with redirect mode `"error"` by specification, so the portal's 302 fails the
update: the old worker and the old bundle both stay. The escape is that only `/` and
`/index.html` are rewritten by `directoryIndex`. **Any other path** (`/settings`,
`/book/1`) misses the precache, reaches the network, and gets the portal, after which the
worker updates normally. That escape only became true with the SPA fallback below: until
then those paths reached the network and were answered **404** by the server, so the
reader got an error page rather than the portal.

The trap worth remembering is the previous fix. `navigateFallback: undefined` was added
for this exact bug and its comment described it as solved. It removed the NavigationRoute
and left the precache route, and the config kept saying "fixed" from v0.2.0 to v0.5.0
while the build kept shipping it. Hence `frontend/scripts/check-build.ts`, which
builds the app and reads `dist/sw.js`: the config was never the thing that was wrong.

### `isRedirect()` is `opaqueredirect` only

It also accepted `status === 0`, on the grounds that missing a redirect put the spinner
back. That was the wrong trade to make: a false positive here is not a wrong message, it
is `clearSession()` plus a page reload, which is the most destructive thing this client
does.

Under `redirect: "manual"` and the default request mode there is no other resolved
response with status 0. The spec gives an opaque-redirect filtered response
`type: "opaqueredirect"` and `status: 0` together, the only other zero-status response is
an opaque one, which needs `mode: "no-cors"` and nothing here sets it, and a transport
failure rejects rather than resolving, which is the `NetworkError` path.

### The reload is counted, and an uncountable one is not taken

`window.location.reload()` with no guard is a loop waiting for its next trigger, and this
one had one. `mutator.ts` records a timestamp in `sessionStorage` before reloading, and a
second edge sign-out within 30 seconds dispatches an event instead: the shell swaps in
`SessionEndedPage`, which says what happened and offers the same navigation as a button.
An infinite loop degrades to a sentence rather than to a spinner.

**The guard counts page loads, not calls, and the distinction is a bug that was in it.**
The library screen has six requests in flight (four in `useLibrary`, the `useListBooks`
inside `useUnconfirmedCount`, and the auth config; seven under proxy auth), so an expiry
resolves six opaque redirects in one batch. Counting calls, the first reloaded and the
other five read a marker aged about zero milliseconds, concluded they were looping, and
put up a screen saying reloading had not helped before the reload had happened at all. A module-level
`reloadRequested` closes it: the rest of a batch is the same event, and module state dies
with the document, which is the boundary wanted.

**What bounds the 30 second window**, since the next reader will be tempted to tune it:
it must exceed one loop cycle, which is a cache-served navigation plus a boot plus the
first request, so seconds; and it must fall short of a person signing in again at the
portal and coming back. Nothing in between distinguishes them. A slow portal makes the
window *safer* rather than riskier: no script of ours runs during the navigation, so a
slower round trip lengthens the measured interval and makes the loop branch less likely
to fire.

`sessionStorage`, not `localStorage`: this is one tab's own reload and should die with the
tab. Storage access is wrapped, because a private window or blocked site data can throw,
and failing to *record* the marker is treated as "do not reload" rather than as "reload
blindly", since a reload nothing can count is exactly the loop being guarded.

### The dead-end branch is the one place that must empty the query cache

Every other way a session ends leaves the document, and memory dies with it: `signOut`
clears the client itself, and `endSession` navigates to `/login`. The edge branch does
neither, so it is the only path that ends a session while the tab lives on. Without
`queryClient.clear()` in `useSessionEndedAtEdge` the client would go on holding every
book, loan, quote and setting the reader had fetched, behind a screen telling them their
session is over.

### `clearSession()` leaves the saved searches and the last location behind, and that is accepted

It removes `token` and `user`. A reader's saved searches and their last shelf position
(`lib/savedSearches.ts`, `lib/lastLocation.ts`) survive in `localStorage`, and `signOut()`
does not clear them either, so on a shared browser profile the next person to sign in
inherits both. What that discloses is what somebody searched for and one book id, never a
book's contents, and every read still goes through `visible_to()`.

Accepted rather than fixed, because it is per device by design: these exist so that a
browser remembers where you were, and clearing them on sign-out would also clear them for
the one person on their own laptop who is the common case. The cost is stated so the next
reader can weigh it rather than discover it. If it is ever fixed, both stores have to be
cleared in `clearSession()`, not in `signOut()`, or the edge path will keep them.

### `--color-paper-0` exists, and its value is `#ffffff`

A token whose value is plain white looks like a token for the sake of one. It is
not: it is the *card*, and a card is white only in this palette. Written as
`bg-white` at forty sites across nineteen files, every card, field and panel
asserts that the top surface is white, which stops being true the moment a
palette with a cream ground is offered. The value is a coincidence of the
default theme and the name is the fact.

`src/index.css` carries the same note beside the token.

### `bloom` and `danger` hold the same five hexes

Two ramps, identical values, and neither is redundant. One rose used to do both
"want to read" and "delete this", which works only because this particular rose
reads as both. It does not survive a palette change: map bloom to a candy pink
and Delete turns cheerful, or keep delete dark enough to alarm and the wishlist
badge becomes a warning.

They are equal here so that nothing changed on screen when they were split. The
split is what has to exist before a palette can move one without the other, and
deleting either ramp because it duplicates the other puts the problem straight
back.

Two call sites keep `bloom` deliberately: the "want to read" badge on a book
card, and the books-finished bar on the statistics page. Everything else that was
rose is `danger`.

### `TAG_PILL_CLASSES` is a four-key table with two values in it

Type, genre and age were a blue, a purple and a green, which was the one place in
this app where a colour was chosen at random. There is no mnemonic that makes
genre purple, so the hue had to be looked up, and the pill has the word written
on it. All four selected chips also failed AA, the green at 2.28:1.

The three now share one neutral and custom keeps the accent, because a tag the
library invented reading as theirs is a distinction with a reason behind it.
The table stays keyed by category rather than collapsing to a default and one
exception, so a category added to the backend enum is a compile error here
instead of an unstyled pill.

### The list row holds the grid card's face, plus two facts from its fold out

A third view is only worth having if it is not the other two, and a dense row
repeating the table's twenty one columns is a worse table. So the row is decided
against them rather than in isolation:

| Held | Why |
|---|---|
| cover, title, author, reading status | what a grid card's **face** carries |
| a loan marker, an unconfirmed ownership marker | also on the card's face, and the two answers to "why is it not on the shelf", which is the question this view exists for |
| series | the fact the card hides in its fold out that somebody scanning a list is looking for: it is what says the next one is missing |
| year | tells two printings apart, which is the other thing a person recognises a book by |

**Dropped from the card's face, deliberately**: the copies badge and the
discussion offer. Both describe a card rather than a book, and neither answers
"where is it".

This table used to say the row holds "exactly what a grid card's face carries",
which was false in both directions: the face carries four conditional things the
row did not, and two of the four were the point of the view. The two that
answer the question are now on the row.

Everything else stays in the table, which exists for reading metadata. The three
optional values are joined into one line rather than laid out in columns: a
column grid with three optional values leaves holes on most rows, and a row with
holes reads as missing data rather than as data a book does not have.

**The status is plain muted text, not the card's coloured pill.** One pill among
covers is a marker; thirty stacked is a colour field with no signal. Measured as
drawn, with the formula `tests/theme/palettes.test.ts` uses: `paper-600` on the
card's `paper-0` is **5.03:1** at worst across the seven palettes (rosepine and
everforest; 5.30 at best, on nord), and `paper-400` on `paper-900` in dark is
**6.00:1** at worst, against the pill's **3.97:1** as drawn. The replacement is
better on contrast as well as quieter, and the word carries the same
information.

The loan and unconfirmed markers keep their colour, and that is the exception
rather than an inconsistency: both are the minority of a shelf, so one of them
among thirty rows is a signal rather than a field. They are the same two colours
the grid uses for the same two facts.

**The whole row is one link**, where the table links only the title. The table's
reason is that a reader copying a publisher out of a cell should not navigate; a
list row holds nothing to copy, and one target per row is what makes it usable
on a phone.

### Every cover in the list loads lazily, and carries no accessible name

A 200 row page would fetch 200 images at once without `loading="lazy"`. It is on
every one, and a test asserts it rather than a comment claiming it.

**The reason is the page size, not the viewport**, and the first version of this
entry had that wrong. It claimed "roughly three times as many rows as the grid
fits cards", which holds on a phone and not on a desktop: computed from the
classes actually shipped, a row is `h-12` plus `py-2` plus a divider, about
**65px**, and a grid card at `minmax(170px,1fr)` is about **400px**. At a 1200px
content width and an 800px viewport that is 12 rows against 12 cards, i.e. **1x**;
at 390px it is about 3x. The grid's covers are lazy too (`BookCard.tsx`), so the
list is not doing something the grid does not: it is the same rule for the same
reason, which is that a page holds up to 200 books.

The `alt` is empty because the title sits beside the cover inside the same link,
and a duplicate label is noise in a screen reader's control list: the quotes
round found exactly this defect twice on the book page. An empty `alt` also takes
the image out of the accessibility tree, which is why the test queries the DOM
rather than the role.

### A selection forces the grid, and that is tested before the view is read

The checkbox lives on a card. Neither the table nor the list has one, so a
selection offered from either would be a selection that does nothing.

The condition used to read `view === "table" && !isSelecting`, which put the
selection second. It now tests the selection **first**, so a fourth view cannot
reintroduce the hole by forgetting to mention itself.

### The palettes are CSS, and the catalogue is TypeScript

`palettes.css` holds every hex; `palettes.ts` holds the list, the attributions and which
member was constructed. Splitting them looks like indirection and is the only arrangement
where the values exist once.

Tailwind generates `bg-paper-0` only because `--color-paper-0` is declared literally in
`@theme`, so the default palette has to be in CSS whatever else happens. Putting the other
six in TypeScript and applying them as inline custom properties would mean the same eleven
ramps in two places, with nothing able to compare them: the test suite runs with CSS
handling scoped to a raw read, so a TypeScript table could be asserted and the stylesheet
could not.

So the stylesheet is the authority and `tests/theme/palettes.test.ts` reads it as text,
resolves the cascade the way a browser does, and measures the result. A palette is then a
block of declarations and a catalogue row, and neither can drift from the other without a
test failing.

### Every palette block repeats tokens that look identical to the block above it

`:root.dark` in `index.css` and `:root[data-theme="x"]` in `palettes.css` are both
specificity (0,2,0), and the palettes are imported first, so in the dark Endpaper's
overrides beat a palette's light block. Only the palette's own dark block, at (0,3,0), beats
them back. A dark block that omits a token because it matches the light block above it
therefore gets **Endpaper's** value, silently, in that one mode. The completeness is
asserted rather than trusted.

### The wallpaper's opacity is solved from a weight, not written down

A layer used to be drawn at a fixed alpha per mode. That stopped being possible the moment
the ink started following the palette, because one alpha over seven inks is seven different
weights on the page. Measured at the shipped alphas, the mean tile weight ran **0.00984 to
0.01252 in light (1.27x) and 0.01435 to 0.01899 in dark (1.32x)**, against an agreed budget
band of 0.0070 to 0.0092, which is 1.31x wide. **The palette alone consumed the entire
budget**, and the dimmer inks landed up to 30% under target on the dark page (0.0427 against
0.061).

The choice was one alpha with a stated tolerance, or an alpha solved per palette. Solved,
and not from a table: `TARGETS` in `patterns.ts` states what one mark of each layer should
do to the page as an OKLab lightness delta, and `wallpaperWeights` bisects for the alpha
that gets there, against the page and ink read off the document's own tokens.

What that buys, measured across the seven shipped palettes:

| | one alpha | solved per palette |
|---|---|---|
| light, spread of the tile's weight | 1.27x | **1.052x** |
| dark | 1.32x | **1.030x** |
| light, in continuous colour | | 1.002x |
| alpha the dark ground needs | 0.075 everywhere | 0.078 to 0.109 |

The residual is not the palette. In continuous colour the seven agree to 1.002x, which is
the bisection's own precision; what is left is the compositor rounding the blend to 8 bits
per channel, and a table of hand-solved alphas would carry the same residual.

Three consequences worth knowing before touching any of it.

- **A table of 56 numbers was the alternative and is worse than it looks.** Seven palettes,
  two modes, four weights, and every one of them wrong the moment a palette moves a hex.
  Solving at runtime means an eighth palette needs nothing here at all.
- **The alpha ceiling had to move**, from 0.15 to 0.30. That number guarded "make it
  visible" from becoming a page that competes with a book cover, and it guarded it in the
  wrong unit: five of the seven palettes need more than 0.15 in dark to reach the weight
  Endpaper reaches at 0.13. The weight ceiling is `TARGETS` now, identical for every
  palette; the alpha ceiling is a guard against an ink so close to its own page that no
  reasonable alpha reaches it. The highest solve that ships is Solarized dark's bloom at
  0.2082.
- **The ink budget changed units with it.** `patterns.test.ts` budgets mean tile dL rather
  than mean alpha, and the two cannot be compared. Under the old unit the budget was a
  budget on the palette as much as on the pattern.

The OKLab in `src/theme/oklab.ts` composites in **gamma-encoded sRGB**, which is what the
compositor does and not the more principled of the two options. Blending in linear light
puts a teal mark on the light page at 0.0443 where sRGB puts it at 0.0715, so a solve done
the principled way would ship the light wallpaper at 1.61x the weight it asked for; on the
dark page the two disagree by 2.28x, in the other direction.

### A pattern is admitted by measurement, not by looking at it

Two designers rejected a woven girih on the same ground: fine interlaced strapwork
collapses into an even grey at wallpaper opacity, and the khatam was respecified coarser
because of it. That judgement is now `frontend/tests/theme/rasterise.ts` and two assertions,
both read off the generated tile rather than off the source.

**Tint contrast.** The tile's ink, blurred, as RMS contrast against its own mean. The floor
is 0.196, which is not chosen: it is what a field of parallel lines at exactly the 12px mark
pitch measures through the same filter. At 4px, the grey wash, the same field measures
0.018; at 30px, 1.140. The ten shipped patterns run 0.354 (Nonpareil) to 1.696 (Pimpernel).

**The floor is a measurement and not a formula**, which matters more than it sounds. The
blur is three passes of a width 7 box, a cascade with a standard deviation of 3.46px whose
response at a 12px period is 0.1515. It was documented as a true Gaussian of sigma 2.25,
chosen so that `exp(-2 pi^2 sigma^2 / p^2)` is 0.5 at 12px, which describes a filter 1.54x
narrower than the one that runs. Nothing was wrong with the floor, because the floor came
from putting a 12px grating through the real filter; but anyone moving the pitch floor by
re-deriving a sigma from that formula would get the wrong filter, so the numbers are stated
in `rasterise.ts` and the formula is not offered.

A single box was the first attempt and is unusable, instructively so. A box of width `w` has
a zero in its response at every period dividing `w`, so a 12px box annihilates a 12px
grating: measured, it puts the pattern the rule **admits** at **0.0035** and the 4px grating
the rule **refuses** at **0.0177**, five times higher. The ordering is inverted, and by the
filter rather than by the patterns. Widening the box to 13 does not fix it, it moves the
zero: 4px then reads 0.0788 and 12px 0.1349. A cascade has no zeros and the problem goes
away.

**Peak coverage.** The most inked pixel of a layer, which must reach 0.9. A pattern of
sub-pixel hairlines can have all the structure in the world and still be invisible, because
nowhere does it lay down a mark that reaches the weight its layer was solved for. That
failure is drawn too thin rather than too faint, and the fix for it is stroke width rather
than opacity.

**Nothing measures a seam in a rendered tile**, and the reasoning that used to sit here is
worth keeping as a record of how a defect got through it.

It said a shape crossing an edge is seamless for free from the nine offsets, which is true,
and then that a quantity laid out across the tile has exactly two ways of going wrong,
`lattice`'s pitch and `flow`'s cycle count, both guarded by a throw at module load. There is
a third, and it is the one that shipped broken: **the parity of a staggered lattice**.
Asanoha offset every other row by half a column across seven rows, so the last row and the
first were on the same phase and the honeycomb broke in a 60px band on every 420px tile,
14% of the page.

Two things that paragraph got wrong, beyond missing the third case. The pitch check was
named as the guard on seamlessness and is **vacuous for Asanoha**, which derives its extent
from its own pitch and so satisfies it by construction. And the deleted seam test was
presented as vindicated: it could not detect a deliberately broken Asanoha, which was read
as the measurement being hopeless rather than as that test being the wrong instrument.

What is true now. The stagger parity is a third throw in `lattice`, so all three run at
module load and a wrong constant fails every test in the file rather than one. The seam is
asserted as a **property of the layout** rather than looked for in a picture, at
`frontend/tests/theme/patterns.test.ts:344`, which walks the cells and requires the last
row's phase to differ from the first's. And the vacuity is itself a test, so nobody cites
the pitch check as a guarantee it does not give.

The general lesson, since it cost a shipped defect: an invariant belongs in the constructor
that can enforce it, and a constructor invariant is only worth what it constrains. Both
halves have to be checked.

### The plait was verified by rendering, and not on a real screen

The condition on shipping the plait was that its over and under survives at true opacity on
a real 2x display, because two designers independently predicted it would not. What was
actually done: the tile was rasterised at 1x at the solved opacity over the light page, and
the image inspected at two tiles square. The break at a crossing is 20px of interrupted
2.2px outline and it reads. The tint contrast is 0.477, which is 2.43x the floor and the
second lowest of the five decorated papers: only Nonpareil resolves less, and Nonpareil is
a field of parallel lines.

**That is a rendering, not a screen.** Nobody has looked at this in a browser on a 2x
display, and the difference is real: subpixel rendering, the browser's own antialiasing of a
scaled data URI, and a viewing distance are all outside what was measured. The objective
half of the condition is met and recorded above; the subjective half is not, and is the
first thing to check when this is next in front of somebody.

### No veins on the leaves

Veining the four large motifs was on the intricacy list and was built before being taken
out. A midrib costs about fifty bytes as a closed sliver inside the leaf's own outline,
knocked out by `fill-rule="evenodd"`. Measured on Pimpernel, it removes **4.4%** of the
foliage's ink and moves the tile's tint contrast by **0.35%**, from 1.696 to 1.690, against
an admission floor of 0.196. On Willow it moves it 2.0%.

It is real ink that changes nothing anybody can see at the scale it is drawn at, which is
the definition of detail that does not survive. The mechanism is left described in
`filled()` so the next person does not have to rediscover that evenodd is what a vein needs.

Three other items from the same list did not ship and are not deferrals either. **Tendrils**
would be Willow-only decoration and the budget has no room for them on the other four.
**More cubics per branch** is what arc-length placement was for, and the branches do not
need refining to prove it. **Piecewise stem width** via `ribbon` was measured against the
underfoliage plane and moves nothing the plane does not, while changing all five silhouettes
at once.

### The ink budget is measured analytically, and that is not free

`coverage` in `rasterise.ts` sums lengths and areas. It therefore counts ink laid twice on
one pixel twice, and counts no ink at all for the round cap on a stroke, and the two errors
run in opposite directions. Against the same tiles rasterised, weighted identically:

```
lily +17.7%   acanthus +10.1%   asanoha +6.5%   willow +3.3%
plait -1.1%   seigaiha -2.6%    nonpareil -12.7%
```

All ten sit inside 0.0070 to 0.0092 under either measure, so nothing is mis-admitted. What
is not measure independent is the **spread**: 1.122x analytically and **1.235x** from the
field, and the error runs systematically toward the dense foliage tiles. Wherever that
spread is quoted it is quoted with the measure.

Budgeting from the field instead is the better instrument and is deferred on purpose: it
moves every tile's number at once and is therefore a retune, not an edit.

### The underfoliage plane is on two patterns, not five

Willow measured 0.00485 mean tile dL against a floor of 0.0070: the only tile under the
band, by 31%, and under because it is the sparsest of the five rather than because it is
drawn faint. Adding ink to its foliage would have made it denser. A third plane behind the
foliage makes it deeper, which is the same number and a different tile.

It is on Willow and Strawberry and nowhere else because the band forbids the rest. Acanthus,
Pimpernel and Golden Lily are already inside it, so a plane there would mean taking the same
ink out of the foliage to pay for it, which is a different pattern rather than a deeper one.

### A dark hover state is stated at every call site, and the rule has no exemptions

Every ramp runs the other way in the dark, so `text-accent-700 hover:text-accent-800`
written once is legible at rest and illegible while pointed at: measured across the seven
palettes those pairings land between **1.36 and 2.85** on a dark card, because `accent-800`
in a dark ramp is nearly the card itself.

Twelve sites were like that and all twelve were repaired, which is why
`frontend/tests/houseRules.test.ts` states the rule with **no allowlist**. That is a claim
rather than an omission. The alternative shape was available, and this repository does ship
it where a rule arrives before its repair (`api/mutator.ts` in the session rule,
`.field:disabled` in the paper rule), but a frozen list of twelve is a list of twelve things
nobody comes back to.

The rule covers `hover:text-` and not `hover:bg-` or `hover:border-`. A surface a shade off
in the dark looks slightly wrong; text a shade off is text nobody can read, and WCAG 1.4.3
has a number for the second and not the first.

### The theming series is one changelog entry, under v0.4.0

Four phases landed separately (the token repair, seven palettes, ten wallpapers, the
picker) and only the last of them is a thing a reader can do anything with, so the entry
was written once, when the picker shipped.

**v0.3.0 was never tagged.** Its section stays as written, because its contents are in
`main` and the section is a true record of them; the next tag is v0.4.0 and carries both.
A version in the changelog with no tag beside it is a fact about git, not a hole in the
record, and folding the bug fixes into the theming release would have lost which was which.

### `warn`, `ok` and `loan` stay raw Tailwind, for now, minus one repair

They are amber, green and orange at 29 lines across 16 files, so six of the seven palettes
ship a success message and an overdue badge in colours belonging to none of them. Tokenising
them is three ramps times seven palettes times two modes, which is a phase of its own and
not this one.

**One repair landed anyway, because it was a live AA failure and needed no token.**
`text-green-600` on the card measured **2.79 (Nord) to 3.22 (Endpaper)** for text that needs
4.5, and it is the success message on four screens. It is now `text-green-800`, measured
**6.19 to 7.13**. `green-700` was the obvious step and does not clear: 4.29 on Nord, 4.37 on
Catppuccin, 4.49 on Gruvbox.

That measurement is also the argument for the token job. A raw hue is a bet on seven
different card colours at once, and the only green that wins it is two steps darker than the
one anybody would reach for.

### `:root:root` in the `prefers-contrast` block

Doubled deliberately, and not a typo. The rule has to outrank `:root[data-theme="x"]`, which
is (0,2,0); written once, at (0,1,0), the preference would be honoured on the default
palette and silently ignored on the other six. The dark half is `:root:root.dark` for the
same reason.

### Appearance is three columns on `users`, and is not on `UserOut`

The columns rather than a `user_preferences` table: a one-to-one with no history, where a
side table buys a join on every read and a row that both shadow-account paths would have to
remember to create.

Not on `UserOut` because that schema is served inside every book payload and the member
list, so a field there would tell everyone in the library what everyone else's library
looks like. `/api/users/me/appearance` takes no member id, so there is no object to
authorize and no way to ask for somebody else's.

### The wallpaper picker is a route, and the wallpaper is not a switch

`/settings/appearance/theme`, its own route and a child of the Appearance settings
screen, rather than a section of that screen and rather than a dialog. The reason is
the one the design turns on: the only honest preview of a wallpaper is the page. The
pattern is painted on `body`, so the picker is the app surface with the controls laid over
it, a choice shows itself the moment it is made, and there is no Save button because there
is nothing to defer. A dialog would have covered the thing being previewed.

The preview is the reader's **own first two book cards**, taken from the query cache and
never fetched. Invented sample content is not the real page, and a request made to fill a
preview would put a book on screen that the reader did not ask for. Where the cache holds
nothing, the picker says so rather than drawing a placeholder book.

**Off is a value in `wallpaper`, not a flag beside it.** The field already answered two
questions (which pattern, or a different one every visit) and a boolean next to it would let
the two disagree: off with a pattern named, or on with none. `WALLPAPER_OFF` is the third
answer, and `patternFor` is the one place that reads it. It is the only id that does not
degrade to a random pattern, because an off that came back as a wallpaper would be a choice
the app declined to keep.

Two off states, and they are not the same thing. A chosen off is `pattern === null`; the
system asking for more contrast is `wallpaperOff`. Both clear the body, only one is worth
explaining, and the picker says which happened. The choice stays recorded and stays marked
underneath the explanation, because it is what comes back when the system stops asking.

### The swatches read the stylesheet rather than restating it

A palette tile draws page, card, ink and the two accents in that palette's own values, and
none of them is a hex in TypeScript. `readPaletteColours` puts each palette on the document
in turn and reads the computed custom properties back, which is what `wallpaperColours`
already does for the wallpaper's ink and for the same reason: thirty five values restated
would be the same eleven ramps written twice, and a tile that disagrees with the palette it
applies is a preview that lies.

The read is wrapped in `withPalette`, which restores the attribute in a `finally`. It runs
from a **layout** effect, so the intermediate states never reach a paint. A passive effect
would paint them.

**`ThemeProvider` applies from a layout effect too**, and that changed when the picker
shipped. It was a passive effect, which was invisible while the only appearance change was
the one `main.tsx` had already painted before React mounted. From a picker, where a choice
is made with the page open, a passive effect shows one frame of the previous look. The
component that applies cannot offer a weaker guarantee than the components that read.

`withPalette` is also what keeps the wallpaper tiles honest, for a different reason: a
child's effect runs before its parent's, so a component that read the tokens after asking
for a palette change would read the previous palette every time and show a grid one choice
behind.

**The wallpaper swatches are drawn at true opacity, and are large instead.** A swatch at
three times the page's opacity is a lie about what is being chosen, and somebody picks
khatam and finds nothing there. `background-size: contain` with four columns inside
`max-w-6xl`, less the page's padding and the section's, is a 257px cell, against tiles that
repeat at 240px to 300px, so nine of the ten are drawn at 86% to 107% of the size they have
on the page. Asanoha, at 420px, is the one that shrinks, to 61%.

### The front door does not shuffle

A device with nobody on it paints Endpaper, the system's mode and **Willow Bough, fixed**.
`readCachedAppearance` returns that when no account is named and the cache is empty, and the
new-account default, which is Surprise me, when one is. Asking for an account is what tells
the two apart, so no caller has to know which is which.

`LoginPage.tsx` calls itself "the first screen anyone sees, so it is the one that decides
whether the app looks made or assembled", and a door that is a different pattern every visit
reads as a slot machine. Randomness is a pleasure once you are inside. An admin-set login
image, where there is one, covers it anyway.

### The appearance cache is keyed by account, and the login screen shows the last one

The server is the authority; `localStorage` is a write-through cache, read before React
mounts. Keyed by account because a library shares devices. The `last` pointer is what the
login screen paints with, which does disclose to anyone holding the device that somebody
here uses Gruvbox. That is a decision rather than an oversight: the alternative is a front
door that looks like a different app every visit.

An inline blocking `<script>` would remove the reconciliation entirely and is not available:
`middleware.py` sets `script-src 'self'` with no nonce, so it would need a per-build hash
and the security middleware would have to be generated from the frontend bundle.

### `useSession` clears the query cache on a change of account id, not per call site

The client outlives an identity change, the cached listings are member-scoped by
`visible_to()`, so they carry private books, and none of the ways the identity changes
reloads the page. See [security.md](security.md).

This used to be a `queryClient.clear()` in `signIn` and another in `signOut`, which was
two of the four ways it changes. "Switch account" is a router link rather than a
navigation; switching into a test account is a button in Settings; and under proxy auth
the identity can change **with nothing happening in this app at all**, which is the case
no call site could ever have covered. So the clear is an effect keyed on `user?.id`, and a
path added later gets it without knowing it exists.

Two details that are not caution and cannot be simplified away:

- **Only a change between two known accounts.** `null` is both "nobody" and "not known
  yet", and the identity is itself two cached queries, so clearing produces a null.
  Treating that as a change clears again, which produces another null: an app that
  refetches for as long as it is open. Reproduced by the proxy test with a stale
  `localStorage` entry.
- **`signOut` still clears for itself**, because it is the one known-account-becomes-nobody
  that matters and it is deliberate, so it can say so where the effect cannot tell.

`tests/houseRules.test.ts` no longer counts clears against session writes. That question
was the right one while three call sites each had to remember; against one effect it asks
for a redundant call per writer. It now asserts that nothing outside `pages/hooks.ts` and
`api/mutator.ts` writes the session at all, which is what keeps every identity change in
front of the effect watching it.

### Under proxy auth a token beats the header, but only a switch token

`AUTH_MODE=proxy` used to ignore tokens entirely. It cannot any more: an admin switching
into a test account needs a session that wins over the header until it is discarded.

Accepting any valid token there would also revive tokens minted before a deployment moved
to proxy auth, and those name real members. So `auth._switch_session` accepts one only
when the account it names is still a switch target, which is narrow by construction rather
than by a claim somebody has to remember to set, and narrows further the moment the flag
comes off the row. An expired or forged token falls back to the header rather than
failing: the header is the identity the deployment already authenticated, and failing
closed would strand whoever holds a stale token behind an error page with no control on
screen to clear it.

The cover cookie follows the same rule on the cover route alone, because an `<img>` sends
no Authorization header and a switched session would otherwise show the test account's
library with a hole where every cover only it can see should be.

### Tailwind 4 has no config file

`tailwind.config.js` and `postcss.config.js` are gone; configuration is `@theme` in
`src/index.css` and `@tailwindcss/vite` runs the pipeline.

### `/login` is routable while signed in

So "Switch Account" can show the form without destroying the current session first.

### The scanner filters barcodes before reporting

Only Bookland EAN-13 and 10-digit ISBNs, or any barcode in view triggers a lookup.

### No i18n library

Two languages and a flat key set. The whole mechanism is an object lookup plus placeholder
substitution; a library would add a dependency, a bundle and a plural-rules engine nothing
here needs. The one property worth having is kept by the type system instead: `de.ts` is
typed as `Messages`, so a missing translation is a compile error.

### No dashes as punctuation, anywhere

Not in UI strings, docs or comments. Em and en dashes do not survive translation cleanly,
they are awkward on the phone keyboards this app is mostly used from, and German typography
uses them differently. Use a colon, a comma, parentheses or a full stop. A test asserts it
for the message catalogues, because a dash is easy to paste in and invisible when skimming.

Related: translate **whole phrases, never fragments**. `"Loaned to {to} by {by}"` is one key
rather than three concatenated pieces, because German does not keep that word order.

### The Google Books search is submitted, not debounced

The library search box debounces; this one does not. Each search is a billed call against
somebody's Google Books quota, and typing "the hobbit" would spend ten of them to answer one
question. Different cost, different interaction.

### `mutate`, not `mutateAsync`, for fire-and-forget writes

`mutateAsync` rejects on failure, so `void save(...)` leaves an unhandled promise rejection
in the console on every failed request. The error is already in the mutation's state, which
is what the UI renders. Found by a vitest unhandled-error report on an otherwise passing
test.

### A selected card is a checkbox, not a disabled link

In selection mode `BookCard` renders as `role="checkbox"` rather than as a `Link` with its
navigation suppressed. At that moment it genuinely is a checkbox, and announcing it as a
link that goes nowhere is worse than useless to anyone using a screen reader.

### The login tabs have `aria-label`s that differ from their text

The tab and the submit button below it show the same words ("Sign In"). Without distinct
accessible names a screen reader announces two identical buttons and neither says which one
switches the form. The labels say "Switch to sign in" / "Switch to registration".

### Debounce tests use `fireEvent`, not `user-event`

`user-event` deadlocks against fake timers. See [testing.md](testing.md).

### The book detail page is six collapsible groups under an identity block

Seventeen panels in one column, three of them free text forms. Nothing caused it and
every feature added one panel, which is how a page becomes a form. The groups are
`reading`, `filing`, `copies`, `lending`, `writing` and `about`, and they collapse.

Collapse rather than tabs: a tab hides that content exists at all, while a collapsed
section keeps a labelled handle visible, which is the whole point for a panel that is
empty on most books. What stays outside every group is chosen as deliberately as what
goes in: the cover, title and author; the loan badge, which is the one thing a member
scans a shelf for; the privacy control, because a control over who can see a book must
not be somewhere you go looking for; the delete button, because a destructive action
hidden in a fold is a worse surprise than a long page; and `EnrichPanel`, for the reason
below.

`DiscussToggle` sits in `reading` rather than in `lending`, against the grouping first
proposed. Its own docstring is the argument: it is a fact about a reader, not about
where the object is.

**The four handles that can name an errand do; the two that hold content name the
content.** "Your reading", "Filing this copy", "Your copies" and "Lending this copy" say
what you came to do. "Notes and quotes" and "About this book" do not, and the exception is
written down rather than left for a reader to notice: both are read for what is in them,
and no verb describes either better than its nouns do. An earlier draft called the second
one "Organisation", which is a label over a drawer rather than something a person arrives
wanting to do, and the third "Copies and condition", which is two errands joined by "and"
and stopped being two the moment `CopyPanel` lost its own disclosure. No title may repeat
a heading or control inside its own section, which is why this is not "On the shelf" (an
ownership button) or "Lending" (the willingness label): a test counts each name and
requires exactly one button.

**`about` is the one group that is not always drawn.** The other five keep their handle
on a book that has nothing in them, because an empty group still offers its act: lending
a book nobody has borrowed is the reason the lending section exists. `about` offers no
act at all, so with no blurb and no categories its handle would open onto nothing and it
is left out.

**`EnrichPanel` is outside every section**, at the foot with the two dialogues it raises.
It was briefly inside `about`, which is exactly wrong: `about` is drawn only when the
catalogue already knows something, so the button that fetches what the catalogue knows
would have been hidden on precisely the books that need it. That is the same fault as the
bug its own comment records, reached by a different route.

**Five panel headings dropped from `h2` to `h3`.** `ReadingPanel`, `ProgressPanel`,
`OwnershipPicker`, `ShelfPanel` (twice) and `CollectionPicker`. Flat `h2`s were correct
on a flat page; inserting a section heading above them is what made them wrong, and a
heading list that shows twelve `h2`s in a row shows no grouping at all. This is the one
place the "no panel changes" scope rule bent, and it bent because that rule exists to
keep a diff reviewable, not to preserve a heading level whose meaning the change removed.
Each site carries a comment saying why, or the next reader repairs it back.

Six panels label themselves with a bold `<p>` rather than a heading at all
(`StatusPicker`, `TagEditor`, `LoanPanel`, `NoteList`, `QuoteList`, `CopiesPanel`), so
they appear in no outline either way. That predates this change and is left alone here:
promoting them is a separate pass with its own reasons, and doing it in this diff would
have hidden the six demotions among a dozen edits. `CopyPanel` was the seventh and is not
left alone, for the reason below: its label is the one this change itself demoted, from a
`<summary>`.

**`CopyPanel` lost its own `<details>`.** It opened itself on a copy with a condition or
a price recorded. Nested inside the `copies` section that signal was swallowed (on a
single copy book the section arrives closed) and the fields sat two clicks deep. One
disclosure idiom per page.

Its label became an `h3` rather than the bold `<p>` six other panels use, and that is not
cosmetic: it was a `<summary>`, which is focusable and announced, and a `<p>` is announced
as nothing. Dropping the wrapper without this would have traded a redundant disclosure for
a lost landmark and left "Your copies" the one section with no heading inside it.

### A section's stored state is three values, and absence is one of them

Which sections open is conditional on the book (`sectionDefaults` in
`pages/BookDetail/hooks.ts`), so "closed" and "nobody has said" cannot be the same
stored value. If they were, closing the loan section on a borrowed book would last until
the next visit, when the condition would win again and open it. Absence therefore means
"use the book", and `resolveOpen()` in `lib/sectionState.ts` is the only place that rule
lives.

The defaults are frozen per book, not once. Left live, marking a loan returned would flip
the lending default to closed and fold the section away under the hand that had just used
it. Keyed on the book id rather than on the ref being empty, because `routes.tsx` renders
`/book/:id` with no `key` and the copies section links straight to a sibling copy: a
freeze that armed once would hand the second book the first one's loan, copy count and
blurb, and it is one click away from the section this change added.

### Section state is per device and per section

`localStorage`, like `libraryView` and the saved searches, and for the same reasons: a
habit rather than library data, no endpoint, no schema, no migration, and the cost of
getting it wrong is one tap. Per member would be a settings round trip and a backend
change for a preference that differs between a phone and a laptop anyway.

Per section rather than one state for the page, because a single flag could only ever
mean "collapse everything", which throws the conditional defaults away. One entry per
section id, and an id no section answers to any more is kept rather than pruned: nothing
renders it, and a section that comes back finds what the reader last said. Only a value
that is neither `open` nor `closed` is dropped. Every read and write is wrapped, and a
page with no stored value at all is the conditional default, which is the state the whole
design is written for.

**The consequence of those two decisions together, and it is load bearing: an entry is
per section and not per book, so the first tap on a section ends its book-conditional
default for every book on that device, permanently.** Somebody who folds the loan section
away on one borrowed book will not see it open itself on the next one. That is the
intended reading of "a reader's own choice wins", the alternative being a page that
re-opens what they closed, but it does mean the conditional defaults are a first-visit
behaviour rather than a permanent one. Clearing site data is the only way back.

### `writing` is fixed closed because the data to decide it is not on the page

`BookOut` carries `active_loan` and `copy_count`, so lending and copies decide their own
default from the book the page already has. It carries no note or quote count: those
arrive from `/notes` and `/quotes`, which are separate requests, so a conditional default
there could only open the section after they landed. That is a flicker, and a fixed
default is better than one. Closed is also the honest guess, because notes and quotes are
empty on most books in a library catalogue. Put a count on `BookOut` and this becomes
conditional like the rest.

`about` is fixed too, open, for the opposite reason: it is drawn only when it has a blurb
or a category, so by the time the default is asked for, the answer cannot be no. It still
collapses, because a blurb is long and somebody who never reads them should be able to
fold it away once and for good.

### A collapsed section is hidden, not unmounted

`aria-controls` has to point at an element that exists, or the relationship it names is a
dangling id. Unmounting would also throw away whatever is half typed inside the section,
so collapsing by accident would lose a note. The `hidden` attribute keeps the panel out of
the accessibility tree and out of the tab order, which is the part that matters, and the
page holds no more DOM than the flat column it replaced.

### The settings page folds against a fixed table, not a condition

The book page keys each section's default on the book in front of the reader. Settings has
no equivalent fact to test, so `SETTINGS_SECTION_DEFAULTS` is a table, and the rule behind
it is what a card is for: **open when the current setting is the whole of the card and
reading it is why you are here, closed when it starts a job or holds a form.** Language,
appearance, the Goodreads toggle, the default language and About are the first kind;
import, the cover backfill, the overdue webhook form, test accounts and backup are the
second, and a deliberate arrival is what a fold costs least.

**`googleBooks` is an exception and is stated as one.** By the rule it belongs with the
second group: it holds a toggle, an API key field with show, save and clear, and three
hint paragraphs, the same shape as the overdue form and the tallest open card on the page
at roughly 309px. It is open anyway, because the toggle is the setting and the key is its
configuration, and because closing it would put five closed handles in a row through the
middle of the page. A rule with a silent exception is what this repository keeps getting
bitten by, so the exception is named in `SETTINGS_SECTION_DEFAULTS` too.

Six of eleven arrive open **for an admin**. The plan this shipped from proposed the
opposite default, folding everything except appearance and the feature toggles. It was
overruled for one measured reason: a member who is not an admin is shown five of these
cards, three of them open, so folding the language switch would leave that reader four
closed handles and nothing to read.

The ids are named after what a card is, not after its title: `appearance`, not
`theme.label`; `overdue`, not `reminders`. The id is what reaches storage, so a renamed
title is free and a renamed id forgets what every reader said.

**Retired 2026-08-27, when Settings became six routes.** The fold was doing a
route's job: the page held thirteen sections, and two features built on one night
had to be told in advance which section each owned to avoid colliding in
`SettingsPage.tsx` and `hooks.ts`. `SETTINGS_SECTION_DEFAULTS`, `SETTINGS_SECTIONS`
and `useSettingsSections` are gone. Keeping the collapse state beside the
navigation would have given a household two ways to hide the same thing. The rule
survives for the book page, which folds against a condition and has no route to
fold into.

### The section store is a parameter, because two pages have an `about`

`readSectionChoices` and `writeSectionChoice` take a `SectionStore`. One shared
`localStorage` key would have made closing a book's blurb close the app's own About card,
with nothing wrong on either page. `SectionStore` is a union of the two key names rather
than a `string`, so a third folding page has to name its store and a typo is a compile
error.

### Folding settings kept the card, and removing the fold removed the variant

`SettingsSection`'s whole reason for being shared is that `/settings/appearance` must not
look like a different app from the page that links to it. Folding by adopting the book
page's row chrome would have broken exactly that, so the disclosure grew a `card` variant
instead: same surface, same icon badge, one behaviour. The badge is its own component,
`components/SectionIcon.tsx`, so the two headings cannot drift apart. `SettingsSection`
stays for the appearance screen, which does not fold because it is arrived at
deliberately.

One thing the fold broke and the fix is worth keeping: the panel is a `role="group"`
labelled by its handle, so the two language pickers' own `role="group"` wrappers became a
second element with the same accessible name and `getByRole` found two. The wrappers went.

### Funding is one link, in the README and in an About card

Ko-fi only, at `ko-fi.com/fklement`. Patreon was dropped: a second platform is a
second thing to maintain, for an audience that has not asked for it.

**It was nowhere in the app until 2026-08-23, when the owner decided otherwise.** What
replaced the old rule is narrower rather than looser: one sentence and one button, in an
About card at the foot of Settings, and nothing anywhere else. No banner, no menu entry,
no dismissible card, no mention on any screen somebody passes through while cataloguing.

**Nowhere is it a pitch, and that is the whole of the wording rule.** Earlier drafts
argued the case at length and read as one; that argument was cut from all three places on
the same day.

**All three places carry the same two facts: what the money pays for, and that nothing is
gated.** The card did not, until 2026-08-24. It asked in one sentence and explained
nothing, on the reasoning that its reader is already inside the app and needs no selling
to.

**That reasoning was wrong, and it is worth saying why, because it reads as sound.** It
treated the sentences as *justification*, which a reader inside the app does not need. They
are not. A donate button provokes two questions wherever it appears, and the second one
matters more to somebody who already installed this than to a stranger:

* **What does this pay for?** The relay, and only the relay.
* **What am I missing by not paying?** Nothing. Every feature is free either way.

Leaving those unanswered did not make the card quieter, it made it vaguer, and a vague ask
is the one that reads as a pitch. The second question is the sharper of the two here: a
donate button inside software somebody already runs invites the suspicion that this is the
free tier, and one short sentence retires it.

**The English is the source and the German is not a gloss of it.** "All features are free
either way" became "Alle Funktionen sind so oder so kostenlos", chosen over the tighter
`ohnehin` because the two sentences before it are informal (`dir`, `du`, `spendier mir`)
and `so oder so` matches that register. `Er hilft, den Server zu finanzieren` keeps the
English's small joke, where `er` is the coffee rather than the donation, and `finanzieren`
rather than `bezahlen` because paying for a server is ongoing rather than one invoice.

**The card's size is what does the work, and the defaults only help an admin.** About is
open unless explicitly closed. An admin has five other open cards beside it and About is
the eleventh of eleven, roughly 1,400px down a long page: the count defends it there. A
member who is not an admin sees five cards, three of them open, and every extra open card
an admin counts (Google Books, Goodreads, the default language) is admin only. **On that
page nothing except About's own height can keep it from dominating**, which is why the
card is two short lines and a button rather than a paragraph: the version and the source
link on one line, one sentence asking, the button.

**Measured, because "shorter" is not a number.** Computed from the class list at
`max-w-2xl` with Tailwind's default type scale rather than in a browser, and the same
model reproduces the design seat's figure for the first draft (286px against their 284px),
which is what makes the rest of these comparable.

| Member page (five cards, three open) | About | painted card | share |
|---|---|---|---|
| First draft, with a sentence describing the app | 286px | 788px | 36% |
| That sentence cut | 246px | 748px | 33% |
| Version and source on one line | 210px | 712px | 29.5% |
| **Shipped: that line replaced by a badge row, 2026-08-24** | **210px** | **712px** | **29.5%** |

About is still the tallest card there by 40px, against 170px for language and 160px for
appearance, and that is where it stops. It is last on the page and one card among five,
and the remaining 40px cannot be bought with words: the only lever left was tightening
this card's `space-y-4` into a block for 24px, and **that was refused**, because it would
give one card a rhythm no other card has, immediately after the same change gave the page
a consistent one. The German support sentence wraps to two lines at this width, which is
20px more (230px); that is a fact about German rather than a design failure.

The six expanded handles are still asserted, because a later change that folded everything
else away would leave About alone on an admin's page:
`SettingsPage.test.tsx::leaves About one open card among six, not the page's only one`
counts them, and `SettingsPage/hooks.test.ts::leaves a member who is not an admin
something to read` pins the member's three. What changed is which of the two is load
bearing.

**The button is served from this deployment** (`frontend/public/kofi-button.png`), not
from `storage.ko-fi.com`. The CSP's `img-src` is derived from `covers.COVER_HOSTS`, so a
hotlinked button would mean widening the policy for a decoration, and it would report the
address of a private server to Ko-fi every time somebody opened Settings.
`rel="noopener noreferrer"` keeps the same true of following the link.

**The artwork is Ko-fi's trademark, not this project's.** It is their published button
image, vendored unchanged and used as their button guidance intends, and it is not covered
by this repository's Apache-2.0 licence: the licence grants nothing over somebody else's
mark, and a fork that wants a different funding link should replace the file rather than
assume it came with the code. The same reasoning `theming.md` applies to the Morris and Co
pattern names: a trademark question rather than a copyright one.

The card also names the version and links the source, which is the half of it that is not
about money at all: a version number is what somebody quotes in a bug report, and the
source link is what an Apache-2.0 reader goes looking for. Since 2026-08-24 both are
badges rather than a sentence, and the section below is why the row cost the figures above
nothing.

### The version is derived, not declared

The card first read its version from `package.json`. That is one file to remember before
every tag, plus `backend/pyproject.toml`, and a mobile manifest once the React Native
client exists. On 2026-08-23 both were still on 0.5.0 while v0.6.0 was being cut, which is
what a number maintained by memory does.

A guard was written first: fail the release when the declared versions disagree with the
tag. It was thrown away the same day, because it does not remove the chore, it only
converts a forgotten edit into a failed pipeline and a re-tag. Making the release *more*
ceremonial is the wrong direction.

`vite.config.ts` now substitutes `__APP_VERSION__`: `CI_COMMIT_TAG` minus the `v` on a
release, `git describe --tags --always --dirty` otherwise. So a development build reads
`0.6.0-14-gbbdf755` and cannot be mistaken for a release, and nothing is edited before a
tag. The remaining `version` fields in `package.json` and `pyproject.toml` are package
metadata that no screen reads; neither is published to a registry that consumes them.

**The frontend is built inside a Docker stage with no `.git` and no CI variables**, so the
tag cannot be discovered there and is handed in as `--build-arg APP_VERSION`
(`Dockerfile`, and the release build stage of the pipeline). Without that the release image would
show `unknown`, which is exactly why the fallback is that word rather than a number
that looks real. It is one token deliberately: a version never contains a space, so a
test can assert the shape of one.

A sentence describing what the app is was written and cut. Somebody reading this card is
already inside the app.

The money is for one thing, running the shared relay, and the two facts that survive the
trim are the two a reader needs: what it pays for, and that no capability sits behind it.
Every feature stays available to somebody who runs their own relay, and if that ever stops
being true it is a different project. Publishing what the relay costs and what came in was
promised in an earlier draft of these texts and is promised in none of them now; it is
unshipped work, waiting on a relay to have a cost.

### The About card's badges are drawn, never fetched

`README.md` opens with a row of shields.io badges. The same row exists in the app, at the
top of the About card, and **none of it is an image**.

**The constraint is the CSP and it is not negotiable here.** `img-src` is derived from
`covers.COVER_HOSTS` (`backend/covers.py`), and this card already refused to widen it once,
for the Ko-fi button, which is served from `/kofi-button.png` for exactly that reason. A
badge is decoration, so it is the weakest possible case for a policy entry, and a remote
one would report a private server to a third party every time somebody opened
Settings.

Drawn as markup and CSS instead, which is better here for three reasons that have nothing
to do with the policy: the row themes with whichever of the seven palettes is in force, it
renders in the installed PWA with no network at all, and it adds no request to a page load.
Written down because an `<img src="https://img.shields.io/...">` is what the next person
reaches for, and it would look like a simplification.

**Four badges, and the rule is that a badge states something knowable without a call:**

| Badge | Value | Where it comes from |
|---|---|---|
| Version | `__APP_VERSION__` | substituted by `vite.config.ts`, see below |
| Licence | Apache 2.0 | static, links the LICENSE file on GitHub |
| Source | GitHub | static, links the repository |

**Three, where the README has five, and languages is the one that was cut.** Two reasons
converge on it. The Language card is the first card on this same page and arrives open,
offering those two languages as buttons, so the badge answers "what does this project
support" for a stranger evaluating the README rather than for a member one card below the
switch: exactly the argument that cut the sentence describing the app. And "DE, EN" was a
fourth hardcoded copy of the locale list, after `CATALOGUES` in `i18n/index.tsx` (the
exhaustive one, where adding a `Locale` is a compile error), `LANGUAGES` in
`SettingsPage.tsx`, and the catalogues themselves. A third locale would have left the badge
reading "DE, EN" with nothing failing.

**The two values that are names are not catalogue entries.** "Apache 2.0" and "GitHub" are
constants in the component. A message key whose value is byte identical in every language
is a translation nobody can make, and three of the seven keys the first draft added were
that. The labels stay translated: "Licence" is "Lizenz" and "Source" is "Quelltext".

**Docker pulls and a latest release badge are deliberately absent.** Both need a request to
a host the CSP does not carry, and the alternative, a number typed into the source, is
wrong within a week and says nothing about being wrong. The README keeps them because
shields.io fetches them at render time; the app cannot.

**The line the row replaced is gone.** The card used to read "Version 0.6.0 · Source code"
above the ask. Both facts are badges now, and keeping the sentence would state each of them
twice on a card whose whole design is that it is short.
`AboutSection.test.tsx::states the version and the source once, not twice` holds that.

**The chrome is neutral in both modes and only the ink carries the accent.** Two solid
accent rungs were measured as a value cell first and both fail in the dark: `accent-900`
against the dark card `paper-900` is **1.01:1** on gruvbox and `accent-950` against it is
1.13:1 on rosepine, so half of each link badge would disappear into the card.

**That rejection is about solid rungs and nothing wider.** The idiom this app already ships
for a tinted chip on a dark surface is an alpha tint, `dark:bg-accent-500/20` in
`app/components/NavBar.tsx`. Composited over the dark card it measures 8.21 to 13.85 CIE L*
of separation across the seven palettes, with `paper-200` ink on it at 4.92:1 to 10.58:1:
better than the neutral split below, on every palette. It is not used here because neutral
chrome is quieter on a card whose whole design is that it is quiet, which is a choice about
loudness. Recorded so the next person does not read the two ratios above as "an accent cell
cannot be built in the dark", because they do not say that.

**The two cells are separated by a hairline, not by their own difference, and the first
draft got this wrong.** `paper-100` against `paper-200` is **1.32 CIE L*** apart on Rose
Pine light where the other six run 3.14 to 8.89, so on that one palette the badge drew as a
single flat chip. That draft had rejected a 1.13:1 accent cell in the dark, then shipped a
1.035:1 split in the light: the same defect, on the same palette, in the other mode. The fix
is `border-l border-paper-300 dark:border-paper-600`, which is 6.75 CIE L* off the value
cell and 5.43 off the label cell at worst (both Rose Pine light), and 12.30 and 24.11 at
worst in the dark (Endpaper and gruvbox).

`paper-300` as the label *background* was measured instead and rejected: `paper-800` on it
is 3.88:1 on catppuccin and nord, under the 4.5 floor.

**A contrast ratio cannot express this, so the test does not use one.**
`frontend/tests/theme/palettes.test.ts` grew a `lightness()` helper and a block asserting
that the separator is at least 3.0 CIE L* from both cells it sits between, on every palette
and in both modes. `paper-100` on `paper-200` is 1.035:1 on Rose Pine and 1.272:1 on
solarized: both round to "the same colour" as a ratio, while their lightness separation
differs by a factor of six and only one of them reads as two surfaces.

**Contrast, measured across all seven palettes and both modes** with the formula
`frontend/tests/theme/palettes.test.ts` uses, and added to that file's pair list so the
numbers cannot drift from the tokens:

| Cell | Pairing | Worst | Where | Best |
|---|---|---|---|---|
| label ink | `paper-800` on `paper-200` | **4.57:1** | catppuccin | 11.35 endpaper |
| label ink | `paper-200` on `paper-800`, dark | 5.57:1 | everforest | 11.35 endpaper |
| value ink | `paper-800` on `paper-100` | 5.34:1 | catppuccin | 12.85 endpaper |
| value ink | `paper-200` on `paper-700`, dark | 4.62:1 | catppuccin | 7.41 rosepine |
| link ink | `accent-800` on `paper-100` | 7.21:1 | catppuccin | 9.05 rosepine |
| link ink | `accent-200` on `paper-700`, dark | **4.58:1** | solarized | 6.76 endpaper |
| link hover | `accent-900` on `paper-100` | 9.34:1 | endpaper | 11.52 rosepine |
| link hover | `accent-100` on `paper-700`, dark | 5.36:1 | gruvbox | 7.89 endpaper |

4.57:1 is the worst of them, against the 4.5 WCAG 1.4.3 asks of text below 18.66px: the
badge is `text-xs`, 12px.

**The four `paper` on `paper` rows are shaped the way that table's tripwire reads.**
`palettes.test.ts::the contrast table in docs/decisions.md` parses rows whose pairing cell
begins with the two tokens, and asserts each figure is the worst across the seven palettes
and each palette is the one it belongs to. The first draft of this table wrote the cell as
"label ink `paper-800` on `paper-200`, light", which the regex does not match, so eight
freshly written figures sat in a document with a guard against exactly that and were not
covered by it. The four `accent` rows are still uncovered: the tripwire reads one ramp.

**The status pill's ramp is deliberately not reused.** The `unread` pill draws `paper-600`
on `paper-200`, which measures 3.55:1 on solarized, 3.56 on nord and 3.87 on catppuccin,
under the floor on three of seven palettes and recorded above as known debt. A badge
copying it would have inherited that. It takes the `paper-800` ink the did-not-finish pill
takes instead, which is the one rung of that pairing that clears 4.5 everywhere.
`AboutBadges.test.tsx::keeps its ink off the rung the status pill fails on` ties the
component to those tokens, because the palette file measures tokens and cannot see which
component uses them.

**A link is told apart by more than its colour.** WCAG 1.4.1, so the value cell of the two
link badges is underlined at rest rather than relying on the accent alone.

**A link badge is named by its own two cells, with a `{" "}` between them.** Measured with
`dom-accessibility-api`, the package testing-library computes names with: two adjacent
spans with no whitespace between them name the link "SourceGitHub", and with the space they
name it "Source GitHub". JSX strips whitespace between elements, which is why it has to be
written explicitly.

The first draft used an `aria-label` instead and justified it by claiming a text node
between the cells would become an anonymous flex item and open a visible gap. **That is
false**: CSS Flexbox Level 1 section 4 says an anonymous flex item containing only white
space is not rendered, as if `display: none`. The label was harmless, the reason was not,
and it was stated in four places while contradicting the rule about never assembling a
phrase out of translated fragments in the one place this component would have done it.

**It lives in the page folder, not `src/components/`.** The bar for that directory is domain
free *and* used by more than one page (`docs/frontend.md`), and this is used by one. The
pill itself carries no domain knowledge and is the half that moves up if a second page ever
wants one.

**The row is one line at `max-w-2xl` and wraps below about 401px of card width**, which is a
phone. Wrapping rather than scrolling is the choice: a badge sliced in half at the card's
edge is worse than a second line, and the second line costs 26px (20px of row plus
`gap-1.5`), so 236px, on a screen where the card is the only thing on it.

### Name lists are ordered in the browser, not by the database

`Ästhetik` used to sort after `Zebra` in every picker. Measured against the deployment's
own SQLite, both orderings the database can offer return the same thing:

```
order by lower(name)         -> ['apple', 'Banana', 'Zebra', 'Ästhetik']
order by name collate nocase -> ['apple', 'Banana', 'Zebra', 'Ästhetik']
```

`Ä` is U+00C4, above every ASCII letter, so **no case fold moves it**. Locale aware
collation in SQLite needs the ICU extension, and building one into the image for a picker's
ordering was refused before it was proposed.

So ordering by name is `frontend/src/lib/nameOrder.ts`, which owns one `Intl.Collator` per
locale and exports `sortByName`. The lists it applies to are a library's collections, tags,
series and authors: unpaginated, fully fetched, and small.

**The locale is the chosen interface language, not `navigator.language`.** It is the one
language this app knows the reader picked, `interpolate` already formats numbers with it,
and two people reading the same library in the same language then see the same order.

**The collator is cached per locale.** Measured on node 24 per 1,000 operations, by two
seats independently: constructing a collator took 7.0 to 60.8ms, comparing two names 0.10
to 0.31ms. Pairing each seat's own figures, the ratio ran from 28:1 to 243:1. The spread is
wide and the conclusion is not: construction costs one to two orders of magnitude more than
the comparison it exists to perform, so building one per call would cost more than the sort.

**The server's `ORDER BY` clauses are left in place, and they are not a second opinion.**
They make an unordered query deterministic, which the export and the API's own consumers
still want. What they stopped being is the order a reader sees: a screen drawing a name
list calls `sortByName` rather than trusting the order it was handed. Removing them would
have been the other way to keep one fact in one place; it is refused because a paged or
scripted consumer would then get rows in whatever order SQLite felt like.

**There is no exception.** Home's filter panel and its selection bar were the two that
still drew the endpoint's order, and both read one field, so `useLibrary` collates it once
and both are fixed at a single site.

**Five lists are deliberately not collated, for two reasons.** `/api/books/locations` and
the three stats breakdowns (`per_user`, `by_tag`, `by_collection` in `routers/stats.py`)
are ordered by count, which answers a different question: re-sorting them by name would
throw away the ranking that is the whole point of the chart. The name is their tiebreak
only. `/api/users` is the second reason: it is a list of account handles rather than of
names, and the loan picker that draws it is choosing an account.

**Grouping and ordering tags is one call.** `groupTagsByCategory(tags, locale)` sorts before
it filters, so no caller can get the grouping without the ordering. The categories keep
`TAG_CATEGORY_ORDER`, which is curated rather than alphabetical.

## The reading record has one owner, and it is a second privacy rule

`backend/reading.py` owns every read and write of `user_books`. The door is
`Reading.by(db, member_id)`, deliberately shaped like `Shelf.seen_by(db, viewer_id)`.

**It exists because this is a different rule from `visible_to()`, not the same one
applied twice.** `visible_to()` decides who may see a **book**. A reading record is
private to its member separately: a book being visible to you does not make my rating or
my status on it yours to read. Before this, eight call sites each spelled
`user_id == current_user.id` inline, and a site that forgot would have leaked with a 200.

**`Records` is a loaded working set that creates on demand.** That is what lets a page, a
bulk write and a 5,000 row import each cost one SELECT: measured, `books_to_out` issues a
flat **7 statements** at page sizes 1, 25 and 100.

**Two named functions read past a member, and they are two rules rather than one hatch.**
`discussers` is a read of the one column that exists to be read by other people;
`resolve_merge` is a write with no viewer at all, on a catalogue operation. Different
direction, different reason, different failure if removed: a blank marker on the grid,
against silent data loss for third parties. Same distinction `test_shelf.py` insists on.

**`shelf.py` is on the import allowlist, and the boundary is a rule rather than a
favour.** Its three `user_books` joins narrow a listing of Books, which house rule 2
owns. The reason the list will not grow is that the next module wanting `UserBook` has to
argue it is narrowing Books, and that argument only works from `shelf.py`.

**Rating a book and offering to discuss it deliberately stamp no dates.** Two of the five
creation sites never called `_stamp_reading_dates`, which looked like an omission and is
not: rating is not a claim about having finished just now, and offering to discuss says
nothing about having read it. Both handler docstrings said so, two tests pinned it, and
the live database held 0 rows with `status=read` and no `finished_at` and 0 with
`status=reading` and no `started_at`. The catalogue is too young to have exercised the
rating only path, so the data rules out an inconsistent row rather than confirming the
rule.

**Concurrent get-or-create is named, not fixed.** Two requests that both find no row both
insert, and the second raises on the unique index. It was present at all five sites
before and is now in one. The fix is a savepoint plus a re-read, which changes behaviour
under a load nobody has reported and cannot be pinned without driving two sessions at one
row, so it fails the house test for an unprompted fix. Being in one place is what makes
it cheap later.

## A write names what it made stale

`frontend/src/api/invalidate.ts` holds four groups, smallest first: `listings()`,
`book(id)`, `catalogue()`, `everything()`. Measured inclusion chain, against the test's
own key set: **2 ⊂ 6 ⊂ 15 ⊂ 34**, so "smallest first" is an ordering rather than a
decoration.

**The seam was opened for eleven keyless invalidations and the real defect was the
opposite.** Four sites hand wrote `queryKey: ["/api/books"]`, and the grid is
`useListBooksInfinite` whose key is `["infinite", "/api/books", params]`. React Query
matches element by element, so `"/api/books"` was compared against `"infinite"` and never
matched. **What bounded it was not a keyless call elsewhere**: `AuthorsPage.refresh` has
three keyed invalidations and no keyless call in either flow. Home is a separate route, so
the grid unmounts and the client default `staleTime` at `src/api/query-client.ts` refetches
it on remount. The observable window was a return to Home within thirty seconds of the
write.

**Not one group per write.** That is combinatorial, and it is what produced eleven
independent decisions in the first place.

**`catalogue()` is defined by exclusion**, which makes the exclusion the fragile half, so
`tests/api/invalidate.test.ts` finds every generated endpoint module with
`import.meta.glob` and asserts its `get*QueryKey` set equals a hand named map. A hand
written module list was tried first and rejected on measurement: `git log --diff-filter=A`
shows five of the eleven modules arrived after the initial commit, so the one way
endpoints actually appear here is the way such a list cannot see.

**Two sites stay wide and carry the reason at the call site.** A duplicate merge moves
notes, loans, quotes and statuses between books and the response names the survivor but
not which children moved; a backup restore replaces every row, including the one behind
the signed in member.

**A keyless `invalidateQueries()` is now confined to that module** by
`houseRules.test.ts`. Its blind spot is stated in the test: it counts a spelling.

### A custom field renders as a link because the Library said so, and only if the value still is one

Two mechanisms, and the second is the one that matters.

`CustomFieldKind.URL` is declared per field. Detection on the value would read a Member
typing prose that begins with `http` as a link, and would make every field a link surface for
a feature that needs one.

**The declaration is not the permission.** `custom_fields.link_target` re-reads the stored
value on every serialisation and hands back a target only for `http` or `https` with a real
host, no credentials and a parseable port. So a row that reached the table without passing
the write check is served as text. There is such a path: `backup.restore` inserts through
Core, where neither a Pydantic model nor `@validates` fires. Same trap `Book.cover_url`
records, answered at the read end rather than by asking one more writer to remember.

`covers.is_renderable` is not reused. It keeps an `<img src>` inside `COVER_HOSTS`, and a
custom field is a link to a system this app has never heard of, so a host allowlist would
refuse the calibre-web URL the feature exists for. What is shared is one hard-won line:
`urlsplit(...).port` **raises** on a port past 65535, so a single stored `https://h:99999/x`
would be a poisoned row that 500s every read of that Book.

`http` is allowed as well as `https`, unlike a cover: a link is a navigation rather than a
subresource, so no browser blocks it as mixed content, and the calibre-web instance this is
for is on a LAN with no certificate.

**The stored value for a URL field is the parsed form.** `urlsplit` strips tabs, newlines and
leading control characters exactly as a browser does, so storing the raw text would leave the
server and the browser reading two different URLs, which is the gap scheme smuggling lives
in.

### Deleting a custom field is admin only, defining one is not

The same split `delete_tag` makes, and the sharper case of it. Defining is additive and
reversible by deleting; deleting destroys, in one request with no undo, content every Member
typed by hand, on Books the caller cannot necessarily see. A `CustomField` records nobody as
its author, so there is no owner to ask. Deleting a Tag takes a label off a Book; deleting a
field takes the words.

### `MAX_CUSTOM_FIELDS` is the only ceiling the feature needs

A Book holds at most one value per definition (`uq_custom_field_values_book_field`), so
bounding the definitions at 25 bounds every Book's payload, every rename's blast radius and
every row this feature can add. It is also what makes `define` cheap enough to fold a name by
scanning the whole table in Python, which is what `create_tag` does and why.

### Settings is an index of six routes, and the descriptions are the page

Grouping settled by the owner, 2026-08-27: six routes, About its own, and
"definitely fewer and larger groupings". Two placements came from reading the
strings rather than the section names. **`defaultLanguage` is Appearance, not
Catalogue**: its string is "Default language for new visitors", which is the
interface language for somebody who has not chosen one, not a cataloguing
decision. **`covers` is Your library, not Catalogue sources**: its own text names
the import as the thing that creates work for it.

The weakest group is `backup` with `testAccounts`, recorded as weak rather than
argued into soundness: both are things only an admin touches, which is a thinner
thread than the other five have.

**The sentence under each heading is the whole value of the index.** Six headings
alone would make a household open three screens to find one setting, which is
worse than the long page this replaced. The test asserts that as a property of all
six rather than by quoting one, so a seventh route with no description fails.

**A member is offered three of the six, and the routes stay mounted.** The three
whose whole body is admin only carry an `adminOnly` flag and are filtered off the
index by `currentUser.is_admin`, a prop threaded from `AppRoutes`, which costs no
request. **Not `localStorage["user"]`**: under proxy authentication that key is
not the identity and is never written, so reading it dropped three entries off a
proxy admin's own index, permanently. The page this replaced refused **in place,
once**, beside the cards it was refusing; six unmarked links would have turned
that into three dead ends, each a tap away and each advertised with a sentence
promising content.

**The flag decides what is offered, never what is allowed.** A deep link still
lands and still meets the admin gate, every endpoint behind those screens is
`require_admin`, and a forged cached account restores the links and then meets the
same refusal. It may only ever fail by under offering.

**`/settings/data` is the weakest gate of the six and is tested as one.** It is
the only route whose entire body is gated by where a JSX tag sits: on the other
admin screens every card consumes `settings`, so moving one out of the gate does
not compile, while neither `BackupSection` nor `TestAccounts` takes that prop.
Measured by making that mutation: typecheck clean, 182 of 182 green, and a member
shown Download and Restore above "Only an admin can change these". Both endpoints
are `require_admin`, so it is an offer the API refuses rather than a leak, and an
offer the API refuses is still a defect.

## Tooling

### Bun, not npm

`bun.lock` is the lockfile. The Docker build uses `oven/bun` for the frontend stage only:
the shipped image is a Python image with no JavaScript toolchain in it.

### `bunfig.toml` configures a security scanner

`bun install` screens packages before any package code executes, the only moment a
supply-chain check is worth anything. Two consequences. If the scanner package is missing,
**`bun install` fails closed** rather than skipping the check. And the scan is an outbound
call made during the Docker build's frontend stage, so a sandbox with no egress fails the
install. Allow the host rather than removing the config.

### `--import-mode=importlib` for pytest

Required by the mirrored layout, not a preference. See [testing.md](testing.md).

### Alpine, and the musl bar for new dependencies

Both stages are Alpine. The runtime moved off Debian because its userland is findings
waiting to happen against software the container never executes.

This matters when adding a Python dependency. **A C-extension package with no musllinux
wheel does not fail politely:** uv tries to build it from source and dies for want of a
compiler, in CI, at image-build time. The current native set (bcrypt, pydantic-core, uvloop,
httptools, watchfiles, greenlet, sqlalchemy) was verified to install from musllinux wheels
*and* to run on musl before the switch.

### TypeScript's strictest options are on

`noUncheckedIndexedAccess` in particular, which is why array access reads `tags[1]!` in
places. That is honest about the fact that an index may miss.

### Each test runs in a transaction, and pysqlite is not allowed to open it

Every test used to drop nine tables, recreate them and reseed 105 tags. That was about
1690 rebuilds a run, and the dominant cost once the database moved to tmpfs and
`synchronous` went OFF. It is now one rebuild per xdist worker, with each test inside a
transaction that is rolled back. Measured on the CI host at `-n 2`: 134.44s for 1683 tests
before, 93.99s to 101.01s for 1689 after, over four runs.

Two pieces of it are load-bearing and fail silently. `join_transaction_mode="create_savepoint"`
is what survives the application committing constantly: without it the first `db.commit()`
in a request ends the outer transaction. And pysqlite has to be taken off transaction duty
(`isolation_level = None`, plus a `begin` listener that emits `BEGIN`), because it opens a
transaction before an INSERT, UPDATE or DELETE and before nothing else, so `SAVEPOINT`
would stand alone in autocommit. Measured before writing the fixture: two tests writing two
rows each left **4** rows behind, and 0 with the listeners in place, on the real engine.

Neither failure breaks the test it happens in. It leaves rows for whoever runs next, which
is why `tests/test_conftest.py` asserts the isolation with an ordered pair of tests rather
than trusting it.

`@pytest.mark.real_database` opts a test out and restores the old behaviour, for DDL, a
second connection, or state that has to outlive a commit. The list and the reason per entry
are in [testing.md](testing.md). The rule is to opt out and say why rather than to force a
file into the transaction: a test that passes alone and fails in a suite costs more than
the seconds it saves.

## Reference implementations: what may be read, and what may not be copied

Endpaper's features were designed against prior art rather than invented, and
two of those sources carry licences that make copying a legal problem rather
than a stylistic one. Recorded here because the document that held it was a
session plan and session plans are deleted.

**BookWyrm is ACSL v1.4**, which is not OSI approved and is compatible with
neither GPL nor MIT. It is the best worked example of quotes from books in the
field, and it is the one that must not be borrowed from literally. Read it for
design; do not copy code without checking the terms. The quotes feature here was
argued in its own words for exactly this reason.

**Koha is GPL.** This project is not, so Koha is a source to read for behaviour
and not a source to lift from. Its value was always the holds queue and
notification model, which is the part deliberately scoped out.

**Reusable, and used as such:** Jelu (MIT) for author pages and merging, BookLogr
(Apache-2.0) for quotes beside notes. Where a design here departs from Jelu, the
departure is argued in the author entries above rather than assumed.

**Two features had no useful reference.** Collections and multiple copies are
shaped by this codebase rather than by the field: what decides them is
`visible_to()`, the shape of the peer sync payload, and `books.isbn`
being unique. Reading a competitor will not tell you what breaking that
constraint costs here.

## Product

### Small libraries and archives are a direction, not a second audience

Decided by the owner on 2026-08-26. The question had been open in two roadmap files at once,
each waiting on the other, and it was the cheapest answer available: it was blocking a mode
switch that had no technical blocker at all, and seventeen features behind that switch.

The framing that was rejected is worth stating, because it is the one somebody will propose
again: **serve households, and let institutions use it if they happen to fit.** That reading
makes every institutional feature optional forever, which sounds cautious and is actually the
expensive answer, because it leaves each one permanently half specified and gated behind a mode
nobody commits to finishing.

Four things move from someday to core as a result.

**The patron record brings the GDPR into the core product.** Everything stored until now is
books and accounts. A patron is a real person's name, email, phone, street, house number,
postcode and city, held by an Austrian operator. Its deletion rule, anonymise the loan rows or
refuse deletion while history exists, has to be decided **before** the schema rather than after,
because both choices are expensive to reverse once data exists.

**Multi workstation is expected**, which withdrew a refusal. See the next entry.

**MARC import and export, and label printing, are core work.** Both were previously behind a
mode. Both are sized higher for this audience than for a household, because physical output
means iterations against a real printer and record exchange means batch handling and error
reporting rather than a parser.

**The outward language has to stop presuming a household, and the claims have to stay staged.**
Those are two separate obligations. Library mode is not built, so a page that advertises a
public catalogue sends an archivist to install a household app. Widen the framing, stage the
claims.

What does not change: **private books stay private in every mode**, and the public catalogue
exposes what was chosen for publication and never a private row. A direction decision makes the
mode worth building. It does not relax the rule the mode exists inside.

### Multi workstation is expected, and the shape is deliberately unchosen

The desktop plan carried a pre written refusal: a small library with a circulation desk and
three machines will ask for shared access, and the answer is the existing container, not a
desktop app learning to be a server. Decide the refusal before somebody asks.

Somebody asked. The owner answered on 2026-08-26 that multi workstation work is expected, so
the refusal is withdrawn and **no replacement has been chosen**. Recorded here because a
withdrawn refusal with nothing in its place is how a product gets decided by default.

**The thing to know first: multi workstation already works.** The container is a server. One
backend process, one SQLite file, many browsers, and concurrency handled at the HTTP layer and
never at the file layer. Three desks is a deployment, not a feature.

**It is the desktop shape that breaks it**, and precisely. The desktop client's single instance
lock exists to stop two desktop processes opening one SQLite file, which is the corruption case.
A second workstation running its own copy against a shared file is exactly that case, over a
network filesystem, which is worse. So the real question is not whether this can serve three
desks. It is which artefact the archive installs.

| | Cost | What it gives up |
|---|---|---|
| The container is the answer | Documentation only | The audience that cannot run Docker, which is most of why a desktop client exists |
| Desktop plus joined terminals | M to L, and mostly built | Nothing structural. The joined device enrolment already specified for phones does not care whether the device is a phone or a second desk |
| The desktop app becomes a server | L to XL | This is the one the original refusal was right about |

The second option is the find, and it was invisible from either plan alone: the desktop plan
and the public library mode plan arrived at the same enrolment design from opposite directions.

**Consequence for anyone starting the desktop client:** do not write the single instance lock
before the shape is chosen. It is cheap now and a refactor later, and it is guarding different
things under each option.

### The outward language names both audiences, and the claims stay staged

Adopted 2026-08-26, following the direction decision above. The line is:

> A self-hosted catalogue for the books you share.
>
> Built for a household's shelves and for the library or archive that has outgrown a
> spreadsheet. Scan a barcode, get a real bibliographic record, and know who has what across
> the people and places that share it.

**Two tiers, because one sentence cannot do both jobs.** A single line trying to address a
family and an archive at once goes vague, which is the failure this was meant to avoid. So the
headline is audience free and carries the places that only accept one string (a Docker Hub
short description is capped at 100 characters), and the second line names both audiences
explicitly where there is room.

**"The books you share" is the unifying frame, and it was chosen over the obvious
alternatives.** Not "shared collections", which is accurate and reads like enterprise software.
Not a benefit line like "know what you own and who has it", which is memorable and says neither
"books" nor "self-hosted", so it works as a subtitle and not as a headline.

**The claims are staged behind what has shipped**, and that is the part most likely to be got
wrong. Widening the framing is free; widening the feature claims is not.

**What was deliberately not rewritten.** `CHANGELOG.md`, because its entries record what shipped
when and restating them in today's vocabulary makes the file lie.

**Capitalisation follows the file.** A document whose job is to define a term capitalises
it; everywhere else, including code comments and the rest of this file, the register is
lowercase: measured on 2026-08-26, `docs/` contained 61 instances of "a
book" and none of "a Book". A pass that capitalised them was reverted for that reason.

### The glossary names the operator only where it has to

The old glossary defined a household as "the group that shares one Library" and then built
seven other definitions on top of it: the household's catalogue, a person who belongs to the
household, a word the household curates. That made the family the load bearing noun of the
whole domain language.

**One deployment holds one Library, so the group that runs it rarely needs naming in code.**
Name the **Library** or its **Members** instead, and the operator kind stops leaking into
definitions that do not depend on it. Where it genuinely has to be named there are now two
kinds, **Household** and **Institution**, and they are not interchangeable in tone or in
obligation.

Five terms were added rather than renamed, each because a decision resolved it: **Institution**,
**Library mode**, **Patron**, **Call number** and **Accession number**. The last carries its
constraint in the definition, because the constraint is not obvious and is expensive to
discover: digits only and fixed length, since a barcode scanner in keyboard mode emits
characters that the host keyboard layout decides, and only digits survive every layout.

**`Tenant` and `organisation` stay on the avoid list**, and `customer`, `client` and `Kunde`
join it for the Institution and Patron entries. A library does not have customers, and a reader
will notice.

**No code had to be renamed.** Checked on 2026-08-26: no table, column, enum, API field or
variable contained the word. Only four test function names did. The domain model had never
named the group, which is what made the glossary change cheap.

### German address follows library mode, as an overlay rather than a second catalogue

Decided by the owner on 2026-08-26. **du with library mode off, Sie with it on.**

`de.ts` is informal throughout and its own header justified that as "a household bookshelf, not
a bank". That was right for a household and wrong for an institution, because a German library
addresses a Benutzer:in as Sie, and a public catalogue written in du reads as careless. It is
the same class of mistake the patron work already avoided when it refused "Kunde" as a shop word
a reader would notice.

**The naive implementation is two catalogues and it is the wrong one.** Measured before
choosing, because the estimate and the fact differ by an order of magnitude: of **640** string
values in `de.ts`, **58 carry address at all**. Forty-four contain a du pronoun or possessive,
fourteen contain a likely informal imperative, and that second figure is an overestimate because
the probe counts nouns such as "Suche läuft". German interface labels mostly avoid address
entirely: "Bibliothek", "Scannen", "Ausleihen" are the same in both registers.

**So the formal register is an overlay.** `de.ts` stays informal and stays the whole catalogue.
`deFormal.ts` holds only the keys that differ, typed as a partial, and is merged over `de` when
library mode is on. Roughly **9%** of the file rather than 100% of it, and the 582 strings that
carry no address exist once, so the two registers cannot drift on them.

**The enforcement is a test, not discipline.** A partial overlay cannot use the `Messages` type
to catch a *missing* formal variant the way `de.ts` catches a missing translation. What catches
it instead: grep the merged formal catalogue for informal markers and fail on a survivor. That
converts a permanent review cost into a one time one, which is the house pattern already used by
`TestTheShelfIsTheOnlyWayIn` and `houseRules.test.ts`.

**Blocked on library mode existing**, because there is no mode to follow until then. English is
unaffected: it has no equivalent distinction.
