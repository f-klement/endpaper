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

`backend/shelf.py` is the only module that imports `visible_to` or `in_trash_for` and the only
one that builds a query over `Book`. A caller asks `Shelf.seen_by(db, member_id)` and narrows
what comes back, so **visibility is a property of how the query was built** rather than a step
each endpoint has to remember.

**A deleted guard with no record reads as a regression, so this is the record.** What went was
a 681 line AST walk over every backend module that tracked scopes and bindings through
`symtable`, carried five `# visible_to exempt:` comments and a second test counting them. It
was good at its job and it was scar tissue over a missing seam: `dependencies.py` owned the
rule for **one** book, nothing owned it for **many**, and that is exactly where the leaks were.
`list_tags` counted books unfiltered and disclosed which tags existed only on somebody's
private books.

`test_shelf.py::TestTheShelfIsTheOnlyWayIn` replaces it with four flat `ast` passes: who
imports the predicate, who builds a query naming `Book`, who reaches `books` through a join,
and who reads a table belonging only to a Book. It resolves which local names mean `Book`
first, so an alias or a rebinding is caught, and it carries short allowlists rather than opt
out comments. **It needs none of the scope machinery**, and the reason is structural: outside
`shelf.py` the correct answer is zero, so there is no "was a predicate applied here" left to
decide.

**The first version of it was two regexes and was measurably weaker than the guard it
replaced**, which both critics found independently. Four shapes passed it clean, every one a
location index publishing a name and a count over every member's private books:

| Shape | Old regexes |
|---|---|
| `db.query(Loan.id, Book.title).join(Book, ...)` | passes |
| `db.query(models.Book.location)` | passes |
| `db.query(B.location)` after `from models import Book as B` | passes |
| `db.execute(sa.select(Book.location))` | passes |

**A guard whose limits are undocumented is read as a guarantee it never made**, and that one
documented the opposite of its limit, which is worse than the hole.

**Where the rule does not reach, named rather than left to be discovered.** Two functions read
past a viewer and they are two rules, not one hatch: `whole_table_for_uniqueness()`, because
the ISBN and copy group constraints are table wide, and `rereading_filtered_rows()`, which
re-reads rows a caller already filtered. `notifications.py` is outside the guard because the
overdue digest has no viewer and partitions on privacy rather than filtering by it, and
`backup.py` is invisible to it because it queries a loop variable, reads every row so a restore
cannot lose one, and is admin only.

**`Shelf.select()` anchors the FROM at `books`**, which fixes the join direction and nothing
else, and it refuses a shelf narrowed by read status, which is worth knowing before reaching
for it.
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
| `paper-600` on `paper-200` | **3.55:1** | solarized (then 3.56 nord, 3.64 ayu, 3.74 tokyonight, 3.87 catppuccin) | 4.71 default |
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

`_LOC_URL` is `http://lx2.loc.gov:210/lcdb`, with `follow_redirects=True`. It is one of the
three catalogues not fetched over TLS, because that is the endpoint the Library of
Congress publishes for its Z39.50-over-HTTP SRU gateway; the other six are https. The
other two plaintext endpoints are `_NLG_URL` and `_NKP_URL`, which arrived later and are
the same gateway shape.

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

### Catalogue XML refuses a doctype, and the response body is capped at 2 MiB

**Every catalogue parse goes through `metadata._parsed`, which refuses a body carrying
`<!DOCTYPE`** and raises `ParseError`, which every caller already caught. `xml.etree` expands
nested internal entities: measured on this project's Python, three levels expand to 1,000
characters, so six is a million. It costs nothing real, since 225 live DNB and K10plus
responses carry no doctype, nor do live BnF or Library of Congress answers.

**The wire body is capped too, and the cap is 2 MiB rather than the 1 MB first proposed.** The
largest honest body moved from 587,810 to 687,481 bytes in three days as the query sample
widened, so the tail of a third party's record sizes is being **sampled, not bounded**, and the
margin is deliberately 3.05x rather than tight.

**Parsing retains a measured 15.28x the wire bytes**, in a pod limited to 512Mi where a 1.8 GB
peak has already caused an OOMKill. That is why a parser bound and a transport bound are both
needed rather than either standing in for the other.

**The cost of streaming was assumed and was zero**: respx intercepts `client.stream` exactly as
it intercepts `client.get`, and 190 existing tests passed against streamed reads with no
fixture changed.
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
next step.** It is reached over plaintext HTTP, which this file already records as
accepted precisely because it is not on the scan path, and putting it there would add an
outbound call to every scan. It was the only plaintext catalogue when this was written;
the National Library of Greece and the Czech national library have joined it since, and
both **are** on the scan path, which is why each needed its own entry rather than this
one being widened. It would also buy nothing for this
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

Measured on one live record, which is the whole argument:

| schema | bytes | GND identifiers |
|---|---|---|
| `oai_dc` | 1,713 | none at all |
| `MARC21-xml` | 15,502 | 100, 600, 650, 651, 655, 689, 710 |

Dublin Core carries no authority identifiers at all, so author identity through the DNB is
impossible on that schema regardless of what else it holds.

**The switch cost one field: the DDC caption.** `dc:subject` reads `830 Deutsche Literatur`
where MARC gives the number without the words. The number is what sorts and files, so the
caption is the cheaper half to lose, and `ddc.py` supplies captions for the divisions it knows.

**Four defects only a live comparison could find**, none visible in a fixture written from the
specification: the two schemas disagree about non sorting delimiters, about which tag carries a
subtitle, about repeating a field where the other subfields it, and about whether a record
without a physical carrier is a book. **The physical book filter is a preference on the lookup
path and a refusal on the search path**, deliberately, because a lookup asked about one ISBN
should answer with what exists rather than nothing.
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
proposed **Crime** and `Trous noirs` proposed **Noir**.

Measured live against the 105 seeded tag names:

| Population | Substring | On word boundaries |
|---|---|---|
| 12 English books, Open Library subjects | 27 suggestions, 7 wrong | 20, **2 wrong** |
| 10 German ISBNs, DNB subject headings | 5 suggestions, **5 wrong** | 0, none |
| both | 32, **12 wrong (37.5%)** | 20, **2 wrong (10%)** |

**The two sides are not symmetrical**, which is what decides it: the client pre-selects every
suggestion, so a wrong one is written unless somebody unticks it, while a missing one costs a
click. Ten wrong removed against two correct lost, on that asymmetry, is not close.

**The German row is the sharper one.** On those records the substring route produced nothing
but false positives, out of `Gegenwartsliteratur` and `Softwareentwicklung`: it was not scoring
zero there, it was scoring negative. That is the failure the DDC number projection exists to
work around.

**What it costs**: a multi word tag whose words are separated differently in the subject no
longer matches. Measured and accepted rather than assumed.
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

**Four channels since 2026-08-28, and the fourth is not like the other three: it does
not go out.** The in app notice is added below; the reasoning in this entry is about
the three that push and is unchanged.

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

**The count is reported per channel as well as once at the top.** It was written when
all three withheld the same rows and all three reported the same number, and it argued
that a single figure would become a lie the moment one audience differed. **That moment
arrived**: the in app channel reports 0, because its audience is a member and nothing is
withheld from them, while the three that push still agree with each other. The shape is
the reason the fourth channel needed no new field.

**A per borrower mail is the one audience that could carry a private book, and it is not
built.** Being reminded of a book *you* borrowed is not a disclosure, and withholding it
means nobody ever chases the one book least likely to be chased by anyone else. The reason it
**was** absent was a missing fact rather than a judgement: no member had an email address.
**That fact changed with #80 and the conclusion did not.** `users.email` exists, a member
or an admin can set it and a directory can fill it, and **nothing in the reminder path
reads it**: `send_mail` takes its recipients from `mailer.checked_config`, which reads
`overdue_mail_to` and nothing else.

What is still missing is the per borrower **audience**, which is a second recipient list
and a second shape of digest rather than a column. Mail still goes to the household's own
mailbox, which is a channel like the other two and excludes private books like the other
two. Recorded so the absence reads as a blocked item rather than an oversight, and
rewritten rather than deleted so that the reason it was blocked, and the fact that the
blocker is gone, are both findable by whoever proposes it next.

### `notified_at` is a timestamp on the loan, stamped when at least one channel that pushes delivered

Without any state the digest has two behaviours and both are wrong: send once and forget a
book that is still out, or repeat the same list into the channel every hour.

Stamped after a send that succeeded rather than before it, so a run where nothing was
delivered leaves the loans to be retried on the next tick. That is why it is a timestamp
rather than a "sent" flag: the interval question ("has this been chased recently") and the
retry question ("did the last attempt land") are the same question, and one column answers
both.

**With four channels, "at least one" rather than "all of them", and the rule is
narrower than it sounds: at least one channel that *pushes*.** The in app notice
delivers nothing outward and never advances the column. **The choice has a cost.** A broken webhook beside a working Telegram chat means that batch never reaches the
webhook. The alternative repeats the identical list hourly on the channels that work, which
is the behaviour people switch off, and the only way to have neither is per loan per sender
state, which is a table this feature does not warrant. The column records that the loan
**was chased**, and it was; a channel that is down is an operator problem, reported in
`senders` rather than compensated for.

**What compensates for it is reporting, and the gap this entry used to describe is
closed.** The hourly ticker discarded its result, so a per channel failure was visible
only on the run that failed and in the log afterwards. It no longer does: every run
records what each channel did into `SettingKey.SENDER_HEALTH`, so a failure survives the
run that produced it and is shown under that channel's own switch.

What survives of the original caveat is the honest half. The column still records that
the loan **was chased** and still does not say by which channel, and per loan per sender
state remains a table this feature does not warrant.

### The digest result carries a `reason`, and it is null exactly when it sent

`sent: false` on its own made six different outcomes one answer on the screen: switched
off, no address stored, nothing overdue, a receiver that refused the request, a channel
whose settings cannot be used, and, since the in app notice, every pushing channel being
off so that nothing was sent anywhere and nothing was meant to be. A person
pressing "Send now" to check their configuration was told "nothing was sent" by a broken
setup and by a quiet week alike, which is the whole thing the button exists to tell apart.

`detail` was already there and is not enough. It is a sentence, and a client cannot branch
on a sentence or translate one. `reason` is the closed set beside it, so the frontend keys a
`Record` off the generated union and adding a seventh reason on the server is a compile error
in the catalogue rather than a silent fall through. It did exactly that: `in_app_only`
reddened `REASON_LABELS` and `SENDER_ROW_REASONS` until both were given an arm.

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

`_purge` used to call `covers.forget` first. A rollback after that point undoes the DELETE and
not the unlink, so the member still has the book and its `cover_url` names a file that does not
exist, with nothing logged. Copies made it reachable through the ordinary scan flow.

`_purge` returns the id and the caller unlinks after its commit. **Reordering inside `_purge`
buys nothing**, because `db.delete` only marks the row in the session, and flushing per book to
get closer would put back the 3,801 statements the "does not commit" note exists to avoid.

**In `_create_book` the unlink sits after the commit and before `_store_cover`.** SQLite reuses
the id of a deleted row, so the new book may hold a purged id: unlinking later deletes its own
cover, and not unlinking hands it somebody else's. That window is three lines wide and pinned
by `test_a_reused_id_keeps_the_new_book_s_own_cover`, because moving the loop below
`_store_cover` passes every other test in the file: only a test that forces the id reuse and
stores a real cover can tell the two orders apart.
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

`uq_collections_name_nocase` was a functional index on `lower(name)`, and SQLite's `lower()`
folds the twenty six ASCII letters and leaves every other letter alone, so `Ästhetik` and
`ästhetik` were two shelves while `Fiction` and `fiction` were one. `COLLATE NOCASE` is the
same twenty six letters: measured, `'Ästhetik' = 'ästhetik' COLLATE NOCASE` is 0 while
`'Fiction' = 'fiction' COLLATE NOCASE` is 1.

A Unicode aware `lower()` needs the ICU extension, which this image does not build, and a
Python UDF registered per connection leaves the index unmaintainable by any connection that
did not register it: the `sqlite3` CLI, a restore, an ad hoc script. **Between a rule enforced
on a derived column and a rule not enforced at all, the derived column wins**, so
`collections.name_folded` is stored with a plain unique index on it.

**One function derives it and three sites call it**, because only one of the three can use a
validator: `Collection._fold_the_name` covering ORM writes, `routers/collections._named`
folding an incoming name to compare, and `backup._parse_row`, whose Core insert fires no
validator. Claiming one *place* derives it is false; one *function* does.

**`.lower()`, not `.casefold()`.** Casefold makes `Straße` and `STRASSE` one shelf, which is a
different product decision and is not this one.

**A pre-revision archive holding a colliding pair is refused, not merged.** A restore repairing
data is a restore that does not restore; it answers 400 rather than raising `IntegrityError`
into a 500.

**A dangling id is a hard failure, not a repair.** Nulling the column would unfile books.

#### The migration merges, and four SQLite traps decided its shape

* **`PRAGMA foreign_keys` is 0 in a migration connection**, so the `ON` listener is not bound
  and cascades do not fire. Anything depending on them is done explicitly.
* **A failed revision may not roll back**, so every check runs before the first write.
* **The surviving row of a merged pair is the higher rowid**, which is what SQLite hands the
  next insert.
* **Reflection loses an index on an expression**, so the batch rebuild recreates it rather
  than reflecting it.

**The downgrade cannot un-merge.** It restores the schema, the losing rows and their names, and
says so rather than implying a round trip.

**Ordering by name was deliberately not part of this.** No fold moves `Ä`, which sorts above
`Z` under a plain comparison; collation for display order is a separate change.
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

Austrian imprints were reaching members as hand typed records, because the catalogues this
app asked cover Austrian publishing thinly. The ÖNB publishes over Alma SRU: CQL in, MARCXML
out, no key, CC0.

**The ISBN index is `alma.isbn`, and no documentation states it.** The published examples
cover the MMS ID, AC number, barcode and title and say nothing about ISBN. It was confirmed by
reading an ISBN off a live record and putting it back through the index.

**A wrong index name is not an error and does not return nothing.** Measured live:
`alma.isbn=` returns 1 record, while `alma.isbn13=` and `zzz.qqq=` both return **7,793,152**,
the entire catalogue, under HTTP 200 with no diagnostic. A typo would have answered a member's
scan with a well formed MARC record for an unrelated book. The only thing between that and a
shelf is the check that a returned record's own `020` carries the ISBN asked for, which now
carries a third source's weight.

**Every error this endpoint reports arrives as HTTP 200**, including an invalid query, and a
bare multi word term is one of those invalid queries, so the terms are ANDed.

#### Where it sits

Asked after the DNB and K10plus, before Open Library. Measured over 50 ISBNs, five each from
ten Austrian presses, off live ÖNB records printed after 2005:

| catalogue | held | mean latency |
|---|---|---|
| ÖNB | 50 / 50 | 0.240s |
| DNB | 47 / 50 | 0.210s |
| K10plus | 39 / 50 | 0.390s |
| neither German source | **3 / 50** | |

**Six percent is a floor, not an estimate**, and the shape says why: every ISBN came off an
ÖNB record from a well known press, which is the half of Austrian publishing the German
catalogues are likeliest to hold too. Enough for a fallback, not enough to widen the fast pair
everybody pays for.

#### Two defects the mapping would have shipped, neither visible by reading

**Non sorting delimiters are spelled differently.** MARC brackets a leading article so a
catalogue can file it: the DNB writes U+0098 and U+009C as specified, the ÖNB writes `<<` and
`>>` and writes U+0098 nowhere. 21 of 150 live `245 $a` values carry a bracketed run.

**Over half of what a title search returns is journal articles**, which a `773` linking entry
identifies. Refusing anything carrying one drops 0 of 122 monographs.

#### A `ValueError` no SRU handler caught, and a bound that could not have helped

`_pages_from_extent` matched `(\d+)` and called `int()`. CPython refuses a conversion of more
than `sys.get_int_max_str_digits()` digits, 4,300 by default, and raises **`ValueError`**,
which is neither `httpx.HTTPError` nor `ElementTree.ParseError`, so **none of the eight SRU
handlers caught it**. One record with 4,301 digits in its `300 $a` turned search and lookup
into a 500 **for every MARC source at once**.

**The response cap could not reach it**, and that is the point rather than a detail. The
poisoned envelope is **4,870 bytes**, while the smallest honest response that source sends is
**4,585 bytes** over 50 live lookups, so no cap that still admits a real lookup could have
refused it. **A transport bound and a parser bound are not substitutes.** The fix bounds the
digits at the parser, with a lookbehind so a bare digit run cannot match across a separator.

#### What was deliberately not done

The ÖNB is not read for author authority identifiers, `MARC 084` is not read though its
records carry it heavily, and no cover host was added. Each is a separate decision with its
own cost, not an oversight.

#### What adding a catalogue cost, which is the seam's own report card

**Two parameters and about forty lines of adapter.** That figure is the reason the source row
work was worth doing, and it is the number to compare the next addition against.
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
card's `paper-0` is **5.03:1** at worst across the ten palettes (rosepine; 5.91 at
best, on endpaper, where an earlier draft of this line said 5.30, which is nord's), and `paper-400` on `paper-900` in dark is
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
  wrong unit: seven of the ten palettes need more than 0.15 in dark to reach the weight
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

Fine interlaced strapwork collapses into an even grey at wallpaper opacity. That judgement is
now `frontend/tests/theme/rasterise.ts` and two assertions, read off the generated tile rather
than off the source.

**Tint contrast**: the tile's ink, blurred, as RMS contrast against its own mean. The floor is
0.196, which is **not chosen**: it is what a field of parallel lines at exactly the 12px mark
pitch measures through the same filter. At 4px, the grey wash, the same field measures 0.018;
at 30px, 1.140. The ten shipped patterns run 0.354 to 1.696.

**The floor is a measurement, not a formula**, so the blur that produced it is part of the
definition: three passes of a width 7 box, a cascade with a standard deviation of 3.46px.
Changing the filter changes the floor, and the number has to be re-derived rather than carried.

**A seam is a property of the layout, not something to look for in a picture.**
`frontend/tests/theme/patterns.test.ts` walks the cells and requires the last row's phase to
differ from the first's. A stagger parity constant is thrown at module load with the others, so
a wrong one fails every test in the file rather than one.

**A pitch check is vacuous for a pattern that derives its extent from its own pitch**, which
Asanoha does, and that vacuity is itself asserted so nobody cites the check as a guarantee it
does not give.

**The general lesson, which cost a shipped defect**: an invariant belongs in the constructor
that can enforce it, and a constructor invariant is only worth what it constrains. Both halves
have to be checked.
### The plait was verified by rendering, and not on a real screen

The condition on shipping the plait was that its over and under survives at true opacity on
a real 2x display, because two designers independently predicted it would not. What was
actually done: the tile was rasterised at 1x at the solved opacity over the light page, and
the image inspected at two tiles square. The break at a crossing is 20px of interrupted
2.2px outline and it reads. The tint contrast is 0.477, which is 2.43x the floor and the
third lowest of the eight decorated papers: Nonpareil at 0.354 and Curl at 0.435 both
resolve less, and both are fields of parallel lines, Curl being Nonpareil combed a second
time. Recounted 2026-08-29 when the family went from five to eight; it read "second lowest
of the five" and named only Nonpareil.

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

They are amber, green and orange at 29 lines across 16 files, so nine of the ten palettes
ship a success message and an overdue badge in colours belonging to none of them. Tokenising
them is three ramps times ten palettes times two modes, which is a phase of its own and
not this one.

**One repair landed anyway, because it was a live AA failure and needed no token.**
`text-green-600` on the card measured **2.61 (Tokyo Night) to 3.22 (Endpaper)** for text
that needs 4.5, and it is the success message on four screens. It is now `text-green-800`,
measured **5.78 (Tokyo Night) to 7.13 (Endpaper)**, clearing on all ten. `green-700` was
the obvious step and does not clear on five of the ten: 4.01 Tokyo Night, 4.12 Kanagawa,
4.29 Nord, 4.37 Catppuccin, 4.49 Gruvbox.

That measurement is also the argument for the token job. A raw hue is a bet on seven
different card colours at once, and the only green that wins it is two steps darker than the
one anybody would reach for.

### `:root:root` in the `prefers-contrast` block

Doubled deliberately, and not a typo. The rule has to outrank `:root[data-theme="x"]`, which
is (0,2,0); written once, at (0,1,0), the preference would be honoured on the default
palette and silently ignored on the other nine. The dark half is `:root:root.dark` for the
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

One Ko-fi link, in `README.md` and in an About card in Settings. **Nowhere is it a pitch**,
which is the whole of the wording rule: all three sites carry the same two facts, what the
money pays for and that nothing is paywalled.

**The English is the source and the German is not a gloss.** "All features are free" becomes a
sentence a German reader would write, not a translation of an English marketing line.

**The button is served from `/kofi-button.png`, not from Ko-fi.** `img-src` derives from
`covers.COVER_HOSTS`, and a funding button is the weakest case for widening a policy that
exists to stop a private server reporting itself to third parties.

**The card's size does the work.** Measured from the class list rather than estimated, as the
share of a five card member page the About card paints:

| Version | About | page | share |
|---|---|---|---|
| First draft, with a sentence describing the app | 286px | 788px | 36% |
| That sentence cut | 246px | 748px | 33% |
| Version and source on one line | 210px | 712px | 29.5% |

A card that is a third of the page reads as an ask whatever its words say, which is why the
sentence went rather than being reworded.
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

`README.md` opens with a row of shields.io badges and the About card carries the same row,
and **none of it is an image**.

**The constraint is the CSP.** `img-src` derives from `covers.COVER_HOSTS`, and this card
already refused to widen it once, for the Ko-fi button, which is served from
`/kofi-button.png` for that reason. A badge is decoration, so it is the weakest possible case
for a policy entry, and a remote one reports a private server to a third party every time
somebody opens Settings.

Drawn as markup and CSS instead, which also themes with whichever palette is in force,
renders in the installed PWA with no network, and adds no request. Written down because
`<img src="https://img.shields.io/...">` is what the next person reaches for, and it would
look like a simplification.

**A badge states something knowable without a call.**

| Badge | Value | Where it comes from |
|---|---|---|
| Version | `__APP_VERSION__` | substituted by `vite.config.ts` |
| Licence | Apache 2.0 | static, links the LICENSE file |
| Source | GitHub | static, links the repository |

**Three, where the README has five.** Languages was cut because the Language card sits on the
same page and arrives open, and because "DE, EN" would have been a fourth hardcoded copy of
the locale list: a third locale would leave the badge stale with nothing failing. Docker pulls
and a latest release are absent because both need a host the CSP does not carry, and a number
typed into the source is wrong within a week and says nothing about being wrong. The README
keeps them because shields.io fetches them at render time.

**"Apache 2.0" and "GitHub" are constants, not catalogue entries.** A message key whose value
is byte identical in every language is a translation nobody can make. The labels stay
translated: "Licence" is "Lizenz", "Source" is "Quelltext".

**The chrome is neutral in both modes and only the ink carries the accent.** Two solid accent
rungs were measured and both fail in the dark: `accent-900` on the dark card is **1.01:1** on
gruvbox and `accent-950` is **1.13:1** on rosepine, so half of each link badge would disappear.
**That rejection is about solid rungs only**: the alpha tint this app already ships for a
chip on a dark surface measures 8.21 to 13.85 CIE L* of separation across the palettes.

**A link is told apart by more than its colour**, per WCAG 1.4.1. The two cells are separated
by a hairline rather than by their own difference, and a contrast ratio cannot express that,
so the test asserts the separation rather than a ratio.

It lives in the page folder rather than `src/components/`, whose bar is domain freedom.
`AboutSection.test.tsx::states the version and the source once, not twice` holds that the row
replaced the sentence rather than duplicating it.
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

### A count in a docstring is pinned by a test or it is not stated

`Loading`'s docstring justifies what `SERIALISED` carries by counting routes: 17 of the
33 reaching `book_for_read` or `book_in_trash` do not serialise the Book they read.
**That count was written wrongly five times in one day, by three parties working
independently**, and the total was never the hard part. Two review seats agreed on 17
and produced two different breakdowns of it, 14/2 and 11/5.

The rule that settles it is one sentence neither draft had: **a route that answers 204
serialises nothing, whether it hangs off a book or off a note.** The three sub-resource
deletes belong with the two book deletes, and the enrichment family has three routes of
which only `GET /{id}/enrich/candidates` fails to serialise its book. Counting families
rather than routes is what produced the 19.

So the numbers are recomputed by
`tests/test_shelf.py::TestTheRoutesThisDocstringCounts` rather than restated, in the
shape `test_the_number_in_the_docstring_is_the_number_it_costs` already uses for the
statement counts. **Each bucket is asserted separately**, because a guard on the total
alone passes when one bucket moves and another moves back, which is precisely the
difference between the two seats' splits. The first draft of the class asserted only
the sum and passed the wrong split; that is recorded here because it was written by the
seat that had just been shown the defect.

Five mutations, all caught, each recorded by the name of the test that failed
rather than by a count. One earlier mutation retyped a 204 route's return
annotation and reported **INVALID, no summary line**, because FastAPI refuses the module
at import: not caught and not survived, and worth knowing because an INVALID that is
read as SURVIVED sends the next round chasing a hole that is not there.

### A guard that enumerates its own universe goes quiet without failing

A test added to stop a docstring count going stale went stale three times itself, in one
helper, and **every one was found by an evasion attempt and none by reading**:

| What was enumerated | Found by |
|---|---|
| the **dependency** universe, a hard coded map of four alias names | a route on a fifth alias |
| the **route** universe, the router variable name | a module declaring its routes differently |
| the route's own **spelling**, matched against those alias names | a route writing the annotation another way |

**The third is the one to remember**, because by then the universe was derived and the guard
looked structural. What was still enumerated was *how a route may write the thing*, which is
open in exactly the way a list of names is.

**The fix is structural every time, never a further arm.** A guard that asks the runtime what
exists cannot be walked past by a spelling it has not met.
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

### German addresses the reader in neither register

**German makes you choose.** Informal address from an institution reads as careless; formal
address in a household reads as a bank. The catalogue had chosen informal, and that became
wrong the day library mode shipped.

**The answer is neither: 82 of 888 string values carried address, 9.2%, and were rephrased to
carry none.** The devices are ordinary German: the infinitive for an instruction, `eigen-` for
a possessive that carries weight, a plain article for one that does not, the passive and
`lässt sich`, and `wer …` for a conditional about the reader.

**Two versions of one language was built, measured and refused**, and the reason is the part
worth keeping: **no type and no test can check the half that matters.** The compiler catches a
missing key and nothing catches a register, so the second copy drifts silently.

Two strings sit outside the 82 deliberately: the published catalogue's one addressed string
was formal already and needs no variant, and the wallpaper button is the one place where the
reader addresses the app rather than the reverse.
### No bookshop or retailer is a catalogue source

Settled by the owner on 2026-08-28, while the breadth programme was choosing which
sources to probe. **Amazon, Bertrand, BOL.com, LastDodo, StripInfo, databazeknih.cz,
Biblionet.gr and Douban are excluded**, and so is anything else of that shape.

**Three independent reasons, which is the point of writing them down: losing one does not
reopen the question.**

1. **A retailer describes what it can sell**, not what was published. It is silent on
   anything out of print, which is a large part of a household shelf and most of an
   archive's.
2. **Its terms usually forbid automated access.** A household running this application
   would inherit that, without having agreed to it or being told.
3. **It has a website rather than a protocol.** A source built on one is a scraper, and it
   breaks on a layout change rather than on a version change.

**The consequence, so nobody reads a competitor's coverage as available ground.**
NeverTooManyBooks reaches Portugal through Bertrand, a bookshop. That is why its Portugal
coverage does not transfer here: Portugal still needs a real library, and the one this
project found, `z3950.porbase.org`, resolves and then times out on the TCP connect to port
210. So Portugal is a known hostname with a shut port rather than an unknown address, and
that is a row no transport work fixes.

A source that fails only the third test, a real catalogue reachable only by scraping, is
still refused, and it is refused by the same reasoning rather than by this list. The list
is examples.

## Multi workstation is joined terminals, and the container stays the documented alternative

Decided by the owner on 2026-08-28. **Shape B: the desktop app on one machine, other machines
enrol against it. Shape A, the container, is documented beside it rather than dropped.**

**This reverses a pre written refusal**, which is why it is recorded here rather than only on the
tracker. The desktop plan listed multi workstation creep among the ways the project could go
wrong, and answered it in advance: a small library with a circulation desk and three machines
will ask for shared access, and the answer is the existing container, not a desktop app learning
to be a server. The owner has since said multi workstation work is expected, so the refusal is
reversed and a shape had to be chosen rather than defaulted into.

**The question was never whether this application can serve three desks.** It already can, and
has since before any of the desktop work: the container is a server, one backend process and one
SQLite file behind many browsers, with concurrency handled at the HTTP layer and never at the
file layer. Three desks is a deployment. **The question is which artefact the archive installs.**

**What made the desktop the hard case is precise.** The single instance lock exists to stop two
desktop processes opening one SQLite file, which is the corruption case. A second workstation
running its own copy against a shared file is exactly that case over a network filesystem, which
is worse than the one the lock was written for.

**B was chosen because it is nearly built, and because two plans reached it independently.** The
phone enrolment work already specifies a device scanning a QR on an admin screen, receiving a
scoped JWT, and writing into the real catalogue. **Nothing in that mechanism cares whether the
device is a phone or a second desk.** The desktop plan and the library mode plan arrived at the
same enrolment design from opposite directions without noticing, which is the strongest argument
available that it is the right shape rather than a convenient one.

**A is documented rather than dropped because it costs nothing to keep and covers the case B does
not**: an institution that can run Docker gets the simpler answer, and B exists for the audience
that cannot, which is most of why a desktop client is being built at all. Offering both is not
indecision here; the two serve different installations.

**C stays refused**: the desktop app on every machine sharing storage, which is either two writers
on one file or a sync protocol nobody asked for. The original reason survives the reversal
intact, because it makes the desktop a worse container.

**One consequence lands immediately.** The single instance lock is written differently if a
second machine is expected to connect, and it is cheap to do now and a refactor later. The phone
enrolment tickets also stop being a phone feature and become the multi workstation mechanism,
which raises both their priority and their review bar.

## VIAF is the wrong supplier for resolution and the right one for discovery

**This is a second decision, not a correction of the first, and the earlier entry stands
unchanged.** The lobid choice recorded why VIAF was refused for resolution: it aggregates
national files rather than minting identifiers, and what this application receives is already a
GND, so reaching a fact through an aggregator that the source states directly is a round trip.
That is correct, and it is correct about **resolution**.

Discovery is the other question. Holding only a name for an author no German catalogue has
cited, the cross walk **is** the value, and no single national file provides it. The same fact
about VIAF supports both decisions because the question changed.

**What the measurement then did to the sizing, 2026-08-28.** The premise was that these
identifiers exist only for authors the GND knows. True, and the GND knows them: lobid's existing
name search found 18 of 18 Spanish, Portuguese, Brazilian, Argentine, Uruguayan and Italian
authors at rank 1, contemporary ones included, and 14 of 14 of their records carried ISNI,
LCNAF, VIAF and Wikidata in `sameAs`. The DNB catalogues foreign literature in translation, so
its authority file is not a German authors file.

So storing what already arrives is the larger half of the work and costs no request at all. What
a VIAF call adds is the national file ids `sameAs` omits, and a fallback for a GND miss that
could not be produced in eighteen attempts.

**The VIAF query shape, settled so it need not be settled again.** The index the documentation
points at is not broken; the CQL **relation** was. For `local.personalNames` and `"Borges, Jorge
Luis"`: `exact` answers 0, `all` answers 44, `=` answers 43, and `any` answers 98,581. Ranking is
the real problem: unsorted, `all` puts a Bioy Casares pseudonym first and Borges nowhere in the
top ten, while `&sortKeys=holdingscount` puts Borges first. `AutoSuggest` ranks by its own score,
put the person first in 8 of 8 names tried, carries `nametype` so work clusters are separable,
and costs 2,461 to 3,517 bytes against 1,778,760 for ten `recordSchema=VIAF` records.

**Two traps measured on 2026-08-28, both of which return a plausible answer rather than an
error.** `justlinks.json` and `viaf.json`, the classic minimal endpoints, now 404 with `"no
Route matched with those values"`, which is a **Kong gateway** message rather than VIAF's: the
service moved behind a gateway and those endpoints did not survive it. And `BriefVIAF` returns
**500 on any record containing a bare `&`**, because it breaks VIAF's own XML serialisation. That
is a property of the data rather than an outage, so retrying is useless; the bare JSON record
endpoint answers 200 for the same cluster and is the only fallback that works.

## An identifier two files disagree about is shown and never stored

`authority.cross_references` omits any scheme named in the candidate's disagreements. A
disagreement means the two files point at different records, so storing either side is resolution
by precedence, which is the one thing this feature refuses to do anywhere. The identifier is
still on the response, beside the conflict; it is not written down.

That rule is why `authority._disagreements` now compares ISNI. The earlier entry there recorded a
deliberate refusal to compare it and named its own trigger: raise it rather than adding it
quietly if ISNI ever becomes something this application cites. It is now stored, and it is the
identity spine, so the trigger fired. The full reasoning is in that function's docstring rather
than repeated here.

### VIAF was refused as a supplier and is used as an enrichment, and both are right


`docs/decisions.md` already records why lobid was chosen over VIAF: VIAF aggregates
national files and mints nothing, the identifier this app receives is already a GND, so
going through an aggregator is the indirect route to a file that can be read directly.
**That entry stands and is not corrected.** This is a second decision about a different
question.

The question it answers is not "who is this person" but "what is this person called in
Brazil". Measured 2026-08-28 over six Romance and Latin American authors: a GND record's
`sameAs` carries ISNI, LCNAF, VIAF and Wikidata and **no national library number at all**,
and the VIAF cluster it names carries BLBNB, ARBABN, BNE, PTBNP, ICCU and BNCHL. Minting
nothing of its own is exactly what makes VIAF the only place those are reachable, so the
same fact supports both decisions because the question changed.

What that buys and what it costs:

* A lookup is unchanged. `resolve` and `search` do not touch VIAF, so
  `GET /authors/authority` costs what it did.
* A confirmation is up to **eight** outbound requests across three hosts: one lobid
  record, four Wikidata (`resolve` compares `P214` and `P213` on this branch) and up to
  three VIAF. At `AUTHORITY_LIMIT`'s ten a minute that is up to eighty. Measured worst
  case 2026-08-28: 0.56s + 0.75s + 1.81s of VIAF on top of a 1.3s resolve, about 4.4s
  against a shared `DEADLINE_SECONDS` of 8.0.
* The third VIAF call is paid only on a 5xx and is nine times the bytes.

### A VIAF cluster is verified against the confirmed record, never trusted


VIAF cluster ids **split and merge**, and #87 measured one name resolving to four
clusters. So nothing here treats a cluster as an identity: what is stored as the `viaf`
scheme still comes from lobid's assertion cross checked against Wikidata's `P214`, and
VIAF's own answer is never written as one.

The cluster is usable anyway because it is checkable. A cluster's `v:sid` list names the
GND record it was built from, as `DNB|118753711`, so it is used only when it names back
the exact identifier the Member confirmed. Six of six clusters did, measured 2026-08-28.
That is the both directions property this feature already prizes for lobid and Wikidata,
applied to a third file.

Three refusals follow from it and each is the same rule rather than caution:

| Refused | Why |
|---|---|
| a cluster naming a different GND record | it is a different person, arriving with six plausible numbers |
| a cluster naming two GND records | that is the merge case, and picking one is adjudication |
| a candidate whose VIAF cluster lobid and Wikidata disagree about | asking VIAF which of the two is right is adjudication by a third party |

The last one is the existing `authority.cross_references` rule, which omits a contested
scheme, applied one level out.

**A cluster is found by name only when lobid names none**, which is 7 of 49 GND person
records sampled on 2026-08-28, one of them Italo Calvino. Even then the name is how the
question is asked and not how the answer is chosen: `AutoSuggest` returns each hit with its
own `dnb`, and the hit is selected on the confirmed GND number. `Mario Benedetti` returns
three different men, and the top ranked one is not the one a search for GND `123000327`
means.

### Storing an identifier and resolving one are different acts


`AuthorityScheme`'s docstring used to argue the six national files out: "nothing in this
app can look one up, so a member for it would be a value no reader can use". That
conflated two acts. The rule it was reaching for is that **a member has to be a value some
writer here can produce**, and these pass it: the identifier arrives free from a cluster
this app already has a reason to read.

Being able to resolve one is a later question, and it runs the other way. `acervo.bn.gov.br`
answers 403 to every agent tried and has no open Z39.50 port, and the rest wait on a Z39.50
transport this app does not have. So an adapter is blocked on a transport rather than on
this list, and the identifier stored today is what makes that adapter cheap on the day the
transport lands.

`SUDOC` is deliberately still absent though every cluster carries it: it is a French union
catalogue rather than one of the six national files that were asked for.

### The national identifiers have one route, and Wikidata is the fallback for it

**Wikidata is asked only when VIAF is unreachable.** One supplier speaks at a time, so no
disagreement arises, `AuthorIdentifier`'s report-never-adjudicate rule is untouched, and no
form normalisation is needed for the two schemes whose numbering differs. **The redundancy is
of supply, not of opinion**: the risk being covered is a gateway outage taking the feature
down. The precedent is in the same module, where VIAF's bare record call is a fallback on a 5xx
rather than a second opinion.

**If Wikidata is ever promoted from fallback to comparator, BNE and BNCHL become contested and
stop being stored**, which is a coverage regression rather than a stricter check. That is the
measurement to read before proposing it: a cross walk read through a single supplier is one
assertion, and two suppliers disagreeing about a national number is not evidence that either
is wrong.
### A refusal test whose subject is a plausible future member is a countdown


`test_a_scheme_no_authority_file_is_read_for_is_refused` existed in three places and went
vacuous twice in one day: its value was `viaf` until `viaf` became a member, then `blbnb`
until `blbnb` became one. Both times it kept passing right up to the commit that made its
subject legal, then failed loudly, which is the good outcome and an expensive way to learn
it.

The three now use `ddc`, a `ClassificationScheme` member, because a shelf notation will
never be a person's identifier: that is a design decision both enums' docstrings state
rather than a fact about today's supply.

**And the first attempt at the guard behind it was wrong, which is why it is worth
having.** It asserted the two enums share no value; the suite refused it. They share `gnd`,
deliberately, because the Gemeinsame Normdatei is one file covering both subjects and
people and the DNB writes both in the same MARC `$0`. What the two enums keep apart is the
column, not the spelling. The test now pins the overlap as exactly `{"gnd"}`, which also
catches `gnd` being dropped from either side.

---

### The in app reminder is a sender, and it is the one that does not stamp `notified_at`


Every other sender pushes: a webhook the household runs, an SMTP account, a Telegram bot.
The in app notice is read rather than sent, and `notifications.pushes_outward` is where that
difference is decided, exhaustively, with an `assert_never` tail.

It matters because of the stamp. `notified_at` records that a reminder went **out** and
`due_for_reminder` reads it, so counting a channel that delivers nothing would stamp every
overdue loan on every run and then select nothing until the interval expired. Measured
against the shipped default of seven days: a broken mail server would be attempted **once a
week instead of once an hour**, from a channel that is on by default. That is one sample a
week for the failure window the health record is built on.

So the stamp condition is "at least one sender that **pushes** delivered", and the rule the
webhook decision recorded is otherwise unchanged: stamping on any success is deliberate, and
the alternative repeats an identical list hourly on the channels that work.

### A sender includes exactly what its audience may see


The three channels that push go to a mailbox or a chat with no member behind them, so they
exclude every private book and report a count instead. That is unchanged.

The in app channel has a **viewer**, so it carries what `visible_to()` already says that
viewer may see, their own private books included. Being told about your own book is not a
disclosure. This is the rule rather than an exception to it, and it is why
`notifications.overdue_for_viewer` is rooted at `Shelf.seen_by` while the digest beside it is
not: the digest has no viewer and is exempt for that reason, and the exemption is the
digest's rather than the module's.

Two audiences, decided in one place, `notifications.sees_every_loan`. A member reads the
loans they borrowed or lent; staff read every overdue loan on their shelf. That is the seam
library mode widens, and it now does: with library mode on, every member reads every
overdue loan on their shelf. What it must not become is "an admin sees all": an admin is
not a superuser over another member's private books anywhere else in this app, and all
three arms go through the Shelf before any clause is added.

### A new endpoint is classified for cache invalidation, or the inventory guard fails


Not a new decision, an existing one meeting its second case. `tests/api/invalidate.test.ts`
walks every query key the generated client can build and fails on one nothing has placed,
which is how `authorAuthority` was caught and is how the in app overdue count and the sender
health record were caught here.

The placements: the overdue count is **catalogue**, because it is a count over loans and
books and it is drawn above the library grid; the health record is **left alone**, with the
settings, because it measures the channels rather than anything derived from the books
table.

### One failed send is a network. Every send failing for a day is a configuration


`ticker()` discarded `run_digest`'s result, so a channel failing hourly existed only as a
warning in the container log. `docs/security.md` recorded that under Known gaps, and the
disposition was wrong: for a household running the published image, "read the container log"
is not a worse form of alerting, it is the absence of one.

The run now records the last outcome per sender into one settings row, `SENDER_HEALTH`. Not
a table: a table needs a migration, a retention rule and a `backup._TABLES` entry, and what
is wanted is one record per sender rather than a history. `settings` is already backed up.

The recording is in `run_digest` rather than in `ticker()`, which is where the symptom was,
because `POST /api/loans/overdue/notify` runs the same pass and had the same defect. It is
the run that "races the ticker" in the ticket's own words, and with the write in one caller a
household pressing "Send now" would leave the panel describing an older run.

**When a channel counts as broken** is the judgement, and it is two rules rather than one
threshold, because the two kinds of failure carry different evidence.

A **refusal** counts at once. `NO_URL` and `MISCONFIGURED` come out of `_REFUSALS`, and all
three of those are raised before a socket is opened: `checked_url` is string handling,
`send_telegram` matches both regexes before `_post`, and `mailer.checked_config` raises at
`mailer.py:109` to `162` while the socket is opened at `mailer.py:230`. Nothing was dialled,
so there is no outage to wait out.

A **transport failure** counts only after `BROKEN_AFTER_HOURS`, 24, **and** at least two
consecutive failures. Both, and the second clause is the one that is easy to leave out: a
working webhook beside a broken mail server stamps `notified_at`, so mail is attempted once
per reminder interval rather than once an hour, and its single failure would otherwise cross
the window having failed exactly once, which is the network event the bar exists to ignore.

24 hours is deliberately not `overdue_reminder_days`. That interval says how often a loan is
chased; this says how long a channel may be broken before somebody is interrupted on a
screen they did not go looking at. A household may set the first to 24 hours without meaning
anything by it, so the two are named separately and a test asserts `_is_broken` does not read
the setting.

---

### YAZ is compiled, not packaged, and the image stays Alpine


Alpine has no `yaz` and no `yaz-dev`, in `main`, `community` or `testing`, on
`edge`, `v3.24`, `v3.22` or `v3.21`. So a Z39.50 client is either compiled or the
base image changes, and the base image is the expensive half: `python:3.14.7-slim`
is **41.4 MB compressed** against alpine's **16.9 MB**, so a packaged `libyaz5`
costs 24.5 MB before YAZ is installed, and buys a larger Debian userland to scan
against a release gate that refuses a fixable HIGH.

Compiling costs a minute, once, and needs no patches against musl.

**A pure Python reimplementation was refused by the owner**, 2026-08-28: "I
definitely do not want to own a protocol reimplementation in Python." The
hand written `InitRequest` in the survey tool stays a survey tool, and the
`SearchRequest` that every target rejected is the evidence for the refusal:
encoding BER by hand reached Init and no further.

**What the runtime image pays**, measured on the pinned base by `du -sk /` before
and after, Alpine 3.24.1:

| | |
|---|---|
| `libxml2`, `libxslt` | 1,384 KiB |
| `gnutls` and the seven packages behind it | 7,704 KiB |
| the stripped `/opt/yaz`: `libyaz.so.5` and `yaz-client` | 1,848 KiB |
| | **10,936 KiB** |

That is **2.7x the 3,359 KiB first estimated**, packages against packages, and the
reason is that the estimate counted three packages where apk installs **ten**. `gnutls` alone is 85% of the
package cost and 70% of the 10,932 KiB total and buys Z39.50 over TLS, which no target surveyed uses.
`--without-gnutls` is the first of **two** edits that would remove all eight: the
recipe stops libyaz linking gnutls, and the packages leave the image only when
`gnutls` also comes off the Dockerfile's runtime `apk add`.

**The owner decided to keep it, 2026-08-28, against the recommendation to drop it, and
the condition was that the cost is recorded rather than paid silently.** That is what
the paragraph below is for. Removing it later is the two edits above, and it is cheap
to reverse: the recipe change moves the build id, hence the tag.

**And the size is not the cost.** The three libraries and their dependants carry **94
distinct CVE ids** in Alpine's security database: 52 against the gnutls group, gnutls
alone 36, and 42 against libxml2 and libxslt. They land on the release scan that
refuses a fixable HIGH.

**All three are equally optional to the build**, and an earlier draft of this said
otherwise: YAZ offers `--with-xml2` and `--with-xslt` beside `--with-gnutls`. So the
52 is the price of TLS against a **judgement about record handling**, not against a
build constraint: catalogue records are parsed and converted through libxml2 and
libxslt, so dropping those costs a feature, while dropping gnutls costs an encrypted
transport no surveyed target offers.

`libyaz.so.5.3.0` strips from 5,168,584 to **1,753,232 bytes**, a 66.1% cut. The
filename is the library revision, not the release number, which is why an
earlier strip aimed at `libyaz.so.5.35.1` silently found nothing, and the soname moved
again from 5.1.1 to 5.3.0 when YAZ went to 5.37.3, so the strip list is globbed.

### The YAZ builder image is named after what it is built from


The compile is skipped by handing the build stage a prebuilt image instead of the
plain base. It is tagged `<yaz version>-<base digest>-<recipe hash>` and built only
when nothing in the registry carries that name, so **the rebuild check and the
artefact's name are the same string**.

**Not a layer cache, and the reason is specific.** `--cache-ttl` expires on a
clock, not on a fact. This repository already learned that the other way round,
from a cached `apk upgrade` layer that re-pinned the patch level, which is why
`--cache-ttl=6h` sits on both build jobs. At six hours a layer cache would
recompile YAZ four times a day for nothing **and still hand a build a YAZ linked
against the previous musl the moment the base image moved.** A tag naming both
inverts both failures.

**The third tag component is an addition to what was settled**, which named the
version and the digest. It is the sha256 of the recipe, and it is there because
those two do not determine the artefact: the configure flags, the strip list and
the runtime subset can all move under a fixed pair. It costs one line to drop,
because correctness does not live in the tag: the recipe stamps its own build id
into the tree and recompiles in place when it does not recognise it. Removing the
component makes builds slower and never wrong.

**The parameter is the base of the YAZ stage, not the source of a `COPY`.** That
is the reverse of the obvious shape and it is forced by the builder. Measured
against kaniko v1.28.3, 2026-08-28: `COPY --from=${ARG}` fails outright with
`could not parse reference: ${ARG}`, while `FROM ${ARG}` resolves and
`--build-arg` overrides it.

### The runtime `COPY` shipped with the builder image, not with the transport


Nothing calls YAZ until the Z39.50 transport lands, so the image carries about
11 MB it does not yet use. Shipping it now was chosen deliberately, over three
alternatives, and the reason is verification rather than convenience.

**A builder image nothing consumes is never verified.** The failure the whole
design exists to prevent is a base image bump that keeps a YAZ compiled against
the previous musl, and that is only detectable when something actually loads the
library. The release smoke test now runs `yaz-client -V` inside the shipped image
and compares it to the version pinned in the Dockerfile, which also catches a
missing runtime package and a tree copied to a path other than `/opt/yaz`. None of
those fail the build; all three fail there.

Two consequences worth stating rather than discovering. The image scan now covers
`gnutls` from today rather than from the day the transport wants to ship, which is
when a blocking HIGH would be most expensive. And shipping now forecloses nothing:
`--without-gnutls` changes the recipe, which changes the build id and the tag, and
the next build rebuilds on its own.

---

### The YAZ build id names what is built, never what it is built against


Three components: the version, the sha256 of the tarball, the sha256 of the recipe. The
environment is deliberately absent, and it was briefly present.

**A musl term was wrong in three ways at once.** It had to be read before the compiler was
installed, and `apk add build-base` moves musl whenever the repository is ahead of the
pinned digest, because `musl-dev` depends on an exact musl version (`D:musl=1.2.6-r2` in
the v3.24 index). It said nothing about libxml2, libxslt or gnutls, which libyaz also
links. And it was too strict: **a YAZ compiled on Alpine 3.24.1 against `musl-1.2.6-r2`
loads and runs clean on Alpine 3.21.7 against `musl-1.2.5-r11`**, three Alpine releases
apart, with `LD_BIND_NOW` set so nothing is deferred to first call.

**That is one ordered pair, and which pair it is matters.** It runs a newly built binary
against an older libc, the harder direction, since symbols a new build expects need not
exist in an old library. The scenario the musl term was for is the other way round, so
this result covers it a fortiori.

At the strength the evidence carries: on one pair three releases apart, in the harder
direction, a base image bump that keeps a YAZ built against the previous musl is not a
breakage. A strong directional result, not a proof about every pair. **The design does not
rest on it either way**: where the ABI is compatible there is nothing to detect, and where
it is not, the load check detects it. So what the tag and the id are worth is that the
artefact is reproducible and attributable, and that the compile is paid once, rather than
that they avert a breakage nobody has yet produced. An earlier draft of this entry said
"nothing detects it because there is nothing to detect", which was false in the second half
of that sentence and contradicted the paragraph after it.

The environment is instead checked by running the library in the runtime stage under
`LD_BIND_NOW`, which covers musl, all three shared libraries and the install prefix at
once.

### The YAZ pin is trust on first use, and nothing else watches it


`ARG YAZ_SHA256` pins the tarball by content, and nothing corroborates it. IndexData
publish no signature and no checksum file beside the release: `.sig`, `.asc`,
`SHA256SUMS`, `CHECKSUMS`, `sha256sums.txt` and `MD5SUMS` all 404 under the release
directory, checked 2026-08-28. Re-fetching only proves upstream has not changed since.
The pin is still worth having: it pins the artefact against a later substitution, which
is the threat it can address.

**And no scanner sees the library.** Trivy's C and C++ analyzer reads `conan.lock` only
and is not applied in a container image or rootfs context, so `/opt/yaz/lib/libyaz.so.5`
is enumerated by nothing in `scan:image` or `verify:image`. NVD returns no results for
this version, so this is a monitoring gap rather than a shipped vulnerability, and it
would have been permanent. A Renovate custom manager now raises the version from
`indexdata/yaz`'s git tags. It is deliberately not automerged: Renovate cannot know the
new hash, so the merge request is expected to be red at `sha256sum -c` until a person
supplies it, and that failure is the design rather than a defect.

### YAZ encrypts a TLS connection and does not authenticate it


YAZ performs no certificate verification in any released version. `verify_peers`,
`set_x509_system_trust`, `session_set_verify_cert`, `set_x509_trust_file` and
`GNUTLS_CERT` appear nowhere in `src/` or `client/`, checked on 5.35.1 and 5.37.3;
`src/tcpip.c` allocates certificate credentials and calls `gnutls_init(GNUTLS_CLIENT)`
without ever loading a trust store. So an `ssl:` target is protected against a passive
listener and not against anyone who can answer for the address. Recorded rather than
acted on: no target this application reaches uses TLS, and whether to keep gnutls at all
is the owner's call.

### A suite pod must not outlive the run that made it


The suite runner deleted its pod from a `trap ... EXIT INT TERM`, which covers every
way the script can end except the one that happens: a tool timeout SIGKILLs the parent
and no handler runs. Measured 2026-08-28: SIGTERM runs the trap, SIGKILL does not.

The cost is the resource request rather than the leftover object. A leaked pod stays
Running for an hour holding 500m of CPU and 512Mi on a four core node that three seats
share, so the next run goes Pending and reads as a hang: one battery waited **17
minutes**, and the same run took **14s** once the orphan was deleted by hand.

A trap cannot be made to cover SIGKILL, so the recovery is at the start of the next run.
A reaper deletes a labelled pod in Succeeded or Failed, which is finished
whoever made it, and a Running pod whose creating process is gone, which each run records
as `<pid> <pod>` before it waits for readiness.

**Neither arm uses an age threshold**, and that is the design rather than an omission: a
threshold would have to exceed the backend suite's 23 minutes, so it would arrive long
after the starvation it exists to prevent, and it would still race a concurrent seat. A
`kill -0` on a recorded pid is exact.

### The suite pod registry is untrusted, and what that bought is a bound rather than safety


`~/.cache/endpaper-ci-pods` is a plain file any process running as this user can append
to, another agent seat included, and the kubeconfig can delete pods in every namespace.
The first version put the registry's pod name straight into `kubectl delete pod`, so a
line could name a real workload **and** be read as flags: `--all` produced
`kubectl delete pod --all`, which empties the namespace.

Three constraints replace the delete-by-name path: the name must match the one shape the
runner creates, every call carries both the namespace and the label, and the name is a
field-selector value rather than a positional. A fourth rule refuses to delete any pod
another registry line claims with a living process, which is what stops a forged line
naming a concurrent seat's live pod.

Two things make that fourth rule work and neither is obvious. **The registry is read once
and both passes use that snapshot**, so everything the deleting pass acts on was seen by
the claiming pass; re-reading the file in the second pass is valid shell, passes every
test, and deletes a pod a living process claims. And **the runner writes its line before
it creates the pod**, because registering afterwards left a window on every single run in
which the pod existed and nothing claimed it. A line naming a pod that does not exist yet
is inert, which is what makes the earlier write safe rather than merely earlier.

**What that delivers is a bounded blast radius, not harmlessness**, and saying so is the
point of this entry. A forged line naming a pod of ours whose owner never registered, or
whose line was already removed, still deletes it. Closing that needs the pod UID recorded
at creation and compared before deletion, which reintroduces a check-then-act window and
is more than a small change. It is recorded here rather than done.

### A member's address is served only where it is named, and never on `UserOut`

`users.email` arrived with issue #80. The owner settled three things: an admin may read and
write any address, a member may read and write their own where the mode allows, and it is
used and shown nowhere else.

The last of those is the one that needed a mechanism rather than an intention. `UserOut` is
served inside every book payload and by the member list, so a field added there is disclosed
to every member who can see a book, with a 200 and nothing in any log. That is the same trap
the three `appearance_*` columns were kept out of, and it was kept out by a comment.

So the address is served by `MemberEmailOut` on four routes and nowhere else, and
`tests/test_house_rules.py::TestAnAddressIsServedOnlyWhereItIsNamed` fails if **any** other
Pydantic model this app builds puts an address in front of a caller, or if any module
outside `auth_backends.py` and `routers/users.py` reads `.email` off anything.

**The first version of that guard was wrong and the way it was wrong is the reason to keep
this entry.** It tested `"email" in model_fields`, which is the field's Python name, and a
reviewer got two evasions past it in one sitting: a `serialization_alias="email"` on
`UserOut`, which `from_attributes` fills from `User.email` and FastAPI serialises
`by_alias=True`; and a model with a `MemberEmailOut` field, which carries the whole address
model and has no address field of its own. Neither reads `.email` anywhere, so the reader
pass stayed clean too.

The fix is not two more arms. The pass asks **pydantic** for each model's wire names
(`model_json_schema`, both modes), which is the question FastAPI asks it and covers every
alias spelling without naming one, and takes a **fixed point** over field annotations, so a
wrapper around a wrapper is caught. Fifteen evasions were attempted and all fifteen caught.
The blind spots it still has, an address under a different wire name and a hand built dict,
are stated in its docstring rather than left to be found.

### Who owns a member's address is a configuration lookup, not a column

Two of the owner's decisions read as a conflict: the directory is authoritative under LDAP
and PROXY, and an admin may write any address. Together they would let an admin type an
address the next sign in silently reverts.

They are not a conflict, and the precedent that settles it is the one decision A already
names. `auth_backends._admin_group_set` says that with no admin group configured `is_admin`
is False because **the app has no opinion, and that must not be read as one**, so
`upsert_directory_user` refuses to demote on it.

`LDAP_EMAIL_ATTRIBUTE` and `PROXY_EMAIL_HEADER` copy that exactly, and both default to
empty:

* Configured, the directory owns the address. It is re-applied at every sign in, an entry
  with no address clears the column (the demotion case unchanged), and the field is read
  only for everybody, an admin included.
* Unset, the directory has no opinion. The attribute is not requested, the header is not
  read, and a locally typed address is never touched.

So an admin may write any address wherever anything is his to write, and the one case where
his write would be reverted is exactly the case where nobody may write. There is no second
column recording which applies: `auth_backends.directory_owns_email` is the one reader of
the answer, and a column would be a cached copy of a config lookup.

A write refused this way is **409, not 403**. Nothing about the caller's rights is wrong,
and a 403 would send an admin looking for a permission to grant themselves that does not
exist. The detail names the variable to clear, because the remedy is a deployment change.

**The clearing is not symmetric with the demotion it copies, and that is the cost of the
precedent.** A wrongly demoted member is restored by putting them back in the admin group. A
cleared address is gone: the value is kept nowhere and the field is read only from the moment
the attribute is configured, so neither the member nor an admin can type it back. Turning
`LDAP_EMAIL_ATTRIBUTE` on therefore empties the stored address of every member the directory
has none for. `.env.example`, `README.md`, `DOCKERHUB.md` and `upsert_directory_user` all say
so, because the person who turns it on is the one who needs to know.

**A refused value is a different event from an absent one**, and both clear the column. A
`Remote-Email` carrying a newline is the injection shape, on the same request whose
`Remote-User` a refusal already logs at WARNING with the peer, so it is logged the same way:
the length and never the value. The LDAP path logs the attribute instead, there being no
peer. `_address_was_refused` defines "refused" once so the two cannot drift.

### A guard is one mechanism, because two mechanisms have a seam

`TestAnAddressIsServedOnlyWhereItIsNamed` took **three** versions, and the second is the one
worth recording, because it was not obviously wrong.

Version one tested `"email" in model_fields`, the Python name. A reviewer walked past it
with a `serialization_alias` and with a model that nested `MemberEmailOut`.

Version two fixed both, with **two** mechanisms: the wire names from `model_json_schema`,
plus a fixed point over Python annotations for the nesting. A reviewer then walked through
the **seam between them**. A `@computed_field` returning `MemberEmailOut` is in the
serialization schema and absent from `model_fields`, so `model_dump()` returned
`{'id': 0, 'person': {..., 'email': ...}}` while the guard saw a model whose only field was
`id`.

Version three is a **net deletion**. `model_json_schema` already inlines every referenced
model into one flattened top level `$defs`, measured to reach a model nested two deep, so
one walk over the schema document, reporting any object node whose `properties` names
`email`, covers naming, every alias spelling, an `alias_generator`, nesting at any depth,
list and dict positions, and computed fields. `_wire_names`, `_referenced`, the fixed point
and the class-to-name map are gone.

Measured over the whole app: 87 models, carriers exactly `['EmailUpdate', 'MemberEmailOut']`,
0 unreadable, which is the pair `openapi.json` independently gives. 21 evasions attempted,
21 caught.

**The general lesson, and it is the one that generalises past this feature: where two
mechanisms meet, that is where the hole is.** The fix to an enumerating guard is structural,
and when it is the right fix it deletes code.

### One definition of what an address is, and it has to hold without its callers

`mailer.looks_like_address` and `mailer.MAX_ADDRESS` are now the single rule, used by the
household recipient list, the sender address, the schema behind `users.email`, and the
directory values `auth_backends` accepts. A second regex would have been a second answer.

**Making it the single rule is also what exposed that it was not a rule.** It was
`re.compile(r"^...$").match`, and `$` matches before a trailing newline, so
`"kim@example.org\n"` passed the header injection control while three docstrings and
`docs/security.md` said it could not. Its character class excluded whitespace and five
punctuation characters, so a NUL or an ESC passed too. Nothing was exploitable: four
independent `.strip()` calls, in `_addresses`, `checked_config`, `EmailUpdate` and
`_directory_email`, stood in front of it. **A control that holds only because of its
callers is not a control**, and no fixture at any layer used the shape it actually
permitted, because every injection fixture put the newline in the middle where the
character class rejects it anyway.

Two structural fixes rather than two more characters: `fullmatch`, and a refusal of any
character whose Unicode general category begins `C`. `TestWhatCountsAsAnAddress` tests the
function with none of the four callers in front of it, which is the whole point of it.

What is **not** a refusal, and the distinction cost a fixture: a value that trimming makes
valid, such as a directory attribute with a stray trailing newline, is stored trimmed. The
property that matters is what reaches the column.

`schemas.settings.MAX_MAIL_ADDRESS` is the same number for the household field and predates
this. Folding the two is one line and was deliberately not done while another seat was in
that file. `models.User.email` keeps `String(320)` as a literal because importing the
constant is an import cycle; a test ties the three together.

---

### The public shelf has no ownership arm, rather than a sentinel viewer

`visible_to(user_id: int)` takes a non optional int and a public reader has no
id. Three shapes were available and two were refused, 2026-08-28.

A **sentinel id** (`0`, `-1`) was refused because `Book.added_by_user_id == 0` is
a real comparison against a real column: it is safe only while no account holds
that id, which nothing enforces, and the leak would be silent and answer 200.
A **nullable parameter** on `visible_to` was refused because it loosens the type
at every call site to serve one caller, and a `None` arriving by accident becomes
a silent mode change.

`Shelf.seen_by_the_public(db)` applies `deleted_at IS NULL` and `is_private IS
false` and **no ownership arm at all**. It is safe by construction rather than
by invariant: there is no value any input can take that makes a private book
match, because the clause that could match one is not in the query. It fails
safe in the other direction too, since an authenticated request wrongly routed
through it sees less rather than more. It goes through the Shelf, so
`TestTheShelfIsTheOnlyWayIn` keeps holding with no exemption.

`Shelf._viewer_id` widened to `int | None` and nothing else did: `seen_by` and
`trashed_by` still take a plain `int`. The three per member narrowings read a
`_viewer` property that **raises** rather than returning None, because the
silent version is wrong rather than empty: `UserBook.user_id == None` compiles to
`IS NULL`, the outer join in `_with_read_status` then matches nothing, and
`status=unread`, whose branch also accepts a missing row, returns the whole
public catalogue.

### Publishing takes two switches, and the conjunction is on the server

Library mode and the public catalogue are separate, because a library running
library mode internally without publishing is the common case rather than an
edge one, and one switch would force an institution to put its catalogue on the
internet to get the cataloguer's columns. It also gives "hard to trip by
accident" a structural meaning rather than a UI one.

`settings_store.public_catalogue_is_published` reads both rows, and the routes
ask it rather than reading a row, so a publish row left on while library mode is
off serves nothing. **The write refuses nothing**: an admin may store
`public_catalogue_enabled` while library mode is off. Refusing the write would
make the order two toggles are saved in matter, and would lose an admin's stated
intent the moment they turned library mode off to look at something.

### The public payload is a separate model, not `BookOut` with an exclusion list

A row filter is necessary and not sufficient. A public book still carries what
the household paid for it, which room it is in, who added it and whether
anybody has read it, and `seen_by_the_public` filters rows rather than columns.

`schemas/public.py` declares its own fields. The difference from an exclusion
list is which way the default falls: an exclusion list publishes every field
somebody forgets to add to it, and a field is added to `BookOut` about twice a
release. The cost is that a genuinely public new field is added in two places.

The rule that decides each field: **public when it is a fact about the work or
about the object as a catalogue record, withheld when it is a fact about a
member, the household, or the transaction.**
`tests/schemas/test_public.py::TestEveryFieldOnBookOutIsClassified` asserts the
partition is **total**, so a new field on `BookOut` fails until a person
classifies it. It is not a list of forbidden names, which is an enumeration over
something open.

Three placements are worth their sentence:

* **`location` is withheld** although in library mode it is the shelf mark a
  patron needs. The column is shared with household mode, where it holds
  "bedroom", and the publish switch does not change what is in it. A shelf mark
  for patrons wants its own field.
* **`copy_count` is withheld** because it cannot be computed here: it counts the
  copies *the caller may see*, and there is no caller.
* **A locally uploaded `cover_url` is dropped**, keeping only an https URL a
  metadata source supplied. `/covers/<id>` is served behind `book_for_read`, so
  publishing that path would advertise an image a public reader cannot fetch,
  and serving those bytes publicly is a new file route with its own
  authorization rather than a column decision. The published catalogue therefore
  shows a cover where a metadata source supplied one and none where a member
  uploaded one.

### The `X-Robots-Tag` belongs in the middleware, not on the routes

It was set from `public_reader` for a round and was wrong twice over. A header
set from a route dependency merges onto the **success path only**: measured, it
was on the 200 and absent from the gate's 404, the item 404, a 429 and a 500,
while `routers/public.py` and `docs/security.md` both said every public response
carried it. And a dependency cannot reach the `StaticFiles` mount, so the HTML a
crawler actually indexes never had it at all, which is the case the header
exists for.

`SecurityHeadersMiddleware` now sets `noindex, nofollow` on **every** response
and the published catalogue paths lift it. That direction fails safe, and it
makes the signed in application noindex too, which it always should have been.

`robots.txt` allows `/catalogue`, the client route, not `/api/public/`. The first
version allowed the JSON prefix, so a library that switched indexing on invited a
crawler to the one path with nothing readable at it and barred the two the
catalogue is read at.

### The public listing takes a subset of the filters, and a subset of the sorts

`status`, `unrated` and `discuss` are absent because the public shelf has no
viewer to read them against; `ownership` and `lending` because they are columns
the payload does not carry, and a filter over a column nobody can see is a way to
read that column one query at a time.

**`collection_id` was accepted in the first draft and was cut.** The ids are
consecutive, so the filter is enumerable, and what it enumerates is the
household's own grouping of its shelves, which `PublicBookOut` withholds. A
public way to link to one shelf wants a published name to link by.

**`sort` is `PublicBookSort`, a declared subset of `BookSort`.** An ordering is a
read of the column it orders by, and unlike a filter it returns the **whole**
ordering in one request: `BookSort.NEWEST` orders by `added_at`, which says when
this household acquired each book.
`tests/schemas/test_public.py::TestEveryPublicSortOrdersByAPublishedColumn`
compiles the clauses `order_for` produces and fails on any column
`PublicBookOut` does not carry, so a sort added to the subset is checked against
the model rather than by eye.

### The published `id` is the insert order, and that disclosure is accepted

**Recorded rather than buried, and it weakens a claim made elsewhere in this
change.** `order_for` appends `Book.id.asc()` to every ordering, and `id` is on
the public payload, so the catalogue comes back in **acquisition order with no
`sort` parameter at all**. Worse, `max(id)` against the number of rows returned
gives the count of rows the shelf withheld: measured on ten rows, three private
and one trashed, `max(id) - count` is exactly 4. So a stranger can learn how
many books a library holds privately, though not which or what.

It is accepted rather than fixed. The id is the URL a record is read at, and an
opaque public id is a schema change, a URL change and a migration: its own
ticket, not a column decision inside this one.

**The consequence for `PublicBookSort` is stated rather than left implied.**
Excluding `newest` was argued as withholding the acquisition order; it withholds
the `added_at` **column** and not the order, which `id` already gives. The subset
is still right, and the reason is the next member rather than this one: a
`BookSort` over a price, a condition or a location would be publicly sortable the
day it was added, and a sort returns the whole ordering of its column in one
request.

### `noindex` by default, because publishing and being crawled are two decisions

A published catalogue sends `X-Robots-Tag: noindex, nofollow` and `/robots.txt`
disallows everything until indexing is separately allowed. With it allowed,
`robots.txt` allows the catalogue paths and nothing else: a bare `Allow: /`
would invite a crawler into the signed in application, where every path answers
401.

---

### What "unreachable" was implemented as, and the two cases it deliberately excludes

**The fallback fires when VIAF produced no cluster record.** Not when VIAF produced no
national numbers, which is a different and wider rule:

| What happened | Wikidata asked |
|---|---|
| the request never got a status: timeout, DNS, refused | yes |
| a 403, a gateway 404, a 5xx whose bare record also failed | yes |
| a 200 carrying HTML rather than JSON | yes |
| a body that parsed and held no `VIAFCluster` | yes |
| `AutoSuggest` answered and matched no hit, or matched two | **no** |
| a cluster came back and named a different GND record | **no** |
| a cluster came back carrying none of the six | **no** |

**The line is supply, not coverage.** The bottom three are VIAF answering, and two of them
are answers `national_identifiers` refuses on a rule of its own: a cluster naming a
different GND record is the wrong person, and two clusters under one GND number is an
ambiguity nothing here is entitled to settle. Asking a second file to overrule a refusal
is adjudication, which is the one thing this feature refuses to do anywhere.

The bottom row is the one that costs coverage: a cluster carrying none of the six leaves
the six unstored even where Wikidata has them. That is deliberate. Widening the trigger to
"VIAF supplied nothing" would let the two suppliers fill different halves of one person's
row, which is the merge the decision above rules out.

**`AutoSuggest` answering and matching nothing is the case that cannot be read off a
return value**, because "VIAF is down" and "VIAF knows nobody by that name" are the same
absent cluster. `authority._viaf_cluster_by_gnd` returns a pair for that reason alone, and
`tests/test_authority.py` pins both sides of it as a diagonal.

### What the fallback refuses to store, and why it is not `_claim`

`_claim` returns a property's **first** value, which is right for the comparison it was
written for and wrong for a write. Measured 2026-08-28 through the Wikidata query service,
humans (`P31=Q5`) carrying more than one truthy value:

| Scheme | Property | Humans with more than one | Humans with the property |
|---|---|---|---|
| BNE | P950 | 4,955 | 235,481 |
| ICCU | P396 | 3,270 | (the count query timed out) |
| PTBNP | P1005 | 899 | (the count query timed out) |
| ARBABN | P3788 | 156 | 8,645 |
| BLBNB | P4619 | 72 | 24,420 |
| BNCHL | P1890 | 44 | 4,081 |

`Q5682`, Cervantes, carries **eight** `P3788` values, all at rank `normal`. So taking the
first would be resolution by ordering for nine thousand people. `authority._claims` reads
every value and the fallback drops a property that has more than one, which is
`_viaf_sources`' rule for a code a cluster names twice, one file over. A `deprecated`
statement is skipped, because that rank is Wikidata saying the value is known wrong.

### The budget moved and the statement moved with it

A confirmation is now up to **fourteen** outbound requests across three hosts rather than
eight: eight on the path that works, and six Wikidata `wbgetclaims` **instead of** the
three VIAF calls rather than beside them. Measured 2026-08-28, the six for `Q1512` are
1,942 bytes and 1.49 seconds together, against the 1,061,272 bytes the three VIAF calls
reach at their worst. `authority.DEADLINE_SECONDS` stays at 8.0 and its comment now says
why the fallback does not move the worst case.

They are asked one at a time. Wikidata answers **429** to a burst: roughly fifty
`wbgetclaims` from one address inside two minutes, measured 2026-08-28, and it kept
answering it for minutes afterwards.

---

### The author card links out to Wikipedia, and the language is resolved rather than guessed

**Settled by the owner 2026-08-28: link out, not fetch.** The refusal of author biographies
and portraits in `docs/featurelist.md` stands untouched. What is read is which language
editions hold an article, which is data about availability; an article's prose is the thing
the refusal exists to prevent. `authority.WikipediaArticle` carries a URL and a language
code and a test asserts it carries nothing else.

**`Special:GoToLinkedPage` was the obvious mechanism and is refused, on a measurement.** It
resolves server side from a Q id and a site code, so it needs no stored URL and cannot go
stale. Measured 2026-08-28, its failure mode is the problem: a site with no article answers
**200 with a 39,003 byte Wikidata maintenance form**, not a 404, so nothing downstream can
tell success from failure and the reader lands on an edit form. Sampled over 300 people
carrying a GND number and the writer occupation, 259 of the 297 with any article have a
`dewiki` one, so **12.8% of German readers** would have hit that form.

**The language therefore has to be known before the link is rendered, and it cannot be a
redirect endpoint.** Every request to this API carries a bearer token and a plain
`<a href>` cannot, which is the same constraint `mutator.downloadFile` records. So it is a
data endpoint, `GET /books/authors/wikipedia`, and a hook.

**The fallback chain ends at the Wikidata item and never at nothing.** The alternative
measured against it, falling back to `Special:GoToLinkedPage/enwiki`, would have worked for
97.3% of the sample and dropped the rest on the form. A link that is right every time and
sometimes points at a data page beats one that is right 97.3% of the time and fails
invisibly.

**The one URL this app takes out of a response, and why that is safe.** Everywhere else in
`authority.py` the rule is three fixed hosts and a cross reference is shown but never
fetched. `_WIKIPEDIA_ARTICLE` matches the API's own `url` against an anchored pattern whose
host half is written here, `wikipedia.org`, with only the language subdomain from the
response and bounded to `[a-z0-9-]{2,32}`. Building the URL from the site code instead was
refused on a measurement: `Q1512` carries 153 sitelinks, **101** ending in `wiki`, of which
exactly one is not Wikipedia (`commonswiki`, at `commons.wikimedia.org`), so a code to host
rule needs a denylist plus a transliteration for `zh_yuewiki` and `bat_smgwiki`. Nothing
fetches the URL: **Wikipedia is not an outbound host of this app.**

**The budget guard was widened deliberately and this is the record.**
`test_wikidata_is_never_asked_for_every_claim`'s allowlist held `labels|descriptions` alone
and now holds `sitelinks/urls`. That test is the budget and refuses `claims` by name, which
is still refused; the refusal is the three tests above it, and none is touched.
`sitelinks/urls` for `Q1512` is **354 bytes** with a `sitefilter` against 243,864 for
`claims`.


---

### The Z39.50 transport is a seam, and the client behind it is not chosen yet

`backend/z3950.py` is a second door beside `fetch.py`, not an extension of it: two of
`fetch.py`'s four bounds have no equivalent here, because the protocol has no redirects and no
content encoding, and the other two had to be built rather than imported.

**What the seam owes a caller is that the bounds arrive by construction**, so no call site has
to remember to ask.

| Bound | How |
|---|---|
| At most `MAX_RESPONSE_BYTES`, 2,097,152, the same figure `fetch.py` uses | counted on record bytes |
| At most `MAX_RECORDS`, 5 | the search returns a count and records are asked for by position |
| One absolute deadline for the open, every search and every record | `Association` holds the clock |
| A member's term cannot change the query's shape | `z3950.query` quotes and escapes it |

**The client is behind a `Session` and `Client` protocol and is not the decision.** The one
that exists is provisional and says so in its own name; which client fills the seam is still
open, and the seam is what lets that stay open.

**Three dispositions, kept apart**, because the first target survey conflated two of them:
refused, unreachable, and answered nothing are three different facts about a catalogue.

**A blocking client is why `Association` exists** rather than a bare handle: it owns one
connection, one deadline and the release, so a caller cannot hold a half open association.

**`MAX_RECORDS` is bounded by time, not by where a walk stops working**, which is the honest
form: five is what fits the fan out budget, not a limit the protocol imposes.

**The record format is named by the seam and both its spellings are the client's problem**,
because targets disagree about the name of the same schema.
### The blur calibration is a test now, because the eleventh pattern arrived as six

`rasterise.ts` carried the tint filter's calibration as a paragraph and said
plainly that it should be a test, deferred until "the eleventh pattern is
admitted", on the reasoning that a test written in the same hour as the thing it
checks tends to encode the mistake. #106 admitted six at once, so it was built.

**What it pins is the filter, not the floor**, and that distinction is the reason
it is worth having. `BLUR_RADIUS` and the three box passes decide what "adjacent
marks at least 12px apart" means. Move either and every pattern's headroom moves
while the floor still reads 0.196, and nothing else in the suite notices, because
every other assertion compares against that same constant. The failure would
arrive as tiles being refused for no stated reason.

Two assertions, both gratings built in the test: a 12px pitch at 2.4px wide must
measure 0.196, and a 4px pitch at 1.2px must measure 0.018. **Attacked with six
mutations** of the radius and the pass count (radius 1, 2 and 4; one, two and four
passes) and every one is caught by both assertions. The nearest miss is four
passes, which takes the 12px figure to 0.1045 against a tolerance of 0.0005.

**One figure in the old prose does not reproduce, and the reason is that a grating
is two numbers.** The three calibration figures do not share a duty cycle: 0.196
is 12px at 2.4px and 0.018 is 4px at 1.2px, both of which reproduce exactly, but
1.140 at 30px only reproduces at a 3px stroke. At 6px, which is the 12px figure's
own duty cycle, a 30px grating measures 1.071. The widths are now stated beside
the figures in `rasterise.ts`. The floor itself was never in doubt: it rests on
the 12px measurement, which is the one the test now holds.

### A displacement field repeats with the tile when its supports are disjoint

Curl is the first pattern here whose geometry comes from a function of absolute
position rather than of a branch parameter, so the header's periodicity condition
binds it directly. `swirl` rotates the plane about each of a set of centres, by an
angle that falls to zero at `reach`. The sum of such terms is periodic in the tile
exactly when no two of them overlap, so the constructor refuses centres closer
than twice the reach. The failure it prevents is a discontinuity along a line
**inside** the tile, which the nine drawing offsets do not rescue.

**The check measures on the torus rather than against nine written copies**, and
that is not a stylistic preference. Enumerating the eight neighbouring offsets
reads correctly and accepts centres at `[0, 0]` and `[484, 4]`, which is the same
lattice written two tiles out and a 5.7px overlap. There is no further arm that
fixes it, because nothing bounds how far out a centre may be written; reducing the
offset into the tile fixes the family. The first draft here enumerated, and the
evasion was found by attacking it rather than by reading it. Eleven evasions are
now checked, three of them in the suite.

The same reduction runs in the displacement itself, so a lattice written at the
origin and the same lattice written a tile out displace a point identically.

### Curl is Nonpareil worked a second time, and that is the point rather than a shortcut

A design critic could reasonably ask why two of the eight papers come out of one
generator. The answer is that this is the marbler's own sequence: a curl marble
**is** a nonpareil that has had a stylus drawn through it in circles, and drawing
it any other way would be drawing spirals rather than reproducing the technique.

Three things follow that are worth having recorded. A rotation maps every circle
about its centre to itself, so the displaced comb lines shear but can never cross
one another, which is why the tile needed no untangling. The compression is
therefore the only thing to tune, and it depends on the **total** turn and not on
the reach: the shear peaks at half the turn whatever radius it is spread over. At
5 radians two lines 15px apart close to 5.6px at the tightest ring, so the stroke
came down to 2.9px against Nonpareil's 3.2px, which puts the densest 7x7 window at
0.72 against Seigaiha's 0.718 and Shippo's 0.786.

### Golden Lily is John Henry Dearle's, not William Morris's

Noticed while tabulating what each Morris pattern reproduces. `docs/theming.md`
said "the historical Morris designs", and Golden Lily (1899) is by Dearle, Morris
& Co's chief designer after Morris. Dearle died in 1932, so it left copyright in 2003 under life plus seventy,
against 1967 for Morris's own. The table says both dates.

### A claim survives review when the evidence that would test it is not on the line

Two rules, learned twice in one file and worth stating once.

**A hit count carries the query that produced it.** The previous `targets.txt` held nine
counts; three named their query. Re-measured 2026-08-29, those three reproduced exactly
(444, 350, 6,638) and the other six did not (12,599 to 1,143, 223 to 10, 1,183 to 56,
1,254 to 95, 24,477 to 350, 2,788 to 410). Sweden is on both sides of that split, so it is
the query and not the target.

**An index claim carries the ISBN that produced it.** Three lines claimed something about
`@attr 1=7` without naming an ISBN, and one was false: Czechia's said the ISBN-10 does not
match, and two ISBN-10s from NKC's own `020$a` match hyphenated and unhyphenated alike.

Both are the same rule. **A claim with no evidence beside it is not reviewable, so it
survives.** That is why the format is the fix rather than a proofread.

### A Z39.50 target is three separate questions, and the third one fails silently

The survey has now been wrong twice in the same shape, each time by taking an earlier
answer as a later one.

| Question | What answers it | What it does not answer |
|---|---|---|
| Will it talk to us? | an unauthenticated `initResponse` | whether a search is answered |
| Will it answer a search? | a `find` returning records | whether it answers **in time**, and whether it answers **an ISBN** |
| Will it answer an ISBN? | `@attr 1=7` matching an ISBN taken from **that target's own record** | |

The first gap cost Spain: `z3950.bne.es` answers Init and refuses every search on every
database name with an identical `[101]`. The second cost Sweden: `libris.kb.se` answers,
and takes **12.9 seconds for the search alone** against a 4.0 second budget for the whole
fan out. The third is new and is the worst of the three, because it has no diagnostic at
all: `catalogos.cultura.gob.es:220/ABNET_REBECA` indexes the ISBN as the exact string
**including its hyphens**, so `84-204-5732-9` matches and `8420457329` returns **0 hits
and no error**. An ISBN normalised the way this application normalises it would return
nothing from that target forever, and nothing anywhere would say so.

**0 hits does not discriminate**, so establishing the third question needs an ISBN the
target itself returned. That is the method, not a detail of it.

### A red line in the survey is a moment, not a verdict

Measured 2026-08-29 against `catalogos.cultura.gob.es:220`, in this order: a clean search
returning 242 records; then about fifteen minutes in which every connection was closed on
Init, to `yaz-client` and to the survey's own probe alike; then a clean search again
and a green probe. Port 212 on the same host answered throughout.

So a target can be recorded as unreachable on a reading that describes fifteen minutes.
`targets.txt` has always said a green line is not sufficient; what it now also says is that
a red line is not conclusive, and re-probing before concluding is what #101 is for.

**This entry started life as the opposite claim**, that the probe under-reports, on the
evidence of one green search and one red probe minutes apart. Two readings taken at
different times were read as a difference between two instruments. The probe and a full
YAZ client agreed in both directions once both were re-run, which is what identified the
single cause.

### Published catalogue lists rot, and a `gaierror` is a claim about a string

Of Tellico's thirteen shipped Z39.50 servers, **four still work and nine have rotted**:
three hostnames do not resolve, two are filtered, one has no route, one is behind
Cloudflare, one closes the connection on Init, one refuses. That is the ordinary state of
this material and is why every entry is verified here rather than copied.

Two specific traps, both of which cost a session's conclusion:

* **The British Library is one character.** Tellico ships `3950cat.bl.uk`, which is
  `gaierror`. `z3950cat.bl.uk` resolves. (The target is retired anyway, refusing on 9909,
  so the correction changed the verdict from "never existed" to "withdrawn".)
* **Portugal was recorded as shut and is not.** `z3950.porbase.org` is filtered, and the
  BNP's own maintained target list names two live hosts on a different domain. Portugal
  went from unreachable to two SEARCHED targets by reading one page.

**The most reliable source is the institution's own page**, and it is not always current
either: Spain's Ministerio de Cultura publishes `catalogos.mecd.es`, which is filtered on
every port, while the same service, ports and database names answer on the ministry's
current domain `catalogos.cultura.gob.es`.

### A load bearing operational fact may not live only in a file that gets deleted

The suite and probe pods run with container name `run` because Falco's
"drop and execute new binary in container" rule is exempted on exactly
`k8s.ns.name = "default" and container.name = "run"`. That rule is level 13, Telegram
pages at 12 and above, and before the exemption existed these pods produced 57,062 alerts
in one day. A rename that looks like tidying therefore pages a person overnight.

That fact lived in a seat note, which is deleted with the plan, and in another
repository's Falco values, which is the rule rather than a warning to whoever writes the
next pod. It now sits beside the manifest line that names the container, and in the
working notes a seat reads before writing one.

### Where a credential is published by the library itself, that is a decision and not a measurement

Argentina's and Uruguay's national libraries each publish the full connection parameters,
user and password included, on their own public pages, with a contact address and no
stated restriction on use. Both targets refuse unauthenticated and answer with those
credentials, verified here.

**The provenance claim has to be exactly right, because it is the whole argument.** This
file first said Uruguay published no database name and spent eleven lines establishing
`BNU01`. The page publishes `Base: BNU01`, one line above the username; the field was lost
by the filter used to read the page, not by reading it. A defence that rests on "the
library publishes this itself" is only as good as the reading of the page.

That is the library's documented front door rather than a guessed credential or a worked
around authentication wall, and it is recorded as SEARCHED for that reason. **Whether
Endpaper ships a credential at all is a separate question and is the owner's**, because it
is about terms of use and about carrying a secret for a third party, not about whether the
target works. Nothing was attempted at Spain's BNE, which publishes none.

### The Alma gateway cannot be enumerated

An Alma hosted national library is reachable at
`eu0N.alma.exlibrisgroup.com:210/<INSTITUTION_CODE>`, which looks like a way to add a
country per line. It is not. A real institution code (`43ACC_ONB`, Austria) and an invented
one (`99NOSUCH_XX`) return the **identical** `[101] Access-control failure`, so membership
cannot be tested from outside; Norway answers only because BIBSYS opted in; and Spain's
CSIC is on `eu00` while Norway is on `eu01`, so the code does not even determine the host.

### A generator may not read its own output

Recorded because it cost a review round and the failure is silent by construction. The tool
that generated these three palettes places each ramp on an envelope, the mean OKLab
lightness per rung across the palettes already shipped, and it read that envelope out of
`palettes.css`. Which is where it writes. So the moment a generated palette was in that
file it joined its own average, and a second run produced different colours from identical
inputs.

**Nothing about that announces itself.** The anchors are published values and never move,
so the file keeps its shape; only the generated rungs walk. Measured: **35 tokens apart, 0
of them anchors.** And because the reporting read the ramps it had just built rather than
the file, every published figure described a palette no browser would render, while the
correction tables, which are all anchors, came out exact. Nine figures in three published
documents were wrong that way, and the suite was green throughout: it reads the stylesheet,
which was correct.

Two changes, and the second is the one that generalises. The envelope now excludes whatever
is being generated, so the tool is idempotent. And the tool **refuses to print a figure at
all** unless every token it built matches the stylesheet byte for byte, because a report
that measures anything other than the shipped file is worth less than no report.

### Three palettes chosen by licence and by measured distance, not by taste

Seven to ten, 2026-08-29. The candidates were Kanagawa, Tokyo Night, Ayu and Flexoki, and
the two that decided the shortlist were not about colour.

**Licence, read off the file the values came from.** Two of the repositories a search
returns first are Apache 2.0 rather than MIT: `folke/tokyonight.nvim`, which is the Tokyo
Night everybody links to, and `ayu-theme/ayu-vim`. The MIT sources are Enkia's original
`tokyo-night/tokyo-night-vscode-theme` and `ayu-theme/ayu-colors`. A palette whose licence
is read off the theme's website rather than the file the hexes came from is a licence read
off the wrong thing.

**Nothing in the tree can check any of that**, and it is worth being plain about why.
`palettes.test.ts` asserts every attribution ends in "MIT", which is a check on a string.
It cannot see a wrong licence and it cannot see a wrong holder, and a wrong holder is
exactly what shipped in the first draft of this: Ayu was credited to "Ayu Theme" where
`ayu-theme/ayu-colors` reads `Copyright (c) Konstantin Pschera`. Caught by a reviewer
reading the licence file, which is the only thing that can catch it.

**Flexoki was refused on a measurement.** It is MIT, publishes both modes and a complete
ramp, and would have been the cheapest of the four to port. Its dark page is **0.6** OKLab
dE from Endpaper's and its light card **1.9** from Endpaper's, so the tile a reader would
be choosing is the one the app already opens on. Distance from what is already shipped is
the thing a palette is for.

**Kanagawa scored no better on that metric and was kept**, which is the part worth
recording because it looks inconsistent. Its nearest neighbour is Rose Pine on the dark
surfaces alone; Flexoki's is Endpaper in both modes and on the card as well as the page.
And Kanagawa is the only one of the four whose upstream names both members, which is the
case the catalogue's two naming rules exist for and which nothing since Rose Pine had
exercised.

**Ayu Dark's third surface is deliberately not taken.** It publishes `surface.base`,
`surface.lift` and `editor.line` inside 4.6 CIE L* in total, so a ladder built from all
three puts the 1px divider this app draws between `paper-800` and `paper-900` at **3.02
L\***, under the 4.0 floor the badge hairline is anchored to and under the 4.25 that was
the faintest divider anything here shipped. Two published rungs, two generated, and the
divider measures 8.33. Nothing tested that divider, which is what made the whole argument
prose: the badge floor of 4.0 is justified by this being the faintest line the app treats as
visible, and a palette drawing it fainter would have retired that justification without
failing anything. `palettes.test.ts::the hairline the badge floor is anchored to stays
visible` now holds it, in both modes, on every palette. Verified by putting Ayu's third
surface back: exactly one test fails and it is that one.

### The channel record lives in two places, and they answer two questions

**Settings keeps the repair affordance. The overdue page shows the consequence.**

A person in Lending settings is there to fix a channel, so the standing record belongs
under the switch that repairs it: `notifications._CONFIGURED_BY` already makes writing
that switch the thing that clears the record. A person on the overdue page is asking
whether the household's reminders are going out at all, beside the books they are about.
Those are two questions and the same fact answers both.

**What stops it being a fact stored twice is that it is one component.**
`SenderHealthLine` moved from the Lending route to `pages/components/` and both screens
draw it, so a change to how a channel's state reads changes both. What differs is the
frame: settings draws it under the fields, the overdue page draws it under a note saying
what it is and is not about.

**The overdue page gets no navigation entry**, and the reason is not the one first written
here. `NavBar.tsx:33` declares `/loans` with `end: false`, so the Loans item **stays
active** on `/loans/overdue`: the page is already inside a navigation entry. With nothing
overdue it carries nothing Lending settings does not, so a permanent link would point at a
usually empty screen. The one state where that bit was the dead end above, and the nudge
fix removes it.

**The banner on the library page stays where it is**, and that is the part of the ticket
that is a judgement rather than a consequence. It is the interrupt, not the detail: it is
admin only, it fires only on the server's `broken` verdict, and it links to the screen
that repairs the channel. Removing it would mean a household learns about a dead Telegram
bot only if somebody happens to open the overdue page. Two banners can appear together on
the library page, an admin with overdue loans and a broken channel, and that is accepted
rather than overlooked. **Flagged for the owner** rather than settled: the ticket asked
for a deliberate decision and this is the reversible one.

### The overdue page reads `overdue_for_viewer`, not the loans list with a filter

**This is a consistency decision, not a disclosure fix, and calling it the second was
wrong.** The security seat established live that the wide set is the household loans list
working as designed: bare `GET /api/loans` with no parameter answers the same rows, so
`overdue_only` opens nothing that was closed, and no arm of either endpoint reaches a book
`visible_to` excludes. What was actually broken is a surface showing one set and counting
another.

`GET /api/loans?overdue_only=true` is rooted at `Shelf.seen_by` and stops there, so a
member reads every overdue loan over a book they can see. `GET /api/loans/overdue` applies
`notifications.overdue_for_viewer` on top, which is the rule the in app count already
uses: staff read every overdue loan on their shelf, a member reads the ones they lent or
borrowed, and in library mode every member reads every overdue loan on their shelf, which
is the widening that seam was reserved for. Both are narrowed by the Shelf first, so neither arm can reach a private book
somebody else added.

**Two screens that disagreed about how many loans are overdue would be worse than either
alone**, and that is what the banner's old link produced. The loans page keeps the wider
endpoint, because a list of the household's loans is a list of the household's loans.

The new endpoint also honours `overdue_in_app_enabled` and answers an empty page when the
switch is off: the switch is spelled "show overdue loans in the app" and this page is what
it shows. The loans list is deliberately unaffected.

**Every screen that counts overdue loans now counts through that one rule**, and the first
attempt did not. The loans page nudge still read `overdue_only=true` while linking to the
new page, so it reproduced the defect one screen over: measured for a non admin member,
which by `sees_every_loan` is every member, the nudge said 2 and the page showed 1; with
the channel switched off it said 2 and the page said "switched off", and since the library
banner hides itself in that state, **that nudge was the only entrance to the dead end**.
Both nudges now read `GET /api/loans/overdue/mine`.

### The channel panel may not claim anything about this page

`notifications.health` reports on channels that **push**, and never consults
`overdue_in_app_enabled`. So a panel sentence about where the loans appear is a sentence
the record cannot support: the empty line ended "They appear here, and nowhere else" and
rendered three lines above "The in app reminder is switched off". Both sentences on screen
together, measured. What survives is the half the record answers, "No channel sends these
reminders anywhere."

The same rule retired an over claim beside it: the page's empty state said "Overdue
reminders are switched off" when only the in app channel is off and Telegram may still be
sending hourly. It now names the channel it means.

### The channel record has three states, and a nullable list is two

Hidden (a member's 403, and the first render), unreadable (any other failure), and read.
They were one nullable value, so an admin whose record 500s got a page that loaded, no
panel, and no error, because this page keeps that query's error out of its own error slot
on purpose. `DeliveryRecord` names the three so a caller has to answer every arm.

### A count and a capped list may not appear on one screen without saying so

The overdue page prints `total` in its header badge and requests one page of fifty rows.
Above fifty those are two different numbers presented as one, and the page has no pager,
so the remainder is not merely uncounted, it is unreachable.

**A pager is more than this ticket, and the honest alternative is not to drop the badge
but to name the cap.** A reader who is told "63" and shown 50 rows has been given a wrong
impression; a reader told "showing the 50 most overdue of 63" has been given a true one
and a reason to look at the loans page. The rows are ordered most overdue first, so the
page a reader gets is the page they wanted.

Two tests, and the second is the one that matters: a line rendered unconditionally
satisfies the first and is wrong on every ordinary page.

**Library mode (#18) is what makes fifty reachable**, which is why this was worth fixing
now rather than when somebody hits it. A private household with fifty overdue books has a
different problem.

### A banner may not say "your" where the viewer is an admin

`sees_every_loan` is `viewer.is_admin`, so an admin's overdue count includes loans between
two other members. Both banners said "{count} of your loans are overdue". They now say the
loans need chasing, which is true under both arms.

Pre-existing on the library banner and propagated to the loans page by #102, so it is a
defect the diff spread rather than one it invented, and it is fixed in both places rather
than in the one the ticket touched.

### `LoanRowSkeleton` exists because the placeholder drifts from the row

#102 moved `LoanRow` into `pages/components/` on the argument that the choice is one move
or one copy, and the copy is what causes drift. It then copied fifteen lines of that row's
loading placeholder into the new page verbatim.

The drift is the same drift: the row gains a line, one page's placeholder grows with it
and the other jumps when the data lands. `testId` is a prop rather than a constant because
the two pages name their lists differently and their tests assert on those names, which is
the one thing a shared component here could not hard-code.

### The health line's docstring said the thing the page exists to deny

`SenderHealthLine` is drawn by two screens, and its docstring described the overdue page as
"where somebody asks whether a borrower was told". The health record holds no loan id, so
no screen built on it can answer that, and `overdue.deliveryNote` exists to say so. The
docstring now says what the panel does answer, and names the wrong framing as wrong,
because the shared component is where the next reader picks a framing up.

### `en.ts` is the source of truth, so a hint fixed in German only is a hint not fixed

`Messages` typing makes a missing key a compile error and says nothing about meaning. The
in app hint was corrected in `de.ts` and left stale in `en.ts`, so German readers got the
accurate sentence and English readers the old one. Nothing failed. This is the divergence
`deliveryNote`'s own test comment names, inverted.

### A check that cannot find its input has not passed

A guard read a file, found nothing, compared the nothing against a real value behind an
`[ -n "$want" ]`, and reported success. It had never once run on the path everybody uses,
because that path executes the script from a copy and the file was resolved relative to
the script's own location.

**The bug is not the path. It is that a missing input was treated as a satisfied
condition.** A guard in that state is indistinguishable from one that is working, from
every angle except the one nobody looks from, and it stays that way indefinitely: nothing
ever fails, so nothing ever asks.

So: **read the input, and refuse when you cannot.** An unreadable input is a defect in the
setup, not an absent constraint, and saying so out loud costs one branch. This is the same
lesson as a stated bound that stops guarding without failing, one level further out: there
the assertion was weakened, here it was skipped.

Third occurrence in two days, which is what promoted it from a fix to an entry.

### Prose inside an unquoted heredoc is code

A heredoc that interpolates a variable interpolates everything else too. A paragraph of
explanation added inside one, with identifiers in backticks the way this repository writes
them everywhere else, became a list of commands executed on the machine running the script.

The detail that makes it worth an entry rather than a comment: substitution **replaces**
what it runs, so the text that survived into the applied document was the paragraph with
its subject deleted. A comment can be destroyed by the act of using the file it documents,
and it happens silently, and the result still looks like a comment.

**Prose belongs outside the heredoc.** Where a document genuinely needs the text, quote the
delimiter and interpolate nothing.

### An eager load is kept because a measurement asks for it, not because the route beside it has one

`GET /api/loans/overdue` took its four eager load options from `GET /api/loans` by copying.
Both blocks were then guarded, and the guard was believed because the whole block could not
be deleted without it failing.

**Deleting the whole block is the wrong mutation.** Run one at a time (the diagonal this
repository already asks for on fixtures), and on 2026-08-29 every one of the four options
could be deleted on its own, in either route, with the file green. One of them was not
merely unpinned: it cost a statement and bought nothing.

**The reason no option was pinned is the fixture, not the assertion.** Both tests built
their page out of one admin who added every book, lent every loan and was the counterparty
to it, so every relationship resolved to a User already in the session's identity map and a
missing `joinedload` cost nothing to omit. **A cost test is only a cost test when every
relationship on the page names a different row.** Rebuilt with a distinct adder, lender and
borrower per loan, three of the four options are reported by name, at +3 selects on a page
of three and +10 on a page of ten.

The measurement then decides each option separately, which is the entry:

| Option | `list_loans` | `list_overdue` |
|---|---|---|
| `.joinedload(Book.added_by)`, the chain link | +3 and +10 on any page | +3 and +10 |
| `joinedload(Loan.loaned_to)` | +3 and +10, page holding returned loans only | 0, and cannot be anything else |
| `joinedload(Loan.loaned_by)` | +3 and +10, page holding returned loans only | 0, and cannot be anything else |
| `joinedload(Loan.book).selectinload(Book.tags)` | **-1**, deleted | **-1**, deleted |

`books_to_out` fetches the page's **active** loans with both users joinedloaded, so
`loaned_to` and `loaned_by` are answered by somebody else's query on an active page and only
`active_only=false` pays for them. `list_overdue` returns unreturned loans by construction,
so there they are free in every shape the route can produce. They stay, as the insurance
that a change to `overdue_for_viewer` does not arrive as an N+1, and nothing pins them
because there is nothing observable to pin: that is written beside them rather than left for
the next diagonal to rediscover.

`selectinload(Book.tags)` is the one deleted, and the line that separates it from the two
kept is worth stating: it is redundant under **every** page shape, because `books_to_out`
selectinloads tags for every book it serialises, while the other two are redundant only under
some. A statement that can never do work is deleted; one that does no work today is kept and
documented.

**A cost figure means nothing without the mutation that produced it**, and this table
cost a round by not saying. The first row was reported once as +6 and +20 and once as +3
and +10, by two seats on the same afternoon, and both were right: dropping the
`.joinedload(Book.added_by)` link while keeping the Book loaded is one lazy member per
loan, and dropping the whole first option takes the Book with it and is two. Written as a
bare `Book.added_by`, the row named neither. This is the same rule as a mutation count
being worthless without the failing test's name, applied to a measurement instead of a
verdict.

### A ceiling cannot see a statement removed

`assert len(selects) <= 12` went on passing at 11 after an option was deleted, which is this
repository's recorded failure mode (a smaller count is a weaker inequality) seen from the
other side: not a bound that drifted, a bound that could not detect the improvement it was
sitting on. Both loan cost tests now assert the count exactly, beside the two-length equality
that catches the N+1. Moving the number stays allowed; it just has to be deliberate.

### Headings are ANDed and Dewey divisions are ORed, in one filter

Two facets over one table, and they take different operators. A heading behaves like a tag:
selecting "Mental health" and "Stress management" means the books carrying both, which is
what selecting two chips has meant in this app since the tag filter was written.

A division does not, and the reason is what a division **is**. It is a shelf location, and a
book has essentially one. ANDing two of them returns only the books carrying two Dewey
numbers that fall in different divisions, so every multiple selection in a browse facet
would return the empty set. A facet whose second click always empties the shelf is worse
than one that disagrees with the filter beside it.

Stated here because the inconsistency is the kind a later reader deletes for tidiness.

### Only Dewey gets a sort, because only Dewey sorts

`BookSort.DDC` orders on the DDC number as text, and there is deliberately no
`sort=classification` covering the other three schemes.

A Dewey notation always carries exactly three leading digits, so text order is numeric
order: `004`, `155.9042`, `830`. A Library of Congress call number does not have that
property. Its class letters are followed by a number that sorts numerically, so `BF75`
precedes `BF575` on a real shelf and text order reverses them. Measured against the live row
`BF575.S75 E64 2022` on 2026-08-29. Ordering on LCC would ship a sort that is wrong exactly
where somebody would trust it, and doing it properly needs a call number parser nobody asked
for. GND and LCSH are subject vocabularies and have no order at all.

The enum member is therefore named for the scheme rather than for "classification": a reader
who sees the general word will assume their LCC numbers are in it.

### A projection that trusts a comment is a fail open filter

`shelf._division_key` reads `classifications.number` as a Dewey notation and carried a
comment saying every write path goes through `ddc.notation`. None did: `ddc.notation` was
called from nowhere outside `ddc.py`, and `POST /api/books` with
`{"scheme": "ddc", "number": "Hello world"}` answered 201 and stored it.

The cost was not a stored oddity. The facet then published a division `He0`, and the chip
linking to `?ddc=He0` hit the drop-rather-than-refuse rule for filter values, applied no
clause at all, and returned **the whole library**. An app producing its own broken link,
into a filter that fails open.

Fixed at both ends, and both halves are load bearing. `ClassificationIn` now refuses a `ddc`
number that is not a notation, which makes the invariant true going forward and is the real
fix. `shelf._looks_like_a_notation` guards the two read paths, because a database written
before that validator still holds whatever it was given and a facet is exactly where such a
row surfaces.

Both critic seats found this independently, which is the signal that process exists to
produce. The general lesson is the one this file keeps relearning: **a comment asserting an
invariant is not an invariant.** `tests/test_shelf.py::TestTheDivisionProjectionsAgree`
compares the Python and SQL projections across all 1,000 three digit numbers, because they
are two expressions of one rule and nothing else holds them together.

### A bound stated in a docstring is not a bound

`HeadingList` was written as `list[str] | None` with `Query(max_length=128)` and a docstring
explaining that the bound was per value, so a scheme plus
`CLASSIFICATION_NUMBER_MAX` fitted and nothing longer could match a row. On a list type
Pydantic renders `max_length` as `maxItems`: it counts the values and says nothing about
their length. The parameter had no length bound at all, and a single 20,000 character value
answered 200.

The `TagIdList` analogy is what misled it, and it is worth naming: that one is `str | None`,
where the same keyword does bound the string. Same spelling, different subject.

The per value bound now lives in `headings()`, which **drops** an over-long value rather than
refusing it, because a value too long to match any row is not a heading and this module has
always dropped those. Both critic seats found this independently too.

### Settled by the owner, and not a seat's to reopen

Stated first and plainly, because both cost a round trip and a later reader
reopening either is the most expensive mistake available here.

1. **An apk finding is acted on immediately, with no soak.** Disposition A of
   three, owner 2026-08-27. Not B, keep refusing but record the true reason, and
   not C, act only after an advisory has been seen on N consecutive nights. The
   owner's own argument for C was withdrawn as thinner than presented: the three
   day windows on PyPI and npm defend against "anyone can publish", and Alpine
   packages are built by distro maintainers from aports and signed.
2. **A rebuild release that did not clear its advisory retries the next night.**
   Owner 2026-08-30, taken over naming the stuck state only and over failing the
   nightly plan job. A rebuild finding is therefore never written to the ledger.
   The accepted cost is up to one public tag per night while upstream has not
   rebuilt; the nightly tags are the signal, chosen over a pager.


Pipeline decisions do live here (kaniko at :5493, Renovate at :5567, the release
image at :4409), so this one belongs. Suggested placement: beside the other
release pipeline entries.

### An apk finding is acted on, because the rebuild is the fix and a digest bump is not

Autopatch's refusal for an OS package read *fixed by moving the base image
digest, which is Renovate's job*, and the mechanism it named could not have
worked. Measured 2026-08-27, when CVE-2026-14456 refused v0.10.0 at
`verify:image`: `libcrypto3` and `libssl3` sat at `3.5.7-r0` with `3.5.8-r0`
published and marked fixed, and the pinned digest was already the current
`python:3.14.7-alpine`, byte for byte. There was no bump for Renovate to make.
Upstream rebuilds on its own schedule and may take weeks. The fix was a rebuild,
which the Dockerfile performs on every release build with `RUN apk upgrade
--no-cache`, and that was itself broken at the time: kaniko had cached the
upgrade layer for up to its two week default TTL, since fixed with
`--cache-ttl=6h` on both build jobs. So the refusal named a mechanism that does
not apply, and the mechanism that does was silently disabled. Nothing covered
apk findings at all.

A fixable HIGH or CRITICAL apk finding now cuts a patch release, which rebuilds.
Owner's decision, 2026-08-27, disposition A of three, gated on the smoke test
existing, which it does: `verify:smoke` and `build:smoke` run
the image smoke test and gate `publish:dockerhub` and the cluster's
digest announcement.

**There is no soak on this path, deliberately.** `uv lock --exclude-newer` and
bun's `--minimum-release-age` hold a language release for three days because
anyone can publish to PyPI and npm. Alpine packages are built by distro
maintainers from aports and signed, and `apk upgrade` moves the whole installed
set rather than one named package, so a per finding delay would buy little and
cost the window it exists to close. The alternative considered and refused was
acting only after an advisory had been seen on N consecutive nights.

**A rebuild finding is not judged by the post bump reports, and reading it out of
them would be a release computed by absence.** No after report can see an apk
package: bun and pip-audit read language manifests, and `ap-recheck` runs `trivy
fs` over the exported source tree, which holds no apk database. So `finalise`
partitions the actionable set: a bumpable finding must be absent from the after
reports, a rebuildable one is released on the strength of what happens after the
tag, `verify:image` scanning the rebuilt candidate with `--exit-code 1`
and `verify:smoke` starting it and requiring `/api/healthz`, both of which gate
`publish:dockerhub`.

### One CVE against two ecosystems is two findings

`_index` collapsed findings sharing any advisory id, and `Finding.merge` keeps
the first ecosystem it saw. One CVE is routinely reported against both an OS
package and the language package that bundles it, libwebp and pillow, libxml2
and lxml, and one `trivy image` report carries the OS packages and the
virtualenv together. So the two halves became one finding whose ecosystem was
decided by Trivy's `Results` order, and the other half appeared in neither the
actionable nor the reported list. Measured on one report holding both halves
under CVE-2026-4863: os-pkgs first gave one apk finding and an empty
`uv-packages.txt`, lang-pkgs first gave one pypi finding and no rebuild.

This was invisible while apk was refused, because the merged finding was refused
either way and reported nightly. **Acting on apk is what turned it fail open**,
which is the general shape worth keeping: widening what a gate acts on can
convert a harmless merge into a silent drop. Identity is now `(ecosystem, id)`.

### The ledger reads one line, not the whole tag message

`cmd_base` built the released-advisory ledger by grepping ids out of every tag's
entire contents. The tag message interpolates a package name and two version
strings straight out of a scanner report, so a `FixedVersion` reading
`3.5.8-r0 CVE-2030-11111` filed an unrelated advisory permanently, and a ledger
entry is what stops this pipeline ever acting on that id again. No newline
needed: `grep -oE` matches anywhere on a line. It now reads only the
`autopatch-advisories:` line this pipeline writes.

The cost is deliberate: an id a person mentions in prose in their own tag
message no longer counts as released. That is the better behaviour, because the
documented way to accept an advisory is `.trivyignore`, which carries a reason
and an expiry and is honoured for every scanner, and a sentence in a tag message
carries neither.

### A `$` anchored pattern is not a `fullmatch`

`$` matches before a trailing newline, so `.match()` on the package-name
patterns accepted one: measured, `libssl3\n` gives match=True, fullmatch=False
on all three. The name reaches `tag-message.txt`, where a second line reading
`autopatch-advisories: CVE-...` is the ledger. Anchoring reads as sufficient and
is not.

### A rebuild finding is not ledgered, so a failed rebuild is retried

Owner's decision, 2026-08-30, taken over naming the stuck state only and over
failing the nightly job. The ledger exists to stop a **bump** shipping the same
advisory every night, because a bump that shipped cannot be improved by shipping
it again. A rebuild is the opposite: it takes whatever the Alpine mirror holds at
the moment it runs, so repeating it tomorrow is what fixes a mirror that was
lagging, and the pipeline self-heals the day Alpine publishes.

The retry is not blind. `release:build` pushes to the internal registry before
`verify:image` scans it, so the image exists at the new tag even when the publish
was refused, and `autopatch:audit:image` reads `:$AUTOPATCH_BASE_TAG`, which is
now that image. The next night measures the rebuild that just happened.

The accepted cost is one public tag per night, unbounded, while upstream has not
rebuilt. The nightly tags are the signal, chosen over a pager.

### The ledger key names the ecosystem

Identity in `decide.py` is `(ecosystem, id)`, because one CVE is routinely
reported against an OS package and against the language package bundling it. The
ledger was bare ids, so releasing one half suppressed the other for ever though
it was never released. An entry now reads `apk/CVE-2026-4863`; a bare id in an
older tag still matches every ecosystem, which is the safe direction. Migration
cost nothing: across every tag in this repository, no ledger entry exists in
either format.

The intermediate fix, holding a shared id back, is worth recording as refused: it
un-suppressed the half that **was** released, so behaviour depended on whether
some language package happened to share the CVE. Both critic seats reached the
qualified key independently.

### An advisory id is one whitespace free token

The ledger line separates entries with a space, so an id carrying one is a second
entry: measured end to end from a report whose `VulnerabilityID` read
`CVE-2026-4 CVE-2030-9999`. Enforced in `Finding.__init__` rather than at the
sink, because these ids also become `--ignore=<id>` arguments to `bun audit fix`,
so a guard on the tag message would leave a command line unguarded. Nothing else
inspects an id: both readers take the scanner's value verbatim.

### A rebuild release builds with the kaniko cache off

`build:` on main and `release:build` share a `--cache-repo` and a six hour TTL,
and every layer before `RUN apk upgrade --no-cache` is identical between them, so
a push to main in the six hours before the nightly run served the patch release
the very layer it was cut to replace. Apk only: a lockfile bump changes a file in
the build context and busts its own layer, while `apk upgrade` changes nothing
kaniko hashes. Under retry nightly the cost is a wasted attempt and a public tag
whose rebuild changed nothing, not a stuck pipeline.

**The obvious fix does not work and the reason is worth keeping.** `ap-finalise`
runs in the nightly pipeline and `release:build` in the pipeline the tag push
creates, so a `reports: dotenv` cannot reach it. The tag annotation can, and this
pipeline already treats tag messages as its record: `finalise` writes an
`autopatch-rebuild:` line and `release:build` reads `CI_COMMIT_TAG_MESSAGE`. Two
spellings of one literal is the drift that would rot, so a test imports the
constant and asserts it appears in the job.

### A finding with no advisory id is refused

The other side of the one token rule, and it fails the same way: the ledger is
ids, so a finding with none cannot be recorded as shipped and releases again
every night. Measured from a bun advisory whose url carries no id: `ACT HIGH
unknown npm/lodash`, a release, and an empty advisories line. `read_trivy`
reaches the same state from a Vulnerability with no `VulnerabilityID`.

### A guard proved on one validated field, then trusted for the fields beside it

**The code was defensible every time and the stated reason was wrong every
time.** That is what makes this worth a decision entry rather than a note: a
reviewer reading the comment agrees with it, because the rule it names is real,
and the guard covers fields that rule was never about.

Four rounds of issue #88 hit it, each found by attacking rather than reading:

| The rule, correctly stated | Where it was trusted and does not reach |
|---|---|
| package names are anchored, so a name cannot forge a line | `installed` and `fixed` are not validated at all |
| the ledger reads one prefixed line, so a space separated payload fails | a newline in a value makes a real second line |
| every value is collapsed to one line, so nothing can forge a line | an **id** carries the ledger's own separator, a space |
| package names admit no colon, so nothing can spell the marker | `installed` and `fixed` are only whitespace collapsed |

It is not an autopatch fact. The same evening, in the classification work, two
critics independently found the shape in `HeadingList`'s stated bound and in
`_division_key`'s stated invariant.

**The tell** is a comment justifying a guard by naming **one** field's rule while
the guard covers several. **The fix that held was structural every time**, never
a further arm: validate at construction so the plan and its sinks agree, split on
whitespace so the rule is that a value may not introduce a line rather than that
`\n` is forbidden and `\r` allowed, anchor to a line rather than matching a
substring.

**And the instrument matters.** One evasion here was found by guessing a
spelling, `NL=''`, and the one that would really have happened, `NL=$(printf
'\n')`, was found only by executing the block. Four assertions on four fragments
say nothing about whether the fragments compose: two rewrites left a mechanism
wholly inert while passing every assertion written about it.

## Open, and not resolved in this ticket

Two gaps are recorded in the autopatch pipeline's own README rather than fixed, because
both need a pipeline configuration edit that this trio's brief forbids:

1. `autopatch:page:resolve` sends `completed` before `release:build` has run,
   and the tag pipeline has no Telegram notifier. The summary now names how many
   findings are waiting on that rebuild, which is a sentence rather than a page.
2. Telegram cannot tell attempt 1 from attempt 40 under retry nightly, because
   the summary is byte identical on every attempt. Not silence: the tag pipeline
   fails each night and GitLab mails the schedule owner, and the owner chose the
   nightly tags as the signal. Closing it properly needs a second marker line
   read back into its own file, which needs a new artifact path in
   the pipeline configuration.

The question that was paged is answered: retry nightly, recorded above. The page
was cleared.

### The provider order is the order sources are asked, and nothing else

Two things could be called a ranking of catalogue sources, and they are two
rules: which sources are **asked**, and which is **believed** when two disagree
about one field. The settings list is the first only, and the screen says so.

**One list cannot honestly drive both.** The two orders disagree about Open
Library in opposite directions: it is kept out of the pair asked on every lookup
for being five times slower (1.64s against 0.36s and 0.11s), and put first for
belief because its search index is edited towards how people write titles. The
lookup path's belief rule is not a list at all, being computed per ISBN from a
`9783` prefix. And the deciding one: `_SECONDARY_SOURCES` is exactly
`_MATCH_PRECEDENCE[4:]`, so "believed last" is a contiguous tail **of that
order**, while in the ask order those same three sit at positions 2, 5 and 6. No
cut in the ask order expresses the regional set, and reseeding the ask order to
make it contiguous changes the lookup chain instead. Either way something a
household never touched moves, which the ticket forbids.

A design seat proposed a stored cut position driving `_SECONDARY_SOURCES` and it
was refused on that measurement. Recorded because it is the obvious next
proposal and the reason it does not work is not obvious.

### The tier a source is asked in is a position, not a property of the source

An earlier draft made "asked on every lookup" a per source constant, reading
`_FALLBACK_SOURCES` as a speed classification. **The Austrian National Library
refutes that**: its measured mean is 0.240s, faster than K10plus's 0.36s, and it
sits in the second tier for coverage (3 answers in 50) rather than for speed.
Freezing that would freeze exactly the case the ticket was filed about, since an
Austrian household wants it asked first and a German one does not. A position is
the thing a household can move.

**One property does stay a constant: metered.** A metered source is never in the
tier asked on every lookup, whatever position it is given, because that tier is
asked even for books another source answers, so Google Books at the top would be
a charge per barcode scan. Moving it up still moves it earlier in the tier
below. The refusal is structural rather than a warning on a screen, because the
promise it protects is structural.

### Google Books has two switches and they are conjoined in one place

Its own section decides whether this library uses Google at all and holds the
key; the provider list decides whether it is asked and where. Two rows for one
source is a fact stored twice, and the answer is the shape
`public_catalogue_is_published` already uses: conjoin them in one function every
caller goes through. `settings_store.catalogue_sources` is that function, and
`stored_catalogue_sources` beside it is what the screen shows, which is the same
pair as `get_raw` and `in_force`.

**Merging them into one row is the better end state and was not done here.** It
needs a migration folding a stored `false` into a disabled entry, and it changes
a field on the public feature flags model. Raised rather than half done.

### The provider list does not reach the cover and authority hosts

`covers.py` still asks Open Library and the DNB for a cover image, and
`authority.py` still asks lobid, VIAF and Wikidata about an author. The boundary
is defensible only because the motivating case is a commercial API and the one
commercial source is Google Books, which the list does control completely. It is
not a general "nothing is asked" claim and nothing in the tree makes one. The
reasoning sits in `backend/sources.py` where a reader would look.

### A source that cannot answer says which of two things is wrong

Google Books can fail to answer for two reasons: no key, or its own card
switched off. `CatalogueSourceOut` therefore carries `has_key` **beside**
`ready` rather than only their conjunction. A screen reading `ready` alone told
a library holding a perfectly good key to add a key, which is the exact symptom
the provider list exists to remove, produced by the first fix for it.

### An evasion attempt is bounded by the shapes its author imagines

The guard that keeps a hard coded source order out of the tree was wrong on its
first attempt three times, and **each attempt was attacked before it shipped**.
Round one collected string literals only and I attacked it with six shapes, all
of them strings, so six shapes tested one spelling. A critic then found that
`(CatalogueSource.DNB, CatalogueSource.K10PLUS)` was invisible, which is the
spelling the enum exists to promote and therefore the one the next mistake will
use. Round two fixed the name and hard coded the **receiver** instead, so an
aliased import and a dotted `enums.CatalogueSource.DNB` were invisible, which is
the shape this repository has been caught by before.

The general form is worth keeping: **testing a guard against shapes you thought
of measures your imagination, not the guard.** What broke the loop each time was
another seat writing fixtures from its own vantage. The rule now matches any
attribute whose name is a member, which over-matches only if some unrelated class
grows an upper case `DNB`, and a false positive fails loudly where a miss is
silent.

### A paragraph describing behaviour is not re-read when the behaviour changes

**Three times in one ticket**, each caught by a seat rather than by the person
who moved the behaviour, and each within the same round as the change:

* `CatalogueSourceOut`'s class docstring enumerated its derived fields and was
  stale on two of them six lines above the field that had just changed.
* The same model's `enabled` comment claimed "off means not asked on every path"
  while a paragraph written in the same round stated the opposite boundary.
* The order guard's "what it cannot see" paragraph named `sorted(...)` as a
  blind spot after a rewrite that made `sorted(("dnb", "loc"))` reported, which
  understates a guard in the direction a reader can act on.

The fix that generalises is not three corrections. **A summary that repeats what
the lines below it already say is the thing that rots**, so the first was deleted
rather than corrected, and the other two now state a measurement instead of a
category. The standing rule this is a second instance of: a string describing
behaviour must be re-read when that behaviour changes in the same round.

## MARC21 import and export

Twelve decisions from one ticket, and the count is worth the sentence: the
feature is four hundred lines of parser and writer, and every one of these was
either found by a critic seat attacking something or measured against a running
system. None of them was reached by reading the code.

### MARC is read through `metadata.py`'s parser, not a second one

`backend/marc.py` composes `metadata.py`'s MARC primitives rather than restating
them: the subfield reader, the non-sorting delimiters in both spellings, NFC
normalisation, the repeated `082 $a`, the `020 $q` cross reference, the ISBD
punctuation that introduces the next subfield, the extent parser and the
language table. None of that is derivable from the specification and all of it
was measured against live catalogues.

`ddc.notation` records what the alternative costs: three parsers once had three
notions of what a Dewey number is, and the column existed to hold one.

**The consequence is a boundary this tree has nowhere else.** Those primitives
are private to `metadata.py`, and no other production module here imports an
underscore name from another. `marc.py` imports twenty. The alternative was to
move the shared MARC block into `marc.py` and have `metadata.py` import it,
which is the structurally right home and was not done in the wave that built
this because `metadata.py` was another trio's file at the time. **Moving it is
mechanical and should be done.**

The round trip test is what holds the seam: `tests/test_marc.py` exports a Book
and reads it back through the reader that parses live DNB and K10plus answers,
so a record this app writes is proved to be one this app's catalogue parser
accepts.

### What `marc.py` refuses is deliberately narrower than what a lookup refuses

A lookup refuses a title naming a volume slot and refuses a disc, because a
catalogue's identifier index matches cross references and the wrong record
poisons an entry. An upload is a cataloguer handing over their own file: `Bd. 3`
may be exactly what they catalogued, and dropping rows they will never be told
about is worse than importing a thin record they can see.

The reader also does not read `100 $0`, though it is the same subfield the DNB
is trusted for. `_k10plus_record` states the rule: a catalogue is not read for a
person's identifier until somebody has compared it live, and nobody can compare
an arbitrary upload.

### An oversized MARC file is refused, where an oversized CSV is truncated

`csv_import.MAX_ROWS` truncates at 20,000 with a log line. `marc.MAX_RECORDS`
refuses. A truncated reading history is a partial reading history and the rows
dropped are still that person's own. A truncated catalogue exchange is an
institution being told its holdings transferred when 20,000 of them arrived and
the rest did not, silently. The cataloguer can split the file; nobody can notice
a silence.

### Library mode is enforced on the server for MARC, at 403

Both directions answer 403 with the mode off, on the rule `routers/public.py`
already states: disabling a control in the browser is advice to one client. 403
rather than the 404 the public catalogue gives, because the caller holds a
session and `GET /api/settings/features` publishes `library_mode` to anybody, so
a 403 conceals nothing. That is `routers/auth.py`'s answer for a closed feature.

The gate is checked **before** the file is parsed, so a refused caller cannot
spend the server's CPU on a 5 MB parse.

### `classifications.py` exists because a ceiling with two implementations is not one

`SCHEME_ORDER`, `bounded_headings` and `add_headings` were private to
`routers/books.py`. `importing.py` now writes a Book's headings out of an
uploaded record and has to obey the same ceiling, the same ordering and the same
drop rule, and a router is the wrong place for a rule a domain module needs.

### A stored `classifications.scheme` is a `str`, and comparing it with `is` fails silently

`classifications.scheme` is a plain `String(20)` column, so a row loaded from the
database hands back a `str` rather than a `ClassificationScheme`. `is` against
the enum is then False for every row. The MARC export written that way answered
200 and carried no call number at all, with nothing in the log.
`classifications.add_headings` had already recorded the trap from the writing
side; `marc.py` walked into it from the reading side within the hour. Caught by
a router test against a real stored row: the unit tests drive the writer with a
stand-in carrying real enum members and cannot see it.

### No `008` in an exported record

The fixed length data elements field encodes place of publication, illustration
codes, literary form, intended audience and a government publication code, none
of which this app holds. Coding forty positions with `|` is legal and says
nothing; coding them with guesses writes assertions nobody here can support. The
language goes in `041` and the date in `264`, which is where a reader looks. No
`003` either: it names the organisation that assigned `001`, as a MARC
Organization Code, and this deployment has none.

---

### The MARC importer applies the API's own bounds, read off the declarations

`importing.within_bounds` holds an incoming record to what `POST /api/books`
would accept, reading the `Ge`, `Le` and `MaxLen` off `BookCreate.model_fields`
and the column widths off `Book.__table__` rather than retyping either. A list
of arms would have been the enumerating shape this repository records as wrong
on every first attempt, and a field added to the importer later inherits the
bound without anybody remembering.

It exists because the importer had no bound at all, and both the security seat
and the implementer found that independently. Two measurements:

* One 3.7 MB upload of a single record stored a 3,000,000 character title into a
  `String(500)` column, and `GET /api/books` then answered 3.8 MB. SQLite does
  not enforce a `VARCHAR` length, so nothing failed.
* `series_index` is bounded `le=1000` on every API path. A ten character
  `245 $n` stored `1e9`, and `routers/books.list_series` computes
  `set(range(1, max(held) + 1))`, which at a measured **70.5 bytes and 0.624
  seconds per million elements** is roughly **70 GB and ten minutes**: the
  container is OOM killed, again on the next request, for every member.

Strings truncate and numbers drop. Truncating a title keeps the record, which is
what a batch wants; clamping a year of `9999`, MARC's own open ended date, to
2200 would assert a date nobody supplied.

### A guard's fixture has to reference the thing the guard stops

`test_a_utf16_doctype_cannot_slip_past_the_byte_scan` was written twice. The
first version used an empty `<collection/>` and a bare `pytest.raises`, so with
the NUL check deleted the file parsed, found no record and raised "That file
holds no MARC records": **green either way**, while `docs/security.md` cited it
as the evidence. Both critic seats found it independently, which is the
strongest signal this process produces.

Two things fix it and neither is enough alone: the fixture references the entity
from a real `245 $a`, so a parse that gets that far expands it, and `match=`
names the refusal, so falling through to any other `MarcError` fails. Measured
on a mutant with the guard removed: 898 bytes became a 1,000,000 character
title.

### The seam into `metadata.py` is pinned by a derived guard, and `mypy` is not in CI

`marc.py` reads twenty private names on `metadata`, which no other module in
this tree does. `tests/test_marc.py::TestTheSeamIntoMetadataIsPinned` derives
that list with `ast` rather than writing it down, and asserts both that every
name still exists and that `marc.py` is the only module doing it.

It took three attempts and each failure was found by attacking it: the first
matched a module basename against any local variable and reported `shelf.py`
three times; the second was blind to `from metadata import _marc_fields`, the
same import shape `tests/test_shelf.py` records its own first version sailing
past; the third keyed on the local binding, so `import metadata as m` filed the
read under `m` and the "is it one of ours" filter skipped it.

**`mypy` reports all twenty statically and the pipeline does not run it.**
The pipeline runs `ruff check`, the OpenAPI diff and `pytest`; its only
mention of `mypy` is a comment. Adding `uv run mypy .` to the backend job would
pin these and `_Subfields`, which is annotation only and which no runtime guard
can reach. **Raised rather than done**, because a pipeline change affects every
trio's push and is not one trio's to make.

### `isbn` is never gap-filled onto a matched Book, and that is what stops a 500

`importing._MARC_GAP_FIELDS` excludes it, and the exclusion was load bearing and
unstated until the security seat's last round. A record whose ISBN belongs to a
Book the member cannot see, but whose title and author match one they can, is
**matched**: `MarcIndex.find` resolves it on the identity key and
`isbn_is_taken` is never consulted. If the gap filler wrote `isbn`, it would put
the invisible Book's ISBN onto the visible one and trip `books.isbn`'s unique
index. That is the failure `_taken_isbns` exists to prevent, arriving by a door
nothing guarded, and it is one transaction, so the transfer writes nothing and
answers 500. The incoming ISBN is dropped instead, which is the cheaper loss,
and `TestAMatchedBookNeverGainsAnIsbn` pins it.

**Worth keeping for the method rather than the fact.** Four statements of the
mechanism were made and all four were wrong, two of them mine. The last one
proposed the autoflush behind `add_headings`'s lazy load, and that flush
**cannot happen in this application**: `database.SessionLocal` is
`sessionmaker(autoflush=False)`, so the SELECT is issued and the pending
`UPDATE` rides past it, measured through the route.

The mechanism is the next **explicit** flush, and it is a property of the file:
the collider alone waits for the commit, and a collider followed by a record
that has to be created surfaces at that record's `_create` flush
(`_apply_one > _create > flush`, both records entered). Both arms measured
through the route rather than through an in process session, which is what put
the earlier answers apart: a session built by hand takes SQLAlchemy's default
`autoflush=True` and is not the session this application ever runs.

**The cleanest tell is the SELECT count, not the traceback.** Same record, same
collision, one argument apart: `autoflush=False`, which is this app's, issues 1
classifications SELECT and raises at the commit; `autoflush=True`, SQLAlchemy's
default, issues 0 and raises inside `add_headings`, because the autoflush fires
before the SELECT is reached. A probe reporting zero is measuring a session this
application never constructs.

The conclusion never depended on the moment, which is exactly why five wrong
statements of it, across three seats, each survived a round. It was settled by
one `grep` of the session factory rather than a sixth traceback: **a measurement
is only evidence about the configuration it was taken under.**

The same shape is why `blocked` under-counts, which narrows the oracle below
rather than widening it: a hit there means the ISBN is held **and** nothing on
this shelf matches the record.

### The MARC preview publishes an ISBN existence oracle, and it is accepted

`MarcPreviewOut.blocked` counts the records whose ISBN belongs to a book the
caller cannot see. The **fact** is not new: it has been readable off
`ImportResultOut.skipped` since the CSV importer, and `importing.py` argues why
the alternative is worse, namely letting the insert reach the unique index,
raise, and write nothing for the whole file with a 500. What is new is the
**price**. The import pays for each probe by writing a Book for every ISBN that
does not collide; a preview writes nothing.

Measured by the security seat, 2026-08-30: a member account against another
member's three private books, five records, `already_held: 0` and `blocked: 3`,
exactly the three private ISBNs; 20,000 records, 3,860,064 bytes, answered 200
in 1.08 seconds with zero books written. At three requests a minute that is
60,000 ISBN existence probes a minute, non-destructive and invisible to the
owner.

**Kept, because no arithmetic hides it.** `readable`, `already_held` and
`blocked` are the three numbers the screen exists for, and publishing any two
publishes the third. Removing the field removes the answer to "will this double
my catalogue", which is the accident the whole feature is shaped around, and
puts back the overstatement that a preview promised records the import then
refused.

What it discloses is that **some** book in this house carries an ISBN. Never
whose, never its title, never anything about the book, and never a 403 that
would confirm an id. The seat that found it recommended keeping the field and
recording the decision, which is what this is.

---

### The shelf loads what the row needs, not what the serialiser will load anyway

`Loading.SERIALISED` carried `selectinload(Book.tags)` and `serialisation.books_to_out`
re-reads the page with its own, because `BookOut.model_validate` touches the collection.

**The general rule: a statement that can never do work is deleted, one that does no work
today is kept and documented.** This one can never do work, structurally: every Book fetched
with `SERIALISED` is serialised by `books_to_out`, which is the only assembler `BookOut` has.

**A total is the wrong instrument.** Counting SELECTs said one route fell by one and another
by two, and neither number said which load had gone. **Counting only the statements that read
`book_tags` tells a redundant eager load apart from an eager load replaced by a lazy one**, and
only the first is free to delete.

Measured on `builder`, by a viewer who added none of the books, at two page lengths, every row
identical at both. Statements reading `book_tags`:

| Call site | Route | Before | After |
|---|---|---|---|
| `list_books` | `GET /api/books` | 2 | 1 |
| `list_trash` | `GET /api/books/trash` | 2 | 1 |
| `list_duplicates` | `GET /api/books/duplicates` | 2 | 1 |
| `list_copies` | `GET /api/books/{id}/copies` | 3 | 1 |
| `book_for_read` | `GET /api/books/{id}` | 2 | 1 |
| `book_for_read` | `GET /api/books/{id}/notes` | 1 | 0 |
| `book_for_read` | `POST /api/books/{id}/copies` | 3 | 2 |
| `book_in_trash` | `POST /api/books/{id}/restore` | 3 | 1 |
| `book_in_trash` | `DELETE /api/books/{id}/permanent` | 1 | 1 |

**A single book can never gain an N+1 from this**, because an eager load of one row's
collection and a lazy read of it are one statement either way. **The absolute "nothing rose
anywhere" is false**, and the exception is the useful part: one arm of one route costs 12
statements without the option and 11 with it, because it reads a collection already on the
book. The decision stands and the absolute does not.

**`EXPORTED` keeps the option this drops**, because its rows are not serialised by
`books_to_out`, and that asymmetry is the point rather than an inconsistency.

**The general form of the measurement error**: a cost test that reads one row's relationship
inside its own assertion measures the assertion, not the route. Three of four cost tests over
these options passed with their own subject deleted, and a second seat re-measuring in the
opposite direction is what found it.
### Three national catalogues speak SRU over HTTP, so they need no Z39.50 client

**Measured 2026-08-30 for #91.** The internal target survey classified Italy, Greece,
Czechia, Spain, Portugal, Argentina and Uruguay as Z39.50 targets, on the strength of an
unauthenticated `initResponse` and a banner. **Three of them answer `operation=explain`
and `operation=searchRetrieve` over plain HTTP on the same port**, and one of those is the
sharpest case in the ticket.

| Target | HTTP SRU | Query language | Records |
|---|---|---|---|
| `catalogue.nlg.gr:210/biblios` (Greece, Koha) | yes | CQL `bath.isbn`, and PQF via `x-pquery` | **MARC21** as MARCXML |
| `aleph.nkp.cz:9991/NKC` (Czechia) | yes | PQF via `x-pquery`; CQL refused | Dublin Core only |
| `catalogos.cultura.gob.es:220` and `:212` (Spain, two ministry catalogues) | yes | PQF via `x-pquery` | ISO 2709, not UTF-8 |
| `opac.sbn.it:2100` (Italy), `z3950.nlg.gr:210` | no, Metaproxy answers its own HTML 400 | | |
| `z3950.porbase.bnportugal.gov.pt:210` (Portugal) | no, nothing listens for HTTP | | |
| Argentina, Uruguay | HTTP answers and refuses with `Authentication error`, as Z39.50 does | | |

**Latency over that HTTP route, n=7 each, one host, min / median / max**, with the two
SRU sources already in the chain asked the same two ways in the same run from the same
host, which is what makes the candidate figures mean anything:

| Target | ISBN lookup, `maximumRecords=5` | title search, `maximumRecords=10` |
|---|---|---|
| Czechia | 0.057 / 0.072 / 0.109s | 0.187 / 0.190 / 0.245s |
| Greece | 0.201 / 0.203 / 0.235s | 0.254 / 0.256 / 0.262s |
| control, Library of Congress | 0.208 / 0.212 / 0.346s | 0.311 / 0.327 / 0.751s |
| control, DNB | 0.222 / 0.240 / 0.292s | 0.278 / 0.309 / 0.507s |

Both candidates are at or under both controls on both paths, so neither has a latency
argument against it. **These are not comparable with the Z39.50 figures the survey
carries for the same countries**, which were taken on different hardware; a duration
measured on one machine says nothing about another.

**The reason is structural and is why this generalises**: YAZ's Generic Frontend Server
speaks HTTP and Z39.50 on one socket, and answers SRU on it wherever the operator has
configured a database. `metadata._LOC_URL` is already this fact, `http://lx2.loc.gov:210/lcdb`
answering `text/xml`, and it was read as a property of the Library of Congress rather
than of YAZ. **The survey read six YAZ banners and never sent an HTTP request to any of
those sockets.**

What binds: **check for SRU on the Z39.50 port before sizing a target as a client
problem.** One `curl` per target, and it decided three of eight countries here.

### Greece serves MARC21, not UNIMARC, and it is a different host

The target survey records Greece as `UNIMARC ONLY: usmarc and marc21 both return
[239] Record syntax not supported`. That is true of `z3950.nlg.gr`, which is a
Metaproxy. **The National Library of Greece's own Koha is `catalogue.nlg.gr`, a different
address**, and it serves MARC21: leader `04637cam a2200577 a 4500`, `020`, `245`, `260`,
and a `100$0` carrying `urn:nbn:gr:nlg:01-A112061`.

So Greece needs neither a Z39.50 client nor a UNIMARC mapping, which were the two things
that made the session plan call it a mapping ticket rather than a config line.

**It is still not a config line, for a different reason.** `metadata._marc_claims_isbn`
refuses any `020` carrying a `$q` qualifier, because a qualified entry is a cross
reference to a different edition and taking one as identity once returned a Ukrainian
translation of Dune for the American ISBN. **The National Library of Greece uses `$q` for
the binding**, `χαρτόδετο` for paperback and `σκληρόδετο` for hardback. Measured over 50
ISBNs drawn from that library's own catalogue: 50 returned a record, 43 passed the guard,
**7 were rejected and every one was a correct match**. It fails as `NOT_FOUND`, which is
indistinguishable from a catalogue that does not hold the book, and the function is a hard
filter for K10plus and the OENB as well. So the rule is right, its stated reason names one
country's convention, and it covers every country: the recurring shape this register
already has an entry for.

**Superseded 2026-08-31**, by "`020 $q` is a qualifier about this record's item, and
refusing it lost the book" below. The rule turned out not to be right: it was refusing 51
records of the 1,197 misses in the 500 ISBN survey, on three sources rather than one, and
35 of the 51 are German or Austrian rather than Greek. What survives from this entry is the
prediction, which was correct, and the shape it names.

### A miss rate is not a gain: the candidate has to hold the book too

| | keyless misses, of 50 | the candidate holds | realisable gain | 95% Wilson |
|---|---|---|---|---|
| Czechia | 40 | 39 | **78.0%** | 64.8 to 87.2 |
| Greece | 43 | 31 | **62.0%** | 48.2 to 74.1 |

**The discount is real and differs sharply**: Greece's 86.0% gap becomes a 62.0% gain
and Czechia's 80.0% becomes 78.0%. **Which of the two ends up larger is not established**:
the difference is +16.0 points, 95% Newcombe -2.0 to +32.7, which includes zero, and the
Wilson intervals overlap across 64.8 to 74.1. The rows above are ordered arbitrarily. That
the discount matters is the finding; the ranking is not one, and an earlier draft of this
entry made it anyway, at the same n the entry beside it refuses to rank on.

**And a diagnostic beside a hit count is not a failure to answer.** Greece returns the
true `numberOfRecords` **and** `Unknown schema for retrieval` when no `recordSchema` is
named. A probe treating any diagnostic as unreadable reported "Greece: realisable gain
0.0%, 37 unreadable", a confident zero produced entirely by the measuring filter, on the
country the report recommends. Every previous instance of this in the programme has the
same shape and a different filter: a hit count read off an empty SRU envelope, a quota
refusal read as zero, and a transient 503 read as a miss. **The count is deliberately not
stated here**, because a number in prose does not recount itself and this register has an
entry about exactly that.

### The DNB and the OENB answer almost nothing outside German publishing, and both are in the default first tier

**Measured 2026-08-30 for #91, n=50 domestic ISBNs per country, one host, asked through
`metadata._SOURCES` itself so that "answered" means what the application means.** A
source that answered `rate_limited` or `unavailable` after five retries is excluded from
its own denominator rather than counted as a miss, **which is the mistake the entry above
records this programme making again while measuring this**: a refusal scored as a miss, or
a diagnostic scored as an absence, is a number that describes the measuring filter rather
than the catalogue. The sample is drawn from Wikidata, which is in
neither chain, by ISBN registration group, and it is biased towards notable editions:
Open Library and Google Books hold those best, so these figures **understate** the miss
rate rather than inflating it.

| | Italy | Czechia | Greece | Spain | Portugal | Brazil | Argentina | Uruguay |
|---|---|---|---|---|---|---|---|---|
| DNB | 5 | 2 | **0** | 1 | **0** | **0** | **0** | **0** |
| K10plus | 12 | 7 | 3 | 5 | 17 | 23 | 15 | 28 |
| OENB | 4 | 1 | **0** | **0** | **0** | **0** | **0** | **0** |
| Open Library | 30 | 5 | 7 | 30 | 23 | 34 | 14 | 25 |
| Google Books | 47/47 | 42/49 | 22/50 | 48/49 | 34/50 | 35/50 | 24/50 | 41/50 |

`sources.DEFAULT_ORDER` leads with the DNB and `ALWAYS_ASKED` is 2, so **a new install
anywhere in this table spends both of its concurrent lookup slots on sources that answer
0 to 5 of 50.** That is #94's argument with a number against it, and it is actionable
with no new provider: it is a default ordering question.

### Most of the coverage the tree credits to the chain is Google Books, and most installations have no key

| Country | keyless chain misses | with a Google key |
|---|---|---|
| Greece | **86.0%** (73.8 to 93.0) | 54.0% |
| Czechia | 80.0% (67.0 to 88.8) | 14.3% |
| Argentina | 56.0% (42.3 to 68.8) | 42.0% |
| Portugal | 44.0% (31.2 to 57.7) | 24.0% |
| Italy | 36.0% (24.1 to 49.9) | **0.0%** |
| Spain | 36.0% (24.1 to 49.9) | 2.0% |
| Uruguay | 34.0% (22.4 to 47.8) | 16.0% |
| Brazil | 20.0% (11.2 to 33.0) | 16.0% |

95% Wilson, n=50. **The intervals overlap between neighbours, so this does not rank
countries**; it separates the top from the bottom, Greece's floor of 73.8% being above
Brazil's ceiling of 33.0%.

The session plan already records this correction for Brazil ("5 of 5 from Google Books is true
only of a deployment that brought its own key"). It reproduces across eight countries.

### A national library does not hold every ISBN in its own registration group

Of 50 Greek-prefix ISBNs drawn from Wikidata, the National Library of Greece holds
**37**, 95% Wilson 60.4 to 84.1.
So "legal deposit means the domestic edition is there" is 74% true here, and a coverage
argument built on 100% overstates the gain by a quarter. Measured through the library's
own ISBN index, which was verified to discriminate before it was used for anything: an
ISBN out of its own record returns 1, a foreign ISBN returns 0.

### The Library of Congress is credited with the wrong countries

`metadata.search`'s docstring lists the Library of Congress in the free regional tier "for
Spanish, Portuguese and Latin American printings". **Nothing had measured that**, and it
is a published docstring rather than a comment.

Asked by `bath.isbn` over its own SRU, 50 domestic ISBNs per country attempted, 2 or 3
per country unreadable so the denominators vary:

| | Spain | Portugal | Brazil | Argentina | **Uruguay** | Italy | Czechia | Greece |
|---|---|---|---|---|---|---|---|---|
| holds | 12 of 48 | 9 of 48 | 9 of 47 | 8 of 48 | **26 of 47** | 12 of 48 | 3 of 48 | 2 of 47 |
| | 25.0% | 18.8% | 19.1% | 16.7% | **55.3%** | 25.0% | 6.2% | 4.3% |

**The sentence names the wrong countries.** Uruguay is much its strongest and is not
named: 55.3% against Spain's and Italy's 25.0% is +28.0 points, 95% Newcombe +9.0 to
+44.4, which excludes zero, so it is one of the few orderings in this work that is
actually separated. Spain, which the sentence does name, is exactly Italy's, which the
sentence excludes.

**It is a title search source**, so holding the edition is necessary and not sufficient:
the figure says the record exists to be found, not that a title query finds it.

**The docstring was corrected in the same wave** and now reads "the Library of Congress
for Latin American printings", with the table and this reasoning beside it. Nothing below
Uruguay is separated at this sample size, so the six are not ranked. **There is
deliberately no test pinning the numbers**, because pinning them means asking a national
library from the suite, which is a test that fails when that library is down.

### Argentina and Uruguay will be covered, using the credentials their libraries publish

**A decision, not a shipped state. Nothing is built for either country and no
`CatalogueSource` exists for them.** This entry records what was decided and why, so the
work can be sized; the code is its own tickets.

**Owner, 2026-08-30.** The national libraries of Argentina and Uruguay publish Z39.50
usernames and passwords on their own public pages, with contact details and no stated
restriction. Both refuse unauthenticated and answer with them. Both also answer **SRU over
plain HTTP** and refuse there with the identical `Authentication error`, so a credential
would need no Z39.50 client at all.

**The answer is yes, for both, taken 2026-08-30 and reversing a no taken the same day.**
The reversal is recorded rather than tidied away, because the first answer was given on a
question that had been put wrongly. The owner was asked whether to *approach* two foreign
national libraries for credentials, and answered no. That was never the question: the
parameters are already published, on the libraries' own pages, with contact details and
**no stated restriction on use**. What was actually being decided was whether using a
published front door is within its terms, not whether to go and ask for one.

**On the terms of use question itself**, which is the real one: these are published by the
issuing library, on its own site, beside a contact address, with no restriction stated.
That is a documented front door rather than a guessed credential or a worked around
authentication wall, and it is the same relationship a library intends when it publishes an
SRU endpoint. The entry above, on provenance, is what this rests on, and it is load bearing:
the defence is only as good as the reading of the page, and that reading has already been
wrong once in this file.

**What it buys, measured.** Argentina is the **second largest** measured coverage gap of the eight countries
surveyed: 56.0% of a domestic ISBN sample unresolvable without a Google Books key, 95%
Wilson 42.3 to 68.8, and 42.0% with one. Uruguay is 34.0% and 16.0%. Neither has any other
route: no open interface, and no HTTP catalogue that answers, so without the published
credential both are closed entirely.

**Shipping a credential is new for this codebase and is the work rather than a detail.**
Every other source in the chain is either open or takes the household's own key
(`google_books_api_key`). A credential belonging to a third party, carried in the image and
redistributed, is a different thing from both, and how it is stored, whether an install can
replace it, and what happens when the issuing library rotates it are all open. That is
sized in the tickets rather than assumed here.

### A number, once written down, stops being re-derived and starts being copied

**By the person who corrected it.** This is the clearest instance this project has
produced of why a figure in prose needs a test, and it rules out the comfortable
explanations.

A review seat computed a comparison as `26/50` against `12/50` and reported it: +28.0
points, 95% Newcombe +9.0 to +44.4. **The same seat then established, in writing, that
those denominators were wrong**: two or three lookups per country had gone unanswered, so
the real fractions were `26/47` and `12/48`. It corrected the table accordingly. And then
it went on quoting +28.0 as sound through three further rounds, **in the same documents in
which it was insisting on the corrected denominators**. A second seat caught it by
implementing the method independently, validating it against the neighbouring sentence,
and only then searching the denominator space for the pair that produces the stated
triple. The correct figures are +30.3, +10.6 to +47.0, and the conclusion does not move.

**Not inattention, not unfamiliarity, and not a missing measurement.** The right value was
established by the same person, in writing, and the stale one was repeated beside it. A
number that has been written down reads as settled, and nobody recomputes what looks
settled, including its author.

**So the rule is mechanical rather than a matter of care.** Every figure a docstring
derives from another figure in the same docstring gets a test that recomputes it. Where
that check is impossible or disproportionate, the docstring names which figures are
covered and which are not, as `TestTheShelfIsTheOnlyWayIn` does with its blind spots.
**A limit that could be closed by one call to a helper already in the file is not a limit,
it is a gap with a sentence in front of it**, and the next reader cannot tell those apart.

The worked example is `metadata.search`'s Library of Congress table: ten derived figures,
six percentages and four aggregates, all recomputed from the two rows the guard already
parses. Twenty mutations, twenty caught. Six of them survived the first version of that
guard, which pinned three of the ten and left the other seven, **which is the defect its
own docstring diagnoses, recurring inside the fix for it**.

### A finding that rests on a mechanism should say what guards that mechanism

**The search fan-out's deadline is what would cancel a slow national catalogue**, and the
whole argument for adding one over a slow transport rests on it. Exactly one test
exercises it, and until 2026-08-30 that test could barely fail.

It slept 5 seconds behind one source against a 4.0 second deadline and asserted the search
took under 5. A **working** deadline returns at about 4.0, so there was a second of
headroom and no false failure to worry about. The defect was the other way: a **completely
broken** deadline returns at about 5.0, against a bound of 5, so the test failed only by
however much `asyncio.sleep(5)` overshoots 5.000. Its entire ability to detect its own
regression rested on scheduler noise being positive.

**So a bound that several other conclusions leaned on was, in effect, unguarded**, and
none of those conclusions said so. That does not weaken them: the mechanism was correct
throughout and only its test was weak. It changes what a finding has to state. **Name what
guards the mechanism you are relying on, and check that the guard can fail.**

It is now bounded against the deadline rather than against the sleep, with both figures
scaled down so the suite gets four seconds back, and **proved to discriminate** by
removing the timeout in memory: unmutated passes, mutated fails by about a second with a
message quoting the deadline, the sleep and the elapsed time.

**One thing checked rather than assumed, because it would have made the whole test
inert.** The deadline constant is read at call time as a bare module global and is bound
as no default argument anywhere, so patching it in a test actually takes. There is already
a test elsewhere in this tree for exactly that failure, a constant resolved at import
rather than at call time, which is why it was worth a minute rather than a shrug.

### An SRU source built on PQF may not build its own query string

**Found by the security seat on 2026-08-30, and it is the recurring shape this register
already has an entry for: a guard proved on one field, trusted for the field beside it.**
No count is given here on purpose, because the count is kept elsewhere and a second copy
of it in a published file is a number that will not recount itself. Two of the three SRU capable targets accept **only** PQF, as the
`x-pquery` parameter; CQL is refused. So an adapter for them puts a PQF string into an
HTTP query parameter, on the `fetch.py` side of the tree, where the only PQF escaper
lives behind a seam it would not go through.

`metadata._CQL_UNSAFE` does **not** cover it. It is `[=<>"()/\\]+`, and `@` is not in
it. Executed against `_search_terms`, a title term of `@1=1016 harry` becomes
`@attr 1=4 @1 @attr 1=4 1016 @attr 1=4 harry`, which is exactly the injection the Z39.50
seam's own escaper was written against: an `@` followed by a digit at the head of a term
replaces the pinned use attribute, so the query stops being an author or title search and
becomes something else entirely, with no error anywhere.

**The reason a reviewer signs this off is the finding.** `_CQL_UNSAFE` deletes `"` and
`\`, two of the three characters the PQF escaper escapes, so the value looks sanitised;
and the constant's comment names CQL's metacharacters while the string is about to be
parsed as PQF. That is the tell already recorded here: a guard justified by naming one
context's rule while it covers another.

**The fix is structural rather than a further arm on the character class**, which is what
held every previous time: one function produces every PQF string, it is the only way to
produce one, and a house rule test asserts that nothing outside that module formats a
string containing `@attr`. Two riders, both measured: the CQL sanitiser must **not** run
first, because chaining a sanitiser for one grammar into another is the same defect one
level up; and the refusal of control and surrogate characters is still required but its
reason changes, since a NUL survives as `%00` and truncates the C string in the
**server's** parser instead of ours, which is invisible from this side.

**Greece's ISBN lookup is safe by construction and does not need this.** `bath.isbn` is
built from a validated 13 digit ISBN, the same construction as the three live SRU sources
already in the chain.

### A source that is not UTF-8 corrupts a shelf rather than failing a search

The Spanish ministry catalogues answer over SRU with ISO 2709 inside the SRU envelope and
are **not UTF-8**. Three things hold, all measured on this tree's Python 3.14, and the
first draft of this entry got the mechanism wrong in a way worth recording.

**Nothing raises.** `metadata._parsed` hands a `str` to `ElementTree.fromstring`, and a
declaration of `ISO-8859-1` or `windows-1252` parses without complaint. And the decode
that happens first substitutes rather than failing: a response's `.text` decodes with
`errors="replace"`, so a body whose bytes are not UTF-8 arrives as **mojibake**, with
every accented character replaced by U+FFFD. Measured: an author of `Solé` arrives as
`Sol�`.

**So the failure is a corrupted record written to a member's shelf, silently, under a 200
with no log line.** That is worse than a crash, not better, and it is the thing an adapter
for those two catalogues has to be written against.

**The remedy is the one the MARCXML reader already uses, and it brings its own hazard
with it**: read the envelope from the response's bytes rather than its decoded text, and
catch `ValueError` beside `ParseError`. Those two halves are one change, because the
`ValueError` exists **only** on the bytes path. Measured, `str` against `bytes`, same
document:

| declaration | as `str` | as `bytes` |
|---|---|---|
| `ISO-8859-1`, `windows-1252` | parses | parses |
| `EUC-JP`, `Shift_JIS`, `UTF-7` | **parses** | `ValueError: multi-byte encodings are not supported` |

So the text path cannot raise that error and cannot be fixed by catching it, and moving to
bytes is what makes catching it necessary. **Every parse site in `metadata.py` catches
`ParseError` and not `ValueError`**: 8 of 8, uniform, which makes it a structural property
rather than a count that can drift. The MARCXML reader already parses from bytes for this
reason and grew its `ValueError` arm after a 92 byte body produced a 500.

**What the first draft of this entry said, and why it was wrong**, because the correction
is the more useful half. It claimed `fromstring` "raises `ValueError` on a body carrying
its own encoding declaration", and that the hazard was 8 of 13 `try` blocks. Neither
survives: the declaration Spain actually sends parses fine, the module has 16 `try`
statements rather than 13, and the 8 is the numerator of a different and stronger fraction
than the one it was attached to. **A mechanism inherited from a review and not re-derived
is a claim**, and this one was two review rounds from being written into a published file.

## The cataloguer's column set

Nine decisions from #30. The ticket sized itself S because the data mostly
existed, and what it actually cost was settling what one of its three columns
meant: the answer was that it never meant anything, and it is gone.

### The call number is Dewey and Library of Congress, the subjects are GND and LCSH

Two columns rather than one, and the line between them is not a preference.
`ClassificationScheme`'s own docstring draws it: "GND is an authority file
rather than a shelf order", an LCC notation is a call number
(`BF575.S75 E64 2022`), and DDC is the one of the four that also sorts. So the
call number column holds notations and the subjects column holds headings.

The consequence is the rendering rule, which differs between the two on
purpose. **A notation names its scheme** (`Dewey 155.9042`), for the reason
`ClassificationPanel` already gives: `004` is computing in Dewey and is not a
Library of Congress call number at all. **A heading does not**, because it is
words and reads without one. GND decides which way the fallback goes: its
`number` is an opaque identifier (`4203576-4`) and its `label` is the heading,
while LCSH carries the heading in `number` and has no label at all, so the cell
renders `label ?? number`.

**`location` is neither**, and that was the named mistake to avoid. It is prose
about where a book stands in this house. It sorts against nothing and means
nothing outside the house, and it keeps its own column in both modes.

### Sorting the call number sorts the classification, never the cell

The call number header asks the API for `BookSort.ddc`, which is
`min(classifications.number) where scheme = ddc` with nulls last, evaluated in
SQL over the whole table (`backend/shelf.py`, `_DDC_ORDER`). It is deliberately
**not** the string the cell draws: that string carries a scheme name in the
reader's language and may hold a second notation from a different shelf order
after it, so ordering by it would order the library by the word "Dewey" in
English and by "Library of Congress" in German. The table sorts nothing itself,
which is the rule it already had: a browser sort would sort only the page that
has been loaded, silently.

### There is no record status column, and the promise of one is withdrawn

**"Record status" never had a definition.** It appears in the archived plan
exactly once, in a parenthetical list of what matters to a cataloguer, and was
carried verbatim into three files: `settings_store.library_mode`'s docstring,
the `settings.public.modeHint` string on screen, and `docs/featurelist.md`. All
three promised a column that nothing stored and nobody had specified.

Two derivations were built during this ticket and both were refused.

* **From privacy**, restricted when the Book is private. Refused because
  `visible_to()` is
  `or_(Book.is_private.is_(False), Book.added_by_user_id == user_id)`, so a
  listing carries everybody's public Books beside the reader's **own private
  ones**: the column would read true on exactly the rows that must not leave
  the house, in a mode one switch away from a public catalogue, and 30c prints
  the same table onto a spine label.
* **From completeness**, established when the Book carried the descriptive
  minimum the MARC leader's own comment names plus a Classification. Better
  founded, and still refused: **a column invented so that a promise in prose
  comes true is worse than no column, because it looks like data.**

**What a cataloguer actually wants there is the record's source**, which
library it came from or that it was a manual entry. That is provenance, MARC
`040`, not status. It needs a real column and a migration: nothing stores it,
`backend/marc.py` writes no `040` at all, and the datum exists at write time and
is discarded, because the lookup knows which source answered and an import knows
it was an import. It has its own ticket.

So the three prose sites now describe what ships, and none promises the
provenance column before it exists.

### One spec table per column, not a label map beside two lists of keys

`COLUMN_SPECS` holds a label, an `offeredTo` and a `defaultIn` for each column,
and both `AVAILABLE_COLUMNS` and `DEFAULT_COLUMNS` are derived from it.

**The first draft was an exclusion literal and a critic broke it in one move.**
Adding a key to `COLUMN_KEYS` was a compile error in the label map and in
`BookTable`'s definitions, and no error at all in the household's list, which
was spelled as "every key except these". So a third cataloguer column would
have reached every household silently, and the test covering it enumerated the
same literals, making it a second copy rather than a check. The fix is
structural rather than a further arm: a new entry cannot compile without saying
which modes it belongs to.

**One constraint the types still cannot express**, so it is a test:
`ALWAYS_SHOWN` must be offered to every mode. `normalise` filters over
`AVAILABLE_COLUMNS[mode]`, so its forced-title arm cannot fire for a key that
mode does not offer, and `title: { offeredTo: HOUSEHOLD }` compiles and hands a
cataloguer a table with no link to any book.

The label lives in the same row for a second reason. Two things name a column,
the table's own header and the picker that turns it on and off, and a picker
offering "Where it is" against a header reading "Location" is one column
presented as two.

### The column set is per mode, in two localStorage keys

The same argument `libraryView.ts` makes, and it holds unchanged: this is a
habit rather than library data, so it needs no endpoint, no schema and no
migration. It is also the only shape available, because `GET /api/settings` is
admin only and a column choice is one person's rather than the library's.

**Two keys rather than one record holding both**, because the requirement is
that a household's choice survives a switch into library mode and back. Two keys
make that structural: writing one cannot touch the other, so there is no merge
to get wrong and no ordering between the two writes to reason about.

**The set is derived from the mode rather than held as state seeded from it.**
`library_mode` arrives from a fetch, so it is undefined for the first render or
two; a `useState` initialiser would capture the household set and a cataloguer
would keep it for the rest of the session. Reading storage when the mode changes
costs one `getItem`.

**Storage never holds a copy of the default, and `writeColumns` enforces it on
a normalised set.** A stored copy stops following the default the moment a later
version changes it, which is the one thing "back to the usual columns" must not
do. Two shapes reach that state and only the first is obvious: reset, and
turning one column off and straight back on, which also hides the reset control
because there is then nothing to reset *from* while the key still holds a copy.
The guard compares joined strings, so it normalises its input first: without
that it holds only for a canonical caller, and the docstring claiming the
invariant needs nobody to remember it would have been true only because the one
call site remembered.

**`readColumns` decides on the stored tokens, never on its own result.** The
result always carries the forced title, so a length test on it cannot tell a
reader who turned every other column off from a value naming nothing this
version knows, and a title-only table silently reverted on reload. The docstring
claimed the forced title was what stopped those two being confused, and the code
confused exactly them.

One consequence, stated rather than fixed: the stored value is an unversioned
comma list, so a deliberate title-only choice and the survivor of a mass column
rename are the same string. Not worth versioning.

### One table of scheme labels, because there were about to be three

`ClassificationPanel` and `ClassificationPicker` each carried their own
`Record<ClassificationScheme, MessageKey>`, and the table view would have been
the third. The type made a *missing* scheme a compile error in each copy, so the
keys could not drift; the values could, and three places naming one scheme three
ways is drift nobody notices. Now `frontend/src/lib/classificationLabels.ts`.

### A count is not a fact about a file until it says which tree it describes

Two seats measured `vite.config.ts`'s tally of DOM-free test files during this
ticket and got twelve and eleven. **Neither was wrong.** Twelve was correct for
the tree carrying `tests/lib/recordStatus.test.ts`; eleven is correct for the
tree that ships, because that file existed for one round and was deleted with
the rule it guarded. The comment now dates its number rather than merely
stating it, so a reader who counts twelve on an older checkout reads a different
tree instead of a stale number.

That is the general answer to a disagreement this repository keeps having, and
it is cheaper than the alternative: a number stated without its tree has to be
re-derived by everyone who doubts it, and the doubt is never resolved because
both parties are right.

### A refusal belongs where somebody would go to propose it again

`settings_store.library_mode`'s docstring records that there is no record status
column, that "record status" never had a definition, and that **both** attempted
derivations were refused and why. That is the file a person opens when they want
to know what library mode does, so it is where a proposal to add such a column
would start. A refusal recorded only in a changelog or a merge request is a
refusal the next person re-litigates from scratch.

### Check the shape of a scripted edit's result, not its exit code

Two instruments lied at exit code 0 during this ticket: a regex meant to parse
`COLUMN_SPECS` matched 5 of its 23 entries because it assumed one-line bodies,
and a splice of a notes file resolved its end anchor before its start anchor and
duplicated ninety lines. Both were caught by looking at the result's shape, a
count of entries and a list of headings, which is the check this repository
already prescribes after any scripted edit and which nothing else would have
caught.

## The default source order, and what an order can and cannot buy

Eleven entries from #115. The ticket asked for a tuple to be reordered; what it
cost was establishing that the tuple had never had a stated rule, and three of
the four claims in its own description did not survive re-derivation.

### The first tier is a latency budget, and no order of the roster covers more

**#115.** `sources.DEFAULT_ORDER` had no stated rule, so the question "should the
DNB lead" had no answer to check against. It has one now, in the constant's own
docstring, and the rule is that the first tier holds the sources most likely to
answer **within a latency budget**, deliberately not the most authoritative.

Two facts settle that, and both are in the tree rather than here. Authority is
already owned elsewhere and per ISBN: `metadata._merge` sorts by
`_preferred_source(isbn)` regardless of tier position, so promoting a source
changes whether it is asked and never whether it is believed. And **coverage is
order invariant**: `metadata.lookup` asks every enabled source until one answers,
so no permutation of the roster finds more books. Modelled over five candidate
orders on one 500 ISBN outcome set, all five resolved the same 300, and
`tests/test_metadata.py::TestNoOrderOfTheRosterFindsMoreBooks` now asserts it
over every position each source can hold in the chain and over every ordered
pair of sources, rather than over the five orders that were considered. It
enumerated all 362,880 permutations until the cost of that became factorial in a
roster that grows; what replaced enumeration, and what enumeration bought that
the replacement does not, is in the class docstring.

What follows is a refusal worth recording: reordering is never the fix for a
country the chain misses. It buys latency, and which records `_merge` folds.

### The ticket's own premise did not survive re-derivation, and three of its four claims were wrong

**#115, filed off #91's survey.** Recorded because the correction is the finding,
and because `docs/decisions.md` already carries the claim in the form that is
wrong.

The existing entry, *"The DNB and the ÖNB answer almost nothing outside German
publishing, and both are in the default first tier"*, says a new install
*"spends both of its concurrent lookup slots on sources that answer 0 to 5 of
50"*. Measured again on the same 400 ISBNs, cell for cell identical to #91's
table:

* **The ÖNB is not in the first tier.** `ALWAYS_ASKED` is 2 and the ÖNB was
  third, so it was first in the **sequential** tail. The tier was the DNB and
  K10plus.
* **K10plus does not answer 0 to 5 of 50.** It answers 12, 7, 3, 5, 17, 23, 15
  and 28, which is 110 of 400 and the best free source after Open Library.
* **The DNB's slot costs no wall clock.** The tier is gathered, so it costs its
  slowest member: `dnb + k10plus` is a mean of 0.342s and **K10plus alone is a
  mean of 0.342s**, p90 0.447s against 0.446s. What the slot spends is one HTTP
  request and a millisecond.

What survived is the tail order, which was wrong, and the reason given for it,
which does not reproduce. That is what #115 changed.

### The ÖNB's justifying measurement measured a different population

**#115.** `sources.DEFAULT_ORDER` put the ÖNB ahead of Open Library as "the only
source that answers for an Austrian imprint the German pair both missed: 3 of
50", and `metadata.py` recorded 50 of 50 against the DNB's 47 and K10plus's 39,
measured 2026-08-27. A fresh Austrian sample drawn from Wikidata by publisher
country, 50 ISBNs on 2026-08-30, gives 22, 39 and 25, with the ÖNB holding **1**
of the 7 the German pair missed and Open Library holding **2**.

**The two do not disagree, and the tree says why.** `metadata.py`'s ÖNB comment
records that every ISBN in the 2026-08-27 sample was taken off a live ÖNB
record, so its 50 of 50 is true by construction and is not evidence about what
the ÖNB holds. Its 3 of 50 is evidence and is a floor. The new sample is drawn
from books Austrian publishers published, and only that frame can answer how
often the ÖNB answers where the German pair did not, which is the question the
fallback order turns on. Both are now stated where they matter, with their
frames, and the superseded conclusion is marked in place rather than left to be
found twice.

**The correction is worth more than the finding, and it is mine.** The first
version of this entry, and of the two comments it describes, said that how the
earlier sample was drawn "is not recorded anywhere in this tree" and offered the
by construction explanation as a guess. It is recorded, twenty lines into the
block being corrected, and a critic found it in one grep. So this is another
instance of the class this file already names twice over: **the code defensible,
the stated reason wrong**, and the reason wrong in the specific way of asserting
that something is absent without looking. A claim that a record does not exist
is a claim to be checked exactly like a claim that it does.

### Three slots asked together was measured and refused, on 0.061s

**#115.** The ÖNB is the only candidate for a third concurrent slot: Open Library
is outside `FIRST_TIER_BUDGET_SECONDS` and Google Books is metered and barred. It
is nearly free in wall clock, p90 0.447s to 0.507s, and models **0.061s** faster
per lookup, 1.344s to 1.283s over 500 ISBNs, by taking a round trip off the miss
path. It buys **2 more books of 500**, and costs half again as many outbound
requests on every lookup of every install, against other people's free
catalogues. Refused on that, with the numbers in `sources.ALWAYS_ASKED` so it can
be reversed against them, and the size now pinned by `sources.TIER_UNION` rather
than by a guard that sliced with the constant it was checking.

**Recorded because both numbers were wrong first**, and both errors are general.
The model must cost a gathered tier as **that ISBN's own maximum**, never as the
maximum of four per source means, which overstated the absolute by 11% and the
gain by half. And the baseline must be **the order that ships**: against the
order before the tail was reordered it reads 0.108s, which credits the third slot
with the tail reorder's saving.

### Most of the chain's coverage is Google Books, and most installs have no key

**#115, measuring the keyless half of #91's finding.** Over 500 domestic ISBNs
across ten frames the four free sources answer 300 and miss 200; outside German
language publishing they miss 196 of 400. #91's keyed contrast on the same books
was Italy 36% missed against 0%, Greece 86% against 54%. **The keyed half was not
re-derived**: this seat had no key, and a figure that cannot be recomputed is
attributed rather than repeated as its own. Stated in `sources.NEEDS_A_KEY`,
`sources.MEASURED`, `metadata.py`'s chain comment, `README.md`, **`docs/api.md`
and `docs/README.md`**, because a docstring saying the chain covers a country is
a claim about a keyed install. The last two were missed on the first pass and are
the ones that mattered: `docs/api.md` is the tree's most explicit description of
the chain's coverage, and it still carried the old order and the refuted ÖNB
reason in full.

**Superseded figures in this file, for whoever edits it next.** The 50 of 50 and
the 0.240s table at 3020-3030, and "its measured mean is 0.240s, faster than
K10plus's 0.36s" at 6924 and 6941-6942. The entries above append rather than
rewrite, so those lines still read as current until somebody marks them.

### The evidence behind a stated bound has to live where the bound does

**#115.** `sources.MEASURED` and `sources.TIER_UNION` are measured constants, and
the probes that produced them ran in a session directory that is deleted when the
work ships. Three integers presented as measured, whose evidence is gone three
days later, is the failure this repository already records as **a bound that
stops guarding without ever failing**: nothing that could contradict it still
exists. So the sample is committed. It was re-run for #111 and is now
`backend/tests/fixtures/catalogue_survey_2026_08_31.json`, the same 500 books
re-asked, 500 rows of an ISBN,
what each free source answered and how long it took, and
`TestTheConstantsAreRederivableFromTheCommittedSample` recomputes every constant
from it. 109KB, ISBNs and verdicts only, and it is published like the rest of the
test tree.

**It is evidence about that run and not about a re-run**, which both the module
and the test class say in as many words. These are live third party catalogues on
a dated day; re-deriving them against the world means re-running the probe.

**And the answer arrived one `git add` short of working.** The fixture was
untracked and not gitignored, and the publish script exports from
`git archive HEAD`, so the mirror, the image and the pipeline would all have
shipped a test class reading a file that was not there while the local gate
stayed green. **Both critic seats found it independently**, which is the
strongest signal this process produces and means it was not a near miss. A new
file that a test depends on is not added by any gate that runs before the commit.

### A guard proved on one property, then trusted for the property beside it, for the third time in one file

**#115.** The class is already named twice in `CLAUDE.md`, and this wave produced
three more instances in one review cycle, so the tell is worth stating on its own:
**a comment justifying a guard by naming one rule while the guard covers several.**
It reads correctly, a reviewer agrees with it, and the hole survives.

* `test_a_metered_source_never_joins_the_pair_asked_on_every_lookup` keeps a
  metered source out of the tier. A docstring said it held Google Books' position
  in the **tail**. It does not: Google Books at position 1 of `DEFAULT_ORDER`
  passed all 52 assertions in the file, leaving the tier untouched and making the
  metered source the first thing asked on every miss, 200 of 500 sampled lookups
  against 297. Fixed by `test_a_metered_source_is_asked_last_by_default`.
* `test_the_slot_threshold_is_not_fitted_to_this_roster` asserted two inequalities
  the tests above it already made. `SLOT_MUST_EARN = 3` and `= 35`, both edges of
  its own stated interval, survived. The budget beside it had been given the
  proportion of interval treatment and this constant had not, which is the
  "generalisation right, the clause explaining the exception unmeasured" shape.
* `Measured`'s docstring asserted that nothing checked the table against the
  world three lines from a list saying the sample was committed and every figure
  recomputed. The fix falsified a neighbouring sentence and the sentence stayed.

### A fix a critic hands you is itself a first draft

**#115**, and an instance of a rule `CLAUDE.md` already states. The design seat's
fix for the latency model quoted the third slot's gain as 0.11s. That is
three wide measured against the order **before** this change. The refusal is
taken from the order that **ships**, so the figure is **0.061s**; 0.108s credits
the third slot with the tail reorder's saving. The seat confirmed it on
re-reading. The implementer that applies a finding without re-deriving it writes
the next round's error, and this one was in the finding rather than in the code.

### A docstring in a published test may not cite a session path

**#115, and the third instance in one wave.** `backend/tests/` is published while
the internal seat notes directory is stripped, so the publish script's last guard
rejects a published file that names a path inside it, and the build fails
after the push rather than before it. This entry cannot spell that directory
either, which is the rule demonstrating itself: the guard matches a stripped
directory name followed by a slash, wherever it appears. It happened in `backend/tests/test_house_rules.py` here, in
`backend/tests/test_shelf.py` on `main` from another trio, and once already in a
`docs/decisions.md` entry drafted from that same trio's notes.

**The reason it keeps happening is worth more than the rule.** The seat writing
the sentence is looking at the file, so the pointer is true when written and dies
twice: once when the mirror strips it, and again when the wave ships and the
directory is deleted. **Stand the sentence on what the harness proved, not on
where the harness lives.** "Checked by planting one and watching this test fail"
survives both deaths; a path does not.

It is also a class the local gate cannot catch before a commit, because the
script reads `git archive HEAD`. The only cheap check is grepping the changed
published files with the script's own patterns, which is what found this one.

### The source order guard's dict arm: a structural rewrite, tried and reverted

**#115.** Recorded because two seats independently judged it the better shape and
it is not in the tree, so without this the next person to hit that arm starts
from scratch.

`TestNoModuleHardCodesASourceOrder` reads a dict's keys as an ordered literal of
source names. Every mapping keyed on `CatalogueSource` therefore trips it, which
is why `metadata._SOURCES` and `metadata._FREE_SEARCHES` were already exempted
and why `sources.MEASURED` needed a third exemption the day it was written.

**The rewrite** read a mapping's keys as an order only when its **values are the
positions**, so `{DNB: 0, K10PLUS: 1}` stayed an offender and `{DNB: _dnb}` and
`{DNB: Measured(...)}` stopped being ones. It removed three exemptions rather
than adding one, and it **reported** an order nested inside a mapping's values,
which the exemption route exempts.

**Why it was reverted anyway**, and this is the part that inverts the usual
advice. The exemption is one named constant in one named module; the rewrite made
a whole shape invisible **tree-wide**, so a future module relying on a source
keyed dict's iteration order would never be asked the question. And the
alternative the guard appears to invite, restructuring `MEASURED` into a tuple of
`Measured` records, is worse than either: `_source_named` returns `None` for a
`Call`, so a tuple of records is invisible to the guard entirely. Measured
through the guard's own `paths` hook against an isolated fixture. **So the
structural move is right when the structure is what the guard misreads, and here
restructuring the data would have removed the guard's grip rather than satisfying
it.** That is the sentence to keep.

**A known gap, and it predates this ticket**: an order nested inside an exempt
constant's value is exempt, because the exemption walks the whole value subtree.
That is true of `DEFAULT_ORDER` today and is not introduced here.

### Two seats made the same mistake in opposite directions

**#115.** The implementer wrote that a fact was "not recorded anywhere in this
tree" without looking, and it was recorded twenty lines into the block being
corrected. The design seat then reported that a sentence was still present in
`sources.py` after it had been removed, having re-taken the measurement its
finding turned on but not the quotation the finding rested on.

**One asserted an absence without checking, the other asserted a presence without
rechecking.** Both are the same rule as every stale number in `CLAUDE.md`, one
level up from arithmetic: **a claim about what the tree contains is a claim, and
it goes stale exactly like a figure does.** The seat found its own; the other was
found by being contradicted and withdrew it with the mechanism named.

## A test that loops holds one log record per iteration

The `caplog` silencer that used to sit on the roster permutation class carried a rule with
no other home, and the rule outlives the class that bought it.

**pytest's capture handler retains every `LogRecord` emitted inside one test**, so a test
that loops holds one record per iteration until it ends. `metadata.lookup` logs a line per
resolved ISBN, and at 362,880 orders in a single test that was a measured 1059 MB on the
xdist worker and an OOMKill of the backend test job against the runner's 2Gi. Setting the
level stops the record being **created**, so it is the loop that gets cheaper rather than
the handler. The permutation class no longer trips this, because its loop is bounded at 209
iterations. The next loop test will.

## The National Library of Greece, and the rule that was refusing its records

Five entries from #111. The ticket asked for one SRU adapter and predicted one
obstacle; the obstacle turned out to belong to three sources rather than to the new
one, and clearing it moved the whole chain's coverage.

### `020 $q` is a qualifier about this record's item, and refusing it lost the book

**#111.** `_marc_claims_isbn` skipped every `020` entry carrying a subfield `q`, on the
reasoning that `$q` marks a cross reference to another edition. That reasoning came from
one German record and does not reach the catalogues beside it. MARC21 defines `$q` as
qualifying information about **this** record's item: its binding, its volume, its format.

Measured 2026-08-30, records carrying an `020` whose entries are **all** qualified:

| Source | All qualified | Of records with an 020 | What the qualifier says |
|---|---|---|---|
| DNB | 0 | 442 | it does not write them |
| K10plus | 159 | 231 | `ePUB`, `PDF`, bindings, prices |
| NLG | 63 | 317 | `χαρτόδετο` (paperback), `(τ.1)` (volume 1) |

**So the rule refused the record's only identifier**, silently, as a `NOT_FOUND` for a
book the source holds. Over the committed 500 ISBN survey, one fetch per source per ISBN
with both rules read off the same body: the old rule reproduced the recorded outcomes
exactly, 0 discrepancies in 1,197 probes, and preferring unqualified entries turns **51
misses into hits**, 40 on K10plus and 11 on the OeNB. Every one of the 51 qualifiers
describes the record's own item and none is a cross reference.

**The fix is structural rather than a list of qualifier spellings**, because `Broschur`,
`χαρτόδετο` and `pbk.` are one concept in three languages and the next catalogue has a
fourth. `_isbn_entries` prefers unqualified entries and falls back to qualified ones only
where a record has none.

**The Dune failure cannot return, and the same ISBN proves both halves.** Read live
2026-08-30, `pica.isb=9780441013593` answers with two records: the Ukrainian translation,
which carries its own `9786171276895` unqualified **beside** the American ISBN as
`$q amerik. Original`, and the American edition, both of whose entries read `$q : pbk.`.
The first is refused because it names its own ISBN plainly; the second was refused before
this change and is the book that was asked for. The test fixture for that case had been a
simplification with the record's own ISBN left out, so it pinned a shape the catalogue
does not produce.

### Matching an ISBN and choosing one are two questions, and only the first is safe to answer

**#111.** `_isbn_entries` has two readers. `_marc_claims_isbn` **matches**, against an ISBN
the member already holds, and cannot be wrong about which entry it picks. `_marc_isbn`
**chooses** the ISBN to store, and where a record carries no unqualified entry there is
nothing to choose on but catalogue order: on a K10plus record whose three `020` entries are
`ePUB`, `PDF` and `Broschur` it returns the ePUB's. `marc.py` calls it, and that module's
docstring calls the ISBN the importer's primary match key.

**Not fixed, deliberately.** Separating the formats means a list of spellings, `ePUB` and
`PDF` and `e-book` and `EPUB` and whatever the next catalogue writes, which is the
enumerating guard shape this register already holds several entries about: it goes stale
without failing. The record is genuinely ambiguous, one row describing three saleable
forms with no field saying which the row is for, and before this change the same record
stored **no ISBN at all**. An ambiguous identifier beats none, the lookup path is
unaffected because the adapters are handed the ISBN that was asked for, and the limitation
is stated in `_marc_isbn` where somebody reading the code will meet it.

Raised by the design seat, which executed it rather than reading it.

### A pooled union over a country stratified sample is the wrong instrument for the first tier

**#111.** The tier is asked on every lookup, and `TIER_UNION` picks the best union of each
size from the 500 ISBN sample. With the NLG in the roster that arithmetic puts it in the
**leading pair**: `k10plus + nlg` answers 242 of 500 against 221 for the pair that ships.

**Every one of those 34 extra books is in one frame of the ten.** The sample is ten frames
of fifty by country, so pooling weights ten national publishing outputs equally, and no
household's shelf is one tenth Greek. What the tier costs is paid by one library on every
scan; what a national catalogue answers is concentrated in the country it serves.

`TIER_FRAMES_MINIMUM` stated that measurably: a source asked on every lookup must answer
in at least two of the ten frames. Measured 2026-08-30, K10plus and Open Library answer in
10, the DNB in 5, the OeNB in 4 and the NLG in **1**, so every floor from 2 to 4 picks the
same tier and the constant sits in a gap rather than on an edge.

> **Superseded by #112**, and by a source that passed this rule while being the exact shape
> it was written to exclude. See "The tier rule counts concentration, not frames" below. The
> numbers in this section are the 2026-08-30 survey and are kept as the reasoning of the
> day; the current survey is the fixture named in that entry.

**A Greek library can still promote it**, which is what the provider list is for. The
default is what nobody chose.

### The tail's two candidate rules came apart, exactly where the guard said they would

**#111.** `TestTheOrderFollowsTheMeasurement` disclosed that it ordered the tail by
`answered / of` while the constant's own docstring ordered it by how often a source answers
**a book the tier missed**, and that the two would part on a roster where a broad source
only holds what the tier holds.

The NLG is that roster. Pooled it answers 37 of 500 against the OeNB's 55; of the 279 the
leading pair missed it answers **34 against the OeNB's 1**. The pooled rule would ask the
OeNB first on every one of those lookups, to reach a source that answers one of them.

`TAIL_MARGINAL` now carries the marginal count and the guard reads it. **The disclosure
was worth more than the guard was**: it said in advance which roster would break it, and
the roster arrived four days later.

### The National Library of Greece is plaintext too, and the identity check is what that costs

**#111.** `catalogue.nlg.gr:210` speaks no TLS, and `https://catalogue.nlg.gr` on 443 is a
different service answering 404 to this path. Both measured 2026-08-30, which is the date
`metadata._NLG_URL` carries for the same two probes. So this is the
second source in the chain fetched over plaintext HTTP, after the Library of Congress, and
the reasoning there applies unchanged: `fetch.RedirectedOffHost` is what stops an on path
attacker turning the request into a request against an arbitrary address, and substituting
a record is still open to them.

**What it buys them differs by path, and the first draft of this entry got that wrong.**
It said the exposure was narrower here than at the Library of Congress, because this source
answers ISBN lookups and `_marc_claims_isbn` refuses a record that does not name the ISBN
scanned. That is true of `_nlg` and false of `_nlg_search`, which is registered in
`_FREE_SEARCHES`, is on by default, and has no identifier to check against. So the search
path's exposure **equals** the Library of Congress's rather than being narrower, and only
the lookup path is checked. Found by the security seat, by reading the two adapters instead
of the sentence about them.

A wrong index name is diagnosed by this endpoint rather than answered with the whole
catalogue, which is the ÖNB's trap and does not exist here: `bib.isbn` and `srw.isbn`
answer SRU diagnostic 1/15 and `bath.title` answers 1/16. The identity check is kept
regardless, because on the lookup path it is now guarding the wire rather than the index.

## An address at account creation

### An email address belongs to creating an account, and a directory account has no creation moment to attach one to

**#103.** The address is part of `POST /auth/register` and of the admin's account creation
route, sharing one rule with the editing route: `schemas.user.AddressField`, which is
`mailer.looks_like_address` and `MAX_ADDRESS`, so this app has one answer to "is that an
address" rather than two that drift.

**The second row is the admin's creation form**, `POST /api/users/test-accounts`, the only
route by which an admin creates an account here. It takes an address because it takes
`UserCreate` and there is one rule, and the form now offers the field. Owner's instruction,
2026-08-31: "storing and changing an email only works if all the interested parties have
access to the interface for it." Without the field an admin's route to giving a new account
an address was to create it, find it in the member list and edit it, which is three screens
for a field that belongs on the form.

**The third row is the one `editable` could not express, and it needed a second flag.**
A directory account is created by `upsert_directory_user` at a first sign in, with no form
and nobody typing. Where the directory carries an address it is read and owned there. Where
it does **not**, the account exists with none, the member may set one, and nobody had ever
told them so: `editable` is true for that member and for a local account alike, so the
screen had no way to say why the box was empty.

`MemberEmailOut.from_directory` is that fact, and the pair separates three cases where one
flag separated two. **The sentences are third person**, because `AddressField` has two
render sites and only one of them is about the reader: an admin reads one of these per
member, so "your directory" names the wrong person on every row but their own. Both critic
seats found that independently, and the first draft of this very table quoted the second
person wording it had just recorded replacing.

| account | `from_directory` | `editable` | what the screen says |
|---|---|---|---|
| local | false | true | "None set." |
| directory, no address attribute | **true** | **true** | the directory supplies none, it can be set here |
| directory, an address attribute | true | false | this comes from the directory, change it there |

**What was deliberately not built: a prompt outside Settings.** A banner on the shelf
asking for an address would be nagging for a field that **sends nothing yet**, which is the
lie `account.email.hint` exists to avoid. The interface is reachable by every account and
states its own emptiness, which is what the owner's instruction asked for.

The condition that reverses this is a sender that reaches a member's own address, and it is
**recorded on #24 rather than here**, because a sentence that stops being true when
somebody builds something is work rather than a decision. This register carries the refusal
and its reason; the tracker carries what would undo it.

## What the three seats caught, this wave

### A fix round wrote an unmeasured reason into the paragraph about unmeasured reasons

**#103.** `backend/tests/COVERAGE.md` states that its per file figures are collected tests
and *not* `def test_` lines, and gives both numbers so the distinction is checkable. A
recount moved the headline and every row and read straight past that sentence, leaving its
companion figure at 2788 against a real 3426, stale by 638.

The correction then added a second reason for the gap: that a `def test_` inside a mutation
fixture is a line that is never collected. **There is no such line**, measured over every
string constant in every module under `backend/tests`, and the arithmetic runs the other
way in any case: 3965 collected exceeds 3426 written, so parametrisation alone accounts for
it and a never collected line could only widen the gap in the opposite direction.

So the paragraph whose whole subject is a number nobody re-derives acquired, in the act of
being corrected, a **reason** nobody had measured. That is the same failure one level up
from the one it records, and it is the third time this register has caught the shape: a
count goes stale, and the fix for it is written with the same confidence that produced it.
Found by a design critic, which had to read the reason rather than the number to see it.

### Both critic seats found the same two things, from opposite ends

**#111 and #103, the wave's own process note, because `CLAUDE.md` claims this is the
strongest signal the three seat process produces and it is worth having an instance
recorded.** The design seat and the security seat reviewed independently and converged on
two defects neither was looking for: **the roster count had gone stale in fifteen places**,
eleven of them published, and **`fetch._IDENTITY` claimed a live measurement the eighth
source had never been given**, which is the claim the byte cap's whole memory bound rests
on.

They arrived from opposite ends. The design seat was auditing figures against the tree; the
security seat was asking what bounds an outbound request. Neither had the other's findings.

The implementer had already fixed four of the count's fifteen sites and believed the job
done, which is the mechanism this register keeps recording: **a number stops being
re-derived and starts being copied, and the person copying it is usually the one who
corrected it last.**

## The Czech National Library, and a server that renders one record a page

### The search path is refused because the server renders one record per response

**#112.** This target pads a page with `zs:record` elements that carry a packing and
a position and no `recordData` at all, and populates exactly one, always the last.
Measured 2026-08-31 across three queries and four page sizes: data at position 2 of 2, 3
of 3, 5 of 5 and 20 of 20, every time. Over eight title searches at fifty records, **391
of 400 records came back empty**. Asked one at a time, positions 1 to 12 all carry data,
12 of 12. No parameter changes it: `recordSchema=dc`, `marcxml` and `usmarc` are all
refused with "Unknown schema for retrieval".

So a title search showing ten candidates would be **ten sequential requests** to somebody
else's free catalogue inside a 4.0s shared deadline. An ISBN lookup wants one record and
gets one: 20 of 20 on ISBNs harvested from this catalogue's own records and put back
through `@attr 1=7`, p90 0.137s.

**The source goes in as lookup only**, which the roster already expresses: `LOOKUP_SOURCES`
and `SEARCH_SOURCES` are separate sets and the BnF and the Library of Congress are already
search only. This is the first of the mirror kind.

**`SEARCH_SOURCES` stops being `frozenset(DEFAULT_ORDER)`.** Its comment said every source
answers a title search and that is now false, so it is written out and
`TestEveryTargetResolvesToADoorAndAReader` checks that every row's stated
capability has a reader behind it.

**This is a narrowing of the ticket and it is not silent**, which is the rule: the ticket
asked for an adapter, a parser and a provider entry, and it could not have anticipated the
record rendering, because nothing had asked this target for a page of records before.

### The ticket named the shape correctly, and the first fix dismissed it

**#112.** The ticket said `_CQL_UNSAFE` does not contain `@` and that `@1=1016 harry`
survives `_search_terms`. Both true, and **both were the danger**, which this entry
originally denied. It was headed "the injection is in PQF's booleans, not in the shape the
ticket named" and argued that only `@and`, `@or`, `@set` and their siblings mattered,
because `_CQL_UNSAFE` strips `=` so `@attr 1=4` cannot be reassembled out of a term.

The stripped `=` part is right. The conclusion drawn from it is wrong, and the measurement
refuting it was already in this repository, three days old: `z3950.pqf_term` records that
YAZ tests for an escape character followed by a digit **before** the quoted run is read, so
`@1=1016` needs no `=` reassembly and no space-preceded operator keyword. It survives
quoting and repins the use attribute from inside the literal. The live measurement offered
as proof here used `@attr 1=1016`, the spaced form, which **is** inert once quoted. The
sharp form was never fired.

**So the first fix was a second PQF rule that disagreed with the first.** `metadata`
carried a local `_pqf_literal` removing the double quote and nothing else, on the stated
ground that a quote is the only character able to end a PQF literal. `z3950.pqf_term`
escapes `"`, a trailing `\` and `@`, each for a measured reason. Two rules, one measured
and one reasoned, differing on two shapes of three.

**The rule now lives once.** `z3950.pqf_term` is public and `_nkp_query` calls it;
`_pqf_literal` is deleted, and a test asserts it stays deleted rather than asserting the
two agree. `z3950.py` imports only the standard library, so there was never a cycle to
justify the copy.

**What generalises is not "check for a duplicate".** The local rule was argued for at
length as a deliberate refusal to reuse `_CQL_UNSAFE`, which is a CQL constant and
genuinely wrong for PQF. That refusal is correct and is kept:
`test_the_cql_sanitiser_leaves_every_pqf_operator_intact` still asserts the coincidence is
not leaned on. The error was treating a correct refusal to reuse the **wrong** rule as
licence to write a new one without looking for the **right** one. The tell is a docstring
that justifies a fresh guard by naming what it declined to depend on and never naming what
it searched for.

### The tier rule counts concentration, not frames

**#112.** `TIER_FRAMES_MINIMUM` asked a source to answer in at least two of the ten frames
before it could be asked on every lookup. It is retired, and `TIER_MAX_CONCENTRATION`
replaces it: **at most two thirds of a source's answers may sit in its single largest
frame.**

**The rule was changed rather than the constant raised, because the Czech catalogue passed
the old rule while being the exact shape it was written to exclude.** Measured over the
committed 500 ISBN survey: the NKP answers in **six** frames of ten, so a two frame floor
admits it comfortably, and **49 of its 59 answers are Czech**. The NLG, whose 37 answers
are all Greek, failed the old rule on one frame. Two sources with the same defect, and the
old metric caught one of them.

Counting frames answers "how many places did it appear". What the tier needs to know is
"how much of it is one place", and those come apart precisely on a national catalogue with
a thin international tail, which is what every national catalogue is.

**What the bound decides is the tier's size, not its membership**, and that is worth
stating because a guard asserting membership would pass with the rule deleted. The rate
rule already puts K10plus and the DNB in the top two at every bound from 0.49 to 1.05. What
moves is whether a third concurrent slot earns its place: with the rule on the third slot
answers **1** book of 500, and with it off it answers **34**, against a bar of 10.

**The bound sits at two thirds, 42% into the gap** between the most concentrated source it
keeps (the OeNB at 55%) and the least concentrated it excludes (the NKP at 83%). The margin
on the *size* decision ends at that upper edge rather than running to 1.0, which is a
narrower safety margin than `FIRST_TIER_BUDGET_SECONDS` has and is recorded because the two
read like the same kind of number and are not.

**A library in any of those countries can still promote its own national catalogue**, which
is what the provider list is for. The default is what nobody chose.

### An internal document declares itself, and the publish gate checks both directions

The publish gate strips a deny list, and a deny entry is configuration: delete the line and
the file publishes with nothing failing. That has happened once, to a document whose entry was
removed in `346094a`.

So every internal document opens with this line, verbatim:

> **This file is internal.**

**That quotation is deliberate and is this bound's regression case.** It is written in the
exact form a declaration takes, at the start of its line, so the detector's pattern matches it.
What stops this published register from failing the build is that the check is bounded to each
file's header, and this sits thousands of lines down. **Remove the bound and the gate rejects
the document explaining why the bound exists.**

The contract runs both ways: before the strip, every denied document must carry the
declaration in its header; after the strip, no published file may carry one. A deleted deny
line fails the second, a new internal document without the sentence fails the first, and
rewording the sentence fails the first for every document at once, which is intended.

**A guard that exits non zero is not thereby a guard that ran**, and that cost the most time
here. **The gate reads the committed ref, not the working tree**, so both halves must read the
same thing or one of them is checking a tree that does not exist.

**Left open, stated rather than discovered**: a document that is never denied and never
published is invisible to both halves.
### The Czech catalogue is plaintext, and it is on the scan path

**#112.** `aleph.nkp.cz` answers on port 9991 with no TLS endpoint, so it joins the Library
of Congress and the National Library of Greece. Accepted on the same terms as Greece, and
the terms are worth restating because this one is **asked on every scan** where the Library
of Congress is not: `fetch` walks redirects itself and refuses any hop that changes scheme,
host or port, so an on path attacker cannot turn one plaintext request into a request
somewhere else. Substituting a record is still open to them, and the identity check is what
bounds the damage: a returned record is used only when it claims the ISBN that was asked
for.

**The count of plaintext sources is now recomputed rather than written down.** This entry
exists because the previous two each stated a total in prose, and both went stale when this
source landed: `docs/legend.md` said two, `docs/security.md` named two, and a `metadata.py`
docstring said "the one catalogue here reached over plaintext HTTP" while three were
configured. `TestThePlaintextSourcesAreCounted` derives the set from `metadata`'s own
module level endpoint values, every one of which is a plaintext URL, and
fails when a doc disagrees, which is the standing house move of turning a claim that has
gone stale twice into a test.

### A refusal written in two languages was refusing in two languages

**#112.** `metadata._NOT_A_BOOK` keeps a digitised copy off a shelf by matching
`online[- ]?(?:ressource|resource)` and `elektronische ressource`. The Czech is **`online
zdroj`**, which matches none of it and which appeared in the first record ever probed from
this catalogue. So the refusal was scoped to German and English without saying so, and
silently, for every catalogue that is neither.

**Fixed for this source only, deliberately.** Widening the shared pattern is the tempting
move and it changes what six other sources refuse on the strength of a phrase measured
in one catalogue. `_NKP_ONLINE` states this source's own and a test pins that the shared
rule is untouched. **Whether the rule should be per source everywhere was a real question
and a larger one than this ticket.** It is answered below, in "The record's own carrier
code decides, and prose is the fallback": per source exactly where the record declares no
carrier, which is this source and the BnF and nowhere else.

---

## The committed client is generated only by the pinned toolchain, and the script enforces it

Owner's decision, 2026-08-31: the development host's bun is upgraded to match the pin
rather than the generation being moved to CI.

**The generated API client is a committed artefact and CI diffs it against a fresh
generation**, so the toolchain that writes it has to be the toolchain that checks it.
Until this date the client generation script ran whatever `bun` was on the machine. Here that was
**1.3.14 against the 1.4.0 the build pipeline and the `Dockerfile` pin**, and the
consequence was not a failure but a wrong artefact: the older bun rewrote
`frontend/bun.lock` down to lockfileVersion 1. Nothing errored. A session following this
repository's own instruction to regenerate after a schema change would have committed the
downgraded lockfile.

**The 806 line diff that arrived with it was blamed on the same cause by three seats in a
row, including this entry, and that was wrong.** It reproduces on bun 1.4.0, from a
`--frozen-lockfile` install, with `frontend/openapi.json` byte identical and `bun.lock`
unmoved: 846 insertions and 330 deletions across eight endpoint files, 806 of them in
`books.ts`. **The committed client was generated by orval 8.24.0 and `bun.lock` pins
8.26.0**, so it has been stale against its own generator since before any of this, and the
number is a real difference rather than corruption.

**The first attempt at this guard could not see that, and the false negative is the lesson.**
Generating on the correct bun produced no diff and was quoted as proof the tree was clean.
It was proof of nothing: the run used a `node_modules` holding the same stale orval that
wrote the committed client, so the artefact was being compared against itself. **A version
check on the interpreter says nothing about the generator it loads**, which is why the
script now installs `--frozen-lockfile` before generating rather than trusting whatever is
on disk.

**Three drifts, not one, and only the first was known when this guard was written**: the
interpreter against its pin, the installed tree against the lockfile, and the committed
client against the generator that would write it today. The third is not this script's to
fix and is on the tracker.

**The first is the mirror image of a drift the test harness already refuses, and the
pair is the reason the guard is worth its lines.** There, the old bun could not *read* a
lockfile the new one wrote, so the harness broke loudly while CI stayed green. Here the
old bun happily *wrote* one, so the harness stayed green and the artefact broke. **A
version check that catches only the loud direction is half a check.**

**Refusing rather than warning**, for the same reason that file gives: the whole value of
the script is that what it writes is what CI will accept, and on a mismatch it guarantees
nothing.

**The guard is pinned by its diagnoses, not by its exit status, and that was measured
rather than assumed.** Three of its arms are shadowed by the version comparison: an
unreadable pin and a missing bun both leave a variable empty, and empty never equals the
pinned version, so with any one of those arms deleted the run still refuses. A diagonal
mutation run found exactly that, three arms surviving against tests named for them, which
is this repository's recorded shape of a fixture named for what it tests being no evidence
that it tests it. The tests now assert the message, which is what those arms exist to
produce: without them the shadowing arm reports `runs bun , the pipeline runs bun 1.4.0`.
Six mutations, six caught, each by the test named for it.

**Why the upgrade rather than generating in CI.** There is no container runtime on the
development host, and the suite runner deletes its container on exit, so a command that
*writes* has no effect on the tree and reports success anyway. That left no correct way to
run `api:generate` at all, which is a worse state than a slow one.

---

## A national catalogue is asked only about the registration groups it collects

**#122.** The second phase of a lookup asks one source at a time and stops at the first
hit, so a catalogue that cannot answer this ISBN is a round trip spent in front of
whatever would have. Two of the four sources in that phase are national.

**What was refused, and it is the design a reader proposes first.** Demoting a non serving
source to the back of the phase, and skipping it but sweeping the skipped ones when nothing
was found, are the same design and both save nothing: 1.3959s against 1.3964s. The reason
is structural. A phase that stops at the first hit only pays a dead source when something
behind it answers, and on the rows where nothing answers every source is asked whatever the
order. **The whole saving is on the lookups that fail**, 123 of the 500 sampled, and
ordering cannot reach them.

So the saving and the risk are one mechanism: making a failed lookup cheap is what risks
turning a successful one into a failed one. The trade is bounded rather than avoided.

**The bound is zero and is not a threshold.** A catalogue may declare a remit only where
there is no book it alone answers outside it. There is no gap to place a value in, because
the objection the whole rule has to answer is that a catalogue quietly stops being asked
about a book it holds. Measured on the committed sample: the NLG answers nothing at all
outside its two groups, the OeNB answers five and the leading pair holds every one of them,
and the NKP answers two that nothing else in the roster holds. The NKP is therefore refused,
and it would have been the largest single saving.

**Where the groups live: a per source constant, not a per install setting.** Which groups
the National Library of Greece collects is a fact about its statutory remit and is the same
in every household. The provider list's vocabulary is position and on or off, both of which
are household facts. The third state is derived for display, not stored for editing.

**Four fail open paths, each deliberate.** A source with no declared remit is asked about
everything. An ISBN whose registration group this build cannot decode is offered to every
source, which is why `isbn.registration_group` returns None rather than guessing, and why
its range table is deliberately narrow: a narrow range makes an answer unknown, a wide one
makes it wrong. So is an ISBN in a Bookland prefix no remit mentions. And the leading pair
is never filtered, so a library that promotes a national catalogue there has it asked about
every ISBN.

**The prefix arm is the one both critics found and it was a real hole.** `978` and `979`
are separate assignment spaces. A remit listing only `978` groups is **silent** about `979`
rather than negative about it, because a catalogue whose country has no `979` group yet has
no way to spell "none". Without that arm every `979` ISBN lost both national catalogues,
and nothing measured it: all 500 rows of the committed sample are `978` and every one of
them decodes, so the zero book bound was measured over one prefix and the two fail open
paths the design rests on were exercised by no sample row at all.

**The two tables fail in opposite directions and that is the thing to carry away.**
`isbn._GROUP_RANGES` is narrow because an unknown range there decodes to None and every
caller reads None as "ask", so narrow makes an answer unknown rather than wrong. Inside a
prefix `SERVES_GROUPS` names, a group it does not list is a **skip**. "Widen it late rather
than early" is right for the ranges and exactly wrong for the remits: a group missing from
a remit costs books, and dropping `978-618` from the National Library of Greece loses seven
of the fifty sampled Greek ISBNs.

**`serves_groups` on the wire is the remit declared, not the filter applied.** A catalogue
promoted into the leading pair reports its remit and is asked about every ISBN anyway, so
`asked_first` is the field that answers "is this filtered" and has to be read first. Three
documents said otherwise before two critics measured the plan that shows it.

**A registration group is variable length and cannot be read off a string prefix.** `978-6`
is not a group: Greek `978-618` and Brazilian `978-65` both begin with a 6. A survey script
written while measuring this ticket made exactly that mistake, filed 23 of 500 ISBNs under a
group that does not exist, and produced a plausible table with nothing failing.

**What this changes about an older claim.** `sources.DEFAULT_ORDER` says no order of the
roster finds more books than another. That is still true and is now conditional on the
remit rather than absolute: a national catalogue below the leading pair genuinely is
unreachable for a foreign ISBN. The condition costs zero books by the bound above, and
`backend/tests/test_metadata.py::TestNoOrderOfTheRosterFindsMoreBooks` now asks each holder
about a book in its own group rather than one English ISBN for all of them.

## An `isdigit()` guard does not make an `int()` safe

**Found while reviewing #122, unrelated to it, and fixed with the ticket per CLAUDE.md.**
`str.isdigit()` is true for every Unicode digit, and the two halves of that fail in
opposite directions: `int()` **raises** on a superscript two and **accepts** an
Arabic-Indic zero. So the same predicate produced a 500 on `GET /api/books/lookup` and a
silently stored non ASCII ISBN on `POST /api/books` that `uq_books_isbn_single_copy` could
not match. `dependencies.row_ids` had the crashing shape on a query string.

**The helper was the obvious fix and is the weaker one.** An `is_ascii_digits()` that four
modules import is bypassed by anybody writing `.isdigit()` directly, which is what five
call sites had already done.
`test_house_rules.py::TestADigitPredicateIsAlwaysNarrowedToAscii` requires an `isascii()`
call on the **same receiver** in an enclosing `and` at every digit predicate in every
backend module, which cannot be bypassed by writing the ordinary thing.

---

## A subject carries the vocabulary a record declared, and the store is a separate question

`catalogue.Subject` replaces the bare string a `Record` used to carry, with the `$2` code
the record declared and the `$0` value it gave. Nothing is stored: a subject still reaches
the database as words, in `books.categories`.

**Why the store is not here, when the ticket named one.** `classifications` cannot hold it:
`scheme` is a closed four member enum and everything that sorts, filters and orders a
heading reads it, where a declared vocabulary is an open set. Twelve distinct codes turned
up in one day's sampling of four catalogues (`bellobv`, `bisacsh`, `DLC`, `fhv`, `gatbeg`,
`gnd`, `gnd-carrier`, `gnd-content`, `local`, `nlgaf`, `nlggf`, `VLK`), against a MARC
source code list holding hundreds, and a table from those onto the enum is the crosswalk
#134 refuses in as many words.

A new `book_subjects` table cannot hold it either, not without retiring `books.categories`
first: both would hold the same labels, and two stores for one fact is the objection that
decides it. Retiring that column reaches 10 backend modules, 12 frontend files, both
importers, both exporters, `backup` and the public shelf schema, counted 2026-08-31.

**So this ticket writes no migration**, against the wave plan's forecast of one, and
nothing here changes a column, a constraint or a table. Growing `ClassificationScheme`
would not need one either: `b8e2f4c7a913` leaves `classifications.scheme` deliberately
unconstrained for exactly that reason.

The tracker had already split the store out. #143 (identifier and scheme types as rows
rather than closed enums) and #140 (a vocabulary declaration format) are the store, #147 is
the filter and the link, #135 is the enforcement. All four name this as their precondition,
and the owner's own comment on #134 says it: "this ticket is about the sources, not the
column".

## `$2` is read on a subject field only, and the signature is what says so

`metadata._subject_vocabulary` takes the MARC tag and raises outside
`_DNB_SUBJECT_TAGS`. `$2` is a subject vocabulary on `600`, `650`, `651`, `655` and `689`
and the **Dewey edition** on `082`, where this repository's own fixtures spell it `23sdnb`,
`22/ger` and `21`, so a caller handing the reader an `082` records a vocabulary named `21`
and nothing fails: the value is a string, the column is a string, and it surfaces months
later as a subject labelled with an edition number.

**A comment said this and a house rule was cited as the pin, and neither enforced it.** The
rule counted readers of the subfield and never saw which field was passed, so the call it
described as impossible was legal and left the rule green. A test in the same wave asserted
that call returns `"21"`.

Two rules now, doing two different jobs, which is the correction rather than a widening:

* **which field**, enforced by the signature, because no source scan can be evaded past a
  parameter;
* **who may read it**, enforced by `test_house_rules.py::TestOneReaderPerAmbiguousSubfield`,
  which matches the `"2"` **constant** with a two entry allowlist rather than a list of
  spellings.

The spelling list was the wrong shape and measurably so. It enumerated `get`, `all` and a
subscript, "three spellings because `_Subfields` offers three"; `_Subfields` subclasses
`dict`, so it offers every dict reader, and 8 of 10 shapes carrying a literal `"2"` went
unreported, `e.pop`, `e.setdefault`, `dict.get(e, "2")`, `getattr(e, "get")("2")`,
`e.get(*("2",))` and an `items()` loop among them. The denominator that makes the
structural rule affordable is that the whole backend carries **two** `"2"` constants
outside docstrings, one reader and one writer.

## The vocabulary code is lower cased for `marc._extra_headings`, not for the catalogues

`metadata._subject_vocabulary` folds case, and the first version of that comment said two
catalogues motivated it. They do not: 0 of the twelve `$2` codes measured appeared in two
cases, and the two upper case ones are each written by one catalogue only, `VLK` by the
OENB and `DLC` by K10plus. **The dependency that actually breaks is
`marc._extra_headings`**, which decides an LCSH heading by `== "lcsh"`, so an uploaded file
writing `$2 LCSH` loses every one of them silently with the record otherwise whole. That is
now pinned by a test rather than by a comment, and a cataloguer's own export is exactly
where the shouted spelling lives.

## An undeclared repeat folds away only when it adds nothing

`catalogue._restates` decides it, and the identifier clause is the whole rule. Over the 169
live (record, label) pairs carrying a declared and an undeclared occurrence together, the
undeclared entry the rule is handed carries the identical identifier 147 times, none at all
20 times, and a **different** one 2 times, which sums to the 169 and is stated so that it
can be checked. The rows are per pair and not per occurrence: the fold collapses every
undeclared occurrence of a label into one entry before `_restates` runs. Both of those two are the OENB writing
`650 $a Osterreich $2 VLK $0 (AT-VLB)LA01044691` and, on the same record,
`689 $a Osterreich $0 (DE-588)4043271-3`.

**Filling the identifier across the fold is the obvious repair and is refused**: writing
the GND number onto the `VLK` entry asserts that it identifies a heading in the Vorarlberg
list, which is a crosswalk between two vocabularies. The two stay side by side instead.

## A subject label keeps the place of its first occurrence

`categories` is joined from these labels and is **stored on the Book**, so a person reads
the order. The first fold emitted surviving entries in key order, so dropping an undeclared
entry that came first moved its label to wherever the declared one sat, and
`Roman; Informatik` became `Informatik; Roman`. Grouping by label fixes it and stays
linear, because a dict preserves insertion order and a label's first key is inserted at its
first occurrence.

The comment that let this through said "nothing reads the order", listing `as_match` as a
consumer in the same sentence. A human reading a joined string is reading the order.

## The first `$0` is the authority file's number, and `_gnd_identifier` asks a different question

`_subject_identifier` takes a field's **first** `$0`, whole. Measured 2026-08-31 over 718
live subject fields carrying one: where a field carries a `(DE-588)` at all it is the first
of that field's values, 691 of 691, with the `d-nb.info` URL and the `(DE-101)`, `(DE-627)`
and `(DE-576)` house numbers always following; the other 27 carry exactly one `$0` each and
no `(DE-588)`. So no prefix list is needed, and an enumerating guard is what one would be.

**It takes the first `$0` that has a value, and the measurement is not the reason for that
clause.** 691 of 691 counts values as served and says nothing about an element with no text
standing in front of them, because an empty `$0` is not something a catalogue writes: it is
what `_marc_text` makes of `<subfield code="0"/>`. Recounted for this, 0 of the 718 fields
carry an empty `$0` anywhere, so the sample could not have shown it. Reading
`values[0] or None` answered None where `_gnd_identifier`, which scans every value, found
the number and wrote a classification row, so one field produced a heading with an
identifier and a subject without one.

**`_gnd_identifier` is unchanged and still searches every `$0` for a `(DE-588)`.** The two
are different questions rather than one rule spelled twice. That one decides whether a
`classifications` row is written, and that row's `scheme` is a closed set, so a `(DE-101)`
number filed under `gnd` would be an identifier resolving to nothing. This one asks what
the record gave, whatever file it names.

**The identifier keeps its prefix where `Classification.number` drops it**, and that is the
opposite rule on purpose. There the prefix duplicates a scheme column. Here there is no
scheme column and the prefix is the only thing saying which file the number is in: `$2
gatbeg` arrives with `$0 (DE-101)1010008188`, which is the DNB's genre list and the DNB's
own file, two different answers.

## A label under two vocabularies is two subjects; a label restated undeclared is one

Measured over 765 distinct (record, label) pairs from live DNB, OENB, NLG and K10plus
records on 2026-08-31.

* 15 pairs carry one label under two declared vocabularies. `Wörterbuch` is a `gnd` subject
  and a `gnd-content` form type on one record. Folding them asserts one vocabulary's
  heading is the other's.
* 169 pairs carry one label both declared and undeclared. That is the `689` restatement,
  and folding them apart puts one word on the wire twice.

So identity is (label, vocabulary), and an undeclared occurrence of a declared label folds
away. That is not inference: it gives no undeclared value a vocabulary, it drops a second
copy of a string the record already wrote, which is what the plain string deduplication it
replaced did for every case.

`Record.subject_labels` deduplicates a second time for the two consumers, because neither
`categories` nor the tag suggestion can use the distinction and the first would show one
word twice.

## `$2` means a vocabulary on a subject field and a Dewey edition on `082`

`metadata._subject_vocabulary` is the only place in the backend that reads a `$2`, and
`test_house_rules.py::TestOneReaderPerAmbiguousSubfield` counts rather than trusting the
comment saying so. A second reader taking `$2` off whatever field it had in hand would
record a vocabulary called `21`, which is what this repository's own NLG fixture writes on
its `082`: the value is a string, the column is a string, and the mistake surfaces months
later as a subject labelled with an edition number. `marc.py` held a second copy of the
lower casing rule and now calls the one reader.

---

### Every Python file is compiled, and the warning is recorded rather than raised

`backend/tests/test_house_rules.py::TestEveryPythonFileCompilesWithoutAWarning`
compiles every non vendored `.py` under `backend/` and fails on any warning the
compiler emits, naming the file, the line and the category.

Four calls the ticket left open, each answered in the code beside the rule.

**Scope is every Python file, not `_python_sources()`.** The two existing walks
drop the tests, and one drops the migrations too, because the rules that use
them are about application semantics where a fixture has no share. This rule is
about a file loading at all. A migration that will not compile stops
`upgrade_to_head()`; a test module that will not compile takes every house rule
with it. The defect that raised the ticket was a bare escape in a docstring in
`test_house_rules.py` itself, which `_python_sources()` does not return, so a
guard scoped to it could not have caught its own subject. `_every_python_file()`
is therefore one walk and one exclusion rather than a list of directory names.

**Recorded, not raised.** `simplefilter("error", SyntaxWarning)` never surfaces a
`SyntaxWarning`: CPython converts it and raises `SyntaxError`, so `except
SyntaxWarning` catches nothing, and compilation stops at the first warning in
the file. Recording reports every warning in a file, so one fix round clears it.
Measured on one fixture: 2 recorded against 1 raised.

**ruff's `W605` is the fast path and the test is the backstop.** ruff already
reported the same escape with a column and an autofix and was simply not
selected, which is the whole reason the premise held; it is selected now, as
`extend-select` rather than the whole `W` family, which reports one further
finding, a trailing whitespace in a generated Alembic header. That does not
retire the test, and the reason is a shape rather than an overlap: a `select`
list is an enumeration, covering the warnings somebody has written a rule for
and no others, while the test asks the compiler, so a category CPython adds next
release is caught with no rule to select.

**No `filterwarnings` line in `pyproject.toml`, considered rather than
overlooked.** Measured 2026-09-02: importing a module holding a bare escape warns
once and is silent on every import afterwards, because the second import loads a
`.pyc` and never compiles the source. An ini setting would pass or fail on
whether a `__pycache__` happens to exist, which is the environment deciding the
verdict. Compiling the source explicitly has no such hole, and it also reaches a
file nothing imports.

Measured 2026-09-02: 173 non vendored `.py` files under `backend/`, 0 warning and
0 failing to compile, partitioning as 67 from `_python_sources()`, 74 from
`_test_sources()` and 32 under `migrations/` with no remainder. Derived five ways
that share no code: `pathlib.rglob`, shell `find`, `git ls-files`, mypy's own
"173 source files", and `pytest --collect-only`.

### Every field a request body carries is bounded, and the value comes from one place each

`BookMatch` is the body of `POST /api/books/{id}/enrich/apply` and also the response of
`GET /api/books/search` and `/{id}/enrich/candidates`. Being a response is why it looked like
one: four of seventeen fields carried bounds, under a comment saying they matched
`BookCreate`'s, which was true of the two fields it sat above and false of the rest.

**A bound is never taste.** Each comes from the column, from `BookCreate` for the same
column, or from a stated derivation.

| Field | Bound | Source |
|---|---|---|
| `title`, `subtitle`, `author`, `cover_url` | 500 | `BookCreate`, same column |
| `publisher`, `series_name` | 255 | `BookCreate`, same column |
| `isbn13` | 20 | `BookCreate.isbn`, same column under another name |
| `language` | 10 | the column |
| `description` | `DESCRIPTION_MAX` | agreed with `BookCreate` |
| `series_index` | `ge=0, le=1000` | `BookCreate`, same column |
| `google_books_id` | 50 | `books.google_books_id` is `String(50)`; a volume id is 12 characters |
| `categories` | `CATEGORIES_MAX`, 3,902 | derived below |
| `source` | `SOURCE_LABEL_MAX`, 120 | no column behind it; derived |
| `suggested_tag_ids` | 500 entries | finiteness, not a measured shape |
| `year`, `page_count`, `classifications` | unchanged | already bounded |

**`max_length` on a `list` is a count, not a length.** `suggested_tag_ids` was
`list[RowIdField]`, which bounds every entry's value and nothing about how many.

**`series_index` is the one that matters.** `google_books.merge_into` writes it and
`routers/books.list_series` computes `set(range(1, max(held) + 1))` over it, so a stored
`1e9` is roughly 70 GB and ten minutes, per member, per request, until somebody finds the
row. Measured in `importing.py` at 70.5 bytes and 0.624s per million elements.

**`CATEGORIES_MAX` is `32 * CLASSIFICATION_NUMBER_MAX + 31 * 2`, which is 3,902**, written as
the expression so the number and its sentence cannot drift. 32 headings, because the two
failure modes are not symmetric: too loose costs page weight (25 books at 3,902 is 97,550
characters), and too tight drops a whole search result silently, since `_match_rows` drops
the row rather than the field. The widest shape measured here is 14 headings at up to 91
characters, about 1,300, so the bound clears it 3x.

**`BookCreate.language` was 16 against a `String(10)` column and was narrowed rather than the
column widened.** SQLite ignores VARCHAR width, so the disagreement refused nothing and was
invisible: the API accepted six characters no width enforcing engine would store. The longest
tag anybody wants, `zh-Hant-HK`, is exactly 10. `importing.py` reads both widths and takes the
smaller, as a deliberate cross check.

#### The guard is three questions asked of every request body, not a table of fields

Scope comes from walking the routers rather than from a list, so a new body is in scope by
arriving. A ceiling is detected by **executing the field's own validation** rather than by
reading its annotation, which is what makes it work for a constrained type it has never seen.

#### `BodySizeLimitMiddleware` promises a bound it does not apply, and the gap is stated

Its two rules never see a chunked JSON body: rule 1 needs a `Content-Length`, which such a
request does not declare, and rule 2 is multipart only. The deferral to "the route's own
parsing" is empty, because a schema runs only after Starlette has accumulated the whole body
in memory. **Closing it means wrapping `receive` to count bytes and refuse mid stream**, which
changes every request with a body and belongs in its own change. The schema bounds are the
other half and are the half that was missing.

#### Two bounds this entry does not close

**`POST /api/books/{id}/enrich` writes catalogue values with no bound at all.** It hands
`Record.as_match()` to `merge_into` without building a `BookMatch`, so `series_index = 1e9` is
stored with a **200** where the same value on `/enrich/apply` is a **422**. Catalogue
reachable, not upload only: `metadata._marc_title` takes the first digit run of `245 $n` and
calls `float()`. The fix cannot live here, because `google_books` importing the declarations
is circular, and the comments now say which of the two routes is closed rather than implying
both are.

**`POST /api/books/bulk` answers 500 to a large tag id.** `_require_tag` does `int(str(value))`
and hands it to `db.get`, where `10**19` raises `OverflowError` from the driver, while its
sibling `_checked_collection` range checks against `MAX_ROW_ID` and names this failure as its
own reason.

**The lookup fold is two records, not nine.** `Record.merged_with` unions subjects on the
lookup path only; every path constructing a `BookMatch` folds with `filled_from`, which takes
the leading catalogue's list whole.
### The roster count is guarded by a census with a verdict, not by a scan and not by a list

The size of the catalogue roster is spelled in prose at dozens of sites, and adding one
source made twenty two statements stale, found in three passes, every pass believing it was
the last.

**"The roster count" is not one number.** Six named cardinalities over four values, all
computed from `sources.py`: the whole roster and `DEFAULT_ORDER` at 9, `SEARCH_SOURCES` at 8,
`LOOKUP_SOURCES` at 7, the free lookup sources at 6, lookup-or-search at 9. So "six sources"
is a correct free lookup count, a correct count of something else, or a stale search count,
and nothing in the sentence's shape separates them. **The classification is semantic, so a
person makes it once and a machine notices when it needs making again.**

**The shape: a census, and a verdict for everything it finds, enforced both ways**, in
`backend/tests/test_roster_counts.py`. The census matches a number, at most two words and a
roster noun, and admits a candidate only if its **value** is one of the live cardinalities, so
the bound is derived and widens on its own. Every candidate carries a verdict in `CLAIMS`,
keyed on the file plus the phrase **with the number elided**, so the table holds no counts and
correcting a stale sentence needs no edit to it. An unclassified candidate fails, a verdict
matching nothing fails, and a `KnownStale` that has been corrected fails.

**Rejected: a blanket scan.** Most occurrences count something that is not the roster, so an
unclassified scan fails on its first run at that scale and is switched off within the day.

**This register is inside its own subject**, and the pruning of 2026-09-05 is what proves the
arrangement works: entries were rewritten, the sentences several verdicts were written for went
with them, and the guard failed rather than going quiet. The census raises 4 candidates in it.
**0** are live claims the guard now checks against `sources.py`; **4** are not the roster,
being this entry's own worked examples and two sentences about what a shared pattern would have
changed. All three figures are recomputed from the verdict table rather than reread.

**Rejected: an enumeration of sites.** A list of regexes goes stale exactly like the numbers
and does it silently: the site nobody adds is the site nobody checks. `CLAIMS` is not that
list, because it does not decide **where the guard looks**. The census does, over the whole
tree, and fails on anything `CLAIMS` has not judged. The difference is the direction of the
failure.

**A date is not the exemption rule, and that was measured rather than assumed.** The obvious
rule is that a count naming a date is history and may disagree; measured over the census, the
occurrences carrying a date held both correct exemptions and a stale claim. What separates
them is tense and subject, not the date. **The exemption for a historical count is therefore a
verdict whose subject names what was counted**, not a pattern match on a year.

**Both spellings, in `backend/` and in `docs/`.** Every stale site in the original incident was
spelled rather than digits.

Every figure this guard quotes lives in its own module docstring and is deliberately not
copied here: a count in this register is a count nobody recounts, and this file is itself in
the census.

**`CHANGELOG.md` is out of scope.** Every entry in it is dated by construction, so a count
there is history by definition.

#### The hole a reviewer should know about

**A verdict changed from `Counts` to `NotTheRoster` silences a real failure**, and no rule
catches it, because the guard cannot know what a sentence means. That is the cost of the
semantic classification and it is accepted rather than hidden: review a verdict change the way
you would review a deleted assertion.
## A stale count outside the census grammar is fixed by rewriting the sentence, not by widening the census

`backend/tests/test_roster_counts.py` finds a number written beside a roster noun and
demands a verdict for every one it finds. Three counts sat outside that grammar and were
stale: a route docstring with the noun elided, "searches all seven", and two comments
counting "entries" of a row rather than sources.

The obvious two options were both refused. **Widening the grammar** costs more than it
buys, measured: matching a bare number after "all" at a live cardinality, and "the other
N", between them find several dozen occurrences the census does not already see, almost
all of them palettes, routes, call sites and authority schemes that would each need
classifying forever. Both counts are snapshots and live in the guard's docstring, for the
reason the entry below gives. **Leaving them unguarded and saying so** is what the previous wave
already did, and it is what let all three go stale.

So the sentences were brought into the grammar instead: each now names the set it counts,
the census sees it, and a `Counts` verdict compares it with `sources.py` on every run. The
cost is that it constrains how those sentences may be written, and a claim whose subject is
a position or a sub count cannot be rewritten as a size without lying, so this does not
generalise to every blind spot.

**What makes it more than a prose fix is the census's other direction.**
`test_every_verdict_still_has_a_claim_to_judge` names a verdict that judges nothing, so
rewording a sentence back out of the grammar fails a test rather than going quiet. That
rule was already there and is now driven by a test of its own rather than only observed
against the live tree.

---

## Four figures in the roster census are snapshots rather than recomputed, deliberately

The census size, the size it would reach under a widened bound, and the two figures beside
them counting what the refused widenings would newly have to classify, are snapshots. A
test asserting one would count sentences across the whole tree, so it would go red on an
edit to any unrelated paragraph, which teaches a reader to change a number until the
failure stops. What is stated instead is the multiple, which moves least: roughly four
times as many occurrences.

**The current values are in the guard's own module docstring and are deliberately not
copied here.** They have now drifted three times: written as 57 and 228, found at 64 and
238, and again once this register itself came into the census. Every drift was
found by somebody recounting rather than by anything failing, which is what a snapshot
costs and why the docstring now carries the instrument beside each figure. A second copy
in this register is a copy nobody recounts, and this entry was one for a day.

---

## `merge_into` takes a `BookMatch`, not a dictionary

Two routes write catalogue scalars onto a Book, and until 2026-09-03 only one of them
passed the bounds. `POST /api/books/{id}/enrich/apply` takes a `BookMatch` as its body, so
every ceiling on that model applied; `POST /api/books/{id}/enrich` assembled a plain
dictionary from `catalogue.Record.as_match()` and handed it straight over. The identical
oversized value was a 422 on one route and a stored row on the other.

The bound is on the **signature** rather than at the call site, and that is the whole point
rather than tidiness: a rule a caller has to remember is exactly the rule the second route
failed to follow. `google_books.merge_into(book, match: BookMatch, *, overwrite)` fails
mypy for a dictionary at any call site and raises on the first `getattr` at runtime, so a
third call site inherits the bound instead of having to be told about it.

The import is `TYPE_CHECKING` only and cannot be otherwise: `schemas/book.py` imports
`split_categories` from `google_books`, so a runtime import there is a cycle. PEP 649 is
why the annotation still needs no quoting, and Python 3.14 is already required for the same
reason elsewhere.

---

## The enrichment door drops the field; the search door drops the row

`routers/books._match_rows` and `routers/books._bounded_match` both build a `BookMatch`
from third party data and they refuse differently, which is deliberate.

A search answers with a page, so a record the schema refuses costs one result out of
several and dropping it whole is honest. Automatic enrichment answers with the one record
the catalogues returned, so refusing it whole would report `found=False` about a book they
did find, and lose eleven good fields to one bad one: `merge_into` writes twelve columns,
eleven loop names plus `cover_url`, and one of them is the refused one. The field is
dropped and logged at INFO instead, which is the only place a dropped field is recorded:
the response cannot show it.

Which fields get dropped comes from pydantic's own error locations rather than from a list
of names in the helper, so a bound added to `BookMatch` later is enforced on that path with
nothing to keep in step.

Three details of that loop are load bearing and each was bought by a mutation that survived
without it. The refused names are intersected with the record's own keys, because pydantic
reports a **missing** required field at a `loc` naming a key the record never sent, and
deleting a key the record does not hold raises `KeyError`. The fallback builds the empty
match without validating, because a required field also makes `BookMatch()` raise and that
would turn the safe answer into a 500 on the path that exists to avoid one. And the loop is
bounded at one pass per key plus one rather than written `while True`, because a later edit
breaking the shrink invariant then fails a named assertion instead of hanging a suite:
measured, the two mutations a bounded loop reports by name were a run that never finished.
Eight mutations, eight caught, each by a named test.

**That hang is not hypothetical and it cost a control plane.** A critic seat mutating this
very arm on 2026-09-03 deleted the no-field case, its harness's `subprocess.TimeoutExpired`
killed the `uv` parent and not the pytest grandchild, and the orphan spun the unbounded
loop for 53 minutes at 8.6 GB on the machine that runs etcd.

---

## A guard that names two enforcers and has one

`BulkRequest.value` is deliberately untyped, because which field it fills depends on the
verb. Its comment said every handler reading it as a row id range checked before the value
reached the database, and named `_require_tag` and `_checked_collection`. Only the second
one did. `_require_tag` did `int(str(value))` and went to `db.get`, so `2**63` raised
`OverflowError` from inside the driver and answered 500 to any member.

Recorded because the shape recurs here and the comment is what carried it past readers: a
guard proved on one field, trusted for the field beside it, with a comment asserting both.
Counted rather than read, next time, and count the right noun: **three** of the seven bulk
verbs read `value` as a row id (`add_tag`, `remove_tag`, `set_collection`) through **two**
helpers (`_require_tag`, `_checked_collection`). The first draft of this entry said two
verbs, having counted the helpers, which is the same substitution of unit this repository
keeps recording. Derived from `_BULK_HANDLERS` with `ast` rather than by reading.

---

## The series ceiling is applied at the reader as well as at the writers

`routers/books.list_series` builds `set(range(1, max(held) + 1))` over `books.series_index`
under `Shelf.seen_by`, so its cost is linear in a value read out of the database rather
than in the size of the library. Three request bodies bound that column and that is not
enough on its own, for two reasons that both survive the bounds work: `backup.restore`
inserts through Core, where neither pydantic nor a `@validates` fires, and an instance
upgraded from a release before 2026-09-03 carries whatever its enrichment route stored
while that route was unbounded.

Measured on one row at 2,000,000 in a library of one book: `GET /api/books/series` answered
14,888,944 bytes carrying 1,999,999 missing indexes. The fixture that carries the figure
names its series `Restored`, eight characters, because the name is in the JSON and a seven
character name gives 14,888,943: the number is reproducible from the test beneath it rather
than quoted from a handoff.

So the handler truncates the range at `models.MAX_SERIES_INDEX`, which the three bodies now
read instead of each retyping `le=1000`. Truncating rather than refusing keeps the gaps a
member can act on and drops only the part of the range no API path could have produced.

The general rule this is an instance of: **bounding every writer is not the same as
bounding the column**, because a restore is a writer that validates nothing and a released
version is a writer you cannot go back and fix.

---

## The record's own carrier code decides, and prose is the fallback

`_NOT_A_BOOK` was the whole not-a-book rule and every alternative in it was German or English,
so the Czech National Library's `1 online zdroj` matched none of them and an online resource
reached a member's shelf.

**The list of languages is open and the list of record schemas is not.** Five of the seven
sources that answer in a record schema publish a carrier vocabulary: MARC's leader/06, `007`
and `008/23`, and the MODS `physicalDescription/form`, which is MARC's codes in another
spelling. Those need no phrase in any language. Only the two Dublin Core sources carry nothing
and each states its own wording, so **prose is the fallback in exactly two places** rather than
the rule everywhere.

**The bound lives in `Record.__post_init__`, not at the one route that produced the bug**, and
that is the general shape: four consumers read the same record and three already had a bound,
so the one place all four agree is the constructor. The refresh handler needed no change.

**A value too wide loses that field, never the record**, and is cleared rather than truncated,
because half a title is an assertion nobody made and absent is a state every consumer handles.

**A bound on a response model is the 500**, which is why the bound is on the record: a
`ValidationError` raised while constructing a response is not a request validation failure and
falls through to the unhandled handler. A live 10,001 character description is recorded here.

**`source` is deliberately unbounded**, because it is this app's own word rather than a
catalogue's.
## A catalogue record is bounded at construction, not at each door

`PUT /api/books/{book_id}/refresh` wrote nine columns straight off a `catalogue.Record` and
eight of them had no ceiling anywhere: none in the schema, because no Pydantic model sat on
that path, and none in the database, because SQLite does not enforce a `VARCHAR` length.

Two doors were available. Routing that one write through a bounded model, the way the
enrichment route goes through `_bounded_match`, would have closed the route and left the
shape that produced it: **four** consumers read the same record and three of them had a
bound. So the bound went into `Record.__post_init__`, which is the one place all four
agree, and the refresh handler needed no code change at all.

The rule the enrichment work settled applies unchanged, one layer earlier: a value too wide
loses **that field**, never the record, and never 422s a Member's own request. The value is
cleared rather than truncated, because half a title is an assertion nobody made and absent
is a state every consumer already handles.

**The scan endpoint stopped being able to answer 500.** `BookLookup.description` is bounded
and is constructed inside `lookup_isbn`, where a `ValidationError` is not a request
validation failure and falls through to the unhandled handler. A live 10,001 character
description is already recorded in this tree. Bounding the record makes that unreachable;
bounding the response model further could not have, **because a bound on a response model
is the 500**.

**One field is deliberately unbounded and it is `source`**, which is this app's own word
rather than a catalogue's: every producer sets it from a literal, and every source name
this tree ships, joined, comes to 63 characters against a ceiling of 120.

**The second is `isbn`, and it went out, in, and out again inside one day.** It was excluded
because the scan response requires it, so a cleared value 500s a Member's scan. That
exclusion was costing a whole search row, because the search body bounds the field and
`_match_rows` drops the row rather than the field: one record with a 40 character identifier
gives 0 rows against 1 for the same record with a valid one. So it was bounded. That made
the 500 reachable through the same module, because `metadata._google_record` prefers the
unparsed identifier over the canonicalised argument and sits on the ISBN lookup path. One
lost search row was cheaper than the scan route, so the field went back to being unbounded
and the whole trade was written at `_UNBOUNDED` rather than half of it. The one line fix
belonged at that adapter, parsing its own identifier the way both Open Library paths
already do. It landed, and the field is bounded now: see the entry on what makes that safe.

The lesson is this repository's own: a replacement better in the dimension it was designed
for and silently weaker in one nobody re-checked. What found it was a seat attacking the
reasoning rather than reading it.

---

## Two producers of one record, and they differ about one thing

Bounding at construction found what the ticket did not know about: a second producer with
the opposite policy, shipped hours earlier. `marc.py` builds a `catalogue.Record` out of an
**uploaded file**, and `importing.within_bounds` holds it to the same declarations under a
rule of its own: strings truncate, because truncating a title keeps the record and a batch
wants the record; numbers drop, because clamping a `9999` to 2200 asserts a date nobody
supplied.

Both policies are right about different inputs. A catalogue answering over the network
asserts something about a book already on the shelf, and half an assertion overwriting a
good value is worse than nothing. An uploaded file is the Member's own library arriving at
once, and `books.title` is `NOT NULL`, so a dropped title is not a thin record: it is an
`IntegrityError`, a 500 and a lost transfer. Measured before the fix, a 501 character
`245 $a` took the import down where 500 imported cleanly.

So the invariant is the record's and the policy is the producer's. `Record.from_upload` cuts
the readable strings; everything else drops. **Not every string is cut**: a URL, a volume id
and a language code are renamed rather than shortened by a cut, so those drop on both paths.
A test pins that partition exhaustive, and another pins that no module but `marc.py` opens
the truncating door.

---

## A slow catalogue is kept and made opt-in, behind an explicit second search

Owner's ruling, 2026-08-30. An earlier decision ruled a national catalogue out on latency,
10.7s for its title search against a 4.0s fan out, and that was right while there was
nowhere to put a slow source. There is now a provider table with a switch and a position per
source, so "off by default, on for the libraries that want it" is expressible, and dropping
a catalogue that holds domestic editions nothing else holds is a worse answer than offering
it.

**A switch alone is inert for search, and that is the whole reason this exists.** The title
fan out is `asyncio.wait` under one shared wall clock deadline, so a slow source costs the
others nothing and contributes nothing: it is cancelled before it answers. Three
alternatives were refused. Leaving the deadline alone keeps the switch inert. Raising it per
library makes every search in that library wait longer, including the ones that find
nothing, which is the common case. Two waves, fast render then slow update, is the best
experience and needs an async result path and an affordance for rows arriving after the list
has drawn: worth doing later, not the cheapest correct version.

**Nothing changed on the ISBN path, and saying so is half the decision.** That chain is
sequential and stops at the first hit, so a slow catalogue is reached only when every faster
one has already missed, which is exactly when a reader wants it. The obvious "make the
deadline configurable" would have slowed down the path that was already right.

---

## The slow marking ships empty, and that is a measurement

`sources.SLOW_SEARCHES` has no members on today's roster, derived three ways. The slowest
title search this tree records is the OeNB at 3.23s, the worst of 24 live searches on
2026-08-27, against a 4.0s bar. `MEASURED`'s worst p90 is Open Library at 2.562s over 500
ISBNs, which is lookup latency and corroborates. And the one catalogue ever dropped from
search on these grounds, the Czech National Library, is refused for a different reason: it
renders one populated record per response whatever page size is asked, which is a degraded
result rather than a source that is slow once, so a longer deadline would buy a capped run
of sequential requests and fewer records than were asked for.

So the mechanism lands before the catalogue that needs it, which is what splitting it out of
the two country tickets was for.

**The bar names its statistic**, because a bar that does not is decidable by whoever holds
the sample: the p90 of at least twenty title searches, at or above
`metadata.SEARCH_DEADLINE_SECONDS`. p90 rather than a maximum for the reason
`Measured.p90_seconds` already gives, that the fan out is gathered and costs its slowest
member. The OeNB is settled without computing a p90 at all, because a maximum under the bar
puts the p90 under it too.

---

## The longer deadline is separate, bounded, and its margin is chosen rather than measured

`SEARCH_HARDER_DEADLINE_SECONDS` is 12.0 against the default 4.0. The first draft justified
it as "10.0s ceiling plus 2.0s, and three times the default, so two derivations land on the
same number". A design critic showed that is one derivation: `10.0 + m = 3 x 4.0` has a
unique solution, so the margin was picked to make the coincidence.

The honest statement is in the constant. Every title search adapter makes exactly one
request and both transports cap one request at 10.0s, so a concurrent fan out cannot reach
12.0s on today's adapters and the constant does not bind. What it admits that 4.0s does not
is the whole of that 10.0s, which is what a slow catalogue needs. A measurement is owed
before the marking is filled.

---

## The answer says what was asked, rather than the request implying it

`GET /api/books/search` returns `matches`, `asked` and `unasked`. Two booleans were drafted
first and refused: their fourth quadrant was undefined for the case every install reaches
today, a harder request on a library with no slow catalogue. Two lists partition the roster
by construction, have no such quadrant, and let the screen name the catalogue it is offering
rather than describing the machine's effort.

It matters because `harder` is a request and not an instruction. Three things make the
answer an ordinary search anyway: no slow catalogue is enabled, the one long fan out allowed
at a time is already running, or the query was empty. A client inferring what was asked from
what it sent would be wrong in all three.

**Not on `FeatureFlagsOut`**, which is served without a token and whose docstring says it
carries nothing about the catalogue. Both critics reached that independently, from different
halves of it.

---

## The longer fan out is bounded by concurrency, and the bound never waits

`metadata._HARDER_AT_ONCE` is a semaphore of one, taken without waiting. The rate limiter
allows 60 requests a minute per member and says nothing about how many are open together,
and Little's law puts rate times wall clock in flight: 4 searches at the default deadline,
12 at the longer one, from one member, inside the limit, with no burst. At what a whole fan
out costs by `fetch.MAX_RESPONSE_BYTES`' own honest figure, twelve is about 972 MB against a
512 MiB pod.

**Never waited on, and that half is the load bearing one.** A queue would hold a database
connection for the length of the wait, because the session is checked out before the search
runs and returned after the response, so fifteen waiters at 12.0s each is an exhausted pool:
a worse outage than the memory it saves. A caller that cannot have the slot runs the
ordinary search, and `asked` says so.

---

## Asking nothing has two causes, and the answer has to tell them apart

`_search_terms` drops anything under two characters and the CQL keywords, so a query that
passes the route's own two character minimum can still reduce to nothing: `and` and `a b`
both do. `title_search` returns early there having asked no catalogue, which is the same
observable state as a library whose every enabled catalogue is slow.

Reported identically, the panel told somebody who typed "and" that every catalogue their
library has switched on is a slow one: a claim about their settings from something that
never looked at them, which is the failure this whole feature exists to remove, one level in
and introduced by the fix for it.

So `unasked` is decided in `metadata.title_search`, where the difference is known, rather
than subtracted from the plan by the caller, and it is empty for a query with no question in
it. An empty `asked` beside a non empty `unasked` is the slow library; both empty is the
reader's own query. `asked` alone cannot separate them, and neither can the plan.

**The same narrowing reaches a route the trio that made it did not own.**
`GET /{book_id}/enrich/candidates` runs a title search internally and gated on the default
roster, so once the marking is filled a library whose every enabled search catalogue is slow
would have been told to switch a catalogue back on when it had switched nothing off. Fixed
at the merge, where both halves existed in one tree for the first time, along with the
second site of the refusal wording below.

---

## The refused long search names our own limit, not the catalogues'

The line shown when a long search is refused its slot first read "The slow catalogues were
busy with another search". Those catalogues were never asked: the slot was refused here. It
is the same shape as every other claim this feature exists to remove, one notch milder and
in our own copy, and it was caught by the security seat rather than by anyone reading the
string. It now reads "Only one long search runs at a time", the true sentence at the same
length.

One alternative was considered and dropped: "Another long search was already running" names
the event where the shipped line names the rule, and it is two sentences where one does the
work, with the line sitting directly above the button that was just pressed. Recorded
because a rejected alternative that leaves no trace gets proposed again.

**Two defects behind that line were found by the same seat and are not live until the
marking has a member.** The retry was inert, because the flag was already set so React
bailed out of the render and a five minute `staleTime` suppressed the request: the button
did nothing at all for five minutes. And nothing said what had happened, the offer simply
returning unchanged with the spinner stopped. That is the argument for fixing them now
rather than when the marking is filled: the code that creates the state is here, and the
state has no reader today to notice it is wrong.

---

### A scheme says how its own call numbers sort, and a scheme with no rule sorts as text

Taken from Koha, which seeds every classification source with a **filing rule**
naming a sorting routine: `dewey`, `lcc`, `generic`. `backend/filing.py` holds
one rule per scheme, and a rule answers three things: whether it recognises a
number, the key that files it, and whether a shelf may be ordered by it at all.

**The generic rule orders no shelf, and that is the load bearing half.**
Sorting an unrecognised scheme's values as text is an honest thing to do with
the values. Offering it as a *shelf order* would be the defect this replaced:
promising an order nobody has verified. So a scheme that acquires no rule of its
own cannot acquire a shelf order by accident: `shelf._shelf_order` refuses one,
at import, and a test pins that the sorts the API offers cover exactly the
schemes whose rules order a shelf. It is worth knowing that the first version of
this shipped the sentence and not the mechanism, and that both critic seats
found that independently.

**The key is stored, the way Koha stores `cn_sort`.** It was computed in the
query until revision `f1c30ab27d84` added the column; the reason it was not
stored sooner, that another trio held the Alembic head, is spent. The
measurements below are what justified the column and are kept for that: they
describe the `CASE` of `substr` calls in the ORDER BY that the column replaced,
and it was not small. Measured on a seeded
library whose books carry one Dewey and one Library of Congress number each,
best of 3, every column of a row from one run, the Library of Congress clause is
73.1 ms at 5,000 books and 291.8 ms at 20,000, against 16.7 ms and 70.6 ms for
the Dewey clause and 1.1 ms and 4.2 ms for the title order. That is after
flattening it to twelve arms with literal offsets and dropping a branch that
could not change an answer, which took it down from 393.3 ms and 1,652.3 ms.

**The figure to carry is the cost per classification row**, because that is what
the correlated subquery evaluates and it is the one that holds across shapes:
0.0144 ms per Library of Congress row, against 0.078 to 0.082 before, a factor
of 5.7. The security seat measured 0.131 against 0.020 on its own corpus, 6.4x.
A ratio against the title order is not a constant, since that order never
touches the table: that seat measured 59.5x at one row per book and 316x at
four. The worst case a member can build is `MAX_CLASSIFICATIONS_PER_BOOK` rows
on 20,000 books, which is 160,000 rows, and each pair has to come from one
corpus: 12.5 to 13.1 s down to 2.3 s here, 21.0 s down to 3.2 s on the security
seat's. Those totals are the per row figures above multiplied out rather than
measured a second time, which is why the ticket that filed the column quotes
12.6 s and 2.7 s for this box: both pairs fall inside the same per row range and
neither is an independent measurement. Multiply out the range, do not copy a
total.

The absolute figures are a **floor**: SQLite was backed by a file on tmpfs, so
the reads were RAM.
**A stored derivation moves the failure from slow to silent**, and that is what
this change accepts. A computed key cannot go stale against rows written before
the rule changed, which is exactly what happened to `_looks_like_a_notation`'s
subject; a stored one can. Four things hold it: the column is `NOT NULL` with no
default, so a writer that skips the hook raises rather than storing a wrong key;
the `@validates` hook covers both columns the key derives from; `backup.restore`
derives it rather than trusting the archive; and the migration backfills. What
none of them covers is a change to `filing.py` with no revision recomputing the
column. That is stated at the module, at the model and in `docs/data-model.md`,
and enforced nowhere.

**There is no SQL half any more.** The rule is written once, in Python, and the
query reads the column that rule wrote. The second reader that can drift is the
copy of the rule inside revision `f1c30ab27d84`, which states it rather than
importing it, on the precedent four earlier revisions set;
`tests/test_schema.py::TestTheStoredShelfKey` holds that copy to the original
over the corpus in `tests/test_filing.py`. The widths and caps stay module
constants, because a value longer than either cap has to break in the same place
for the migration's copy and for the rule alike.

**Refusing an LCC number at the door was considered and not taken.**
`ClassificationIn.dewey_numbers_are_notations` refuses a `ddc` row whose number
is not a notation, and `FilingRule.recognises` makes the same door available to
every scheme. It is deliberately not wired up: an LCC pattern that refuses a
real call number loses a catalogue's assertion, where one that mis-files a real
call number only mis-files it. `metadata.py` applies no scheme specific
normaliser to an LCC number for the same reason. Every number does go through
`ClassificationIn.tidy_number`, which collapses whitespace and, since this work,
refuses a control character.

### A catalogue source is a row, and its parser is not

Adopted from Koha's `z3950servers` without copying it, and narrowed to what this project
actually varies. **Koha transforms records with XSLT and this project will not**: the
parsers here produce a typed `Record` and carry refusals a stylesheet cannot express, so
they became a closed set of **seven readers** chosen by a row rather than one stylesheet
per target.

**MARC21 is two of those seven and that is the whole reason the count is not four.**
`_dnb_record` harvests GND identified headings across five tags and refuses a title naming
a volume slot; `_k10plus_record` joins `650 $a` and `$x` into one subject and does neither.
Folding them would change answers rather than restructure code.

**A row names an index, never a query template.** FOLIO's `copycatprofile` stores a query
template with a placeholder, and the ticket's own comment names the substitution point as
the security question in the same breath. A template is a strictly larger grammar than an
index name: it can spell `num=1 or num=$isbn` and an index name cannot spell anything at
all. `targets.Target.isbn_query` and `title_query` are the only two functions in this
application that concatenate a value into a catalogue query, and `targets.cql_term` is the
CQL half of `z3950.pqf_term`.

### The runtime asks the constant, and the table waits for the ticket that edits it

`catalogue_targets` is seeded and read by nothing. That is a decision rather than an
unfinished edge.

`fetch.py` and `z3950.py` both argue they need no host allowlist because a target's
address is a module constant, and `docs/security.md` says it in the same words. #127's
decision D2 refuses a member supplied host and sends it to its own ticket with its own
review. Reading an address off a row is that decision, so the runtime stays on
`targets.SEEDED` and all three sentences stay true unamended.

What that costs is one thing and it is worth knowing: **the rows drift from the constants
the first time a constant is corrected, silently, because nothing reads them.** So the
startup seeder **reconciles** rather than only inserting, which is where it departs from
`seed_tags`: a tag a library renamed is theirs and a seeded target is not. `is_seeded` is
what the ticket that allows editing clears on a row a household has touched.

### An invariant a restore can reach is a CHECK constraint or it is nothing

`targets.Target.__post_init__` validates every invariant visible on one row and fires on
nothing a database returns. `backup.restore` writes through Core, where neither a validator
nor a dataclass runs, and that file has already settled the trust question: an admin is not
a reason to trust a file.

So three constraints, each stating a refusal the Python already makes. The one worth
naming: `requires_isbn_claim` may be false for the DNB alone. Everywhere else that check is
the ISBN identity test, and at the Austrian National Library it is the whole defence
against a mistyped index, which answers HTTP 200 with 7,793,152 records and no diagnostic
rather than with an error. One boolean flipped on a restored row would put an arbitrary
catalogue record on a member's shelf from a barcode scan.

### The roster guard changed shape because the question did

`TestTheProviderRosterIsOneList` compared two dispatch tables keyed on a source against two
sets in `sources`. Both tables are keyed on a **reader** now and one reader serves three
sources, so the comparison cannot be restated: which sources answer what is a field on a
row, and `LOOKUP_SOURCES`, `SEARCH_SOURCES`, `METERED` and `NEEDS_A_KEY` are derived from
those fields rather than written beside them.

What is left to check is what that test was really asking: **is there code that can serve
what this row claims.** `metadata.resolve` is that question, and it is a function rather
than only a test because the startup seeder calls it on every row before writing, so a
reader nothing implements fails the boot rather than a member's scan.

### What the guard learned from being attacked

Two seats attacked it independently and both found the same hole, which is the
strongest signal available here: **`INFORMAL` said "every spelling German has"
and omitted `ihr`**, the nominative of the very paradigm this file used until
the rewrite ("Eure Schlagwörter"). It is now covered, **bare and with no
suffix**: standalone `ihr` occurs 0 times in 888 values and the suffixed forms
occur 8, every one a third person possessive, so `ihr\w*` would have failed the
build on seven legitimate strings.

Three more, each a class rather than an instance:

* **`dein\w*` matched `Deinstallation`**, a legitimate German word that would
  have failed the build. `(?!st)` is narrower than listing the paradigm, which
  drops `deins`, `deinetwegen` and `deinerseits`.
* **Two rules held the same three clause predicate twice**, and their
  exhaustiveness depended on the copies staying identical with nothing
  asserting it. One is the complement of the other, so they are now one
  function: widening a copy of it let a formal address pass both.
* **The set phrase list was interpolated into a `RegExp` unescaped.** A future
  phrase with a metacharacter throws at module load, or silently stops matching.

### The frontend suite shares one environment, and `tests/doubles/` is what pays for it

`isolate: false` takes the suite from about 2m18s to 22.79s, and the figure is quoted beside
the setting in `vite.config.ts` rather than here, where nothing recounts it.

**Sharing one environment means sharing one module registry, and `vi.mock` loses to it.** A
mock is dropped whenever another file evaluated that module first, silently, handing the test
the real module:

| Order | What the second file got | Result |
| --- | --- | --- |
| `App.test.tsx`, then `BarcodeScanner.test.tsx` | the real ZXing decoder | 15 of 33 tests failed |
| `App.test.tsx`, then `BookDetail.test.tsx` | the real `useNavigate` | its one test failed |

**The fix is structural rather than an exemption.** A double in `frontend/tests/doubles/` plus
a `test.alias` entry resolves for every importer regardless of order. **Two guards, because
the rule and its escape hatch fail differently**: one fails the build on a new `vi.mock`, the
other keeps the doubles honest.

**A spy on a storage instance survives `vi.restoreAllMocks()`.** `setItem` is inherited, so
the spy lands on the instance and the suite wide restore never reaches it; measured, a
throwing stub reached 33 of 66 tests in a later file. `vi.spyOn(Storage.prototype, ...)` is
fine, because the prototype is a plain object the restore does reach, and eight files spy that
way without leaking. `tests/setup.ts` now round trips both storages after every test and fails
the test that broke one.

**That defect predates `isolate: false`, which only widened it**: it was already leaking
through the rest of its own file, and per file isolation hid it at the boundary rather than
preventing it.

**Detecting it by introspection failed three times, and the lesson generalises.** The spy is
not on the prototype's descriptors, because it is installed against the instance; it is not
among the instance's own properties, because happy-dom implements `Storage` as a Proxy whose
`hasOwnProperty` answers false for a key its `get` returns; reading every key throws, because
prototype accessors are invoked by reading them; and `.mock` survives `mockRestore()`, so
looking for it flags a file that did the right thing. **Ask the object what it does, not what
it is made of.**

**What is still not fixed**: module level state in `src/` crosses files, and a shuffled seed
can surface it. When one does, probe before reaching for the known suspect: a named drifter
was blamed once and the pair failed identically with the fix in and out.

**The honest cost.** Order dependence is what this setting buys back. The suite is nine times
faster and a leak is now a suite level fault rather than a file level one, which is a trade
made deliberately rather than a property to be surprised by.
### The backend suite is twice as slow in CI as in an identical pod, and three obvious reasons are not it

Measured on one node, with the suite pod shaped to match the CI job pod exactly: two CPUs,
2Gi, the same Alpine `uv` image family, `-n 2` both ways.

| Where | pytest |
| --- | --- |
| CI job | 315.54s to 319.73s across three runs |
| An isolated pod of the same shape | 153.18s, 154.11s |

**Three candidates were measured and eliminated, and they are written down so nobody spends
the runner time again.**

**Stage contention is not it.** The runner allows four job pods at once, each permitted two
CPUs, on a six core box, so the test stage can demand eight cores' worth of limits on six.
That is real, and it costs about three seconds: the suite was run as the only job in its
pipeline and came in at 315.54s against 318.75s with the full stage beside it.

**More pytest workers is not it, and it is actively worse.** In a two CPU pod, `-n 4` took
387.08s and 391.29s against `-n 2` at 153.18s and 154.11s. Both arms repeat within one
percent. Four workers in a two core cgroup is the shape this repository already warns about,
now measured on it: the `-n 2` in `addopts` is not a conservative guess, it matches
`cpu_limit = "2"` exactly. **Do not raise it without raising the pod's CPU limit first**, and
that limit has an incident behind it.

**The tmpfs fallback is not it.** `conftest._fastest_scratch()` puts the databases on
`/dev/shm` and falls back to disk **silently**, which made it the best remaining candidate: a
run that lost tmpfs still passes and differs only in duration. CI reports
`endpaper scratch: /dev/shm (tmpfs)`, the same as the fast pod. Eliminated by measurement
rather than by reading the code.

**What is still open**, and neither has been measured: the two images are different digests
of the same base, and the tree and virtualenv sit on a hostPath in the suite pod against the
container overlay in CI.

**The diagnostic that settled the third one is now permanent**, because a silent fallback is
worth a line in every run. Getting that line to appear took three attempts and the reason
generalises: `addopts` carries `-q`, which drops `pytest_report_header` outright, and a
`write_line` from `pytest_configure` lands before the reporter starts writing. Only
`pytest_terminal_summary` prints under this project's own settings. **A diagnostic that is
invisible under the settings it ships with is the same defect it exists to report**, which is
why `backend/tests/test_scratch_report.py` pins the hook name as well as the text.

### The runner checks its image against the pipeline for both toolchains, not one

The suite runner refused to run the frontend suite on a different bun than the pipeline
and had no such check for uv, which is the toolchain the larger suite runs on. The gap was
invisible until Renovate moved the pipeline to a newer uv and the runner stayed on an older
digest: the backend suite then validated against a different uv and a different Python than
CI ran, silently, with everything green.

**The runner's pin could not have been compared even if somebody had looked**, and that is
the part worth keeping. It named the unversioned `uv:python3.14-alpine` tag at a digest,
while the pipeline names a versioned one. Two strings that are never equal are not a check
that fails, they are a check that cannot be written. The runner now carries the pipeline's
exact reference.

One implementation serves both, because a second copy of twenty five lines is how the next
one goes missing too. It takes the label, the pattern and the consequence.

**Two things the attack found that reading did not.**

The refusal that fires when a pin has gone missing named the wrong file. It read
`${want:+$0}${want:-$ci_file}`, which expands to the runner's path followed by the found
reference whenever the pipeline's side is the one that is present, so a runner that had lost
its own pin was reported as a path with an image glued to the end. Two explicit branches
replace it, and the test asserts the message names the pipeline file and not the runner.

And the guard reads its own file with `grep | head -1`, while both patterns are now written
out as string literals a few lines above the pins they match. A pattern that matched its own
literal would compare a comment against the pipeline and pass for ever. Neither does, checked
by running the greps rather than by reading them, and pinned by a test that asserts each
pattern finds exactly one reference in the runner.

Deleting the call does not fail a test, it stops the suite running at all with the refusal on
stderr, which is the self enforcing rung rather than the tested one.

### What the pipeline now reports about its own CPU

The backend job reads `cpu.stat` from its cgroup in `after_script`. It is there to settle one
question and it is written down so the answer is read correctly: `nr_throttled` high against
`nr_periods` means the two CPU quota is binding, while `nr_throttled` near zero with
`usage_usec` far below two cores' worth of the elapsed time means the opposite, that the
ceiling is never reached because the pod requests 200m and loses its turns to everything else
on the box.

In `after_script` so a failed run reports too, and every read is guarded with a fallback to
cgroup v1 and then to a plain line, because a diagnostic that fails the job it is diagnosing
is worse than none, and silence is indistinguishable from a healthy pod.

```markdown
## The loans list was never the thing refusing anything, and library mode does not touch it

Library mode was asked to let a member see loans on every book that is not
private, rather than only those they own. That reading of the filter was wrong
in a way worth recording, because the obvious implementation would have made
the app worse.

`visible_to(viewer)` is `deleted_at IS NULL AND (is_private IS false OR
added_by_user_id = viewer)`. It admits **every non private book, plus the
viewer's own private ones**. `list_loans` is rooted at `Shelf.seen_by` and adds
no lender-or-borrower arm, so it has always answered with every loan over every
public book, housemates' included; `test_a_member_does_not_read_a_loan_they_are_not_party_to`
has asserted exactly that since the overdue page was split out of it.

So "every book that is not private" is a **subset** of what the loans list
already served, and narrowing to it would have dropped a member's own private
books out of their own loan list. That contradicts a rule settled earlier and
written into `overdue_for_viewer`: a member's own private books belong in what
they are told about, because being told about your own book is not a disclosure.

The refusal a volunteer actually meets is on the overdue page, which narrows to
the loans they are party to unless `notifications.sees_every_loan` says
otherwise. That function's own docstring had already named library mode as the
clause it would gain, so it gained it and nothing else moved. Both arms are
rooted at the Shelf either way, so neither can reach a book its viewer may not
see, and an admin is no more a superuser over another member's private books
than the mode is.

The cost of the clause is one row read per request on the overdue routes, which
took `GET /api/loans/overdue` from 12 statements to 13. The figure moved in the
commit that moved the code.

## The loan clock is one module, because a badge and a reminder were computing it separately

`is_overdue` was inline in `routers/loans._to_out` and `days_overdue` was inline
in `notifications.build_digest`. Both are the same question about a loan and a
moment, and two definitions of it can disagree: a row whose badge says the book
is fine, listed on a page whose query says it is late, is a screen contradicting
itself with nothing failing anywhere.

`backend/lending.py` holds the three of them, `days_out` included, and both
callers read it. The SQL form stays in `notifications._overdue_clauses`, because
a query cannot call a Python predicate, and `tests/test_lending.py` asserts the
two select the same loans rather than trusting the comment that says they
should. The one clause only the query has is `Book.deleted_at`, which is a fact
about the book rather than about the loan, and that asymmetry is asserted too.

`days_out` is the number that means something for the lending that has no
deadline at all, which is most of it here: a household reading only
`days_overdue` has nothing to go on for a loan with no `due_at`.
```

## The library view is remembered per mode, and the household's key kept its name

The view preference was one `localStorage` key, and a per mode default alone would not have
been enough: with one key the first change a cataloguer made overwrote the household's choice,
and turning the mode off left somebody looking at a view they never picked.

`lib/libraryView.ts` takes a `CatalogueMode` and holds a default and a key per mode, `grid` for
a household and `list` for a cataloguer. **Separate keys make independence structural**: writing
one cannot touch the other and there is no merge to get wrong. Same shape as
`lib/libraryColumns.ts`, and two deliberate differences from it:

**The household's key stays `libraryView`, unprefixed.** The column keys shipped with the modes
and had nothing to preserve; this one is in every browser that has ever chosen a view, so
renaming it would reset every household to the grid, which is the clobber the split exists to
prevent arriving from the other side.

**`writeLibraryView` stores a choice equal to the default where `writeColumns` clears it.** The
half of that rule about a stored default going stale does reach the view and is accepted; the
half about a reader stuck with a frozen copy does not, because there is no reset control here.

**The view is derived from the mode rather than seeded into state**, and that is what makes the
per mode default correct on a cold load: the mode is fetched, so a state initialiser would read
storage while the mode still answered household.

**`catalogueMode(undefined)` is a fallback for reading and not for writing.** A wrong read costs
one render; a wrong write is permanent and silent, and the control paints before the flags land.
So `useLibrary` refuses every per mode write until the flags resolve, through one door rather
than a guard at each writer, and disables the controls meanwhile so a refused click is visible
rather than inert.

**Resolved means settled either way, not `flags !== undefined`.** A failed fetch is an answer:
defining it the other way locks the controls for the session.

**What the gate refuses that nothing refused before**: a household's pick during that window,
which would have been correct and is indistinguishable from a cataloguer's, because the
fallback is the same value. Accepted deliberately.

Pinned by mutation rather than by reading: over the whole suite, deleting the gate fails three
named tests and defining resolved as `data !== undefined` fails five.
## The SRU server borrows the public catalogue's gate rather than growing one

The ticket asked only that library mode off make the endpoint disappear.
`routers/sru.py` imports `routers.public.public_reader` instead, which is library mode
**and** the publish row, plus the rate limit, in that order.

That is stricter than what was asked and the reason is not caution. `routers/public.py`
names five questions a public surface has to answer and enforces each in a different place;
a second unauthenticated surface answering any of them a second, different way is two
answers that drift the first time one is edited. Importing the dependency makes the drift
impossible rather than unlikely. An institution that has not published its catalogue has
not published it over a protocol either.

The same reasoning gives it the catalogue's rate limit counter rather than one of its own
size: there is one published catalogue, and a harvester and a browser reading the same
records should not have two budgets between them.

## The column boundary for a MARC record is `marc.py`'s field mapping, and it is now pinned

`Shelf.seen_by_the_public` filters rows and `schemas/public.py` is the column boundary for
the JSON catalogue. The SRU server publishes MARC, so its column boundary is whatever
`marc.py` writes, and MARC is the **richer** record of the two: it has fields for the shelf
mark, the price paid and the acquisition source. `marc.py` writes none of them, which is
what made reusing it safe, and nothing enforced that.

`tests/test_sru.py::TestTheRecordCarriesNoColumnThePublicPayloadWithholds` enforces it
with two different instruments, because two readings of one instrument are one instrument
twice: it puts a distinctive value in every withheld column of a transient Book and looks
for it in a rendered record, and it reads the writer's source for the Book attributes it
touches at all. The first catches a value that reaches the document; the second catches a
column that is read at all, including one whose value happens not to render.

An `852 $b` for a cataloguer is a reasonable future request and it fails that test. The
answer then is a record writer for SRU, not a wider boundary.

## Masking is supported because SQLite's LIKE does not backtrack

The obvious reason to refuse CQL's `*` and `?` on a public endpoint is that they become SQL
wildcards and a pattern of many wildcards is a classic denial of service. Measured, that is
not true of this storage engine.

**The first measurement was worthless and the conclusion it reached was right**, which is
the awkward combination: `('%a' * 400)` against a 120 character title needs 400 literal
`a`s inside 120 characters, so it fails at the first position on every row and never
backtracks, and 400 masks is above the bound anyway. Two review seats found that
independently. The number then outlived its own retraction inside `sru.py` for one commit,
which is the malignant stale form: the correction arrived in the commit that left the wrong
number at the site the correction points at.

Re-derived on the worst shape the bound admits, eight wildcards alternating with a literal
that matches everywhere and then one that cannot: against 3,000 books whose title is 120
identical characters, 12.7 to 13.2 ms in total, 4.23 to 4.40 microseconds per book.

So they are translated rather than refused, and the correctness question replaces the cost
one: the literal text of a term is escaped **before** the masks are put in, so a client
searching for `100%` means a per cent sign and a client searching for `100*` means a
wildcard. `MAX_MASKS_IN_A_TERM` remains, and its comment says plainly that it is not a cost
bound: a term of a thousand wildcards is not a search anybody meant to run, and a future
storage engine is not promised to behave as this one measured.

Anchoring (`^`) is refused with the diagnostic the specification has for it, because
mapping it correctly is fiddlier than the value it adds and treating it as a literal would
return the wrong result silently.

## The query bound is a cost budget, because a count of predicates is not a cost

The first version bounded the parse five ways and published the resulting predicate count
as the ceiling. Counting in that unit made the **cheap** shape look like the worst case.
Measured against 3,000 books with 2,000 character descriptions: 384 comparisons through
`cql.serverChoice` are 584 to 650 ms, while 128 through `dc.description`, which the same
parse bounds admit, are 2091 to 2284 ms, and 64 through `dc.subject` are 1067 to 1143 ms.
Three times the comparisons, a third of the cost.

So comparisons are charged against a budget, weighted per index, refused when it runs out.
**The weight is a property of the index and not of the column**, and that is where the
obvious derivation fails: "the column has no length limit" gets `dc.description` right and
`dc.subject` wrong, since its column is `String(100)` and its cost is a correlated `EXISTS`
over a join. The two classes are declared per row with no default, so a thirteenth index
cannot be added without somebody deciding what it costs.

**The parse bounds stay.** They bound structure, which is memory and stack; the budget
bounds work, which is CPU. Neither is the other, and the budget is applied on top, so it is
strictly tighter and admits nothing that used to be refused. What it now refuses that it
used to allow is named in `docs/security.md`, because a bound in a different unit is a
different bound rather than a tighter one.

## An integer the storage engine cannot hold was three unauthenticated 500s

`int()` parses any number of digits; SQLite stores 64 bits. A value in between parsed, went
to the driver, and raised `OverflowError`, which is not an `SruError`, so it left `respond`
and reached a caller with no credentials as `Internal Server Error`. Three routes:
`rec.id`, `dc.date` and `startRecord`.

Both review seats found it independently, and neither found it by reading: the exception is
raised well below this module and only a test at the transport sees the status a client
got. The claim it falsified was written in three places, including the ticket.

The fix is one range at the two integer conversions, which are the only `int()` calls in
the module. **Both ends**, because the negative arm overflows exactly as the positive one
does. `startRecord` is the one a range check could not have caught: `page()` runs with
`start_record - 1` before the check that compares it against the total, so the overflow
happened inside the query.

**The two sites have different outer refusals and a test written on the assumption that
they behave alike failed.** A term lives inside `query`, so `MAX_QUERY_CHARS` caps it at
about a thousand digits and CPython's own 4,300 digit limit is unreachable there; a
parameter has no such cap, so `startRecord` really does reach it. Both arms are pinned.

## A filter is a read of its column, and only the record writer was guarded

`schemas/public.py` is the column boundary, `TestEveryPublicSortOrdersByAPublishedColumn`
enforces it on the ORDER BY, and the SRU server enforced it on the record writer. Nothing
enforced it on the twelve new filters, so an index pointed at the shelf mark would have
been an oracle a stranger walks one query at a time with the row filter perfectly intact.

Each index's predicate is now compiled and every `books` column named in it checked against
`PublicBookOut`, in the same shape as the sort rule, so there is one rule rather than two
that resemble each other.

## `explain` reads the `Host` header directly, and not `request.url`

The explain document reports the host and port the request arrived at, which is the only
honest answer since no setting holds one. The obvious implementation is
`request.url.hostname`, and it is wrong in a way that is invisible from the call site.

Starlette 1.6.0 validates the `Host` header itself against
`^([a-z0-9.-]+|\[ipv6\])(?::[0-9]+)?$` and, when it will not use it, falls back to
`scope["server"]`, which is the address this process is **bound** to. Behind a reverse
proxy that is a container's internal listen address, so a client sending a malformed
`Host` would be handed a deployment's internal address in a document it can keep.

Reading the header means the only two answers are the client's own host and `localhost`.
The router's own pattern is narrower than Starlette's in two ways it states: it bounds the
length, since that rule admits a name of any length and this value goes into XML, and it
refuses the bracketed IPv6 form, which costs a client on such a deployment an accurate
`<host>` and nothing else.

## The diagnostic numbers were checked against a second implementation, and four changed

Three of the numbers this server raised at the time of the check, twenty two of them, were
the ones its author was least sure of: 30, 31 and 36. A wrong number here is not a wrong message, it is a URI a client matches
on and misroutes, and no amount of re-reading the code would have found it, because the
code says exactly what its author remembered.

`targets.py` already corroborated 8, 11 and 235 from contact with live servers. The rest
were read off CLARIN's `fcs-sru-server` `SRUConstants.java`, an independent implementation
of the same list. All twenty two agreed name for name, so the three uncertain ones were
right. **The register has grown since and no number is quoted for its current size**, here
or in the module: a count in prose does not recount itself, and the totality test does.

**What the check was actually worth was not the confirmation.** Reading the whole list
showed four places this server was answering with a general code where the specification
has a specific one: `recordPacking` was diagnostic 6 and is 71, and `sortKeys`,
`stylesheet` and `resultSetTTL` were all diagnostic 8, "there is no such parameter", where
the numbers for declining those three features are 80, 110 and 50. The difference is what a
client does next: told there is no such parameter as `sortKeys`, it goes looking for a typo.

The generic code is still what an *unknown* parameter gets, and
`tests/test_sru.py` asserts both halves, because a table that swallowed everything would
leave diagnostic 8 unreachable with nothing failing.

## `dc.subject` searches tags, and classification headings are not indexed

An SRU client asking for a subject would reasonably expect the Dewey and GND headings this
library holds, and `PublicBookOut` publishes them. They are not indexed, and the reason is
where the code would have to reach: `Book.classifications.any(Classification.number == ...)`
inside `Shelf.where` is a statement that `BOOK_OWNED_READERS` in `tests/test_shelf.py`
exists to make somebody justify, and that is a decision about the privacy guard rather than
about SRU.

`explain` is generated from the index registry, so a client sees the omission rather than
guessing at it. Adding the index later is a row in `INDEXES` and one allowlist entry with
a reason.

## The one catalogue record scalar that is deliberately unbounded

Moved out of `catalogue.py` on 2026-09-05, where the derivation was 72 lines above
a constant. The rule stays at the constant; the measurements are here. This named
two scalars until `isbn` gained a ceiling later the same day, for which see the
entry below.

**`source`** is this app's own word rather than a catalogue's. Every producer
sets it from a literal: the adapters in `metadata.py` from the source roster,
`marc.py` from its own `SOURCE`, and `_SOURCE_JOIN` joins those. **Two
modules, not one**, and the count is worth stating rather than the module,
because this comment named only `metadata.py` on the day the second one
arrived. No catalogue can widen it either way, which is also what makes it
safe to log untruncated. `SOURCE_LABEL_MAX` still bounds it at `BookMatch`,
where it is a field on the wire.

Pinned by `TestWhichScalarsAreBoundedAndWhichAreNamedInstead`, which asserts
this set's **contents** and not only that the partition covers everything: an
earlier version compared unions, so moving a name from a ceilings table into
here would have left both sides equal and nothing red.

## A catalogue record's ISBN is bounded, and what makes that safe

`catalogue.Record.isbn` was excluded from `_TEXT_CEILINGS` because a bound can clear the
field, `as_lookup()` hands `None` to a required `BookLookup.isbn`, and `lookup_isbn` catches
no `ValidationError`: a 500 on a member's scan. What made that reachable was
`metadata._google_record` preferring the volume's own unparsed `industryIdentifiers` entry
over the canonicalised argument. `metadata._google_isbn13` closed it.

**Decided 2026-09-05: bound it.** The question was what the exclusion refuses that a bound
would accept, and on the lookup path the answer is nothing.

Every producer that can reach `BookLookup` was enumerated from the roster rather than from a
call graph, because a name based graph reported all nine `Record(` constructions in
`metadata.py` reachable, which is the whole domain and therefore a tell rather than a
measurement. `sources.LOOKUP_SOURCES` holds seven rows behind four readers
(`_LOOKUP_READERS` plus `_BESPOKE_LOOKUPS`), and they reach five record constructions:
`_dnb_record`, `_k10plus_record`, `_nkp_record`, `_open_library` and `_google_record`. The
other four are search and cluster path only. Each of the five sets `isbn` from the
canonicalised argument, from `metadata._marc_isbn`, or from `metadata._google_isbn13`, and
all three are `isbn.parse` output.

**Measured, `isbn.parse`'s output width, by three routes:** a sweep of 400,000 random and
1,400,000 constructed inputs through `parse` gave 1,400,040 non-None outputs, every one **13
characters**; driving `isbn10_to_isbn13` over 300,000 valid ISBN-10s gave 300,000 outputs at
**13**; and the branch reading, `is_valid_isbn13` requiring `len == 13` and
`isbn10_to_isbn13` returning `"978" + isbn10[:9]` plus one check digit. Against
`ISBN_MAX = 20`. Thirteen against twenty, so the ceiling cannot clear the field.

**What the bound buys:** on the search path a record with a 40 character identifier gives
**1 row against 0**, because `BookMatch.isbn13` is bounded at 20 and `_match_rows` drops the
whole record. Measured through `_match_rows` with the ceiling in place and again with it
lifted in process.

**What the bound is safe because of, and not on its own.** The invariant is that every
lookup producer parses its own identifier. It is enforced by
`tests/test_metadata.py::TestEverySourceSetsTheIsbnItWasAskedFor`, whose fixture bodies carry
the ISBN-10 form so an adapter reading its own bytes fails it, and whose
`test_every_registered_source_has_a_body_here` arms it for a source added later. The pair of
tripwires in `tests/test_catalogue.py::TestWhichScalarsAreBoundedAndWhichAreNamedInstead`
covering `_google_record` are now the precondition rather than the record of a defect.
`test_the_ceiling_admits_every_isbn_the_parser_can_produce` recomputes the width from a sweep
rather than from `_ISBN13_LENGTH`, which would be the constant agreeing with itself.

`isbn` joins `_KEPT_WHOLE_ON_UPLOAD`: a cut identifier fails its own checksum, so it names no
book, and `books.isbn` is the MARC importer's primary match key.

## A request body bounds the cover URL it stores, not the one it receives

`Book`'s `@validates("cover_url")` runs `covers.https_url` on every write, which turns
`http://` into `https://` and lengthens the value by one, so a `max_length` equal to the
column bounds a string one character shorter than the stored one.

**Measured on both request bodies carrying the field**, with a 500 character http URL on an
allowed cover host: `BookCreate` accepted it and its own validator returned **501**, and
`BookMatch` accepted it at 500 and the ORM stored **501**, both against `String(500)`. SQLite
holds the over-wide row rather than refusing it; an engine that enforces a `VARCHAR` width
fails the flush mid request. `POST /api/books` and `POST /api/books/{book_id}/enrich/apply`
are both ordinary authenticated member routes, so this needs no hostile upstream.
`BookCreate` was the sharper of the two and was outside the ticket, which named `BookMatch`
only: that model's own validator returns the upgraded value, so the schema emitted the 501
rather than merely passing a 500 along.

**Fixed by bounding what is stored**, in one helper,
`schemas/book._a_cover_url_the_column_can_hold`, called from both. Not by raising
`max_length` to 501, which would state a bound nobody could derive from the column. The
ceiling is refused rather than dropped, because here there is a caller to tell: a 422 on both
routes, and `routers/books._bounded_match` catches it and drops the field, which is the
catalogue path's answer reached through this one rule. `catalogue._AS_STORED` is the same
rule on the catalogue path.

`_AS_STORED` is the register of which columns a write rewrites, and it arguably belongs
beside the column in `models.py` rather than in `catalogue.py`. Wherever it lives,
`tests/schemas/test_book.py::TestAColumnRewrittenOnWriteIsBoundedAfterTheRewrite` asserts
`set(catalogue._AS_STORED) == set(Book.__mapper__.validators)`, which keeps the two in step.
Measured before that arm existed: a lengthening validator added for `publisher` with the
table untouched left every test in both files green.

## Which columns an import may fill, column by column

Moved out of `importing.py` on 2026-09-05, where it was 72 lines above the
constant. The rule stays there: fill the gaps, never overwrite.

**Never an overwrite**, which is `_fill_gaps`'s rule and the same one
metadata enrichment follows: a Book already here was catalogued by somebody
who had it in their hands, and an uploaded file did not.

Wider than the CSV importer's four, because a MARC record carries more and
because the fields it adds are the ones a cataloguer would otherwise retype.
Derived from `_MARC_RECORD_FIELDS` rather than written out again: the gap
filler takes everything the create path writes **except the title**, which a
matched Book already has by definition, since the title is half of what
matched it.

**`isbn` is in neither tuple, and that is what stops a 500 rather than an
economy.** It is written once, on the create path, and never filled in on a
matched Book. Adding it here would reach this shape: a record whose ISBN
belongs to a Book this Member cannot see, whose title and author match one
they can. `MarcIndex.find` matches on the identity key, so `isbn_is_taken` is
never consulted, and the gap filler would then write the invisible Book's
ISBN onto the visible one, tripping `books.isbn`'s unique index.

**The assignment is silent, and no lazy load can surface it**, which is the
first thing to know because it is the first thing a reader guesses. This
application's sessions come from `database.SessionLocal`, which is
`sessionmaker(autocommit=False, autoflush=False)`, so reading
`book.classifications` in `add_headings` emits its SELECT without flushing
anything.

**The count of that SELECT is the tell, and it needs no traceback.** Same
record, same collision, one argument apart:

| session | classifications SELECTs | raises at |
|---|---|---|
| `autoflush=False`, which is this app's | 1 | the commit |
| `autoflush=True`, which is SQLAlchemy's default | 0 | `add_headings` |

One means the lazy load was issued and flushed nothing. Zero means the
autoflush raised **before** the SELECT was reached. So a probe that reports
zero is measuring a session this application never constructs, which is what
three seats spent five rounds not noticing.

**So it surfaces at the next explicit flush, and which one that is depends on
the rest of the file.** Measured through the route, both arms:

| file | records entered | frames |
|---|---|---|
| the collider alone | `['Stoner']` | `apply > commit > flush` |
| the collider, then a new record | both | `_apply_one > _create > flush` |

So a later record that has to be created surfaces the earlier record's write
at **its** insert, and with nothing after the collision it waits for the
commit.

The conclusion never depended on which: it is one transaction, so the whole
transfer writes nothing and answers 500, which is the exact failure
`_taken_isbns` exists to prevent by another route. The incoming ISBN is
dropped instead, silently, and that is the cheaper loss.

**Written down anyway, because five statements of this mechanism were made
across three seats and every one was wrong**, two of them in this comment. A
comment naming a mechanism is what the next reader trusts **instead of
measuring**: "at the commit" sends somebody debugging this to the end of the
run, and "at the autoflush" sends them to a flush this session never
performs.

It was settled by one `grep` of the session factory rather than by a sixth
traceback. **A measurement is only evidence about the configuration it was
taken under**, and every round of this argument measured the symptom while
none of them read `database.py:18`.

`tests/routers/test_imports_marc.py::TestAMatchedBookNeverGainsAnIsbn` pins
it, because nothing else would notice the tuple gaining one entry.

## Which authority schemes exist, and why the list is code rather than rows

Moved out of `backend/enums.py` on 2026-09-05. The rule stays at the code.

Not `ClassificationScheme`, and the split is the point rather than tidiness.
Every member of that enum answers "what is this book about"; every member of
this one answers "which record in a file of *people* is this author". The
DNB writes both in the same MARC `$0`, which is exactly why they need two
closed sets: `4203576-4` is a subject heading and `118181505` is a person,
and one column holding both would make a heading and an author the same kind
of row.

**Eleven members, and only one of them is ever the entry point.** GND is the
only scheme a catalogue writes here: the DNB is the only source this app
reads a person's identifier from (`100 $0` and `700 $0`), and K10plus
carries the same subfield and is deliberately not read for it, which
`_k10plus_record` records. The other ten arrive as cross references on a GND
record that a Member confirmed, four of them free in that record's `sameAs`
through `authority.cross_references` and six from the VIAF cluster it names
through `authority.national_identifiers`. None of them arrives on its own.
So a search still starts with a name and a GND.

This docstring used to say "one member, and the count is the honest state of
the supply rather than a stub", and that sentence was true while nothing
stored a second scheme. Storing the cross references is what retired it, and
it is replaced rather than deleted because the reasoning is still the rule:
a member here has to be a value some writer can produce.

**`ISNI` is the spine.** ISO 27729, deliberately language neutral, and it
identifies a person rather than a cluster of records about one, which is the
difference between it and `VIAF`. Measured 2026-08-28 over fourteen GND
records spanning Spanish, Portuguese, Brazilian, Argentine, Uruguayan and
Italian authors: all fourteen carried ISNI, LCNAF, VIAF and Wikidata in
`sameAs`.

**`LCNAF` rather than `LC`**, because the file has a name and the
abbreviation for the library is not it: `id.loc.gov` serves several
authority files and this is the one about people.

**The six national files are spelled as VIAF spells them**, in `v:sid` as
`BLBNB|000560509`, because that source code is what the parser matches on and
a second spelling here would be a second name for one fact. Lowercased for
the stored value, like every other member.

## Storing an identifier and resolving one are different acts

This docstring used to argue the six out on the ground that "nothing in this
app can look one up, so a member for it would be a value no reader can use".
**That conflated two acts, and the correction is the reason they are members
now.** A scheme has to be a value some writer can produce, which was the rule
the old sentence was reaching for and which these pass: the identifier
arrives free from a VIAF cluster this app already has a reason to read.
Being able to *resolve* one is a separate and later question, and it is what
makes the argument run the other way: Brazil and Argentina answer 403 to
every agent tried and have no open Z39.50 port, so an adapter for them is
blocked on a transport rather than on this list, and the identifier stored
today is what makes that adapter cheap on the day the transport lands.

So the closed set is still closed for the same reason: a member has to be
something a writer here produces. What changed is that six more things are.

Adding a member costs one line here, one value in
`ck_author_identifiers_scheme`, and a migration to widen that constraint.
**`SUDOC` is deliberately still absent**, though a cluster carries it: it is
a French union catalogue rather than one of the six national files named
here, and nothing has asked for it. It goes in when somebody asks, in the
next migration.

## The Z39.50 door's bounds, and which of fetch.py's four have no counterpart

Moved out of `backend/z3950.py` on 2026-09-05. The rule stays at the code.

**A second transport beside `fetch.py`, not an extension of it.** `fetch.py` is the
single door for HTTP and everything it enforces is HTTP shaped: a cap counted on
`aiter_raw` chunks, a per request deadline around a redirect walk, a refusal of any hop
that leaves the host, and a refusal of a content encoding nobody asked for. Z39.50 has no
redirects, no content encoding and no chunked reads, so two of those four have no
equivalent here and the other two need building rather than importing.

What this module owes a caller is the property that makes `fetch.py` worth having: the
bounds arrive **by construction**, so no call site has to remember to ask.

| `fetch.py` | Here |
|---|---|
| `MAX_RESPONSE_BYTES`, on raw chunks | `MAX_RESPONSE_BYTES`, on record bytes, and `MAX_RECORDS` |
| `TIMEOUT_SECONDS` under one `asyncio.timeout` | one absolute deadline held by the association |
| `MAX_REDIRECTS` and the same host walk | nothing: the protocol has no redirect |
| `UnrequestedEncoding` | nothing: the protocol has no content encoding |
| `catalogue_client()` | `association()` |
| every refusal is an `httpx.HTTPError` | every refusal is a `Z3950Error` |

**The client is behind a seam and is not chosen yet.** `Session` and `Client` are the
whole of what a client has to be, and every bound is enforced on this side of them. The
one client that exists today is `z3950_provisional.py`, and its name is the status it
has: it exists so this module can be exercised and the Library of Congress control can be
checked, not because a route has been picked.

**Three dispositions, and the survey conflated two of them once already.**

| Disposition | What it is | How it arrives |
|---|---|---|
| **unreachable** | nothing answered | `Unreachable` |
| **refused** | the target answered, and said no | `Refused`, carrying the code |
| **answered nothing** | the target answered, and held nothing | `Answer(hits=0, records=())` |

The third is a value and not an exception, because a catalogue that does not hold a book
is the ordinary case. Measured 2026-08-28, all three are live: `z3950.bne.es` accepts the
association and refuses every search with `[101] Access-control failure`; `z3950.dbc.dk`
answers `[2] Temporary system error, HTTP error: 400` behind all four database names it
knows; `lx2.loc.gov/LCDB` returns 0 hits for an ISBN it does not hold.

**A blocking client is the reason `Association` exists rather than a bare handle.**
Z39.50 clients are synchronous, so every call runs off the event loop, and a thread cannot
be cancelled. Three consequences, each of which has been measured as a real failure and
each of which is answered by the association owning one worker thread and one lock:

* an abandoned call is still using the connection, so **closing it from the loop thread
  frees memory a live thread is reading**: measured, a 0.05s deadline on a search to the
  Library of Congress left the process to be SIGKILLed at 40s where not closing returned
  at 0.40s;
* two coroutines sharing one association corrupt each other's result set, because a
  `Session` holds one: measured over eight runs, five bogus `Unreachable`, two
  `Answer(hits=0)` on a query that returns 444 serially, and one SIGSEGV;
* a timed out open still produces a session, and nothing was holding it: measured,
  `sessions built: 1, closed: [0]`, a connection and a socket for the life of the process.

**There is no host allowlist and there is deliberately no SSRF guard.** The reasoning is
`fetch.py`'s: a `Target` is built from module constants, never from anything a member
supplies, so there is no host an attacker gets to choose and nothing an allowlist would
refuse. **That property lives in the callers, not here**, and the day a `Target` is built
from stored configuration or from a request body, this module needs the allowlist
`covers.is_fetchable` already is for the other direction.

## UNIMARC is read from the Library of Congress crosswalk, and not until a source sends one

Three tickets treated UNIMARC as a mapping this project would have to invent, which is what
made the Romance and Mediterranean national libraries look expensive. It has been written
already, and the question was which of the existing answers is usable here.

**USEMARCON is refused, on its licence and on its contents, and either alone is enough.**

Its README says "USEMARCON is provided under a fairly liberal license". The `LICENSE` file
it points at is a **modified GPL-2.0** under the title "USEMARCON PLUS SOFTWARE LICENCE
AGREEMENT", copyright the British Library and USEMARCON Consortium, 2001. Modified rather
than reproduced: it is numbered 0 to 8, where GPL-2.0 runs to 12; GPL-2.0's sections 7 to 10
are absent, its warranty sections 11 and 12 are renumbered 7 and 8, and its section 2(b),
the clause that is GPL's copyleft, does not appear anywhere in the file. Neither the Free
Software Foundation nor the words "General Public License" are named in it. GitHub's licence
detector reports `NOASSERTION`.

**That makes it worse to depend on rather than better.** What survives the edit is section
2's whole-work clause, "the distribution of the whole must be on the terms of this Licence",
so it is still copyleft; what does not survive is any way to reason about it. A real GPL-2.0
has thirty years of compatibility analysis behind it, and a bespoke copyleft licence that
merely resembles one has none. Endpaper is Apache-2.0. **A README is not a licence, and this
is the case that shows why**: the sentence everybody quotes and the file it points at say
different things.

Separately, the repository ships one ruleset, `uni2uk`, and it converts UNIMARC to
**UKMARC**, a format the British Library retired in favour of MARC21. There is no UNIMARC to
MARC21 ruleset in it at all. So even had the licence permitted taking the rules, the rules
for this conversion are not there.

**Linking the tool instead is refused on the licence first and the cost second.** The
tempting reading is that running a separate binary escapes copyleft, and the licence does say
"activities other than copying, distribution and modification are not covered". Running it is
indeed outside that scope. **Shipping it is not**: this project publishes an image to Docker
Hub, which is distribution, and section 3 governs distributing "in object code or executable
form under the terms of Sections 1 and 2 above", which is where the whole-work clause quoted
above lands. So linking is the strongest form of the copyleft question here rather than a way
around it.

The cost is a second refusal rather than the only one, and the distinction matters: a cost
argument is overturned the day somebody finds a smaller build, and a licence blocker is not.
`docker/build-yaz.sh` already shows what one C library costs this image, and the Dockerfile
drops pip and setuptools specifically to shrink the scan surface, so a second C dependency to
parse records is a poor trade against implementing a table. And it would run the same absent
ruleset, so there is nothing to run.

**The Library of Congress crosswalk is the specification.** UNIMARC to MARC 21 Conversion
Specifications, version 3.0, August 2001, from the Network Development and MARC Standards
Office: six documents giving field, indicator and subfield level mappings with processing
notes, thirteen procedures and five tables. It is field by field rather than approximate:
UNIMARC 210 `$c` becomes MARC21 260 `$b` and `$d` becomes `$c`, which is exactly what
`_marc_publisher` and `_marc_year` read; UNIMARC relator `070` becomes `aut`, which is
exactly what `_marc_author_entries` tests for.

It states its own limits, and they are quoted rather than summarised: "Although updated in
2001 for UNIMARC users, resources were not available for exhaustive review. Some UNIMARC or
MARC 21 elements may be missing from this specification." Its UNIMARC side is the UNIMARC
Manual, Bibliographic Format, 2nd edition, 1994, which is what dates it.

**It is the bibliographic crosswalk only.** Authority records are not in it and stay a
separate question, which matters because the author identity work will want them and will
not find them here.

**Thirteen of the sixteen datafield tags this tree reads have a source in it.** The three
without are `264`, which is RDA and postdates the MARC21 edition the crosswalk targets, and
which costs nothing because `_marc_publisher` and `_marc_year` read `260` as well; `655`,
genre, whose UNIMARC counterpart 608 appears nowhere in the document because it postdates
the 1994 edition; and `689`, the German networks' subject chain, which is not standard
MARC21 and which no UNIMARC record carries. Both real losses are subject headings, so a
converted record is thinner and never wrong.

**The shape is element to element, and the tempting shape is wrong.** `metadata._marc_fields`
produces `dict[str, list[_Subfields]]` and `marc._record` consumes one, so a transformation
between two such dicts looks like the whole job. It is not: that map is built from
`datafield` alone and carries **no leader, no control fields and no indicators**. Those are
load bearing at two different ends, and conflating them is what makes the dict look
sufficient.

**The leader and the control fields are load bearing on the output side.** Procedure 9
constructs the MARC21 leader and `008` from UNIMARC's coded fields and is the largest single
piece of the document, and the carrier door below reads both off the record node.

**The indicators are load bearing on the input side**, which is easy to miss because nothing
in this tree reads a MARC21 indicator: filing is handled by stripping the delimiters in
`_marc_text`, a subject's vocabulary comes from `$2`, and every `ind1` and `ind2` in the
backend is in `marc.py`'s writer. The crosswalk's rules are keyed on the **UNIMARC** record's
indicators all the same. Procedure 1 sets the MARC21 `100` first indicator from the UNIMARC
`700` second indicator, which is what says whether the entry element is a forename or a
surname. Nothing here reads it: `_flip_catalogue_name` guesses the same thing from the comma
count, and gets a direct order name carrying one comma wrong. A dict built from `datafield`
cannot express a rule keyed on something it discarded.

**The carrier door is the first thing such a path has to answer**, and it fails open rather
than closed. `_marc_carrier_is_book` reads the leader and the control fields off the record
node, by its own docstring, precisely because `_marc_fields` does not carry them. Executed on
a UNIMARC record with a UNIMARC leader and no `007` or `008`, it returns `True`, where the
same function correctly returns `False` for a MARC21 online resource. So a dict to dict
transform would admit every UNIMARC record as a physical book, including the electronic ones,
silently.

**None of it is built yet, and the reason is a count rather than an estimate.** No source
this build has answers UNIMARC. `targets.Reader` has seven members and none is UNIMARC,
`enums.CatalogueSource` has nine and none is, and the Z39.50 seam names the format while
`Target` refuses that transport outright, so no target carries it. The one catalogue ever
measured for UNIMARC answered MARC21 labelled MARC21. A reader for a format nothing sends is
a reader nothing can test. **Establish the format per source and not per country**: the
assumption that a country implies a format has been wrong three times already in this tree.

**Two more things will bite whoever builds it, and they are today's behaviour rather than
UNIMARC's.**

* **The ISBN, which is the importer's primary match key.** MARC21 `020 $b` is obsolete, so
  the crosswalk's processing note for UNIMARC 010 folds the qualification into `$a` in
  parentheses. `metadata._marc_isbn` parses `9783161484100`, `978-3-16-148410-0` and
  `9783161484100 :`, and returns nothing for `9783161484100 (pbk.)`. That divergence is
  already recorded on `marc._record`; what is new is that a UNIMARC path makes it the normal
  case rather than the occasional one, because `broché` and `relié` are what `$b` holds in
  the catalogues this would be built for.
* **Co-authors.** UNIMARC records the role in the tag, 701 for alternate and 702 for
  secondary intellectual responsibility. The crosswalk maps both to `700` and copies `$4`
  only where the source had one, so the role the tag carried is dropped with nothing put in
  its place. `_marc_author_entries` then keeps only the main entry, and the fallback that
  would have caught the rest does not run because the main entry made the credit line
  non-empty. That is a defect in the MARC21 reader today and is on the tracker as its own
  issue, not a UNIMARC one.

**And a licence consequence for whoever writes the tests.** USEMARCON's sample records are
covered by the licence above, so they cannot become fixtures here. A UNIMARC fixture in this
repository is hand written.

## ISNI is the identity spine, and VIAF is a discovery route

Owner's ruling, 2026-08-28, on #99. What says two spellings are one person is a stored
ISNI, and nothing else may.

**No internal author id is minted, because the schema already refuses one.** `books.author`
is free text, an author page is a `GROUP BY`, and neither identity table carries a foreign
key to an author because there is nothing to point at. The spelling is already the
identifier and is stable by construction, being derived from the books rather than
assigned.

**ISNI rather than VIAF, on measurement.** A cluster id is not a person: clusters split and
merge, and #87 measured `Stevenson, Robert Louis` resolving to four distinct personal
clusters. A spine built on one would offer a merge that changes with nothing in this
database having changed. ISNI is ISO 27729, minted per person and language neutral, and
that single property is the whole of why it was chosen.

**ISNI rather than the GND, though the GND is the entry point.** The GND is a national
file, so a spine built on it works for German language authors and thins out elsewhere,
which is the coverage gap the authority feature exists to close.

**A VIAF cluster id is still stored, and that is not a contradiction.** `author_identifiers`
holds cross references beside the confirmed record; the identity is the record a Member
confirmed. What the ruling forbids is a cluster id **deciding** who somebody is, and that is
now true by construction rather than by convention: `authors.IDENTITY_SPINE` is the one
place that names the scheme, and
`tests/test_authorship.py::TestOnlyTheSpineSaysTwoSpellingsAreOnePerson` asks every member
of `AuthorityScheme` in turn and fails if any but ISNI acquires the power.

**A shared ISNI suggests a merge and never performs one.** Folding on it would adjudicate at
write time, which is the one thing this feature refuses at both ends. The confirmation that
put the number there was a person saying which record an author is, not a person saying two
of their authors are the same. It joins `spelling`, `initials` and `fragment` as a fourth
suggestion rule, and it is the only one of the four that reaches a pen name, a
transliteration or a married name, because it is the only one that reads a stored fact
rather than the letters of a name.

**An author carrying two ISNIs contributes nothing.** That is a disagreement rather than an
identity, and keeping either value would be resolution by ordering, the call
`authority._viaf_sources` refuses for a code a cluster names twice. The disagreement is not
lost by being dropped: `AuthorOut.identifier_conflicts` reports it under its scheme.

**An author with no ISNI is the common case and is unaffected.** The spelling stays the key
and the same suggestions are offered. Confirmed rather than assumed, in
`TestAnAuthorWithNoSpine`.
